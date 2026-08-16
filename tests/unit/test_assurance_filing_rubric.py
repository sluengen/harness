"""#354 — assurance is chosen once, at filing, and every filing surface delegates.

`harness/assurance.py` (#352) answered *"given a level, what must this run pay
for?"* — labels in, required stages out. Nothing answered the other direction:
*"given this work, which level does the filer put on it?"*. Every ticket since
#352 nevertheless carries a level, applied out of an operator's head — which is
the state that drifts.

**#435 restored this module after the package it imported went.** Its whole
filing-time subject survives verbatim, so the only edit was to write the level
vocabulary here rather than import it. Claims about the deleted package stay in
the past tense; they are why these assertions are shaped the way they are.

This ticket puts that second answer in exactly one place (``spec-authoring`` →
*Choosing assurance*), makes assurance a mandatory input **and** postcondition of
the ``create`` contract, and has every filing surface point at it.

This module owns the **rubric**: that it exists in one place, that its two
load-bearing rules are stated with the right polarity and quantifier and are not
restated anywhere else, and that the ``create`` contract makes a level mandatory
without saying which one. Its companion,
:mod:`tests.unit.test_assurance_filing_surfaces`, owns the **reach** — the files
that file an issue, their pointers, the provider recipes, and version parity —
and imports every predicate from here rather than re-implementing one.

**What these two files measure, and what they deliberately do not.**

* AC-5a (ambiguous / missing / conflicting → ``simple``) was *runtime* behaviour,
  measured against ``resolve_assurance``; both went with the package in #435.
  Nothing here replaces it — the fail-safe was a property of code that no longer
  runs. What survives is the filing-time rule that made it rarely necessary: R1
  below, *uncertain is* ``simple``.
* AC-1 (the three labels exist, with descriptions distinguishing lifecycle
  assurance from engine/model choice) has no honest test: its subject lives on
  the tracker, not in the tree, and a guard for it would hard-code this repo's
  backend and label ids into a *distributed* surface. It is re-measured with
  ``gh label list``.

**Craft.** Every rule assertion is paired — the rule is *stated*, and its
*inversion* is absent across the registered tree — because a substring guard over
prose is blind to polarity (#399). Every predicate is a named function called by
the real-tree assertion **and** by its controls (#179/#327). Every derived set
carries a floor that is non-empty, names known members, and discriminates. The
level vocabulary has one home here and every predicate derives from it, so a
fourth level is covered the day it is added.

**The pairing rests on two things below it, and both were once the defect.** A
polarity predicate asks *"does this unit say the opposite?"*, so it is only as
honest as what counts as a **unit** (:func:`_sentences` — a rule ending inside
emphasis merged with the sentence contradicting it and lent it the rule's own
``Never``) and what each polarity token is **anchored to**
(:data:`_NEGATED_INFERENCE`, :func:`_levels_chosen` — a negation forbids the verb
it governs, not the whole sentence). Clean standalone samples cannot fail for
either reason, so the unit-boundary test splices each inversion into the **real**
rubric instead.

**Section-scoped, not file-scoped.** Two strings already in the pre-change tree
make the naive file-wide predicates vacuous on arrival: ``spec-authoring``
already contains *"exactly one home"*, and ``commands/build.md`` already contains
*"carries exactly one assurance value"*. Every quantifier assertion below is
therefore scoped to the section or instruction that **is** the rule.
"""

# size: over the ceiling on the shared prose-predicate primitives re-homed here
# by #435, which are ~90 lines of recorded measurement — which escape each
# negation anchor still misses, and what each emphasis half was measured letting
# through — attached to five short definitions. Splitting the primitives from
# `_sentences`/`_section` would fork the unit boundary every polarity predicate
# in this tree is anchored on, which is the one thing that must not have two
# renderings.
from __future__ import annotations

import re
from pathlib import Path

import pytest

# The registered-surface derivation has exactly one home in the suite; #327's
# guard owns it and its own floor asserts it parses ≥ 25 files. Re-deriving it
# here would be a second copy of the definition of "distributed", which is the
# duplication `code-quality` → *grep before writing a helper* forbids.
from tests.unit.test_tracker_neutral_lifecycle import _registered_surface

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY = _REPO_ROOT / "registry.yaml"

#: The assurance vocabulary — its one remaining home. Imported from
#: ``harness.assurance`` until #435 deleted the package; ADR 0015 keeps the
#: levels and the namespace, which are tracker labels a filer applies rather
#: than runtime machinery. The floor below pins the decided set.
ASSURANCE_LEVELS = ("trivial", "simple", "complex")
ASSURANCE_LABEL_PREFIX = "assurance:"

#: The one home of the filing-time rubric.
_RUBRIC_HOME = "skills/spec-authoring/SKILL.md"
#: The rubric's subsection title — what a pointer has to name to be a pointer.
_RUBRIC_SECTION_TITLE = "Choosing assurance"
#: The backend-neutral contract that carries assurance as input and postcondition.
_TRACKER_SKILL = "skills/tracker/SKILL.md"
_TRACKER_CREATE_SECTION = "### `create` contract"
_GITHUB_SKILL = "skills/github-issues/SKILL.md"
_LINEAR_SKILL = "skills/linear/SKILL.md"


