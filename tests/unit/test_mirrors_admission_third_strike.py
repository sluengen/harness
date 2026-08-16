"""CAL-800 / #206 — a "mirrors/duplicates/keep-in-sync" comment is the third strike.

From ``/assess code`` 2026-06-19 (report ``assessments/2026-06-19-code-2.md``),
insight CODE-INSIGHT-2, accepted 2026-06-19 by sluengen. Small units are being
*copied* with a comment admitting the copy — "mirrors X", "duplicates Y", "keep
in sync with Z" — and the rule-of-three misses them because each copy is
individually tiny. The fix makes the admission comment itself the trigger. #206
(form repo ``/assess code`` 2026-07-24, CODE-INSIGHT-1; originating CAL-1214)
then broadened the trigger's subject past "a helper", because three UI
components each carried a comment admitting they mirrored the previous one and
the rule as worded did not visibly apply to a component.

**Converted under #459** (ADR 0016, and ``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*). Five functions of
unanchored term co-occurrence across two rule-homes became **two tripwires, one
per home**. Half of ``test_mirroring_trigger_broadened.py`` moved here in the
same pass: #206's subject-breadth claim is now the ``component`` and ``module``
entries in the term set below, because that module read this same paragraph and
one rule-home takes one tripwire. Moving the claim rather than dropping it is
what keeps it measured (``craft.md`` → *A deletion pass that moves a definition
must move its killer*); the mutation table carries the entry that proves the
killer arrived. That module survives holding #206's other half — the
coverage-parity claim — and **imports** this module's paragraph slicer, so the
two tripwires cannot fork a window between them.

**What this module now asserts.**

* **Tripwire 1 — the builder's home.** The admission paragraph inside ``###
  Extract on the third strike``, sliced from inside ``## Part B — Structure``.
  The window is the *paragraph*, not the section: the rule-of-three paragraph
  beside it already contains ``component`` ("shared UI in a component"), so a
  section-scoped breadth assertion would stay green with #206's broadening
  deleted — the over-wide unit ``craft.md`` → *The text unit is part of the
  predicate* names.
* **Tripwire 2 — the reviewer's home.** The diff-shape-checks Stage 2 bullet
  naming the admission comment, sliced to the bullet. Terms: the finding's tier
  and the rule-of-three tier it is pegged to. **This one has no polarity** — the
  bullet states an equivalence between two tiers, and an equivalence has no
  direction to invert. Faking one with a bare ``not`` over the bullet would be
  decoration, so none is asserted.

**Term sets.** Tripwire 1: the three admission spellings (``mirrors``,
``duplicates``, ``in sync``), plus ``component`` and ``module`` — the subjects
#206 added. Tripwire 1's **polarity** is the dismissal of the count-or-size,
bound to the noun it dismisses; without it the inverted rule ("the count still
governs; extract once the copies are large") carries every term and passes.

**What it does not prove.** That the tiers are the right tiers, or that a rewrite
keeping every term while reversing the advice around them says what it used to.
Measured limit: an inversion that re-uses this vocabulary in the opposite
arrangement — "the size is the trigger, not the admission" — is not
distinguishable from the rule by any regex, and is the reviewer's.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit.test_assurance_filing_rubric import _section

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CODE_QUALITY = _REPO_ROOT / "skills" / "code-quality" / "SKILL.md"
_REVIEW_DISCIPLINE = (
    _REPO_ROOT
    / "skills"
    / "review-discipline"
    / "references"
    / "diff-shape-checks.md"
)

_PART_B = "## Part B — Structure"
_HEADING = "### Extract on the third strike"
_STAGE_TWO = "### Stage 2 — Diff-shape checks"

#: The terms the admission trigger cannot be stated without: the three spellings
#: of the comment ("in sync" is the stem shared by keep/kept-in-sync), and the
#: two subjects #206 added beside "helper".
_TERMS = (
    r"\bmirrors\b",
    r"\bduplicates\b",
    r"\bin sync\b",
    r"\bcomponent\b",
    r"\bmodule\b",
)

#: The dismissal **bound to what it dismisses**. The rule's direction is that
#: the admission, not the accumulated count or the size of each copy, is the
#: trigger; a bare ``not`` over the paragraph would be satisfied by any English.
_DISMISSES_THE_COUNT_OR_SIZE = re.compile(
    r"\b(?:no longer|not|never)\b(?:\W+\w+){0,3}?\W+(?:matters?|size|count)\b"
    r"|\bregardless of how small\b",
    re.IGNORECASE,
)

#: The reviewer bullet's two tier terms: the finding's own tier, and the
#: rule-of-three tier it is pegged to.
# ``Medium`` until #455 retired the grade scale for the blocking×size 2×2.
# The assertion is unchanged in kind — it pegs *this* bullet's placement to
# the rule-of-three placement — only the vocabulary the equivalence is
# written in moved.
_BULLET_TERMS = (r"\bnon-blocking\b", r"3\+")


def _third_strike_section() -> str:
    """``### Extract on the third strike``, sliced from inside ``## Part B``.

    ``_section`` is imported rather than re-spelled, and the two calls are
    nested so Part B membership lives in the anchor instead of a second test.
    """
    text = _CODE_QUALITY.read_text(encoding="utf-8")
    return _section(_section(text, _PART_B), _HEADING)


def _admission_paragraph() -> str:
    """The one paragraph in that section stating the admission trigger.

    Selected by content, never by index: an ordinal into the section is
    invalidated by a correct insertion (``craft.md`` → *An ordinal reference
    into an enumeration is invalidated by a correct insertion*), and the section
    has already grown a paragraph once (#231's second-copy rule).
    """
    paragraphs = [
        block.strip()
        for block in _third_strike_section().split("\n\n")
        if block.strip()
    ]
    hits = [p for p in paragraphs if re.search(r"\badmission\b", p, re.IGNORECASE)]
    assert hits, (
        f"no paragraph in {_HEADING!r} states the mirrors/duplicates/kept-in-sync "
        "comment as an explicit *admission* of duplication (CAL-800 AC-1)."
    )
    assert len(hits) == 1, (
        f"{_HEADING!r} states the admission trigger across {len(hits)} paragraphs; "
        "this guard's window can no longer tell which one it is pinning, and a term "
        "in one would satisfy an assertion about the other."
    )
    return hits[0]


def _admission_bullet() -> str:
    """The Stage 2 bullet carrying the admission-comment finding.

    Sliced to the bullet, never the file: the diff-shape reference is a list of
    a dozen checks and any of them can supply a stray term.
    """
    stage_two = _section(_REVIEW_DISCIPLINE.read_text(encoding="utf-8"), _STAGE_TWO)
    m = re.search(r"^- \*\*[^\n]*irror[^\n]*$", stage_two, re.MULTILINE)
    assert m, (
        "review-discipline's Stage 2 diff-shape checks have no bullet naming the "
        "mirror/duplicate admission-comment rule (CAL-800 AC-2)."
    )
    rest = stage_two[m.start() :]
    nxt = re.search(r"^(?:- \*\*|#{2,3} )", rest[1:], re.MULTILINE)
    return rest[: nxt.start() + 1] if nxt else rest


def test_the_builder_home_states_the_admission_trigger() -> None:
    """AC-1: the admission paragraph names its subjects and keeps its polarity."""
    para = _admission_paragraph()

    missing = [t for t in _TERMS if not re.search(t, para, re.IGNORECASE)]
    assert not missing, (
        "the admission paragraph no longer carries the terms the trigger cannot be "
        f"stated without; missing {missing}. A comment saying a helper, component or "
        "module mirrors / duplicates / is kept in sync with a sibling is the third "
        f"strike on its own (CAL-800 AC-1, #206 AC-1). Paragraph read:\n{para}"
    )

    assert _DISMISSES_THE_COUNT_OR_SIZE.search(para), (
        "the trigger has lost its polarity: the paragraph must dismiss the count or "
        "the size of each copy as the thing that decides. Without that negation "
        "bound to what it dismisses, the inverted rule — the count still governs, "
        "extract once the copies are large enough — carries every term above and "
        f"passes (CAL-800 AC-1). Paragraph read:\n{para}"
    )


def test_the_reviewer_home_pegs_the_finding_to_the_rule_of_three_tier() -> None:
    """AC-2: the Stage 2 bullet reports the unextracted copy at the same tier.

    No polarity assertion: the claim is an *equivalence* between this finding's
    tier and the rule-of-three tier, and an equivalence has no direction to
    invert. See the module docstring.
    """
    bullet = _admission_bullet()
    missing = [t for t in _BULLET_TERMS if not re.search(t, bullet)]
    assert not missing, (
        "the Stage 2 admission bullet no longer pegs the finding to the same tier as "
        f"the same logic in 3+ places; missing {missing}. Bullet read:\n{bullet}"
    )
