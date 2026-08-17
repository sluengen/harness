"""`/ship`'s base-drift rule names the same-valued-monotonic-field collision.

Two branches that independently compute *the next* value of a monotonic field —
a version number, a migration ordinal, a sequence id — produce identical text on
that line, so the merge carries no conflict marker. Identical text is not
agreement: the merged tree is a third state distinct from either side, shipping
under a value both sides already claimed. Every automated signal reads green,
including the one everybody trusts to surface merge risk.

That class was assessed onto ``commands/ship.md`` rather than into the review
craft reference, on the audience test: the defect does not exist inside any
branch diff, only between two trees at merge time, so the actor who can catch it
is whoever executes a reconciliation. This module pins the rule where that actor
reads.

What this module pins, after #459:

* **one tripwire** — the ``### 2. Integrate`` section and its base-drift
  paragraph resolve, the sentence unit discriminates, the rule's term set is
  present, its negation sits beside the noun it governs, and the rule is stated
  only in that paragraph;
* **the artifact sweep and its splice control**, unchanged — the rule is
  generically phrased, naming no source-repo filename, because this command ships
  into consuming repos where such a name is a fact about somebody else's tree.

Six assertions collapsed into the tripwire under #459 (ADR 0016): four were
derivation floors and placement re-checks the tripwire performs in one pass, one
pinned three exact example phrases (``"a version number"``, ``"a migration
ordinal"``, ``"a sequence id"``) — a breadth claim expressed as literals, so any
rewording of the examples broke it while a gutted rule passed — and one pinned
the obligation as three exact clauses. Occurrence the surviving polarity check
cites (``code-quality`` Part C): a term-set predicate over *collision*, *detect*,
*accept* and *advance* is satisfied word for word by prose saying a same-valued
monotonic field is an agreement to accept rather than a collision to detect. The
negation anchored to ``agreement`` is what separates the rule from its inversion;
the ``craft.md`` class is *A guard over prose owns structure and negative space,
never meaning*.

What this module does **not** prove:

* **That the rule is correct, or that anyone obeys it.** It is prose in a
  command document; whether a reconciliation actually checked the field is a
  property of the merge, invisible to the tree.
* **That the artifact predicate is complete.** It keys on a bounded extension
  list, which is a blacklist, and a blacklist has no completion condition — a
  repo fact named without an extension (a bare directory, a symbol) passes. It
  catches the shape the assessment actually rejected, and the control below
  proves it catches that shape rather than nothing.
* **That the wording is generic in meaning.** A sentence can name a source-repo
  fact in plain words with no filename in it at all. Only a reader catches that.
"""

from __future__ import annotations

import re
from collections import Counter

from tests.unit._prose import REPO_ROOT

_SHIP_REL = "commands/ship.md"
_SHIP = REPO_ROOT / _SHIP_REL

#: The section the rule belongs to, and the level its boundaries are drawn at.
_SECTION_HEADING = "### 2. Integrate"

#: The term that identifies the base-drift paragraph inside that section. The
#: paragraph already names itself this way; keying on its own wording is what
#: makes the derivation positional rather than a line number that drifts.
_PARAGRAPH_ANCHOR = "base-drift"

#: The rule's own sentences are the ones naming the field class. Selecting by the
#: term the rule is *about* keeps the artifact sweep off the paragraph's
#: pre-existing prose, which is not this change's to constrain.
_RULE_TERM = "monotonic"

#: A sentence ends at the whitespace after a period, allowing the period to be
#: followed by markdown emphasis or a closing delimiter. Only the whitespace is
#: consumed, so the parts rejoin to the paragraph and
#: :func:`test_the_sentence_unit_splits_the_real_paragraph` can assert that they
#: do — a separator that eats characters shortens the corpus silently, which is
#: the class this whole change is about. Python ``re`` requires each lookbehind
#: branch to be fixed-width, hence the alternation rather than one pattern.
_SENTENCE_BREAK = re.compile(r"(?:(?<=\.)|(?<=\.\*\*)|(?<=\.`)|(?<=\.\)))\s+")

#: Extensions that make a token read as a repo artifact rather than as prose.
_ARTIFACT = re.compile(
    r"\b[\w-]+\.(?:md|ya?ml|json|jsonc|js|mjs|cjs|ts|tsx|py|toml|cfg|ini|sh|txt|lock)\b"
)


