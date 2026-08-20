"""#494 — `/build` keeps final gate evidence adjacent to the push it licenses."""

from __future__ import annotations

import re

from tests._gitutil import indexed_text

_EXPECTED = (
    "in_review",
    "substantive_review",
    "reconcile",
    "delta_review",
    "full_gate",
    "pass",
    "tree_compare",
    "push",
    "tracker_done",
)


def _lifecycle() -> list[tuple[str, str]]:
    text = indexed_text("commands/build.md")
    begin = "<!-- harness:build-lifecycle:begin -->"
    end = "<!-- harness:build-lifecycle:end -->"
    assert text.count(begin) == 1 and text.count(end) == 1
    block = text.split(begin, 1)[1].split(end, 1)[0]
    entries = re.findall(
        r"^- stage: (?P<stage>[a-z_]+)\n  authority: (?P<authority>[a-z_]+)$",
        block,
        re.MULTILINE,
    )
    assert entries, "the structured lifecycle is empty"
    return entries


def test_review_reconciliation_and_final_binding_have_one_order() -> None:
    """The review-wide race is closed by putting reconciliation next to binding."""
    assert tuple(stage for stage, _authority in _lifecycle()) == _EXPECTED


def test_no_tracker_operation_interrupts_pass_tree_compare_and_push() -> None:
    """A post-PASS status write cannot spend the narrow push window."""
    lifecycle = _lifecycle()
    start = _EXPECTED.index("pass")
    finish = _EXPECTED.index("push") + 1

    assert all(authority != "tracker" for _stage, authority in lifecycle[start:finish])
    assert lifecycle[_EXPECTED.index("in_review")][1] == "tracker"
    assert lifecycle[_EXPECTED.index("tracker_done")][1] == "tracker"
