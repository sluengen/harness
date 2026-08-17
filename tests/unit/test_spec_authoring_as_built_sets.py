"""#285 — feature specs cannot hand-list a code-owned set without a guard.

**What this module asserts, after #459.** Two tripwires over two rule-homes in
``skills/spec-authoring/SKILL.md`` → ``## Feature spec`` — the code-owned set
rule (#285) and the present-tense quantity rule (#470) — plus the
version/registry correspondence, which is structural and untouched. Each
tripwire is the negation anchored to the verb it governs together with the
sanctioned alternative the rule cannot be stated without. Whether the prose
argues either rule well is the review gate's, per ADR 0016.

Craft class this conversion answers (``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*): the deleted
``test_feature_spec_rule_prevents_hand_listed_code_owned_sets`` pinned three
sentence fragments verbatim, and the deleted
``test_feature_spec_guard_tokens_were_absent_before_this_change`` asserted that
three example nouns from the pre-change tree were present — a non-vacuity
control that, once the rule shipped, became identical in effect to the home
assertion it was guarding and could only ever fail together with it.

**Why the window is a paragraph and not the section (#470).** The two rules
share their sanctioned-alternative vocabulary: both offer *a guard that derives*
the thing and *fails* on disagreement. Measured over the two paragraphs as
written, a section-wide scan would leave the code-owned set tripwire's
guard/derive conjunct satisfied by the quantity rule alone, and two of the five
assertions in the quantity tripwire satisfied by the code-owned set rule alone.
Neither guard goes wholly vacuous that way, but a conjunct that survives the
deletion of the rule it guards is defending nothing — the double-anchoring trap
in ``review-discipline`` → ``references/craft.md`` (*A prose mutation needs a
paired splice to prove it was live*). Each tripwire therefore resolves its own
paragraph by an anchor unique to that rule, and an anchor that resolves to
anything other than exactly one paragraph fails by name rather than falling
through to a neighbour.

**What this guard does not catch, deliberately.** An *appended* exception —
the rule left intact with a sentence granting a carve-out added after it —
passes, measured. That is the fail-open shape ``craft.md`` names under *A
blacklist inversion sweep fails open on an appended grant*, and closing it would
need a whitelist sweep over permissive wording, which ADR 0016 rules out as
asserting meaning. The reviewer catches that edit; this guard catches the rule
going missing, losing its polarity, or losing one of its three alternatives.

Occurrence this guard prevents (#470, promoted from the proposals ledger
2026-08-17): four false or unreconstructable measured claims across four
reviews — three of them present-tense counts in one feature spec, plus ADR
0016's own unreconstructable figures.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

SKILL = REPO_ROOT / "skills" / "spec-authoring" / "SKILL.md"
REGISTRY = REPO_ROOT / "registry.yaml"

#: The rule's direction, anchored to the verb it governs. A paragraph merely
#: containing a negation and the word "enumerate" somewhere states nothing; what
#: the rule says is that enumerating is the thing an as-built record may not do.
_MUST_NOT_ENUMERATE = re.compile(
    r"\b(?:must not|never|not|cannot|may not)\b(?:\W+\w+){0,4}?\W+enumerat\w+",
    re.IGNORECASE,
)

#: Same shape for the quantity rule: the negation has to govern the *stating* of
#: the figure. A paragraph carrying a stray "not" states no prohibition.
#:
#: The verb is spelled out rather than written ``stat\w+`` because the loose form
#: matches the *noun*: measured against this rule's own paragraph, replacing the
#: prohibition with "…states a quantity on its own: this is not a statement of
#: preference" left ``stat\w+`` satisfied by "statement" and the guard green over
#: an inverted rule. That is the false converse ``review-discipline`` →
#: ``references/craft.md`` names (*The negation window assumes a false
#: converse*): a negation inside the window is not a negation governing the verb.
_MUST_NOT_STATE = re.compile(
    r"\b(?:must not|never|not|cannot|may not)\b(?:\W+\w+){0,4}?"
    r"\W+(?:state|states|stating|stated)\b",
    re.IGNORECASE,
)

#: Alternative (a) — the figure names the commit it was measured at. Bound as a
#: relation, not two loose tokens: "commit" alone survives in the clause about
#: the next commit that falsifies the count, so only the adjacency dies when the
#: alternative is removed.
_MEASURED_AT_A_COMMIT = re.compile(
    r"\bcommit\w*\b(?:\W+\w+){0,3}?\W+measur\w+",
    re.IGNORECASE,
)

#: Alternative (b) — a guard *derives* the figure. Bound the same way, because
#: a guard mentioned without the derivation is the claim the rule rejects.
_A_GUARD_DERIVES = re.compile(
    r"\bguard\w*\b(?:\W+\w+){0,3}?\W+deriv\w+",
    re.IGNORECASE,
)

#: The anchors that select each rule's paragraph. Each is a token the other rule
#: does not use, so a deleted rule cannot be impersonated by its neighbour.
_ENUMERATED_SET_ANCHOR = re.compile(r"\benumerat\w+", re.IGNORECASE)
_QUANTITY_ANCHOR = re.compile(r"\bquantit\w+", re.IGNORECASE)


def _feature_spec_section() -> str:
    """The ``## Feature spec`` section, bounded by the next top-level heading.

    Matched as a whole heading rather than split on a substring, so a renamed
    section fails with a named assertion instead of an ``IndexError`` from the
    split that missed.
    """
    text = SKILL.read_text()
    m = re.search(r"^##\s+Feature spec\b", text, re.MULTILINE)
    assert m, "spec-authoring must have a '## Feature spec' section"
    rest = text[m.end() :]
    nxt = re.search(r"^##\s+", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def _rule_paragraph(anchor: re.Pattern[str], rule: str) -> str:
    """The one paragraph of ``## Feature spec`` carrying ``rule``.

    Resolving the window is itself an assertion, and a loud one. Two rules now
    live in this section and they share their sanctioned-alternative vocabulary
    (a *guard* that *derives*), so a tripwire scanning the whole section is
    satisfied by whichever rule survives. Anchoring to a paragraph is only a
    real narrowing if a missing anchor **fails** — a helper that returned the
    section, the first paragraph, or an empty string on no match would restore
    exactly the fall-through it exists to prevent.
    """
    hits = [
        para
        for para in re.split(r"\n[ \t]*\n", _feature_spec_section())
        if anchor.search(para)
    ]
    assert len(hits) == 1, (
        f"expected exactly one paragraph of spec-authoring's '## Feature spec' "
        f"section to carry the {rule} rule, matched by {anchor.pattern!r}; "
        f"found {len(hits)}. A rule whose anchor no longer resolves must fail "
        f"here, because the assertions below would otherwise run against a "
        f"neighbouring paragraph that shares its vocabulary and report green "
        f"over a rule that is gone."
    )
    return hits[0]


def test_the_code_owned_set_rule_has_a_home() -> None:
    """The Feature spec section forbids hand-listing a set the code owns.

    Three conjuncts, in the paragraph that states the rule. The negation carries
    the direction; ``owns`` is what scopes the ban to sets the code is the
    authority on rather than to every list a spec may contain; and
    ``guard``/``derive`` is the sanctioned escape, without which the rule bans
    the useful list instead of pricing it.
    """
    section = _rule_paragraph(_ENUMERATED_SET_ANCHOR, "code-owned set")
    assert _MUST_NOT_ENUMERATE.search(section), (
        "spec-authoring's '## Feature spec' section no longer states that an "
        "as-built record must *not* enumerate a code-owned set. Term "
        "co-occurrence has no direction — without the negation beside the verb, "
        "a section inviting the enumeration would read the same to this guard."
    )
    lower = section.lower()
    assert "owns" in lower, (
        "the ban must be scoped to a set the *code* owns; unscoped, it forbids "
        "every list an as-built record legitimately carries"
    )
    assert "guard" in lower and re.search(r"\bderiv\w+", lower), (
        "the rule must offer the sanctioned form — pair the list with a guard "
        "that derives the set from the code — or a spec author routes around a "
        "prohibition that leaves the reader nothing"
    )


def test_the_present_tense_quantity_rule_has_a_home() -> None:
    """A present-tense quantity in an as-built record is anchored, derived, or pinned.

    Five assertions over the paragraph the ``quantit*`` anchor resolves, and the
    window is the point: two of them — *a guard that derives*, and the failure
    condition — are satisfied verbatim by the neighbouring code-owned set rule,
    so a section-wide scan would leave those two defending nothing the day this
    rule is deleted. The negation carries the direction: a paragraph that
    *invites* the bare figure reads identically to a guard without it. Each of
    the three sanctioned alternatives is asserted separately, because an
    obligation whose halves die to the same edit hides one behind the other
    (``review-discipline`` → ``references/craft.md``, *Every prose obligation
    needs a pair with separate exclusive killers*).
    """
    para = _rule_paragraph(_QUANTITY_ANCHOR, "present-tense quantity")
    assert _MUST_NOT_STATE.search(para), (
        "spec-authoring's quantity rule no longer states that a present-tense "
        "figure must *not* be stated on its own. Without the negation beside "
        "the verb it governs, a paragraph blessing the bare count would satisfy "
        "every other assertion here."
    )
    assert _MEASURED_AT_A_COMMIT.search(para), (
        "the rule must offer the first sanctioned form — the figure names the "
        "commit it was measured at. Dropping it leaves an author with no way to "
        "record a measurement that was honest when taken."
    )
    assert _A_GUARD_DERIVES.search(para), (
        "the rule must offer the second sanctioned form — a guard that derives "
        "the figure from the tree — or the only compliant record is one that "
        "carries no measured numbers at all."
    )
    assert re.search(r"\bfail\w*", para, re.IGNORECASE), (
        "the derivation alternative must say the guard *fails* when tree and "
        "claim disagree. A guard that derives a number and asserts nothing "
        "about it is the same unmeasured claim with more machinery."
    )
    assert re.search(r"\binvariant\w*", para, re.IGNORECASE), (
        "the rule must offer the third sanctioned form — restate the figure as "
        "the invariant it was evidence for — which is the only alternative "
        "available when the measurement cannot be reproduced."
    )


def test_spec_authoring_version_agrees_with_the_registry() -> None:
    """The skill's stamp and its registry entry move together.

    This pinned both to the literal ``0.10.1`` until #321 — the version #285
    happened to land at. That literal was not the invariant: a *correct* later
    edit to the skill, which must bump both, failed this test, and the only way
    to pass was to retype the new version here, re-arming the trap for the next
    edit. What is durable is the **agreement**: a stamp that drifts from the
    registry entry is how a consuming repo pulls a file whose version says it
    already has it.
    """
    header = re.search(r"guidance:spec-authoring@([\d.]+)", SKILL.read_text())
    entry = re.search(
        r"skills/spec-authoring/SKILL\.md:\s*\{[^}]*version:\s*([\d.]+)",
        REGISTRY.read_text(),
    )
    assert header and entry
    assert header.group(1) == entry.group(1)
