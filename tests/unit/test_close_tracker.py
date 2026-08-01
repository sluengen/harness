"""Tests for ``harness.cli.close_tracker`` — #251.

``close.py`` sat back at its 500-line hard limit with no ``# size:`` marker and
no recorded Watchlist-trigger decision (CAL-1139's mechanism, missed twice in a
row across #233 and #247). The seam this ticket extracts is the Done-transition
mapping: turning the tracker's three failure shapes into one control-flow
exception the verb then maps to its own ``FailureReason`` vocabulary — the same
split ``design_tracker.py`` already makes for the ``design`` verb's tracker I/O.

Case 2 vs. 3 below is the load-bearing edge case: ``TrackerTransitionUnconfirmed``
*subclasses* ``TrackerRequestError``, so clause order in the transition mapper is
the only thing standing between the correct ``unconfirmed=True`` tag and a
silently wrong ``unconfirmed=False`` one.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from harness.cli.close_tracker import TicketNotDone, transition_ticket_done
from harness.tracker_errors import (
    TrackerNotFound,
    TrackerRequestError,
    TrackerTransitionUnconfirmed,
)


def _stub_client(side_effect: Exception | None = None) -> MagicMock:
    stub = MagicMock()
    if side_effect is not None:
        stub.transition_to_done = AsyncMock(side_effect=side_effect)
    else:
        stub.transition_to_done = AsyncMock(return_value=None)
    return stub


async def test_transition_success_raises_nothing() -> None:
    client = _stub_client()
    await transition_ticket_done(client, "CAL-572")
    client.transition_to_done.assert_called_once_with("CAL-572")


async def test_transition_unconfirmed_maps_to_ticket_not_done_unconfirmed() -> None:
    """``TrackerTransitionUnconfirmed`` (#233) must tag ``unconfirmed=True``."""
    client = _stub_client(
        TrackerTransitionUnconfirmed(
            "issueUpdate reported success, but the post-write state is In Review"
        )
    )
    with pytest.raises(TicketNotDone) as excinfo:
        await transition_ticket_done(client, "CAL-572")
    assert excinfo.value.unconfirmed is True
    assert "CAL-572" in excinfo.value.detail


async def test_transition_request_error_maps_to_ticket_not_done_confirmed_false() -> None:
    """A ``TrackerRequestError`` that is NOT the unconfirmed subclass tags
    ``unconfirmed=False`` — the subclass-ordering edge case that silently
    regresses if the ``except`` clauses are ever reordered."""
    client = _stub_client(TrackerRequestError("permission denied"))
    with pytest.raises(TicketNotDone) as excinfo:
        await transition_ticket_done(client, "CAL-572")
    assert excinfo.value.unconfirmed is False
    assert "CAL-572" in excinfo.value.detail


async def test_transition_not_found_maps_to_ticket_not_done_confirmed_false() -> None:
    client = _stub_client(TrackerNotFound("no such ticket"))
    with pytest.raises(TicketNotDone) as excinfo:
        await transition_ticket_done(client, "CAL-572")
    assert excinfo.value.unconfirmed is False


async def test_transition_unmodelled_error_propagates_unchanged() -> None:
    """No broad ``except`` was added — an unexpected error type propagates as-is."""
    client = _stub_client(RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        await transition_ticket_done(client, "CAL-572")
