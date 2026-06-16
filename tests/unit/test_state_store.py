"""Tests for harness.state.store — SQLite schema + WAL + idempotent init.

See SPEC §12 for the schema, §4.8 for the store responsibilities.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from harness.state import store

# ---------------------------------------------------------------------------
# init_db — idempotency, parent-dir creation, both tables exist
# ---------------------------------------------------------------------------


async def _table_names(db_path: Path) -> set[str]:
    async with aiosqlite.connect(db_path) as conn, conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ) as cursor:
        return {row[0] async for row in cursor}


async def _index_names(db_path: Path) -> set[str]:
    async with aiosqlite.connect(db_path) as conn, conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    ) as cursor:
        return {row[0] async for row in cursor}


async def _table_columns(db_path: Path, table: str) -> dict[str, dict[str, object]]:
    async with (
        aiosqlite.connect(db_path) as conn,
        conn.execute(f"PRAGMA table_info({table})") as cursor,
    ):
        return {
            row[1]: {"type": row[2], "notnull": row[3], "pk": row[5]}
            async for row in cursor
        }


async def test_init_db_creates_both_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    await store.init_db(db_path)
    tables = await _table_names(db_path)
    assert "runs" in tables
    assert "events" in tables


async def test_init_db_creates_indexes(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    await store.init_db(db_path)
    indexes = await _index_names(db_path)
    assert "idx_runs_status" in indexes
    assert "idx_runs_workflow" in indexes
    assert "idx_runs_started" in indexes
    assert "idx_events_run" in indexes
    assert "idx_events_type" in indexes
    assert "idx_events_run_node" in indexes


async def test_init_db_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    await store.init_db(db_path)
    # Second call must not raise.
    await store.init_db(db_path)
    tables = await _table_names(db_path)
    assert {"runs", "events"} <= tables


async def test_init_db_creates_parent_dir(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "deeper" / "harness.db"
    assert not db_path.parent.exists()
    await store.init_db(db_path)
    assert db_path.exists()


# ---------------------------------------------------------------------------
# Schema — columns match SPEC §12
# ---------------------------------------------------------------------------


async def test_runs_table_columns_match_spec(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    await store.init_db(db_path)
    cols = await _table_columns(db_path, "runs")

    expected = {
        "run_id", "workflow_name", "workflow_version", "status", "state_json",
        "inputs_json", "base_branch", "worktree_branch", "exit_code",
        "started_at", "completed_at", "duration_ms",
        "pid",          # dormant column; engine-era SIGTERM cancel removed (CAL-587)
        "ticket",       # CAL-570: Linear ticket identifier for ``harness start``
        "worktree_path",  # CAL-570: worktree filesystem path for ``harness start``
    }
    assert set(cols.keys()) == expected
    assert cols["run_id"]["pk"] == 1
    assert cols["workflow_name"]["notnull"] == 1
    assert cols["workflow_version"]["notnull"] == 1
    assert cols["status"]["notnull"] == 1
    assert cols["state_json"]["notnull"] == 1
    assert cols["inputs_json"]["notnull"] == 1
    assert cols["started_at"]["notnull"] == 1


async def test_events_table_columns_match_spec(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    await store.init_db(db_path)
    cols = await _table_columns(db_path, "events")

    expected = {
        "id", "run_id", "node_id", "event_type", "timestamp",
        "duration_ms", "data_json",
    }
    assert set(cols.keys()) == expected
    assert cols["id"]["pk"] == 1
    assert cols["run_id"]["notnull"] == 1
    assert cols["event_type"]["notnull"] == 1
    assert cols["timestamp"]["notnull"] == 1
    assert cols["data_json"]["notnull"] == 1


# ---------------------------------------------------------------------------
# Connection — WAL mode + foreign keys
# ---------------------------------------------------------------------------


async def test_connect_enables_wal_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    await store.init_db(db_path)
    async with store.connect(db_path) as conn, conn.execute("PRAGMA journal_mode") as cursor:
        row = await cursor.fetchone()
        assert row is not None
        assert row[0].lower() == "wal"


async def test_connect_enables_foreign_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    await store.init_db(db_path)
    async with store.connect(db_path) as conn, conn.execute("PRAGMA foreign_keys") as cursor:
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1


# ---------------------------------------------------------------------------
# Foreign-key cascade — events deleted when their run is deleted
# ---------------------------------------------------------------------------


async def test_events_cascade_delete_with_run(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    await store.init_db(db_path)
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("R1", "test", 1, "running", "{}", "{}", "2026-05-04T00:00:00Z"),
        )
        await conn.execute(
            "INSERT INTO events (run_id, event_type, timestamp) VALUES (?, ?, ?)",
            ("R1", "workflow_started", "2026-05-04T00:00:00Z"),
        )
        await conn.execute(
            "INSERT INTO events (run_id, event_type, timestamp) VALUES (?, ?, ?)",
            ("R1", "node_started", "2026-05-04T00:00:01Z"),
        )
        await conn.commit()

        async with conn.execute("SELECT COUNT(*) FROM events") as cur:
            row = await cur.fetchone()
            assert row is not None and row[0] == 2

        await conn.execute("DELETE FROM runs WHERE run_id = ?", ("R1",))
        await conn.commit()

        async with conn.execute("SELECT COUNT(*) FROM events") as cur:
            row = await cur.fetchone()
            assert row is not None and row[0] == 0


# ---------------------------------------------------------------------------
# Status enum — runs.status accepts the v1.5 values (paused, stalled)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    ["pending", "running", "completed", "failed", "cancelled", "stalled", "paused"],
)
async def test_runs_status_enum_accepts_all_documented_values(
    tmp_path: Path, status: str
) -> None:
    """SPEC §12 documents the status enum; the schema doesn't constrain via CHECK
    but inserts should round-trip every value the engine will write.
    """
    db_path = tmp_path / "harness.db"
    await store.init_db(db_path)
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"R-{status}", "test", 1, status, "{}", "{}", "2026-05-04T00:00:00Z"),
        )
        await conn.commit()
        async with conn.execute(
            "SELECT status FROM runs WHERE run_id = ?", (f"R-{status}",)
        ) as cur:
            row = await cur.fetchone()
            assert row is not None and row[0] == status


# ---------------------------------------------------------------------------
# CAL-713 — no migration for a writer-less column
# ---------------------------------------------------------------------------

_STORE_SRC = Path(__file__).resolve().parents[2] / "harness" / "state" / "store.py"


def test_no_pid_migration() -> None:
    """AC #2: ``pid`` has no writer, so ``_migrate`` runs no ``ADD COLUMN pid``.

    ``pid`` is a dormant column declared once in ``_SCHEMA``'s CREATE TABLE and
    retained to avoid a destructive ``DROP COLUMN`` on existing DBs (see
    ``specs/features/run-ledger.md``). The redundant ``ALTER TABLE runs ADD
    COLUMN pid`` migration was removed in CAL-713; this guard keeps it gone.
    """
    src = _STORE_SRC.read_text()
    assert "ADD COLUMN pid" not in src, (
        "store.py runs an ADD COLUMN pid migration, but pid has no writer "
        "(engine-era SIGTERM cancel removed in CAL-587). The column stays "
        "declared in _SCHEMA; the migration must not (CAL-713, AC #2)."
    )


async def test_pid_column_present_via_schema(tmp_path: Path) -> None:
    """The dormant ``pid`` column is still created — from ``_SCHEMA``, not a
    migration — so existing-DB reads and the column contract are unchanged."""
    db_path = tmp_path / "harness.db"
    await store.init_db(db_path)
    cols = await _table_columns(db_path, "runs")
    assert "pid" in cols
