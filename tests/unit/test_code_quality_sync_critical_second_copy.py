"""#231 — a sync-critical pattern extracts on the second copy, not the third.

`code-quality` Part B's rule-of-three tells the builder to extract on the
*third* strike. The steward's cross-file-duplication lens (`agents/steward.md`
lens 2) already applies a stricter bar — *two or more* — when the duplicated
pattern is a security check, an auth gate, or a domain rule that must stay in
sync, since two copies that can drift are already a latent bug. That gap let a
duplicated authorization predicate accumulate multiple hand-written copies
through separate merge reviews without a build-time rule ever naming it: at
copy two, the rule-of-three's own wording says "twice is a coincidence."

Filed via a downstream repo's steward assessment, routed upstream per this
repo's own guidance-fix-routing rule (`CLAUDE.md`).

Acceptance criteria (this ticket):

* **AC-1** — `code-quality` Part B, "Extract on the third strike", states that
  a permission check, an auth gate, or a domain rule that must stay in sync
  extracts on the **second** copy, immediately after the rule-of-three
  paragraph and before the mirrors-admission paragraph. Proven by
  :func:`test_second_copy_paragraph_names_the_subjects`,
  :func:`test_second_copy_paragraph_states_the_threshold_and_rationale`, and
  :func:`test_second_copy_paragraph_sits_between_its_neighbours`.
* **AC-2** — the guard is scoped to the *new* paragraph, not the section as a
  whole: the existing rule-of-three sentence already contains the phrase "a
  permission check", so an unscoped guard would be green before this ticket's
  text exists. Proven by :func:`test_selector_is_a_proper_subset_of_the_section`.
* **AC-3** — the same subject vocabulary ("auth gate", the stay-in-sync domain
  rule) that grounds this paragraph is not orphaned from the steward's lens
  that already applies the two-copy bar, so a later edit cannot silently drop
  one surface's half of the rule. Proven by
  :func:`test_subject_vocabulary_still_present_in_steward_lens`.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CODE_QUALITY = _REPO_ROOT / "skills" / "code-quality" / "SKILL.md"

_HEADING = "### Extract on the third strike"


def _section() -> str:
    """The 'Extract on the third strike' subsection's own span.

    Sliced from its heading to the next ``###``/``##`` heading so the
    assertions see only this rule, not the neighbouring Structure subsections
    or the mirrors-admission paragraph that already lives in the same section.
    """
    text = _CODE_QUALITY.read_text()
    m = re.search(rf"^{re.escape(_HEADING)}\s*$", text, re.MULTILINE)
    assert m, f"code-quality must have a {_HEADING!r} section"
    rest = text[m.end() :]
    end = re.search(r"^#{2,3} ", rest, re.MULTILINE)
    return (rest if end is None else rest[: end.start()]).strip()


def _paragraphs() -> list[str]:
    """The section's paragraphs, blank-line separated, in file order."""
    return [block.strip() for block in _section().split("\n\n") if block.strip()]


def _second_copy_paragraph() -> str:
    """The new paragraph, selected by content — not by index.

    ``_paragraphs()[1]`` would be the pre-existing rule-of-three paragraph
    until this ticket's text lands, and a later insertion elsewhere in the
    section would silently redirect a hardcoded index. Select the block that
    states the **second**-copy threshold instead.
    """
    hits = [b for b in _paragraphs() if "second" in b.lower()]
    assert hits, (
        "no paragraph in 'Extract on the third strike' states a second-copy "
        "threshold — the sync-critical exception (permission check / auth "
        "gate / domain rule that must stay in sync) is missing (AC-1)."
    )
    return "\n\n".join(hits)


def _rule_of_three_paragraph() -> str:
    hits = [b for b in _paragraphs() if "coincidence" in b.lower()]
    assert hits, "the rule-of-three paragraph ('twice is a coincidence') is missing"
    return hits[0]


