"""CLI surface for ``harness cancel <run-id>`` — abandon a run (CAL-587).

Under the verb model ``cancel`` is the *abandon / close-without-merge*
transition — the third terminal outcome alongside ``close`` (merged) and a
run that simply never finishes.  It does **not** signal any process: the
engine-era ``harness run`` daemon it used to SIGTERM no longer exists.
``harness start`` writes a ledger row and exits, so the recorded ``runs.pid``
was dead on arrival and the old SIGTERM path could only ever hit its refusal
branches.  CAL-587 redefines the verb for the contract it actually serves:

1. Resolve the ``runs`` row for ``run-id``.
2. Refuse if the run is already terminal (``closed`` / ``cancelled`` /
   ``completed`` / ``failed``) — there is nothing to abandon.
3. Mark the run ``status='cancelled'`` and stamp ``completed_at`` (mirroring
   ``intake.cancel_run``), then emit a ``workflow_failed`` event with
   ``reason='cancelled'`` so ``harness status`` surfaces
   ``failure_reason='cancelled'`` (and ``failure_retryable=False``).

This keeps the public verb contract (SPEC §5) and the launcher ``cancel`` op
honest: the verb now does what its name promises and leaves an auditable mark
on the one ledger that is the whole audit trail.

Exit codes (SPEC §11):
* 0  — run abandoned; ``{"run_id": ..., "outcome": "cancelled"}``.
* 2  — invocation error: unknown run-id, or the run is already terminal.
* 1  — unexpected error (DB failure).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import typer

from harness.events.emitter import EventEmitter
from harness.state import store

__all__ = ["cancel_command"]

#: Statuses from which a run can no longer be abandoned — already finalised.
#: Everything else (``open`` under the verb model, plus the legacy ``running`` /
#: ``pending`` / ``paused`` / ``stalled`` the retired engine and intake path
#: still write) is in-flight and therefore cancellable.
_TERMINAL_STATUSES: tuple[str, ...] = ("closed", "cancelled", "completed", "failed")


def _resolve_db_path(db: Path | None) -> Path:
    """``--db`` override or the default ``.harness/harness.db`` under CWD."""
    if db is not None:
        return db
    return Path.cwd() / store.DEFAULT_DB_PATH


class _CancelError(Exception):
    """Internal control-flow exception carrying a message and an exit code."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


async def _run_cancel(db_path: Path, run_id: str) -> None:
    """Abandon the run; raise :class:`_CancelError` on refusal or error."""
    if not db_path.exists():
        raise _CancelError(f"no run with run_id={run_id!r}", 2)

    completed_at = datetime.now(UTC).isoformat()
    async with store.connect(db_path) as conn:
        cur = await conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
        row = await cur.fetchone()
        if row is None:
            raise _CancelError(f"no run with run_id={run_id!r}", 2)

        status = str(row[0])
        if status in _TERMINAL_STATUSES:
            raise _CancelError(
                f"run {run_id!r} is already terminal (status={status!r}); "
                "only an in-flight run can be cancelled",
                2,
            )

        # Guard the transition on the exact status we observed — optimistic
        # concurrency. If a close/cancel raced in between the read above and
        # here, the status differs, zero rows change, and we refuse rather than
        # overwrite a terminal state (and emit no event).
        update = await conn.execute(
            "UPDATE runs SET status = 'cancelled', completed_at = ? "
            "WHERE run_id = ? AND status = ?",
            (completed_at, run_id, status),
        )
        if update.rowcount == 0:
            raise _CancelError(
                f"run {run_id!r} changed state concurrently; only an in-flight "
                "run can be cancelled",
                2,
            )
        await conn.commit()

    # Emit the terminal event AFTER the status flip commits, so a failed write
    # never leaves a `workflow_failed` event on a run that is still open.
    await EventEmitter(db_path).emit(
        run_id=run_id,
        event_type="workflow_failed",
        data={"reason": "cancelled"},
    )


def cancel_command(
    run_id: str = typer.Argument(..., help="Run identifier (ULID)."),
    db: Path | None = typer.Option(
        None,
        "--db",
        help="Path to harness.db (defaults to .harness/harness.db).",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Abandon an in-flight run — mark it cancelled and record the abandonment."""
    db_path = _resolve_db_path(db)

    try:
        asyncio.run(_run_cancel(db_path, run_id))
    except _CancelError as exc:
        if json_output:
            typer.echo(json.dumps({"error": exc.message}))
        else:
            typer.echo(exc.message, err=True)
        raise typer.Exit(code=exc.code) from exc

    if json_output:
        typer.echo(json.dumps({"run_id": run_id, "outcome": "cancelled"}))
    else:
        typer.echo(f"Cancelled run {run_id} (abandoned — not merged)")
