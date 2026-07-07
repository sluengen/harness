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
   re-cancel). ``harness status`` then surfaces ``failure_reason='cancelled'``.

This keeps the public verb contract (SPEC §1) honest: the verb now does what its
name promises and leaves an auditable mark on the one ledger that is the whole
audit trail.

Exit codes (SPEC §11):
* 0  — run abandoned; ``{"run_id": ..., "outcome": "cancelled"}``.
* 2  — invocation error: unknown run-id, a run already terminal, or a run
       whose status is not on the in-flight allowlist (an unknown/future
       status is refused, never silently overwritten).
* 1  — unexpected error (DB failure).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import typer

from harness._time import iso_z
from harness.cli._abandon import AbandonError
from harness.cli._abandon import abandon_run_in_ledger as _abandon_in_ledger
from harness.cli._query_common import _resolve_db_path
from harness.cli._verb import run_verb
from harness.state import store

__all__ = ["cancel_command"]

#: The reason recorded on the ``workflow_failed`` event a cancel emits.
#: ``harness reclaim`` reuses the same shared transaction (:mod:`harness.cli
#: ._abandon`) with ``reason='reclaimed'``; the allowlist and event-type
#: invariants live there so both verbs share one ledger-write rule.
_CANCEL_REASON = "cancelled"


async def _run_cancel(db_path: Path, run_id: str) -> None:
    """Abandon the run; raise :class:`AbandonError` on refusal or error."""
    if not db_path.exists():
        raise AbandonError(f"no run with run_id={run_id!r}", 2)

    completed_at = datetime.now(UTC).isoformat()
    event_ts = iso_z()

    async with store.connect(db_path) as conn:
        # The status flip and the audit event must land together — see
        # :func:`harness.cli._abandon.abandon_run_in_ledger`, the one
        # transaction ``cancel`` and ``reclaim`` share.
        await _abandon_in_ledger(
            conn,
            run_id,
            reason=_CANCEL_REASON,
            completed_at=completed_at,
            event_ts=event_ts,
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

    run_verb(
        lambda: asyncio.run(_run_cancel(db_path, run_id)),
        json_output=json_output,
    )

    if json_output:
        typer.echo(json.dumps({"run_id": run_id, "outcome": "cancelled"}))
    else:
        typer.echo(f"Cancelled run {run_id} (abandoned — not merged)")
