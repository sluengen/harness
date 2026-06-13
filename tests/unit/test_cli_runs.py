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


def test_runs_failed_entry_line_has_no_trailing_residue(tmp_path: Path) -> None:
    """A failed-run entry renders exactly run_id / workflow / started_at — no
    trailing format slot (guards against re-introducing engine-era residue like
    the removed empty ``node_info`` interpolation)."""
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(
        db_path, run_id="F1", workflow_name="wf", status="failed",
        started_at="2026-06-01T10:00:00Z",
    )
    _seed_event(
        db_path, run_id="F1", event_type="workflow_failed",
        data={"reason": "ContractViolation"},
    )

    result = runner.invoke(app, ["runs", "--db", str(db_path), "--failed"])
    assert result.exit_code == 0, result.stdout

    entry_lines = [
        line for line in result.stdout.splitlines() if "F1" in line
    ]
    assert entry_lines == ["  F1  wf  2026-06-01T10:00:00Z"]


def test_runs_failed_no_failures_shows_message(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="R1", status="completed")

    result = runner.invoke(app, ["runs", "--db", str(db_path), "--failed"])
    assert result.exit_code == 0, result.stdout
    assert "no failure" in result.stdout.lower() or "(no failures)" in result.stdout


async def _seed_raw_event_async(
    db_path: Path,
    *,
    run_id: str,
    event_type: str,
    data_json: str,
    timestamp: str = "2026-06-01T10:00:00Z",
) -> None:
    """Insert an event with a verbatim ``data_json`` payload.

    Unlike :func:`_seed_event` (which ``json.dumps`` a dict), this seeds the
    column with the exact bytes given — so a malformed/non-dict blob can be
    exercised.
    """
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO events (run_id, node_id, event_type, timestamp, "
            "duration_ms, data_json) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, None, event_type, timestamp, None, data_json),
        )
        await conn.commit()


def _seed_raw_event(db_path: Path, **kwargs: Any) -> None:
    _run_sync(_seed_raw_event_async(db_path, **kwargs))


def test_runs_failed_malformed_data_json_lands_under_unknown(tmp_path: Path) -> None:
    """A ``workflow_failed`` event with a malformed (non-JSON) ``data_json``
    must not crash the grouping — the run lands under ``(unknown reason)``.

    Locks the tolerant-decode equivalence: the shared ``_safe_json_loads``
    surfaces an undecodable blob as the empty reason, exactly as the inline
    ``try/except (TypeError, ValueError)`` did before the dedup.
    """
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="FM", status="failed", workflow_name="wf")
    _seed_raw_event(
        db_path, run_id="FM", event_type="workflow_failed",
        data_json="not-valid-json",
    )

    result = runner.invoke(app, ["runs", "--db", str(db_path), "--failed"])
    assert result.exit_code == 0, result.stdout
    assert "(unknown reason)" in result.stdout
    assert "FM" in result.stdout


def test_runs_failed_non_dict_data_json_lands_under_unknown(tmp_path: Path) -> None:
    """A ``data_json`` that decodes to valid-but-non-dict JSON (e.g. a bare
    string) also lands under ``(unknown reason)`` — ``reason`` is only read
    from a dict payload."""
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="FN", status="failed", workflow_name="wf")
    _seed_raw_event(
        db_path, run_id="FN", event_type="workflow_failed",
        data_json='"just a string"',
    )

    result = runner.invoke(app, ["runs", "--db", str(db_path), "--failed"])
    assert result.exit_code == 0, result.stdout
    assert "(unknown reason)" in result.stdout
    assert "FN" in result.stdout


def test_runs_uses_shared_safe_json_loads() -> None:
    """``runs`` decodes the ``workflow_failed`` ``data_json`` blob via the
    shared ``_query_common._safe_json_loads`` — the same tolerant decoder
    ``status`` / ``events`` use — not a private hand-rolled copy.

    Binding the same function object keeps the decode policy single-sourced
    (mirrors ``test_cancel_uses_shared_resolve_db_path`` for ``_resolve_db_path``).
    Once the shared helper owns the decode, the module-scope ``import json`` is
    dead and must not linger.
    """
    from harness.cli import _query_common, query_runs

    assert query_runs._safe_json_loads is _query_common._safe_json_loads
    assert not hasattr(query_runs, "json"), (
        "query_runs should not import json directly; decode via _safe_json_loads"
    )


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
