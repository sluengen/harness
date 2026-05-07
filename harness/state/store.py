"""SQLite state store — see SPEC §4.8, §7, §12.

Single database per project at ``$workspace/.harness/harness.db``. WAL journal
mode for concurrent reads. Foreign keys ON so events cascade-delete with their
run.

This module currently exposes the connection helper and the idempotent schema
init. State write operations (type-driven merge, ``StateStore.update``) land in
H-010 on top of this foundation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

DEFAULT_DB_PATH = Path(".harness/harness.db")

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
  duration_ms         INTEGER
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
