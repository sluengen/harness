"""CAL-906 (WS1, proposal ``harden-loop-layer``) — ledger-backed spend breakers.

The autonomous Build loop and the review→fix→re-review cycle had no per-run
budget and no hard retry ceiling. ``harness/loop_budget.py`` is the pure home of
the two deterministic breakers the harness *can* observe from the ledger:

* a **hard ceiling** on review→fix cycles per run — ``max_review_cycles`` counts
  the cycles a run may *spend* (default 5), the first
  ``unconditional_review_cycles`` of them (default 3) needing no convergence
  judgment. Both are independent configured keys since #329; the policy they
  enforce is single-homed in ``skills/review-discipline/SKILL.md``;
* a **per-run wall-clock budget** in minutes (default 110, the single source
  the stale-run reclamation staleness threshold).

Both thresholds are **read from CONTEXT.md** (the ``loop:`` block), not
hardcoded — these tests pin that by loading a synthetic CONTEXT.md and asserting
the loaded values drive the decision.

The decision functions are pure (no DB, no clock): the verb passes in the prior
review count, the run's ``started_at``, and ``now``. That keeps every numeric
bound measurable in a unit test, per ``code-quality`` Part C.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from harness.loop_budget import (
    DEFAULT_ATTENDED_IDLE_MINUTES,
    DEFAULT_ENGINE_TIMEOUT_SECONDS,
    DEFAULT_MAX_REVIEW_CYCLES,
    DEFAULT_UNCONDITIONAL_REVIEW_CYCLES,
    DEFAULT_WALL_CLOCK_BUDGET_MINUTES,
    REVIEW_CYCLE_CEILING_REASON,
    WALL_CLOCK_BUDGET_REASON,
    LoopBudget,
    convergence_check_required,
    cycles_exhausted,
    evaluate_breakers,
    load_loop_budget,
)

# A fixed, aware-UTC anchor so wall-clock arithmetic is exact.
_T0 = datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)


def _budget(
    max_cycles: int = 5, wall_clock: int = 110, unconditional: int = 3
) -> LoopBudget:
    return LoopBudget(
        max_review_cycles=max_cycles,
        wall_clock_budget_minutes=wall_clock,
        unconditional_review_cycles=unconditional,
    )


# ---------------------------------------------------------------------------
# load_loop_budget — thresholds come from CONTEXT.md, not from code
# ---------------------------------------------------------------------------


def _write_context(
    root: Path, *, max_cycles: int, wall_clock: int, engine_timeout: int | None = None
) -> None:
    engine_line = (
        f"  engine_timeout_seconds: {engine_timeout}\n"
        if engine_timeout is not None
        else ""
    )
    (root / "CONTEXT.md").write_text(
        "<!-- guidance:template-context@0.1.4 -->\n"
        "# CONTEXT.md\n\n"
        "```yaml\n"
        "profile: harness\n"
        "loop:\n"
        f"  max_review_cycles: {max_cycles}\n"
        f"  wall_clock_budget_minutes: {wall_clock}\n"
        f"{engine_line}"
        "```\n"
    )


def test_load_reads_thresholds_from_context(tmp_path: Path) -> None:
    """The two breakers are read from CONTEXT.md's ``loop:`` block (AC-4)."""
    _write_context(tmp_path, max_cycles=4, wall_clock=30)
    budget = load_loop_budget(tmp_path)
    assert budget.max_review_cycles == 4
    assert budget.wall_clock_budget_minutes == 30


def test_load_defaults_when_no_context(tmp_path: Path) -> None:
    """A repo with no CONTEXT.md falls back to the documented defaults (5 / 110)."""
    budget = load_loop_budget(tmp_path)
    assert budget.max_review_cycles == DEFAULT_MAX_REVIEW_CYCLES == 5
    assert budget.wall_clock_budget_minutes == DEFAULT_WALL_CLOCK_BUDGET_MINUTES == 110


