---
feature: run-ledger
status: implemented
last_updated: 2026-06-14
linear: [CAL-570, CAL-583, CAL-613, CAL-661]
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
- THEN the same row flips to `status='closed'` and a terminal `close` event is appended

#### Scenario: a cancelled run

- GIVEN an `open` run the agent abandons
- WHEN `harness cancel <run-id>` runs
- THEN it sets `status='cancelled'`, stamps `completed_at`, and emits a `workflow_failed` event with `reason='cancelled'` (it also reclaims legacy engine-era `running`/`pending` rows)

The partial unique index `idx_runs_ticket_open ON runs(ticket) WHERE status = 'open'` keeps at most one `open` run per ticket, so a concurrent `harness start` cannot insert a second open row (CAL-570).

The remaining statuses (`pending` / `running` / `completed` / `failed` / `stalled` / `paused`) belong to the **retired** deterministic engine (CAL-574) and survive only so historical rows validate. `RUN_STATUSES` / the `RunStatus` `Literal` in `harness/state/schema.py` enumerates both the verb-model statuses and the retired-engine ones, so a status read out of any `runs` row validates against one type-safe seam (CAL-583); the column itself is plain `TEXT` (no `CHECK`).

### The review verdict and its reviewed SHA live on an event, not a column

The gate's load-bearing datum — the SHA a passing review was bound to — is **not** a `runs` column. `harness review` appends a `review` event whose `data_json` carries `{ run_id, reviewed_sha, verdict, issues, created_at }` (and optional `commit_message` / `deferred_brief`).

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
| `events` | `id` (PK), `run_id` (FK, `ON DELETE CASCADE`), `event_type`, `timestamp`, `data_json` | Append-only log; carries the `review` and `close` events |

New `runs` columns are added via idempotent `ALTER TABLE ... ADD COLUMN` migrations in `_migrate()`. The `pid` column is vestigial (the engine-era SIGTERM `cancel` path was removed in CAL-587; always `NULL`); `runs.state_json` survives as `"{}"` for verb-model rows but is no longer merged or snapshotted (the engine-era state machinery and the never-shipped resume snapshot layer were removed in CAL-613). The full DDL, the migration table, and the `BaseState` model are the **schema reference** in [`specs/state-store.md`](../state-store.md).

## Interface surface

`store.py` exposes only the connection helper, the schema, and the migrations — the verbs own the reads and writes. `connect(db_path)` is an `@asynccontextmanager` (`async with connect(path) as conn`) that opens an `aiosqlite` connection, sets WAL and foreign keys, yields, and closes on exit. `DEFAULT_DB_PATH = Path(".harness/harness.db")`. The ledger is surfaced read-only through `harness status` / `harness events` / `harness runs` (see [cli-surface.md](cli-surface.md)).

## Known limitations

- WAL mode permits concurrent reads (`harness status` while a run is in progress) but the DB is single-writer; the verbs serialise lifecycle writes.
- Retired-engine columns (`workflow_name`, `workflow_version`, `state_json`, `inputs_json`, `pid`) are retained as dormant columns to avoid a destructive migration on existing DBs; they carry no live meaning under the verb model.

## Decisions

D5 (all run-lifecycle state goes through the ledger so the close gate can validate against it) and D2 (the reviewed SHA recorded on the review event) are recorded in [`specs/architecture-principles.md`](../architecture-principles.md) and referenced here.

## Cross-references

- [`specs/state-store.md`](../state-store.md) — the full SQLite DDL, migrations, and `BaseState` schema reference
- [verb-model.md](verb-model.md) — the verbs that read and write the ledger
- [cli-surface.md](cli-surface.md) — the read-only ledger inspection commands
