"""``close``'s bounded transient retry — the single home of the retry table (#301).

After a ``pass`` verdict, ``harness close`` is one command, but the orchestrating
agent still had to read a non-zero exit against a refusal table and pick a
recovery — and for most of what is actually reachable right after a fresh pass at
a clean HEAD, the "judgment" was not judgment at all: it was *run it again*. A
lost push race, a GraphQL hiccup, a tracker that answered before its own write
settled. This module absorbs those, so the agent's decision tree collapses to
**exit 0 → done; non-zero → escalate**.

The table lives here, next to the classifications it keys on and *above* the
tracker seam, for the reason ``loop.wall_clock_budget_minutes`` is one value
serving two consumers (#260): a retry table in a wrapper script or an agent
prompt is a second home for a rule whose truth is set at the raise sites, and it
would drift from them silently. The verb computes the classification, so the verb
acts on it.

**Two frozensets, not one.** The retried steps raise different typed
classifications — :data:`~harness.close_merge.CloseMergeReason` for the merge,
:data:`~harness.cli.close_tracker.TicketFailureKind` for the transition — and a
single wire-``reason`` set could not tell ``not_found`` from ``request_error``,
since both exit as ``ticket_transition_failed``. That is precisely the collapse
#301 removed; re-introducing it here to save a set would undo it.

**Three attempts is deliberately small.** The retry rides out a blip, not an
outage: a real tracker outage should reach a human rather than be persisted
through, and ~10s of total backoff keeps a retrying close far from anything that
would make a live run look dead to ``reclaim --stale``. The caps are module
constants rather than ``CONTEXT.md`` config because the ``loop:`` knobs bound
*spend policy*, which is a per-repo choice, whereas a transient-blip retry is
mechanics.

Nothing here is swallowed. A failure the table does not model, and one that
exhausts the budget, both re-raise the original exception on the spot — so
``close``'s existing handlers translate exactly what they always translated, and
the exit code and ``reason`` an operator branches on are preserved structurally
rather than by a second translation table. Retry changes latency and the ledger;
it never changes the contract.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from harness.cli.close_tracker import TicketFailureKind, TicketNotDone
from harness.close_merge import CloseMergeError, CloseMergeReason

__all__ = [
    "Classify",
    "DEFAULT_BACKOFF_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "RETRYABLE_MERGE_REASONS",
    "RETRYABLE_TICKET_KINDS",
    "call_with_retry",
    "merge_retry_tag",
    "ticket_retry_tag",
]

T = TypeVar("T")

#: Total attempts a retried step may spend — the initial call plus the retries.
DEFAULT_MAX_ATTEMPTS = 3

#: The delay before each retry, in seconds. Its length must be
#: ``DEFAULT_MAX_ATTEMPTS - 1``: one delay per retry the bound allows. A shorter
#: table would raise ``IndexError`` on a live retry — the one path that fires
#: only when something is already going wrong — so a guard test pins the
#: relationship rather than leaving it to whoever edits one of the two.
DEFAULT_BACKOFF_SECONDS: tuple[float, ...] = (2.0, 8.0)

#: The step-6 failures worth re-running. Each is a *state of the world* that a
#: second attempt genuinely re-evaluates: a rejected push re-fetches the winner's
#: tip, and both network reasons re-reach a remote that may have come back.
#: Everything else ``close_merge`` raises needs work on the run branch or on the
#: machine, and is left to escalate — notably ``merge_conflict``, which the
#: ticket names as out of scope in any form.
RETRYABLE_MERGE_REASONS: frozenset[CloseMergeReason] = frozenset(
    {"network_timeout", "fetch_failed", "push_rejected"}
)

#: The step-7 failures worth re-issuing the transition for. ``unconfirmed`` is a
#: mutation whose own post-write response did not show the requested state (#233)
#: — on both backends the confirmation is embedded in the mutation response, so
#: re-issuing *is* the re-read, at the cost of a read and with no new method on
#: the ``Tracker`` protocol. ``request_error`` is the 401/5xx bucket.
#:
#: ``not_found`` is deliberately absent: a missing issue is deterministic, and no
#: number of re-issues makes it exist.
RETRYABLE_TICKET_KINDS: frozenset[TicketFailureKind] = frozenset(
    {"unconfirmed", "request_error"}
)

#: The ledger label for each retryable tracker kind. Distinct from the verb's
#: exit-1 ``reason`` vocabulary on purpose: ``request_error`` and ``not_found``
#: both exit as ``ticket_transition_failed``, so the ledger is the only place the
#: third discrimination is observable — which is where a degrading tracker is
#: actually diagnosed from.
_TICKET_RETRY_LABELS: dict[TicketFailureKind, str] = {
    "unconfirmed": "ticket_transition_unconfirmed",
    "request_error": "ticket_transition_request_error",
}

#: Indirected so tests can record the delays instead of paying them. A module
#: attribute rather than a ``sleep=`` parameter because the tests that matter —
#: the ones counting attempts through the whole verb — drive ``close`` through
#: the Typer runner and have nowhere to thread a parameter in, which would leave
#: the parameter dead weight at exactly the level the bound is asserted.
_sleep = asyncio.sleep

#: Returns the label to record **iff** the exception is worth retrying, else
#: ``None``. One callback does both jobs so the decision and the label cannot
#: disagree — a table that said "retry" while labelling it something else would
#: make the ledger lie about what was absorbed.
Classify = Callable[[BaseException], str | None]


def merge_retry_tag(exc: BaseException) -> str | None:
    """Classify a step-6 failure; the label is the reason ``close_merge`` computed.

    Reusing the reason verbatim rather than inventing a retry vocabulary keeps
    the ledger's account of what was absorbed in the same words as the exit-1
    tag the failure would have carried had it exhausted.
    """
    if isinstance(exc, CloseMergeError) and exc.reason in RETRYABLE_MERGE_REASONS:
        return exc.reason
    return None


def ticket_retry_tag(exc: BaseException) -> str | None:
    """Classify a step-7 failure by its :data:`TicketFailureKind`.

    Keying on the kind is what keeps the retry above the tracker seam (AC-4):
    every backend's failures already map onto these three, so neither backend
    can acquire retry behaviour the other lacks.
    """
    if isinstance(exc, TicketNotDone) and exc.kind in RETRYABLE_TICKET_KINDS:
        return _TICKET_RETRY_LABELS[exc.kind]
    return None


async def call_with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    classify: Classify,
    absorbed: list[str],
) -> T:
    """Run ``operation``, absorbing the transient failures ``classify`` names.

    Args:
        operation: The step to run. Called afresh each attempt, so a retry
            re-evaluates the world rather than replaying a captured result.
        classify: Returns a label for a retryable exception, ``None`` otherwise.
        absorbed: Appended to, in order, once per absorbed failure — the ledger's
            record of what the retry hid. The caller owns the list so the same
            record is readable from both the landed path and the terminal-event
            handler.

    Returns:
        Whatever ``operation`` returned on the attempt that succeeded.

    Raises:
        BaseException: The exception from the final attempt, unchanged — either
            because ``classify`` declined it or because the bound was spent.
    """
    for attempt in range(1, DEFAULT_MAX_ATTEMPTS + 1):
        try:
            return await operation()
        except Exception as exc:
            tag = classify(exc)
            if tag is None or attempt == DEFAULT_MAX_ATTEMPTS:
                raise
            absorbed.append(tag)
            await _sleep(DEFAULT_BACKOFF_SECONDS[attempt - 1])
    # Unreachable: the loop either returns or raises on its final attempt. Kept
    # so the function is total for a reader and for mypy's return analysis.
    raise AssertionError("call_with_retry exhausted its loop without returning or raising")
