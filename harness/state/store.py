"""SQLite state store — see SPEC §4.8, §7, §12.

Single database per project at ``$workspace/.harness/harness.db``. WAL journal
mode for concurrent reads. Foreign keys ON so events cascade-delete with their
run.

H-003 supplied :func:`connect` and :func:`init_db`. H-010 layers
:func:`read_state` and :func:`update_state` on top of that foundation.
H-2-001 adds :func:`write_snapshot` and :func:`read_latest_snapshot` for
per-completion state snapshot history (foundation for v2 resume).

State writes go through :func:`update_state` only. The function:

1. Validates incoming field names against the supplied derived schema
   (rejects unknown fields).
2. Loads the current ``state_json``, validates it, applies type-driven
   merge per SPEC §7 (list = append, scalar = overwrite, dict =
   reject — deferred to v1.5), re-validates the result, and writes it
   back inside a single transaction.
3. Caps the framework ``notes`` list at :data:`NOTES_MAX_ENTRIES`
   entries / :data:`NOTES_MAX_CHARS` characters, dropping oldest first.
   Bounding is **scoped to ``notes`` only** — the spec calls out the
   notes auto-capture as the unbounded growth risk; other workflow-
   declared list fields append without caps so a future overflow
   surfaces clearly rather than getting silently truncated.
4. Emits a ``state_changed`` event on success unless the caller opts
   out via ``emit_event=False``.

After each node completes the executor calls :func:`write_snapshot`,
which appends an immutable snapshot row to ``run_snapshots`` keyed by
``run_id`` + an auto-incrementing ``seq``. The v2 resume machinery reads
the highest-``seq`` row via :func:`read_latest_snapshot` to rehydrate
state without relying on the mutable ``runs.state_json`` column.

Module-level functions (rather than a ``StateStore`` class) match the
existing style — H-003 defined :func:`connect` / :func:`init_db` as
free functions and the single-db-per-project model means there's no
state worth bundling on an instance.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar, get_origin

import aiosqlite
from pydantic import ValidationError

from harness.state.schema import BaseState

DEFAULT_DB_PATH = Path(".harness/harness.db")

# Caps for the framework `notes` list. SPEC §7 bounding strategy.
# Applied only to `notes` — see module docstring for the rationale.
NOTES_MAX_ENTRIES = 100
NOTES_MAX_CHARS = 50_000

S = TypeVar("S", bound=BaseState)


class StateStoreError(Exception):
    """Raised when a read or write violates the schema or merge rules.

    Wraps Pydantic :class:`ValidationError` and surfaces unknown-field /
    dict-write rejects so callers see one error type at the boundary.
    """


# Schema per SPEC §12. Idempotent — every CREATE uses ``IF NOT EXISTS``. Re-running
# this script on an existing DB is a no-op.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id              TEXT PRIMARY KEY,
  workflow_name       TEXT NOT NULL,
  workflow_version    INTEGER NOT NULL,
  status              TEXT NOT NULL,
  state_json          TEXT NOT NULL,
  inputs_json         TEXT NOT NULL,
  base_branch         TEXT,
  worktree_branch     TEXT,
  exit_code           INTEGER,
  started_at          TEXT NOT NULL,
  completed_at        TEXT,
  duration_ms         INTEGER,
  pid                 INTEGER
);

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_workflow ON runs(workflow_name);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at);

CREATE TABLE IF NOT EXISTS events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id      TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  node_id     TEXT,
  event_type  TEXT NOT NULL,
  timestamp   TEXT NOT NULL,
  duration_ms INTEGER,
  data_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_run_node ON events(run_id, node_id);

CREATE TABLE IF NOT EXISTS run_snapshots (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id      TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  node_id     TEXT NOT NULL,
  seq         INTEGER NOT NULL,
  state_json  TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  UNIQUE (run_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_run ON run_snapshots(run_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_run_seq ON run_snapshots(run_id, seq);
"""


