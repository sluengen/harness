"""SQLite ledger — connection, schema, and migrations. See SPEC §4.6.

Single database per project at ``$workspace/.harness/harness.db``. WAL journal
mode for concurrent reads. Foreign keys ON so events cascade-delete with their
run.

This module owns the ledger's *foundation*: opening a managed connection
(:func:`connect`), creating the ``runs`` / ``events`` schema idempotently
(:func:`init_db`), and applying incremental column/index migrations
(:func:`_migrate`). The ``runs`` row plus its ``events`` are the whole audit
trail; the verbs (``start`` / ``review`` / ``close``) read and write them
directly through :func:`connect`.

The engine-era per-node state machinery (``read_state`` / ``update_state`` /
``restore_state``) and the never-shipped v2-resume snapshot layer
(``write_snapshot`` / ``read_latest_snapshot`` + the ``run_snapshots`` table)
were removed in CAL-613 — they had no production caller after the deterministic
engine was retired in CAL-574. The current schema reference is
``specs/features/run-ledger.md``.

Module-level functions (rather than a ``StateStore`` class) match the
existing style — the single-db-per-project model means there's no state
worth bundling on an instance.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

DEFAULT_DB_PATH = Path(".harness/harness.db")


# Schema per ``specs/features/run-ledger.md``. Idempotent — every CREATE uses
# ``IF NOT EXISTS``. Re-running this script on an existing DB is a no-op.
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

    The ``runs.pid`` column (vestigial — the engine-era SIGTERM ``harness
        cancel`` path was removed in CAL-587, so nothing writes it) is declared
        once in ``_SCHEMA`` above and kept as a dormant column to avoid a
        destructive ``DROP COLUMN`` on existing DBs. Its ``ADD COLUMN``
        migration was removed in CAL-713: a writer-less column needs no
        migration, and ``_SCHEMA`` already creates it for fresh DBs.
    CAL-570: ``runs.ticket TEXT`` — Linear ticket identifier (e.g. ``CAL-570``)
        for runs opened via ``harness start``.
    CAL-570: ``runs.worktree_path TEXT`` — filesystem path of the worktree
        created by ``harness start`` (mirrors the ``worktree_path`` state field
        but stored at the row level for observability without parsing state_json).
    CAL-570: ``idx_runs_ticket_open`` partial unique index on ``(ticket)``
        WHERE ``status='open'`` — prevents two concurrent ``harness start``
        calls from inserting duplicate open rows for the same ticket.
    #258: ``runs.resumed_from TEXT`` — the preserved WIP branch ``harness start
        --resume`` actually recovered, or ``NULL`` for a clean start (including
        a ``--resume`` that fell back). ADR 0008 gates design inheritance on
        *how the run started*, and ``start`` computed that distinction and then
        discarded it; this column makes it durable. Nullable by design: ``NULL``
        is the clean-start signal, and every pre-migration run reads it, so
        those runs keep re-designing exactly as before.
    #352: ``runs.assurance TEXT`` / ``runs.assurance_reason TEXT`` — the
        assurance level ``harness start`` resolved from the issue's labels and
        the tag saying why it resolved that way (``harness/assurance.py``).
        Snapshotted once at ``start`` and never mutated, so the stages a run is
        required to pay for cannot change under it when someone edits a label
        mid-run. Both nullable: ``NULL`` is what every row written before this
        migration carries, and ``coerce_assurance`` reads it as ``simple`` — the
        level that still requires a review — so legacy runs need no backfill and
        behave exactly as they did.
    """
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA foreign_keys = ON")
        for ddl in (
            "ALTER TABLE runs ADD COLUMN ticket TEXT",
            "ALTER TABLE runs ADD COLUMN worktree_path TEXT",
            "ALTER TABLE runs ADD COLUMN resumed_from TEXT",
            "ALTER TABLE runs ADD COLUMN assurance TEXT",
            "ALTER TABLE runs ADD COLUMN assurance_reason TEXT",
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
