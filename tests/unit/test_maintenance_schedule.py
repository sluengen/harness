"""The maintenance sweep schedule — pure predicates, measured (#310).

Everything here is a function of two integers and a configured interval, with no
clock and no I/O, which is what lets AC-4's criterion be *measured* rather than
described. AC-4 says sweep absence is detectable from the ledger; "absent" is a
quantity — the lag between the newest recorded sweep and now, against one
interval — so the boundary is walked here rather than asserted about the word
"sweep" appearing in some output (``code-quality`` Part C).

The split between this module and :mod:`harness.maintenance.sweep` is the one
``harness/hostenv/broker.py`` already draws: the pure schedule separate from the
thread that obeys it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.loop_budget import (
    DEFAULT_MAINTENANCE_INTERVAL_MINUTES,
    LoopBudget,
    load_loop_budget,
)
from harness.maintenance.schedule import (
    MIN_SWEEP_INTERVAL_MS,
    SweepConfig,
    config_from_budget,
    next_delay_ms,
    sweep_lag_ms,
    sweep_overdue,
)

_INTERVAL_MS = 60 * 60 * 1000


# ---------------------------------------------------------------------------
# AC-4 — the overdue boundary, measured at the interval itself.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lag_ms", "expected"),
    [
        (0, False),
        (_INTERVAL_MS - 1, False),
        (_INTERVAL_MS, False),
        (_INTERVAL_MS + 1, True),
        (_INTERVAL_MS * 5, True),
    ],
)
def test_the_overdue_boundary_is_exactly_one_interval(lag_ms: int, expected: bool) -> None:
    """A sweep is overdue once its lag *exceeds* one interval, not on reaching it.

    The quantity AC-4 states is a duration, so the test moves a clock across the
    boundary and asserts the transition. ``lag == interval`` sitting on the
    ``False`` side is the load-bearing cell: a sweep that fired exactly one
    interval ago is due *now*, and reporting it late would make every healthy
    host WARN once per interval.
    """
    now_ms = 1_000_000_000
    last_ms = now_ms - lag_ms

    assert sweep_overdue(last_ms, now_ms, interval_ms=_INTERVAL_MS) is expected


def test_no_recorded_sweep_is_overdue_rather_than_unknown() -> None:
    """A host up for a day with nothing recorded is the condition AC-4 exists for.

    ``None`` must not read as "cannot tell": the scheduler writes a row for every
    cycle including a no-op, so an empty table means no cycle has completed.
    """
    assert sweep_overdue(None, 1_000_000_000, interval_ms=_INTERVAL_MS) is True


def test_the_lag_is_the_measured_distance_from_the_newest_sweep() -> None:
    """The message doctor prints carries this number, so it is asserted as a number."""
    assert sweep_lag_ms(1_000_000_000 - 90_000, 1_000_000_000) == 90_000


def test_an_unrecorded_sweep_has_no_lag_to_report() -> None:
    """``None``, not ``0``: zero would render as "last sweep 0m ago" — a lie that
    reads as the healthiest possible state."""
    assert sweep_lag_ms(None, 1_000_000_000) is None


# ---------------------------------------------------------------------------
# The wake schedule.
# ---------------------------------------------------------------------------


def test_the_wake_lands_when_the_earliest_repo_comes_due() -> None:
    now_ms = 1_000_000_000
    due = [now_ms + 10 * 60 * 1000, now_ms + 40 * 60 * 1000]

    assert next_delay_ms(due, now_ms, interval_ms=_INTERVAL_MS) == 10 * 60 * 1000


def test_a_repo_already_due_still_waits_the_floor() -> None:
    """A repo never swept is due *now*, and the floor is what bounds a crash-restart
    loop to one sweep per minute per repo rather than a spin."""
    now_ms = 1_000_000_000

    assert next_delay_ms([now_ms], now_ms, interval_ms=_INTERVAL_MS) == MIN_SWEEP_INTERVAL_MS
    assert (
        next_delay_ms([now_ms - _INTERVAL_MS], now_ms, interval_ms=_INTERVAL_MS)
        == MIN_SWEEP_INTERVAL_MS
    )


def test_no_sweepable_repo_falls_back_to_the_plain_interval() -> None:
    """Nothing to sweep is not a reason to spin, and not a reason to stop: the
    thread re-derives the repo set from disk on the next wake, so a repo created
    under an allowed root while ``serve`` runs is picked up without a restart."""
    assert next_delay_ms([], 1_000_000_000, interval_ms=_INTERVAL_MS) == _INTERVAL_MS


def test_the_floor_is_below_the_default_interval() -> None:
    """Non-vacuity floor for the two tests above: were the floor at or above the
    interval, every wake would return the floor and the schedule would be a
    constant, satisfying both assertions for the wrong reason."""
    assert 0 < MIN_SWEEP_INTERVAL_MS < DEFAULT_MAINTENANCE_INTERVAL_MINUTES * 60 * 1000


# ---------------------------------------------------------------------------
# AC-3's sibling: the interval is read from the one loop: block, never carried.
# ---------------------------------------------------------------------------


def test_the_config_reads_the_interval_from_the_loop_budget() -> None:
    budget = LoopBudget(5, 110, maintenance_interval_minutes=17)

    assert config_from_budget(budget) == SweepConfig(interval_minutes=17)
    assert config_from_budget(budget).interval_ms == 17 * 60 * 1000


def test_a_zero_interval_disables_sweeps() -> None:
    """``0`` is this key's documented off switch, on ``untracked_file_limit`` /
    ``probe_max_entries``' convention: a repo that runs ``serve`` but drives
    maintenance from its own scheduler otherwise has no escape hatch."""
    assert SweepConfig(interval_minutes=0).enabled is False
    assert SweepConfig(interval_minutes=1).enabled is True


def test_a_repo_without_a_context_file_still_resolves_an_interval(tmp_path: Path) -> None:
    """The scheduler never has to invent an interval — the same degradation every
    other loop knob has, so a repo that never wrote a ``loop:`` block is swept on
    the constant rather than not at all."""
    assert (
        load_loop_budget(tmp_path).maintenance_interval_minutes
        == DEFAULT_MAINTENANCE_INTERVAL_MINUTES
    )


def test_a_configured_interval_overrides_the_default(tmp_path: Path) -> None:
    """The knob is read from the one ``loop:`` block every other bound comes from,
    so a repo tunes its sweep cadence where it tunes everything else."""
    (tmp_path / "CONTEXT.md").write_text(
        "```yaml\nloop:\n  maintenance_interval_minutes: 7\n```\n", encoding="utf-8"
    )

    assert load_loop_budget(tmp_path).maintenance_interval_minutes == 7
