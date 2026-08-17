"""#204 — a placeholder/stub returning fabricated data must be flag-gated.

*Origin:* form repo, Linear CAL-1130 (``/assess code`` steward pass 2026-07-17,
CODE-INSIGHT-1; report ``assessments/2026-07-17-code-review.md``). Decision made
2026-07-24: adopt as drafted. Two instances one day apart in the originating
repo — a share-card stub and an OCR stub — both wired to live, ungated surfaces,
both filed after the fact rather than caught at merge. The originating repo owned
a gating mechanism (feature-visibility flags) but had no rule mandating its use
for incomplete features.

**Converted under #459** (ADR 0016, and ``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*). Four prose tests became
**two tripwires, one per rule-home** — the builder's home and the reviewer's. The
two dropped tests were placement re-checks their own slicers already performed
(``craft.md`` → *The text unit is part of the predicate*): each asserted a term
against the very window the sibling test had already sliced.

**What this module now asserts.**

* **Two tripwires, two homes.** ``code-quality`` Part A states the rule for the
  builder; ``review-discipline``'s diff-shape checks state it for the reviewer.
  Both are anchored — the Part A subsection is sliced *from inside* ``## Part A
  — Scope`` so the slice carries the placement claim, and the reviewer's copy is
  sliced to its own Stage 2 bullet, never the whole file.
* **Term set** — the stub shape (``hardcoded``/``faked``/``placeholder``), the
  gate (``off-by-default``, ``feature flag``) and what must not reach it
  (``user-facing control``). The rule cannot be stated without them: drop
  ``off-by-default`` and a flag that ships on satisfies the rest.
* **Polarity** — the negation bound to what it governs: the stub *must **not** be
  reachable*. A bare ``not`` in the paragraph would be decoration; bound to
  ``reachable`` it inverts with the rule (``craft.md`` → *Mutate the rule into
  its opposite, not only out of existence*).
* **Two identity assertions stay byte-for-byte** — each file's ``guidance:``
  header against its ``registry.yaml`` entry. Neither operand is an opinion, so
  neither is affected by this conversion.

**What it does not prove.** That any repo's flag is actually off by default, or
that the prose around these terms still advises what it used to. That is the
reviewer's.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._prose import REPO_ROOT, section

_CODE_QUALITY = REPO_ROOT / "skills" / "code-quality" / "SKILL.md"
_REVIEW_DISCIPLINE = (
    REPO_ROOT
    / "skills"
    / "review-discipline"
    / "references"
    / "diff-shape-checks.md"
)
_REGISTRY = REPO_ROOT / "registry.yaml"

_HEADER_RE = re.compile(r"<!--\s*guidance:[\w-]+@([\d.]+)\s*-->")

_PART_A = "## Part A — Scope"
_HEADING = "### Placeholder and stub gating"
_STAGE_TWO = "### Stage 2 — Diff-shape checks"

#: The words the rule cannot be stated without. The first is an alternation
#: because the three spellings of a fabricated-data body are interchangeable.
_TERMS = (
    r"\bhardcoded\b|\bfaked\b|\bplaceholder\b",
    r"\boff-by-default\b",
    r"\bfeature flag\b",
    r"\buser-facing control\b",
)

#: The negation **bound to the reachability it denies**. ``not`` alone is
#: satisfied by almost any English sentence; within a couple of words of
#: ``reachable`` it is the clause that inverts with the rule.
_MUST_NOT_BE_REACHABLE = re.compile(
    r"\b(?:not|never)\b(?:\W+\w+){0,2}?\W+reachable\b", re.IGNORECASE
)


def _header_version(path: Path) -> str:
    m = _HEADER_RE.search(path.read_text())
    assert m, f"{path} must carry a guidance: header"
    return m.group(1)


def _registry_version(rel_path: str) -> str:
    text = _REGISTRY.read_text()
    m = re.search(
        rf"^\s*{re.escape(rel_path)}:.*?version:\s*([\d.]+)", text, re.MULTILINE
    )
    assert m, f"{rel_path} must have a registry.yaml files: entry"
    return m.group(1)


def _builder_rule() -> str:
    """``### Placeholder and stub gating``, sliced from inside ``## Part A``.

    ``section`` is imported rather than re-spelled, and the two calls are
    nested so the placement claim lives in the anchor instead of a second test.
    """
    text = _CODE_QUALITY.read_text(encoding="utf-8")
    return section(section(text, _PART_A), _HEADING)


def _reviewer_bullet() -> str:
    """The Stage 2 bullet carrying the placeholder/stub check.

    Sliced to the bullet, never the file: an assertion over the whole reference
    is satisfied by a neighbouring bullet's vocabulary and would stay green with
    this rule deleted.
    """
    stage_two = section(_REVIEW_DISCIPLINE.read_text(encoding="utf-8"), _STAGE_TWO)
    m = re.search(r"^- \*\*[^\n]*(?:laceholder|stub)[^\n]*$", stage_two, re.MULTILINE)
    assert m, (
        "review-discipline's Stage 2 diff-shape checks have no bullet naming the "
        "placeholder/stub reachability rule (#204 AC-2)."
    )
    rest = stage_two[m.start() :]
    nxt = re.search(r"^(?:- \*\*|#{2,3} )", rest[1:], re.MULTILINE)
    return rest[: nxt.start() + 1] if nxt else rest


def _assert_states_the_gating_rule(window: str, *, where: str, ac: str) -> None:
    """The tripwire body, shared by both homes.

    One predicate, two call sites — re-spelling it per home would fork the
    predicate from the samples that measure it (``craft.md`` → *A positive
    control must exercise the predicate, not re-implement it*).
    """
    assert window.strip(), f"{where} is empty — a heading with no rule states nothing."

    missing = [t for t in _TERMS if not re.search(t, window, re.IGNORECASE)]
    assert not missing, (
        f"{where} no longer carries the terms the placeholder-gating rule cannot be "
        f"stated without; missing {missing}. A body returning hardcoded/faked/"
        "placeholder data must sit behind an off-by-default feature flag before any "
        f"user-facing control can reach it ({ac}). Window read:\n{window}"
    )

    assert _MUST_NOT_BE_REACHABLE.search(window), (
        f"{where} has lost its polarity: the stub must be stated as *not reachable* "
        "from a user-facing control unless gated. Without the negation bound to "
        "`reachable`, a passage carrying every term above while permitting the "
        f"ungated stub passes ({ac}). Window read:\n{window}"
    )


def test_the_builder_home_states_the_gating_rule() -> None:
    """AC-1: ``code-quality`` Part A is the builder's home for the rule."""
    _assert_states_the_gating_rule(
        _builder_rule(), where=f"code-quality {_HEADING!r}", ac="#204 AC-1"
    )


def test_the_reviewer_home_states_the_gating_rule() -> None:
    """AC-2: the diff-shape checks state the same rule for the reviewer."""
    _assert_states_the_gating_rule(
        _reviewer_bullet(),
        where="the review-discipline Stage 2 placeholder/stub bullet",
        ac="#204 AC-2",
    )


# --- AC-3: header + registry version parity -------------------------------


def test_code_quality_header_matches_registry() -> None:
    assert _header_version(_CODE_QUALITY) == _registry_version(
        "skills/code-quality/SKILL.md"
    ), "code-quality's guidance: header must match its registry.yaml version (#204 AC-3)."


def test_review_discipline_header_matches_registry() -> None:
    assert _header_version(_REVIEW_DISCIPLINE) == _registry_version(
        "skills/review-discipline/references/diff-shape-checks.md"
    ), (
        "review-discipline's guidance: header must match its registry.yaml "
        "version (#204 AC-3)."
    )
