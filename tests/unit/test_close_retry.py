"""Tests for ``harness.cli.close_retry`` — the bounded transient retry (#301).

``close``'s step 6 and step 7 fail in ways that split cleanly into "run it
again" and "a human has work to do", and the verb is the component that already
computes that classification. This module is where the split lives, so the
orchestrating agent's decision tree collapses to *exit 0 → done; non-zero →
escalate*.

The two properties that actually matter here are **the bound** and **what is not
retried**. A retry that eventually succeeds proves nothing on its own — an
unbounded loop passes that test too — so every case below counts attempts, and
the backoff is measured rather than assumed. The totality guard is the other
half: a reason added to ``close_merge`` later must fail loudly here instead of
silently defaulting to non-retryable, which is how a genuinely transient failure
would quietly start escalating to a human again.
"""

from __future__ import annotations

from typing import get_args

import pytest

from harness import close_merge
from harness.cli import close_retry
from harness.cli.close_retry import (
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
    RETRYABLE_MERGE_REASONS,
    RETRYABLE_TICKET_KINDS,
    call_with_retry,
    merge_retry_tag,
    ticket_retry_tag,
)
from harness.cli.close_tracker import TicketFailureKind, TicketNotDone

# The reasons/kinds this change deliberately leaves un-retried, written out so
# the totality guards below can prove the two lists partition the real
# vocabularies. Hand-listed on purpose: this is the *claim*, and the vocabulary
# it is checked against is derived.
NEVER_RETRIED_MERGE_REASONS = frozenset(
    {"merge_conflict", "merge_failed", "git_status_failed", "worktree_create_failed"}
)
NEVER_RETRIED_TICKET_KINDS = frozenset({"not_found"})


