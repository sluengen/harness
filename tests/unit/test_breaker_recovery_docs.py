"""Doc guard — recovering from a breaker trip requires ``cancel`` before
``start --resume`` (#237).

``start --resume`` resolves a ticket's existing **open** run and returns it
unchanged (``harness/cli/start.py`` step 4 short-circuits before step 4b's
resume resolution ever runs) — so on a run a breaker (``review_cycle_ceiling``
/ ``wall_clock_budget``, :mod:`harness.loop_budget`) already tripped, plain
``--resume`` hands back the *same* ``run_id`` with the *same* ``started_at``,
and the very next ``harness review`` trips the identical breaker immediately.
``commands/harness.md`` documented ``--resume`` as the recovery path (the
proactive context-rollover handoff section) without ever stating that a
still-open run's budget window does not reset on its own, or that
``harness cancel <run_id>`` must run first.

This guard pins the doc fix: a recovery recipe naming ``harness cancel`` ahead
of the ``--resume`` restart, anchored in the Step 3 breaker-refusal region, plus
a cross-reference from the proactive-handoff section (the same "resume reuses
the open row" mechanic applies there too, per the ticket). It binds to
:data:`~harness.loop_budget.REVIEW_CYCLE_CEILING_REASON` /
:data:`~harness.loop_budget.WALL_CLOCK_BUDGET_REASON` so a rename of either
breaker tag that misses the doc fails here, mirroring
``tests/unit/test_context_rollover_handoff.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.loop_budget import REVIEW_CYCLE_CEILING_REASON, WALL_CLOCK_BUDGET_REASON

REPO_ROOT = Path(__file__).parent.parent.parent
HARNESS_COMMAND = REPO_ROOT / "commands" / "harness.md"

_STEP3_HEADING = "**Step 3 — `review`.**"
_STEP4_HEADING = "**Step 4 — `close`.**"
_HANDOFF_HEADING = "#### Proactive context-rollover handoff"
_HANDOFF_END = "**This is distinct from death-keyed reclamation**"


def _doc() -> str:
    return HARNESS_COMMAND.read_text()


def _slice(doc: str, start_needle: str, end_needle: str) -> str:
    start = doc.index(start_needle)
    end = doc.index(end_needle, start)
    return doc[start:end]


def _step3_slice(doc: str) -> str:
    return _slice(doc, _STEP3_HEADING, _STEP4_HEADING)


def _handoff_slice(doc: str) -> str:
    return _slice(doc, _HANDOFF_HEADING, _HANDOFF_END)


def test_step3_and_handoff_slices_are_non_empty() -> None:
    """Anchor: both regions this guard scopes to actually exist and are non-trivial,
    so a heading rename fails loudly here instead of the slicer silently returning
    an empty (vacuously-passing) region below."""
    doc = _doc()
    assert len(_step3_slice(doc)) > 500, "Step 3 region missing or heading renamed"
    assert len(_handoff_slice(doc)) > 200, "handoff section missing or heading renamed"


def test_step3_region_binds_to_both_breaker_reason_tags() -> None:
    """The recovery note must live where the breaker refusal is already documented —
    bound to the actual reason constants so a rename of either tag that misses the
    doc fails here, not silently."""
    step3 = _step3_slice(_doc())
    assert REVIEW_CYCLE_CEILING_REASON in step3
    assert WALL_CLOCK_BUDGET_REASON in step3


def test_step3_documents_cancel_before_resume_recovery() -> None:
    """AC: the Step 3 region states the recovery recipe — `harness cancel` before
    the restart, `harness checkpoint` before that, and the same-row mechanic
    (`run_id` / `started_at`) that makes plain `--resume` insufficient."""
    step3 = _step3_slice(_doc())
    for needle in ("harness cancel", "harness checkpoint", "--resume", "run_id", "started_at"):
        assert needle in step3, (
            f"Step 3's breaker-recovery note must mention {needle!r} "
            "(commands/harness.md, #237)."
        )
    cancel_idx = step3.index("harness cancel")
    # The recovery mention of --resume (the restart) must come after `cancel` —
    # the ordering the fix is about. Find the LAST --resume occurrence in the
    # slice (the restart step), which must still be preceded by `harness cancel`.
    resume_idx = step3.rindex("--resume")
    assert cancel_idx < resume_idx, (
        "Step 3 must document `harness cancel` BEFORE the `--resume` restart — "
        "resuming without cancelling reopens the same tripped run (#237)."
    )
    checkpoint_idx = step3.index("harness checkpoint")
    assert checkpoint_idx < cancel_idx, (
        "Step 3's recovery recipe must checkpoint the WIP before cancelling the "
        "tripped run — cancel does not push the branch, and --resume only "
        "recovers what is on origin (#237)."
    )


def test_handoff_section_cross_references_cancel() -> None:
    """AC: the proactive-handoff section names the same `cancel`-before-resume
    mechanic — the ticket notes the "resume reuses the open row" ambiguity
    applies there too, just without the immediate re-trip consequence."""
    handoff = _handoff_slice(_doc())
    assert "harness cancel" in handoff, (
        "the proactive context-rollover handoff section must cross-reference "
        "`harness cancel` — the same open-run-reuse mechanic applies to a "
        "handoff that never cancels its run (#237)."
    )


# ---------------------------------------------------------------------------
# Non-vacuity: each assertion must actually fail against the pre-fix text.
# ---------------------------------------------------------------------------


def _pre_fix_step3() -> str:
    """A synthetic Step 3 slice matching the text as it stood before #237 —
    verdict bullets with no breaker-recovery note."""
    return (
        "**Step 3 — `review`.** ...\n"
        f"- **`fail`** — ... a 6th `harness review` is refused with "
        f"`reason={REVIEW_CYCLE_CEILING_REASON}` (a `90`-minute per-run wall-clock "
        f"budget trips the same way, `reason={WALL_CLOCK_BUDGET_REASON}`). On a "
        "breaker refusal, **stop and escalate to the human** — do not work "
        "around it; the loop is bounded out for a reason.\n"
        "- **`defer`** — ...\n"
        "- **`pass`** — proceed to close.\n"
    )


def _pre_fix_handoff() -> str:
    return (
        "#### Proactive context-rollover handoff\n\n"
        "1. **`harness checkpoint --run-id <run_id>`** — push the WIP branch.\n"
        "2. **Post a handoff comment** ...\n"
        "3. **A fresh session continues the same ticket** with "
        "`harness start <TICKET> --resume`.\n"
    )


def test_teeth_step3_recovery_check_fails_on_pre_fix_text() -> None:
    pre = _pre_fix_step3()
    assert "harness cancel" not in pre, "fixture must not already contain the fix"
    with pytest.raises(AssertionError):
        for needle in ("harness cancel", "harness checkpoint", "--resume", "run_id", "started_at"):
            assert needle in pre


def test_teeth_handoff_cross_reference_fails_on_pre_fix_text() -> None:
    pre = _pre_fix_handoff()
    with pytest.raises(AssertionError):
        assert "harness cancel" in pre
