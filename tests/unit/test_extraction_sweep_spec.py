"""CAL-1172 — an extraction must sweep for its copies.

*Source:* nano-erp steward insight **CODE-INSIGHT-3** (second ``/assess code``
pass of 2026-07-17), evidence finding CODE-4. A prior fix (nano-erp ERP-85) swept
exactly the four locations a finding named and no wider, so a fifth copy — the
only one whose body had diverged — was invisible to both the steward and the
fixer. The class of defect is "an extraction whose green diff certifies a
unification that did not actually happen, because a divergent copy survived
outside the finding's location list."

``code-quality`` Part A already carries the mirror-image rule for a *removal*
(*A removal sweeps for its dependents*); this guard pins the presence of the
matching rule for an *extraction*: grep the whole tree, and a copy whose body
differs is the finding, not the leftover.

This guard evidences the *rule*, not that a sweep was performed on any change —
the same honest limit the removal-sweep guard states.

Acceptance criteria (CAL-1172):

* **AC-1** — the ``code-quality`` skill carries the extraction-sweep rule.
  :func:`test_code_quality_has_extraction_sweep_rule`,
  :func:`test_extraction_sweep_flags_divergent_copy`.
* **AC-1 (placement)** — the rule lives in the Part A — Scope discipline.
  :func:`test_extraction_sweep_in_scope_section`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
CODE_QUALITY = REPO_ROOT / "skills" / "code-quality" / "SKILL.md"


def _code_quality_text() -> str:
    return CODE_QUALITY.read_text()


def test_code_quality_has_extraction_sweep_rule() -> None:
    """AC-1: the skill states the core rule — an extraction is not complete until
    you grep the whole tree for the extracted pattern, and a finding's location
    list is a starting point, not the boundary."""
    low = _code_quality_text().lower()
    assert "extraction is not complete" in low, (
        "code-quality must state that an 'extraction is not complete' until the "
        "whole tree has been swept for copies (CAL-1172 AC-1)."
    )
    assert "grep the whole tree" in low, (
        "the rule must say to grep the whole tree for the extracted pattern, not "
        "just the named locations (CAL-1172 AC-1)."
    )
    assert "starting point, not the boundary" in low, (
        "the rule must state that a finding's location list is a starting point, "
        "not the sweep boundary (CAL-1172 AC-1)."
    )


def test_extraction_sweep_flags_divergent_copy() -> None:
    """AC-1: the load-bearing sentence — diff every copy against the canonical
    body before deleting it, because a copy whose body *differs* is the finding,
    not the leftover; a surviving divergent copy makes the green diff certify a
    unification that did not happen."""
    low = _code_quality_text().lower()
    assert "is the finding, not the leftover" in low, (
        "the rule must say a copy whose body differs is the finding, not the "
        "leftover — the sentence that turns the divergent copy from something a "
        "sweep deletes into something a sweep reports (CAL-1172 AC-1)."
    )
    assert "certifies a unification that did not happen" in low, (
        "the rule must warn that a surviving divergent copy makes the "
        "extraction's green diff certify a unification that did not happen "
        "(CAL-1172 AC-1)."
    )


def test_extraction_sweep_in_scope_section() -> None:
    """AC-1 (placement): the rule sits inside 'Part A — Scope' — an extraction's
    completeness is a scope-discipline concern — not an unrelated part of the
    skill."""
    text = _code_quality_text()
    m = re.search(r"^##\s+Part A\b.*Scope", text, re.MULTILINE)
    assert m, "code-quality must have a 'Part A — Scope' section."
    rest = text[m.end():]
    nxt = re.search(r"^##\s+Part B\b", rest, re.MULTILINE)
    section = rest[: nxt.start()] if nxt else rest
    assert "extraction is not complete" in section.lower(), (
        "the extraction-sweep rule must live in the 'Part A — Scope' discipline "
        "(CAL-1172 AC-1 placement)."
    )
