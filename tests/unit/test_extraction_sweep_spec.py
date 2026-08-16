"""CAL-1172 — an extraction must sweep for its copies.

*Source:* nano-erp steward insight **CODE-INSIGHT-3** (second ``/assess code``
pass of 2026-07-17), evidence finding CODE-4. A prior fix (nano-erp ERP-85) swept
exactly the four locations a finding named and no wider, so a fifth copy — the
only one whose body had diverged — was invisible to both the steward and the
fixer. The class of defect is "an extraction whose green diff certifies a
unification that did not actually happen, because a divergent copy survived
outside the finding's location list."

**Converted under #459** (ADR 0016, and ``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*). Five exact-sentence
pins — ``"extraction is not complete"``, ``"grep the whole tree"``, ``"starting
point, not the boundary"``, ``"is the finding, not the leftover"``, ``"certifies
a unification that did not happen"`` — plus a placement re-check became the
single tripwire below. Those pins verified bytes, not meaning: any of them broke
on a rewording that preserved the rule, and none could see the rule reversed.

**What this module now asserts.** One tripwire, one rule-home:

* **Anchor** — ``### An extraction sweeps for its copies`` resolves *from inside*
  ``## Part A — Scope``. The nesting carries the placement claim the dropped
  third test re-checked; that test was a strict subset of this slice.
* **Term set** — ``extraction``, ``grep``, ``whole tree``, ``copy``. Drop
  ``whole tree`` and the rule collapses back into "sweep the locations the
  finding named", which is the defect it was written against.
* **Polarity** — the negation bound to what it governs: an extraction *is **not**
  complete* until the sweep runs. A bare ``not`` over the paragraph would be
  decoration (``craft.md`` → *Mutate the rule into its opposite, not only out of
  existence*).

**What it does not prove.** That a sweep was performed on any change — the same
honest limit the removal-sweep guard beside it states — nor that the prose still
says the right thing around these terms. That is the reviewer's.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit.test_assurance_filing_rubric import _section

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CODE_QUALITY = _REPO_ROOT / "skills" / "code-quality" / "SKILL.md"

_PART_A = "## Part A — Scope"
_HEADING = "### An extraction sweeps for its copies"

#: The words the rule cannot be stated without, as whole-word patterns.
_TERMS = (
    r"\bextraction\b",
    r"\bgrep\b",
    r"\bwhole tree\b",
    r"\bcop(?:y|ies)\b",
)

#: The negation **bound to the completeness it denies**. ``not`` on its own is
#: satisfied by any paragraph of English; ``not`` within a couple of words of
#: ``complete`` is the clause that inverts with the rule.
_IS_NOT_COMPLETE = re.compile(
    r"\b(?:not|never)\b(?:\W+\w+){0,2}?\W+complete\b", re.IGNORECASE
)


def _rule() -> str:
    """``### An extraction sweeps for its copies``, sliced from inside Part A.

    ``_section`` is imported rather than re-spelled, and the two calls are
    nested so the placement claim lives in the anchor instead of a second test.
    """
    text = _CODE_QUALITY.read_text(encoding="utf-8")
    return _section(_section(text, _PART_A), _HEADING)


def test_the_extraction_sweep_rule_has_a_home() -> None:
    """One tripwire: the rule is in Part A, names its terms, keeps its polarity."""
    rule = _rule()
    assert rule.strip(), (
        f"{_HEADING!r} is empty — a heading with no rule under it states nothing "
        "(CAL-1172)."
    )

    missing = [t for t in _TERMS if not re.search(t, rule, re.IGNORECASE)]
    assert not missing, (
        f"{_HEADING!r} no longer carries the terms the extraction-sweep rule cannot "
        f"be stated without; missing {missing}. The sweep greps the *whole tree* for "
        "copies of the extracted pattern, not just the locations a finding named "
        f"(CAL-1172). Section read:\n{rule}"
    )

    assert _IS_NOT_COMPLETE.search(rule), (
        "the rule has lost its polarity: an extraction must be stated as *not "
        "complete* until the sweep runs. Without the negation bound to `complete`, "
        "a paragraph describing extraction and grepping in the opposite direction "
        f"carries every term above and passes (CAL-1172). Section read:\n{rule}"
    )
