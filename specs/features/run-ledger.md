---
feature: run-ledger
status: implemented
last_updated: 2026-07-17
linear: [CAL-570, CAL-583, CAL-613, CAL-661, CAL-693, CAL-1002, CAL-1114]
---

# Run ledger — the SQLite audit trail

> The single source of truth for the run lifecycle: a `runs` row per run and an append-only `events` log, against which the close gate validates.

## Behaviour

Per-run state lives in SQLite at `.harness/harness.db` — one database per project. The `runs` / `events` tables **are** the whole audit trail; the [verbs](verb-model.md) (`start` / `review` / `close`) read and write the ledger through the connection helper, and `close` enforces its gate by querying it. Under the verb model the agent session — not a rehydrated state row — holds run context, so the ledger records *what happened*, it does not drive *what happens next* (decision D5, [`specs/architecture-principles.md`](../architecture-principles.md)).

### The verb-model run lifecycle

A run is `open` from `harness start`; it then reaches one of two **live** terminal states — `closed` when `harness close` passes its gate, or `cancelled` when `harness cancel` abandons it (a close-without-merge).

#### Scenario: the open→closed lifecycle

- GIVEN `harness start <ticket>` succeeds
- THEN it inserts a `runs` row with `status='open'`, `ticket`, `worktree_path`, `worktree_branch`, `base_branch`, and `started_at`
- WHEN `harness close` passes its gate
- THEN the same row flips to `status='closed'` and a terminal `close` event is appended — **both in one `BEGIN IMMEDIATE` transaction**: a failed event write rolls the status flip back, so a run can never land `closed` with no `close` event (an inconsistent ledger no retry can repair, since nothing re-drives a terminal run) (CAL-1002). This mirrors the shared abandon transaction the `cancel`/`reclaim` scenarios use.

#### Scenario: a cancelled run

- GIVEN an `open` run the agent abandons
- WHEN `harness cancel <run-id>` runs
- THEN it sets `status='cancelled'`, stamps `completed_at`, and emits a `workflow_failed` event with `reason='cancelled'` (it also reclaims legacy engine-era `running`/`pending` rows)

#### Scenario: a reclaimed run (orchestrator died mid-flight)

- GIVEN an `open` run whose orchestrating session died, leaving its ticket stuck *In Progress*
- WHEN `harness reclaim <run-id>` (or `--ticket <ID>`) runs
- THEN it first reverts the Linear ticket to **Todo** (+ a `reclaimed` label and comment), then reuses the `cancel` ledger transaction to set `status='cancelled'` + stamp `completed_at` + emit a `workflow_failed` event with `reason='reclaimed'` — clearing the `open` row so a fresh `harness start` is not blocked. The worktree/branch are **preserved**, not pruned (proposal [`stale-run-reclamation`](../proposals/stale-run-reclamation.md) D4). `cancel` and `reclaim` share one ledger-abandon transaction (`harness/cli/_abandon.py`); they differ only in the recorded `reason`.

#### Scenario: a reclaim reversed (a confirmed false positive)

- GIVEN a `cancelled` run whose `workflow_failed` event carries `reason='reclaimed'`, on a ticket reverted to Todo with the `reclaimed` label — and the reclamation is confirmed to have been wrong (the session was alive all along)
- WHEN `harness reclaim --undo <run-id>` (or `--ticket <ID>`) runs
- THEN it first restores the ticket — **In Progress**, the `reclaimed` label removed, a correcting comment posted — then flips `status='cancelled' → 'open'`, sets `completed_at` back to `NULL`, and **appends** a `reclaim_undone` event, both in one `BEGIN IMMEDIATE` transaction. The `workflow_failed` event is **not** deleted or rewritten: the ledger is append-only, so the trail shows the reclamation *and* its reversal. Consequence to read deliberately — `harness status` on a re-opened run reports `failure_reason='reclaimed'` (it reads the newest `workflow_failed`) while `status` reads `open`; the **row** is authoritative, the log is the history including the mistake. The `reclaim_undone` event is load-bearing a second time: being the restored run's newest ledger activity, it stops the next `--stale` sweep from immediately re-reclaiming the ticket just restored. The worktree needs no restoration — reclaim never pruned it (D4). Authority is bounded (proposal [`stale-run-reclamation`](../proposals/stale-run-reclamation.md) D5): only a run provably reclaim-cancelled can be undone, so a deliberate `harness cancel` is refused (`not_reclaimed`); and when the ticket already carries another `open` run — the duplicate-session shape the incident produced — the verb refuses (`ticket_has_open_run`) **before any tracker write** rather than arbitrating between two sessions. Tracker-first ordering mirrors `reclaim`: a failed restore leaves the row `cancelled`, so a retry still sees work to undo (#254).