def _read(rel: str) -> str:
    return (_REPO_ROOT / rel).read_text(encoding="utf-8")


def _registered_markdown() -> list[str]:
    """Every registered `.md` file, as repo-relative posix paths."""
    return [p.as_posix() for p in _registered_surface()]


def _sentences(text: str) -> list[str]:
    """``text`` split into sentences, each with its internal wrapping normalized.

    Prose in this tree is hard-wrapped, so a rule routinely spans two source
    lines. Normalizing inside the sentence is what lets a predicate anchor on a
    phrase (*"a small estimated diff alone"*) rather than on a line break.

    **The closing emphasis is part of the boundary.** This tree bolds its
    load-bearing rules, so a sentence ends ``…diff alone.**`` — a ``*``, not a
    ``.``, before the space. A splitter looking one character back never fires
    there, and the rule merges with everything after it. That is not cosmetic:
    every polarity predicate below asks *"is there a negation in this unit"*, so
    a merged unit lends a rule's own ``Never`` to the sentence contradicting it.
    Closing ``*``, ``_``, backtick, ``)`` and ``]`` are therefore consumed first.
    """
    return [
        " ".join(s.split()) for s in re.split(r"(?<=[.!?])[*_`)\]]*\s+|\n\n", text) if s.strip()
    ]


def _section(text: str, header: str) -> str:
    """The body of ``header``, from the header line to the next heading of its level or above."""
    match = re.search(rf"^{re.escape(header)}\s*$", text, re.MULTILINE)
    assert match, f"missing section header {header!r}"
    level = len(header) - len(header.lstrip("#"))
    rest = text[match.end() :]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


# ---------------------------------------------------------------------------
# The vocabulary, derived from the policy module rather than typed
#
# #459 removed ``test_the_level_vocabulary_is_populated`` from here. It asserted
# that ``ASSURANCE_LEVELS`` is non-empty and contains ``complex``, and that
# ``ASSURANCE_LABEL_PREFIX`` ends in a colon — all three over literals declared
# a few dozen lines above it in this same module. No edit to the guidance tree
# these guards read can make it fail; only an edit to this file can, and the
# author of that edit is holding the assertion in the same diff. That is the
# constant-asserting-on-itself shape ADR 0016 names, and it is not a floor: it
# never observed the subject.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# AC-2 — every filing surface points at the one rubric
# ---------------------------------------------------------------------------

#: A pointer names **both** the rubric's home skill and its subsection. Naming
#: the skill alone is not enough: `commands/start.md` and `commands/propose.md`
#: both already name `spec-authoring` in prose that says nothing about choosing
#: a level, so a bare-skill check passes on the pre-change tree.
_POINTS_AT_THE_RUBRIC = re.compile(
    rf"`spec-authoring`[^.]{{0,120}}?{_RUBRIC_SECTION_TITLE}"
    rf"|{_RUBRIC_SECTION_TITLE}[^.]{{0,120}}?`spec-authoring`",
    re.IGNORECASE,
)


def _delegates_the_level_choice(unit: str) -> bool:
    """Does this instruction delegate the level choice to the rubric's one home?"""
    return bool(_POINTS_AT_THE_RUBRIC.search(unit))


# ---------------------------------------------------------------------------
# AC-2 / AC-5b — the rubric, its two load-bearing rules, and their polarity
# ---------------------------------------------------------------------------

_UNIVERSAL_NEGATION = re.compile(r"\bnever\b|\bmust not\b|\bmay not\b|\bcannot\b", re.IGNORECASE)
_INFERS = re.compile(r"\binfer\w*\b", re.IGNORECASE)
#: R2's negation, **anchored to the verb it governs**. A sentence-wide "is there
#: a negation anywhere?" test — `_UNIVERSAL_NEGATION` alone — cannot tell a
#: prohibition from a permission whose subordinate clause carries an unrelated
#: `cannot` (*"a filer who **cannot** reach the certification command **may
#: infer** `trivial` from …"*) — a permission wearing a prohibition's tokens.
#: Every legitimate spelling keeps negation and verb within two words ("never
#: infer", "must not infer", "may never be inferred"); a negation further off
#: governs something else. The bound is deliberately tight: a rephrasing that
#: separates them fails loudly, where the loose form failed silently open.
_NEGATED_INFERENCE = re.compile(
    r"\b(?:never|must not|may not|cannot|can not|do(?:es)? not|is not|are not)\b"
    r"(?:\s+\w+){0,2}\s+infer\w*\b",
    re.IGNORECASE,
)
_TRIVIAL = re.compile(r"\btrivial\b", re.IGNORECASE)
_ALONE = re.compile(r"\balone\b", re.IGNORECASE)
#: The properties of a ticket's *text* — every one of them authored by whoever
#: filed it, which is what makes R2 a security rule rather than a style rule.
#: ``severity`` was the first of the three until #455: the grade scale was
#: retired for the blocking×size 2×2, so a ticket has no severity to read and the
#: property it stood for — *the ticket saying the work is small* — is now spelled
#: as the filer's own claim of minorness. The rule, its arity, and its polarity
#: are unchanged; only the name of one author-controlled property moved.
_TEXT_PROPERTIES = ("minor", "description", "diff")


