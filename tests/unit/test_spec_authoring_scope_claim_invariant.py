"""CAL-1101 — require a scope-claim invariant to cite its enumeration.

*Source:* ``assessments/2026-07-16-code.md`` (CODE-INSIGHT-2, Medium — systemic
insight). A doc-only commit recorded two rules in ``CONTEXT.md`` that both
overstated what the call graph keeps: the sentinel rule claimed a value's "one
consumer" when three others read it (one doing arithmetic that put a bar 517px
off-screen), and the client-aggregate rule cited a function in the past tense
that was still live. Recording a rule the tree does not follow is worse than not
recording it — it launders an open violation into a documented invariant that
future review trusts. The sentinel rule's own text named its falsifier; nobody
ran the one grep that would have found the extra consumers.

The fix is a design-time rule in ``spec-authoring``: an invariant stated as a
scope claim ("the only consumer", "exactly one home", "nothing else reads this")
is a claim about the whole call graph, so the spec must cite the enumeration
that establishes it. If the enumeration finds a second consumer, it is a finding,
not an invariant — converting the class from a steward catch to an author-time
one, the same move CAL-1075 made for vacuous fixtures.

This guard pins the *presence* of that rule in the surface. It cannot prove the
enumeration was genuinely run on any ticket (the honest limit the grounding and
lifecycle-sweep guards state) — only that the rule the reviewer checks against
is on record. It is a text-parse content guard in the style of
``test_lifecycle_sweep_spec`` (CAL-973) and ``test_grounding_step``.

Acceptance criteria (this ticket):

* **AC-1** — the skill states the rule: a scope-claim invariant is a whole-call-
  graph claim, cite the enumeration, and a second consumer makes it a finding.
  :func:`test_spec_authoring_has_scope_claim_rule`,
  :func:`test_scope_claim_rule_states_finding_consequence`.
* **AC-1 (placement)** — the rule lives in the change-spec design guidance.
  :func:`test_scope_claim_rule_in_change_spec_section`.
* **AC-3** — the rule is phrased universally, naming no single consumer's stack.
  :func:`test_scope_claim_rule_is_universal`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SPEC_AUTHORING = REPO_ROOT / "skills" / "spec-authoring" / "SKILL.md"


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


def test_spec_authoring_has_scope_claim_rule() -> None:
    """AC-1: the skill frames a scope claim as a whole-call-graph claim that must
    cite its enumeration."""
    low = _change_spec_section().lower()
    assert "scope claim" in low, (
        "spec-authoring must name the trigger — an invariant stated as a 'scope "
        "claim' (CAL-1101 AC-1)."
    )
    assert "whole call graph" in low, (
        "the rule must state a scope claim is a claim about the 'whole call "
        "graph', not a local fact (CAL-1101 AC-1)."
    )
    assert "cite the enumeration" in low, (
        "the rule must require the spec to *cite the enumeration* that "
        "establishes the claim (CAL-1101 AC-1)."
    )


def test_scope_claim_rule_states_finding_consequence() -> None:
    """AC-1: the rule states the consequence that gives it teeth — if the
    enumeration finds a second consumer, the claim is a finding, not an
    invariant. This clause is what converts the class from steward-catch to
    author-time."""
    low = _change_spec_section().lower()
    assert re.search(r"if the enumeration finds a second consumer", low), (
        "the rule must state that if the enumeration finds a second consumer, "
        "the invariant is not recorded (CAL-1101 AC-1)."
    )
    assert "finding" in low, (
        "the rule must name the second-consumer outcome a *finding*, not an "
        "invariant (CAL-1101 AC-1)."
    )


def test_scope_claim_rule_in_change_spec_section() -> None:
    """AC-1 (placement): the rule sits inside the change-spec design guidance,
    beside the sibling grounding / watchlist / lifecycle-sweep rules."""
    section = _change_spec_section()
    assert "**Scope-claim invariants" in section, (
        "the scope-claim rule must live in the '## Change spec' design guidance "
        "as a bolded conditional rule, beside its siblings (CAL-1101 placement)."
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