# ---------------------------------------------------------------------------
# engine_timeout_seconds — the mid-verb subprocess ceiling (CAL-1004)
# ---------------------------------------------------------------------------


def test_load_reads_engine_timeout_from_context(tmp_path: Path) -> None:
    """The review-engine subprocess ceiling is read from the ``loop:`` block (CAL-1004)."""
    _write_context(tmp_path, max_cycles=6, wall_clock=90, engine_timeout=300)
    budget = load_loop_budget(tmp_path)
    assert budget.engine_timeout_seconds == 300


def test_load_defaults_engine_timeout_when_absent(tmp_path: Path) -> None:
    """A ``loop:`` block without the key falls back to the documented default."""
    # CONTEXT.md present but no engine_timeout_seconds line → default, not error.
    _write_context(tmp_path, max_cycles=6, wall_clock=90)
    budget = load_loop_budget(tmp_path)
    assert budget.engine_timeout_seconds == DEFAULT_ENGINE_TIMEOUT_SECONDS == 720


def test_load_defaults_engine_timeout_when_no_context(tmp_path: Path) -> None:
    """No CONTEXT.md at all → the documented engine-timeout default."""
    budget = load_loop_budget(tmp_path)
    assert budget.engine_timeout_seconds == DEFAULT_ENGINE_TIMEOUT_SECONDS == 720


# ---------------------------------------------------------------------------
# attended_idle_minutes — the reclamation threshold for a declared-attended run
# (#297, ADR 0011)
# ---------------------------------------------------------------------------


def test_load_defaults_attended_idle_when_no_context(tmp_path: Path) -> None:
    """AC-4 — no CONTEXT.md at all still yields the *decided* 480, not a missing
    or unbounded value.

    The #291 precedent: a repo that never wrote a ``loop:`` block inherits the
    threshold this repo runs, so ``reclaim --stale`` has a defined attended
    threshold everywhere rather than only where someone configured one.
    """
    budget = load_loop_budget(tmp_path)
    assert budget.attended_idle_minutes == DEFAULT_ATTENDED_IDLE_MINUTES == 480


def test_load_reads_attended_idle_from_context(tmp_path: Path) -> None:
    """AC-4 — a configured value is read, through the same key regex as the rest.

    200 is chosen because it is neither the 480 default nor any other knob's
    value, so neither the fallback nor a mis-wiring to a sibling key satisfies
    it.
    """
    (tmp_path / "CONTEXT.md").write_text(
        "```yaml\nloop:\n  attended_idle_minutes: 200\n```\n"
    )
    budget = load_loop_budget(tmp_path)
    assert budget.attended_idle_minutes == 200


def test_the_attended_threshold_is_not_shorter_than_the_wall_clock() -> None:
    """The shipped defaults keep attendance a *longer* threshold, not a shorter one.

    ADR 0011's distinction between "a longer threshold" and "an exemption" only
    holds in one direction: were the attended value below the wall clock,
    declaring attendance would make a run *more* reclaimable, which is neither
    mode's intent. Pinned as an ordering rather than as numbers, in the spirit of
    ``test_the_engine_ceiling_nests_inside_the_wall_clock``.
    """
    assert DEFAULT_ATTENDED_IDLE_MINUTES >= DEFAULT_WALL_CLOCK_BUDGET_MINUTES


def test_load_defaults_when_loop_block_absent(tmp_path: Path) -> None:
    """A CONTEXT.md without a ``loop:`` block falls back to the defaults."""
    (tmp_path / "CONTEXT.md").write_text("```yaml\nprofile: harness\n```\n")
    budget = load_loop_budget(tmp_path)
    assert budget.max_review_cycles == 5
    assert budget.wall_clock_budget_minutes == 110