def _names_text_properties(sentence: str) -> int:
    return sum(1 for noun in _TEXT_PROPERTIES if re.search(rf"\b{noun}\w*\b", sentence, re.I))


def _states_the_trivial_inference_ban(text: str) -> list[str]:
    """Sentences forbidding inference of ``trivial`` from ticket-text properties.

    R2. Requires **all** of: a negation governing the inference verb, the level
    ``trivial``, at least two of the text properties, and the quantifier
    ``alone``. The quantifier is a conjunct on purpose — dropping it turns a
    correct rule ("these three are never *sufficient*") into a false one ("these
    three may never be *considered*"), and a guard blind to the difference is the
    substring-over-prose failure #399 cost a tick.
    """
    return [
        sentence
        for sentence in _sentences(text)
        if _NEGATED_INFERENCE.search(sentence)
        and _TRIVIAL.search(sentence)
        and _ALONE.search(sentence)
        and _names_text_properties(sentence) >= 2
    ]


def _permits_trivial_inference(text: str) -> list[str]:
    """The **inverted** rule: the same subject with the negation gone.

    Deliberately not "a permissive modal is present": the cheapest way to lose
    this rule is to drop the negation, not to replace it with *may*. Any sentence
    relating ``trivial`` to two or more author-controlled text properties, whose
    inference verb is **not itself negated** (``_NEGATED_INFERENCE`` — not merely
    "carries no negation"), permits the exploit R2 forbids. Exact complement of
    the predicate above over the same subject, so nothing slips between them.
    """
    return [
        sentence
        for sentence in _sentences(text)
        if _INFERS.search(sentence)
        and _TRIVIAL.search(sentence)
        and _names_text_properties(sentence) >= 2
        and not _NEGATED_INFERENCE.search(sentence)
    ]


_UNCERTAINTY = re.compile(
    r"\buncertain\w*\b|\bunsure\b|\bambiguous\w*\b|\bcannot place\b|\bin doubt\b", re.IGNORECASE
)
#: A choice verb and the level it points at, within two words — R1's destination
#: anchored as R2's negation is (``_NEGATED_INFERENCE``). "Does the sentence
#: contain `simple`?" cannot tell *choosing* it from *mentioning* it, so an
#: inversion phrased as a contrast (*"chooses `complex` rather than `simple`"*)
#: satisfies a sentence-wide shield while stating the rule's opposite. The level
#: vocabulary is imported, so a fourth level is anchored the day it exists.
_CHOICE_OF_LEVEL = re.compile(
    r"\b(?:choos\w*|chose\w*|pick\w*|default\w*|is|are|remains?|stays?)\b"
    r"(?:\s+\w+){0,2}?\s+`?(?P<level>\w+)`?",
    re.IGNORECASE,
)


def _levels_chosen(sentence: str) -> set[str]:
    """The assurance levels a choice verb in ``sentence`` points at.

    Empty when the sentence names levels but chooses none — the common, correct
    case in prose discussing the vocabulary rather than applying it.
    """
    return {
        match.group("level").lower()
        for match in _CHOICE_OF_LEVEL.finditer(sentence)
        if match.group("level").lower() in ASSURANCE_LEVELS
    }


def _routes_uncertainty_to_simple(text: str) -> list[str]:
    """R1. Sentences making ``simple`` the answer when the filer cannot place the work."""
    return [
        sentence
        for sentence in _sentences(text)
        if _UNCERTAINTY.search(sentence) and "simple" in _levels_chosen(sentence)
    ]


def _routes_uncertainty_away_from_simple(text: str) -> list[str]:
    """The **inverted** R1: uncertainty sent to any level other than ``simple``.

    Complementary to the presence predicate over the *chosen* level rather than
    the mentioned one, so a sentence routing uncertain work to ``complex`` while
    naming ``simple`` in a contrasting clause is an offender here, and not a
    statement of R1 there.
    """
    return [
        sentence
        for sentence in _sentences(text)
        if _UNCERTAINTY.search(sentence) and (_levels_chosen(sentence) - {"simple"})
    ]


def _rubric() -> str:
    """The rubric subsection of the one home."""
    return _section(_read(_RUBRIC_HOME), f"### {_RUBRIC_SECTION_TITLE}")


def test_the_rubric_has_a_home() -> None:
    """AC-2: the one canonical rubric exists, as a named subsection of the craft skill."""
    text = _read(_RUBRIC_HOME)
    assert re.search(rf"^### {re.escape(_RUBRIC_SECTION_TITLE)}\s*$", text, re.MULTILINE), (
        f"{_RUBRIC_HOME} has no `### {_RUBRIC_SECTION_TITLE}` subsection — the "
        f"filing-time rubric has nowhere to live, and every pointer written for "
        f"AC-2 points at nothing (#354 AC-2)."
    )


