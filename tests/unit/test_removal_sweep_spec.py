"""CAL-974 — a removal must sweep for its dependents.

*Source:* ``assessments/2026-07-03-full-review.md`` (CODE-INSIGHT-2, Medium —
systemic insight). One review pass surfaced several dead contracts left keyed to
removed things: an unreachable 409 guarding a constraint dropped in a migration,
a coverage floor no gate measured, ``tools/`` references three files deep, and a
prior pass's orphaned library helpers. The class of defect is "a removal that
leaves its dependents behind."

The fix is a scope-discipline rule in ``code-quality``: a removal is not complete
until you grep for the removed name and delete or update every dependent — the
diff of a removal should include its dependents.

This guard pins the *presence* of that rule in the surface (the same honest limit
the lifecycle-sweep and grounding guards state — it evidences the rule, not that
a sweep was performed on any change).

Acceptance criteria (CAL-974):

* **AC-1** — the upstream skill carries the exact rule wording.
  :func:`test_code_quality_has_removal_sweep_rule`,
  :func:`test_removal_sweep_names_dependent_kinds`.
* **AC-1 (placement)** — the rule lives in the Part A — Scope discipline, not
  some unrelated section. :func:`test_removal_sweep_in_scope_section`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
CODE_QUALITY = REPO_ROOT / "skills" / "code-quality" / "SKILL.md"


def _code_quality_text() -> str:
    return CODE_QUALITY.read_text()


def test_code_quality_has_removal_sweep_rule() -> None:
    """AC-1: the skill states the core rule — a removal is not complete until you
    grep for the removed name, and the diff of a removal includes its
    dependents."""
    low = _code_quality_text().lower()
    assert "removal is not complete" in low, (
        "code-quality must state that a 'removal is not complete' until its "
        "dependents are swept (CAL-974 AC-1)."
    )
    assert "grep for the removed name" in low, (
        "the rule must say to grep for the removed name (CAL-974 AC-1)."
    )
    assert "dependent" in low, (
        "the rule must require deleting or updating every dependent (CAL-974 AC-1)."
    )


def test_removal_sweep_names_dependent_kinds() -> None:
    """AC-1: the rule names the concrete dependent kinds the class covers —
    constraint names in exception handlers, feature names in config / testpaths /
    docs — so the sweep is actionable, not abstract."""
    low = _code_quality_text().lower()
    kinds = ("exception handler", "config", "doc")
    missing = [k for k in kinds if k not in low]
    assert not missing, (
        "the removal-sweep rule must name the concrete dependent kinds "
        f"(constraint names in exception handlers, feature names in "
        f"config/testpaths/docs); missing {missing} (CAL-974 AC-1)."
    )


def test_removal_sweep_in_scope_section() -> None:
    """AC-1 (placement): the rule sits inside 'Part A — Scope' — a removal's
    completeness is a scope-discipline concern — not an unrelated part of the
    skill."""
    text = _code_quality_text()
    m = re.search(r"^##\s+Part A\b.*Scope", text, re.MULTILINE)
    assert m, "code-quality must have a 'Part A — Scope' section."
    rest = text[m.end():]
    nxt = re.search(r"^##\s+Part B\b", rest, re.MULTILINE)
    section = rest[: nxt.start()] if nxt else rest
    assert "removal is not complete" in section.lower(), (
        "the removal-sweep rule must live in the 'Part A — Scope' discipline "
        "(CAL-974 AC-1 placement)."
    )
