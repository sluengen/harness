"""Tests for harness runs command — list recent runs."""

from __future__ import annotations

import asyncio
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


def test_runs_missing_db_exits_zero_empty(tmp_path: Path) -> None:
    """Missing DB should exit 0 with empty/no output (not an error condition)."""
    db_path = tmp_path / ".harness" / "harness.db"

    result = runner.invoke(app, ["runs", "--db", str(db_path)])
    assert result.exit_code == 0, result.stdout


def test_runs_docstring_exit_codes_match_contract() -> None:
    """The module docstring's exit-code block must match the tested behaviour.

    ``runs`` is a list command with no run-id: a missing DB is the empty case
    (exit 0), not an invocation error. The run-id read commands
    (``status``/``events``) exit 2 on a missing DB because the run cannot be
    found, and that wording must not leak into ``runs``. Guards against the
    docstring drifting back to the copied "missing DB → exit 2" claim that
    ``test_runs_missing_db_exits_zero_empty`` proves false.
    """
    from harness.cli import query_runs

    doc = query_runs.__doc__ or ""
    exit_block = doc[doc.index("Exit codes") :]
    two_line = next(
        line for line in exit_block.splitlines() if line.lstrip().startswith("* 2")
    )
    assert "missing DB" not in two_line, (
        "runs exits 0 (not 2) on a missing DB; remove the copied claim"
    )
    assert "missing or empty DB" in exit_block, (
        "docstring should document the exit-0 missing/empty-DB case"
    )