def test_the_rubric_names_exactly_the_decided_levels() -> None:
    """The rubric's vocabulary is the decided one, derived rather than re-typed.

    A rubric that named two of three levels, or invented a fourth, would send a
    filer to apply a label the tracker has no taxonomy row for — and an
    unrecognized level reads to a reviewer as no level at all.
    """
    named = {
        match.group(1)
        for match in re.finditer(r"`(\w+)`", _rubric())
        if match.group(1) in ASSURANCE_LEVELS
    }
    assert named == set(ASSURANCE_LEVELS), (
        f"the rubric names {sorted(named)}; the decided vocabulary is "
        f"{sorted(ASSURANCE_LEVELS)} (#354 AC-2)."
    )


def test_the_rubric_disclaims_the_runtime_direction() -> None:
    """The boundary that stops the rubric being read as a copy of the policy module.

    The rubric answers *work → level*; the other direction — *level → required
    stages* — is what ``commands/build.md`` reads to decide which stages a run
    pays for. Without a sentence saying so, the next author to touch either one
    has no way to tell which of the two they are editing, and the required-stages
    mapping grows a second home inside the rubric.
    """
    rubric = " ".join(_rubric().split())
    assert re.search(r"\bstages?\b", rubric, re.IGNORECASE), (
        "the rubric must name the other direction (required stages) to disclaim it"
    )
    assert re.search(r"\bnot this rubric'?s\b|\bnot this skill'?s\b", rubric, re.IGNORECASE), (
        "the rubric must say the required-stages mapping is not its decision — "
        "otherwise the two homes read as two copies (#354 AC-2)."
    )


def test_the_rubric_states_the_trivial_inference_ban() -> None:
    """AC-5b: R2 is stated, with its negation and its quantifier."""
    stated = _states_the_trivial_inference_ban(_read(_RUBRIC_HOME))
    assert stated, (
        f"{_RUBRIC_HOME} does not forbid inferring `trivial` from a ticket's own "
        f"text. All three properties — a claim of minorness, the description, the "
        f"estimated diff size — are authored by whoever filed the issue, so a "
        f"rubric without this rule lets a ticket argue its way down (#354 AC-5b)."
    )


def test_the_trivial_inference_ban_has_exactly_one_home() -> None:
    """AC-2: R2 is stated in the rubric and **nowhere else**.

    Exclusivity is the right assertion for R2 and the wrong one for R1: R2 is a
    filing-time rule with nothing downstream of it, while R1 (*uncertain →
    simple*) legitimately has a counterpart — ``commands/build.md`` states the
    run-time form of the same default. Writing exclusivity for both out of
    symmetry would fail on correct prose.
    """
    homes = {rel for rel in _registered_markdown() if _states_the_trivial_inference_ban(_read(rel))}
    assert homes == {_RUBRIC_HOME}, (
        f"the trivial-inference ban is stated in {sorted(homes)}; it belongs in "
        f"{_RUBRIC_HOME} alone. A second copy agrees with the first the day it is "
        f"written and drifts later (#354 AC-2)."
    )


@pytest.mark.parametrize("rel", _registered_markdown(), ids=lambda r: r)
def test_no_registered_document_permits_inferring_trivial(rel: str) -> None:
    """AC-5b, the inversion: no distributed file relates ``trivial`` to a ticket's
    own text without forbidding it.

    Deleting a rule is the mutation everyone tests for. Inverting one — *never*
    to *sometimes*, or the negation simply dropped — leaves a paragraph that
    still names every noun the presence check looks for, and reads green (#399).
    This sweep is only as honest as its unit boundary and its anchoring, both of
    which have been the defect here; the module docstring says why, and
    ``test_the_rule_predicates_read_the_real_rubrics_unit_boundaries`` measures
    both against the real rubric.
    """
    offenders = _permits_trivial_inference(_read(rel))
    assert not offenders, (
        f"{rel} permits inferring `trivial` from properties of a ticket's own "
        f"text: {offenders}. Those properties are author-controlled, so this is "
        f"the injection surface R2 exists to close (#354 AC-5b)."
    )


def test_the_rubric_routes_uncertainty_to_simple() -> None:
    """AC-5b / R1: the filer who cannot place the work chooses ``simple``.

    Presence only — see the asymmetry documented on the exclusivity test above.
    """
    stated = _routes_uncertainty_to_simple(_read(_RUBRIC_HOME))
    assert stated, (
        f"{_RUBRIC_HOME} does not say that uncertain work is `simple`. Guessing "
        f"high costs one design pass; guessing low costs the review that would "
        f"have caught the guess (#354 AC-5b)."
    )


@pytest.mark.parametrize("rel", _registered_markdown(), ids=lambda r: r)
def test_no_registered_document_routes_uncertainty_away_from_simple(rel: str) -> None:
    """R1's inversion: uncertainty must never be sent to a level other than ``simple``."""
    offenders = _routes_uncertainty_away_from_simple(_read(rel))
    assert not offenders, (
        f"{rel} sends uncertain work somewhere other than `simple`: {offenders}. "
        f"Both homes of the assurance decision fail toward *more* verification "
        f"(#354 AC-5b)."
    )