def _mirrors_admission_paragraph() -> str:
    hits = [b for b in _paragraphs() if "mirrors" in b.lower()]
    assert hits, "the mirrors-admission paragraph is missing"
    return hits[0]


# --- AC-1: the paragraph exists, names its subjects, states the threshold -----


def test_second_copy_paragraph_names_the_subjects() -> None:
    """The paragraph names all three sync-critical subjects (AC-1)."""
    para = _second_copy_paragraph().lower()
    for phrase in ("permission check", "auth gate", "domain rule"):
        assert phrase in para, (
            f"the second-copy paragraph must name {phrase!r} as a sync-critical "
            f"subject; got: {para!r} (AC-1)."
        )
    assert "stay in sync" in para or "sync" in para, (
        "the second-copy paragraph must state that the domain rule must stay "
        f"in sync; got: {para!r} (AC-1)."
    )


def test_second_copy_paragraph_states_the_threshold_and_rationale() -> None:
    """The paragraph states 'second copy' extraction and the drift rationale (AC-1)."""
    para = _second_copy_paragraph().lower()
    assert "second" in para and "extract" in para, (
        "the paragraph must require extraction on the second copy; got: "
        f"{para!r} (AC-1)."
    )
    assert "drift" in para or "latent bug" in para, (
        "the paragraph must state the rationale — two copies that can drift "
        f"are already a latent bug; got: {para!r} (AC-1)."
    )
    assert "coincidence" in para, (
        "the paragraph must say the coincidence allowance does not apply to "
        f"these subjects; got: {para!r} (AC-1)."
    )


def test_second_copy_paragraph_sits_between_its_neighbours() -> None:
    """The paragraph lands directly after rule-of-three, before mirrors-admission (AC-1)."""
    paragraphs = _paragraphs()
    rot = _rule_of_three_paragraph()
    mirrors = _mirrors_admission_paragraph()
    second_copy = _second_copy_paragraph()

    assert second_copy != rot and second_copy != mirrors, (
        "the second-copy paragraph must be distinct from its neighbours, not "
        "folded into either (AC-1)."
    )
    rot_idx = paragraphs.index(rot)
    mirrors_idx = paragraphs.index(mirrors)
    second_copy_idx = paragraphs.index(second_copy.split("\n\n")[0])

    assert rot_idx < second_copy_idx < mirrors_idx, (
        "the second-copy paragraph must sit strictly between the rule-of-three "
        f"paragraph (index {rot_idx}) and the mirrors-admission paragraph "
        f"(index {mirrors_idx}); got index {second_copy_idx} (AC-1)."
    )


# --- AC-2: the guard is scoped to the new paragraph, not the whole section ----


def test_selector_is_a_proper_subset_of_the_section() -> None:
    """The second-copy paragraph is a proper subset of the section (AC-2).

    The existing rule-of-three sentence already contains the exact phrase "a
    permission check" (as an example load-bearing pattern), so an unscoped
    guard checking the whole section for that phrase would be green before
    this ticket's paragraph ever existed. Pin the selector to a strict subset.
    """
    section = _section()
    second_copy = _second_copy_paragraph()
    assert second_copy != section, (
        "the second-copy selector must not degenerate to the whole section — "
        "that would make the AC-1 tests pass on pre-existing wording (AC-2)."
    )
    assert second_copy in section
    assert second_copy != _rule_of_three_paragraph(), (
        "the second-copy paragraph must be its own paragraph, distinct from "
        "the rule-of-three paragraph that already mentions 'a permission "
        "check' as an example pattern (AC-2)."
    )


# --- AC-3: the subject vocabulary stays in the domain-standard home -----------


def test_subject_vocabulary_stays_in_code_quality() -> None:
    """The domain-standard home retains the sync-critical subjects (AC-3)."""
    para = _second_copy_paragraph().lower()
    assert "auth gate" in para
    assert "domain rule" in para and "sync" in para
