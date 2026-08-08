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

# size: one production module's whole contract, and it is a *table* of knobs
# rather than a set of behaviours — every knob added to ``LoopBudget`` costs this
# file a fixed handful of cases (present / absent / unreadable / clamped), so it
# grows linearly with a table it does not control. #359's
# ``untracked_file_limit`` is the addition that crossed the ceiling; the file sat
# just under it beforehand, which is exactly the state in which the next feature
# trips a guard that is not really about that feature.
#
# The extraction candidate, named rather than deferred vaguely: the
# ``load_loop_budget`` cases — everything that writes a synthetic CONTEXT.md and
# asserts what comes back — split to ``test_loop_budget_loader.py``, leaving the
# pure decision functions (``evaluate_breakers``, the convergence advisory,
# ``cycles_exhausted``, ``evaluate_repeat_timeout``) here. The seam is real and
# already visible in the helper split: the loader half builds files through
# ``_write_context`` / ``_write_loop_block``, the decision half builds values
# through ``_budget``, and the two share nothing but the ``LoopBudget`` type.
# It is not done in #359 because that ticket adds one knob and the split touches
# every case in the file, which would bury the change under the move.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from harness import loop_budget
from harness.loop_budget import (
    DEFAULT_ATTENDED_IDLE_MINUTES,
    DEFAULT_ENGINE_TIMEOUT_SECONDS,
    DEFAULT_MAX_REVIEW_CYCLES,
    DEFAULT_REVIEW_MODEL,
    DEFAULT_UNCONDITIONAL_REVIEW_CYCLES,
    DEFAULT_WALL_CLOCK_BUDGET_MINUTES,
    ENGINE_TIMEOUT_ATTEMPT_LIMIT,
    REPEAT_ENGINE_TIMEOUT_REASON,
    REVIEW_CYCLE_CEILING_REASON,
    WALL_CLOCK_BUDGET_REASON,
    LoopBudget,
    convergence_check_required,
    cycles_exhausted,
    evaluate_breakers,
    evaluate_repeat_timeout,
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
    assert budget.engine_timeout_seconds == DEFAULT_ENGINE_TIMEOUT_SECONDS == 900


def test_load_defaults_engine_timeout_when_no_context(tmp_path: Path) -> None:
    """No CONTEXT.md at all → the documented engine-timeout default."""
    budget = load_loop_budget(tmp_path)
    assert budget.engine_timeout_seconds == DEFAULT_ENGINE_TIMEOUT_SECONDS == 900


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
# review_model — the claude review engine's alias, configured once (#321)
#
# It replaces the per-ticket ``review:<tier>`` label ADR 0005 established. The
# knob is a **plain token string**, not the retired ``Literal["sonnet","opus"]``
# — an enum is the same premature constraint being retired, and it would coerce
# a typo to the default, hiding the operator's mistake behind a review that ran
# on the wrong model.
# ---------------------------------------------------------------------------


def _write_review_model(root: Path, value: str) -> None:
    (root / "CONTEXT.md").write_text(
        "```yaml\nprofile: harness\nloop:\n" f"  review_model: {value}\n```\n"
    )


def test_load_reads_review_model_from_context(tmp_path: Path) -> None:
    """The review engine's alias is read from the ``loop:`` block (#321 AC-4)."""
    _write_review_model(tmp_path, "opus")
    assert load_loop_budget(tmp_path).review_model == "opus"


def test_load_reads_an_alias_the_harness_has_no_opinion_about(tmp_path: Path) -> None:
    """Any bare token is carried through — the value is not an enum (#321).

    The retired mechanism resolved to one of two literals and silently coerced
    everything else to ``sonnet``. That is the constraint being dropped: a third
    alias must be a one-line CONTEXT.md edit, not a code change, and a typo must
    reach the claude CLI and fail loudly rather than run the wrong model quietly.
    """
    _write_review_model(tmp_path, "haiku")
    assert load_loop_budget(tmp_path).review_model == "haiku"


def test_load_defaults_review_model_when_absent(tmp_path: Path) -> None:
    """A ``loop:`` block without the key falls back to the documented default."""
    _write_context(tmp_path, max_cycles=6, wall_clock=90)
    assert load_loop_budget(tmp_path).review_model == DEFAULT_REVIEW_MODEL == "opus"


def test_load_defaults_review_model_when_no_context(tmp_path: Path) -> None:
    """No CONTEXT.md at all → the same default a configured repo ships (AC-4)."""
    assert load_loop_budget(tmp_path).review_model == DEFAULT_REVIEW_MODEL == "opus"


def test_a_value_outside_the_token_pattern_falls_back(tmp_path: Path) -> None:
    """A value carrying whitespace or quotes never reaches an argv (#321).

    The alias is passed to the claude engine as ``--model <alias>``, so the
    loader admits only a bare token. Anything else is treated as an unset key —
    the same degrade-never-raise posture the integer knobs take, because a
    nonsensical CONTEXT.md must never make a repo unable to run a verb.
    """
    _write_review_model(tmp_path, '"gpt 4"')
    assert load_loop_budget(tmp_path).review_model == DEFAULT_REVIEW_MODEL


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


# ---------------------------------------------------------------------------
# evaluate_repeat_timeout — the third breaker, keyed on the tree (#347)
#
# Run 01KZ67FRV3HZRZ8CMAHBYBP4QT recorded four consecutive ``engine_timeout``
# refusals at one SHA, ~725s each: ~44% of the unattended wall-clock budget spent
# re-buying an identical answer. The decision is pure here for the same reason
# the other two are — the numeric bound stays measurable in a unit test.
# ---------------------------------------------------------------------------

_SHA = "1dff096187a00450711e5b9abb983036417f80af"


@pytest.mark.parametrize("timeouts", [0, 1])
def test_a_tree_under_the_limit_still_gets_its_attempt(timeouts: int) -> None:
    """One hang is worth a re-run; the bound is two attempts spent, then stop."""
    assert (
        evaluate_repeat_timeout(
            timeouts_at_sha=timeouts, reviewed_sha=_SHA, budget=_budget()
        )
        is None
    )


@pytest.mark.parametrize("timeouts", [2, 3, 4])
def test_a_tree_at_or_past_the_limit_trips(timeouts: int) -> None:
    """At the limit and beyond — so a run that refused once refuses again.

    Idempotence matters because the refusal itself is recorded: a decision that
    only fired at *exactly* the limit would let an over-count (a hand-edited
    ledger, a retried write) reopen the retry loop.
    """
    trip = evaluate_repeat_timeout(
        timeouts_at_sha=timeouts, reviewed_sha=_SHA, budget=_budget()
    )
    assert trip is not None
    assert trip.reason == REPEAT_ENGINE_TIMEOUT_REASON


def test_the_trip_message_names_the_tree_and_the_ceiling_it_burned() -> None:
    """The message must let a reader act without opening the ledger."""
    budget = _budget()
    trip = evaluate_repeat_timeout(
        timeouts_at_sha=ENGINE_TIMEOUT_ATTEMPT_LIMIT, reviewed_sha=_SHA, budget=budget
    )
    assert trip is not None
    assert _SHA[:12] in trip.message
    assert str(budget.engine_timeout_seconds) in trip.message


def test_raising_the_ceiling_is_named_as_the_wrong_remedy() -> None:
    """AC-4's claim, on the breaker's own message.

    The ``engine_timeout`` detail this replaces told the reader to raise
    ``engine_timeout_seconds`` — the one change that makes a hang *worse*, since
    it spends more per dead attempt and brings the wall-clock breaker forward.
    A message that stops the loop while still pointing at that lever would hand
    the next reader the same wrong move.
    """
    trip = evaluate_repeat_timeout(
        timeouts_at_sha=ENGINE_TIMEOUT_ATTEMPT_LIMIT, reviewed_sha=_SHA, budget=_budget()
    )
    assert trip is not None
    assert "engine_timeout_seconds is not the remedy here" in trip.message


def test_the_limit_is_a_parameter_so_a_repo_key_can_arrive_later() -> None:
    """The bound is defaulted, not baked into the comparison."""
    assert (
        evaluate_repeat_timeout(
            timeouts_at_sha=1, reviewed_sha=_SHA, budget=_budget(), limit=1
        )
        is not None
    )
    assert (
        evaluate_repeat_timeout(
            timeouts_at_sha=2, reviewed_sha=_SHA, budget=_budget(), limit=3
        )
        is None
    )


def _write_loop_block(root: Path, body: str) -> None:
    """Write a CONTEXT.md whose ``loop:`` block is exactly ``body``.

    The sibling ``_write_context`` takes one keyword per knob, which does not
    reach the cases below: a key spelled with a value its reader *rejects*, and a
    block that omits the key entirely.
    """
    (root / "CONTEXT.md").write_text(
        "<!-- guidance:template-context@0.1.4 -->\n"
        "# CONTEXT.md\n\n"
        "```yaml\n"
        "profile: harness\n"
        f"{body}"
        "```\n"
    )


# --- untracked_file_limit (#359) ----------------------------------------------
#
# The bound ``review``'s polluted-worktree guard measures a run worktree against.
# A CONTEXT key rather than a module constant like ``ENGINE_TIMEOUT_ATTEMPT_LIMIT``
# on the criterion that constant's own comment states: there is no repo for which
# a fifth identical timeout is right, but there *is* one for which a large
# untracked tree is right — a JS repo whose gate cannot run without
# ``node_modules`` in the worktree. Without the key, that repo's every review is
# refused with no recourse.


def test_load_reads_the_untracked_file_limit_from_context(tmp_path: Path) -> None:
    """A configured key wins over the constant."""
    _write_loop_block(tmp_path, "loop:\n  untracked_file_limit: 250\n")
    assert load_loop_budget(tmp_path).untracked_file_limit == 250


def test_load_defaults_the_untracked_file_limit_when_absent(tmp_path: Path) -> None:
    """An absent key falls back to the constant, so an unconfigured repo is guarded."""
    _write_loop_block(tmp_path, "loop:\n  max_review_cycles: 5\n")
    assert (
        load_loop_budget(tmp_path).untracked_file_limit
        == loop_budget.DEFAULT_UNTRACKED_FILE_LIMIT
    )


def test_a_zero_untracked_file_limit_is_honoured_as_disabled(tmp_path: Path) -> None:
    """``0`` reaches the caller intact — it is the documented off switch.

    The other integer knobs floor at 1 because a 0 there wedges every run at its
    first boundary. This one is the opposite: 0 means *do not measure*, so a
    clamp would make the escape hatch unreachable.
    """
    _write_loop_block(tmp_path, "loop:\n  untracked_file_limit: 0\n")
    assert load_loop_budget(tmp_path).untracked_file_limit == 0


@pytest.mark.parametrize("raw", ["-5", "lots", ""])
def test_an_unreadable_untracked_file_limit_falls_back(tmp_path: Path, raw: str) -> None:
    """A value the reader's digits-only pattern rejects degrades to the default.

    Notably a **negative** does not clamp to 0 — it does not match at all, so it
    reads as absent. That matters because 0 is the off switch: a clamp would turn
    a typo into a silently disabled guard.
    """
    _write_loop_block(tmp_path, f"loop:\n  untracked_file_limit: {raw}\n")
    assert (
        load_loop_budget(tmp_path).untracked_file_limit
        == loop_budget.DEFAULT_UNTRACKED_FILE_LIMIT
    )