def test_load_partial_loop_block_defaults_the_missing_key(tmp_path: Path) -> None:
    """One key present, the other missing → the missing one defaults."""
    (tmp_path / "CONTEXT.md").write_text(
        "```yaml\nloop:\n  max_review_cycles: 8\n```\n"
    )
    budget = load_loop_budget(tmp_path)
    assert budget.max_review_cycles == 8
    assert budget.wall_clock_budget_minutes == 110


# ---------------------------------------------------------------------------
# evaluate_breakers — the review→fix cycle budget (AC-1)
# ---------------------------------------------------------------------------


def test_cycles_one_to_five_do_not_trip_the_ceiling() -> None:
    """Reviews 1–5 (prior count 0–4) run; no ceiling trip yet."""
    for prior in range(0, 5):  # cycles 1..5
        trip = evaluate_breakers(
            prior_review_count=prior, started_at=_T0, now=_T0, budget=_budget()
        )
        assert trip is None, f"cycle {prior + 1} must not trip the ceiling"


def test_the_call_after_the_budget_trips_and_escalates() -> None:
    """The review after the budget is spent stops + escalates (AC-1).

    The message names the **budget**, not the ordinal of the refused call: the
    number a reader has to act on is how many cycles the run was allowed, which
    is the one ``CONTEXT.md`` configures.
    """
    trip = evaluate_breakers(
        prior_review_count=5, started_at=_T0, now=_T0, budget=_budget()
    )
    assert trip is not None
    assert trip.reason == REVIEW_CYCLE_CEILING_REASON
    assert "5" in trip.message


def test_fifth_cycle_is_the_last_allowed() -> None:
    """#329 — ``max_review_cycles`` counts the cycles a run may *spend*.

    The canonical stop policy allows five review→fix cycles in total, so at the
    shipped budget the 5th review runs and the 6th is refused. Before #329 the
    key named the ordinal that trips (``prior + 1 >= max``), so a budget of 5
    refused the 5th cycle and only four ever ran — the same number meaning two
    different things depending on which document you read, which is the drift
    this ticket removes.
    """
    budget = _budget(max_cycles=5)
    assert (
        evaluate_breakers(
            prior_review_count=4, started_at=_T0, now=_T0, budget=budget
        )
        is None
    ), "the 5th review is inside a 5-cycle budget and must run"

    trip = evaluate_breakers(
        prior_review_count=5, started_at=_T0, now=_T0, budget=budget
    )
    assert trip is not None
    assert trip.reason == REVIEW_CYCLE_CEILING_REASON


def test_ceiling_is_read_from_budget_not_hardcoded() -> None:
    """A CONTEXT.md budget of 4 spends 4 cycles and refuses the 5th call."""
    # cycles 1..4 (prior 0..3) clear; the 5th call (prior 4) trips.
    assert (
        evaluate_breakers(
            prior_review_count=3, started_at=_T0, now=_T0, budget=_budget(max_cycles=4)
        )
        is None
    )
    trip = evaluate_breakers(
        prior_review_count=4, started_at=_T0, now=_T0, budget=_budget(max_cycles=4)
    )
    assert trip is not None and trip.reason == REVIEW_CYCLE_CEILING_REASON


# ---------------------------------------------------------------------------
# evaluate_breakers — the configured wall-clock boundary (AC-3; #260 AC-5)
# ---------------------------------------------------------------------------


def test_wall_clock_within_budget_does_not_trip() -> None:
    """A run at exactly 110 minutes has not *exceeded* the budget — no trip.

    The boundary pair below is stated at the **configured** value (#260 AC-5),
    so it moves with ``DEFAULT_WALL_CLOCK_BUDGET_MINUTES`` rather than pinning a
    number the shipped config no longer uses.
    """
    now = _T0 + timedelta(minutes=110)
    trip = evaluate_breakers(
        prior_review_count=0, started_at=_T0, now=now, budget=_budget()
    )
    assert trip is None


