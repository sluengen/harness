"""``spec-authoring`` requires a lifecycle sweep in change-spec design sections.

*Source:* ``assessments/2026-07-03-full-review.md`` (CODE-INSIGHT-1 — systemic
insight). One review pass surfaced three separate write/delete paths that
shipped their primary mutation but missed a *derived* artifact of the same
entity: a POST that never invalidated its cache, a deletion that never revoked
the entity's share token, and an anonymisation that filtered some aggregates but
not others. The class of defect is "a state change that forgets its derived
artifacts", and the fix is to do the sweep at spec time, where it is cheapest.

**What this module asserts, after #459.** One tripwire over one rule-home: the
``**Lifecycle sweep`` paragraph inside ``skills/spec-authoring/SKILL.md`` →
``## Change spec``. It reads a small term set the rule cannot be stated without,
plus the negation anchored to the noun it governs — *silence* is not an
acceptable answer. Whether the surrounding prose argues the rule well is the
review gate's, per ADR 0016: no regex reads meaning, so a pinned sentence is
brittle and vacuous at the same time.

Craft class this conversion answers (``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*). Three of the four
deleted functions read the **whole skill file** rather than the rule's window,
so any of their terms appearing anywhere in ``spec-authoring`` satisfied them;
one of those pinned four example artifact kinds (``cache``, ``share token``,
``aggregate``, ``session``), which are illustrations the rule survives losing.
The fourth asserted that ``derived artifact`` appears somewhere in
``## Change spec`` — the placement the slicer below now performs as a
precondition, so it could not fail alone.

This guard cannot prove the sweep was genuinely performed on any ticket (the
same honest limit its sibling grounding guard states) — only that the rule the
reviewer checks against is on record.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

SPEC_AUTHORING = REPO_ROOT / "skills" / "spec-authoring" / "SKILL.md"

#: The rule's direction, anchored to the noun it governs. "Unaffected" being an
#: acceptable answer is only half a rule; what closes the gap is that *silence*
#: is not one, which is what turns an omission into a spec defect. A bare
#: negation over the paragraph would be decoration.
_SILENCE_IS_NOT = re.compile(
    r"\bsilence\b(?:\W+\w+){0,3}?\W+\bnot\b|\bnot\b(?:\W+\w+){0,3}?\W+\bsilence\b",
    re.IGNORECASE,
)


def _spec_authoring_text() -> str:
    return SPEC_AUTHORING.read_text()


def _change_spec_section() -> str:
    """The ``## Change spec`` section body, bounded to the next top-level heading."""
    text = _spec_authoring_text()
    m = re.search(r"^##\s+Change spec\b", text, re.MULTILINE)
    assert m, "spec-authoring must have a '## Change spec' section."
    rest = text[m.end() :]
    nxt = re.search(r"^##\s+", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def _lifecycle_sweep_paragraph() -> str:
    """The rule's own paragraph, sliced from its bolded marker inside the section.

    The window is a paragraph, not the section: ``enumerate``, ``artifact`` and
    ``unaffected`` all have neighbours in ``## Change spec`` that could supply
    them, and a section-wide conjunction would then be satisfied by prose that
    says nothing about a state change — the over-wide unit ``craft.md`` → *The
    text unit is part of the predicate* names.
    """
    section = _change_spec_section()
    marker = "**Lifecycle sweep"
    start = section.find(marker)
    assert start != -1, (
        "spec-authoring's '## Change spec' section must carry the bolded "
        "`Lifecycle sweep` rule, beside its sibling conditional rules"
    )
    rest = section[start:]
    end = rest.find("\n\n")
    return (rest if end == -1 else rest[:end]).lower()


def test_the_lifecycle_sweep_rule_has_a_home() -> None:
    """The change-spec guidance carries the lifecycle sweep, with its direction.

    Four conjuncts and a negation. The trigger scopes the rule to a state
    change; ``derived artifact`` is its subject; ``enumerate`` is the obligation
    (mentioning them is not doing the sweep); ``unaffected`` is the sanctioned
    cheap answer; and the negation beside ``silence`` is what makes an omission
    a spec defect rather than an oversight.
    """
    paragraph = _lifecycle_sweep_paragraph()
    for term, why in (
        ("state-changing operation", "the sweep is scoped to a state-changing "
                                     "operation; unscoped it is advice"),
        ("derived artifact", "the derived artifacts of the affected entity are "
                             "the sweep's subject"),
        ("enumerat", "the rule must require *enumerating* them, not merely "
                     "mentioning that they exist"),
        ("unaffected", "'Unaffected' is the sanctioned per-artifact answer, and "
                       "without it the rule reads as demanding work per artifact"),
    ):
        assert term in paragraph, (
            f"spec-authoring's lifecycle-sweep rule no longer names {term!r} — {why}"
        )
    assert _SILENCE_IS_NOT.search(paragraph), (
        "the lifecycle-sweep rule no longer states that silence is *not* an "
        "acceptable answer. That clause is the whole difference between a "
        "checklist and a hint: without it a change spec that says nothing about "
        "a derived artifact has complied, which is the defect class the rule "
        "exists to close."
    )
