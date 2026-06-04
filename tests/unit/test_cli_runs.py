"""Tests for harness runs command — list recent runs with optional failed grouping."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from harness.cli import app
from harness.state import store

runner = CliRunner()


# ---------------------------------------------------------------------------
# DB helpers (mirrors pattern from test_cli_query.py)
# ---------------------------------------------------------------------------


async def _seed_run_async(
    db_path: Path,
    *,
    run_id: str,
    workflow_name: str = "feature",
    workflow_version: int = 1,
    status: str = "completed",
    state_json: str = "{}",
    inputs_json: str = "{}",
    base_branch: str | None = "main",
    worktree_branch: str | None = None,
    exit_code: int | None = 0,
    started_at: str = "2026-06-01T10:00:00Z",
    completed_at: str | None = "2026-06-01T10:30:00Z",
    duration_ms: int | None = 1_800_000,
) -> None:
    await store.init_db(db_path)
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, base_branch, worktree_branch, exit_code, "
            "started_at, completed_at, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                workflow_name,
                workflow_version,
                status,
                state_json,
                inputs_json,
                base_branch,
                worktree_branch,
                exit_code,
                started_at,
                completed_at,
                duration_ms,
            ),
        )
        await conn.commit()


def _run_sync(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _seed_run(db_path: Path, **kwargs: Any) -> None:
    _run_sync(_seed_run_async(db_path, **kwargs))


async def _seed_event_async(
    db_path: Path,
    *,
    run_id: str,
    event_type: str,
    timestamp: str = "2026-06-01T10:00:00Z",
    node_id: str | None = None,
    duration_ms: int | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO events (run_id, node_id, event_type, timestamp, "
            "duration_ms, data_json) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, node_id, event_type, timestamp, duration_ms,
             json.dumps(data or {})),
        )
        await conn.commit()


def _seed_event(db_path: Path, **kwargs: Any) -> None:
    _run_sync(_seed_event_async(db_path, **kwargs))


def _init_db(db_path: Path) -> None:
    _run_sync(store.init_db(db_path))


# ---------------------------------------------------------------------------
# harness runs — basic listing
# ---------------------------------------------------------------------------


def test_runs_command_registered_in_app() -> None:
    """runs must appear in the CLI help output."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "runs" in result.stdout


def test_runs_lists_recent_runs(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="R1", workflow_name="feature", status="completed")
    _seed_run(db_path, run_id="R2", workflow_name="bugfix", status="failed",
              exit_code=1)

    result = runner.invoke(app, ["runs", "--db", str(db_path)])
    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert "R1" in out
    assert "R2" in out
    assert "feature" in out
    assert "bugfix" in out


def test_runs_empty_db_exits_zero(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    _init_db(db_path)

    result = runner.invoke(app, ["runs", "--db", str(db_path)])
    assert result.exit_code == 0, result.stdout


def test_runs_limit_flag_restricts_output(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    for i in range(5):
        _seed_run(db_path, run_id=f"R{i}",
                  started_at=f"2026-06-01T10:0{i}:00Z")

    result = runner.invoke(app, ["runs", "--db", str(db_path), "--limit", "2"])
    assert result.exit_code == 0, result.stdout
    out = result.stdout
    # Only 2 rows should appear — count run IDs by "R" prefix appearances.
    run_ids_found = [f"R{i}" for i in range(5) if f"R{i}" in out]
    assert len(run_ids_found) <= 2


def test_runs_shows_status_column(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="RX", status="failed", exit_code=1)

    result = runner.invoke(app, ["runs", "--db", str(db_path)])
    assert result.exit_code == 0, result.stdout
    assert "failed" in result.stdout


# ---------------------------------------------------------------------------
# harness runs --failed — grouped by reason
# ---------------------------------------------------------------------------


def test_runs_failed_groups_by_reason(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="F1", status="failed", workflow_name="wf")
    _seed_run(db_path, run_id="F2", status="failed", workflow_name="wf")
    _seed_event(
        db_path, run_id="F1", event_type="workflow_failed",
        data={"reason": "ContractViolation"},
    )
    _seed_event(
        db_path, run_id="F2", event_type="workflow_failed",
        data={"reason": "ContractViolation"},
    )

    result = runner.invoke(app, ["runs", "--db", str(db_path), "--failed"])
    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert "ContractViolation" in out
    assert "F1" in out
    assert "F2" in out


def test_runs_failed_groups_different_reasons_separately(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="FA", status="failed")
    _seed_run(db_path, run_id="FB", status="failed")
    _seed_event(
        db_path, run_id="FA", event_type="workflow_failed",
        data={"reason": "ContractViolation"},
    )
    _seed_event(
        db_path, run_id="FB", event_type="workflow_failed",
        data={"reason": "CheckFailed"},
    )

    result = runner.invoke(app, ["runs", "--db", str(db_path), "--failed"])
    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert "ContractViolation" in out
    assert "CheckFailed" in out
    # Both run IDs must appear.
    assert "FA" in out
    assert "FB" in out


def test_runs_failed_no_failures_shows_message(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="R1", status="completed")

    result = runner.invoke(app, ["runs", "--db", str(db_path), "--failed"])
    assert result.exit_code == 0, result.stdout
    assert "no failure" in result.stdout.lower() or "(no failures)" in result.stdout


def test_runs_missing_db_exits_zero_empty(tmp_path: Path) -> None:
    """Missing DB should exit 0 with empty/no output (not an error condition)."""
    db_path = tmp_path / ".harness" / "harness.db"

    result = runner.invoke(app, ["runs", "--db", str(db_path)])
    assert result.exit_code == 0, result.stdout