def test_wall_clock_exceeded_trips() -> None:
    """A run past 110 minutes trips the wall-clock breaker (AC-3)."""
    now = _T0 + timedelta(minutes=110, seconds=1)
    trip = evaluate_breakers(
        prior_review_count=0, started_at=_T0, now=now, budget=_budget()
    )
    assert trip is not None
    assert trip.reason == WALL_CLOCK_BUDGET_REASON
    assert "110" in trip.message


def test_wall_clock_is_read_from_budget_not_hardcoded() -> None:
    """A CONTEXT.md budget of 30 minutes trips at 31 minutes, proving it is configured."""
    now = _T0 + timedelta(minutes=31)
    trip = evaluate_breakers(
        prior_review_count=0, started_at=_T0, now=now, budget=_budget(wall_clock=30)
    )
    assert trip is not None and trip.reason == WALL_CLOCK_BUDGET_REASON


def test_ceiling_takes_precedence_over_wall_clock() -> None:
    """When both would trip, the cycle ceiling is reported first (deterministic)."""
    now = _T0 + timedelta(minutes=120)
    trip = evaluate_breakers(
        prior_review_count=5, started_at=_T0, now=now, budget=_budget()
    )
    assert trip is not None and trip.reason == REVIEW_CYCLE_CEILING_REASON


# ---------------------------------------------------------------------------
# evaluate_breakers — the wall clock is scoped to unattended runs (#296, ADR 0011)
# ---------------------------------------------------------------------------
#
# Every case below shares one budget and one elapsed value, strictly greater
# than that budget, so the *only* variable across the pair is the mode. The
# elapsed value is derived from the budget rather than restating 111, so it
# stays past the bound if the configured value ever moves.
_ATTENDANCE_BUDGET = _budget()
_PAST_BUDGET = _T0 + timedelta(minutes=_ATTENDANCE_BUDGET.wall_clock_budget_minutes + 1)


def test_attended_run_past_the_budget_does_not_trip() -> None:
    """AC-1: an attended run's elapsed time buys no refusal.

    The clock measures autonomous spend; in an attended session it also counts
    however long the operator took to answer, during which the run spent
    nothing (ADR 0011).
    """
    assert (
        evaluate_breakers(
            prior_review_count=0,
            started_at=_T0,
            now=_PAST_BUDGET,
            budget=_ATTENDANCE_BUDGET,
            attended=True,
        )
        is None
    )


def test_unattended_run_at_the_same_elapsed_value_still_trips() -> None:
    """AC-2: identical arithmetic, opposite verdict.

    Same budget, same ``started_at``, same ``now`` as the attended case above —
    so what changed is the mode, not the bound.
    """
    trip = evaluate_breakers(
        prior_review_count=0,
        started_at=_T0,
        now=_PAST_BUDGET,
        budget=_ATTENDANCE_BUDGET,
        attended=False,
    )
    assert trip is not None
    assert trip.reason == WALL_CLOCK_BUDGET_REASON


def test_omitting_the_mode_leaves_the_run_bounded() -> None:
    """Unattended is the *default*, so a caller with no view of the mode fails
    toward the bound rather than inheriting the exemption by omission."""
    trip = evaluate_breakers(
        prior_review_count=0,
        started_at=_T0,
        now=_PAST_BUDGET,
        budget=_ATTENDANCE_BUDGET,
    )
    assert trip is not None
    assert trip.reason == WALL_CLOCK_BUDGET_REASON


def test_attended_run_still_trips_the_cycle_ceiling() -> None:
    """AC-3: the ceiling is unconditional — attendance exempts the clock only."""
    trip = evaluate_breakers(
        prior_review_count=_ATTENDANCE_BUDGET.max_review_cycles,
        started_at=_T0,
        now=_T0,
        budget=_ATTENDANCE_BUDGET,
        attended=True,
    )
    assert trip is not None
    assert trip.reason == REVIEW_CYCLE_CEILING_REASON


