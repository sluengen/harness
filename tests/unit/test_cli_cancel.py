"""Tests for ``harness cancel <run-id>`` — abandon a run (CAL-587).

Under the verb model ``cancel`` is the *abandon / close-without-merge*
transition.  It does **not** signal any process — the engine-era ``harness run``
daemon it used to SIGTERM no longer exists (``harness start`` writes a ledger
row and exits, so its recorded PID was dead on arrival and ``cancel`` could only
ever hit its refusal paths).  The redefined contract:

* ``harness cancel <run-id>`` marks an in-flight run ``status='cancelled'``,
  stamps ``completed_at``, and emits a ``workflow_failed`` event with
  ``reason='cancelled'`` (so ``harness status`` surfaces
  ``failure_reason='cancelled'`` / ``failure_retryable=False``).
* Exits 2 (invocation error) when the run does not exist.
* Exits 2 when the run is already terminal (``closed`` / ``cancelled`` /
  ``completed`` / ``failed``) — there is nothing to abandon.
* Exits 0 and abandons the run for any in-flight status (``open`` plus the
  legacy ``running`` / ``pending`` the intake path still marks), with no PID
  required.
* ``--json`` emits ``{"run_id": ..., "outcome": "cancelled"}`` on success and
  ``{"error": ...}`` on failure.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from harness.cli import app
from harness.state import store

cli_runner = CliRunner()


# ---------------------------------------------------------------------------
# DB seeding / inspection helpers
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


def _fetch_row(db_path: Path, run_id: str) -> dict[str, Any] | None:
    """Return ``status`` + ``completed_at`` for ``run_id`` (or ``None``)."""

    async def _select() -> dict[str, Any] | None:
        async with store.connect(db_path) as conn:
            cur = await conn.execute(
                "SELECT status, completed_at FROM runs WHERE run_id = ?", (run_id,)
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return {"status": row[0], "completed_at": row[1]}

    return _run_sync(_select())  # type: ignore[return-value]


def _fetch_events(db_path: Path, run_id: str, event_type: str) -> list[dict[str, Any]]:
    """Return ``data_json``-parsed events of ``event_type`` for ``run_id``."""

    async def _select() -> list[dict[str, Any]]:
        async with store.connect(db_path) as conn:
            cur = await conn.execute(
                "SELECT data_json FROM events WHERE run_id = ? AND event_type = ?",
                (run_id, event_type),
            )
            rows = await cur.fetchall()
        return [json.loads(r[0]) for r in rows]

    return _run_sync(_select())  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Refusal cases
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
    payload = json.loads(result.output)
    assert "error" in payload


def test_cancel_closed_run_refused(tmp_path: Path) -> None:
    """Exits 2 when the run is already closed (terminal — nothing to abandon)."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="closed")
    result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])
    assert result.exit_code == 2
    # The row is untouched.
    assert _fetch_row(db, "R1") == {"status": "closed", "completed_at": None}
    # No workflow_failed event is emitted on a refusal.
    assert _fetch_events(db, "R1", "workflow_failed") == []


def test_cancel_already_cancelled_run_refused(tmp_path: Path) -> None:
    """Exits 2 when the run is already cancelled — idempotent refusal, no dup event."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="cancelled")
    result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])
    assert result.exit_code == 2
    assert _fetch_events(db, "R1", "workflow_failed") == []


def test_cancel_completed_run_refused(tmp_path: Path) -> None:
    """Exits 2 when the run is a legacy ``completed`` (terminal)."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="completed")
    result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])
    assert result.exit_code == 2


def test_cancel_failed_run_refused(tmp_path: Path) -> None:
    """Exits 2 when the run is a legacy ``failed`` (terminal)."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="failed")
    result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])
    assert result.exit_code == 2


def test_cancel_refusal_json(tmp_path: Path) -> None:
    """``--json`` emits ``{"error": ...}`` when the run is terminal."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="closed")
    result = cli_runner.invoke(app, ["cancel", "R1", "--json", "--db", str(db)])
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert "error" in payload