@asynccontextmanager
async def connect(
    db_path: Path = DEFAULT_DB_PATH,
) -> AsyncIterator[aiosqlite.Connection]:
    """Open an aiosqlite connection with WAL + foreign keys enabled.

    Use as ``async with store.connect(path) as conn:`` — the connection closes
    automatically on exit. PRAGMAs are set inside the context so every caller
    gets a connection in the documented mode.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    finally:
        await conn.close()


async def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Create tables and indexes if they don't exist. Idempotent."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.executescript(_SCHEMA)
        await conn.commit()
    await _migrate(db_path)


async def _migrate(db_path: Path) -> None:
    """Apply incremental column additions that cannot be expressed in ``_SCHEMA``.

    ``CREATE TABLE IF NOT EXISTS`` leaves existing tables untouched, so new
    columns added to ``_SCHEMA`` after the initial creation must be applied
    as ``ALTER TABLE ... ADD COLUMN`` migrations here.  Each migration is
    idempotent: the ``OperationalError`` raised when a column already exists
    is silently swallowed.

    H-2-006: ``runs.pid INTEGER`` — process ID of the harness run process,
        used by ``harness cancel <run-id>`` to deliver SIGTERM.
    CAL-570: ``runs.ticket TEXT`` — Linear ticket identifier (e.g. ``CAL-570``)
        for runs opened via ``harness start``.
    CAL-570: ``runs.worktree_path TEXT`` — filesystem path of the worktree
        created by ``harness start`` (mirrors the ``worktree_path`` state field
        but stored at the row level for observability without parsing state_json).
    CAL-570: ``idx_runs_ticket_open`` partial unique index on ``(ticket)``
        WHERE ``status='open'`` — prevents two concurrent ``harness start``
        calls from inserting duplicate open rows for the same ticket.
    """
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA foreign_keys = ON")
        for ddl in (
            "ALTER TABLE runs ADD COLUMN pid INTEGER",
            "ALTER TABLE runs ADD COLUMN ticket TEXT",
            "ALTER TABLE runs ADD COLUMN worktree_path TEXT",
        ):
            try:
                await conn.execute(ddl)
                await conn.commit()
            except aiosqlite.OperationalError:
                pass  # Column already present — fresh DB or migration already ran.

        # Idempotent index creation for the partial unique constraint on open
        # ticket rows.  ``CREATE UNIQUE INDEX IF NOT EXISTS`` is safe to re-run.
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_ticket_open "
            "ON runs(ticket) WHERE status = 'open'"
        )
        await conn.commit()


# ---------------------------------------------------------------------------
# State read / write — SPEC §4.8, §7
# ---------------------------------------------------------------------------


async def read_state(
    run_id: str,
    schema: type[S],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> S:
    """Load and validate ``runs.state_json`` for ``run_id`` against
    the supplied derived schema.

    Raises:
        StateStoreError: the run doesn't exist, or the persisted JSON
            fails schema validation.
    """
    async with store_connection(db_path) as conn:
        raw = await _select_state_json(conn, run_id)
    return _validate(schema, json.loads(raw), context=f"run {run_id!r}")


async def update_state(
    run_id: str,
    schema: type[S],
    *,
    db_path: Path = DEFAULT_DB_PATH,
    emit_event: bool = True,
    merge_overrides: dict[str, str] | None = None,
    **fields: Any,
) -> S:
    """Apply ``fields`` to the run's state under SPEC §7 merge rules.

    Returns the new full state instance.

    Merge rules:
      * **list** field — incoming list is appended to the existing list.
        For the framework ``notes`` list, caps are applied
        (entries first, then characters; oldest dropped).
      * **scalar** field (str / int / bool / float / model / Literal /
        constrained) — overwrite; last writer wins.
      * **dict** field — rejected (``StateStoreError``); merge semantics
        deferred to v1.5.
      * **unknown** field — rejected (``StateStoreError``).

    Per-write merge overrides (H-1.5-004):
      ``merge_overrides`` maps field names to a merge strategy that takes
      precedence over the type-driven default:

      * ``"replace"`` — unconditional overwrite regardless of field type.
        Most useful for lists (forces overwrite instead of append).

    The full read-modify-write happens inside a single
    ``BEGIN IMMEDIATE`` transaction so concurrent writers serialise
    cleanly at SQLite's write-lock layer.

    On success, emits a ``state_changed`` event whose ``data_json``
    carries ``{"fields": [<changed names>]}`` — narrower than the full
    new state, easier for downstream consumers to filter on.
    """
    if not fields:
        # No-op writes shouldn't emit events or churn the DB. Return
        # the current state so callers always get a value back.
        return await read_state(run_id, schema, db_path=db_path)

    _reject_unknown_fields(schema, fields)
    _reject_dict_writes(schema, fields)

    async with store_connection(db_path) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            raw = await _select_state_json(conn, run_id)
            current = _validate(schema, json.loads(raw), context=f"run {run_id!r}")

            merged = _merge(schema, current, fields, merge_overrides or {})
            new_state = _validate(schema, merged, context=f"run {run_id!r} (post-merge)")

            await conn.execute(
                "UPDATE runs SET state_json = ? WHERE run_id = ?",
                (new_state.model_dump_json(), run_id),
            )
            await conn.commit()
        except StateStoreError:
            await conn.rollback()
            raise
        except Exception:
            await conn.rollback()
            raise

    if emit_event:
        # Local import — the emitter module imports ``store`` for the
        # connection helper, so a top-level import here would form a
        # cycle.
        from harness.events.emitter import EventEmitter

        emitter = EventEmitter(db_path)
        await emitter.emit(
            run_id=run_id,
            event_type="state_changed",
            data={"fields": sorted(fields.keys())},
        )

    return new_state


async def restore_state(
    run_id: str,
    state: BaseState,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Overwrite ``runs.state_json`` verbatim with the supplied state.

    Unlike :func:`update_state` (which applies field-level merge rules),
    this function replaces the persisted JSON atomically with the exact
    serialisation of ``state``.  It is intended for resume operations
    where the caller already holds a validated snapshot and must restore
    it without any merge semantics.

    Raises:
        StateStoreError: the run does not exist.
    """
    async with store_connection(db_path) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            async with conn.execute(
                "SELECT 1 FROM runs WHERE run_id = ?", (run_id,)
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                raise StateStoreError(f"no run with run_id={run_id!r}")

            await conn.execute(
                "UPDATE runs SET state_json = ? WHERE run_id = ?",
                (state.model_dump_json(), run_id),
            )
            await conn.commit()
        except StateStoreError:
            await conn.rollback()
            raise
        except Exception:
            await conn.rollback()
            raise


# ---------------------------------------------------------------------------
# Per-completion snapshots — H-2-001
# ---------------------------------------------------------------------------


async def write_snapshot(
    run_id: str,
    node_id: str,
    state: BaseState,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Append an immutable state snapshot row after a node completes.

    ``seq`` is computed as ``MAX(seq) + 1`` for the run (or 1 if none
    exist), assigned inside a single ``BEGIN IMMEDIATE`` transaction so
    concurrent writers targeting the same run serialise correctly.

    The snapshot is purely additive — it never mutates ``runs.state_json``.
    The v2 resume machinery reads the latest snapshot via
    :func:`read_latest_snapshot` rather than the mutable row.
    """
    captured_at = datetime.now(UTC).isoformat()
    state_json = state.model_dump_json()

    async with store_connection(db_path) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            async with conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM run_snapshots WHERE run_id = ?",
                (run_id,),
            ) as cur:
                row = await cur.fetchone()
            assert row is not None  # COALESCE aggregate always returns a row
            next_seq: int = int(row[0]) + 1

            await conn.execute(
                "INSERT INTO run_snapshots (run_id, node_id, seq, state_json, captured_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (run_id, node_id, next_seq, state_json, captured_at),
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise


async def read_latest_snapshot(
    run_id: str,
    schema: type[S],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> S | None:
    """Return the state at the most recent snapshot, or ``None`` if none exist.

    The "most recent" snapshot is the row with the highest ``seq`` for the
    given ``run_id``. Returns ``None`` (not an error) when a run exists but
    has no snapshots yet — callers should fall back to ``read_state`` in
    that case.

    Raises:
        StateStoreError: the snapshot's ``state_json`` fails schema validation.
    """
    async with (
        store_connection(db_path) as conn,
        conn.execute(
            "SELECT state_json FROM run_snapshots WHERE run_id = ? ORDER BY seq DESC LIMIT 1",
            (run_id,),
        ) as cur,
    ):
        row = await cur.fetchone()

    if row is None:
        return None

    return _validate(schema, json.loads(str(row[0])), context=f"snapshot for run {run_id!r}")


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

# Re-exposed under a private alias so callers inside this module don't
# shadow ``connect`` when the function appears in busy code paths.
store_connection = connect


async def _select_state_json(conn: aiosqlite.Connection, run_id: str) -> str:
    async with conn.execute("SELECT state_json FROM runs WHERE run_id = ?", (run_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        raise StateStoreError(f"no run with run_id={run_id!r}")
    return str(row[0])


def _validate(schema: type[S], payload: dict[str, Any], *, context: str) -> S:
    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise StateStoreError(f"state for {context} failed schema validation: {exc}") from exc


def _reject_unknown_fields(schema: type[BaseState], fields: dict[str, Any]) -> None:
    known = set(schema.model_fields.keys())
    unknown = set(fields.keys()) - known
    if unknown:
        raise StateStoreError(
            f"unknown state field(s) {sorted(unknown)!r}; declared fields are {sorted(known)!r}"
        )


def _reject_dict_writes(schema: type[BaseState], fields: dict[str, Any]) -> None:
    for name in fields:
        annotation = schema.model_fields[name].annotation
        if get_origin(annotation) is dict:
            raise StateStoreError(
                f"dict-field write to {name!r} is not supported "
                f"(dict-merge semantics deferred to v1.5)"
            )


def _merge(
    schema: type[BaseState],
    current: BaseState,
    incoming: dict[str, Any],
    merge_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Apply per-field merge to ``current`` and return a plain dict.

    ``merge_overrides`` maps field name → merge strategy.  Currently only
    ``"replace"`` is defined: it forces an unconditional overwrite for any
    field type, bypassing the type-driven rules below.

    The caller re-validates the result against ``schema`` before
    persisting — so we don't need to be defensive about types here, the
    re-validation step will catch a list-shaped value handed to a
    scalar field, etc.
    """
    overrides = merge_overrides or {}
    merged: dict[str, Any] = current.model_dump(mode="json")

    for name, value in incoming.items():
        # Per-write override takes priority over type-driven defaults.
        if overrides.get(name) == "replace":
            merged[name] = value
            continue

        annotation = schema.model_fields[name].annotation
        if get_origin(annotation) is list:
            existing = list(merged.get(name) or [])
            existing.extend(value or [])
            if name == "notes":
                existing = _bound_notes(existing)
            merged[name] = existing
        else:
            # Scalar / model / Literal / constrained — overwrite.
            merged[name] = value

    return merged


def _bound_notes(notes: list[str]) -> list[str]:
    """Apply SPEC §7 bounding to the framework ``notes`` list.

    Order matters: entry-count cap first (cheap), then character-budget
    cap. The character cap may need to drop further entries even after
    the entry cap has fired — both run on every write.
    """
    # 1. Entry count cap.
    if len(notes) > NOTES_MAX_ENTRIES:
        notes = notes[-NOTES_MAX_ENTRIES:]
    # 2. Character budget cap — drop oldest whole entries until under.
    total = sum(len(n) for n in notes)
    while notes and total > NOTES_MAX_CHARS:
        total -= len(notes[0])
        notes = notes[1:]
    return notes