@pytest.mark.parametrize("attended", [True, False])
def test_ceiling_still_wins_over_the_clock_in_both_modes(attended: bool) -> None:
    """AC-4: with both breakers eligible the ceiling is reported, in either mode.

    The mode guard sits strictly below the ceiling's ``return``, so the ordering
    a fast runaway depends on — name the loop bound deterministically even when
    the clock has also blown — is unchanged by this ticket.
    """
    trip = evaluate_breakers(
        prior_review_count=_ATTENDANCE_BUDGET.max_review_cycles,
        started_at=_T0,
        now=_PAST_BUDGET,
        budget=_ATTENDANCE_BUDGET,
        attended=attended,
    )
    assert trip is not None
    assert trip.reason == REVIEW_CYCLE_CEILING_REASON


# ---------------------------------------------------------------------------
# convergence_check_required — the judged window (AC-2; retuned by #329)
# ---------------------------------------------------------------------------


def test_unconditional_cycles_do_not_require_convergence_check() -> None:
    """A fail before the last unconditional cycle owes no judgment yet (AC-2).

    The advisory is about the cycle the agent is deciding to spend *next*, so it
    is silent only while the next cycle is still inside the unconditional
    window. At the shipped 3/5 that is cycles 1 and 2 — a fail on cycle 3 is
    covered by the sibling test below, because the cycle it precedes is judged.
    """
    for completed in (1, 2):
        assert (
            convergence_check_required(
                cycles_completed=completed, verdict="fail", budget=_budget()
            )
            is False
        ), f"cycle {completed} is unconditional"


def test_post_unconditional_fail_requires_convergence_check() -> None:
    """A fail preceding a judged cycle flags the convergence path (AC-2, #329).

    The canonical rule demands a recorded judgment *before* cycles 4 and 5, so
    the advisory must fire on the fails that precede them — cycles 3 and 4. The
    pre-#329 strict low bound fired at 4 and 5, one cycle late, which left the
    judgment before cycle 4 unprompted by the very signal that exists to prompt
    it.
    """
    for completed in (3, 4):
        assert (
            convergence_check_required(
                cycles_completed=completed, verdict="fail", budget=_budget()
            )
            is True
        ), f"cycle {completed} must advise a convergence assessment"


def test_pass_never_requires_convergence_check() -> None:
    """A pass heads to close, not another cycle — no advisory regardless of count."""
    assert (
        convergence_check_required(
            cycles_completed=5, verdict="pass", budget=_budget()
        )
        is False
    )


def test_the_unconditional_window_is_configured_not_derived() -> None:
    """The window is its own key — it does not move when the budget moves (#329).

    It used to be ``max_review_cycles // 2``, which returned the canonical 3
    only because the budget happened to be 6. Holding the budget's two possible
    values against one fixed window is what distinguishes a real key from a
    derivation that coincides with it: under the old property these would read 3
    and 2.
    """
    assert _budget(max_cycles=6, unconditional=3).unconditional_review_cycles == 3
    assert _budget(max_cycles=4, unconditional=3).unconditional_review_cycles == 3
    assert DEFAULT_UNCONDITIONAL_REVIEW_CYCLES == 3


# ---------------------------------------------------------------------------
# cycles_exhausted — the terminal half of the pair (#329)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("completed", [1, 2, 3, 4])
def test_a_fail_inside_the_budget_is_not_exhaustion(completed: int) -> None:
    """Every cycle the run may still follow with another leaves the flag false."""
    assert (
        cycles_exhausted(
            cycles_completed=completed, verdict="fail", budget=_budget()
        )
        is False
    ), f"cycle {completed} is inside a 5-cycle budget"


def test_a_fail_on_the_last_allowed_cycle_is_exhaustion() -> None:
    """A fail that consumed the last cycle stops the run where the policy says.

    This is the signal that makes the stop land at the *completion* of the last
    allowed cycle rather than one wasted implement pass later, when the refused
    call finally reports ``review_cycle_ceiling``.
    """
    assert (
        cycles_exhausted(cycles_completed=5, verdict="fail", budget=_budget()) is True
    )


