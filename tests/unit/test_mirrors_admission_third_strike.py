"""CAL-800 — a "mirrors/duplicates/keep-in-sync" comment is the third strike.

From ``/assess code`` 2026-06-19 (report ``assessments/2026-06-19-code-2.md``),
insight CODE-INSIGHT-2, accepted 2026-06-19 by sluengen. Small pure helpers are
being *copied* with a comment admitting the copy — "mirrors X", "duplicates Y",
"keep in sync with Z" — and the existing rule-of-three misses them because each
copy is individually tiny. The fix makes the admission comment itself the
trigger: the comment is the explicit duplication signal the size threshold
cannot see.

These are text-parse content guards in the style of
``test_review_discipline_port_orphan`` (CAL-665) and ``test_over_engineering_lens``
(CAL-711): they read the as-built guidance and assert the rule is present, so a
later re-edit cannot silently drop it.

Acceptance criteria (this ticket):

* **AC-1** — ``code-quality`` tells builders a ``mirrors`` / ``duplicates`` /
  ``keep in sync`` comment is an explicit duplication admission that counts as
  the third strike and requires extraction *now*, regardless of helper size.
  Proven by :func:`test_code_quality_treats_admission_comment_as_third_strike`
  and :func:`test_admission_rule_lives_in_extract_section`.
* **AC-2** — ``review-discipline`` tells reviewers that an unextracted helper
  carrying that admission comment is a **Medium** structural finding, the same
  tier as the same logic in 3+ places. Proven by
  :func:`test_review_discipline_reports_admission_helper_as_medium` and
  :func:`test_admission_finding_is_in_stage_two`.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CODE_QUALITY = _REPO_ROOT / "skills" / "code-quality" / "SKILL.md"
_REVIEW_DISCIPLINE = _REPO_ROOT / "skills" / "review-discipline" / "SKILL.md"

#: The three admission phrases the comment can carry, as the lower-cased stems
#: the assertions match against. "in sync" is the stem of the keep/kept-in-sync
#: admission, so it matches both inflections ("keep in sync" / "kept in sync").
_ADMISSIONS = ("mirrors", "duplicates", "in sync")


def _extract_section(text: str) -> str:
    """The 'Extract on the third strike' subsection of code-quality Part B.

    Slice from that ``###`` heading to the next ``###``/``##`` heading so the
    assertions see only the rule, not the neighbouring Structure subsections.
    """
    m = re.search(r"^### Extract on the third strike\s*$", text, re.MULTILINE)
    assert m, "code-quality must have an '### Extract on the third strike' section"
    rest = text[m.end() :]
    end = re.search(r"^#{2,3} ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def _stage_two(text: str) -> str:
    """review-discipline's Stage 2 quality body (where structural checks live)."""
    start = text.index("### Stage 2")
    end = text.index("## Severity", start)
    return text[start:end]


def _admission_bullet(text: str) -> str:
    """The Stage 2 bullet for the admission-comment rule.

    The rule is its own ``- **…**`` bullet alongside the other concrete
    structural checks (Dead-surface / Port-time-orphan / Misplaced-pure-helper);
    find the bullet whose header names the mirror/duplicate admission and slice
    to the next top-level bullet or heading.
    """
    stage_two = _stage_two(text)
    m = re.search(r"^- \*\*[^\n]*irror[^\n]*$", stage_two, re.MULTILINE)
    assert m, (
        "review-discipline Stage 2 has no bullet naming the mirror/duplicate "
        "admission-comment rule (CAL-800 AC-2)."
    )
    rest = stage_two[m.start() :]
    nxt = re.search(r"^(?:- \*\*|#{2,3} )", rest[1:], re.MULTILINE)
    return rest[: nxt.start() + 1] if nxt else rest


# --- AC-1: code-quality makes the admission comment the third strike ----------


def test_code_quality_treats_admission_comment_as_third_strike() -> None:
    """code-quality names all three admission phrases as a third-strike trigger."""
    section = _extract_section(_CODE_QUALITY.read_text()).lower()
    missing = [a for a in _ADMISSIONS if a not in section]
    assert not missing, (
        "the 'Extract on the third strike' section must name the admission "
        f"phrases that count as the third strike; missing: {missing} (AC-1)."
    )
    assert "admission" in section, (
        "code-quality must frame a mirrors/duplicates/keep-in-sync comment as an "
        "explicit *admission* of duplication (CAL-800 AC-1)."
    )


def test_admission_rule_requires_extraction_now_regardless_of_size() -> None:
    """The rule says extract *now* and that helper size is irrelevant (AC-1)."""
    section = _extract_section(_CODE_QUALITY.read_text()).lower()
    assert "extract" in section and "now" in section, (
        "the admission rule must require extracting the helper *now* (AC-1)."
    )
    # The whole point: the size threshold the rule-of-three uses cannot see this,
    # so the admission overrides size ("regardless of how small each copy is").
    assert "regardless" in section and ("size" in section or "small" in section), (
        "the admission rule must state that helper size is irrelevant — the "
        "admission, not the size, is the trigger (CAL-800 AC-1)."
    )


def test_admission_rule_lives_in_extract_section() -> None:
    """The rule sits in the third-strike extraction section, not buried elsewhere."""
    section = _extract_section(_CODE_QUALITY.read_text()).lower()
    # The section is the rule-of-three home; the admission rule extends it there.
    assert "third strike" in _CODE_QUALITY.read_text().lower()
    assert any(a in section for a in _ADMISSIONS), (
        "the admission rule must live inside 'Extract on the third strike', "
        "beside the rule-of-three it extends (CAL-800 AC-1)."
    )


# --- AC-2: review-discipline reports the unextracted helper as Medium ---------


def test_review_discipline_reports_admission_helper_as_medium() -> None:
    """The Stage 2 admission bullet names a Medium structural finding (AC-2)."""
    bullet = _admission_bullet(_REVIEW_DISCIPLINE.read_text())
    low = bullet.lower()
    assert any(a in low for a in _ADMISSIONS), (
        "the admission bullet must name the mirrors/duplicates/keep-in-sync "
        f"comment; got: {bullet!r} (AC-2)."
    )
    assert "medium" in low, (
        "an unextracted helper carrying the admission comment must be reported "
        f"as a *Medium* structural finding; got: {bullet!r} (AC-2)."
    )
    # Same tier as the rule-of-three the code-quality rule extends.
    assert "3+" in bullet or "three" in low, (
        "the bullet must place the finding at the same tier as the same logic in "
        f"3+ places; got: {bullet!r} (AC-2)."
    )


def test_admission_finding_is_in_stage_two() -> None:
    """The admission rule lives in Stage 2, beside the other structural checks."""
    stage_two = _stage_two(_REVIEW_DISCIPLINE.read_text()).lower()
    assert any(a in stage_two for a in _ADMISSIONS), (
        "the admission-comment finding must live in the Stage 2 quality checks, "
        "alongside the existing structural checks (CAL-800 AC-2)."
    )
