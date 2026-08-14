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
        "resumed_from",   # #258: the preserved branch ``--resume`` recovered, else NULL
        "assurance",         # #352: the level start snapshotted for the run
        "assurance_reason",  # #352: why the run carries that level
        "base_sha",          # #353: the merge-target SHA the trivial classifier diffs from
    }
    assert set(cols.keys()) == expected
    # #352: both nullable. A run row written before the migration must be
    # readable *as it stands* — ``coerce_assurance(None)`` reads NULL as
    # ``simple`` — so no backfill is needed and no historical row is rewritten.
    assert cols["assurance"]["notnull"] == 0
    assert cols["assurance_reason"]["notnull"] == 0
    # #258 / ADR 0008 F2: the adopt gate reads this as "did the WIP come back?",
    # so a clean start must be distinguishable — the column has to be nullable.
    assert cols["resumed_from"]["notnull"] == 0
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


# ---------------------------------------------------------------------------
# #258 — the ``runs.resumed_from`` migration (AC-7)
# ---------------------------------------------------------------------------


async def _premigration_ledger(db_path: Path, run_id: str) -> None:
    """Build a ledger as it stood *before* the ``resumed_from`` migration.

    ``_SCHEMA``'s ``CREATE TABLE IF NOT EXISTS`` cannot express the column drop,
    so the pre-migration shape is written directly: today's ``runs`` table minus
    ``resumed_from``, carrying one row. Running :func:`store.init_db` over this
    is exactly what an existing checkout's ledger meets on upgrade.
    """
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "CREATE TABLE runs ("
            "run_id TEXT PRIMARY KEY, workflow_name TEXT NOT NULL, "
            "workflow_version INTEGER NOT NULL, status TEXT NOT NULL, "
            "state_json TEXT NOT NULL, inputs_json TEXT NOT NULL, "
            "base_branch TEXT, worktree_branch TEXT, exit_code INTEGER, "
            "started_at TEXT NOT NULL, completed_at TEXT, duration_ms INTEGER, "
            "pid INTEGER, ticket TEXT, worktree_path TEXT)"
        )
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, started_at) VALUES (?, '', 0, 'open', "
            "'{}', '{}', '2026-07-30T00:00:00Z')",
            (run_id,),
        )
        await conn.commit()


async def test_resumed_from_migration_opens_a_premigration_ledger(
    tmp_path: Path,
) -> None:
    """AC-7: a ledger predating the migration upgrades, and its runs read ``NULL``.

    The whole point of the additive ``ALTER TABLE``: an existing checkout's
    ledger gains the column without losing a row, and every run written before
    it reads ``resumed_from IS NULL`` — which the adopt gate treats as a clean
    start, so pre-migration runs behave exactly as they did.
    """
    db_path = tmp_path / "harness.db"
    await _premigration_ledger(db_path, "01JOLDRUNXXXXXXXXXXXXXXXX1")

    await store.init_db(db_path)

    assert "resumed_from" in await _table_columns(db_path, "runs")
    async with (
        aiosqlite.connect(db_path) as conn,
        conn.execute("SELECT run_id, resumed_from FROM runs") as cursor,
    ):
        rows = await cursor.fetchall()
    assert rows == [("01JOLDRUNXXXXXXXXXXXXXXXX1", None)]


async def test_resumed_from_migration_is_idempotent(tmp_path: Path) -> None:
    """AC-7: applying the migration twice succeeds and preserves the value.

    ``init_db`` runs on every verb invocation, so the second application is the
    common case, not an edge one. A migration that raised — or that reset a
    recorded ``resumed_from`` — would break every run after the first.
    """
    db_path = tmp_path / "harness.db"
    await _premigration_ledger(db_path, "01JOLDRUNXXXXXXXXXXXXXXXX2")
    await store.init_db(db_path)
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "UPDATE runs SET resumed_from = 'harness/01JSOURCE'",
        )
        await conn.commit()

    await store.init_db(db_path)  # second application — must not raise or reset

    async with (
        aiosqlite.connect(db_path) as conn,
        conn.execute("SELECT resumed_from FROM runs") as cursor,
    ):
        rows = await cursor.fetchall()
    assert rows == [("harness/01JSOURCE",)]


# ---------------------------------------------------------------------------
# #352 — the ``runs.assurance`` / ``runs.assurance_reason`` migration (AC-2)
# ---------------------------------------------------------------------------


async def test_assurance_migration_opens_a_premigration_ledger(tmp_path: Path) -> None:
    """AC-2: an existing ledger gains both columns without losing or rewriting a row.

    :func:`_premigration_ledger` builds the ``runs`` table as it stood before
    ``resumed_from``, so it also predates these two — which is exactly the shape
    every existing checkout's ledger has. The row must survive with ``NULL`` in
    both, because "no assurance recorded" is the state
    ``harness.assurance.coerce_assurance`` reads as ``simple``: the no-backfill
    half of the criterion is that the row is still there and still untouched.
    """
    db_path = tmp_path / "harness.db"
    await _premigration_ledger(db_path, "01JOLDRUNXXXXXXXXXXXXXXXX3")

    await store.init_db(db_path)

    cols = await _table_columns(db_path, "runs")
    assert "assurance" in cols
    assert "assurance_reason" in cols
    async with (
        aiosqlite.connect(db_path) as conn,
        conn.execute(
            "SELECT run_id, status, started_at, assurance, assurance_reason FROM runs"
        ) as cursor,
    ):
        rows = await cursor.fetchall()
    assert rows == [
        ("01JOLDRUNXXXXXXXXXXXXXXXX3", "open", "2026-07-30T00:00:00Z", None, None)
    ]


async def test_assurance_migration_is_idempotent(tmp_path: Path) -> None:
    """AC-2: re-application must neither raise nor reset a recorded snapshot.

    ``start`` runs ``init_db`` on every invocation — before its first ledger read
    since #352 — so a run's second, third and hundredth ``start`` all re-apply
    this migration. (An earlier draft of this docstring said *every verb* runs
    it. That was false, and the falsehood mattered: ``design`` and ``review``
    never call it, which is why they must tolerate a ledger that predates the
    column rather than assume it has been healed. See
    ``test_runs_resolver.py::test_read_run_assurance_tolerates_a_ledger_that_predates_the_column``.)

    Resetting would be the worse failure of the two and is the one an
    "it did not raise" assertion misses: a run opened ``complex`` would silently
    read back as ``simple`` on the next verb call, dropping its design
    requirement mid-run.
    """
    db_path = tmp_path / "harness.db"
    await _premigration_ledger(db_path, "01JOLDRUNXXXXXXXXXXXXXXXX4")
    await store.init_db(db_path)
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("UPDATE runs SET assurance = 'complex', assurance_reason = 'label'")
        await conn.commit()

    await store.init_db(db_path)  # second application — must not raise or reset

    async with (
        aiosqlite.connect(db_path) as conn,
        conn.execute("SELECT assurance, assurance_reason FROM runs") as cursor,
    ):
        rows = await cursor.fetchall()
    assert rows == [("complex", "label")]