@pytest.fixture
def delays(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record what the driver sleeps instead of actually sleeping.

    The bound is 2s + 8s per retried step; a suite that really slept it would
    pay ~10s per exhausted-retry test.
    """
    recorded: list[float] = []

    async def _record(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(close_retry, "_sleep", _record)
    return recorded


class _BoomError(RuntimeError):
    """An exception no classifier models — stands in for the unexpected."""


def _always(tag: str | None) -> close_retry.Classify:
    return lambda _exc: tag


# ---------------------------------------------------------------------------
# AC-6 / AC-7: the bound, counted — and the backoff, measured
# ---------------------------------------------------------------------------


async def test_a_transient_failure_is_attempted_at_most_three_times(
    delays: list[float],
) -> None:
    """The whole point of the bound: three attempts, then the failure stands.

    Counted rather than inferred from "it eventually gave up" — an off-by-one
    that spent a fourth attempt would still give up, and would still look
    correct to a test that only asserted the final exception.
    """
    calls = 0

    async def _operation() -> str:
        nonlocal calls
        calls += 1
        raise _BoomError("transient")

    absorbed: list[str] = []
    with pytest.raises(_BoomError):
        await call_with_retry(_operation, classify=_always("blip"), absorbed=absorbed)

    assert calls == DEFAULT_MAX_ATTEMPTS == 3
    assert delays == [2.0, 8.0]
    assert absorbed == ["blip", "blip"]


async def test_a_recovered_failure_stops_retrying_the_moment_it_succeeds(
    delays: list[float],
) -> None:
    """A blip on attempt 1 costs one retry and one sleep, not the whole budget."""
    calls = 0

    async def _operation() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _BoomError("transient")
        return "landed"

    absorbed: list[str] = []
    assert await call_with_retry(
        _operation, classify=_always("blip"), absorbed=absorbed
    ) == "landed"

    assert calls == 2
    assert delays == [2.0]
    assert absorbed == ["blip"]


async def test_a_success_on_the_first_attempt_never_sleeps(delays: list[float]) -> None:
    """The overwhelmingly common path pays nothing — no sleep, no ledger entry."""
    calls = 0

    async def _operation() -> str:
        nonlocal calls
        calls += 1
        return "landed"

    absorbed: list[str] = []
    assert await call_with_retry(
        _operation, classify=_always("blip"), absorbed=absorbed
    ) == "landed"

    assert calls == 1
    assert delays == []
    assert absorbed == []


# ---------------------------------------------------------------------------
# AC-3: what is never retried
# ---------------------------------------------------------------------------


async def test_an_unclassified_failure_is_attempted_exactly_once(
    delays: list[float],
) -> None:
    """``classify`` returning ``None`` means *stop*, not *retry without a label*.

    This is the safety property the whole retry rests on: a failure the table
    does not model must behave exactly as it did before this change.
    """
    calls = 0

    async def _operation() -> str:
        nonlocal calls
        calls += 1
        raise _BoomError("deterministic")

    absorbed: list[str] = []
    with pytest.raises(_BoomError):
        await call_with_retry(_operation, classify=_always(None), absorbed=absorbed)

    assert calls == 1
    assert delays == []
    assert absorbed == []


async def test_the_exhausted_failure_re_raises_the_last_exception_untouched(
    delays: list[float],
) -> None:
    """AC-9: the caller's ``except`` sees what it always saw.

    ``close``'s existing handlers translate the exception into the exit code and
    ``reason`` an operator branches on. Re-raising the original — not a wrapper
    carrying retry metadata — is what keeps that contract structural instead of
    dependent on a second translation table staying in sync.
    """
    raised = [_BoomError("first"), _BoomError("second"), _BoomError("third")]

    async def _operation() -> str:
        raise raised[len(delays)]

    with pytest.raises(_BoomError, match="third"):
        await call_with_retry(_operation, classify=_always("blip"), absorbed=[])


# ---------------------------------------------------------------------------
# The classifiers — decision and label come from one callback, so they agree
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reason", sorted(RETRYABLE_MERGE_REASONS))
def test_merge_retry_tag_labels_every_retryable_reason_with_itself(reason: str) -> None:
    error = close_merge.CloseMergeError("boom", reason=reason)  # type: ignore[arg-type]
    assert merge_retry_tag(error) == reason


@pytest.mark.parametrize("reason", sorted(NEVER_RETRIED_MERGE_REASONS))
def test_merge_retry_tag_declines_every_reason_that_needs_a_human(reason: str) -> None:
    error = close_merge.CloseMergeError("boom", reason=reason)  # type: ignore[arg-type]
    assert merge_retry_tag(error) is None


def test_merge_retry_tag_declines_an_exception_of_another_type() -> None:
    """A non-``CloseMergeError`` carries no ``reason`` to key on — decline, never crash."""
    assert merge_retry_tag(_BoomError("unmodelled")) is None


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("unconfirmed", "ticket_transition_unconfirmed"),
        ("request_error", "ticket_transition_request_error"),
    ],
)
def test_ticket_retry_tag_labels_every_retryable_kind(kind: str, expected: str) -> None:
    """The two retryable arms get distinct ledger labels.

    ``request_error`` has no wire counterpart — it and ``not_found`` both exit as
    ``ticket_transition_failed`` — so the ledger is the only place the third
    discrimination is visible, which is exactly where a degrading tracker is
    diagnosed from.
    """
    assert ticket_retry_tag(TicketNotDone("boom", kind=kind)) == expected  # type: ignore[arg-type]


def test_ticket_retry_tag_declines_a_not_found_ticket() -> None:
    """AC-3: a missing issue is deterministic — re-issuing cannot make it exist."""
    assert ticket_retry_tag(TicketNotDone("boom", kind="not_found")) is None


def test_ticket_retry_tag_declines_an_exception_of_another_type() -> None:
    assert ticket_retry_tag(_BoomError("unmodelled")) is None


# ---------------------------------------------------------------------------
# Totality: the retry table is checked against the vocabularies it keys on
# ---------------------------------------------------------------------------


def test_the_merge_retry_table_partitions_the_whole_merge_vocabulary() -> None:
    """Every ``CloseMergeReason`` is classified once, deliberately.

    Derived from ``close_merge``'s own declared vocabulary, so a reason added
    there fails here rather than defaulting silently to non-retryable — a
    default that would be *wrong in the dangerous direction* for a transient
    reason, since the loop would quietly go back to escalating it to a human.
    """
    declared = set(get_args(close_merge.CloseMergeReason))

    assert declared, "the derivation found no reasons; it broke rather than the module shrinking"
    assert not (RETRYABLE_MERGE_REASONS & NEVER_RETRIED_MERGE_REASONS)
    assert declared == RETRYABLE_MERGE_REASONS | NEVER_RETRIED_MERGE_REASONS


def test_the_ticket_retry_table_partitions_the_whole_kind_vocabulary() -> None:
    """The same, for the three-way tracker discrimination AC-1 introduced."""
    declared = set(get_args(TicketFailureKind))

    assert declared, "the derivation found no kinds; it broke rather than the type shrinking"
    assert not (RETRYABLE_TICKET_KINDS & NEVER_RETRIED_TICKET_KINDS)
    assert declared == RETRYABLE_TICKET_KINDS | NEVER_RETRIED_TICKET_KINDS


def test_the_retry_set_is_exactly_the_one_the_ticket_specified() -> None:
    """AC-2, asserted literally rather than left to the partition above.

    The partition guards *completeness*; this guards the *choice*. Without it,
    moving ``merge_conflict`` into the retry set would keep the partition intact
    while making the verb retry the one failure the ticket names as out of
    scope.
    """
    assert {"network_timeout", "fetch_failed", "push_rejected"} == RETRYABLE_MERGE_REASONS
    assert {"unconfirmed", "request_error"} == RETRYABLE_TICKET_KINDS


def test_the_backoff_table_covers_every_retry_the_bound_allows() -> None:
    """AC-6: ``MAX_ATTEMPTS - 1`` retries need exactly that many delays.

    A shorter table would raise ``IndexError`` mid-close on a live retry — on
    the one path that only fires when something is already going wrong, which is
    the worst possible place to discover it.
    """
    assert len(DEFAULT_BACKOFF_SECONDS) == DEFAULT_MAX_ATTEMPTS - 1
    assert DEFAULT_BACKOFF_SECONDS == (2.0, 8.0)


def test_the_retry_never_names_a_tracker_backend() -> None:
    """AC-4: the retry sits above the seam.

    It keys on ``TicketNotDone.kind``, which every backend's failures already
    map onto, so neither backend can acquire retry behaviour the other lacks.
    """
    source = close_retry.__file__
    with open(source) as handle:
        text = handle.read()

    for backend in ("GitHubClient", "LinearClient", "github", "linear"):
        assert backend not in text, (
            f"close_retry names {backend!r}; the retry must key on the "
            f"backend-neutral TicketNotDone.kind, not on a specific tracker"
        )
