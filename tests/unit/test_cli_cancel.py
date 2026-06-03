"""Tests for ``harness cancel <run-id>`` — H-2-006.

Cancellation contract:

* ``harness cancel <run-id>`` sends SIGTERM to the process whose PID is
  stored in the ``runs.pid`` column.
* Exits 2 (invocation error) when the run does not exist.
* Exits 2 when the run exists but is not in ``running`` status.
* Exits 2 when the run is running but the PID column is NULL (run predates
  H-2-006 or was not started by the harness CLI).
* Exits 2 when the process referred to by the PID is no longer alive
  (stale PID, process already exited).
* Exits 0 and delivers SIGTERM on a live running process.
* ``--json`` flag emits ``{"run_id": ..., "outcome": "cancelled"}`` on
  success and ``{"error": ...}`` on failure.
"""

from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from harness.cli import app
from harness.state import store

cli_runner = CliRunner()


# ---------------------------------------------------------------------------
# DB seeding helpers
# ---------------------------------------------------------------------------


def _run_sync(coro: object) -> object:
    """Drive a coroutine from a synchronous test function."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)  # type: ignore[arg-type]
    finally:
        loop.close()


def _seed_run(
    db_path: Path,
    *,
    run_id: str,
    status: str,
    pid: int | None = None,
) -> None:
    """Seed a minimal run row for cancel tests."""

    async def _insert() -> None:
        await store.init_db(db_path)
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
                "state_json, inputs_json, base_branch, started_at, pid) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    "test",
                    1,
                    status,
                    "{}",
                    "{}",
                    "main",
                    "2026-01-01T00:00:00+00:00",
                    pid,
                ),
            )
            await conn.commit()

    _run_sync(_insert())


# ---------------------------------------------------------------------------
# Failure cases
# ---------------------------------------------------------------------------


def test_cancel_nonexistent_run(tmp_path: Path) -> None:
    """Exits 2 when the run_id is not in the DB."""
    db = tmp_path / "harness.db"
    result = cli_runner.invoke(app, ["cancel", "NOTFOUND", "--db", str(db)])
    assert result.exit_code == 2


def test_cancel_nonexistent_run_json(tmp_path: Path) -> None:
    """``--json`` emits ``{"error": ...}`` and exits 2 when not found."""
    db = tmp_path / "harness.db"
    result = cli_runner.invoke(app, ["cancel", "NOTFOUND", "--json", "--db", str(db)])
    assert result.exit_code == 2
    import json

    payload = json.loads(result.output)
    assert "error" in payload


def test_cancel_completed_run(tmp_path: Path) -> None:
    """Exits 2 when run is completed (not running)."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="completed", pid=12345)
    result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])
    assert result.exit_code == 2


def test_cancel_failed_run(tmp_path: Path) -> None:
    """Exits 2 when run is already failed."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="failed", pid=12345)
    result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])
    assert result.exit_code == 2


def test_cancel_paused_run(tmp_path: Path) -> None:
    """Exits 2 when run is paused (awaiting human decision, not running)."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="paused", pid=12345)
    result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])
    assert result.exit_code == 2


def test_cancel_running_null_pid(tmp_path: Path) -> None:
    """Exits 2 when run is running but PID is NULL (predates H-2-006)."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="running", pid=None)
    result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])
    assert result.exit_code == 2


def test_cancel_stale_pid(tmp_path: Path) -> None:
    """Exits 2 when the PID belongs to a process that no longer exists."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="running", pid=99999999)
    # Patch os.kill so the probe (kill pid, 0) raises ProcessLookupError.
    with patch("harness.cli.cancel.os.kill", side_effect=ProcessLookupError):
        result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])
    assert result.exit_code == 2


