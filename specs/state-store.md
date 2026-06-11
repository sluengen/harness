# State Store — SQLite schema, BaseState, state merge, snapshots

Per-run state lives in SQLite as a JSON blob on the `runs` row. Writes are validated, merged, and snapshotted through a set of free functions in `harness/state/store.py`.

---

## Purpose

Provides the single source of truth for run state. All state mutations go through `update_state`; direct mutation of the `state_json` column from outside this module is forbidden. The store also manages a per-completion snapshot table for the v2 resume path.

---

## SQLite schema

Three tables in `.harness/harness.db`:

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
  pid                 INTEGER   -- PID of the owning harness process; updated on resume (H-2-006)
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

CREATE TABLE run_snapshots (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id      TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  node_id     TEXT NOT NULL,
  seq         INTEGER NOT NULL,
  state_json  TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  UNIQUE (run_id, seq)
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
| `pid` | `INTEGER` | H-2-006 | Vestigial. Once held the owning process PID for the engine-era SIGTERM `harness cancel`; that path was removed in CAL-587, so `harness start` no longer writes it (always `NULL`). Retained as a dormant column to avoid a destructive migration on existing DBs. |
| `ticket` | `TEXT` | CAL-570 | Linear ticket identifier (e.g. `CAL-570`) for runs opened via `harness start`. |
| `worktree_path` | `TEXT` | CAL-570 | Absolute filesystem path to the git worktree; set by `harness start`. |

### `status` values

The run lifecycle under the **verb model** (proposal [`harness-as-tool`](proposals/harness-as-tool.md)) is just two states: a run is `open` from `harness start` until `harness close` flips it to `closed`. The remaining statuses below belong to the legacy deterministic engine (retired in CAL-574) and are documented for historical rows.

| Value | Set by | Meaning |
|---|---|---|
| `open` | `harness start` | Run initialised; ticket transitioned to In Progress and worktree created. The verb run is in progress (implement → review → close). The partial unique index `idx_runs_ticket_open` keeps at most one `open` run per ticket. |
| `closed` | `harness close` | Gate passed (a `verdict=pass` whose reviewed SHA == HEAD); branch merged + pushed, ticket transitioned to Done, run finalised. Terminal state of the verb lifecycle. |
| `pending` | `harness run` (legacy) | Workflow accepted; executor not yet started. |
| `running` | engine (legacy) | At least one node has started. |
| `completed` | engine (legacy) | All nodes completed successfully. |
| `failed` | engine (legacy) | A node or workflow-level error terminated the run. |
| `cancelled` | `harness cancel` | Run abandoned (close-without-merge). The verb marks the in-flight run cancelled, stamps `completed_at`, and emits a `workflow_failed` event with `reason='cancelled'`. Also set by the intake reconciler (`intake.cancel_run`) for legacy `running`/`pending` rows. |
| `stalled` | engine (legacy) | No progress within the stall timeout. |
| `paused` | engine (v2, legacy) | Run awaiting a decision. |

The `RunStatus` `Literal` / `RUN_STATUSES` frozenset in `harness/state/schema.py` enumerates all of the above — both the verb-model statuses (`open`/`closed`) and the retired-engine statuses — so a status read out of a `runs` row written by `harness start`/`close` validates against the type-safe seam (CAL-583, which closed the type drift the verb model had introduced). The `runs.status` column is still plain `TEXT` (no `CHECK`); `RUN_STATUSES` is the validation seam readers use.

### Review verdict and the reviewed SHA (verb model)

The review gate's load-bearing datum — the **SHA a passing review was bound to** — is **not** a `runs` column. `harness review` appends a `review` event to the `events` table whose `data_json` carries `{ run_id, reviewed_sha, verdict, issues, created_at }` (and optional `commit_message` / `deferred_brief`). `harness close` enforces the gate by querying for a `review` event with `verdict='pass'` whose `reviewed_sha` equals the worktree's current HEAD:

```sql
SELECT json_extract(data_json, '$.reviewed_sha')
FROM events
WHERE run_id = ? AND event_type = 'review'
  AND json_extract(data_json, '$.verdict') = 'pass';
```

Storing the reviewed SHA on the append-only event (rather than mutating a `runs` column) keeps the full review history auditable and is why no schema migration was needed to support D2 — the `events` table already holds arbitrary JSON. `close` then emits a terminal `close` event carrying `{ run_id, ticket, merged_sha, closed_at }`.

---

## `BaseState`

Framework-defined fields prepended to every derived state class:

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

`extra="forbid"` means an agent that hallucinates an unknown field is rejected at validation time. The per-workflow derived class subclasses `BaseState` and adds one field per name in the workflow's `writes:` declarations, defaulting scalars to `None` and lists to `[]`.

Run statuses are typed as `RunStatus = Literal["open", "closed", "pending", "running", "completed", "failed", "cancelled", "stalled", "paused"]` — the verb-model statuses (`open`/`closed`) followed by the retired-engine statuses (see the status table above).

---

## State merge rules

`update_state` applies type-driven merge per field:

| Field annotation | Merge behaviour |
|---|---|
| `list[...]` | Append: incoming list is extended onto the existing list |
| Scalar (`str`, `int`, `bool`, `float`, Pydantic model, `Literal`) | Overwrite: last writer wins |
| `dict[...]` | Rejected (`StateStoreError`): dict-merge semantics deferred to v1.5 |
| Unknown field | Rejected (`StateStoreError`) |

Per-write overrides: `merge_overrides` maps field name to `"replace"`, which forces unconditional overwrite regardless of field type. Used by steps with `{field: name, merge: replace}` in their `writes:` list.

The full read-modify-write happens inside a single `BEGIN IMMEDIATE` transaction so concurrent writers serialise at SQLite's write-lock layer.

### Notes bounding

The `notes` field is the only list subject to automatic caps:
- Entry count cap: max 100 entries; oldest dropped first.
- Character budget cap: max 50,000 characters total; oldest entries dropped until under budget.

Both caps run on every write. Other workflow-declared list fields append without caps.

---

## Snapshots

After each node completes successfully, the executor calls `write_snapshot(run_id, node_id, state)`. This appends a row to `run_snapshots` with the full `state_json` at that point. `seq` is computed as `MAX(seq) + 1` inside a `BEGIN IMMEDIATE` transaction.

`read_latest_snapshot(run_id, schema)` returns the state at the highest-`seq` row, or `None` if no snapshots exist yet. The v2 resume machinery reads this instead of the mutable `runs.state_json` column.

---

## Connection helper

`connect(db_path)` is an `@asynccontextmanager` that opens an `aiosqlite` connection, sets WAL and foreign keys, yields the connection, and closes it on exit. All callers use it as `async with connect(path) as conn`.

`DEFAULT_DB_PATH = Path(".harness/harness.db")` is the single-DB-per-project default.

---

## Notable constraints

- No-op writes (empty `fields` dict) return the current state without touching the DB or emitting an event.
- `update_state` emits a `state_changed` event on success (unless `emit_event=False`). The event carries only `{"fields": [<changed names>]}`, not the full new state.
- Dict fields are explicitly rejected. Any attempt to write a `dict`-annotated field raises `StateStoreError` immediately.
- `restore_state(run_id, state)` performs a verbatim overwrite of `runs.state_json` without any merge. It is the only sanctioned path for resume operations that must restore an exact snapshot. Like `update_state`, it is the sole place where direct SQL against `state_json` is permitted.
