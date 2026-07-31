"""``review``'s terminal-observation write — the denominator's one seam (#262).

``review`` recorded an event only where a verdict parsed. Every other way the
verb can end — an engine timeout, a tripped spend breaker, ``no_design``,
``no_gate_evidence``, a red gate, the sandbox wall, an unreadable HEAD — returned
without writing anything, so the ledger held 380 verdicts and **no denominator**.
"How often does review succeed?" and "how often does the engine time out?" were
not slow questions; they were unanswerable ones.

This module is the writer those paths call. It lives outside
:mod:`harness.cli.review` on the ``design_tracker`` / ``close_tracker`` /
``review_inherit`` precedent — the verb is watchlisted and already over a
thousand lines, and the alternative was inlining an emit at ten raise sites,
where the tenth would eventually be forgotten and the denominator would go
quietly wrong rather than loudly missing.

**Observation is subordinate to the thing observed** (ADR 0009). A verb that has
already decided to refuse must refuse with exactly the exit code, ``reason`` and
printed JSON it would have had before this module existed. That rule now lives in
:func:`harness.events.observation.emit_observation`, which swallows *every*
exception the write can raise, down to a database that will not open — extracted
there on its second caller (#263's ``close`` writer) so the two verbs cannot
enforce it unevenly. What stays here is this verb's payload. The one thing
neither does is guess: a path with no run resolved never reaches here, because
there is no run to anchor the row to (ADR 0009 records the same for ``close``'s
``no_run``).
"""

from __future__ import annotations

from pathlib import Path

from harness._time import elapsed_ms, iso_z
from harness.events.observation import emit_observation
from harness.events.payloads import REVIEW_UNEXPECTED_REASON, ReviewRefusalEventData

__all__ = ["record_terminal_refusal"]


async def record_terminal_refusal(
    db_path: Path,
    *,
    run_id: str,
    reason: str | None,
    detail: str,
    invoked_at: str,
) -> None:
    """Append the ``review`` event for a terminal path that produced no verdict.

    Args:
        db_path: The run's ledger.
        run_id: The resolved run. A caller with none must not call this.
        reason: The verb's own machine-readable literal, or ``None`` for a raise
            site that carries none — mapped to
            :data:`~harness.events.payloads.REVIEW_UNEXPECTED_REASON` so those
            paths stay distinguishable from one another in the aggregate rather
            than collapsing into a NULL.
        detail: The human specifics (the refusal's own message).
        invoked_at: When the verb began work on this run, for the duration.

    The row carries **no ``verdict`` key**, which is what keeps the close gate
    exactly as wide as it was: :func:`~harness.cli._review_gate.certify_head`
    filters ``$.verdict = 'pass'`` and a missing key answers ``NULL``. So this
    cannot open a gate however it is called — enforcement by absence, pinned by
    test rather than left to inspection.

    Never raises.
    """
    created_at = iso_z()
    data = ReviewRefusalEventData(
        run_id=run_id,
        reason=reason or REVIEW_UNEXPECTED_REASON,
        detail=detail,
        created_at=created_at,
        invoked_at=invoked_at,
        duration_ms=elapsed_ms(invoked_at, created_at),
    ).model_dump(exclude_none=True)

    await emit_observation(db_path, run_id=run_id, event_type="review", data=data)
