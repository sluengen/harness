"""#181 — ``review-discipline`` catches a type predicate that validates a subset.

TypeScript takes ``value is T`` on faith — it cannot check a user-defined type
predicate against the type it asserts. In the nano-erp assessment,
``isMeResponse`` validated four of six required fields and nothing (compiler,
reviewer, tests) caught it; it was the highest-severity finding in the pass and
survived two prior reviews (nano-erp ERP-107, ERP-121). The failure mode is
entirely mechanical — enumerate the asserted type's required fields and check
the guard covers each one — and belongs in the review checklist so it is
caught the next time, not just this once (nano-erp assessment
``assessments/2026-07-22-code.md``, systemic insight CODE-INSIGHT-2 /
nano-erp ERP-138).

This guard binds the new rule into the skill so a future re-edit cannot
silently drop it, in the style of the sibling Stage-2 content guards
(``test_review_discipline_port_orphan``, ``test_review_discipline_misplaced_helper``).

Acceptance criteria (this ticket):

* **AC-1** — ``review-discipline`` carries a rule that every user-defined type
  predicate (``value is T``) must be checked against *T*'s required fields,
  and a predicate validating only a subset is a defect, not a nit. Proven by
  :func:`test_review_discipline_has_type_predicate_rule`.
* **AC-2** — the rule lives in the Stage 2 quality checks (``For code:``),
  beside the other concrete structural/correctness checks, not buried
  elsewhere. Proven by :func:`test_type_predicate_rule_is_in_stage_two`.
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
    start = text.index("### Stage 2")
    end = text.index("## Severity", start)
    return text[start:end]


def _type_predicate_bullet(text: str) -> str:
    stage_two = _stage_two(text)
    m = re.search(r"^- \*\*Type predicate coverage\*\*", stage_two, re.MULTILINE)
    assert m, (
        "review-discipline Stage 2 has no bullet naming the type-predicate "
        "coverage rule (#181)"
    )
    rest = stage_two[m.start() :]
    nxt = re.search(r"^(?:- \*\*|#{2,3} )", rest[1:], re.MULTILINE)
    return rest[: nxt.start() + 1] if nxt else rest


def test_review_discipline_has_type_predicate_rule() -> None:
    """The skill states the type-predicate coverage rule (AC-1)."""
    bullet = _type_predicate_bullet(_skill_text()).lower()
    # It is about a *user-defined type predicate* (`value is T`)...
    assert "type predicate" in bullet, (
        "the rule must name a user-defined type predicate"
    )
    assert "value is t" in bullet, (
        "the rule must cite the `value is T` predicate syntax"
    )
    # ...enumerated against T's *required fields*...
    assert "required fields" in bullet, (
        "the rule must require enumerating the asserted type's required fields"
    )
    # ...and a subset-validating predicate is a false assurance / defect.
    assert "subset" in bullet, (
        "the rule must flag a predicate that validates only a subset"
    )
    assert "false assurance" in bullet, (
        "the rule must name the failure as a false assurance at the boundary"
    )
    assert "defect" in bullet and "nit" in bullet, (
        "the rule must state this is a defect, not a nit"
    )


def test_type_predicate_rule_is_in_stage_two() -> None:
    """The rule sits in Stage 2 quality, in the `For code:` checks (AC-2)."""
    text = _skill_text()
    stage_two_start = text.find("### Stage 2")
    assert stage_two_start != -1, "review-discipline must have a Stage 2 section"
    severity_start = text.find("## Severity")
    assert severity_start != -1, "review-discipline must have a Severity section"
    stage_two = text[stage_two_start:severity_start]
    assert "**Type predicate coverage**" in stage_two, (
        "the type-predicate coverage rule must live in the Stage 2 quality "
        "checks, alongside the other structural/correctness rules"
    )
