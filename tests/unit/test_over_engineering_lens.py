"""CAL-711 — review-discipline over-engineering taxonomy + assessment-craft reference.

Spawned from ``specs/proposals/borrow-from-ponytail.md`` (accepted 2026-06-15,
decision D1 = review-discipline canonical + assessment-craft reference). The
ponytail plugin itself is **not** installed.

``review-discipline`` already cites principle violations and has diff-scoped
deletion lenses ("Dead surface after a deletion", "Port-time orphan"), but no
reusable **over-engineering taxonomy** — so "this is over-built, here is what
replaces it" was a per-case judgement instead of a fast, repeatable call. These
guards pin the taxonomy and its single canonical home:

* **AC-1** — ``review-discipline`` Stage 2 names the over-engineering lens with
  all five tags (``stdlib`` / ``native`` / ``yagni`` / ``shrink`` / ``delete``),
  each instructing the reviewer to name what replaces the cut.
* **AC-2** — the lens is complexity-only (correctness/security/perf stay in their
  own lenses) and never flags the minimum smoke test / ``assert``-based
  self-check as bloat.
* **AC-3** — ``assessment-craft`` references the taxonomy for ``/assess code``
  and does **not** duplicate the tag definitions: the tag list lives in exactly
  one skill file.
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


# --- AC-1: the lens names all five tags, each naming the replacement ----------


def test_over_engineering_lens_has_all_five_tags() -> None:
    """review-discipline Stage 2 names the lens with all five tags (AC-1)."""
    block = _over_engineering_block(REVIEW_DISCIPLINE.read_text())
    present = _tag_markers(block)
    missing = set(TAGS) - present
    assert not missing, (
        "the over-engineering lens must define all five tags in `tag:` form "
        f"(stdlib/native/yagni/shrink/delete); missing: {sorted(missing)} (AC-1)."
    )


def test_over_engineering_lens_names_the_replacement() -> None:
    """Each tag instructs the reviewer to name what replaces the cut (AC-1).

    The lens's whole point is that a finding stays actionable because it names the
    simpler form. The block must instruct naming the replacement, not merely flag
    "this is over-built".
    """
    block = _over_engineering_block(REVIEW_DISCIPLINE.read_text()).lower()
    assert "replace" in block, (
        "the over-engineering lens must instruct the reviewer to name what "
        "*replaces* the cut so the finding stays concrete (AC-1)."
    )


# --- AC-2: complexity-only, and the minimum test is never bloat ---------------


def test_over_engineering_lens_is_complexity_only() -> None:
    """The lens states it is complexity-only — other axes stay in their lenses (AC-2)."""
    block = _over_engineering_block(REVIEW_DISCIPLINE.read_text()).lower()
    assert "complexity only" in block, (
        "the lens must state it is 'complexity only' so correctness/security/"
        "performance stay in their own lenses (AC-2)."
    )


def test_over_engineering_lens_never_flags_the_minimum_test() -> None:
    """The lens never flags the minimum smoke test / self-check as bloat (AC-2)."""
    block = _over_engineering_block(REVIEW_DISCIPLINE.read_text()).lower()
    mentions_min_test = "smoke test" in block or "self-check" in block
    assert mentions_min_test, (
        "the lens must carve out the single minimum smoke test / assert-based "
        "self-check as never-bloat (AC-2)."
    )
    assert "not" in block or "never" in block, (
        "the smoke-test / self-check carve-out must be a negative ('not'/'never' "
        "over-engineering) (AC-2)."
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
