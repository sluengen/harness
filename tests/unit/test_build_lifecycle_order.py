"""#623 — the lifecycle splits at PASS, and the rebase runs before the review.

**What #494 asserted, and why the subject moved.** This module was born asserting
that ``/build`` kept final gate evidence adjacent to the push it licensed: the
stage order interleaved review and landing — ``reconcile`` sat *between*
``substantive_review`` and ``delta_review``, and the gate ran after it — so the
guard's job was to stop a tracker write from spending the narrow window between
the verdict and the push.

That interleaving existed for one reason: to keep a verdict bound to a tree while
the integration branch moved underneath it. ADR 0022 retired that binding, and
with it the reason. #623 collapses the sequence to a linear one and cuts it at
PASS: ``/build`` ends at a reviewed branch, ``/promote`` takes it from there.

**``delta_review`` is gone, and its absence is the assertion.** It existed only
because reconciling *after* the review admitted bytes no verdict covered.
Rebasing *before* the review means the reviewer reads the branch as it will land,
so there is nothing for a delta review to be about — and the bytes it used to
read were other tickets' work, already reviewed and gated in their own runs.
:func:`test_the_rebase_precedes_the_review` is what would fail if someone
restored the old order; :func:`test_no_landing_stage_survives_in_build` is what
would fail if the split were undone by moving landing back.

**Two blocks, one vocabulary.** Each skill owns the block naming its own stages,
and ``pass`` appears in both — the same meaning (the run holds green
certification over the tree in hand and may proceed) reached by two certifiers,
which is what the ``authority`` field is for. ``skills/build/references/run-state.md``
holds that vocabulary and states the meaning; this module asserts the order and
the authorities, never what a stage means.

**Admitted under ADR 0017 D5 class (e), tree-consistency.** The blocks are
delimited regions of tracked documents, read from the index, and each entry is
matched as an opaque ``stage``/``authority`` pair. Nothing here reads what a
stage *does*.
"""

from __future__ import annotations

import re

from tests._gitutil import indexed_text

_BUILD = (
    ("in_review", "tracker"),
    ("rebase", "git"),
    ("substantive_review", "reviewer"),
    ("pass", "reviewer"),
)

_PROMOTE = (
    ("rebase", "git"),
    ("full_gate", "gate"),
    ("pass", "gate"),
    ("tree_compare", "git"),
    ("push", "git"),
    ("tracker_done", "tracker"),
)

_RETIRED = ("reconcile", "delta_review")


def _lifecycle(path: str, marker: str) -> list[tuple[str, str]]:
    text = indexed_text(path)
    begin = f"<!-- harness:{marker}:begin -->"
    end = f"<!-- harness:{marker}:end -->"
    assert text.count(begin) == 1 and text.count(end) == 1
    block = text.split(begin, 1)[1].split(end, 1)[0]
    entries = re.findall(
        r"^- stage: (?P<stage>[a-z_]+)\n  authority: (?P<authority>[a-z_]+)$",
        block,
        re.MULTILINE,
    )
    assert entries, f"the structured lifecycle in {path} is empty"
    return entries


def _build() -> list[tuple[str, str]]:
    return _lifecycle("skills/build/SKILL.md", "build-lifecycle")


def _promote() -> list[tuple[str, str]]:
    return _lifecycle("skills/promote/SKILL.md", "promote-lifecycle")


def test_build_runs_the_four_stages_that_end_at_a_reviewed_branch() -> None:
    """#623 AC-1 — `/build` ends at PASS and names no landing stage."""
    assert tuple(_build()) == _BUILD


def test_promote_runs_the_six_stages_that_take_a_reviewed_branch_to_landed() -> None:
    """#623 AC-1 — the landing half is `/promote`'s, in this order."""
    assert tuple(_promote()) == _PROMOTE


def test_the_rebase_precedes_the_review() -> None:
    """The point of the change: the reviewer reads the branch as it will land."""
    stages = [stage for stage, _authority in _build()]
    assert stages.index("rebase") < stages.index("substantive_review")


def test_no_retired_stage_survives_in_either_block() -> None:
    """`delta_review` re-reviewed reviewed code; `reconcile` is now `rebase`."""
    for name, entries in (("build", _build()), ("promote", _promote())):
        stages = {stage for stage, _authority in entries}
        assert not stages & set(_RETIRED), (
            f"the {name} lifecycle still names a retired stage: "
            f"{sorted(stages & set(_RETIRED))}"
        )


def test_no_landing_stage_survives_in_build() -> None:
    """The seam at PASS: `/build` neither gates for landing nor pushes."""
    stages = {stage for stage, _authority in _build()}
    assert not stages & {"full_gate", "tree_compare", "push", "tracker_done"}


def test_no_tracker_operation_interrupts_pass_tree_compare_and_push() -> None:
    """A post-PASS status write cannot spend the narrow push window."""
    lifecycle = _promote()
    stages = [stage for stage, _authority in lifecycle]
    start = stages.index("pass")
    finish = stages.index("push") + 1

    assert all(authority != "tracker" for _stage, authority in lifecycle[start:finish])
    assert lifecycle[stages.index("tracker_done")][1] == "tracker"
    assert _build()[0] == ("in_review", "tracker")
