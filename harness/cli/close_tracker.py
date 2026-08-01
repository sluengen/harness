"""The close verb's tracker I/O — map the Done-transition's failure shapes.

``close`` touches the tracker at exactly one point after the merge has already
landed: transitioning the ticket to Done. This module maps the tracker's three
failure shapes (:class:`~harness.tracker_errors.TrackerTransitionUnconfirmed`,
:class:`~harness.tracker_errors.TrackerNotFound`,
:class:`~harness.tracker_errors.TrackerRequestError`) to one control-flow
exception; the verb (:mod:`harness.cli.close`) maps that to its own
``FailureReason`` exit-1 vocabulary. Split out in #251 (the ``architecture``
watchlist trigger on `close.py` re-arming at its 500-line limit) — mirroring the
tracker-boundary split :mod:`harness.cli.design_tracker` already makes for the
``design`` verb, and keeping the git mechanics in :mod:`harness.close_merge`.

The layering is one-way: this module raises tracker-shaped failures and knows
nothing of exit codes or ``reason`` tags — that vocabulary, and the
``tracker_client`` resolution used to configure it, stay in ``close.py``.
"""

from __future__ import annotations

from harness.tracker import Tracker
from harness.tracker_errors import (
    TrackerNotFound,
    TrackerRequestError,
    TrackerTransitionUnconfirmed,
)

__all__ = ["TicketNotDone", "transition_ticket_done"]


class TicketNotDone(Exception):  # noqa: N818 — SPEC vocab, not PEP 8 Error suffix
    """The ticket could not be confirmed Done after the merge already landed.

    ``unconfirmed`` is ``True`` iff the tracker raised
    :class:`~harness.tracker_errors.TrackerTransitionUnconfirmed` (the mutation
    reported success, but the post-write state was not Done, #233); ``False``
    for every other tracker failure. The verb maps the two to distinct
    ``FailureReason`` tags so an operator can tell "the tracker refused" from
    "the tracker said yes but lied" apart.
    """

    def __init__(self, detail: str, *, unconfirmed: bool) -> None:
        super().__init__(detail)
        self.detail = detail
        self.unconfirmed = unconfirmed


async def transition_ticket_done(client: Tracker, ticket: str) -> None:
    """Transition ``ticket`` to Done; raise :class:`TicketNotDone` naming how it failed.

    ``TrackerTransitionUnconfirmed`` is checked **first** — it subclasses
    ``TrackerRequestError``, so clause order is the only thing distinguishing
    ``unconfirmed=True`` from ``unconfirmed=False``. Any other exception type
    propagates unchanged: no broad ``except`` is added here.
    """
    try:
        await client.transition_to_done(ticket)
    except TrackerTransitionUnconfirmed as exc:
        raise TicketNotDone(
            f"ticket {ticket} was not confirmed Done: {exc}", unconfirmed=True
        ) from exc
    except (TrackerNotFound, TrackerRequestError) as exc:
        raise TicketNotDone(
            f"failed to transition ticket {ticket} to Done: {exc}", unconfirmed=False
        ) from exc