def test_the_rubric_rule_predicates_discriminate() -> None:
    """The controls, through the same predicates the tree assertions call.

    Four samples per rule, and the pairs are what make the polarity claim real: a
    predicate that fired on all four, or on none, would leave both the presence
    and the absence assertions above passing for the wrong reason.
    """
    banned = (
        "**Never infer `trivial` from a ticket calling the work minor, a short "
        "description, or a small estimated diff alone.**"
    )
    assert _states_the_trivial_inference_ban(banned) == [banned]
    assert _permits_trivial_inference(banned) == []

    # The inversion: same subject, same nouns, negation replaced.
    permitted = (
        "A filer may sometimes infer `trivial` from a ticket calling the work "
        "minor, a short description, or a small estimated diff alone."
    )
    assert _permits_trivial_inference(permitted) == [permitted]
    assert _states_the_trivial_inference_ban(permitted) == []

    # The quantifier, dropped: a *different*, absolute rule, and not R2.
    without_alone = (
        "Never infer `trivial` from a ticket calling the work minor, a short "
        "description, or a small estimated diff."
    )
    assert _states_the_trivial_inference_ban(without_alone) == [], (
        "the ban predicate cannot see the `alone` quantifier — it would accept an "
        "absolute rule in place of the sufficiency rule R2 states (#399)."
    )

    # A single noun is not the rule: `trivial` is legitimately related to the
    # certified *diff* all over the tree, and flagging that would forbid the
    # truthful sentence.
    one_noun = "`trivial` is earned only when the certification command measures the real diff."
    assert _permits_trivial_inference(one_noun) == []

    # The negation must **govern the inference verb**, not merely share a
    # sentence with it: an unrelated `cannot` in a subordinate clause is a
    # permission wearing a prohibition's tokens.
    shielded = (
        "A filer who cannot reach the certification command may infer `trivial` from "
        "a ticket calling the work minor, a short description, or a small "
        "estimated diff alone."
    )
    assert _permits_trivial_inference(shielded) == [shielded], (
        "an unrelated `cannot` shields a permission — the negation is not "
        "anchored to the verb it is supposed to forbid."
    )
    assert _states_the_trivial_inference_ban(shielded) == [], (
        "the ban predicate accepts a sentence whose negation forbids something "
        "else — it would count that sentence as a home for R2."
    )

    uncertain = "A filer who cannot place the work confidently chooses `simple`, always."
    assert _routes_uncertainty_to_simple(uncertain) == [uncertain]
    assert _routes_uncertainty_away_from_simple(uncertain) == []

    inverted = "A filer who is unsure chooses `complex`, always."
    assert _routes_uncertainty_away_from_simple(inverted) == [inverted]
    assert _routes_uncertainty_to_simple(inverted) == []

    # R1's destination is anchored to the choice verb for the same reason: an
    # inversion that names both levels — how a real edit would phrase it — passes
    # a shield that only knows `simple` appears somewhere.
    contrasted = "A filer who is unsure chooses `complex` rather than `simple`."
    assert _routes_uncertainty_away_from_simple(contrasted) == [contrasted], (
        "naming `simple` anywhere shields an inversion — the destination is not "
        "anchored to the verb that chooses it."
    )
    assert _routes_uncertainty_to_simple(contrasted) == [], (
        "R1's presence check counts a sentence routing uncertainty *away* from "
        "`simple` as a statement of R1 — it reads the contrast, not the choice."
    )


def test_the_rule_predicates_read_the_real_rubrics_unit_boundaries() -> None:
    """The controls above are blind to the boundary; these splice into the real text.

    Every sample in ``test_the_rubric_rule_predicates_discriminate`` is a
    standalone, already-clean sentence, so that test can only fail for a defect
    in a predicate's *tokens*. The sweeps it certifies never see such sentences:
    they run :func:`_sentences` over a whole markdown file, where a rule ending
    inside emphasis (``…diff alone.**``) merged with everything after it and lent
    its ``Never`` to prose contradicting it. These splice each inversion into the
    **real** rubric and sweep it with the functions the tree assertions call.
    """
    rubric = _rubric()

    # R2's inversion, where the merge used to hide it: immediately after the
    # bolded ban it contradicts, carrying no negation of its own.
    ban = "estimated diff alone.**"
    assert ban in rubric, "the bolded R2 sentence moved — re-anchor this control"
    drifted = rubric.replace(
        ban,
        ban + " Where the certification command is unavailable, a filer may infer "
        "`trivial` from a ticket calling the work minor, a short description, or "
        "a small estimated diff alone.",
    )
    assert _permits_trivial_inference(drifted), (
        "an exception appended to R2 is invisible to the tree-wide sweep — the "
        "bolded rule and the sentence contradicting it are being read as one unit, "
        "so R2's own `Never` suppresses the predicate over prose that guts it."
    )

    # R1 inverted outright, then inverted as a contrast — how an edit meaning to
    # keep the rule readable would write it, and the shape a sentence-wide
    # `simple` shield misses. Only the **inversion** sweep is asserted: the
    # bolded lead *"Uncertain is `simple`."* states R1 correctly on its own, so
    # presence legitimately still fires. That is what the pairing is for.
    for flipped in ("chooses `complex`, always", "chooses `complex` rather than `simple`, always"):
        routed = rubric.replace("chooses `simple`, always", flipped)
        assert routed != rubric, "R1's clause moved — re-anchor this control"
        assert _routes_uncertainty_away_from_simple(routed), (
            f"R1 inverted to {flipped!r} is invisible to the tree-wide sweep — the "
            f"bolded lead's `simple` is being read as part of the same unit, "
            f"suppressing the inversion predicate."
        )


