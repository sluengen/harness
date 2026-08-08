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

from typing import Literal

from harness.tracker import Tracker
from harness.tracker_errors import (
    TrackerNotFound,
    TrackerRequestError,
    TrackerTransitionUnconfirmed,
)

__all__ = ["TicketFailureKind", "TicketNotDone", "transition_ticket_done"]

#: How the Done transition failed — one member per tracker failure shape (#301).
#:
#: This used to be a ``bool``: ``TrackerNotFound`` and ``TrackerRequestError``
#: both meant ``unconfirmed=False``, which was enough while the verb only had to
#: choose between two exit-1 ``reason`` tags. It stopped being enough once the
#: verb *retries*: a not-found issue is deterministic — re-issuing the mutation
#: cannot make the issue exist — while a request error (401, 5xx) is the
#: transient blip a retry exists to ride out. Collapsed together, the retry
#: would have to either burn its whole budget on a permanently missing ticket or
#: give up on a recoverable one.
#:
#: The kinds are *how the tracker failed*, deliberately not the verb's exit-1
#: ``reason`` vocabulary: this module knows nothing of exit codes, and the
#: mapping from three kinds onto the two unchanged ``TicketFailureReason`` tags
#: stays in ``close.py`` where that contract lives.
TicketFailureKind = Literal["unconfirmed", "not_found", "request_error"]


class TicketNotDone(Exception):  # noqa: N818 — SPEC vocab, not PEP 8 Error suffix
    """The ticket could not be confirmed Done after the merge already landed.

    ``kind`` is the :data:`TicketFailureKind` naming which tracker failure shape
    fired: ``unconfirmed`` for
    :class:`~harness.tracker_errors.TrackerTransitionUnconfirmed` (the mutation
    reported success, but the post-write state was not Done, #233),
    ``not_found`` for :class:`~harness.tracker_errors.TrackerNotFound`, and
    ``request_error`` for :class:`~harness.tracker_errors.TrackerRequestError`.
    The verb reads it twice over: to pick the exit-1 ``FailureReason`` tag an
    operator branches on, and to decide whether the failure is worth retrying.
    """

    def __init__(self, detail: str, *, kind: TicketFailureKind) -> None:
        super().__init__(detail)
        self.detail = detail
        self.kind: TicketFailureKind = kind


async def transition_ticket_done(client: Tracker, ticket: str) -> None:
    """Transition ``ticket`` to Done; raise :class:`TicketNotDone` naming how it failed.

    ``TrackerTransitionUnconfirmed`` is checked **first** — it subclasses
    ``TrackerRequestError``, so clause order is the only thing distinguishing
    ``kind='unconfirmed'`` from ``kind='request_error'``. ``TrackerNotFound``
    precedes the request-error clause for readability only; the two are
    unrelated types, so that pair is order-independent. Any other exception type
    propagates unchanged: no broad ``except`` is added here.
    """
    try:
        await client.transition_to_done(ticket)
    except TrackerTransitionUnconfirmed as exc:
        raise TicketNotDone(
            f"ticket {ticket} was not confirmed Done: {exc}", kind="unconfirmed"
        ) from exc
    except TrackerNotFound as exc:
        raise TicketNotDone(
            f"failed to transition ticket {ticket} to Done: {exc}", kind="not_found"
        ) from exc
    except TrackerRequestError as exc:
        raise TicketNotDone(
            f"failed to transition ticket {ticket} to Done: {exc}", kind="request_error"
        ) from exc
