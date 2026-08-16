"""#276 / #459 — a seam extraction must also say where the extracted module's tests went.

#273 extended the Stage-2 **Architecture watchlist** bullet so that a seam
extraction refreshes the ``architecture_watchlist.files`` entry it invalidates.
The adjacent question — *where do the extracted module's tests now live?* — was
asked nowhere: not by that bullet, and not by ``code-quality`` Part B (*Extract
on the third strike*), which governs production structure only and fires at
build time, when the tests may not have moved yet.

So test structure could silently stop following production structure. The repo
demonstrably has the convention — three extractions in one window each got their
own test module — but nothing stated it, so adherence was coincidental, and a
fourth family's four extractions all landed their tests back in a single
2,768-line module. The fix is one clause on the same bullet, bound to the same
*extraction* outcome and folded into the same **non-blocking** finding (the
same bullet, in the vocabulary #455 left behind after the grade scale went).

**What this module asserts, after #459.** One tripwire over one clause-home
(ADR 0016, ``code-quality`` Part C → *A guard over prose owns structure and
negative space, never meaning*), plus the second-placement sweep, which is
negative space and stays:

1. **Anchor** — the ``- **Architecture watchlist**`` bullet, sliced by
   :func:`~tests.unit.test_architecture_watchlist._review_watchlist_bullet`, and
   narrowed again to the *sentences* naming tests. The narrowing is load-bearing:
   the bullet already contains ``module``, ``reason``, ``extraction``,
   ``non-blocking`` and ``diff`` for other reasons, so any bullet-wide key is
   green against the
   pre-clause file and measures nothing — the over-wide unit ``craft.md`` → *The
   text unit is part of the predicate* names.
2. **Term set** — ``test`` selects the clause; ``stay`` is what makes the
   obligation an *answer* rather than a mandate to move.
3. **Polarity** — ``with no reason stated``, the negation anchored to the reason
   it governs. Tests left behind are a finding only when nothing was said, so an
   edit that dropped the negation would turn a recorded decision into a
   violation, or a violation into a shrug, depending which way it fell. And the
   **binding** carries direction independently: every test-bearing sentence must
   name the extraction, so a clause demanding the check on every watchlist touch
   goes red. Mutating a relation means mutating the relation, not the relata.

What went: ``"test" in bullet`` — over a bullet about testing — and the
slicer-boundary control, which was a verbatim duplicate of the one
``test_review_discipline_watchlist_entry_currency`` owns over the same slicer and
the same file. One copy of a control, called by the assertions it protects.
"""

from __future__ import annotations

import re
from pathlib import Path

# Import both helpers from the modules that own them rather than declaring a
# third and fourth private copy. A copy drifts from the prose it slices and
# produces a confident false green — the argument #272 and #273 each recorded.
# The slicer carries its own CAL-815 assertion, so a renamed or deleted bullet
# fires there instead of silently measuring nothing here.
from tests.unit.test_architecture_watchlist import _review_watchlist_bullet
from tests.unit.test_review_discipline_watchlist_entry_currency import _sentences

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "review-discipline" / "references" / "diff-shape-checks.md"

# The placements a finding can carry. `non-blocking` is the one this bullet
# already uses; the other must stay absent, because the clause folds into that
# finding rather than introducing a placement of its own. These were the four
# retired grade names (`critical`/`high`/`medium`/`low`) until #455 replaced the
# scale with the blocking×size 2×2 — the claim is unchanged, and it is now
# written in the vocabulary `review-discipline` actually defines.
_THIS_PLACEMENT = "non-blocking"
_OTHER_PLACEMENTS = ("blocking",)

#: The escape hatch, with the negation **anchored to the reason it governs**.
#: ``reason`` alone is present elsewhere in the bullet (the deferral clause), so
#: only the anchored form measures this clause; and only the negation
#: distinguishes "tests left behind are a finding" from "tests left behind are
#: fine".
_NO_REASON_STATED = re.compile(r"\bno\b(?:\W+\w+){0,2}?\W+reason\b", re.IGNORECASE)


def _bullet() -> str:
    return _review_watchlist_bullet(_SKILL.read_text(encoding="utf-8"))


def test_the_extracted_modules_test_home_is_owed_on_an_extraction() -> None:
    """The bullet obliges an answer about the extracted module's tests, on extraction.

    Three claims on the sentences that mention tests, and the scope is the
    point. A deferral carves nothing out, so no tests were orphaned and there is
    nothing to confirm — which is why the binding to the extraction outcome is
    asserted per sentence rather than as bullet-wide co-presence. The obligation
    is to *answer*: tests may stay when the change says why, and they are a
    finding only when no reason was stated.
    """
    bearing = [s for s in _sentences(_bullet()) if "test" in s.lower()]
    assert bearing, (
        "no sentence in the Architecture watchlist bullet mentions tests — the "
        "obligation this clause adds is missing. Production structure and test "
        "structure part company at the extraction commit and nothing else "
        "looks (#276)"
    )
    for sentence in bearing:
        assert "extract" in sentence.lower(), (
            "the tests obligation must be bound to the seam-extraction outcome "
            "in the sentence that states it, not merely co-present in the "
            "bullet; an unbound clause reads as 'check the tests on every "
            f"watchlist touch' (#276). Offending sentence: {sentence!r}"
        )
    assert any(re.search(r"\bstay", s, re.IGNORECASE) for s in bearing), (
        "the bullet no longer admits the tests staying with a stated reason as "
        "a discharged obligation. The reviewer is confirming a decision was "
        "made, not enforcing one outcome — a clause that only ever mandates the "
        "move is a different, stricter rule (#276)"
    )
    assert any(_NO_REASON_STATED.search(s) for s in bearing), (
        "the bullet no longer says that tests left behind with *no* reason "
        "stated are the finding. Without the negation the clause grades a "
        "recorded decision and a silent omission the same way, in whichever "
        "direction the edit fell (#276, #459)"
    )


def test_the_clause_adds_no_second_placement() -> None:
    """The clause folds into the bullet's existing non-blocking finding (AC-3)."""
    bullet = _bullet().lower()

    assert _THIS_PLACEMENT in bullet, (
        "the Architecture watchlist bullet must keep placing its structural "
        "finding non-blocking — the tests clause folds into it (#276)"
    )
    # `blocking` is a substring of `non-blocking`, so the absence half is read
    # over the bullet with this bullet's own placement removed. Without that
    # removal the assertion is constant-false the moment the bullet states its
    # own placement — the frame mismatch `craft.md` names, reached through an
    # overlapping vocabulary rather than through an empty subject.
    residue = bullet.replace(_THIS_PLACEMENT, "")
    for placement in _OTHER_PLACEMENTS:
        assert not re.search(rf"\b{placement}\b", residue), (
            f"the bullet now places a finding as {placement!r}. The tests clause "
            "reuses the bullet's existing placement rather than introducing one "
            "of its own; a second placement makes one check produce two "
            "findings (#276)"
        )
