"""Ledger-backed spend breakers for the autonomous loop — CAL-906 (WS1).

The Build routine and the review→fix→re-review cycle have no view of the
orchestrating session's token meter (the verbs are one-shot CLI calls, not the
session), so the harness cannot meter dollars directly. What it *can* observe,
deterministically, is the ledger: how many ``review`` events a run has recorded
and when the run started. This module turns those two observable facts into two
**circuit breakers** that bound the behaviours that burn tokens:

* a **hard ceiling** on review→fix cycles per run — the run stops and escalates
  on *reaching* the ceiling-th cycle (default 6). Cycles 1..N/2 run
  unconditionally; the cycles after that and below the ceiling carry a
  convergence-assessment advisory (the build agent decides whether the fixes are
  converging before spending another cycle);
* a **per-run wall-clock budget** in minutes (default 90), deliberately mirroring
  the stale-run reclamation staleness threshold so a runaway run trips this
  breaker right as reclamation would call it stale (keep the two in step).

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
    "DEFAULT_ENGINE_TIMEOUT_SECONDS",
    "DEFAULT_MAX_REVIEW_CYCLES",
    "DEFAULT_WALL_CLOCK_BUDGET_MINUTES",
    "REVIEW_CYCLE_CEILING_REASON",
    "WALL_CLOCK_BUDGET_REASON",
    "LoopBudget",
    "BreakerTrip",
    "load_loop_budget",
    "evaluate_breakers",
    "convergence_check_required",
]

# The breaker values set by proposal ``harden-loop-layer`` (D1). They are the
# fallback when CONTEXT.md does not configure them; a repo overrides them in its
# CONTEXT.md ``loop:`` block.
DEFAULT_MAX_REVIEW_CYCLES = 6
DEFAULT_WALL_CLOCK_BUDGET_MINUTES = 90

# The review-engine subprocess ceiling (CAL-1004). The two breakers above are
# checked only at *verb boundaries*; a review engine that hangs mid-verb is
# bounded by neither until the next boundary. This ceiling closes that gap — it
# caps a single ``claude -p`` / ``codex exec`` subprocess so a hung engine is
# killed and surfaced as an infra failure rather than hanging the verb until an
# external kill. Default 600s to match the documented ops kill; a repo overrides
# it in the same ``loop:`` block.
DEFAULT_ENGINE_TIMEOUT_SECONDS = 600

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
    """

    max_review_cycles: int
    wall_clock_budget_minutes: int
    engine_timeout_seconds: int = DEFAULT_ENGINE_TIMEOUT_SECONDS

    @property
    def unconditional_review_cycles(self) -> int:
        """Cycles 1..this run unconditionally; later cycles assess convergence.

        Derived as half the ceiling: proposal ``harden-loop-layer`` sets the
        ceiling at "double the unconditional 3", so the two move together from
        one configured knob rather than drifting as two independent numbers.
        """
        return self.max_review_cycles // 2


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


def _read_int_key(text: str, key: str, default: int) -> int:
    match = re.search(_KEY_PATTERN.format(key=re.escape(key)), text, re.MULTILINE)
    if match is None:
        return default
    return int(match.group(1))


def load_loop_budget(repo_root: Path) -> LoopBudget:
    """Load the breaker thresholds from ``repo_root/CONTEXT.md``.

    Falls back to :data:`DEFAULT_MAX_REVIEW_CYCLES` /
    :data:`DEFAULT_WALL_CLOCK_BUDGET_MINUTES` when CONTEXT.md is absent or a key
    is missing, so a repo that has not configured the ``loop:`` block still gets
    the proposal's defaults rather than an unbounded loop.
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
    return LoopBudget(
        max_review_cycles=_read_int_key(
            text, "max_review_cycles", DEFAULT_MAX_REVIEW_CYCLES
        ),
        wall_clock_budget_minutes=_read_int_key(
            text, "wall_clock_budget_minutes", DEFAULT_WALL_CLOCK_BUDGET_MINUTES
        ),
        engine_timeout_seconds=_read_int_key(
            text, "engine_timeout_seconds", DEFAULT_ENGINE_TIMEOUT_SECONDS
        ),
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
) -> BreakerTrip | None:
    """Decide whether the *upcoming* review must be refused. ``None`` = proceed.

    ``prior_review_count`` is the number of ``review`` events already recorded
    for the run, so the review about to run is cycle ``prior_review_count + 1``.

    Checks, in order (the cycle ceiling first so a fast runaway reports the loop
    bound deterministically even when it has also blown the clock):

    1. **Cycle ceiling.** The run stops on reaching the ceiling-th cycle — i.e.
       when the upcoming cycle ``>= max_review_cycles``. With the default 6 that
       refuses the 6th review (cycles 1–5 ran).
    2. **Wall-clock.** The run has *exceeded* (strictly) the wall-clock budget.
    """
    upcoming_cycle = prior_review_count + 1
    if upcoming_cycle >= budget.max_review_cycles:
        return BreakerTrip(
            REVIEW_CYCLE_CEILING_REASON,
            f"review→fix cycle ceiling reached: this would be cycle "
            f"{upcoming_cycle} of a maximum {budget.max_review_cycles}. The run "
            f"stops and escalates to the user rather than spinning further.",
        )

    elapsed_minutes = (now - started_at).total_seconds() / 60.0
    if elapsed_minutes > budget.wall_clock_budget_minutes:
        return BreakerTrip(
            WALL_CLOCK_BUDGET_REASON,
            f"per-run wall-clock budget exceeded: {elapsed_minutes:.1f} min "
            f"elapsed against a {budget.wall_clock_budget_minutes}-minute budget. "
            f"The run is flagged for escalation at this verb boundary.",
        )

    return None


def convergence_check_required(
    *,
    cycles_completed: int,
    verdict: str,
    budget: LoopBudget,
) -> bool:
    """Whether this fail lands past the unconditional window and below the ceiling.

    ``cycles_completed`` includes the review just run. A ``fail`` on a cycle
    *strictly after* the unconditional window (``> unconditional_review_cycles``)
    and below the ceiling means the build agent must assess whether the fixes are
    converging before spending another cycle — cycles 1..N/2 ran unconditionally,
    so only fails past them are flagged. A ``pass`` heads to ``close`` — never an
    advisory.
    """
    if verdict != "fail":
        return False
    return (
        budget.unconditional_review_cycles
        < cycles_completed
        < budget.max_review_cycles
    )
