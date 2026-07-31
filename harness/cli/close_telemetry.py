"""``close``'s terminal-observation write — the refusal denominator (#263).

``close`` recorded an event only where the close *landed*. Every gate refusal —
``dirty_worktree``, ``no_passing_review``, ``stale_review``, ``no_gate_evidence``
— raised before any ledger write, and so did the post-merge ticket failures. The
ledger therefore held landed merges and no denominator: "how often does the gate
refuse, and for what?" was not a slow question but an unanswerable one. ADR 0010
had to accept a 24-excess-pass *upper bound* for the ``stale_review`` rate for
exactly this reason; this module is what turns that bound into a measurement.

It is the payload builder those paths call, living outside
:mod:`harness.cli.close` on the :mod:`~harness.cli.close_tracker` /
:mod:`~harness.cli.review_telemetry` precedent — ``close.py`` is watchlisted, and
the alternative was inlining an emit at every raise site, where the last one
added would eventually be forgotten and the denominator would go quietly wrong
rather than loudly missing. The never-raises write itself is
:func:`~harness.events.observation.emit_observation` (ADR 0009), shared with
``review``'s writer.

The one thing this does not do is guess: a refusal with no resolved run never
reaches here, because ``events.run_id`` is ``NOT NULL`` with a foreign key to
``runs`` and there is nothing to anchor the row to (the accepted ``no_run`` gap,
ADR 0009).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harness._time import elapsed_ms, iso_z
from harness.events.observation import emit_observation
from harness.events.payloads import (
    CLOSE_OUTCOME_FAILED,
    CLOSE_OUTCOME_REFUSED,
    CLOSE_UNEXPECTED_REASON,
    CloseFailureEventData,
)

__all__ = ["CloseAttempt", "outcome_for_exit_code", "record_terminal_close"]


@dataclass
class CloseAttempt:
    """What the terminal-event recorder needs about an in-flight attempt (#263).

    ``merged_sha`` is set the instant the merge lands and read by the ``except``
    handler, so a recorded row says whether the merge landed on *every* failing
    path — including the step-8 ledger-write failure, which happens after the
    merge and carries no ``reason``. ``_CloseError.extra={"merged": True}`` is
    deliberately not reused for this (it is set at only the two ticket-transition
    sites, so that failure would record as un-merged — the exact misreport the
    invariant exists to prevent), and the SHA is deliberately not put *into*
    ``extra``, which ``run_verb`` merges into the printed JSON this change holds
    fixed.
    """

    invoked_at: str
    merged_sha: str | None = None


#: The verb's gate-refusal exit code (``close.py``'s documented contract): the
#: verb declined before any side effect.
_REFUSAL_EXIT_CODE = 2


def outcome_for_exit_code(exit_code: int) -> str:
    """Map the verb's exit code onto the payload's ``outcome`` discriminator.

    Exit 2 is :data:`CLOSE_OUTCOME_REFUSED` — the gate declined and *nothing
    happened*; anything else is :data:`CLOSE_OUTCOME_FAILED`. Deriving the
    outcome from the exit code rather than from which ``reason`` fired is
    deliberate: the exit code is the signal the verb already publishes and
    documents, so the recorded outcome cannot drift from it — whereas a
    reason-to-outcome membership table is something a later ``reason`` lands on
    the wrong side of, silently.

    Note this says nothing about whether the merge landed. That is
    ``merged_sha``'s job, and the two are genuinely independent: a ticket
    transition can fail (exit 1) with the merge already landed.
    """
    return CLOSE_OUTCOME_REFUSED if exit_code == _REFUSAL_EXIT_CODE else CLOSE_OUTCOME_FAILED


async def record_terminal_close(
    db_path: Path,
    *,
    run_id: str,
    ticket: str,
    exit_code: int,
    reason: str | None,
    detail: str,
    merged_sha: str | None,
    invoked_at: str,
) -> None:
    """Append the ``close`` event for a terminal path that did not land the close.

    Args:
        db_path: The run's ledger.
        run_id: The resolved run. A caller with none must not call this.
        ticket: The ticket the close was for.
        exit_code: The verb's exit code, mapped by :func:`outcome_for_exit_code`.
        reason: The verb's own machine-readable literal, or ``None`` for a raise
            site that carries none — mapped to :data:`CLOSE_UNEXPECTED_REASON` so
            those paths stay distinguishable from one another in the aggregate
            rather than collapsing into a NULL.
        detail: The human specifics (the refusal's own message).
        merged_sha: The merged SHA **iff the merge already landed**, else
            ``None``. Written only to the ledger, so the printed refusal JSON is
            unchanged.
        invoked_at: When the verb began work on this run, for the duration.

    ``merged_sha``'s presence is what keeps #233's "a ``close`` event means the
    tracker was confirmed Done" claim as narrow as it was: a reader keying on the
    merged SHA still cannot be satisfied by a gate refusal, and a post-merge
    failure is not misreported as a blocked one.

    Never raises.
    """
    created_at = iso_z()
    data = CloseFailureEventData(
        run_id=run_id,
        ticket=ticket,
        outcome=outcome_for_exit_code(exit_code),
        reason=reason or CLOSE_UNEXPECTED_REASON,
        detail=detail,
        created_at=created_at,
        merged_sha=merged_sha,
        invoked_at=invoked_at,
        duration_ms=elapsed_ms(invoked_at, created_at),
    ).model_dump(exclude_none=True)

    await emit_observation(db_path, run_id=run_id, event_type="close", data=data)
