"""Tests for ``harness.cli.close_tracker`` — #251.

``close.py`` sat back at its 500-line hard limit with no ``# size:`` marker and
no recorded Watchlist-trigger decision (CAL-1139's mechanism, missed twice in a
row across #233 and #247). The seam this ticket extracts is the Done-transition
mapping: turning the tracker's three failure shapes into one control-flow
exception the verb then maps to its own ``FailureReason`` vocabulary — the same
split ``design_tracker.py`` already makes for the ``design`` verb's tracker I/O.

Case 2 vs. 3 below is the load-bearing edge case: ``TrackerTransitionUnconfirmed``
*subclasses* ``TrackerRequestError``, so clause order in the transition mapper is
the only thing standing between the correct ``unconfirmed`` tag and a silently
wrong ``request_error`` one.

#301 widened the mapping from two shapes to **three**. The bool collapsed
``TrackerNotFound`` and ``TrackerRequestError`` into one ``unconfirmed=False``
tag, but for retry purposes they are opposites: a not-found issue is
deterministic and must never be retried, while a request error (401, 5xx) is
transient and should be. The tests below assert the three-way ``kind`` and — as
the thing that actually protects the contract — that the verb's exit-1 ``reason``
vocabulary is *unchanged* by the widening.
"""

from __future__ import annotations

from typing import get_args
from unittest.mock import AsyncMock, MagicMock

import pytest

from harness.cli.close_tracker import (
    TicketFailureKind,
    TicketNotDone,
    transition_ticket_done,
)
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
    """``TrackerTransitionUnconfirmed`` (#233) must tag ``kind='unconfirmed'``."""
    client = _stub_client(
        TrackerTransitionUnconfirmed(
            "issueUpdate reported success, but the post-write state is In Review"
        )
    )
    with pytest.raises(TicketNotDone) as excinfo:
        await transition_ticket_done(client, "CAL-572")
    assert excinfo.value.kind == "unconfirmed"
    assert "CAL-572" in excinfo.value.detail


async def test_transition_request_error_maps_to_ticket_not_done_request_error() -> None:
    """A ``TrackerRequestError`` that is NOT the unconfirmed subclass tags
    ``kind='request_error'`` — the subclass-ordering edge case that silently
    regresses if the ``except`` clauses are ever reordered."""
    client = _stub_client(TrackerRequestError("permission denied"))
    with pytest.raises(TicketNotDone) as excinfo:
        await transition_ticket_done(client, "CAL-572")
    assert excinfo.value.kind == "request_error"
    assert "CAL-572" in excinfo.value.detail


async def test_transition_not_found_maps_to_ticket_not_done_not_found() -> None:
    """#301 AC-1: not-found is its own kind, not collapsed into the request error.

    The two used to share ``unconfirmed=False``. They are opposites for the
    retry: a missing issue is deterministic and re-issuing the mutation cannot
    make it exist, while a 401/5xx is exactly what a retry rides out.
    """
    client = _stub_client(TrackerNotFound("no such ticket"))
    with pytest.raises(TicketNotDone) as excinfo:
        await transition_ticket_done(client, "CAL-572")
    assert excinfo.value.kind == "not_found"


async def test_the_three_kinds_are_distinct_and_totally_declared() -> None:
    """The widening is three-way, and the vocabulary declares exactly those three.

    Without this, ``TicketFailureKind`` could gain a fourth member that no
    ``except`` clause ever produces, or lose one while the mapper still names
    it — either way the retry's membership test would be reasoning about a set
    the mapper does not actually raise.
    """
    assert set(get_args(TicketFailureKind)) == {
        "unconfirmed",
        "not_found",
        "request_error",
    }


@pytest.mark.parametrize(
    ("raised", "expected_kind"),
    [
        (TrackerTransitionUnconfirmed("post-write state is In Review"), "unconfirmed"),
        (TrackerNotFound("no such ticket"), "not_found"),
        (TrackerRequestError("permission denied"), "request_error"),
    ],
)
async def test_every_declared_kind_is_reachable_from_a_tracker_failure(
    raised: Exception, expected_kind: str
) -> None:
    """Every member of the vocabulary is produced by some real tracker shape.

    The floor under the totality assertion above: a declared kind nothing can
    raise would let the retry's never-retry set look complete while covering a
    case that never occurs.
    """
    with pytest.raises(TicketNotDone) as excinfo:
        await transition_ticket_done(_stub_client(raised), "CAL-572")
    assert excinfo.value.kind == expected_kind


async def test_transition_unmodelled_error_propagates_unchanged() -> None:
    """No broad ``except`` was added — an unexpected error type propagates as-is."""
    client = _stub_client(RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        await transition_ticket_done(client, "CAL-572")
