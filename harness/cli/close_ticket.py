"""Verified ticket-Done transition — attempt, then observe (#233).

``close`` used to trust ``transition_to_done``'s acknowledgement as proof the
ticket reached Done: a mutation that did not raise was reported as
``ticket_done: true`` even when it silently did not take, or its response
never reached the caller. This module is the fix — attempt the transition,
then **read the state back**, so a recorded ``true`` means *observed*, not
*attempted*.

The layering mirrors :mod:`harness.cli.design_tracker`'s one-way discipline:
this module raises a tracker-shaped failure (:class:`TicketNotDoneError`) and
knows nothing of exit codes or ``reason`` tags — ``close`` owns that
vocabulary and translates.
"""

from __future__ import annotations

from harness.tracker import Tracker
from harness.tracker_errors import TrackerNotFound, TrackerRequestError

__all__ = ["TicketNotDoneError", "confirm_ticket_done"]

#: Bounded, deterministic retries — no sleep/backoff. A wedged tracker must not
#: burn the run's wall-clock budget; surfacing after two attempts hands the
#: decision to the caller instead of retrying forever.
_ATTEMPTS = 2


class TicketNotDoneError(RuntimeError):
    """The ticket was never observed Done across every transition attempt.

    Carries the last underlying tracker error (if any) in its message —
    ``close`` embeds this behind its own ``ticket_transition_failed`` reason.
    """


async def confirm_ticket_done(client: Tracker, ticket: str, *, attempts: int = _ATTEMPTS) -> None:
    """Transition ``ticket`` to Done and verify by reading its state back.

    Each attempt transitions then reads. A transition failure
    (``TrackerNotFound`` / ``TrackerRequestError``) does **not** short-circuit
    the attempt — the read still runs, because a write can land while its
    response is lost; the read is the source of truth. Returns as soon as a
    read observes Done. Raises :class:`TicketNotDoneError` if no read across
    ``attempts`` ever observes it.
    """
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            await client.transition_to_done(ticket)
        except (TrackerNotFound, TrackerRequestError) as exc:
            last_error = exc
        else:
            last_error = None
        try:
            if await client.issue_is_done(ticket):
                return
        except (TrackerNotFound, TrackerRequestError) as exc:
            last_error = exc

    detail = f": {last_error}" if last_error is not None else ""
    raise TicketNotDoneError(
        f"ticket {ticket} was not Done after {attempts} transition attempts{detail}"
    )
