"""``spec-authoring`` requires a scope-claim invariant to cite its enumeration.

*Source:* ``assessments/2026-07-16-code.md`` (CODE-INSIGHT-2 — systemic
insight). A doc-only commit recorded two rules in ``CONTEXT.md`` that both
overstated what the call graph keeps: the sentinel rule claimed a value's "one
consumer" when three others read it, and the client-aggregate rule cited a
function in the past tense that was still live. Recording a rule the tree does
not follow launders an open violation into a documented invariant that future
review trusts.

**What this module asserts, after #459.** Two things, and they are different in
kind.

* **One tripwire** over one rule-home: the ``**Scope-claim invariants``
  paragraph inside ``## Change spec``. It reads a small term set the rule cannot
  be stated without, plus the negation anchored to the noun it governs — an
  enumeration that finds a second consumer means the claim is *not* an
  invariant. That anchoring is the fix for the inversion-passes class: the three
  functions this replaced were term co-occurrence over the same window, and term
  co-occurrence has no direction (ADR 0016).
* **A negative-space sweep**, kept verbatim: the rule names no single consumer's
  stack. That one judges no meaning — it only has to find a forbidden token — so
  it is exempt from the observation above and stays.

The deleted third function asserted that the rule's bolded marker sits inside
``## Change spec``; the slicer below starts from that marker *within* the
section, so the placement was already a precondition of every other assertion —
a re-check that could not fail alone (``craft.md`` → a control that cannot
distinguish its subject from its slicer).

This guard cannot prove the enumeration was genuinely run on any ticket (the
honest limit its sibling grounding and lifecycle-sweep guards state) — only that
the rule the reviewer checks against is on record.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SPEC_AUTHORING = REPO_ROOT / "skills" / "spec-authoring" / "SKILL.md"

#: The rule's direction, anchored to the noun it governs. What the rule says is
#: that a claim the enumeration falsifies stops being an *invariant*; a bare
#: negation somewhere in the paragraph would be decoration, since almost any
#: English paragraph carries one.
_NOT_AN_INVARIANT = re.compile(
    r"\binvariant\b(?:\W+\w+){0,3}?\W+\bnot\b|\bnot\b(?:\W+\w+){0,3}?\W+\binvariant\b",
    re.IGNORECASE,
)


def _spec_authoring_text() -> str:
    return SPEC_AUTHORING.read_text(encoding="utf-8")


def _change_spec_section() -> str:
    """The ``## Change spec`` section body, bounded to the next top-level heading.

    Scoped deliberately so every assertion binds on the design guidance where the
    rule belongs, not on wording that might drift into another section.
    """
    text = _spec_authoring_text()
    m = re.search(r"^##\s+Change spec\b", text, re.MULTILINE)
    assert m, "spec-authoring must have a '## Change spec' section."
    rest = text[m.end() :]
    nxt = re.search(r"^##\s+", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def test_the_scope_claim_rule_has_a_home() -> None:
    """The scope-claim rule is stated in the change-spec design guidance.

    Four conjuncts and a negation, all inside the rule's own paragraph.
    ``call graph`` is what makes the claim global rather than local; the
    ``enumeration`` is the evidence the rule demands; and the negation beside
    ``invariant`` is the consequence that gives it teeth — without it the
    paragraph asks for a grep and says nothing about what a failing grep means.
    """
    paragraph = _scope_claim_paragraph(_change_spec_section().lower())
    for term, why in (
        ("scope claim", "the rule must name its trigger — an invariant stated "
                        "as a scope claim"),
        ("call graph", "a scope claim is a claim about the whole call graph, "
                       "not a local fact"),
        ("enumeration", "the spec must cite the enumeration that establishes "
                        "the claim"),
        ("finding", "a falsified scope claim is a finding, and naming it that "
                    "is what routes it somewhere"),
    ):
        assert term in paragraph, (
            f"spec-authoring's scope-claim rule no longer names {term!r} — {why}"
        )
    assert _NOT_AN_INVARIANT.search(paragraph), (
        "the scope-claim rule no longer states that an enumeration finding a "
        "second consumer means the claim is *not* recorded as an invariant. "
        "Without the negation beside the noun, a paragraph inviting the claim "
        "to be recorded anyway would read the same to this guard."
    )


def test_scope_claim_rule_is_universal() -> None:
    """AC-3: the rule names no single consumer's stack.

    Filed from one consumer's defect (a mobile sentinel read by a component that
    rendered a bar off-screen), the rule is distributed to every repo, so it
    keys off the call graph every codebase has rather than a particular stack.
    This guard pins that boundary — the standing rule for guidance edits born
    from a single repo.
    """
    low = _change_spec_section().lower()
    for leak in ("mobile", "react", "expo", "typescript", "http", "endpoint"):
        assert leak not in _scope_claim_paragraph(low), (
            f"the scope-claim rule must not name {leak!r}: spec-authoring is "
            "distributed to every consumer repo (the universal/repo boundary)."
        )


def _scope_claim_paragraph(section_lower: str) -> str:
    """The scope-claim rule's own paragraph, so the universality guard binds on
    the rule's text and not on a stack term used elsewhere in the change-spec
    section (e.g. a sibling rule's example)."""
    marker = "**scope-claim invariants"
    start = section_lower.find(marker)
    assert start != -1, "scope-claim rule paragraph must be present (CAL-1101)."
    rest = section_lower[start + len(marker) :]
    end = rest.find("\n\n")
    return rest if end == -1 else rest[:end]