@pytest.mark.parametrize("verdict", ["pass", "defer"])
def test_only_a_fail_exhausts_the_budget(verdict: str) -> None:
    """A pass or defer on the last cycle is a finished run, not an exhausted one."""
    assert (
        cycles_exhausted(cycles_completed=5, verdict=verdict, budget=_budget()) is False
    )


def test_exhaustion_and_the_advisory_are_mutually_exclusive() -> None:
    """The two flags partition the fails — one asks for a judgment, one ends it.

    An orchestrator that saw both set would have no defined action: the advisory
    says *decide whether to spend another cycle*, exhaustion says *there is none
    to spend*. The bounds are what keep that unrepresentable, so assert it over
    the whole range rather than trusting the two definitions to stay aligned.
    """
    for completed in range(1, 8):
        both = convergence_check_required(
            cycles_completed=completed, verdict="fail", budget=_budget()
        ) and cycles_exhausted(
            cycles_completed=completed, verdict="fail", budget=_budget()
        )
        assert not both, f"cycle {completed} set both flags"


def test_exhaustion_is_read_from_the_budget_not_hardcoded() -> None:
    """A configured budget of 3 exhausts at cycle 3, not at the shipped 5."""
    assert (
        cycles_exhausted(
            cycles_completed=3, verdict="fail", budget=_budget(max_cycles=3)
        )
        is True
    )
    assert (
        cycles_exhausted(
            cycles_completed=2, verdict="fail", budget=_budget(max_cycles=3)
        )
        is False
    )


# ---------------------------------------------------------------------------
# unconditional_review_cycles — the new configured key (#329)
# ---------------------------------------------------------------------------


def test_load_reads_the_unconditional_window_from_context(tmp_path: Path) -> None:
    """The window is configured per repo, through the same key regex as the rest.

    2 is chosen because it is neither the 3 default nor any other knob's value,
    so neither the fallback nor a mis-wiring to a sibling key satisfies it.
    """
    (tmp_path / "CONTEXT.md").write_text(
        "```yaml\nloop:\n  unconditional_review_cycles: 2\n```\n"
    )
    assert load_loop_budget(tmp_path).unconditional_review_cycles == 2


def test_load_defaults_the_unconditional_window_when_absent(tmp_path: Path) -> None:
    """A ``loop:`` block without the key inherits the canonical 3."""
    (tmp_path / "CONTEXT.md").write_text(
        "```yaml\nloop:\n  max_review_cycles: 5\n```\n"
    )
    budget = load_loop_budget(tmp_path)
    assert budget.unconditional_review_cycles == DEFAULT_UNCONDITIONAL_REVIEW_CYCLES


def test_a_window_wider_than_the_budget_clamps_to_it(tmp_path: Path) -> None:
    """A window larger than the budget could never be left — clamp, never raise.

    The loader degrades rather than erroring, so a nonsensical integer costs a
    repo the judged window, not the ability to run a verb at all.
    """
    (tmp_path / "CONTEXT.md").write_text(
        "```yaml\nloop:\n  max_review_cycles: 5\n  unconditional_review_cycles: 9\n```\n"
    )
    budget = load_loop_budget(tmp_path)
    assert budget.unconditional_review_cycles == 5


def test_a_zero_budget_clamps_to_one_runnable_cycle(tmp_path: Path) -> None:
    """``max_review_cycles: 0`` would refuse the *first* review and wedge the run."""
    (tmp_path / "CONTEXT.md").write_text(
        "```yaml\nloop:\n  max_review_cycles: 0\n```\n"
    )
    budget = load_loop_budget(tmp_path)
    assert budget.max_review_cycles == 1
    assert budget.unconditional_review_cycles == 1
    assert (
        evaluate_breakers(
            prior_review_count=0, started_at=_T0, now=_T0, budget=budget
        )
        is None
    ), "the first review must still run under a clamped budget"
