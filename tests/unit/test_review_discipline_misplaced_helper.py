"""CAL-823 — ``review-discipline`` catches a misplaced pure helper at reuse.

Surfaced as a Medium carry-forward by the ``harness review`` of CAL-800. CAL-796
added a **"Misplaced pure helper"** structural check to ``review-discipline``
Stage 2: in a repo whose CONTEXT designates a home for testable client logic
(e.g. a ``lib/`` under a coverage ratchet), a *pure* function declared inline in
a view/screen that a **second** view also needs belongs in that home before
approval, not copied screen-to-screen — a class that hides per-change because
each ticket touches one screen, so it is caught at the moment of reuse.

Unlike its sibling Stage-2 structural classes, that rule shipped with no content
guard. Every other concrete structural class has a text-parse guard pinning it
into the skill — ``test_review_discipline_port_orphan`` (CAL-665),
``test_over_engineering_lens`` (CAL-711),
``test_mirrors_admission_third_strike`` (CAL-800) — so a future re-edit cannot
silently drop the rule. Only **Misplaced pure helper** lacked one. This is that
guard, in the style of ``test_review_discipline_port_orphan``: it reads the
as-built guidance and asserts the rule is present, in the right place.

Acceptance criteria (this ticket):

* **AC-1** — ``review-discipline`` carries a rule that a *pure* helper declared
  inline in a screen, that a *second* screen also needs, belongs in the
  CONTEXT-designated home (e.g. ``lib/``) before approval — caught at the moment
  of reuse, not copied screen-to-screen. Proven by
  :func:`test_review_discipline_has_misplaced_helper_rule`.
* **AC-2** — the rule lives in the Stage 2 quality checks, beside its sibling
  structural rules, not buried elsewhere. Proven by
  :func:`test_misplaced_helper_rule_is_in_stage_two`.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "review-discipline" / "references" / "diff-shape-checks.md"


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _stage_two(text: str) -> str:
    """review-discipline's Stage 2 quality body (where structural checks live).

    Slice between the ``### Stage 2`` heading and the ``## Severity`` section so
    the assertions see only the quality rules, not the neighbouring sections.
    """
    start = text.index("### Stage 2")
    end = text.index("## Severity", start)
    return text[start:end]


def _misplaced_helper_bullet(text: str) -> str:
    """The Stage 2 bullet for the Misplaced-pure-helper rule.

    The rule is its own ``- **Misplaced pure helper**`` bullet alongside the
    other concrete structural checks (Dead-surface / Port-time-orphan /
    Mirrors-admission); find that bullet and slice to the next top-level bullet
    or heading so the assertions see only this rule.
    """
    stage_two = _stage_two(text)
    m = re.search(r"^- \*\*Misplaced pure helper\*\*", stage_two, re.MULTILINE)
    assert m, (
        "review-discipline Stage 2 has no bullet naming the Misplaced-pure-helper "
        "rule (CAL-796 / CAL-823 AC-1)."
    )
    rest = stage_two[m.start() :]
    nxt = re.search(r"^(?:- \*\*|#{2,3} )", rest[1:], re.MULTILINE)
    return rest[: nxt.start() + 1] if nxt else rest


def test_review_discipline_has_misplaced_helper_rule() -> None:
    """The skill states the misplaced-pure-helper rule (AC-1)."""
    bullet = _misplaced_helper_bullet(_skill_text()).lower()
    # It is about a *pure* function declared *inline* in a view/screen file...
    assert "pure" in bullet and "inline" in bullet and "screen" in bullet, (
        "the rule must name a *pure* helper declared *inline* in a screen/view"
    )
    # ...that a *second* view also needs (the reuse signal, not the first use)...
    assert "second" in bullet, (
        "the rule must trigger when a *second* view/screen needs the helper, "
        "not on its first declaration"
    )
    # ...belongs in the CONTEXT-designated home (e.g. ``lib/``) *before approval*...
    assert "lib/" in bullet, (
        "the rule must send the helper to the CONTEXT-designated home (e.g. lib/)"
    )
    assert "before approval" in bullet, (
        "the helper belongs in its home *before approval*, not copied screen-to-screen"
    )
    # ...and is caught at the moment of reuse, not copied screen-to-screen.
    assert "moment of reuse" in bullet, (
        "the rule must be caught at the *moment of reuse* (the class hides "
        "per-change because each ticket touches one screen)"
    )
    assert "screen-to-screen" in bullet, (
        "the rule must reject copying the helper *screen-to-screen*"
    )


def test_misplaced_helper_rule_is_in_stage_two() -> None:
    """The rule sits in Stage 2 quality, beside the sibling structural rules (AC-2)."""
    text = _skill_text()
    stage_two_start = text.find("### Stage 2")
    assert stage_two_start != -1, "review-discipline must have a Stage 2 section"
    severity_start = text.find("## Severity")
    assert severity_start != -1, "review-discipline must have a Severity section"
    stage_two = text[stage_two_start:severity_start]
    assert "**Misplaced pure helper**" in stage_two, (
        "the misplaced-pure-helper rule must live in the Stage 2 quality checks, "
        "alongside the other structural rules (Dead-surface / Port-time-orphan / "
        "Mirrors-admission), not buried elsewhere"
    )