def _ship_text() -> str:
    return _SHIP.read_text(encoding="utf-8")


def _integrate_section() -> str:
    """The body between ``### 2. Integrate`` and the next ``### `` heading.

    Returns ``""`` when the heading is absent, so a rename surfaces as an empty
    section the assertions below reject — rather than as a silently empty scan.
    """
    text = _ship_text()
    start = re.search(rf"^{re.escape(_SECTION_HEADING)}\s*$", text, re.MULTILINE)
    if start is None:
        return ""
    rest = text[start.end() :]
    following = re.search(r"^### ", rest, re.MULTILINE)
    return (rest[: following.start()] if following is not None else rest).strip()


def _paragraphs(text: str) -> list[str]:
    return [block.strip() for block in text.split("\n\n") if block.strip()]


def _base_drift_paragraph() -> str:
    """The one paragraph in the Integrate section that states the base-drift rule."""
    matching = [p for p in _paragraphs(_integrate_section()) if _PARAGRAPH_ANCHOR in p]
    return matching[0] if len(matching) == 1 else ""


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_BREAK.split(text) if s.strip()]


def _rule_text() -> str:
    """The sentences of the base-drift paragraph that state the collision rule."""
    return " ".join(s for s in _sentences(_base_drift_paragraph()) if _RULE_TERM in s)


def _artifact_tokens(text: str) -> list[str]:
    """Tokens that read as a repo artifact filename, in order of appearance."""
    return [m.group(0) for m in _ARTIFACT.finditer(text)]


#: The words the rule cannot be stated without. Words, not clauses: how the
#: obligation is phrased is the review gate's business, and the pre-#459 form
#: pinned three exact clauses that any rewording broke.
_RULE_TERMS = ("collision", "detect", "accept", "advance")

#: The negation **anchored to the noun it governs**. This is the whole polarity
#: of the rule: identical text is *not* agreement. A bare ``"not" in rule`` is
#: decoration — almost any English sentence satisfies it — and a term-set check
#: over :data:`_RULE_TERMS` alone passes word for word on the inversion ("treat a
#: same-valued monotonic field as an agreement to accept rather than a collision
#: to detect"). Six words of gap covers every legitimate spelling and stops short
#: of a negation governing something else in the same sentence.
_NOT_AGREEMENT = re.compile(
    r"\b(?:not|never|no|rather than)\b(?:\W+\w+){0,6}?\W+agreement\b", re.IGNORECASE
)


