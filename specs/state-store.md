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
  status              TEXT NOT NULL,  -- pending|running|completed|failed|cancelled|stalled|paused
  state_json          TEXT NOT NULL,
  inputs_json         TEXT NOT NULL,
  base_branch         TEXT,
  worktree_branch     TEXT,
  exit_code           INTEGER,
  started_at          TEXT NOT NULL,
  completed_at        TEXT,
  duration_ms         INTEGER
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
```

WAL journal mode and `PRAGMA foreign_keys = ON` are set on every connection opened via `connect()`. `init_db()` creates all tables and indexes idempotently (`IF NOT EXISTS`).

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

Run statuses are typed as `RunStatus = Literal["pending", "running", "completed", "failed", "cancelled", "stalled", "paused"]`.

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
