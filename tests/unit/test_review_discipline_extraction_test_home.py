"""#276 — a seam extraction must also say where the extracted module's tests went.

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
2,768-line module.

The fix is one clause on the same bullet, bound to the same *extraction*
outcome and folded into the same **Medium** finding — not a new Stage-2 bullet
with its own trigger and severity. The bullet already holds the changed-file set
from its own ``git diff --name-only`` comparison, so the confirmation costs
nothing extra to run, and the review gate is the one moment both halves — the
extracted module and its tests — are visible at once.

Acceptance criteria (this ticket):

* **AC-1** — the clause lives on the **Architecture watchlist** bullet and both
  version stamps move (the skill header and its ``registry.yaml`` entry). The
  stamp half needs no new test: header ↔ registry parity is already asserted by
  ``test_review_discipline_backend_module_clone::test_review_discipline_header_matches_registry``
  and the tree-wide sweep in ``test_guidance_source``, so a stamp bumped without
  its registry entry (or vice versa) goes red there. The clause half is proven by
  :func:`test_watchlist_bullet_asks_where_the_extracted_modules_tests_went`.
* **AC-2** — the obligation is bound to the *extraction* outcome and admits the
  tests staying for a stated reason, rather than mandating the move. Proven by
  :func:`test_the_test_home_obligation_is_bound_to_the_extraction_outcome`.
* **AC-3** — the clause reuses the bullet's existing severity rather than adding
  a tier. Proven by :func:`test_the_clause_adds_no_new_severity`.
* **AC-4** — the assertions are *anchored to that bullet*, not matched anywhere
  in the file. Proven by :func:`test_the_clause_lives_inside_the_watchlist_bullet`.
* **AC-5** — the verify gate is green (the gate, not a test).

Why these tokens and not the obvious ones: the pre-change bullet already contains
``module`` ("the modules carved out beside it"), ``reason`` (the deferral
clause), ``extraction``, ``Medium``, ``diff`` and ``decomposition``. A guard
keyed on any of those bullet-wide is green against the *unmodified* file and
measures nothing, so each is used only inside a sentence scope, never as the
measure. ``test`` and ``stay`` were each confirmed absent from the bullet before
the clause was written, and carry the measurement.
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
_SKILL = _REPO_ROOT / "skills" / "review-discipline" / "SKILL.md"

# The neighbouring bullet. Its title must never appear inside our slice — if it
# does, the slicer over-ran and the assertions below could be satisfied by
# *that* bullet's prose instead of ours.
_NEIGHBOUR_TITLE = "**CONTEXT.md currency**"

# The severities the repo grades findings at. `medium` is the one this bullet
# already uses; the rest must stay absent, because the clause folds into that
# finding rather than introducing a tier of its own.
_OTHER_SEVERITIES = ("critical", "high", "low")


def _bullet() -> str:
    return _review_watchlist_bullet(_SKILL.read_text(encoding="utf-8"))


def test_watchlist_bullet_asks_where_the_extracted_modules_tests_went() -> None:
    """The bullet obliges an answer about the extracted module's tests (AC-1)."""
    bullet = _bullet().lower()

    assert "test" in bullet, (
        "the Architecture watchlist bullet must ask where the extracted "
        "module's tests now live — production structure and test structure "
        "part company at the extraction commit and nothing else looks (#276)"
    )
    # The obligation is to *answer*, not to move: tests may stay when the change
    # says why. A clause that only ever mandates the move would satisfy the
    # token above and fail here.
    assert re.search(r"\bstay", bullet), (
        "the bullet must admit the tests staying with a stated reason as a "
        "discharged obligation, not mandate the move — the reviewer is "
        "confirming a decision was made, not enforcing one outcome (#276)"
    )


def test_the_test_home_obligation_is_bound_to_the_extraction_outcome() -> None:
    """The answer is owed on an *extraction*, not on every watchlist touch (AC-2).

    A deferral carves nothing out, so no tests were orphaned and there is
    nothing to confirm. A clause demanding the check on every watchlist touch
    would pass the token test above and fail here — and it should, because that
    is the drift toward *check everything every time* that the neighbouring
    bullet rules out in its own text.
    """
    bearing = [s for s in _sentences(_bullet()) if "test" in s.lower()]
    assert bearing, (
        "no sentence in the Architecture watchlist bullet mentions tests — the "
        "obligation this ticket adds is missing (#276)"
    )
    for sentence in bearing:
        assert "extract" in sentence.lower(), (
            "the tests obligation must be bound to the seam-extraction outcome "
            "in the sentence that states it, not merely co-present in the "
            "bullet; an unbound clause reads as 'check the tests on every "
            f"watchlist touch' (#276). Offending sentence: {sentence!r}"
        )
    # `reason` is present elsewhere in the bullet (the deferral clause), so this
    # is a real assertion only inside the sentence scope: it pins the escape
    # hatch to the sentences that state the obligation.
    assert any("reason" in s.lower() for s in bearing), (
        "the sentences stating the tests obligation must name the stated "
        "reason that discharges it — without it the clause reads as an "
        "unconditional mandate to move the tests (#276)"
    )


def test_the_clause_adds_no_new_severity() -> None:
    """The clause folds into the bullet's existing Medium finding (AC-3)."""
    bullet = _bullet().lower()

    assert "medium" in bullet, (
        "the Architecture watchlist bullet must keep grading its structural "
        "finding Medium — the tests clause folds into it (#276)"
    )
    for severity in _OTHER_SEVERITIES:
        assert not re.search(rf"\b{severity}\b", bullet), (
            f"the bullet now grades a {severity!r} finding. The tests clause "
            "reuses the bullet's existing severity rather than introducing a "
            "tier of its own; a second severity makes one check produce two "
            "findings (#276)"
        )


def test_the_clause_lives_inside_the_watchlist_bullet() -> None:
    """The claims are anchored to the bullet, not matched file-wide (AC-4)."""
    text = _SKILL.read_text(encoding="utf-8")
    bullet = _bullet()

    assert bullet.strip(), (
        "the Architecture watchlist slice is empty — the guard would assert "
        "nothing (#276)"
    )
    assert len(bullet) < len(text), (
        "the Architecture watchlist slice spans the whole skill file, so every "
        "assertion above degenerates into a file-wide substring match (#276)"
    )
    assert _NEIGHBOUR_TITLE not in bullet, (
        f"the slice ran past the bullet into {_NEIGHBOUR_TITLE} — prose from "
        "that bullet could satisfy the tokens above without the clause "
        "existing at all (#276)"
    )
    # And the neighbour is genuinely a separate bullet in the file, so the
    # exclusion above is a real boundary rather than a vacuous one.
    assert _NEIGHBOUR_TITLE in text, (
        f"{_NEIGHBOUR_TITLE} is no longer a Stage-2 bullet, so excluding it "
        "from the slice proves nothing — re-anchor this guard (#276)"
    )
