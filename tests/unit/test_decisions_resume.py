"""Unit tests for harness.decisions.resume — H-2-005.

The resume module's ``rehydrate_state`` function loads the most recent
per-completion snapshot from ``run_snapshots`` and writes it back to
``runs.state_json`` so the executor starts from the correct state when
the runner resumes a paused run.

Tests:

* rehydrate_state uses the latest snapshot when one exists.
* rehydrate_state writes the snapshot state to runs.state_json.
* rehydrate_state returns the correct state object.
* rehydrate_state falls back to runs.state_json when no snapshot exists.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
from pydantic import create_model

from harness.decisions.resume import rehydrate_state
from harness.state import store
from harness.state.schema import BaseState


def _base_kwargs(run_id: str = "R1") -> dict[str, Any]:
    return {
        "run_id": run_id,
        "workflow_name": "wf",
        "base_branch": "main",
        "artifacts_dir": "/tmp/x",
        "started_at": datetime(2026, 5, 8, 12, 0, 0).isoformat(),
        "notes": [],
    }


def _make_schema(**extra: Any) -> type[BaseState]:
    cls: type[BaseState] = create_model(
        "DerivedState",
        __base__=BaseState,
        **extra,
    )
    return cls


async def _seed_run(db_path: Path, run_id: str = "R1", state_json: str | None = None) -> None:
    await store.init_db(db_path)
    if state_json is None:
        state_json = json.dumps(_base_kwargs(run_id))
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, "wf", 1, "paused", state_json, "{}", "2026-05-08T00:00:00Z"),
        )
        await conn.commit()


async def _read_state_json(db_path: Path, run_id: str = "R1") -> dict[str, Any]:
    async with aiosqlite.connect(db_path) as conn, conn.execute(
        "SELECT state_json FROM runs WHERE run_id = ?", (run_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    return json.loads(row[0])


# ---------------------------------------------------------------------------
# rehydrate_state — snapshot exists
# ---------------------------------------------------------------------------


async def test_rehydrate_state_returns_snapshot_state(tmp_path: Path) -> None:
    """rehydrate_state returns the state from the latest snapshot."""
    db = tmp_path / "h.db"
    schema = _make_schema(label=(str | None, None))
    await _seed_run(db)

    snapshot_state = schema.model_validate(_base_kwargs() | {"label": "from_snapshot"})
    await store.write_snapshot("R1", "step-a", snapshot_state, db_path=db)

    result = await rehydrate_state("R1", schema, db_path=db)

    assert result.label == "from_snapshot"  # type: ignore[attr-defined]


async def test_rehydrate_state_writes_snapshot_to_runs_state_json(tmp_path: Path) -> None:
    """rehydrate_state writes the snapshot's state back to runs.state_json."""
    db = tmp_path / "h.db"
    schema = _make_schema(label=(str | None, None))

    # Seed a run with stale state_json (no label).
    initial = json.dumps(_base_kwargs())
    await _seed_run(db, state_json=initial)

    # Write a snapshot with a label value.
    snapshot_state = schema.model_validate(_base_kwargs() | {"label": "snapshot_label"})
    await store.write_snapshot("R1", "step-a", snapshot_state, db_path=db)

    await rehydrate_state("R1", schema, db_path=db)

    # runs.state_json should now have the snapshot label.
    persisted = await _read_state_json(db)
    assert persisted.get("label") == "snapshot_label"


async def test_rehydrate_state_uses_latest_of_multiple_snapshots(tmp_path: Path) -> None:
    """When multiple snapshots exist, rehydrate_state uses the highest-seq one."""
    db = tmp_path / "h.db"
    schema = _make_schema(label=(str | None, None))
    await _seed_run(db)

    s1 = schema.model_validate(_base_kwargs() | {"label": "first"})
    s2 = schema.model_validate(_base_kwargs() | {"label": "second"})
    s3 = schema.model_validate(_base_kwargs() | {"label": "third"})
    await store.write_snapshot("R1", "step-a", s1, db_path=db)
    await store.write_snapshot("R1", "step-b", s2, db_path=db)
    await store.write_snapshot("R1", "step-c", s3, db_path=db)

    result = await rehydrate_state("R1", schema, db_path=db)
    assert result.label == "third"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# rehydrate_state — no snapshot (fallback to runs.state_json)
# ---------------------------------------------------------------------------


async def test_rehydrate_state_fallback_when_no_snapshot(tmp_path: Path) -> None:
    """When no snapshot exists, rehydrate_state reads from runs.state_json."""
    db = tmp_path / "h.db"
    schema = _make_schema(label=(str | None, None))

    state_with_label = _base_kwargs() | {"label": "from_runs_row"}
    await _seed_run(db, state_json=json.dumps(state_with_label))

    # No snapshot written.
    result = await rehydrate_state("R1", schema, db_path=db)
    assert result.label == "from_runs_row"  # type: ignore[attr-defined]


async def test_rehydrate_state_fallback_does_not_corrupt_state_json(tmp_path: Path) -> None:
    """Fallback path (no snapshot) does NOT write to runs.state_json."""
    db = tmp_path / "h.db"
    schema = _make_schema(label=(str | None, None))
    original_json = json.dumps(_base_kwargs() | {"label": "original"})
    await _seed_run(db, state_json=original_json)

    await rehydrate_state("R1", schema, db_path=db)

    persisted = await _read_state_json(db)
    assert persisted.get("label") == "original"