#### Scenario: a deferred ticket (triage, not a build run)

- GIVEN the unattended Build routine picks a Todo ticket the `work-discovery` skill judges **not** wholly actionable
- WHEN `harness defer <ticket> --reason <text> [--needs decision|input|operator]` runs
- THEN it posts the reason as a comment on the ticket, **additively** applies the hold label (`--needs` selects it: `decision` — the default —, `input`, or `operator`; `issueAddLabel`, never a full-set replace), **assigns the ticket to the operator** (Linear `viewer`, the machine-readable "a human holds this" signal `work-discovery` skips), and records a `defer` event carrying the `needs` kind — anchored on its own terminal `runs` row (`workflow_name='defer'`, `status='closed'`, no worktree) because a defer has no build run and the `events` FK needs one. The `'closed'` status keeps the row clear of `idx_runs_ticket_open`, so a later `harness start` on the same ticket is never blocked (CAL-1143, CAL-1167). The three kinds partition held work by what kind of human input the ticket waits on — `decision` (a judgment call, clearable by answering), `input` (the operator must supply something the run cannot), `operator` (an interactive session; its meaning narrows now that `input` covers the "owes this ticket something" case) — `work-discovery` skips all three, and only the return path (`/decision`) distinguishes them (ADR 0006). A ticket not on the Build queue is refused with a structured `reason` before any write; a tracker-less repo is a clean no-op. The queue in force is nullable (#248): `repo.project` when configured, otherwise the backend's natural full queue — the seam answers membership through `fetch_queue_membership(identifier, *, project)`, so the verb never infers which backend it holds. The `project` the event records is the effective scope: the configured value when set, else the ticket's own project as the backend reports it, else `null`.

The partial unique index `idx_runs_ticket_open ON runs(ticket) WHERE status = 'open'` keeps at most one `open` run per ticket, so a concurrent `harness start` cannot insert a second open row (CAL-570).

The remaining statuses (`pending` / `running` / `completed` / `failed` / `stalled` / `paused`) belong to the **retired** deterministic engine (CAL-574) and survive only so historical rows validate. `RUN_STATUSES` / the `RunStatus` `Literal` in `harness/state/schema.py` enumerates both the verb-model statuses and the retired-engine ones, so a status read out of any `runs` row validates against one type-safe seam (CAL-583); the column itself is plain `TEXT` (no `CHECK`).

### The review verdict and its reviewed SHA live on an event, not a column

The gate's load-bearing datum — the SHA a passing review was bound to — is **not** a `runs` column. `harness review` appends a `review` event whose `data_json` carries `{ run_id, reviewed_sha, verdict, issues, engine, created_at }` (and optional `commit_message` / `deferred_brief`). `engine` records which review engine produced the verdict (`claude` | `codex`, CAL-701). When an explicit `--engine codex` run hits an exhausted tier, the verb falls back once to Claude (CAL-702): `engine` then reads `claude` and an optional `fallback_from: "codex"` records the substitution, so the gate stays *available* without the fallback ever being silent.

Each event payload's shape is a **typed contract** in [`harness/events/payloads.py`](../../harness/events/payloads.py) (CAL-1012) — `ReviewEventData`, `CheckpointEventData`, `WorkflowFailedEventData`, `CloseEventData`, `DeferEventData`, `DesignEventData`, `ReleaseEventData`. The emitting verb builds the model (field names checked statically); a reader imports the field-derived constant from that one module rather than spelling the key itself. The constant's **shape follows its consumer** (#217): a `*_PATH` constant is the `$.<field>` form for a reader that `json_extract`s in SQL (the close gate's `$.reviewed_sha` / `$.verdict` are `REVIEW_REVIEWED_SHA_PATH` / `REVIEW_VERDICT_PATH`, passed as bound parameters); a `*_KEY` constant is the bare field name for a reader that indexes an already-parsed payload `dict` (`harness status`'s `WORKFLOW_FAILED_REASON_KEY`, the design gate's `DESIGN_STATUS_KEY` / `DESIGN_HASH_KEY`). So a key rename breaks at the model/constant level rather than silently degrading the gate to `no_passing_review` — or, for the design linkage, silently dropping the design context from every review.

#### Scenario: the close gate query

- GIVEN a run with one or more `review` events
- WHEN `harness close` checks the gate
- THEN it queries for a `review` event with `verdict='pass'` whose `reviewed_sha` equals the worktree's current HEAD:

```sql
SELECT json_extract(data_json, '$.reviewed_sha')
FROM events
WHERE run_id = ? AND event_type = 'review'
  AND json_extract(data_json, '$.verdict') = 'pass';
```

Storing the reviewed SHA on the append-only event (rather than mutating a `runs` column) keeps the full review history auditable and is why decision D2 needed no schema migration — the `events` table already holds arbitrary JSON. `start` emits **no** event (the open run *is* the `runs` row); so the audit trail is the `runs` row **plus** its events, not the events alone.

### The promotion ledger — a sibling table (CAL-1114)

The [promotion lifecycle](cli-surface.md#the-promotion-lifecycle-group) ([ADR 0003](../decisions/0003-promotion-lifecycle.md)) records its state in a **sibling `promotions` table** in the same per-project `.harness/harness.db`, owned by `harness/state/promotions.py`. It is deliberately separate from `runs`/`events`: `close` gates a ticket's integration into `dev`, promotion gates branch movement toward release, and the two lifecycles must not weaken each other — so a promotion is not a `runs` row. Each promotion is a `Promotion` (Pydantic, `extra="forbid"`) stored as a JSON blob keyed by `promotion_id`, with a denormalized `status` column for querying; it reads back by promotion id so an outer orchestrator can pause after the harness classifies a merge+gate attempt and resume by re-reading the state it left. The `Promotion` model carries the branch endpoints and promotion branch, the lifecycle `status` (`opened` / `pr_ready` / `agent_may_fix` / `needs_ticket` / `blocked` / `promoted` / `pr_opened` / `escalated` / `cancelled`), the `gated_sha` the PR gate reads, the bounded repair `attempts` count, the terminal `pr_url` / `escalation_ticket`, and a bounded `evidence` reference. The two hops have **distinct** terminal successes (CAL-1158): the staging hop lands the candidate on the target and is done (`promoted`), while the release hop's success is an open PR a human still merges (`pr_opened`) — collapsing them would record "a PR was opened" for a promotion that opened none, which is the kind of rounding-off an audit trail cannot do. The **PR gate** (`pr_gate_satisfied`) passes only for a `pr_ready` promotion carrying a gated SHA — the same evidence discipline this run ledger's review→close gate enforces, applied to release movement. The table is created lazily on first write; a read that predates any write returns `None`. The subcommands that surface it are in [cli-surface.md](cli-surface.md#the-promotion-lifecycle-group).

## Data model

Two tables in `.harness/harness.db`, created idempotently by `init_db()` (`IF NOT EXISTS`). Every connection opened via the helper sets WAL journal mode and `PRAGMA foreign_keys = ON`.

| Table | Key columns | Purpose |
|---|---|---|
| `runs` | `run_id` (PK, ULID), `status`, `ticket`, `worktree_path`, `worktree_branch`, `base_branch`, `started_at`, `completed_at` | One row per run; the open/closed lifecycle |
| `events` | `id` (PK), `run_id` (FK, `ON DELETE CASCADE`), `event_type`, `timestamp`, `data_json` | Append-only log; carries the live `review` / `close` / `workflow_failed` / `checkpoint` events |

The canonical `event_type` set is whatever `EventType` in `harness/events/schema.py` enumerates — that `Literal` is the source of truth, and `EVENT_TYPES` derives from it so the two cannot drift (`test_event_emitter.py` asserts the derived set equals the tested one, so a new type cannot be added without the round-trip test seeing it). One writable type per live emitter: `workflow_failed` (`harness cancel`, and `reclaim`'s reuse of the same abandon transaction), `review`, `close`, `checkpoint` (the run-branch push that makes WIP durable, CAL-738), `defer` (the audited triage write, CAL-1143), `release` (the `/decision` return write, #193), `design` (the design stage's recorded attempt, ADR 0007 / #211), and `reclaim_undone` (a reclaim reversed as a confirmed false positive, #254). CAL-713 pruned the 16 retired deterministic-engine types (CAL-574) out of the writable set; the emitter validates them out, but historical rows that carry them read back unchanged (readers never re-validate `event_type`).

New `runs` columns are added via idempotent `ALTER TABLE ... ADD COLUMN` migrations in `_migrate()`. The `pid` column is vestigial (the engine-era SIGTERM `cancel` path was removed in CAL-587; always `NULL`) — declared in the base `_SCHEMA` and kept as a dormant column; CAL-713 removed its redundant `ADD COLUMN` migration (a writer-less column needs none). `runs.state_json` survives as `"{}"` for verb-model rows but is no longer merged or snapshotted (the engine-era state machinery and the never-shipped resume snapshot layer were removed in CAL-613; the `BaseState` model that once described `state_json` was deleted in CAL-1107). The full DDL and the migration table are the **schema reference** below.

## Interface surface

`store.py` exposes only the connection helper, the schema, and the migrations — the verbs own the reads and writes. `connect(db_path)` is an `@asynccontextmanager` (`async with connect(path) as conn`) that opens an `aiosqlite` connection, sets WAL and foreign keys, yields, and closes on exit. `DEFAULT_DB_PATH = Path(".harness/harness.db")`. The ledger is surfaced read-only through `harness status` / `harness events` / `harness runs` (see [cli-surface.md](cli-surface.md)).

## Schema reference

The full SQLite schema, migrations, and status values — `harness/state/store.py` owns the connection helper, the schema, and the idempotent migrations; the verbs (`start` / `review` / `close`) read and write the ledger through `connect()`. (Folded here from the former `specs/state-store.md` in CAL-693 so the feature spec is the sole as-built record.)

> The engine-era per-node state machinery (`read_state` / `update_state` / `restore_state`) and the never-shipped v2-resume snapshot layer (`write_snapshot` / `read_latest_snapshot` + the `run_snapshots` table) were removed in CAL-613: they had no production caller after the deterministic engine was retired (CAL-574). Under the verb model the agent session — not a rehydrated state row — holds run context. The `runs.state_json` column survives (written as `"{}"` by `harness start`, surfaced as `state` in `harness status --json`) but is no longer merged or snapshotted.

### SQLite DDL

Two tables in `.harness/harness.db`:

```sql
CREATE TABLE runs (
  run_id              TEXT PRIMARY KEY,
  workflow_name       TEXT NOT NULL,
  workflow_version    INTEGER NOT NULL,
  status              TEXT NOT NULL,  -- open|closed (verb lifecycle) | pending|running|completed|failed|cancelled|stalled|paused (legacy engine)
  state_json          TEXT NOT NULL,
  inputs_json         TEXT NOT NULL,
  base_branch         TEXT,
  worktree_branch     TEXT,
  worktree_path       TEXT,           -- absolute path to the git worktree (set by harness start)
  ticket              TEXT,           -- Linear ticket identifier, e.g. "CAL-570" (set by harness start)
  exit_code           INTEGER,
  started_at          TEXT NOT NULL,
  completed_at        TEXT,
  duration_ms         INTEGER,
  pid                 INTEGER   -- vestigial; always NULL (engine-era SIGTERM cancel removed in CAL-587). Dormant base-schema column — no migration (CAL-713)
);

CREATE TABLE events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id      TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  node_id     TEXT,
  event_type  TEXT NOT NULL,
  timestamp   TEXT NOT NULL,
  duration_ms INTEGER,
  data_json   TEXT NOT NULL DEFAULT '{}'
);

-- Partial unique index: prevents two concurrent `harness start` calls from
-- inserting duplicate open rows for the same ticket (CAL-570).
CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_ticket_open
  ON runs(ticket) WHERE status = 'open';
```

WAL journal mode and `PRAGMA foreign_keys = ON` are set on every connection opened via `connect()`. `init_db()` creates all tables and indexes idempotently (`IF NOT EXISTS`).

### `runs` column additions (migrations)

New columns added after the initial schema are applied via `ALTER TABLE ... ADD COLUMN` in `_migrate()`. Each migration is idempotent.

| Column | Type | Added by | Description |
|---|---|---|---|
| `ticket` | `TEXT` | CAL-570 | Linear ticket identifier (e.g. `CAL-570`) for runs opened via `harness start`. |
| `worktree_path` | `TEXT` | CAL-570 | Absolute filesystem path to the git worktree; set by `harness start`. |

> The `pid` column is **not** in this table: it is declared in the base `_SCHEMA` CREATE TABLE (a dormant, writer-less column — see above) and its redundant `ADD COLUMN` migration was removed in CAL-713.

### `status` values

Under the **verb model** (proposal [`harness-as-tool`](../proposals/harness-as-tool.md)) a run has three **live** statuses: `open` (from `harness start`) and its two terminal states — `closed` (`harness close` passed its gate) and `cancelled` (`harness cancel` abandoned it). The remaining statuses (`pending` / `running` / `completed` / `failed` / `stalled` / `paused`) belong to the legacy deterministic engine (retired in CAL-574) and survive only so historical rows validate.

| Value | Set by | Meaning |
|---|---|---|
| `open` | `harness start` | **Live.** Run initialised; ticket transitioned to In Progress and worktree created. The verb run is in progress (implement → review → close). The partial unique index `idx_runs_ticket_open` keeps at most one `open` run per ticket. |
| `closed` | `harness close` | **Live.** Gate passed (a `verdict=pass` whose reviewed SHA == HEAD); branch merged + pushed, ticket transitioned to Done, run finalised. Terminal state of the verb lifecycle. |
| `cancelled` | `harness cancel` | **Live.** Run abandoned (close-without-merge). The verb marks the in-flight run cancelled, stamps `completed_at`, and emits a `workflow_failed` event with `reason='cancelled'`. It also abandons legacy `running`/`pending` rows historical engine-era runs left behind. |
| `pending` | `harness run` (legacy) | Workflow accepted; executor not yet started. |
| `running` | engine (legacy) | At least one node has started. |
| `completed` | engine (legacy) | All nodes completed successfully. |
| `failed` | engine (legacy) | A node or workflow-level error terminated the run. |
| `stalled` | engine (legacy) | No progress within the stall timeout. |
| `paused` | engine (v2, legacy) | Run awaiting a decision. |

The `RunStatus` `Literal` / `RUN_STATUSES` frozenset in `harness/state/schema.py` enumerates all of the above — both the live verb-model statuses (`open` / `closed` / `cancelled`) and the retired-engine statuses — so a status read out of a `runs` row written by `harness start`/`close`/`cancel` validates against the type-safe seam (CAL-583, which closed the type drift the verb model had introduced). The `runs.status` column is still plain `TEXT` (no `CHECK`); `RUN_STATUSES` is the validation seam readers use.

### `BaseState` (removed)

`harness/state/schema.py` once carried `BaseState`, the engine-era pydantic model of the run-state shape (`run_id`, `workflow_name`, `base_branch`, `worktree_path` / `worktree_branch`, `artifacts_dir`, `started_at`, `notes`). CAL-574 retired the workflow engine that derived per-workflow state on top of it, leaving the model with **no production importer** — nothing validated `state_json` against it — so CAL-1107 deleted it. The persisted run shape is now the `runs` table schema above; `state_json` survives as an always-`"{}"` blob no model validates. `harness/state/schema.py` now owns only the `RunStatus` / `RUN_STATUSES` vocabulary.

Run statuses are typed as `RunStatus = Literal["open", "closed", "pending", "running", "completed", "failed", "cancelled", "stalled", "paused"]` — the live verb-model statuses (`open` / `closed` / `cancelled`) interleaved with the retired-engine statuses (see the status table above).

## Known limitations

- WAL mode permits concurrent reads (`harness status` while a run is in progress) but the DB is single-writer; the verbs serialise lifecycle writes.
- Retired-engine columns (`workflow_name`, `workflow_version`, `state_json`, `inputs_json`, `pid`) are retained as dormant columns to avoid a destructive migration on existing DBs; they carry no live meaning under the verb model.

## Decisions

D5 (all run-lifecycle state goes through the ledger so the close gate can validate against it) and D2 (the reviewed SHA recorded on the review event) are recorded in [`specs/architecture-principles.md`](../architecture-principles.md) and referenced here.

## Cross-references

- [verb-model.md](verb-model.md) — the verbs that read and write the ledger
- [cli-surface.md](cli-surface.md) — the read-only ledger inspection commands
