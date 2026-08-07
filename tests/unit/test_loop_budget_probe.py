"""#363 — the two `loop:` knobs that bound `review`'s probe stage.

AC-4 says the probe budget must be an enforced **bound**, not a convention. Two
quantities need bounding and they fail differently, so they are two keys:

* `probe_max_entries` — how many mutations one review may run. Also the stage's
  **disable switch** at `0`, on `untracked_file_limit`'s convention: one knob,
  rather than a knob plus a flag that can disagree with it.
* `probe_budget_seconds` — how long the mutation subprocess may take before it is
  killed. Clamped by the loader to `engine_timeout_seconds`, so one review's
  added cost can never exceed one engine's ceiling.

Its own module rather than more of `test_loop_budget.py`: that module's recorded
`# size:` decision already puts it over the ceiling on the grounds that #360-era
knobs read as one table, and its named extraction candidate is the loader cases.
Appending two more knobs to it would grow the file the marker exists to bound.

The **clamp direction** is the claim worth testing hardest. Raising
`engine_timeout_seconds` to buy a probe more time is the standing "the ceiling is
not the fix" mistake wearing a new hat, so the relationship has to hold from the
probe side: configuring a larger probe budget than the engine ceiling silently
yields the engine ceiling, never the other way round.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.loop_budget import (
    DEFAULT_ENGINE_TIMEOUT_SECONDS,
    DEFAULT_PROBE_BUDGET_SECONDS,
    DEFAULT_PROBE_MAX_ENTRIES,
    load_loop_budget,
)


def _repo(tmp_path: Path, loop_block: str) -> Path:
    (tmp_path / "CONTEXT.md").write_text(f"loop:\n{loop_block}", encoding="utf-8")
    return tmp_path


def test_a_repo_with_no_loop_block_runs_the_shipped_defaults(tmp_path: Path) -> None:
    """`DEFAULT_*` carries the same value in lockstep (#291's rule)."""
    budget = load_loop_budget(tmp_path)

    assert budget.probe_max_entries == DEFAULT_PROBE_MAX_ENTRIES
    assert budget.probe_budget_seconds == DEFAULT_PROBE_BUDGET_SECONDS


def test_both_keys_are_read_from_context(tmp_path: Path) -> None:
    budget = load_loop_budget(
        _repo(tmp_path, "  probe_max_entries: 5\n  probe_budget_seconds: 120\n")
    )

    assert budget.probe_max_entries == 5
    assert budget.probe_budget_seconds == 120


def test_zero_entries_is_the_documented_off_switch_and_is_not_clamped(tmp_path: Path) -> None:
    """The escape hatch has to be reachable.

    The cycle knobs are floored at 1 because a budget of 0 would wedge every run
    at its first boundary. Here 0 is the *documented* value — it means "run no
    probe stage" — so a floor would make the off switch unreachable, exactly as
    `untracked_file_limit` states for its own 0.
    """
    budget = load_loop_budget(_repo(tmp_path, "  probe_max_entries: 0\n"))

    assert budget.probe_max_entries == 0


@pytest.mark.parametrize(
    ("configured", "expected"),
    [(60, 60), (DEFAULT_ENGINE_TIMEOUT_SECONDS, DEFAULT_ENGINE_TIMEOUT_SECONDS)],
    ids=["under-the-ceiling", "at-the-ceiling"],
)
def test_a_probe_budget_at_or_below_the_engine_ceiling_is_taken_as_written(
    tmp_path: Path, configured: int, expected: int
) -> None:
    budget = load_loop_budget(_repo(tmp_path, f"  probe_budget_seconds: {configured}\n"))

    assert budget.probe_budget_seconds == expected


def test_a_probe_budget_above_the_engine_ceiling_is_clamped_to_it(tmp_path: Path) -> None:
    """AC-4's bound, and the reason it is a *clamp* rather than a validation.

    The loader degrades, it does not raise: a repo must never be unable to run a
    verb because its CONTEXT.md holds an over-ambitious integer. What it must not
    do is honour a probe budget larger than the ceiling the engine itself runs
    under — that would let the added cost of probing exceed the cost of the thing
    it is added to.
    """
    budget = load_loop_budget(
        _repo(
            tmp_path,
            "  engine_timeout_seconds: 300\n  probe_budget_seconds: 9000\n",
        )
    )

    assert budget.engine_timeout_seconds == 300
    assert budget.probe_budget_seconds == 300


def test_the_clamp_follows_a_lowered_engine_ceiling_rather_than_the_default(
    tmp_path: Path,
) -> None:
    """The clamp reads the *configured* ceiling, not the constant.

    A repo that lowers `engine_timeout_seconds` and leaves the probe budget at
    its default would otherwise get a probe stage allowed to outlast its own
    engine — the drift a clamp against the constant cannot see.
    """
    budget = load_loop_budget(_repo(tmp_path, "  engine_timeout_seconds: 45\n"))

    assert budget.probe_budget_seconds == 45
