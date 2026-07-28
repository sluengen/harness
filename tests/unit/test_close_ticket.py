"""``harness.cli.close_ticket.confirm_ticket_done`` — attempt, then observe (#233).

Pins the retry logic independently of ``close``'s CLI plumbing: a transition
is trusted only once a read-back of the issue's state confirms it, and a
transition failure never short-circuits that read (a write can land while its
response is lost).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from harness.cli.close_ticket import TicketNotDoneError, confirm_ticket_done
from harness.tracker_errors import TrackerRequestError


def _client(
    *,
    transition: Exception | None = None,
    is_done: bool | list[bool] | Exception = True,
) -> MagicMock:
    stub = MagicMock()
    stub.transition_to_done = AsyncMock(
        side_effect=transition if transition is not None else None
    )
    if isinstance(is_done, (Exception, list)):
        stub.issue_is_done = AsyncMock(side_effect=is_done)
    else:
        stub.issue_is_done = AsyncMock(return_value=is_done)
    return stub


async def test_transition_ok_and_verified_returns_after_one_attempt() -> None:
    client = _client(is_done=True)
    await confirm_ticket_done(client, "CAL-572")
    assert client.transition_to_done.call_count == 1
    assert client.issue_is_done.call_count == 1


async def test_transition_ok_but_never_verified_raises_after_all_attempts() -> None:
    client = _client(is_done=False)
    with pytest.raises(TicketNotDoneError, match="not Done after 2 transition attempts"):
        await confirm_ticket_done(client, "CAL-572")
    assert client.transition_to_done.call_count == 2
    assert client.issue_is_done.call_count == 2


async def test_transition_raises_but_read_confirms_done_still_returns() -> None:
    """The observed state outranks a failed acknowledgement — a write can land
    while its response is lost, so a raising transition must not short-circuit
    the read that follows it in the same attempt."""
    client = _client(transition=TrackerRequestError("response lost"), is_done=True)
    await confirm_ticket_done(client, "CAL-572")
    assert client.transition_to_done.call_count == 1
    assert client.issue_is_done.call_count == 1


async def test_transition_raises_and_read_also_raises_reports_the_underlying_error() -> None:
    client = _client(
        transition=TrackerRequestError("boom"),
        is_done=TrackerRequestError("boom"),
    )
    with pytest.raises(TicketNotDoneError, match="boom"):
        await confirm_ticket_done(client, "CAL-572")
    assert client.transition_to_done.call_count == 2
    assert client.issue_is_done.call_count == 2


async def test_recovers_on_second_attempt_when_first_read_is_stale() -> None:
    client = _client(is_done=[False, True])
    await confirm_ticket_done(client, "CAL-572")
    assert client.transition_to_done.call_count == 2
    assert client.issue_is_done.call_count == 2


async def test_attempts_is_configurable() -> None:
    client = _client(is_done=False)
    with pytest.raises(TicketNotDoneError, match="not Done after 3 transition attempts"):
        await confirm_ticket_done(client, "CAL-572", attempts=3)
    assert client.transition_to_done.call_count == 3
    assert client.issue_is_done.call_count == 3
