"""#198 — the CONTEXT.md currency bullet also covers RELEASING.md.

A repo-wide config change (a tracker cutover, a branch-topology amendment) can
update ``CONTEXT.md`` correctly while leaving the sibling process doc
``RELEASING.md`` silently describing the old world — the same "grep every
documenting surface" gap tick #87's ledger already named for the hold-kind
taxonomy change. ``RELEASING.md`` went stale at exactly two such trigger
points (the Linear→GitHub cutover and the dev→staging→main promotion
topology) and neither was caught, because the existing "CONTEXT.md currency"
bullet (`test_review_discipline_context_currency.py`) scopes only to
``CONTEXT.md`` itself, not its dependent docs (assessment
``assessments/2026-07-23-code.md``, insight CODE-INSIGHT-2, evidence: finding
CODE-2 / #196).

Acceptance criteria (this ticket):

* **AC-1** — the CONTEXT.md currency bullet additionally names a trigger: a
  diff that changes CONTEXT.md's ``tracker:`` field or ``branches:`` roles
  obliges the reviewer to confirm ``RELEASING.md``'s release checklist names
  the current tracker and promotion path. Proven by
  :func:`test_bullet_covers_releasing_on_tracker_or_branch_change`.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "review-discipline" / "SKILL.md"


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _stage_two(text: str) -> str:
    start = text.index("### Stage 2")
    end = text.index("## Severity", start)
    return text[start:end]


def _context_currency_bullet(text: str) -> str:
    stage_two = _stage_two(text)
    m = re.search(r"^- \*\*CONTEXT\.md currency\*\*", stage_two, re.MULTILINE)
    assert m, (
        "review-discipline Stage 2 has no bullet naming the CONTEXT.md "
        "currency trigger (#184)"
    )
    rest = stage_two[m.start() :]
    nxt = re.search(r"^(?:- \*\*|#{2,3} )", rest[1:], re.MULTILINE)
    return rest[: nxt.start() + 1] if nxt else rest


def test_bullet_covers_releasing_on_tracker_or_branch_change() -> None:
    """The bullet names RELEASING.md as a dependent doc to re-check (#198, AC-1)."""
    bullet = _context_currency_bullet(_skill_text())
    lowered = bullet.lower()
    assert "releasing.md" in lowered, (
        "the CONTEXT.md currency bullet must also name RELEASING.md as a "
        "sibling doc that can go stale on a tracker/branch-role change (#198)"
    )
    assert "`tracker:`" in bullet, (
        "the bullet must name CONTEXT.md's `tracker:` field as a trigger for "
        "checking RELEASING.md"
    )
    assert "`branches:`" in bullet, (
        "the bullet must name CONTEXT.md's `branches:` roles as a trigger for "
        "checking RELEASING.md"
    )
    assert "release checklist" in lowered, (
        "the bullet must point at RELEASING.md's release checklist "
        "specifically, not the file in the abstract"
    )
