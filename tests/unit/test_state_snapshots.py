"""Tests for H-2-001 — per-completion state snapshots.

After each node completes, the executor writes a ``run_snapshots`` row
containing the full serialised state at that point. This gives the v2
rehydration layer a clean history to replay from.

Tests cover:

* Schema (AC1..AC3) — ``run_snapshots`` table created by ``init_db``,
  has the right columns, and cascade-deletes with the parent run.
* write_snapshot (AC4..AC6) — rows inserted with correct content,
  sequential ``seq`` numbers within a run, and the function is idempotent
  across multiple runs.
* read_latest_snapshot (AC7..AC9) — returns ``None`` when no snapshots
  exist, returns the row with the highest ``seq`` for a run, and ignores
  snapshots from other runs.
* Executor integration (AC10..AC11) — each successful node completion
  produces exactly one snapshot row; failed nodes produce none.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from pydantic import create_model

from harness.state import store
from harness.state.schema import BaseState
from harness.state.store import read_latest_snapshot, write_snapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_state_kwargs(run_id: str = "R1") -> dict[str, Any]:
    return {
        "run_id": run_id,
        "workflow_name": "wf",
        "base_branch": "main",
        "artifacts_dir": "/tmp/x",
        "started_at": datetime(2026, 5, 8, 12, 0, 0).isoformat(),
        "notes": [],
    }


def _make_schema(**extra: Any) -> type[BaseState]:
    cls: type[BaseState] = create_model(  # type: ignore[call-overload]
        "DerivedState",
        __base__=BaseState,
        **extra,
    )
    return cls


async def _seed_run(db_path: Path, run_id: str = "R1") -> None:
    """Create db + insert a minimal runs row."""
    await store.init_db(db_path)
    state_json = json.dumps(_base_state_kwargs(run_id))
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, "wf", 1, "running", state_json, "{}", "2026-05-08T00:00:00Z"),
        )
        await conn.commit()


async def _snapshot_rows(db_path: Path, run_id: str = "R1") -> list[dict[str, Any]]:
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT id, run_id, node_id, seq, state_json, captured_at "
            "FROM run_snapshots WHERE run_id = ? ORDER BY seq",
            (run_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def _table_columns(db_path: Path, table: str) -> dict[str, dict[str, object]]:
    async with (
        aiosqlite.connect(db_path) as conn,
        conn.execute(f"PRAGMA table_info({table})") as cursor,
    ):
        return {row[1]: {"type": row[2], "notnull": row[3], "pk": row[5]} async for row in cursor}


async def _index_names(db_path: Path) -> set[str]:
    async with (
        aiosqlite.connect(db_path) as conn,
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        ) as cursor,
    ):
        return {row[0] async for row in cursor}


# ---------------------------------------------------------------------------
# AC1 — init_db creates run_snapshots table
# ---------------------------------------------------------------------------


async def test_ac1_init_db_creates_run_snapshots_table(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    await store.init_db(db_path)
    async with (
        aiosqlite.connect(db_path) as conn,
        conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur,
    ):
        tables = {row[0] async for row in cur}
    assert "run_snapshots" in tables


# ---------------------------------------------------------------------------
# AC2 — run_snapshots columns match spec
# ---------------------------------------------------------------------------


async def test_ac2_run_snapshots_columns_match_spec(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    await store.init_db(db_path)
    cols = await _table_columns(db_path, "run_snapshots")

    expected = {"id", "run_id", "node_id", "seq", "state_json", "captured_at"}
    assert set(cols.keys()) == expected
    assert cols["id"]["pk"] == 1
    assert cols["run_id"]["notnull"] == 1
    assert cols["node_id"]["notnull"] == 1
    assert cols["seq"]["notnull"] == 1
    assert cols["state_json"]["notnull"] == 1
    assert cols["captured_at"]["notnull"] == 1


# ---------------------------------------------------------------------------
# AC3 — run_snapshots cascade-delete with parent run
# ---------------------------------------------------------------------------


async def test_ac3_snapshots_cascade_delete_with_run(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    await _seed_run(db_path)
    schema = _make_schema()
    state = schema.model_validate(_base_state_kwargs())

    await write_snapshot("R1", "step-a", state, db_path=db_path)
    await write_snapshot("R1", "step-b", state, db_path=db_path)

    async with store.connect(db_path) as conn:
        async with conn.execute("SELECT COUNT(*) FROM run_snapshots") as cur:
            row = await cur.fetchone()
            assert row is not None and row[0] == 2

        await conn.execute("DELETE FROM runs WHERE run_id = 'R1'")
        await conn.commit()

        async with conn.execute("SELECT COUNT(*) FROM run_snapshots") as cur:
            row = await cur.fetchone()
            assert row is not None and row[0] == 0


# ---------------------------------------------------------------------------
# AC4 — write_snapshot inserts a row with correct content
# ---------------------------------------------------------------------------


async def test_ac4_write_snapshot_inserts_row(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    await _seed_run(db_path)
    schema = _make_schema()
    state = schema.model_validate(_base_state_kwargs())

    await write_snapshot("R1", "step-one", state, db_path=db_path)

    rows = await _snapshot_rows(db_path)
    assert len(rows) == 1
    assert rows[0]["run_id"] == "R1"
    assert rows[0]["node_id"] == "step-one"
    assert rows[0]["seq"] == 1
    assert json.loads(rows[0]["state_json"])["run_id"] == "R1"
    assert rows[0]["captured_at"] != ""


# ---------------------------------------------------------------------------
# AC5 — seq increments within a run
# ---------------------------------------------------------------------------


async def test_ac5_seq_increments_across_snapshots(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    await _seed_run(db_path)
    schema = _make_schema()
    state = schema.model_validate(_base_state_kwargs())

    await write_snapshot("R1", "step-a", state, db_path=db_path)
    await write_snapshot("R1", "step-b", state, db_path=db_path)
    await write_snapshot("R1", "step-c", state, db_path=db_path)

    rows = await _snapshot_rows(db_path)
    seqs = [r["seq"] for r in rows]
    assert seqs == [1, 2, 3]
    assert [r["node_id"] for r in rows] == ["step-a", "step-b", "step-c"]


# ---------------------------------------------------------------------------
# AC6 — seq is per-run, not global
# ---------------------------------------------------------------------------


async def test_ac6_seq_is_per_run_not_global(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    await _seed_run(db_path, run_id="R1")
    await _seed_run(db_path, run_id="R2")
    schema = _make_schema()

    state_r1 = schema.model_validate(_base_state_kwargs("R1"))
    state_r2 = schema.model_validate(_base_state_kwargs("R2"))

    await write_snapshot("R1", "step-a", state_r1, db_path=db_path)
    await write_snapshot("R1", "step-b", state_r1, db_path=db_path)
    await write_snapshot("R2", "step-a", state_r2, db_path=db_path)

    r1_rows = await _snapshot_rows(db_path, "R1")
    r2_rows = await _snapshot_rows(db_path, "R2")

    # R1 has seq 1, 2; R2 starts at 1 independently.
    assert [r["seq"] for r in r1_rows] == [1, 2]
    assert [r["seq"] for r in r2_rows] == [1]


# ---------------------------------------------------------------------------
# AC7 — read_latest_snapshot returns None when no snapshots
# ---------------------------------------------------------------------------


async def test_ac7_read_latest_snapshot_returns_none_when_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    await _seed_run(db_path)
    schema = _make_schema()

    result = await read_latest_snapshot("R1", schema, db_path=db_path)
    assert result is None


# ---------------------------------------------------------------------------
# AC8 — read_latest_snapshot returns the highest-seq row
# ---------------------------------------------------------------------------


async def test_ac8_read_latest_snapshot_returns_highest_seq(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    await _seed_run(db_path)
    schema = _make_schema(label=(str | None, None))

    state1 = schema.model_validate(_base_state_kwargs() | {"label": "first"})
    state2 = schema.model_validate(_base_state_kwargs() | {"label": "second"})
    state3 = schema.model_validate(_base_state_kwargs() | {"label": "third"})

    await write_snapshot("R1", "step-a", state1, db_path=db_path)
    await write_snapshot("R1", "step-b", state2, db_path=db_path)
    await write_snapshot("R1", "step-c", state3, db_path=db_path)

    result = await read_latest_snapshot("R1", schema, db_path=db_path)
    assert result is not None
    assert result.label == "third"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC9 — read_latest_snapshot ignores other runs' snapshots
# ---------------------------------------------------------------------------


async def test_ac9_read_latest_snapshot_ignores_other_runs(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    await _seed_run(db_path, "R1")
    await _seed_run(db_path, "R2")
    schema = _make_schema(label=(str | None, None))

    # R2 gets many snapshots; R1 gets only one.
    state_r1 = schema.model_validate(_base_state_kwargs("R1") | {"label": "r1-only"})
    state_r2 = schema.model_validate(_base_state_kwargs("R2") | {"label": "r2-snap"})

    await write_snapshot("R2", "step-a", state_r2, db_path=db_path)
    await write_snapshot("R2", "step-b", state_r2, db_path=db_path)
    await write_snapshot("R1", "step-a", state_r1, db_path=db_path)

    result = await read_latest_snapshot("R1", schema, db_path=db_path)
    assert result is not None
    assert result.label == "r1-only"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC10 — read_latest_snapshot returns None when run has no snapshots
# ---------------------------------------------------------------------------


async def test_ac10_read_latest_snapshot_missing_run_returns_none(tmp_path: Path) -> None:
    """No run row means no snapshots — return None (not an error)."""
    db_path = tmp_path / "h.db"
    await store.init_db(db_path)
    schema = _make_schema()

    result = await read_latest_snapshot("ghost", schema, db_path=db_path)
    assert result is None


# ---------------------------------------------------------------------------
# AC11 — init_db creates snapshot indexes
# ---------------------------------------------------------------------------


async def test_ac11_init_db_creates_snapshot_indexes(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    await store.init_db(db_path)
    indexes = await _index_names(db_path)
    assert "idx_snapshots_run" in indexes
    assert "idx_snapshots_run_seq" in indexes


# ---------------------------------------------------------------------------
# AC12 — executor writes one snapshot per successful node completion
# ---------------------------------------------------------------------------


async def test_ac12_executor_writes_snapshot_on_node_complete(tmp_path: Path) -> None:
    """After each successful node, the executor inserts exactly one snapshot row."""
    from unittest.mock import AsyncMock

    from pydantic import create_model as _cm

    from harness.engine.executor import Context, Executor
    from harness.nodes.base import Attestation, NodeResult
    from harness.state.store import connect, init_db
    from harness.workflow.schema import AIStep, WriteSpec

    db_path = tmp_path / "h.db"
    await init_db(db_path)

    # Seed the runs row with minimal valid state.
    schema = _make_schema(summary=(str | None, None))
    initial = schema.model_validate(_base_state_kwargs() | {"summary": None})
    async with connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("R1", "wf", 1, "running", initial.model_dump_json(), "{}", "2026-05-08T00:00:00Z"),
        )
        await conn.commit()

    # Build a minimal step.
    contract_cls = _cm("SummaryContract", summary=(str, ...))  # type: ignore[call-overload]
    contract_instance = contract_cls(summary="hello")

    step = AIStep(
        id="summarise",
        type="ai",
        agent="claude",
        prompt="prompts/noop.j2",
        writes=[WriteSpec(field="summary")],
    )

    mock_runner = AsyncMock(
        return_value=NodeResult(
            contract=contract_instance,
            attestation=Attestation(status="complete"),
        )
    )

    ctx = Context(
        run_id="R1",
        db_path=db_path,
        contracts={"summarise": contract_cls},
        state_schema=schema,
        nodes={"ai": mock_runner},
        workflow_name="wf",
    )

    executor = Executor()
    await executor.execute(step, ctx)

    # Exactly one snapshot row should exist after one successful completion.
    rows = await _snapshot_rows(db_path)
    assert len(rows) == 1
    assert rows[0]["node_id"] == "summarise"
    assert rows[0]["seq"] == 1
    persisted = json.loads(rows[0]["state_json"])
    assert persisted["summary"] == "hello"


# ---------------------------------------------------------------------------
# AC13 — executor does NOT write snapshot when node fails
# ---------------------------------------------------------------------------


async def test_ac13_executor_does_not_write_snapshot_on_node_failure(tmp_path: Path) -> None:
    """A node that raises must not leave a snapshot row."""
    from unittest.mock import AsyncMock

    from harness.engine.executor import Context, Executor
    from harness.state.store import connect, init_db
    from harness.workflow.schema import AIStep

    db_path = tmp_path / "h.db"
    await init_db(db_path)

    schema = _make_schema()
    initial = schema.model_validate(_base_state_kwargs())
    async with connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("R1", "wf", 1, "running", initial.model_dump_json(), "{}", "2026-05-08T00:00:00Z"),
        )
        await conn.commit()

    step = AIStep(
        id="boom",
        type="ai",
        agent="claude",
        prompt="prompts/noop.j2",
        writes=[],
    )

    boom_runner = AsyncMock(side_effect=RuntimeError("exploded"))

    ctx = Context(
        run_id="R1",
        db_path=db_path,
        contracts={},
        state_schema=schema,
        nodes={"ai": boom_runner},
        workflow_name="wf",
    )

    executor = Executor()
    with pytest.raises(RuntimeError, match="exploded"):
        await executor.execute(step, ctx)

    rows = await _snapshot_rows(db_path)
    assert len(rows) == 0


# ---------------------------------------------------------------------------
# AC_UNIQUE — UNIQUE (run_id, seq) prevents duplicate seq values at DB level
# ---------------------------------------------------------------------------


async def test_ac_unique_run_id_seq_constraint_rejects_duplicate(tmp_path: Path) -> None:
    """DB-level UNIQUE (run_id, seq) constraint prevents silent corruption."""
    import aiosqlite as _aiosqlite

    db_path = tmp_path / "h.db"
    await _seed_run(db_path)

    # First insert is fine.
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO run_snapshots (run_id, node_id, seq, state_json, captured_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("R1", "step-a", 1, "{}", "2026-01-01T00:00:00"),
        )
        await conn.commit()

    # Second insert with the SAME (run_id, seq) must raise.
    with pytest.raises(_aiosqlite.IntegrityError):
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO run_snapshots (run_id, node_id, seq, state_json, captured_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("R1", "step-b", 1, "{}", "2026-01-01T00:00:01"),
            )
            await conn.commit()