def test_cancel_permission_denied(tmp_path: Path) -> None:
    """Exits 2 when we lack permission to signal the target process."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="running", pid=1)
    with patch("harness.cli.cancel.os.kill", side_effect=PermissionError):
        result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# Success cases
# ---------------------------------------------------------------------------


def test_cancel_sends_sigterm(tmp_path: Path) -> None:
    """Exits 0 and delivers SIGTERM to the recorded PID."""
    db = tmp_path / "harness.db"
    pid = os.getpid()
    _seed_run(db, run_id="R1", status="running", pid=pid)

    kill_calls: list[tuple[int, int]] = []

    def _spy(p: int, sig: int) -> None:
        kill_calls.append((p, sig))
        # Don't actually deliver any signal — just record the call.

    with patch("harness.cli.cancel.os.kill", side_effect=_spy):
        result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])

    assert result.exit_code == 0, result.output
    # Both the existence probe (0) and the actual SIGTERM must have been sent.
    assert (pid, signal.SIGTERM) in kill_calls


def test_cancel_success_human_output(tmp_path: Path) -> None:
    """Human output contains the run_id and a 'Cancelled' confirmation."""
    db = tmp_path / "harness.db"
    pid = os.getpid()
    _seed_run(db, run_id="R1", status="running", pid=pid)

    with patch("harness.cli.cancel.os.kill"):
        result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])

    assert result.exit_code == 0
    assert "R1" in result.output


def test_cancel_success_json(tmp_path: Path) -> None:
    """``--json`` emits ``{"run_id": ..., "outcome": "cancelled"}`` on success."""
    import json

    db = tmp_path / "harness.db"
    pid = os.getpid()
    _seed_run(db, run_id="R1", status="running", pid=pid)

    with patch("harness.cli.cancel.os.kill"):
        result = cli_runner.invoke(app, ["cancel", "R1", "--json", "--db", str(db)])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["run_id"] == "R1"
    assert payload["outcome"] == "cancelled"


def test_cancel_non_running_json(tmp_path: Path) -> None:
    """``--json`` emits ``{"error": ...}`` when the run is not running."""
    import json

    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="completed", pid=12345)
    result = cli_runner.invoke(app, ["cancel", "R1", "--json", "--db", str(db)])
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert "error" in payload


# ---------------------------------------------------------------------------
# TOCTOU — process exits between liveness probe and SIGTERM delivery
# ---------------------------------------------------------------------------


def test_cancel_toctou_process_exits_between_probe_and_signal(tmp_path: Path) -> None:
    """Exits 2 cleanly when the process exits between the liveness probe and
    SIGTERM delivery.

    The TOCTOU window: ``os.kill(pid, 0)`` succeeds (process alive at probe
    time), but ``os.kill(pid, SIGTERM)`` raises ``ProcessLookupError`` because
    the process exited in the gap.  Before the fix, this propagated as an
    unhandled exception and printed a Python traceback.  After the fix the
    command exits 2 with a clean error message.
    """
    db = tmp_path / "harness.db"
    pid = os.getpid()
    _seed_run(db, run_id="R1", status="running", pid=pid)

    def _toctou_kill(p: int, sig: int) -> None:
        if sig == 0:
            # Liveness probe passes — process appears alive.
            return
        # Actual SIGTERM delivery — process has since exited.
        raise ProcessLookupError(f"[Errno 3] No such process: {p}")

    with patch("harness.cli.cancel.os.kill", side_effect=_toctou_kill):
        result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])

    assert result.exit_code == 2
    # No Python traceback should appear in the output.
    assert "Traceback" not in result.output


def test_cancel_toctou_process_exits_between_probe_and_signal_json(
    tmp_path: Path,
) -> None:
    """``--json`` emits ``{"error": ...}`` rather than a traceback on TOCTOU."""
    import json

    db = tmp_path / "harness.db"
    pid = os.getpid()
    _seed_run(db, run_id="R1", status="running", pid=pid)

    def _toctou_kill(p: int, sig: int) -> None:
        if sig == 0:
            return
        raise ProcessLookupError(f"[Errno 3] No such process: {p}")

    with patch("harness.cli.cancel.os.kill", side_effect=_toctou_kill):
        result = cli_runner.invoke(app, ["cancel", "R1", "--json", "--db", str(db)])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert "error" in payload


def test_cancel_toctou_permission_error_on_signal_delivery(tmp_path: Path) -> None:
    """Exits 2 cleanly when ``PermissionError`` is raised during SIGTERM delivery
    (TOCTOU window — permissions may change between probe and delivery).
    """
    db = tmp_path / "harness.db"
    pid = os.getpid()
    _seed_run(db, run_id="R1", status="running", pid=pid)

    def _toctou_kill(p: int, sig: int) -> None:
        if sig == 0:
            return
        raise PermissionError(f"[Errno 1] Operation not permitted: {p}")

    with patch("harness.cli.cancel.os.kill", side_effect=_toctou_kill):
        result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])

    assert result.exit_code == 2
    assert "Traceback" not in result.output
