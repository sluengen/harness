---
feature: run-ledger
status: implemented
last_updated: 2026-07-06
linear: [CAL-570, CAL-583, CAL-613, CAL-661, CAL-693, CAL-1002]
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

The partial unique index `idx_runs_ticket_open ON runs(ticket) WHERE status = 'open'` keeps at most one `open` run per ticket, so a concurrent `harness start` cannot insert a second open row (CAL-570).

The remaining statuses (`pending` / `running` / `completed` / `failed` / `stalled` / `paused`) belong to the **retired** deterministic engine (CAL-574) and survive only so historical rows validate. `RUN_STATUSES` / the `RunStatus` `Literal` in `harness/state/schema.py` enumerates both the verb-model statuses and the retired-engine ones, so a status read out of any `runs` row validates against one type-safe seam (CAL-583); the column itself is plain `TEXT` (no `CHECK`).

### The review verdict and its reviewed SHA live on an event, not a column

The gate's load-bearing datum — the SHA a passing review was bound to — is **not** a `runs` column. `harness review` appends a `review` event whose `data_json` carries `{ run_id, reviewed_sha, verdict, issues, engine, created_at }` (and optional `commit_message` / `deferred_brief`). `engine` records which review engine produced the verdict (`claude` | `codex`, CAL-701). When an explicit `--engine codex` run hits an exhausted tier, the verb falls back once to Claude (CAL-702): `engine` then reads `claude` and an optional `fallback_from: "codex"` records the substitution, so the gate stays *available* without the fallback ever being silent.

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

## Data model

Two tables in `.harness/harness.db`, created idempotently by `init_db()` (`IF NOT EXISTS`). Every connection opened via the helper sets WAL journal mode and `PRAGMA foreign_keys = ON`.

| Table | Key columns | Purpose |
|---|---|---|
| `runs` | `run_id` (PK, ULID), `status`, `ticket`, `worktree_path`, `worktree_branch`, `base_branch`, `started_at`, `completed_at` | One row per run; the open/closed lifecycle |
| `events` | `id` (PK), `run_id` (FK, `ON DELETE CASCADE`), `event_type`, `timestamp`, `data_json` | Append-only log; carries the live `review` / `close` / `workflow_failed` / `checkpoint` events |

The canonical `event_type` set (`harness/events/schema.py`) is the four live-emitter types — `workflow_failed` (`harness cancel`), `review`, `close`, and `checkpoint` (`harness checkpoint` — the run-branch push that makes WIP durable, CAL-738). CAL-713 pruned the 16 retired deterministic-engine types (CAL-574) out of the writable set; the emitter validates them out, but historical rows that carry them read back unchanged (readers never re-validate `event_type`).

New `runs` columns are added via idempotent `ALTER TABLE ... ADD COLUMN` migrations in `_migrate()`. The `pid` column is vestigial (the engine-era SIGTERM `cancel` path was removed in CAL-587; always `NULL`) — declared in the base `_SCHEMA` and kept as a dormant column; CAL-713 removed its redundant `ADD COLUMN` migration (a writer-less column needs none). `runs.state_json` survives as `"{}"` for verb-model rows but is no longer merged or snapshotted (the engine-era state machinery and the never-shipped resume snapshot layer were removed in CAL-613). The full DDL, the migration table, and the `BaseState` model are the **schema reference** below.

## Interface surface

`store.py` exposes only the connection helper, the schema, and the migrations — the verbs own the reads and writes. `connect(db_path)` is an `@asynccontextmanager` (`async with connect(path) as conn`) that opens an `aiosqlite` connection, sets WAL and foreign keys, yields, and closes on exit. `DEFAULT_DB_PATH = Path(".harness/harness.db")`. The ledger is surfaced read-only through `harness status` / `harness events` / `harness runs` (see [cli-surface.md](cli-surface.md)).

## Schema reference

The full SQLite schema, migrations, status values, and the `BaseState` model — `harness/state/store.py` owns the connection helper, the schema, and the idempotent migrations; the verbs (`start` / `review` / `close`) read and write the ledger through `connect()`. (Folded here from the former `specs/state-store.md` in CAL-693 so the feature spec is the sole as-built record.)

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

### `BaseState`

Framework-defined fields prepended to every derived state class (largely vestigial under the verb model — no per-workflow state is derived; the agent session holds context):

```python
class BaseState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    workflow_name: str
    base_branch: str
    worktree_path: Path | None = None
    worktree_branch: str | None = None
    artifacts_dir: Path
    started_at: datetime
    notes: list[str] = Field(default_factory=list)
```

`extra="forbid"` means an agent that hallucinates an unknown field is rejected at validation time. Run statuses are typed as `RunStatus = Literal["open", "closed", "pending", "running", "completed", "failed", "cancelled", "stalled", "paused"]` — the live verb-model statuses (`open` / `closed` / `cancelled`) interleaved with the retired-engine statuses (see the status table above).

## Known limitations

- WAL mode permits concurrent reads (`harness status` while a run is in progress) but the DB is single-writer; the verbs serialise lifecycle writes.
- Retired-engine columns (`workflow_name`, `workflow_version`, `state_json`, `inputs_json`, `pid`) are retained as dormant columns to avoid a destructive migration on existing DBs; they carry no live meaning under the verb model.

## Decisions

D5 (all run-lifecycle state goes through the ledger so the close gate can validate against it) and D2 (the reviewed SHA recorded on the review event) are recorded in [`specs/architecture-principles.md`](../architecture-principles.md) and referenced here.

## Cross-references

- [verb-model.md](verb-model.md) — the verbs that read and write the ledger
- [cli-surface.md](cli-surface.md) — the read-only ledger inspection commands