# ---------------------------------------------------------------------------
# AC-6 — assurance is an input and a postcondition of `create`, with a failure shape
# ---------------------------------------------------------------------------

_ASSURANCE = re.compile(r"\bassurance\b", re.IGNORECASE)
#: The quantifier, **anchored to the noun it governs**. A bare `exactly one`
#: check would be satisfied by any of the four unrelated "exactly one"s already
#: in the tree; a sentence-wide conjunction with `assurance` would be satisfied
#: by a sentence that pins the count of something else entirely.
_EXACTLY_ONE = re.compile(
    r"\bexactly one\b[^.]{0,40}?\bassurance\b|\bassurance\b[^.]{0,80}?\bexactly one\b",
    re.IGNORECASE,
)
#: The quantifiers that would make a partial filing legal — anchored the same
#: way, and for a second reason: the contract's input sentence legitimately says
#: *optional labels or priority*, so a sentence-wide `optional` ban would forbid
#: the correct prose rather than the weakened prose.
_WEAKENED_QUANTIFIER = re.compile(
    r"\b(?:at least one|one or more)\b[^.]{0,40}?\bassurance\b"
    r"|\b(?:optional|where possible|if available)\b[^.]{0,20}?\bassurance\b"
    r"|\bassurance\b[^.]{0,40}?\b(?:is|are|remains?)\s+optional\b",
    re.IGNORECASE,
)
_QUEUE_READY = re.compile(r"queue[- ]ready", re.IGNORECASE)


def _create_contract() -> str:
    return _section(_read(_TRACKER_SKILL), _TRACKER_CREATE_SECTION)


def _states_assurance_as_create_input(text: str) -> list[str]:
    """Sentences declaring what ``create`` takes, that name assurance among it."""
    return [
        sentence
        for sentence in _sentences(text)
        if re.search(r"\binput is\b", sentence, re.IGNORECASE) and _ASSURANCE.search(sentence)
    ]


def _requires_exactly_one_assurance(text: str) -> list[str]:
    """Sentences pinning the assurance-label count at exactly one."""
    return [sentence for sentence in _sentences(text) if _EXACTLY_ONE.search(sentence)]


def _permits_partial_assurance(text: str) -> list[str]:
    """The **inversion**: a weakened quantifier on the assurance label."""
    return [sentence for sentence in _sentences(text) if _WEAKENED_QUANTIFIER.search(sentence)]


def _refuses_a_queue_ready_identifier(text: str) -> list[str]:
    """Sentences refusing a queue-ready result when the label could not be applied."""
    return [
        sentence
        for sentence in _sentences(text)
        if _QUEUE_READY.search(sentence) and _UNIVERSAL_NEGATION.search(sentence)
    ]


def _permits_a_queue_ready_identifier(text: str) -> list[str]:
    """The **inversion**: a queue-ready identifier returned anyway."""
    return [
        sentence
        for sentence in _sentences(text)
        if _QUEUE_READY.search(sentence) and not _UNIVERSAL_NEGATION.search(sentence)
    ]


def _states_an_incomplete_filing(text: str) -> list[str]:
    """Sentences naming the incomplete-filing outcome and what to do with it.

    AC-6's failure shape has to reach the **provider**, not only the protocol.
    The protocol can say a filing is incomplete all it likes; the recipe an agent
    actually follows is where the behaviour either happens or does not. Both
    provider skills are checked with this one predicate, and the surfaces module
    imports it rather than re-spelling it per backend.
    """
    return [
        sentence
        for sentence in _sentences(text)
        if re.search(r"\bincomplete\b", sentence, re.IGNORECASE)
        and re.search(r"\bstop\b|\bidentifier\b|\bURL\b", sentence, re.IGNORECASE)
    ]


def test_the_create_contract_takes_assurance_as_an_input() -> None:
    """AC-6: assurance is declared alongside the body file and Todo placement."""
    stated = _states_assurance_as_create_input(_create_contract())
    assert stated, (
        f"{_TRACKER_SKILL} → {_TRACKER_CREATE_SECTION} does not name assurance "
        f"among `create`'s inputs. A postcondition with no input is a rule the "
        f"caller has no way to satisfy (#354 AC-6)."
    )


