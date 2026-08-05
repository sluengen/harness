"""Ledger-backed spend breakers for the autonomous loop — CAL-906 (WS1).

The Build routine and the review→fix→re-review cycle have no view of the
orchestrating session's token meter (the verbs are one-shot CLI calls, not the
session), so the harness cannot meter dollars directly. What it *can* observe,
deterministically, is the ledger: how many ``review`` events a run has recorded
and when the run started. This module turns those two observable facts into two
**circuit breakers** that bound the behaviours that burn tokens:

* a **hard ceiling** on review→fix cycles per run — ``max_review_cycles`` is the
  count of cycles a run may *spend* (default 5), so the run stops once they are
  used up and the review after them is refused. The first
  ``unconditional_review_cycles`` (default 3) run with no judgment required; the
  cycles after those and inside the budget carry a convergence-assessment
  advisory (the build agent decides whether the fixes are converging before
  spending another cycle), and a fail on the last one carries
  :func:`cycles_exhausted` so the run stops where the policy says it stops
  rather than one wasted implement pass later. The policy itself is single-homed
  in ``skills/review-discipline/SKILL.md`` (#329); this module is its
  enforcement, and ``CONTEXT.md`` is the only home for the numbers;
* a **per-run wall-clock budget** in minutes (default 110). It is not merely
  *aligned* with the stale-run reclamation staleness threshold — since #260 it
  **is** that threshold: ``reclaim --stale`` resolves the same
  ``loop.wall_clock_budget_minutes`` when ``--older-than`` is omitted. The
  breaker reads it prospectively (stop spending on a run past it), reclamation
  retrospectively (a run past it is presumed dead); one value means they cannot
  drift, so nobody has to "keep the two in step". Since #296 the breaker applies
  that value to **unattended runs only** (ADR 0011), and since #297 so does the
  sweep — an attended run is measured against ``attended_idle_minutes`` instead.
  The shared quantity is unchanged; what differs is which runs it is measured
  against, and the two consumers now agree about that too.

Both thresholds are **read from CONTEXT.md** (the ``loop:`` block), not hardcoded,
so each self-hosting repo configures its own bounds. The decision functions are
pure — the caller (``harness review``, the loop boundary) passes in the prior
review count, the run's ``started_at``, and ``now`` — which keeps every numeric
bound measurable in a unit test (``code-quality`` Part C).

The breakers are checked at *verb boundaries*, not mid-session: a run that runs
away between verbs is bounded by the wall-clock check at the next boundary, not
interrupted mid-thought. That is the honest limit of ledger-backed breakers and
the reason true token/$ metering is deferred (proposal ``harden-loop-layer``).
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

__all__ = [
    "DEFAULT_ATTENDED_IDLE_MINUTES",
    "DEFAULT_ENGINE_TIMEOUT_SECONDS",
    "DEFAULT_MAX_REVIEW_CYCLES",
    "DEFAULT_REVIEW_MODEL",
    "DEFAULT_UNCONDITIONAL_REVIEW_CYCLES",
    "DEFAULT_WALL_CLOCK_BUDGET_MINUTES",
    "REVIEW_CYCLE_CEILING_REASON",
    "WALL_CLOCK_BUDGET_REASON",
    "LoopBudget",
    "BreakerTrip",
    "load_loop_budget",
    "evaluate_breakers",
    "convergence_check_required",
    "cycles_exhausted",
]

# The breaker values set by proposal ``harden-loop-layer`` (D1). They are the
# fallback when CONTEXT.md does not configure them; a repo overrides them in its
# CONTEXT.md ``loop:`` block.
DEFAULT_MAX_REVIEW_CYCLES = 5
# How many of those cycles run with no convergence judgment required. The two
# are **independent keys**, not one derived from the other (#329). The old
# ``max_review_cycles // 2`` derivation only ever produced the canonical 3
# because the ceiling happened to be 6; at the canonical budget of 5 it yields 2
# and silently contradicts the rule it is supposed to implement. Stating both
# makes the relationship configured rather than coincidental, and lets a repo
# tune the unconditional window without moving the budget.
DEFAULT_UNCONDITIONAL_REVIEW_CYCLES = 3
# The longest a legitimate run may take. Read by **two** consumers, not one
# (#260): ``review``'s wall-clock breaker enforces it prospectively (stop
# spending on a run past it) and ``reclaim --stale`` applies it retrospectively
# (a run past it is presumed dead). They are the same quantity viewed from two
# directions, so divergence is a bug, not a tuning option — a run aged between
# the two would be spared reclamation *and* refused at review, alive on the
# board and unable to finish. One value, read twice, is what makes that
# unrepresentable. 110 keeps the hourly-tick property the old 90 had (a stale
# run is first caught at the *second* tick after it starts) with slack for tick
# jitter, while letting a merely-slow run finish.
DEFAULT_WALL_CLOCK_BUDGET_MINUTES = 110

# The review-engine subprocess ceiling (CAL-1004). The two breakers above are
# checked only at *verb boundaries*; a review engine that hangs mid-verb is
# bounded by neither until the next boundary. This ceiling closes that gap — it
# caps a single ``claude -p`` / ``codex exec`` subprocess so a hung engine is
# killed and surfaced as an infra failure rather than hanging the verb until an
# external kill. Sit it at or below the documented ops kill so the clean exit
# wins. Raised 600 → 720 on 2026-07-30: across 18 timed design runs the old
# ceiling sat *inside* the working distribution (successes ran 213–561s), so it
# was clipping the right tail rather than catching hung engines. The constant
# moves with the configured value for the same reason the wall clock's does
# (#260, #291) — a repo that never wrote a ``loop:`` block must run the ceiling
# this one's evidence produced, not the one it replaced. A repo still overrides
# it in the same ``loop:`` block.
DEFAULT_ENGINE_TIMEOUT_SECONDS = 720

# How long a run that *declared itself attended* may sit idle before
# ``reclaim --stale`` presumes it abandoned (#297, ADR 0011). A longer
# threshold, not an exemption: the operator is regularly asked a question
# mid-run, and a human thinking touches none of the three liveness clocks the
# sweep reads — so a paused session is indistinguishable from a dead
# orchestrator and the wall clock reverts the ticket underneath them. 480 (8h)
# covers a working day's worth of thinking while still reclaiming a session
# abandoned overnight, so the board self-heals and worktrees do not accumulate.
# It must not fall below DEFAULT_WALL_CLOCK_BUDGET_MINUTES: below it, declaring
# attendance would make a run *more* reclaimable, which is neither mode's
# intent.
#
# Unlike the wall clock this is read by **one** consumer. ``review``'s breaker
# does not apply to an attended run at all (#296), so there is no second
# direction for this value to be seen from and no equality to keep — the
# #260 invariant it would otherwise have to satisfy cannot be violated because
# the window it forbids (refused at review, spared reclamation) has no
# review-side clock to open it.
DEFAULT_ATTENDED_IDLE_MINUTES = 480

# The alias the claude review engine runs on (#321). It replaces ADR 0005's
# per-ticket ``review:<tier>`` label, which was a real control signal that was
# never once set: every review in the ledger resolved to this same fallback,
# while the mechanism cost a tracker ``fetch_issue`` round-trip and five
# degradation branches on the review path to read a label nobody wrote.
#
# A **plain token string, not an enum.** A ``Literal["sonnet", "opus"]`` is the
# same premature constraint being retired: it makes a third alias a code change,
# and it coerces a typo to the default — hiding an operator's mistake behind a
# review that quietly ran a different model from the one configured. An
# unrecognized alias instead reaches the claude CLI and fails there, loudly.
# ``sonnet`` is the value every recorded review has actually run, so this change
# retires the mechanism without also moving the behaviour.
DEFAULT_REVIEW_MODEL = "sonnet"

# Stable, machine-readable ``reason`` tags carried on a trip — mirrors the
# ``{"error", "reason"}`` refusal shape of ``close`` / the review infra failure
# (CAL-866) so the orchestrator branches on the *kind* of trip without parsing
# the human message.
REVIEW_CYCLE_CEILING_REASON = "review_cycle_ceiling"
WALL_CLOCK_BUDGET_REASON = "wall_clock_budget"


class LoopBudget(NamedTuple):
    """The configured loop bounds for a run, read from CONTEXT.md's ``loop:`` block.

    The first two are the ledger-backed spend breakers checked at verb
    boundaries (:func:`evaluate_breakers`). ``engine_timeout_seconds`` is the
    mid-verb complement: the per-subprocess ceiling a hung review engine is
    killed at, consumed by ``review``'s runner rather than the boundary check.
    ``attended_idle_minutes`` is neither: it is ``reclaim --stale``'s staleness
    threshold for a run that declared itself attended (#297), the retrospective
    half of a mode that has no prospective clock at all.
    ``unconditional_review_cycles`` shapes the first breaker rather than adding
    one: it splits the budget into the window that needs no judgment and the
    window that does.

    ``review_model`` is none of those: it is not a bound at all but the alias the
    claude review engine is invoked with (#321). It rides here because it is
    configured in the same ``loop:`` block and read on the same path, so the verb
    resolves one object rather than two.

    Each new field is **appended last** so every existing positional
    construction — including ``load_loop_budget``'s ``OSError`` fallback — keeps
    its meaning, the rule ``attended_idle_minutes`` (#297) and
    ``unconditional_review_cycles`` (#329) each followed in turn.
    """

    max_review_cycles: int
    wall_clock_budget_minutes: int
    engine_timeout_seconds: int = DEFAULT_ENGINE_TIMEOUT_SECONDS
    attended_idle_minutes: int = DEFAULT_ATTENDED_IDLE_MINUTES
    unconditional_review_cycles: int = DEFAULT_UNCONDITIONAL_REVIEW_CYCLES
    review_model: str = DEFAULT_REVIEW_MODEL


class BreakerTrip(NamedTuple):
    """A tripped breaker: the stable ``reason`` tag and a human message."""

    reason: str
    message: str


# ---------------------------------------------------------------------------
# Config — read the thresholds from CONTEXT.md (not hardcoded)
# ---------------------------------------------------------------------------

# Each threshold is a distinctly-named integer key in CONTEXT.md's ``loop:``
# block.  The keys are unique enough that a direct per-key match is robust and
# avoids pulling in a YAML parser for two integers (engineering-principles:
# smallest change).  A missing or unparseable key falls back to its default.
_KEY_PATTERN = r"^\s*{key}:\s*(\d+)\s*(?:#.*)?$"

# The sibling for a token-valued key (#321). The character class is deliberately
# narrow: the one such key is a model alias that becomes an ``--model <alias>``
# argv element, so a value carrying whitespace, a quote or a shell metacharacter
# does not match and the loader falls back to the default rather than forwarding
# it to a subprocess.
_STR_KEY_PATTERN = r"^\s*{key}:\s*([A-Za-z0-9._-]+)\s*(?:#.*)?$"


def _read_int_key(text: str, key: str, default: int) -> int:
    match = re.search(_KEY_PATTERN.format(key=re.escape(key)), text, re.MULTILINE)
    if match is None:
        return default
    return int(match.group(1))


def _read_str_key(text: str, key: str, default: str) -> str:
    match = re.search(_STR_KEY_PATTERN.format(key=re.escape(key)), text, re.MULTILINE)
    if match is None:
        return default
    return match.group(1)


def load_loop_budget(repo_root: Path) -> LoopBudget:
    """Load the loop thresholds from ``repo_root/CONTEXT.md``.

    Falls back to :data:`DEFAULT_MAX_REVIEW_CYCLES` /
    :data:`DEFAULT_WALL_CLOCK_BUDGET_MINUTES` when CONTEXT.md is absent or a key
    is missing, so a repo that has not configured the ``loop:`` block still gets
    the proposal's defaults rather than an unbounded loop. The fallback is
    shared for the same reason the configured value is (#260): both consumers
    land on one constant, so the no-CONTEXT.md path cannot drift either.

    Not breaker-only: ``wall_clock_budget_minutes`` is also the single source of
    ``reclaim --stale``'s default staleness threshold, which resolves it through
    this same function rather than carrying a literal of its own.
    """
    context = repo_root / "CONTEXT.md"
    try:
        text = context.read_text()
    except OSError:
        return LoopBudget(
            DEFAULT_MAX_REVIEW_CYCLES,
            DEFAULT_WALL_CLOCK_BUDGET_MINUTES,
            DEFAULT_ENGINE_TIMEOUT_SECONDS,
        )
    # Both cycle keys are clamped rather than validated: this loader degrades,
    # it does not raise — a repo must never be unable to run a verb because its
    # CONTEXT.md holds a nonsensical integer. ``max`` floors at 1 because a
    # budget of 0 would refuse the *first* review and wedge every run at its
    # first boundary; ``unconditional`` is held inside [1, max] because a window
    # larger than the budget can never be left, and one of 0 would demand a
    # convergence judgment before the very first cycle.
    max_cycles = max(1, _read_int_key(text, "max_review_cycles", DEFAULT_MAX_REVIEW_CYCLES))
    unconditional = _read_int_key(
        text, "unconditional_review_cycles", DEFAULT_UNCONDITIONAL_REVIEW_CYCLES
    )
    return LoopBudget(
        max_review_cycles=max_cycles,
        wall_clock_budget_minutes=_read_int_key(
            text, "wall_clock_budget_minutes", DEFAULT_WALL_CLOCK_BUDGET_MINUTES
        ),
        engine_timeout_seconds=_read_int_key(
            text, "engine_timeout_seconds", DEFAULT_ENGINE_TIMEOUT_SECONDS
        ),
        attended_idle_minutes=_read_int_key(
            text, "attended_idle_minutes", DEFAULT_ATTENDED_IDLE_MINUTES
        ),
        unconditional_review_cycles=min(max(1, unconditional), max_cycles),
        review_model=_read_str_key(text, "review_model", DEFAULT_REVIEW_MODEL),
    )


# ---------------------------------------------------------------------------
# The breaker decision — pure
# ---------------------------------------------------------------------------


def evaluate_breakers(
    *,
    prior_review_count: int,
    started_at: datetime,
    now: datetime,
    budget: LoopBudget,
    attended: bool = False,
) -> BreakerTrip | None:
    """Decide whether the *upcoming* review must be refused. ``None`` = proceed.

    ``prior_review_count`` is the number of ``review`` events already recorded
    for the run, so the review about to run is cycle ``prior_review_count + 1``.

    Checks, in order (the cycle ceiling first so a fast runaway reports the loop
    bound deterministically even when it has also blown the clock):

    1. **Cycle ceiling.** ``max_review_cycles`` counts the cycles a run may
       *spend*, so the refusal lands once they are used up — i.e. when
       ``prior_review_count >= max_review_cycles``. With the default 5 that runs
       cycles 1–5 and refuses the 6th call.  **Unconditional** — it bounds the
       fix loop itself, which an operator's presence does not make cheaper.
    2. **Wall-clock**, *unattended runs only* (#296, ADR 0011). The run has
       *exceeded* (strictly) the wall-clock budget.  The clock stands in for
       autonomous spend; in an attended run its elapsed time also counts however
       long the operator took to answer, during which the run spent nothing, so
       measuring it would refuse finished work for time that cost nothing.

    ``attended`` defaults to :data:`False` deliberately rather than being
    required: unattended is both the default and the failure default (ADR 0011),
    so a caller with no view of the mode inherits the *bounded* behaviour. The
    exemption must be asked for; it is never acquired by omission.
    """
    upcoming_cycle = prior_review_count + 1
    if prior_review_count >= budget.max_review_cycles:
        return BreakerTrip(
            REVIEW_CYCLE_CEILING_REASON,
            f"review→fix cycle budget exhausted: the {budget.max_review_cycles} "
            f"review→fix cycles this run may spend are used up, so cycle "
            f"{upcoming_cycle} is refused. The run stops and the ticket goes on "
            f"operator hold rather than spinning further.",
        )

    # Strictly below the ceiling's return, so the ordering above is unaffected:
    # a run eligible for both breakers still reports the ceiling, in either mode.
    if not attended:
        elapsed_minutes = (now - started_at).total_seconds() / 60.0
        if elapsed_minutes > budget.wall_clock_budget_minutes:
            return BreakerTrip(
                WALL_CLOCK_BUDGET_REASON,
                f"per-run wall-clock budget exceeded: {elapsed_minutes:.1f} min "
                f"elapsed against a {budget.wall_clock_budget_minutes}-minute "
                f"budget. The run is flagged for escalation at this verb boundary.",
            )

    return None


def convergence_check_required(
    *,
    cycles_completed: int,
    verdict: str,
    budget: LoopBudget,
) -> bool:
    """Whether this fail is the last one inside the unconditional window or later.

    ``cycles_completed`` includes the review just run, and the advisory is about
    the cycle the agent is deciding whether to spend *next*. So a ``fail`` on the
    **last unconditional cycle** already owes a judgment — the next cycle is the
    first judged one — which is why the low bound is ``<=`` and not ``<`` (#329).
    The old strict bound fired one cycle late: at the canonical 3-unconditional
    window it first advised after cycle 4, when the rule demands the judgment
    *before* cycle 4. The upper bound stays strict — a fail on the last cycle the
    budget allows is not an invitation to assess convergence, it is
    :func:`cycles_exhausted`. A ``pass`` heads to ``close`` — never an advisory.
    """
    if verdict != "fail":
        return False
    return (
        budget.unconditional_review_cycles
        <= cycles_completed
        < budget.max_review_cycles
    )


def cycles_exhausted(
    *,
    cycles_completed: int,
    verdict: str,
    budget: LoopBudget,
) -> bool:
    """Whether this fail consumed the last review→fix cycle the run may spend.

    The terminal half of the advisory pair (#329). ``convergence_check_required``
    says *judge before spending another*; this says *there is no other to spend*
    — stop, preserve the WIP, and put the ticket on operator hold.

    It exists so the stop lands where the canonical rule says it lands: at the
    **completion** of the last allowed cycle. The exit-4 refusal in
    :func:`evaluate_breakers` is the deterministic backstop for an orchestrator
    that ignores this flag, but by the time it fires the run has already spent a
    whole implement pass on work it was never allowed to review.

    Fail-only, like the advisory: a ``pass`` or ``defer`` on the last cycle is a
    finished run heading to ``close``, not an exhausted one.
    """
    if verdict != "fail":
        return False
    return cycles_completed >= budget.max_review_cycles
