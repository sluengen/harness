"""#184 — ``review-discipline`` catches a `CONTEXT.md` gone stale in this diff.

``CONTEXT.md`` is the first file every agent reads, so a stale entry there
mis-primes every later session — and the class is recurring, not incidental. In
nano-erp it carried three stale frontend claims (no test runner, backend-only, a
gate step omitting tests), each gone stale at an identifiable commit, none of
which pointed a reviewer at ``CONTEXT.md``; a "D1–D12" line survived three
assessment passes against a live D17. No per-change reviewer catches it because
no future change re-touches the gap (nano-erp assessment
``assessments/2026-07-22-code.md``, systemic insight CODE-INSIGHT-3 /
nano-erp ERP-152).

The fix is a *narrow, mechanically checkable* trigger — not "review CONTEXT.md
every time": the diff adding or removing a test runner, a gate step, a
workspace, or a top-level path is the moment the file can go stale, and that is
when the reviewer looks. This guard binds the rule into the skill so a future
re-edit cannot silently drop it, in the style of the sibling Stage-2 content
guards (``test_review_discipline_type_predicate_coverage``,
``test_review_discipline_port_orphan``).

Acceptance criteria (this ticket):

* **AC-1** — ``review-discipline`` carries a trigger naming the four diff
  conditions (test runner, gate step, workspace, top-level path) that oblige a
  reviewer to confirm ``CONTEXT.md`` names them correctly. Proven by
  :func:`test_context_currency_rule_names_its_triggers`.
* **AC-2** — the rule names the ``CONTEXT.md`` blocks to check (``stack`` /
  ``commands`` / ``layers``) and grades a stale entry **Medium**, with the
  first-file-read rationale. Proven by
  :func:`test_context_currency_rule_grades_and_justifies`.
* **AC-3** — the rule lives in the Stage 2 quality checks, beside the other
  concrete structural checks, not buried elsewhere. Proven by
  :func:`test_context_currency_rule_is_in_stage_two`.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "review-discipline" / "references" / "diff-shape-checks.md"

_BULLET_TITLE = "**CONTEXT.md currency**"


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _stage_two(text: str) -> str:
    start = text.index("### Stage 2")
    end = text.index("## Severity", start)
    return text[start:end]


def _context_currency_bullet(text: str) -> str:
    stage_two = _stage_two(text)
    m = re.search(
        r"^- \*\*CONTEXT\.md currency\*\*", stage_two, re.MULTILINE
    )
    assert m, (
        "review-discipline Stage 2 has no bullet naming the CONTEXT.md "
        "currency trigger (#184)"
    )
    rest = stage_two[m.start() :]
    nxt = re.search(r"^(?:- \*\*|#{2,3} )", rest[1:], re.MULTILINE)
    return rest[: nxt.start() + 1] if nxt else rest


def test_context_currency_rule_names_its_triggers() -> None:
    """The trigger is the four narrow diff conditions, not "every time" (AC-1)."""
    bullet = _context_currency_bullet(_skill_text()).lower()
    for condition in ("test runner", "gate step", "workspace", "top-level path"):
        assert condition in bullet, (
            f"the trigger must name {condition!r} as a diff condition that "
            "obliges a CONTEXT.md check"
        )
    # It fires on the diff *changing* one of those, in either direction — a
    # removal leaves CONTEXT.md as stale as an addition does.
    assert "adds or removes" in bullet, (
        "the trigger must fire on a diff that adds *or removes* one of the "
        "named conditions, not additions only"
    )


def test_context_currency_rule_grades_and_justifies() -> None:
    """It says which blocks to check, the severity, and why (AC-2)."""
    bullet = _context_currency_bullet(_skill_text())
    lowered = bullet.lower()
    for block in ("stack", "commands", "layers"):
        assert f"`{block}`" in bullet, (
            f"the rule must name CONTEXT.md's `{block}` block as what to confirm"
        )
    assert "medium" in lowered, (
        "the rule must grade a stale CONTEXT.md entry as a Medium finding"
    )
    # The rationale is what makes the severity non-arbitrary: CONTEXT.md is the
    # first file the next agent reads, so staleness mis-primes every session.
    assert "first file" in lowered, (
        "the rule must justify the severity — CONTEXT.md is the first file the "
        "next agent reads"
    )


def test_context_currency_rule_is_in_stage_two() -> None:
    """The rule sits in Stage 2 quality, in the `For code:` checks (AC-3)."""
    text = _skill_text()
    stage_two_start = text.find("### Stage 2")
    assert stage_two_start != -1, "review-discipline must have a Stage 2 section"
    severity_start = text.find("## Severity")
    assert severity_start != -1, "review-discipline must have a Severity section"
    stage_two = text[stage_two_start:severity_start]
    assert _BULLET_TITLE in stage_two, (
        "the CONTEXT.md currency rule must live in the Stage 2 quality checks, "
        "alongside the other structural/correctness rules"
    )