def test_the_create_contract_requires_exactly_one_assurance_label() -> None:
    """AC-6: the quantifier is pinned, and pinned inside the section that is the rule.

    Section-scoped because ``commands/build.md`` already carries *"exactly one
    assurance value"* — a file-wide or tree-wide check on that phrase is
    satisfied by the pre-change tree.
    """
    section = _create_contract()
    assert _requires_exactly_one_assurance(section), (
        f"{_TRACKER_SKILL} → {_TRACKER_CREATE_SECTION} does not require exactly "
        f"one assurance label on a created issue (#354 AC-6)."
    )
    assert not _permits_partial_assurance(section), (
        f"the `create` contract weakens the assurance quantifier: "
        f"{_permits_partial_assurance(section)}. Two labels fail safe to `simple` "
        f"at runtime, so a weakened contract loses the filer's choice silently "
        f"(#354 AC-6)."
    )


def test_the_create_contract_refuses_a_queue_ready_identifier_without_the_label() -> None:
    """AC-6: the failure shape — incomplete, never queue-ready.

    Paired: the refusal is stated, and its inversion is absent. The queue's
    readers act on what a ticket says about itself, so a filing reported as
    successful without a level is picked up as though it had been classified.
    """
    section = _create_contract()
    assert _refuses_a_queue_ready_identifier(section), (
        f"{_TRACKER_SKILL} → {_TRACKER_CREATE_SECTION} does not refuse a "
        f"queue-ready identifier for a filing that could not carry exactly one "
        f"assurance label (#354 AC-6)."
    )
    assert not _permits_a_queue_ready_identifier(section), (
        f"the `create` contract permits returning a queue-ready identifier "
        f"anyway: {_permits_a_queue_ready_identifier(section)} (#354 AC-6)."
    )


def test_the_create_contract_predicates_discriminate() -> None:
    """The controls, through the same predicates the section assertions call."""
    input_sentence = (
        "Input is a title, a UTF-8 body file, exactly one assurance level, optional "
        "labels or priority, and mandatory initial Todo placement."
    )
    assert _states_assurance_as_create_input(input_sentence) == [input_sentence]
    assert _requires_exactly_one_assurance(input_sentence) == [input_sentence]

    weakened = "A created issue carries at least one recognized assurance label."
    assert _permits_partial_assurance(weakened) == [weakened]
    assert _requires_exactly_one_assurance(weakened) == []

    refusal = "It never returns a queue-ready identifier."
    assert _refuses_a_queue_ready_identifier(refusal) == [refusal]
    assert _permits_a_queue_ready_identifier(refusal) == []

    inverted = "It may return a queue-ready identifier."
    assert _permits_a_queue_ready_identifier(inverted) == [inverted]
    assert _refuses_a_queue_ready_identifier(inverted) == []

    incomplete = "That is an incomplete filing: report the identifier and URL, and stop."
    assert _states_an_incomplete_filing(incomplete) == [incomplete]
    # Discrimination: naming the word without saying what to do with it is not
    # the rule — the outcome is what an agent acts on.
    assert _states_an_incomplete_filing("An incomplete taxonomy is a separate problem.") == []

    # Discrimination: an input sentence that names no assurance is not the rule.
    pre_change = (
        "Input is a title, a UTF-8 body file, optional labels or priority, and "
        "mandatory initial Todo placement."
    )
    assert _states_assurance_as_create_input(pre_change) == []

    # ...and the quantifier is anchored to the noun it governs. The correct
    # contract calls *labels and priority* optional in the same breath as it
    # makes assurance mandatory, so a sentence-wide `optional` ban would flag the
    # prose this ticket is trying to write. Both directions are asserted, because
    # an anchor loose enough to be useless and one tight enough to be blind fail
    # on opposite samples.
    assert _permits_partial_assurance(input_sentence) == [], (
        "the weakened-quantifier predicate flags the correct input sentence — it "
        "is reading `optional labels or priority`, not a weakened assurance rule."
    )
    assert _permits_partial_assurance("Applying an assurance label is optional.") == [
        "Applying an assurance label is optional."
    ]

    # The Linear taxonomy states the quantifier the other way round, so the
    # `exactly one` anchor has to read in both directions.
    table_row = "| Assurance | `assurance:trivial`, `assurance:simple` | Exactly one, always |"
    assert _requires_exactly_one_assurance(table_row) == [table_row]


def test_the_create_contract_carries_no_classification_criteria() -> None:
    """The contract requires that a level was chosen; it never says which.

    The `create` contract is read by both providers and by every filing surface.
    A criterion written here is a second rubric with a wider audience than the
    first — which is the drift this ticket closes, arriving through the door
    marked "just one clarifying sentence".
    """
    section = _create_contract()
    assert not _states_the_trivial_inference_ban(section), (
        "the `create` contract restates the rubric's R2 — point at "
        f"`spec-authoring` → *{_RUBRIC_SECTION_TITLE}* instead (#354 AC-2)."
    )
    assert _delegates_the_level_choice(" ".join(section.split())), (
        f"the `create` contract must name `spec-authoring` → "
        f"*{_RUBRIC_SECTION_TITLE}* as where the level comes from (#354 AC-2)."
    )