# ---------------------------------------------------------------------------
# Success cases — abandon an in-flight run
# ---------------------------------------------------------------------------


def test_cancel_open_run_marks_cancelled(tmp_path: Path) -> None:
    """Exits 0 and flips an ``open`` run to ``cancelled`` with a completion stamp."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="open")
    result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])
    assert result.exit_code == 0, result.output

    row = _fetch_row(db, "R1")
    assert row is not None
    assert row["status"] == "cancelled"
    assert row["completed_at"] is not None


def test_cancel_open_run_needs_no_pid(tmp_path: Path) -> None:
    """A run with a NULL ``pid`` still cancels — the new path never reads pid."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="open", pid=None)
    result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert _fetch_row(db, "R1")["status"] == "cancelled"  # type: ignore[index]


def test_cancel_emits_workflow_failed_reason_cancelled(tmp_path: Path) -> None:
    """A ``workflow_failed`` event with ``reason='cancelled'`` is recorded."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="open")
    result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])
    assert result.exit_code == 0, result.output

    events = _fetch_events(db, "R1", "workflow_failed")
    assert len(events) == 1
    assert events[0].get("reason") == "cancelled"


def test_cancel_surfaces_failure_reason_in_status(tmp_path: Path) -> None:
    """After cancel, ``harness status`` reports ``failure_reason='cancelled'``
    and ``failure_retryable=False`` — the end-to-end observable contract."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="open")

    cancel_result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])
    assert cancel_result.exit_code == 0, cancel_result.output

    status_result = cli_runner.invoke(app, ["status", "R1", "--json", "--db", str(db)])
    assert status_result.exit_code == 0, status_result.output
    payload = json.loads(status_result.output)
    assert payload["status"] == "cancelled"
    assert payload["failure_reason"] == "cancelled"
    assert payload["failure_retryable"] is False


def test_cancel_legacy_running_run_abandoned(tmp_path: Path) -> None:
    """A legacy ``running`` run (intake-marked) is still abandonable."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="running")
    result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert _fetch_row(db, "R1")["status"] == "cancelled"  # type: ignore[index]


def test_cancel_success_human_output(tmp_path: Path) -> None:
    """Human output names the run on success."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="open")
    result = cli_runner.invoke(app, ["cancel", "R1", "--db", str(db)])
    assert result.exit_code == 0
    assert "R1" in result.output


def test_cancel_success_json(tmp_path: Path) -> None:
    """``--json`` emits ``{"run_id": ..., "outcome": "cancelled"}`` on success."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="open")
    result = cli_runner.invoke(app, ["cancel", "R1", "--json", "--db", str(db)])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["run_id"] == "R1"
    assert payload["outcome"] == "cancelled"


# ---------------------------------------------------------------------------
# Atomicity — the status flip and the audit event land together or not at all
# ---------------------------------------------------------------------------


def _drop_events_table(db_path: Path) -> None:
    """Drop the ``events`` table so the cancellation event INSERT fails."""

    async def _drop() -> None:
        async with store.connect(db_path) as conn:
            await conn.execute("DROP TABLE events")
            await conn.commit()

    _run_sync(_drop())


def test_cancel_event_write_failure_rolls_back_status(tmp_path: Path) -> None:
    """If the cancellation event cannot be written, the status flip is rolled back.

    A run marked ``cancelled`` with no ``workflow_failed`` event is an
    inconsistent ledger that retry cannot repair (a terminal run refuses
    re-cancel). The transition and the event must be atomic: when the event
    INSERT fails the run stays ``open`` and cancel exits non-zero (exit 1).
    """
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="open")
    _drop_events_table(db)

    result = cli_runner.invoke(app, ["cancel", "R1", "--json", "--db", str(db)])

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert "error" in payload
    # The status flip must NOT have persisted — the run is still abandonable.
    assert _fetch_row(db, "R1")["status"] == "open"  # type: ignore[index]