def test_the_collision_rule_is_stated_where_a_reconciler_reads() -> None:
    """The one tripwire: the rule resolves, reads, and lives in one paragraph.

    Four parts, in the order a failure is easiest to read:

    * **anchor** — ``### 2. Integrate`` resolves to prose that still describes
      reconciliation, and exactly one paragraph inside it names ``base-drift``. A
      heading rename names itself here instead of emptying the derivation and
      leaving the artifact sweep below scanning ``""``.
    * **unit** — the sentence splitter divides that paragraph without dropping or
      duplicating text, and the rule it selects is strictly shorter than the
      paragraph. The text unit is part of the predicate, so it needs its own
      killer: a splitter that never fires returns the whole paragraph as one
      sentence and silently widens the artifact sweep to prose this change never
      wrote.
    * **terms** — :data:`_RULE_TERMS` are present in the selected rule.
    * **polarity** — :data:`_NOT_AGREEMENT` fires inside it. Without this the
      three assertions above are all satisfied by the rule's exact inversion.

    **Placement** closes it: ``monotonic`` occurs in ``commands/ship.md`` only
    inside this paragraph. Not a cardinality pin — nothing fixes how many times
    the word appears — only that no occurrence sits outside the paragraph a
    reconciler is actually reading. A second copy under *Preconditions* would
    satisfy a file-wide containment check and reach nobody at the moment it
    applies; it dies here.
    """
    section = _integrate_section()
    assert section, f"{_SHIP_REL} has no {_SECTION_HEADING!r} section"
    assert "reconcile" in section, (
        f"the {_SECTION_HEADING!r} section no longer describes reconciliation — "
        "the collision rule's home moved, so re-point this module before assuming "
        "the rule is gone"
    )

    section_paragraphs = _paragraphs(section)
    matching = [p for p in section_paragraphs if _PARAGRAPH_ANCHOR in p]
    assert len(matching) == 1, (
        f"expected exactly one paragraph naming {_PARAGRAPH_ANCHOR!r} in "
        f"{_SECTION_HEADING!r}; found {len(matching)} of {len(section_paragraphs)}"
    )
    paragraph = matching[0]

    sentences = _sentences(paragraph)
    assert len(sentences) > 1, f"the paragraph did not split: {sentences}"
    assert re.sub(r"\s+", "", "".join(sentences)) == re.sub(r"\s+", "", paragraph), (
        "the split dropped or duplicated text — the unit is not covering the paragraph"
    )

    rule = _rule_text()
    assert rule, f"no sentence in the base-drift paragraph names {_RULE_TERM!r}"
    assert len(rule) < len(paragraph), (
        "the rule selection is the whole paragraph — the sentence unit is not "
        "discriminating, so the assertions below measure the paragraph, not the rule"
    )

    missing = [term for term in _RULE_TERMS if term not in rule.lower()]
    assert not missing, (
        f"the base-drift collision rule no longer states {missing}. A sentence that "
        "names the hazard without the disposition leaves a reader who agrees with "
        "it and does nothing."
    )
    assert _NOT_AGREEMENT.search(rule), (
        "the rule does not say identical text is *not* agreement. Without the "
        "negation beside the noun it governs, the terms above are satisfied word "
        "for word by the opposite instruction — accept the agreement rather than "
        "detect the collision — which is exactly the merge this rule refuses."
    )

    text = _ship_text()
    assert text.count(_RULE_TERM) == paragraph.count(_RULE_TERM) > 0, (
        f"{_RULE_TERM!r} appears in {_SHIP_REL} outside the base-drift paragraph — "
        "a reconciler reads one paragraph, and a second home is where the two "
        "copies start disagreeing"
    )


def test_the_artifact_predicate_catches_a_spliced_filename() -> None:
    """The control: the predicate flags an artifact spliced into the real rule.

    Spliced into the *rule's own text* rather than judged over a standalone
    sample, so this cannot pass while the derivation above points at the wrong
    span — a control that passes on text the real assertion never reads proves
    only that the regex compiles. Two shapes, because a single one would leave a
    one-extension predicate reading as a general one.

    The splice point is **derived** — the midpoint word boundary — rather than a
    phrase lifted from the rule, and the verdict is the **difference** the splice
    makes rather than the absolute token set. Both were measured, not assumed:
    with a phrase anchor, an edit adding a filename to that very phrase moved the
    anchor and killed this control alongside the real assertion; with an absolute
    equality, the same edit killed it again because the rule now carried a token
    of its own. Either way the control and the assertion it backs died to one
    edit, which is the shape where two assertions hide each other. The difference
    form leaves this control green on a leak and lets the leak assertion report
    it alone.
    """
    rule = _rule_text()
    assert rule, "no collision rule derived"
    words = rule.split(" ")
    assert len(words) > 4, f"the rule is too short to splice into: {rule!r}"
    midpoint = len(words) // 2
    for artifact in ("registry.yaml", "hooks/guidance-freshness.js"):
        spliced = " ".join([*words[:midpoint], artifact, *words[midpoint:]])
        added = Counter(_artifact_tokens(spliced)) - Counter(_artifact_tokens(rule))
        assert added == Counter([artifact.rsplit("/", 1)[-1]]), (
            f"splicing {artifact!r} into the real rule adds {dict(added)} to what "
            "the predicate sees — it does not recognise that shape"
        )


def test_the_collision_rule_names_no_artifact() -> None:
    """The rule is generically phrased — no source-repo filename in it.

    ``commands/ship.md`` is installed into consuming repos, where a source-repo
    artifact is a fact about somebody else's tree. The worked example that
    surfaced this class was a specific file; the assessment rejected naming it,
    so the generic phrasing is the decision and this is its killer.
    """
    rule = _rule_text()
    assert rule, "no collision rule derived"
    found = _artifact_tokens(rule)
    assert not found, (
        f"the base-drift collision rule names artifact(s) {found} — this command "
        "ships into consuming repos, so the rule must name the field class, never "
        "a file that carries one here"
    )
