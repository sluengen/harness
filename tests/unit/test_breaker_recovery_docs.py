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

# The `fail`-verdict bullet, sliced out of the wider Step 3 region because the
# human-authorised recovery recipe *also* lives in Step 3 and legitimately names
# `harness cancel` / `--resume` (#329). Asserting their absence over the whole
# region would flag the very block they belong in.
_FAIL_BULLET_HEADING = "- **`fail`** —"
_FAIL_BULLET_END = "- **`defer`** —"


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


def _fail_bullet_slice(doc: str) -> str:
    return _slice(doc, _FAIL_BULLET_HEADING, _FAIL_BULLET_END)


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


# ---------------------------------------------------------------------------
# #329 — the automated exhaustion recipe, and what it must NOT reach for
# ---------------------------------------------------------------------------
#
# Two recoveries live in this document and they are not interchangeable. The
# automated one, on the `fail` bullet, preserves the work and hands the ticket to
# a human. The human-authorised one, under *Recovering from a breaker trip*,
# cancels the run and resumes it — which opens a fresh budget window and resets
# *both* breakers. If the automated path ever reaches for the second, an
# unattended loop can grant itself unlimited cycles one cancel at a time, which
# is the runaway spend the budget exists to bound. Prose is the only thing
# holding those apart, so it is what this pins.

#: The two commands the automated recipe runs, in the order it must run them.
_EXHAUSTION_RECIPE = ("harness checkpoint", "harness defer")

#: The commands that reset a budget. Legal under the human-authorised heading,
#: never on the automated path.
_BUDGET_RESETTING = ("harness cancel", "--resume")


def test_fail_bullet_slice_is_non_empty() -> None:
    """Floor: the slice exists, so the two rules below are not vacuous.

    A rename of either bullet marker would silently empty the subject and leave
    an unguarded recipe reading as guarded.
    """
    bullet = _fail_bullet_slice(_doc())
    assert len(bullet) > 400, "the `fail` verdict bullet is missing or was renamed"


def test_exhaustion_recipe_checkpoints_before_deferring() -> None:
    """Push the WIP, *then* hand the ticket over — the order is load-bearing.

    Deferring first names a branch that may not be on ``origin`` yet, so the
    human the hold summons can be pointed at work that is only in a container
    about to be torn down.
    """
    bullet = _fail_bullet_slice(_doc())
    positions = []
    for command in _EXHAUSTION_RECIPE:
        assert command in bullet, (
            f"the exhaustion recipe must name `{command}` — it is how an "
            "orchestrator that has run out of cycles preserves the work and puts "
            "the ticket on operator hold (#329)"
        )
        positions.append(bullet.index(command))
    assert positions == sorted(positions), (
        "the exhaustion recipe must order "
        + " before ".join(f"`{c}`" for c in _EXHAUSTION_RECIPE)
    )


def test_the_automated_path_names_no_budget_resetting_command() -> None:
    """The `fail` bullet must not reach for cancel/resume — that is the human's call."""
    bullet = _fail_bullet_slice(_doc())
    found = [command for command in _BUDGET_RESETTING if command in bullet]
    assert not found, (
        "the automated exhaustion path names budget-resetting command(s) "
        f"{found} — cancel + resume opens a new budget window and resets both "
        "breakers, so an unattended loop reaching for it can grant itself "
        "unlimited cycles. They belong under *Recovering from a breaker trip*, "
        "which a human enters deliberately (#329)."
    )


def test_teeth_the_recipe_rules_fail_on_a_pre_329_bullet() -> None:
    """Positive control over both rules, on the wording this ticket replaced.

    The pre-#329 bullet ended at "stop and escalate to the human" and named no
    recipe at all, so the ordering rule must reject it. The second sample is the
    subtler regression the ordering rule alone would miss: a bullet that *does*
    carry a recipe, but the human-authorised one.
    """
    pre_329 = (
        "- **`fail`** — fix the listed `issues`, then re-run `harness review`. "
        "On a breaker refusal, stop and escalate to the human."
    )
    assert not all(command in pre_329 for command in _EXHAUSTION_RECIPE), (
        "the pre-#329 bullet named no exhaustion recipe, so the ordering rule "
        "must not be satisfiable by it"
    )

    wrong_recipe = (
        "- **`fail`** — on exhaustion, `harness checkpoint`, then `harness cancel "
        "<run_id>` and `harness start <TICKET> --resume` to keep going. "
        "harness defer is not needed."
    )
    assert [c for c in _BUDGET_RESETTING if c in wrong_recipe], (
        "the sample must name a budget-resetting command, or it does not "
        "exercise the rule it is the control for"
    )