# ---------------------------------------------------------------------------
# Shared prose-predicate primitives
# ---------------------------------------------------------------------------
# `_units`, `_BLOCKING_VERBS`/`_NEGATION_GAP` and `_EMPHASIS` were #288's and
# lived in `test_build_assurance_workflow`, which #435 deleted with the verb
# loop it described. They are re-homed here, beside `_sentences` and `_section`,
# rather than re-spelled at each call site: every polarity predicate in this
# tree is only as honest as this boundary, and a fork of it is a fork of the
# unit the controls were written to hold.

def _units(text: str) -> str:
    """``text`` re-joined one :func:`_sentences` unit per paragraph.

    Loss-free for every predicate here, because every one of them runs over
    ``_sentences`` units and ``_sentences`` already normalizes whitespace inside
    a unit. What it buys is **wrap-insensitivity for the controls below**: a
    control anchored on a hard-wrapped phrase stops landing the moment the
    paragraph is re-wrapped at another column width, and a re-wrap must not read
    as a finding. Call it on a section body, never on the whole file — ``_section``
    needs its headers on lines of their own.
    """
    return "\n\n".join(_sentences(text))


# ---------------------------------------------------------------------------
# The shared negation gap — what a negation is allowed to reach across
# ---------------------------------------------------------------------------

#: Verbs that **block** whatever follows them. A negation landing on one of
#: these states the *opposite* of the rule it appears to state: *"does not
#: preclude proceeding"*, *"does not block integration"* and *"does not forbid
#: writing"* each read to a negation-then-verb anchor as the prohibition intact,
#: while granting exactly what the prohibition forbids. Measured, one sentence at
#: a time, against the real file: each of those three left the whole module at
#: **25 passed**. So the gap a negation may reach across excludes them — a
#: negation whose object is a blocking verb governs the blocking, not the verb
#: beyond it, and the predicate must decline to treat the occurrence as covered.
#:
#: ``fail`` and ``hesitat`` are here for the double negation (*"never fails to
#: proceed"*), which is the same false converse reached by a different idiom.
#: Prefixes, not whole words: ``preclud`` covers *precludes/precluding*, ``rul``
#: covers *rule out/rules out*.
_BLOCKING_VERBS = (
    r"preclud|prevent|block|forbid|prohibit|bar|stop|halt|refus|restrict|"
    r"impede|hinder|obstruct|disallow|deter|rul|fail|hesitat"
)
#: The gap between a negation and the verb it governs: up to two words, none of
#: them a blocking verb. Two is #354's measured bound — every legitimate spelling
#: here keeps them adjacent or within two words (*"never proceeds"*, *"No one
#: writes"*, *"never integrate"*, *"refusal to integrate"*), and a negation
#: further off governs something else.
#:
#: **What this does not catch, measured rather than assumed.** Eighteen further
#: grant-shaped wordings were spliced into the real file one at a time, and the
#: line falls in a describable place:
#:
#: *Caught.* A grant whose blocking word is a noun or an idiom wider than the gap
#: — *"is no bar to proceeding"*, *"does not stand in the way of proceeding"*,
#: *"Nothing here prevents proceeding"*, *"is not a reason to withhold
#: proceeding"* — matches **no** negation at all, so the occurrence stays
#: uncovered and the sweep flags it. That is the fail-closed side, and it is why
#: the exclusion only has to rescue the cases where a negation *does* match.
#:
#: *Escapes.* **An outer negation over a well-formed inner prohibition** — *"It
#: is not true that no one writes an as-built record on a `trivial` run"*,
#: *"There is no rule that a mismatch must not be integrated"*, *"A thin design
#: is not a reason the run cannot proceed"*. The inner clause is exactly the rule
#: these predicates look for, spelled correctly, with a clean gap; the grant
#: lives in the matrix clause, which no token-window anchor can reach. All three
#: were measured escaping all three predicates. It is a different class from the
#: one fixed here — sentential negation scope, not a verb inside a gap — and it
#: is **not** closed. Closing it needs clause structure, not a wider window, so
#: it is recorded here at its measured size rather than papered over.
_NEGATION_GAP = rf"(?:\s+(?!(?:{_BLOCKING_VERBS})\w*\b)\w+){{0,2}}"


#: Emphasis, stripped before any *anchored* predicate runs: this tree bolds its
#: rules, so ``**stops**`` puts a ``*`` between the verb and the words that
#: release it, and a "verb, then up to N words" anchor never crosses it.
#: **Asterisks only** — ``_`` emphasis is unused here and ``certified_tree`` is
#: not, and splitting one identifier into two tokens spends two of an anchor's
#: gap allowance on a single word. Both halves measured: the first let
#: ``**stops** only when the operator asks`` read as unconditional, the second
#: let ``Comparing `HEAD^{tree}` to `certified_tree` is optional`` escape.
_EMPHASIS = re.compile(r"\*+")
#: A stop **released by a qualifier**. The rule is unconditional by design —
