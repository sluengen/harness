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

What this module pins:

* the ``### 2. Integrate`` section and the base-drift paragraph inside it are
  each derived from the file and non-empty — a renamed heading fails loudly here
  rather than leaving the assertions below scanning an empty string;
* the rule sits **inside** that paragraph, not merely somewhere in the file,
  because a reader mid-reconciliation is reading that paragraph;
* the rule names its obligation — detect a collision rather than accept an
  agreement, and advance past both sides;
* the rule names the field class through several instances rather than one, so
  it is not read as being about the one example it gives;
* the rule is generically phrased: it names no artifact filename, proven by a
  predicate with a paired splice into the real rule text as its control.

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
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

_SHIP_REL = "commands/ship.md"
_SHIP = _REPO_ROOT / _SHIP_REL

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


def test_the_integrate_section_resolves() -> None:
    """The section boundaries actually resolved to prose.

    Kept as its own test so a heading rename names itself here, instead of
    emptying the derivation and leaving every assertion below scanning ``""`` —
    the shape where a containment check quietly stops checking anything.
    """
    section = _integrate_section()
    assert section, f"{_SHIP_REL} has no {_SECTION_HEADING!r} section"
    assert "reconcile" in section, (
        f"the {_SECTION_HEADING!r} section no longer describes reconciliation — "
        "the collision rule's home moved, so re-point this module before assuming "
        "the rule is gone"
    )


def test_the_base_drift_paragraph_resolves() -> None:
    """Exactly one paragraph in that section states the base-drift rule."""
    section_paragraphs = _paragraphs(_integrate_section())
    matching = [p for p in section_paragraphs if _PARAGRAPH_ANCHOR in p]
    assert len(matching) == 1, (
        f"expected exactly one paragraph naming {_PARAGRAPH_ANCHOR!r} in "
        f"{_SECTION_HEADING!r}; found {len(matching)} of {len(section_paragraphs)}"
    )


def test_the_sentence_unit_splits_the_real_paragraph() -> None:
    """The splitter divides the real paragraph, and the rule is a part of it.

    The text unit is part of the predicate, so it needs its own killer. A
    splitter that never fires returns the whole paragraph as one sentence, and
    every selection below silently widens to the whole paragraph — which would
    hand the artifact sweep prose this change never wrote. The strict-shortness
    assertion is what separates "selected the rule" from "selected everything".
    """
    paragraph = _base_drift_paragraph()
    assert paragraph, "no base-drift paragraph derived"

    sentences = _sentences(paragraph)
    assert len(sentences) > 1, f"the paragraph did not split: {sentences}"
    squashed = re.sub(r"\s+", "", "".join(sentences))
    assert squashed == re.sub(r"\s+", "", paragraph), (
        "the split dropped or duplicated text — the unit is not covering the paragraph"
    )

    rule = _rule_text()
    assert rule, f"no sentence in the base-drift paragraph names {_RULE_TERM!r}"
    assert len(rule) < len(paragraph), (
        "the rule selection is the whole paragraph — the sentence unit is not "
        "discriminating, so the assertions below measure the paragraph, not the rule"
    )


#: The three load-bearing halves of the rule. "Detect" and "accept" are its
#: polarity — dropping either inverts the instruction — and "advance past both
#: sides" is the action, which is the half a reader cannot re-derive from the
#: hazard. Spelled once, because the positional assertion and the obligation
#: assertion both need them and a phrase spelled twice drifts once.
_OBLIGATION = ("collision to detect", "agreement to accept", "advance past both sides")


def test_the_collision_rule_sits_inside_the_base_drift_paragraph() -> None:
    """The rule lives in the paragraph a reconciler reads, and only there.

    Positional, deliberately. The actor who can catch this defect is whoever is
    executing a reconciliation, and they are reading one paragraph; the same
    sentence under *Preconditions* or in the report section would satisfy a
    file-wide containment and reach nobody at the moment it applies.

    Asserted as *every* occurrence in the file falling inside that paragraph,
    which is what gives this test a killer the obligation assertion below does not
    share. Containment alone cannot have one: the rule is **derived** from the
    paragraph, so a sentence moved out of it stops being the rule and takes the
    obligation assertion down with this one — the same edit killing both, which is
    the shape where two assertions hide each other. A second copy pasted elsewhere
    dies here and nowhere else.

    It is not a cardinality pin: nothing here fixes how many times the phrase
    appears, only that no occurrence sits outside the paragraph. Quoting the rule
    in another section is exactly the drift being refused, not collateral.
    """
    text = _ship_text()
    paragraph = _base_drift_paragraph()
    assert paragraph, "no base-drift paragraph derived"

    strays = {
        phrase: text.count(phrase) - paragraph.count(phrase)
        for phrase in _OBLIGATION
        if text.count(phrase) != paragraph.count(phrase)
    }
    assert not strays, (
        f"the collision rule appears outside the base-drift paragraph: {strays} — "
        "a reconciler reads one paragraph, and a second home is where the two "
        "copies start disagreeing"
    )
    absent = [phrase for phrase in _OBLIGATION if paragraph.count(phrase) == 0]
    assert not absent, (
        f"the base-drift paragraph does not carry {absent} — without this the "
        "equality above is satisfied by the phrase being nowhere at all"
    )


def test_the_collision_rule_names_its_obligation() -> None:
    """The rule states what to do, not only that the hazard exists.

    Three phrases, because a sentence that names the hazard without the
    disposition leaves a reader who agrees with it and does nothing. Read over the
    *derived rule* rather than the paragraph, so the obligation is pinned to the
    sentences this change wrote and not to the paragraph they sit in.
    """
    rule = _rule_text()
    assert rule, "no collision rule derived"
    missing = [phrase for phrase in _OBLIGATION if phrase not in rule]
    assert not missing, f"the base-drift collision rule does not state {missing}"


def test_the_rule_names_the_field_class_by_more_than_one_instance() -> None:
    """The rule names the class through several instances, not one.

    "A monotonic field" read against a single example is read as being about that
    example. The three the assessment wrote span three different mechanisms —
    a released version, a schema ordinal, an allocated id — so a reader
    reconciling a fourth kind recognises it. Pinned by membership rather than by
    count, so adding a fourth is free and dropping one names itself.

    Its own test, because its killer is a wording edit inside the rule's example
    list, which every other assertion here is deliberately blind to.
    """
    rule = _rule_text()
    assert rule, "no collision rule derived"
    missing = [
        instance
        for instance in ("a version number", "a migration ordinal", "a sequence id")
        if instance not in rule
    ]
    assert not missing, (
        f"the rule no longer names {missing} — with one instance left, the class "
        "reads as being about that instance"
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
