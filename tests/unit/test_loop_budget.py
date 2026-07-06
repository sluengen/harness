"""CAL-906 (WS1, proposal ``harden-loop-layer``) — ledger-backed spend breakers.

The autonomous Build loop and the review→fix→re-review cycle had no per-run
budget and no hard retry ceiling. ``harness/loop_budget.py`` is the pure home of
the two deterministic breakers the harness *can* observe from the ledger:

* a **hard ceiling** on review→fix cycles per run — the run stops and escalates
  on reaching the ceiling-th cycle (default 6; cycles 1–3 unconditional, 4–5
  assess convergence);
* a **per-run wall-clock budget** in minutes (default 90, deliberately mirroring
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

from harness.loop_budget import (
    DEFAULT_ENGINE_TIMEOUT_SECONDS,
    DEFAULT_MAX_REVIEW_CYCLES,
    DEFAULT_WALL_CLOCK_BUDGET_MINUTES,
    REVIEW_CYCLE_CEILING_REASON,
    WALL_CLOCK_BUDGET_REASON,
    LoopBudget,
    convergence_check_required,
    evaluate_breakers,
    load_loop_budget,
)

# A fixed, aware-UTC anchor so wall-clock arithmetic is exact.
_T0 = datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)


def _budget(max_cycles: int = 6, wall_clock: int = 90) -> LoopBudget:
    return LoopBudget(
        max_review_cycles=max_cycles, wall_clock_budget_minutes=wall_clock
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
    """A repo with no CONTEXT.md falls back to the documented defaults (6 / 90)."""
    budget = load_loop_budget(tmp_path)
    assert budget.max_review_cycles == DEFAULT_MAX_REVIEW_CYCLES == 6
    assert budget.wall_clock_budget_minutes == DEFAULT_WALL_CLOCK_BUDGET_MINUTES == 90


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
    assert budget.engine_timeout_seconds == DEFAULT_ENGINE_TIMEOUT_SECONDS == 600


def test_load_defaults_engine_timeout_when_no_context(tmp_path: Path) -> None:
    """No CONTEXT.md at all → the documented engine-timeout default."""
    budget = load_loop_budget(tmp_path)
    assert budget.engine_timeout_seconds == DEFAULT_ENGINE_TIMEOUT_SECONDS == 600


def test_load_defaults_when_loop_block_absent(tmp_path: Path) -> None:
    """A CONTEXT.md without a ``loop:`` block falls back to the defaults."""
    (tmp_path / "CONTEXT.md").write_text("```yaml\nprofile: harness\n```\n")
    budget = load_loop_budget(tmp_path)
    assert budget.max_review_cycles == 6
    assert budget.wall_clock_budget_minutes == 90


def test_load_partial_loop_block_defaults_the_missing_key(tmp_path: Path) -> None:
    """One key present, the other missing → the missing one defaults."""
    (tmp_path / "CONTEXT.md").write_text(
        "```yaml\nloop:\n  max_review_cycles: 8\n```\n"
    )
    budget = load_loop_budget(tmp_path)
    assert budget.max_review_cycles == 8
    assert budget.wall_clock_budget_minutes == 90


# ---------------------------------------------------------------------------
# evaluate_breakers — the 6-cycle ceiling (AC-1)
# ---------------------------------------------------------------------------


def test_cycles_one_to_five_do_not_trip_the_ceiling() -> None:
    """Reviews 1–5 (prior count 0–4) run; no ceiling trip yet."""
    for prior in range(0, 5):  # cycles 1..5
        trip = evaluate_breakers(
            prior_review_count=prior, started_at=_T0, now=_T0, budget=_budget()
        )
        assert trip is None, f"cycle {prior + 1} must not trip the ceiling"


def test_sixth_cycle_trips_and_escalates() -> None:
    """Reaching the 6th review→fix cycle (5 prior reviews) stops + escalates (AC-1)."""
    trip = evaluate_breakers(
        prior_review_count=5, started_at=_T0, now=_T0, budget=_budget()
    )
    assert trip is not None
    assert trip.reason == REVIEW_CYCLE_CEILING_REASON
    assert "6" in trip.message  # names the ceiling


def test_ceiling_is_read_from_budget_not_hardcoded() -> None:
    """A CONTEXT.md ceiling of 4 trips at the 4th cycle, proving it is configured."""
    # cycles 1..3 (prior 0..2) clear; cycle 4 (prior 3) trips.
    assert (
        evaluate_breakers(
            prior_review_count=2, started_at=_T0, now=_T0, budget=_budget(max_cycles=4)
        )
        is None
    )
    trip = evaluate_breakers(
        prior_review_count=3, started_at=_T0, now=_T0, budget=_budget(max_cycles=4)
    )
    assert trip is not None and trip.reason == REVIEW_CYCLE_CEILING_REASON


# ---------------------------------------------------------------------------
# evaluate_breakers — the 90-minute wall-clock (AC-3)
# ---------------------------------------------------------------------------


def test_wall_clock_within_budget_does_not_trip() -> None:
    """A run at exactly 90 minutes has not *exceeded* the budget — no trip."""
    now = _T0 + timedelta(minutes=90)
    trip = evaluate_breakers(
        prior_review_count=0, started_at=_T0, now=now, budget=_budget()
    )
    assert trip is None


def test_wall_clock_exceeded_trips() -> None:
    """A run past 90 minutes trips the wall-clock breaker (AC-3)."""
    now = _T0 + timedelta(minutes=90, seconds=1)
    trip = evaluate_breakers(
        prior_review_count=0, started_at=_T0, now=now, budget=_budget()
    )
    assert trip is not None
    assert trip.reason == WALL_CLOCK_BUDGET_REASON
    assert "90" in trip.message


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
# convergence_check_required — cycles 1–3 unconditional, 4–5 advise (AC-2)
# ---------------------------------------------------------------------------


def test_unconditional_cycles_do_not_require_convergence_check() -> None:
    """Cycles 1–3 run unconditionally — no convergence advisory on their fails (AC-2)."""
    for completed in (1, 2, 3):
        assert (
            convergence_check_required(
                cycles_completed=completed, verdict="fail", budget=_budget()
            )
            is False
        ), f"cycle {completed} is unconditional"


def test_post_unconditional_fail_requires_convergence_check() -> None:
    """After the 3 unconditional cycles, a FAIL flags the convergence path (AC-2)."""
    for completed in (4, 5):
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


def test_unconditional_window_is_half_the_ceiling() -> None:
    """The unconditional window is derived as half the ceiling (proposal: 6 = double 3)."""
    assert _budget(max_cycles=6).unconditional_review_cycles == 3
    assert _budget(max_cycles=4).unconditional_review_cycles == 2
