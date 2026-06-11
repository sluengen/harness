"""CLI surface for ``harness cancel <run-id>`` — abandon a run (CAL-587).

Under the verb model ``cancel`` is the *abandon / close-without-merge*
transition — the third terminal outcome alongside ``close`` (merged) and a
run that simply never finishes.  It does **not** signal any process: the
engine-era ``harness run`` daemon it used to SIGTERM no longer exists.
``harness start`` writes a ledger row and exits, so the recorded ``runs.pid``
was dead on arrival and the old SIGTERM path could only ever hit its refusal
branches.  CAL-587 redefines the verb for the contract it actually serves:

1. Resolve the ``runs`` row for ``run-id``.
2. Cancel only from an explicit in-flight allowlist (``open`` plus the legacy
   ``running`` / ``pending`` / ``paused`` / ``stalled``). Refuse a terminal run
   (``closed`` / ``cancelled`` / ``completed`` / ``failed``) and refuse an
   unrecognised status — an allowlist, not a denylist, so an unknown or future
   status is never silently overwritten.
3. In **one transaction**, mark the run ``status='cancelled'`` + stamp
   ``completed_at`` *and* append a
   ``workflow_failed`` event with ``reason='cancelled'``. Both land together or
   not at all — a run marked ``cancelled`` with no cancellation event is an
   inconsistent ledger that retry cannot repair (a terminal run refuses
   re-cancel). ``harness status`` then surfaces ``failure_reason='cancelled'``
   (and ``failure_retryable=False``).

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

from harness.events.schema import EVENT_TYPES
from harness.state import store
from harness.state.schema import RUN_STATUSES

__all__ = ["cancel_command"]

#: In-flight statuses a run can be abandoned *from* — an explicit allowlist, not
#: a terminal denylist. The verb model only ever writes ``open``; the rest are
#: legacy engine / intake states that may still appear on historical rows. An
#: allowlist means an unknown or future status is **refused**, never silently
#: overwritten to ``cancelled``.
_CANCELLABLE_STATUSES: frozenset[str] = frozenset(
    {"open", "running", "pending", "paused", "stalled"}
)
# The allowlist must stay a subset of the canonical run-status set.
assert _CANCELLABLE_STATUSES <= RUN_STATUSES

#: The cancellation event. ``workflow_failed`` with ``reason='cancelled'`` is the
#: canonical mark (a member of :data:`EVENT_TYPES`) that ``harness status`` reads
#: to derive ``failure_reason='cancelled'`` / ``failure_retryable=False``.
_CANCEL_EVENT_TYPE = "workflow_failed"
_CANCEL_REASON = "cancelled"
assert _CANCEL_EVENT_TYPE in EVENT_TYPES  # guard against a future rename drift


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
    event_ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    event_data = json.dumps({"reason": _CANCEL_REASON})

    async with store.connect(db_path) as conn:
        # The status flip and the audit event must land together: a run marked
        # `cancelled` with no cancellation event is an inconsistent ledger that
        # retry cannot repair (a terminal run refuses re-cancel). So both writes
        # share one transaction — commit once, or roll back together.
        await conn.execute("BEGIN IMMEDIATE")
        try:
            cur = await conn.execute(
                "SELECT status FROM runs WHERE run_id = ?", (run_id,)
            )
            row = await cur.fetchone()
            if row is None:
                raise _CancelError(f"no run with run_id={run_id!r}", 2)

            status = str(row[0])
            if status not in _CANCELLABLE_STATUSES:
                # Refuse anything not on the allowlist. Distinguish a known
                # terminal run from an unrecognised status for a clearer
                # message, but never overwrite either.
                if status in RUN_STATUSES:
                    raise _CancelError(
                        f"run {run_id!r} is already terminal (status={status!r}); "
                        "only an in-flight run can be cancelled",
                        2,
                    )
                raise _CancelError(
                    f"run {run_id!r} has an unrecognised status {status!r}; "
                    "refusing to cancel",
                    2,
                )

            # Guard the transition on the exact status we observed — optimistic
            # concurrency. If a close/cancel raced in between the read above and
            # here, the status differs and zero rows change: refuse rather than
            # overwrite a terminal state.
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

            # Append the cancellation event in the same transaction (mirrors
            # EventEmitter's INSERT; inlined here so it shares the commit).
            await conn.execute(
                "INSERT INTO events (run_id, node_id, event_type, timestamp, "
                "duration_ms, data_json) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, None, _CANCEL_EVENT_TYPE, event_ts, None, event_data),
            )
            await conn.commit()
        except _CancelError:
            await conn.rollback()
            raise
        except Exception as exc:  # noqa: BLE001
            await conn.rollback()
            raise _CancelError(f"failed to record cancellation: {exc}", 1) from exc


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
