"""CAL-711 — review-discipline over-engineering taxonomy + assessment-craft reference.

Spawned from ``specs/proposals/borrow-from-ponytail.md`` (accepted 2026-06-15,
decision D1 = review-discipline canonical + assessment-craft reference). The
ponytail plugin itself is **not** installed.

``review-discipline`` already cites principle violations and has diff-scoped
deletion lenses, but had no reusable **over-engineering taxonomy** — so "this is
over-built, here is what replaces it" was a per-case judgement instead of a fast,
repeatable call.

**What this module asserts, after #459.** Two exclusivity checks — the five-tag
list has exactly one home among the skills, and ``assessment-craft`` references it
without reproducing the set — plus **one tripwire** over the lens bullet itself:
the five tags in their definitional form, the instruction to name the replacement,
the complexity-only scope, and the carve-out for the minimum test.

Three lens-body pins collapsed into it (ADR 0016).

Occurrence the polarity anchor cites (``code-quality`` Part C): the pre-#459
carve-out check was ``assert "not" in block or "never" in block`` over the lens
bullet. That is decoration, not polarity — the bullet is ~1,200 characters of
English and contains ``not`` several times over for unrelated reasons ("do not
relabel a real bug", "pre-existing complexity … is not a finding"). It could not
fail while the lens existed, including on the exact regression it names: a bullet
rewritten to flag the minimum smoke test as bloat keeps every one of those
negations. Anchoring the negation to ``smoke test`` / ``self-check`` is the fix.
The ``craft.md`` class is *A guard over prose owns structure and negative space,
never meaning*.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "skills"
REVIEW_DISCIPLINE = SKILLS_DIR / "review-discipline" / "SKILL.md"
ASSESSMENT_CRAFT = SKILLS_DIR / "assessment-craft" / "SKILL.md"

#: The five over-engineering tags, in their definitional ``\`tag:\``` inline-code
#: form. The canonical home defines each as a list item; a reference elsewhere
#: must not reproduce the whole set (AC-3).
TAGS = ("stdlib", "native", "yagni", "shrink", "delete")

#: The carve-out, **anchored to the subject it protects**. The smallest thing that
#: proves the change works is never bloat; a lens that flags it turns the
#: over-engineering call into an argument against testing.
#:
#: **Four words of gap, measured rather than guessed.** The bullet's preceding
#: sentence ends *"do not relabel a real bug as over-engineering."* and the
#: carve-out opens *"The single minimum smoke test"* — ten words apart. A gap of
#: twelve therefore matched that unrelated negation against this subject, so an
#: inverted carve-out ("is routinely flagged as bloat") still satisfied the
#: predicate. Four spans every legitimate spelling of the real clause
#: (``self-check, is **never** flagged``) and stops short of the neighbour.
_MINIMUM_TEST_IS_NEVER_BLOAT = re.compile(
    r"\b(?:never|not|no)\b(?:\W+\w+){0,4}?\W+(?:smoke test|self-check)\b"
    r"|\b(?:smoke test|self-check)\b(?:\W+\w+){0,4}?\W+(?:never|not|no)\b",
    re.IGNORECASE,
)


def _tag_markers(text: str) -> set[str]:
    r"""The tags appearing in ``text`` in their definitional ``\`tag:\``` form."""
    return {t for t in TAGS if f"`{t}:`" in text}


def _over_engineering_block(text: str) -> str:
    """The over-engineering lens block: from its bullet to the next top-level item.

    The lens is a ``- **Over-engineering** —`` bullet under Stage 2 → Quality with
    an indented sub-list of tags and a scope clause. Slice from that bullet to the
    next top-level ``- **`` bullet or the next ``##`` heading so the assertions see
    only the lens.
    """
    m = re.search(r"^- \*\*Over-engineering\*\*", text, re.MULTILINE)
    assert m, (
        "review-discipline Stage 2 has no '- **Over-engineering**' lens bullet "
        "(CAL-711 AC-1)."
    )
    rest = text[m.end() :]
    end = re.search(r"^(?:- \*\*|## )", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def test_the_over_engineering_lens_names_its_cuts_and_its_carve_out() -> None:
    """The one tripwire over the lens bullet (AC-1/AC-2).

    Four parts:

    * **anchor** — the ``- **Over-engineering**`` bullet resolves;
      :func:`_over_engineering_block` asserts it exists, so a rename names itself
      instead of emptying the window.
    * **terms** — all five tags in their definitional form, plus ``replace`` (the
      lens's whole point is that a finding names the simpler form, not that
      something feels over-built) and ``complexity only`` (the scope that keeps
      correctness, security, and performance in their own lenses).
    * **polarity** — the negation anchored to ``smoke test`` / ``self-check``.
      The carve-out is the one part of this lens that can be *inverted* rather
      than merely dropped, and inverting it is expensive: a reviewer that reads
      the minimum test as bloat argues against the smallest evidence a change can
      carry.
    """
    block = _over_engineering_block(REVIEW_DISCIPLINE.read_text())

    missing = sorted(set(TAGS) - _tag_markers(block))
    assert not missing, (
        "the over-engineering lens must define all five tags in `tag:` form "
        f"(stdlib/native/yagni/shrink/delete); missing: {missing} (AC-1)."
    )

    lowered = block.lower()
    assert "replace" in lowered, (
        "the over-engineering lens no longer instructs the reviewer to name what "
        "*replaces* the cut. Without it a finding is a vibe, not a fix (AC-1)."
    )
    assert "complexity only" in lowered, (
        "the lens no longer states it is 'complexity only', so correctness, "
        "security, and performance findings can be relabelled as over-engineering "
        "and lose their own lens's bar (AC-2)."
    )

    assert _MINIMUM_TEST_IS_NEVER_BLOAT.search(block), (
        "the lens no longer carves the single minimum smoke test / `assert`-based "
        "self-check out as never-bloat, with the negation beside the thing it "
        "protects. A bare negation elsewhere in the bullet is satisfied by a lens "
        "that flags the minimum test — which turns an over-engineering call into "
        "an argument against testing at all (AC-2)."
    )


# --- AC-3: the tag list lives in exactly one skill file -----------------------


def test_tag_taxonomy_lives_in_exactly_one_skill_file() -> None:
    """Exactly one skill file defines the full five-tag list — review-discipline (AC-3)."""
    homes = [
        p
        for p in SKILLS_DIR.glob("*/SKILL.md")
        if _tag_markers(p.read_text()) == set(TAGS)
    ]
    rels = sorted(str(p.relative_to(REPO_ROOT)) for p in homes)
    assert rels == ["skills/review-discipline/SKILL.md"], (
        "the over-engineering tag list must have exactly one canonical home "
        f"(skills/review-discipline/SKILL.md); found in: {rels} (AC-3)."
    )


def test_assessment_craft_references_without_duplicating() -> None:
    """assessment-craft points /assess code at the taxonomy without copying it (AC-3)."""
    text = ASSESSMENT_CRAFT.read_text()
    assert "over-engineering" in text.lower() and "review-discipline" in text, (
        "assessment-craft must reference the review-discipline over-engineering "
        "taxonomy for the /assess code pass (AC-3)."
    )
    present = _tag_markers(text)
    assert present != set(TAGS), (
        "assessment-craft must REFERENCE the taxonomy, not duplicate the tag "
        f"definitions — the full tag list belongs in one skill file; found: "
        f"{sorted(present)} (AC-3)."
    )
