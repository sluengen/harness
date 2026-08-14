"""#377/#288 — the agent-led build flow carries the assurance policy.

The harness ledger is paused, but its intended quality boundary must remain in
the distributed guidance.  These checks lock the operator-facing contract,
where a future install can rely on it without the harness runtime.

**#288 — the obligations, derived rather than restated.** #377 wrote the policy
into ``commands/build.md`` and guarded it with substrings, which are blind to
polarity and to per-level distinctness: the table collapsing to one row, a level
losing its design or review requirement, and the safe default inverting to
``trivial`` all left it green. The guards below instead *parse the command's own
``## Assurance`` table* and assert each row equals
:func:`harness.assurance.required_stages` for that level. The expected values are
**imported**, never restated, so the table stays the single rendering of the one
home (``specs/features/guidance-system.md`` records ``harness/assurance.py`` as
that home) and the two halves cannot drift apart in silence.

**Why the prose predicates' blind spot is safe here.** :func:`_requires` asks
"is there a unit naming this obligation that is *not* negated", so a cell mixing
an assertion and a negation inside one sentence is outside its reach. But the
expected side comes from an independent module, so any misreading of the prose
can only produce a **failing** test, never a silently passing one: to pass while
drifting, an edit would have to change the prose without changing either
boolean. The polarity direction is deliberate — *any un-negated naming unit*,
not *no negated naming unit* — because the ``trivial`` cell contains both
obligation nouns under a ``never``, and because an obligation **appended** to
that cell with the ``never`` left intact is exactly the drift that must fail.

:data:`_CONTINUE` deliberately excludes ``implement\\w*``: the correct sentence
contains "design-blind implementation" three words after its ``never``, so
including it would flag the prose it protects. That leaves an **accepted,
uncovered blind spot**, and it is stated here rather than papered over: an
exception worded *"the orchestrator may implement against the change spec
alone"*, appended to ``### Complex: design``, is invisible to **both** halves of
the pair — measured, not assumed. The presence half cannot see it either,
because such an exception removes nothing the presence half looks for. Widening
:data:`_CONTINUE` to close it would make the rule's own sentence an offender, so
the gap is accepted at its measured size.

:func:`_uncovered_continuations` is **section-wide** over ``### Complex: design``
rather than scoped to a "no usable design" subject: measured, dropping ``never``
from the rule's second sentence leaves it invisible to a subject-scoped sweep,
because that sentence carries no "no usable design" token. A future legitimate
unqualified "proceeds" in that section therefore fails the gate on purpose; the
failure message says so, so the next author reads it as the rule and not as a
false positive.
"""

# size: one document's acceptance suite — `commands/build.md`'s five assurance
# obligations (AC-1..AC-5), each as a *paired* presence assertion and inversion
# sweep, plus the controls that splice every one of them into the real file. The
# length is that enumeration, not accreted logic: the pairing is the ticket's own
# subject, so each obligation costs two assertions and a control by construction,
# and the predicates carry their measurements because a prose guard whose
# anchoring is not recorded is re-derived from scratch by the next author. #288's
# first review FAILED on precisely the obligation that shipped unpaired, so the
# structure that makes this file long is what the ticket exists to establish.
# Splitting by AC was considered and rejected: the controls and the polarity
# predicates are shared across the ACs, so a split trades length for a fourth
# cross-module import of predicates whose honesty is the thing under test.

from __future__ import annotations

import re
from pathlib import Path

import pytest

from harness.assurance import (
    ASSURANCE_LEVELS,
    DEFAULT_ASSURANCE,
    RequiredStages,
    required_stages,
)

# `_sentences` (the unit boundary) and `_section` (the scope) are #354's, and
# every polarity predicate below is only as honest as they are. Importing across
# test modules is the established pattern here — `test_assurance_filing_rubric`
# imports `_registered_surface` from `test_tracker_neutral_lifecycle` for the
# same reason. Moving them to a shared module would re-open #354's controls,
# which is out of this ticket's scope.
from tests.unit.test_assurance_filing_rubric import _UNIVERSAL_NEGATION, _section, _sentences

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD = REPO_ROOT / "commands" / "build.md"
REVIEWER = REPO_ROOT / "agents" / "reviewer.md"
ARCHITECT = REPO_ROOT / "agents" / "architect.md"
CONTEXT_TEMPLATE = REPO_ROOT / "templates" / "CONTEXT.template.md"

_ASSURANCE_SECTION = "## Assurance"
_DESIGN_SECTION = "### Complex: design"
_CERTIFY_SECTION = "### Certify trivial work"
_SHIP_SECTION = "## 3. Ship"


def _build_text() -> str:
    return BUILD.read_text(encoding="utf-8")


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


# ---------------------------------------------------------------------------
# The `## Assurance` table, parsed and derived
# ---------------------------------------------------------------------------

#: A table row's level cell: a single backticked word and nothing else. Every
#: such row is parsed, **unfiltered by vocabulary** — a spurious `` `moderate` ``
#: row must fail the row-set floor rather than being quietly skipped, which is
#: what gives that floor an edit only it can see. The header (`Level`) and the
#: separator (`---`) carry no backticks and are excluded by the same rule.
_LEVEL_CELL = re.compile(r"`(\w+)`")

_DESIGN = re.compile(r"\bdesign\w*\b", re.IGNORECASE)
_REVIEW = re.compile(r"\brevie\w*\b", re.IGNORECASE)


def _assurance_rows() -> dict[str, str]:
    """``{level: required-evidence cell}`` parsed out of the command's own table."""
    rows: dict[str, str] = {}
    for line in _section(_build_text(), _ASSURANCE_SECTION).splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        match = _LEVEL_CELL.fullmatch(cells[0])
        if match:
            rows[match.group(1)] = cells[1]
    return rows


def _requires(cell: str, noun: re.Pattern[str]) -> bool:
    """Is there a unit of ``cell`` naming the obligation that is **not** negated?"""
    return any(
        noun.search(unit) and not _UNIVERSAL_NEGATION.search(unit) for unit in _sentences(cell)
    )


def _derived_stages(cell: str) -> RequiredStages:
    """The stages a row's evidence cell obliges, read off the prose."""
    return RequiredStages(design=_requires(cell, _DESIGN), llm_review=_requires(cell, _REVIEW))


def test_the_derived_row_set_is_the_policy_vocabulary() -> None:
    """FLOOR under every derived assertion below.

    A dead parser — a changed table shape, a renamed section — yields an empty
    mapping, and an empty mapping makes a per-level parametrization vacuous and
    a "for each row" loop pass over nothing. Equality with the imported
    vocabulary additionally catches a *fourth* row appearing in the command:
    that row would send an operator to apply a level ``resolve_assurance`` does
    not recognize, which fails safe to ``simple`` in silence.
    """
    rows = _assurance_rows()

    assert set(rows) == set(ASSURANCE_LEVELS), (
        f"`commands/build.md` → {_ASSURANCE_SECTION} states rows for "
        f"{sorted(rows)}; the policy module's vocabulary is "
        f"{sorted(ASSURANCE_LEVELS)} (#288 AC-1)."
    )
    assert "complex" in rows and "trivial" in rows, (
        f"the parsed row set {sorted(rows)} lost a known level — the parser is "
        f"reading something other than the assurance table."
    )
    for level, cell in rows.items():
        assert cell.strip(), f"the `{level}` row states no required evidence at all"


@pytest.mark.parametrize("level", ASSURANCE_LEVELS, ids=lambda level: level)
def test_the_table_states_the_stages_the_policy_module_requires(level: str) -> None:
    """AC-1: the command's table equals ``required_stages(level)``, expected values imported.

    Not distinctness: equality subsumes it — two rows cannot state the same
    obligations without at least one of them disagreeing with the module — and
    additionally catches the case distinctness cannot see, where the prose and
    the runtime mapping drift apart while the rows still differ.
    """
    cell = _assurance_rows()[level]
    derived = _derived_stages(cell)
    expected = required_stages(level)  # type: ignore[arg-type]

    assert derived == expected, (
        f"`commands/build.md`'s `{level}` row reads as {derived} but "
        f"`harness.assurance.required_stages({level!r})` is {expected}. The "
        f"table is a rendering of the policy module, not a second home for it; "
        f"the row states: {cell!r} (#288 AC-1)."
    )


# ---------------------------------------------------------------------------
# The safe default, read off the same section
# ---------------------------------------------------------------------------

_LEVEL_ALT = "|".join(re.escape(level) for level in ASSURANCE_LEVELS)
_UNRESOLVED = re.compile(
    r"\bmissing\b|\bconflicting\b|\bunrecognis\w*\b|\bunrecogniz\w*\b|\bunknown\b",
    re.IGNORECASE,
)
#: A default verb and the level it points at. `_levels_chosen` from #354 cannot
#: read ``default to `simple` `` — its lazy ``{0,2}?`` bound is "the next word",
#: which returns ``to`` and filters out — so this predicate is written fresh
#: rather than reused into a vacuous-then-failing guard.
_DEFAULTS_TO = re.compile(
    rf"\bdefaults?\w*\s+to\s+`?(?P<level>{_LEVEL_ALT})`?",
    re.IGNORECASE,
)


def _unresolved_defaults(text: str) -> set[str]:
    """The levels that unresolved assurance is *sent to* by un-negated units.

    The negation exclusion is the point: ``must not **default to `simple`**``
    names the right level while stating the opposite rule, and a predicate that
    only looked for the destination would read it as the rule intact.
    """
    found: set[str] = set()
    for unit in _sentences(text):
        if not _UNRESOLVED.search(unit) or _UNIVERSAL_NEGATION.search(unit):
            continue
        found.update(match.group("level").lower() for match in _DEFAULTS_TO.finditer(unit))
    return found


def test_unresolved_assurance_defaults_to_the_policy_modules_default() -> None:
    """AC-1: the safe default is the module's, and inverting it fails.

    Third-party input decides this: labels are settable by anyone with issue
    write access, so the direction the unresolved case falls in is the whole
    protection. Sent to ``trivial`` it would skip the review engine entirely.
    """
    section = _section(_build_text(), _ASSURANCE_SECTION)
    routed = _unresolved_defaults(section)

    assert routed == {DEFAULT_ASSURANCE}, (
        f"`commands/build.md` → {_ASSURANCE_SECTION} sends missing, conflicting "
        f"or unrecognised assurance to {sorted(routed) or 'nowhere'}; "
        f"`harness.assurance.DEFAULT_ASSURANCE` is {DEFAULT_ASSURANCE!r}. An "
        f"empty result means the rule was negated or lost its default verb, not "
        f"that the file is silent on it (#288 AC-1)."
    )


# ---------------------------------------------------------------------------
# AC-2 — a `complex` run whose design produces nothing usable stops
# ---------------------------------------------------------------------------

_STOPS = re.compile(r"\bstops?\b|\bstopped\b|\bstopping\b", re.IGNORECASE)
_NO_USABLE_DESIGN = re.compile(
    r"\bno usable design\b|\bnothing usable\b|\bunusable design\b", re.IGNORECASE
)
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
#: absence, failure, and an artifact that misses the change spec are one outcome
#: — so ``only`` and its kin do not narrow the rule, they replace it with a
#: discretionary pause. This half catches a stop turned *conditional*; the sweep
#: below catches one turned into a *continuation*. Neither sees the other's
#: edit, which is what makes them two guards rather than one stated twice.
#:
#: **In either word order**, as :data:`_RELEASED_BINDING` already is. Measured:
#: anchored forwards only, rewriting the rule to *"Only where the operator
#: insists does a `complex` run with no usable design **stop**."* left
#: :func:`test_an_unusable_design_stops_the_run` **passing** — the rule turned
#: discretionary and read green.
#:
#: The two directions take different shapes on purpose. Forwards the qualifier
#: trails the verb inside a bounded four-token window. Backwards it *fronts the
#: clause*, and fronting has no bounded distance — the measured probe puts
#: twelve tokens between ``Only`` and ``stop``, so any token budget is a number
#: picked to fit the one wording that was tried. The backward arm is therefore
#: scoped to the **unit** (a single sentence, whitespace-normalized by
#: ``_sentences``): a releasing qualifier anywhere ahead of the stop verb in the
#: same sentence releases it. That over-flags a sentence that stops
#: unconditionally *and* uses one of these words for something else — which
#: fails **closed**, loudly, on the presence assertion, and is the direction to
#: err in for a rule whose whole content is that it has no exceptions.
_STOP_RELEASE = (
    r"only|unless|except|optional\w*|discretion\w*|at the operator|on request|"
    r"when asked|if asked"
)
_RELEASED_STOP = re.compile(
    rf"\bstop\w*\b(?:\s+\S+){{0,4}}?\s+\b(?:{_STOP_RELEASE})\b"
    rf"|\b(?:{_STOP_RELEASE})\b.*?\bstop\w*\b",
    re.IGNORECASE,
)
#: Deliberately without ``implement\w*`` — see the module docstring.
_CONTINUE = re.compile(
    r"\b(?:proceed\w*|continu\w*|falls? back|carries on|goes ahead)\b", re.IGNORECASE
)
_NEGATED_CONTINUE = re.compile(
    r"\b(?:never|must not|may not|cannot|can not|does not|do not|is not|are not|without)\b"
    rf"{_NEGATION_GAP}\s+(?:proceed\w*|continu\w*|falls? back|carries on|goes ahead)\b",
    re.IGNORECASE,
)


def _uncovered_continuations(unit: str) -> list[str]:
    """Continuation verbs in ``unit`` that no negation governs.

    Two narrowings, and neither is a closure — say what each buys:

    *Per-occurrence, not per-sentence.* A sentence-wide "is there a negation"
    shield lets one appended clause grant what the sentence's own ``never``
    forbids. Anchoring each negation to the occurrence it reaches removes that
    shield. It does **not** close #354's hole, which is about the *unit* a
    predicate reads; it narrows it to the width of one negation's gap.

    *A blocking verb inside that gap does not count as coverage.* Without this,
    ``does not preclude proceeding`` scored as ``never proceeds`` — the exact
    opposite boolean — and the whole module stayed at 25 passed. See
    :data:`_NEGATION_GAP`, which also records what the exclusion still misses.

    What remains uncovered, measured rather than assumed: the ``implement\\w*``
    blind spot named in the module docstring, and an outer negation over a
    correctly spelled inner prohibition (*"is not a reason the run cannot
    proceed"*) — both recorded at :data:`_NEGATION_GAP`. Everything else probed
    for this fix leaves its continuation verb uncovered, so the sweep flags it.
    """
    negated = {match.end() for match in _NEGATED_CONTINUE.finditer(unit)}
    return [match.group(0) for match in _CONTINUE.finditer(unit) if match.end() not in negated]


def _unconditional_stops(text: str) -> list[str]:
    """Units stating an unusable design stops the run, with nothing releasing the stop.

    Co-occurrence of the subject and the verb is not the rule: ``**stops** only
    when the operator asks for it`` names both and states the opposite, so the
    qualifier is part of what is asserted, not context around it.
    """
    return [
        unit
        for unit in _sentences(text)
        if _NO_USABLE_DESIGN.search(unit)
        and _STOPS.search(unit)
        and not _RELEASED_STOP.search(_EMPHASIS.sub(" ", unit))
    ]


def test_an_unusable_design_stops_the_run() -> None:
    """AC-2: no usable design is a stop, not a licence to implement design-blind.

    The agent-led counterpart of ``harness.assurance.DESIGN_NOT_USABLE_REASON``:
    absence and failure are distinct causes with the same refusal — and the
    refusal is unconditional, so a stop handed a qualifier does not satisfy this.
    """
    section = _section(_build_text(), _DESIGN_SECTION)
    stated = _unconditional_stops(section)

    assert stated, (
        f"`commands/build.md` → {_DESIGN_SECTION} does not say that a `complex` "
        f"run whose design stage produces no usable design **stops** — or says "
        f"it under a qualifier, which is the same thing. Without it the "
        f"orchestrator's cheapest response to a failed design agent is to "
        f"implement anyway — the degradation the harness path refuses with "
        f"`DESIGN_NOT_USABLE_REASON` (#288 AC-2)."
    )


def test_the_design_section_negates_every_continuation() -> None:
    """AC-2, the inversion: nothing in the design stage carries on unqualified.

    Section-wide on purpose. A legitimate future "proceeds" here fails this
    gate: that is the rule, not a false positive — qualify it with the negation
    that says when the run does *not* proceed, or state it outside this section.
    """
    section = _section(_build_text(), _DESIGN_SECTION)
    offenders = [
        (unit, found) for unit in _sentences(section) if (found := _uncovered_continuations(unit))
    ]

    assert not offenders, (
        f"`commands/build.md` → {_DESIGN_SECTION} lets the run carry on with no "
        f"negation governing it: {offenders}. Either the stop rule lost its "
        f"`never`, or an exception was appended to it — both leave a `complex` "
        f"run free to implement against a design that produced nothing (#288 AC-2)."
    )


# ---------------------------------------------------------------------------
# AC-4 — who writes a `trivial` run's as-built record, and when
# ---------------------------------------------------------------------------

_TRIVIAL = re.compile(r"\btrivial\b", re.IGNORECASE)
#: The *surface*, stripped before any write verb is looked for: "as-built-record"
#: contains a bare `record`, so an unstripped verb search reads the noun as a
#: verb and flags the trivial table row, which states no rule about writing at all.
_AS_BUILT = re.compile(r"as-built[- ]record", re.IGNORECASE)
#: Every verb **open-ended**, rather than an enumerated set of inflections.
#: Measured: "the as-built record is **authored** by the certifier" escaped the
#: sweep while the same sentence spelled "written" was caught, because the
#: predicate carried write's inflections but only ``authors?`` — and widening
#: that one verb then let "**recorded**" through, one spelling later. Which
#: spelling an edit reaches for is arbitrary, so the shape is fixed here rather
#: than the two spellings that happened to be measured.
_WRITE_VERBS = r"writ\w*|wrote|record\w*|author\w*"
_WRITE = re.compile(rf"\b(?:{_WRITE_VERBS})\b", re.IGNORECASE)
_NEGATED_WRITE = re.compile(
    r"\b(?:no one|nobody|never|must not|may not|cannot|can not|does not|do not|is not|are not)\b"
    rf"{_NEGATION_GAP}\s+(?:{_WRITE_VERBS})\b",
    re.IGNORECASE,
)
_CERTIFIED_TREE = re.compile(r"`?certified_tree`?")
#: The record's placement relative to ``certified_tree``. ``after`` is the whole
#: rule: a record written *before* the capture is inside the certified tree and
#: raises nothing, so a unit reading "before" states no rule at all while naming
#: every noun the ordering assertion looks for. Measured — the swap passed.
_AFTER = re.compile(r"\bafter\b|\bfollowing\b|\bsubsequent to\b|\bonce\b", re.IGNORECASE)
_BEFORE = re.compile(r"\bbefore\b|\bprior to\b|\bahead of\b|\bpreceding\b", re.IGNORECASE)


def _uncovered_writes(unit: str) -> list[str]:
    """Write verbs in ``unit``, minus the as-built-record noun, that no negation governs."""
    stripped = _AS_BUILT.sub(" ", unit)
    negated = {match.end() for match in _NEGATED_WRITE.finditer(stripped)}
    return [match.group(0) for match in _WRITE.finditer(stripped) if match.end() not in negated]


def _permits_a_trivial_record(text: str) -> list[str]:
    """Units putting an as-built-record write on a ``trivial`` run without forbidding it."""
    return [
        unit
        for unit in _sentences(text)
        if _TRIVIAL.search(unit) and _AS_BUILT.search(unit) and _uncovered_writes(unit)
    ]


def _forbids_a_trivial_record(text: str) -> list[str]:
    """Units that put an as-built-record write on a ``trivial`` run and forbid it.

    Extracted so the control below can assert this half **dies** on the same
    edit that makes :func:`_permits_a_trivial_record` fire. A control that
    asserts only the sweep proves the pair moves in one direction; a pair where
    only one half moves is not a pair, and re-implementing the predicate inside
    the control would prove nothing about the predicate the test runs.
    """
    return [
        unit
        for unit in _sentences(text)
        if _TRIVIAL.search(unit)
        and _AS_BUILT.search(unit)
        and _NEGATED_WRITE.search(_AS_BUILT.sub(" ", unit))
    ]


def test_a_trivial_run_has_no_as_built_record_writer() -> None:
    """AC-4: the owner is named, and the name is *nobody* — and nothing is missing.

    A `trivial` run has no reviewer, and the reviewer is who records reality.
    Leaving the owner unstated invites the orchestrator or the implementer to
    fill the gap, which is the separation of concerns `CLAUDE.md` calls
    load-bearing: the agent that promises would be recording delivery.
    """
    stated = _forbids_a_trivial_record(_section(_build_text(), _CERTIFY_SECTION))

    assert stated, (
        f"`commands/build.md` → {_CERTIFY_SECTION} does not say who writes the "
        f"as-built record on a `trivial` run. The certifier rejects any "
        f"as-built-record surface, so the honest answer is that no one does and "
        f"none is missing — but unstated, it reads as an omission (#288 AC-4)."
    )


def test_no_unit_permits_an_as_built_record_on_a_trivial_run() -> None:
    """AC-4, the inversion, swept file-wide.

    Deleting the rule is the mutation everyone tests for; flipping its subject
    — "no one writes" to "the implementer writes" — leaves a sentence carrying
    every noun the presence check looks for and reads green.
    """
    offenders = _permits_a_trivial_record(_build_text())

    assert not offenders, (
        f"`commands/build.md` gives a `trivial` run an as-built-record writer: "
        f"{offenders}. That path has no reviewer, and writing the record after "
        f"`certified_tree` changes the tree the certificate covers (#288 AC-4)."
    )


def _ordered_record_rules(text: str) -> list[str]:
    """Units placing an as-built-record write **after** ``certified_tree``.

    Extracted so the control can assert this returns nothing on the reversed
    text through the same predicate the test runs, rather than a copy of it.
    """
    return [
        unit
        for unit in _sentences(text)
        if _CERTIFIED_TREE.search(unit)
        and _AS_BUILT.search(unit)
        and _WRITE.search(_AS_BUILT.sub(" ", unit))
        and _AFTER.search(unit)
        and not _BEFORE.search(unit)
    ]


def test_the_trivial_record_rule_is_ordered_against_certified_tree() -> None:
    """AC-4: the rule is placed relative to ``certified_tree``, not merely stated.

    The ``as-built record`` conjunct is not decoration: without it the staging
    line ``git add -A && git write-tree    # certified_tree`` satisfies a
    "certified_tree near a write verb" assertion by itself, and the guard
    measures nothing.
    """
    ordered = _ordered_record_rules(_section(_build_text(), _CERTIFY_SECTION))

    assert ordered, (
        f"`commands/build.md` → {_CERTIFY_SECTION} does not place the as-built "
        f"record **after** `certified_tree`. A record written afterwards is "
        f"not an exception to the invalidation rule — it is the ordinary case "
        f"of it, and saying so is what stops it being read as one. Placed the "
        f"other way round the sentence states no rule while still naming every "
        f"noun: a record written *before* the capture is inside the tree the "
        f"certificate covers and raises nothing (#288 AC-4)."
    )


# ---------------------------------------------------------------------------
# AC-3 — ship binds every commit to the tree its assurance stage certified
# ---------------------------------------------------------------------------

_INTEGRATE = re.compile(r"\bintegrat\w*\b", re.IGNORECASE)
_NEGATED_INTEGRATE = re.compile(
    r"\b(?:never|must not|may not|cannot|can not|does not|do not|is not|are not|refus\w*|without)\b"
    rf"{_NEGATION_GAP}\s+integrat\w*\b",
    re.IGNORECASE,
)
_MISMATCH = re.compile(r"\bdoes not equal\b|\bnot equal\b|\bmismatch\w*\b", re.IGNORECASE)

#: The binding itself — the comparison a committed tree is held to. ``ship`` is
#: deliberately **absent**: the real rule reads "has **no** verdict, so it
#: ships", and a release predicate anchored on a shipping verb would read that
#: ``no`` as releasing the binding it is nowhere near.
_BINDING = r"compar\w*|equals?|equalit\w*|identit\w*|match\w*|bound to|binds?|binding"
_BINDS = re.compile(rf"\b(?:{_BINDING})\b", re.IGNORECASE)
#: A release **anchored to the binding**, in either word order. The anchoring is
#: the whole predicate: the real rule says the run "has **no** verdict", and an
#: unanchored ``no`` would read that as "no comparison". Gaps are ``\S+`` rather
#: than ``\w+`` because the tokens between are backticked identifiers —
#: ``` `HEAD^{tree}` ``` is not a ``\w+``, and a ``\w+`` gap silently fails to
#: cross it, which is the same class of miss as an anchor that cannot cross
#: ``**``.
_RELEASED_BINDING = re.compile(
    rf"\b(?:without|need(?:s)? not|need(?:s)? no|no need to|not required to|"
    rf"never required to|not needed|skip\w*|omit\w*|forgo\w*|forego\w*|bypass\w*|"
    rf"waiv\w*|exempt\w*|optional\w*|unnecessary|unneeded|no|regardless of)\b"
    rf"(?:\s+\S+){{0,5}}?\s+\b(?:{_BINDING})\b"
    rf"|\b(?:{_BINDING})\b(?:\s+\S+){{0,5}}?\s+\b(?:optional\w*|unnecessary|unneeded|"
    rf"not required|never required|not needed|nothing|anything|advisor\w*|"
    rf"informational|non-?binding)\b",
    re.IGNORECASE,
)


def _binds_a_trivial_ship(text: str) -> list[str]:
    """Units binding a ``trivial`` run's commit to ``certified_tree`` by a comparison.

    Both nouns **and** the comparison must sit in one unit. Naming the two trees
    beside each other is not a binding — the identity check is the obligation,
    and a unit that omits it states an association.
    """
    return [
        unit
        for unit in _sentences(text)
        if _TRIVIAL.search(unit) and _CERTIFIED_TREE.search(unit) and _BINDS.search(unit)
    ]


def _permits_an_unbound_trivial_ship(text: str) -> list[str]:
    """The **inversion**: a ``trivial``/``certified_tree`` unit that releases the binding.

    The presence half cannot catch this and is not meant to. *"A ``trivial`` run
    may ship **without comparing** ``certified_tree`` to anything at all"* names
    both trees and a comparison verb, so it satisfies presence exactly while
    granting what AC-3 forbids — measured, that sentence left the whole module
    green. The two halves therefore have separate exclusive killers: deleting
    the rule kills presence alone, and this sentence kills the sweep alone.
    """
    return [
        unit
        for unit in _sentences(text)
        if _TRIVIAL.search(unit)
        and _CERTIFIED_TREE.search(unit)
        and _RELEASED_BINDING.search(_EMPHASIS.sub(" ", unit))
    ]


def _mismatch_units(text: str) -> list[str]:
    """Units that speak about integrating when the committed tree does not match."""
    return [unit for unit in _sentences(text) if _MISMATCH.search(unit) and _INTEGRATE.search(unit)]


def _permits_integration_on_mismatch(text: str) -> list[str]:
    """The **inversion**: a mismatch unit whose integrate verb no negation governs."""
    offenders = []
    for unit in _mismatch_units(text):
        negated = {match.end() for match in _NEGATED_INTEGRATE.finditer(unit)}
        if any(match.end() not in negated for match in _INTEGRATE.finditer(unit)):
            offenders.append(unit)
    return offenders


def test_ship_binds_a_trivial_commit_to_certified_tree() -> None:
    """AC-3: the level with no verdict still ships only the tree it certified.

    ``reviewed_tree`` is produced by a reviewer, and a `trivial` run has none —
    so the identity comparison the PASS path states covers every run except the
    one whose only evidence is a certificate.
    """
    section = _section(_build_text(), _SHIP_SECTION)
    bound = _binds_a_trivial_ship(section)

    assert bound, (
        f"`commands/build.md` → {_SHIP_SECTION} states no unit carrying "
        f"`trivial`, `certified_tree` **and** the comparison that binds them, so "
        f"nothing holds a certified run's commit to the tree that was certified. "
        f"All three must sit in one unit: split across two sentences the binding "
        f"is not stated, only implied, and the two nouns alone are an "
        f"association rather than an obligation (#288 AC-3)."
    )


def test_no_unit_permits_an_unbound_trivial_ship() -> None:
    """AC-3, the inversion — the half the presence assertion cannot be.

    AC-5 is what this exists for: the presence half passes on text stating the
    opposite, because a sentence releasing the run from the comparison still
    names the comparison. Swept file-wide, like the record inversion: a
    permissive sentence added under *Certify trivial work* would grant the same
    licence as one added under *Ship*.
    """
    offenders = _permits_an_unbound_trivial_ship(_build_text())

    assert not offenders, (
        f"`commands/build.md` releases a `trivial` run from comparing its "
        f"commit to `certified_tree`: {offenders}. The certificate covers one "
        f"tree and one only; a commit that is not held to it ships a tree "
        f"nothing certified, which is the whole failure the comparison exists "
        f"to stop (#288 AC-3, AC-5)."
    )


def test_ship_refuses_integration_on_tree_mismatch() -> None:
    """AC-3, paired: the refusal is stated, and its inversion is absent.

    The presence half survives the cheapest inversion — ``never integrate`` to
    ``integrate anyway`` keeps every noun it looks for — which is why the
    permissive sweep is the half that catches it.
    """
    section = _section(_build_text(), _SHIP_SECTION)

    assert _mismatch_units(section), (
        f"`commands/build.md` → {_SHIP_SECTION} states no rule about "
        f"integrating when the committed tree does not equal the certified or "
        f"reviewed one (#288 AC-3)."
    )
    offenders = _permits_integration_on_mismatch(section)
    assert not offenders, (
        f"`commands/build.md` → {_SHIP_SECTION} permits integrating a tree that "
        f"does not match: {offenders}. The comparison exists to stop exactly "
        f"that, so an unqualified integrate verb in a mismatch sentence undoes "
        f"the whole check (#288 AC-3)."
    )


# ---------------------------------------------------------------------------
# The controls — every one splices into the **real** file text
# ---------------------------------------------------------------------------


def test_the_new_predicates_read_the_real_documents_boundaries() -> None:
    """The predicates above, exercised against mutations of the real prose.

    A control fed a hand-written clean sentence can only fail for a defect in a
    predicate's *tokens*; it can never fail the way the real assertion fails,
    because the real assertion runs over a whole markdown section where units
    merge and negations shield what follows them (#354). Every sample here is
    the real text with one edit, and every edit asserts it landed.
    """
    text = _build_text()
    rows = _assurance_rows()

    # 1. The segmentation floor. If the `trivial` cell reads as one unit, its
    #    `never` shields anything appended to it — control 3 would then pass for
    #    the wrong reason, and an added obligation would be invisible.
    assert len(_sentences(rows["trivial"])) >= 2, (
        "the `trivial` cell reads as a single unit — a splitter that merges its "
        "two sentences lends the `never` to whatever follows (#354)."
    )

    # 2. The negation is what makes the cell read (False, False): remove it and
    #    both obligations appear.
    unnegated = rows["trivial"].replace("never receives", "receives")
    assert unnegated != rows["trivial"], (
        "the `trivial` cell's negation moved — re-anchor this control"
    )
    assert _requires(unnegated, _DESIGN) and _requires(unnegated, _REVIEW), (
        "the obligation predicate cannot see an un-negated obligation in the "
        "`trivial` cell — it is reading nouns, not polarity."
    )

    # 3. The other direction, and the one a `not negated anywhere` predicate is
    #    blind to: an obligation **appended** while the `never` survives.
    appended = rows["trivial"] + " It receives an independent reviewer sub-agent."
    assert _requires(appended, _REVIEW), (
        "an obligation appended after the `never` is invisible — the predicate "
        "is asking `is this cell negated` instead of `is there an un-negated "
        "unit naming the obligation`, which is fail-open for assurance."
    )
    assert not _requires(rows["trivial"], _REVIEW), (
        "the predicate reads the real `trivial` cell as requiring a review — it "
        "is not reading the `never` at all."
    )

    # 4. The safe default, both inversions, spliced into the real section.
    section = _section(text, _ASSURANCE_SECTION)
    flipped = section.replace("default to `simple`", "default to `trivial`")
    assert flipped != section, "the safe-default sentence moved — re-anchor this control"
    assert _unresolved_defaults(flipped) == {"trivial"}, (
        "the default predicate does not read the level the rule points at."
    )
    negated = section.replace("must **default to", "must not **default to")
    assert negated != section, "the safe-default sentence moved — re-anchor this control"
    assert _unresolved_defaults(negated) == set(), (
        "`must not default to `simple`` reads as the rule intact — the negation "
        "exclusion is not firing, so the inverted rule passes."
    )

    # 5. An exception appended to the design section — #354's splice shape, the
    #    one a subject-scoped or sentence-wide predicate misses.
    design = _section(text, _DESIGN_SECTION)
    spliced = design.rstrip() + (
        " Where the architect returns nothing usable the orchestrator may "
        "proceed to implementation."
    )
    assert spliced != design, "the design section is empty — re-anchor this control"
    assert any(_uncovered_continuations(unit) for unit in _sentences(spliced)), (
        "an exception appended to the design stage is invisible to the sweep — "
        "the rule's own `never` is being read as covering it."
    )

    # 6. The record owner flipped, in the real file: presence dies **and** the
    #    file-wide inversion fires. Both halves are asserted through the very
    #    predicates the tests call, because a pair where only one moves is not a
    #    pair — and a control that re-implements the predicate proves nothing
    #    about the predicate under test.
    flipped_owner = text.replace("**No one writes an", "**The implementer writes an")
    assert flipped_owner != text, "the record-owner rule moved — re-anchor this control"
    assert _permits_a_trivial_record(flipped_owner), (
        "flipping the record owner leaves the file-wide sweep green — it is "
        "matching nouns rather than the polarity of the write verb."
    )
    assert not _forbids_a_trivial_record(_section(flipped_owner, _CERTIFY_SECTION)), (
        "the presence half still reads a forbidden record write after the owner "
        "was flipped to a real one — it is finding a negation somewhere in the "
        "unit rather than one governing the write verb."
    )

    # 7. The as-built-record noun must not be read as a write verb: the
    #    `trivial` table row names the surface and states no writing rule.
    assert not _permits_a_trivial_record(f"| `trivial` | {rows['trivial']} |"), (
        "the `trivial` table row is flagged as permitting a record write — the "
        "predicate is reading the `record` inside `as-built-record` as a verb."
    )

    # 8. The ship refusal, inverted the way an edit would write it.
    ship = _section(text, _SHIP_SECTION)
    permissive = ship.replace("never integrate", "integrate anyway")
    assert permissive != ship, "the ship refusal moved — re-anchor this control"
    assert _permits_integration_on_mismatch(permissive), (
        "`integrate anyway` on a mismatch reads as the refusal intact — the "
        "negation is not anchored to the verb it governs."
    )
    assert _mismatch_units(permissive), (
        "the presence half stopped firing on the inverted text — then the pair "
        "is redundant rather than complementary, and one half is untested."
    )

    # 9. The write-verb morphology, in the real section. "authored" and
    #    "written" are the same sentence; measured, only one of them was caught,
    #    and which spelling an edit reaches for is arbitrary.
    certify = _units(_section(text, _CERTIFY_SECTION))
    for spelling in ("authored", "written", "recorded"):
        record_write = (
            f"{certify}\n\nOn a `trivial` run the as-built record is {spelling} by the certifier."
        )
        assert _permits_a_trivial_record(record_write), (
            f"a permissive record sentence spelled {spelling!r} escapes the "
            f"sweep — the write vocabulary covers one verb's inflections and not "
            f"another's, which is fail-open by spelling."
        )
    assert not _permits_a_trivial_record(certify), (
        "the real *Certify trivial work* section already reads as permitting a "
        "`trivial` record write, so control 9 cannot distinguish the splice from "
        "the file it was spliced into."
    )

    # 10. The stop, released by a qualifier: the subject and the verb both
    #     survive, so only an anchored qualifier check can see it.
    design_units = _units(design)
    qualified = design_units.replace(
        "no usable design **stops**.",
        "no usable design **stops** only when the operator asks for it.",
    )
    assert qualified != design_units, "the stop rule moved — re-anchor this control"
    assert _unconditional_stops(design_units) and not _unconditional_stops(qualified), (
        "a stop qualified with `only when the operator asks for it` still reads "
        "as an unconditional stop — the presence half is checking that the "
        "subject and the verb co-occur, which text stating the opposite does too."
    )

    # 11. The record ordering, reversed: every noun survives and the rule does not.
    reversed_order = certify.replace(
        "record after `certified_tree`", "record before `certified_tree`"
    )
    assert reversed_order != certify, "the record ordering rule moved — re-anchor this control"
    assert _ordered_record_rules(certify) and not _ordered_record_rules(reversed_order), (
        "the ordering assertion reads ``before `certified_tree``` as placing the "
        "record after it — it is reading co-occurrence, not order."
    )

    # 12-14. The false converse, one control per negation predicate: a grant
    #     whose *blocking verb* sits inside the negation's own gap. Each of the
    #     three sentences below was measured against the real file one at a time
    #     and left the whole module at 25 passed — the predicate computed the
    #     opposite boolean from the rule it was written to protect.

    # 12. Continuation. `does not preclude proceeding` against `never proceeds`.
    precluded = design.rstrip() + " A thin design does not preclude proceeding to implementation."
    assert precluded != design, "the design section is empty — re-anchor this control"
    assert not any(_uncovered_continuations(unit) for unit in _sentences(design)), (
        "the real design section already carries an uncovered continuation, so "
        "control 12 cannot tell its splice apart from the file it spliced into."
    )
    assert any(_uncovered_continuations(unit) for unit in _sentences(precluded)), (
        "`does not preclude proceeding` reads as `never proceeds` — the negation "
        "is being credited with covering the verb its own blocking verb governs, "
        "which is the opposite boolean and grants design-blind implementation."
    )

    # 13. Integration. `does not block integration` against `never integrate`.
    unblocked = ship.rstrip() + " On a `trivial` run a mismatch does not block integration."
    assert unblocked != ship, "the ship section is empty — re-anchor this control"
    assert not _permits_integration_on_mismatch(ship), (
        "the real ship section already permits integration on a mismatch, so "
        "control 13 cannot tell its splice apart from the file it spliced into."
    )
    assert _permits_integration_on_mismatch(unblocked), (
        "`does not block integration` reads as the refusal intact — the negation "
        "governs `block`, not `integration`, and the sentence grants what the "
        "refusal forbids."
    )

    # 14. Writing. `does not forbid writing` against `No one writes`. This one
    #     moves **both** halves, and the presence half is the sharper assertion:
    #     it scored a sentence granting the write as forbidding it.
    record_rule = "No one writes an as-built record on a `trivial` run, and none is missing."
    granted = certify.replace(
        record_rule,
        "The invalidation rule does not forbid writing an as-built record on a `trivial` run.",
    )
    assert granted != certify, "the record-owner rule moved — re-anchor this control"
    assert not _forbids_a_trivial_record(granted), (
        "the presence half reads `does not forbid writing an as-built record` as "
        "forbidding it — a grant scored as the refusal, so the rule can be "
        "inverted in place and the assertion still passes."
    )
    assert _permits_a_trivial_record(granted), (
        "the sweep cannot see a granted `trivial` record write whose write verb "
        "sits behind a blocking verb — nothing is left guarding the owner rule."
    )

    # 15. The stop released by a **fronted** qualifier: same rule, reversed word
    #     order, every noun and the verb intact. Only a predicate written in both
    #     directions sees it — `_RELEASED_BINDING` already was, and this one was
    #     not, which is how the rule could be made operator-gated and read green.
    fronted = design_units.replace(
        "A `complex` run whose design stage produces no usable design **stops**.",
        "Only where the operator insists does a `complex` run with no usable design **stop**.",
    )
    assert fronted != design_units, "the stop rule moved — re-anchor this control"
    assert not _unconditional_stops(fronted), (
        "a stop gated on `Only where the operator insists` still reads as "
        "unconditional — the qualifier check is anchored in one word order, so "
        "fronting it turns AC-2's rule discretionary without failing anything."
    )


#: Permissive rewrites of the ship binding, each **replacing the real binding
#: unit** in the real section rather than standing alone. A control fed a
#: hand-written clean string can only fail for a defect in a predicate's tokens;
#: spliced in here, each is measured where the real assertion runs. Every wording
#: below satisfies the presence half — that is the point of the pair, and it is
#: what let the unpaired assertion pass on text stating the opposite.
_UNBOUND_SHIP_WORDINGS = (
    "A `trivial` run has no verdict, so it may ship without comparing "
    "`certified_tree` to anything at all.",
    "A `trivial` run need not compare its committed tree to `certified_tree`.",
    "A `trivial` run ships whatever tree it committed; no comparison against "
    "`certified_tree` is required.",
    "Comparing `HEAD^{tree}` to `certified_tree` is optional on a `trivial` run.",
    "A `trivial` run may skip the `certified_tree` comparison.",
    "On a `trivial` run the `certified_tree` identity comparison is unnecessary.",
    "A `trivial` run's commit is compared to nothing; `certified_tree` is advisory.",
)


def test_the_unbound_ship_wordings_are_a_populated_set() -> None:
    """FLOOR under the paraphrase parametrization below.

    A hand-written tuple loses a member as silently as a dead derivation, and an
    **empty** ``@pytest.mark.parametrize`` set reports ``1 skipped``, not a
    failure — verified in this environment. So the whole paraphrase-robustness
    claim for AC-3 can be emptied out and the gate stays green. The named member
    pins that the set still covers the obligation-free spelling (*"need not"*)
    and not just the ones that happen to remain.
    """
    assert len(_UNBOUND_SHIP_WORDINGS) >= 5, (
        f"only {len(_UNBOUND_SHIP_WORDINGS)} release wordings remain; the sweep "
        f"is being measured against too few paraphrases to show it reads the "
        f"property rather than one sentence (#288 AC-5)."
    )
    assert any("need not" in wording for wording in _UNBOUND_SHIP_WORDINGS), (
        "the `need not` paraphrase is gone from the set — the members are "
        "hand-written, so one can be dropped without anything else noticing."
    )


def _ship_section_released_by(wording: str) -> str:
    """The real ``## 3. Ship`` section with its binding unit swapped for ``wording``.

    Spliced at the **unit** level, not by a raw string replace: the lead is
    hard-wrapped, and an anchor on its wrapped form would stop landing the
    moment the paragraph is re-flowed — leaving this control silently measuring
    unmodified text, which is the failure mode it exists to rule out.
    """
    section = _section(_build_text(), _SHIP_SECTION)
    bound = _binds_a_trivial_ship(section)
    assert bound, "the real ship section states no binding unit to replace"
    return "\n\n".join(wording if unit in bound else unit for unit in _sentences(section))


@pytest.mark.parametrize("wording", _UNBOUND_SHIP_WORDINGS, ids=range(len(_UNBOUND_SHIP_WORDINGS)))
def test_the_ship_binding_sweep_catches_a_rewritten_release(wording: str) -> None:
    """AC-5: the sweep reads the property, not the one sentence it was written against.

    Fixing the measured defect against its one measured sentence would leave the
    next paraphrase through, and a guard that only recognises the wording it was
    written against is a spelling check wearing a rule's clothes.
    """
    released = _ship_section_released_by(wording)

    assert _binds_a_trivial_ship(released), (
        f"the presence half stops firing on {wording!r}, so this wording is "
        f"caught by presence rather than by the sweep — then the pair is "
        f"redundant here and the sweep is untested against it."
    )
    assert _permits_an_unbound_trivial_ship(released), (
        f"{wording!r} releases a `trivial` commit from `certified_tree` and the "
        f"sweep does not see it. The presence half passes on this sentence, so "
        f"nothing else will (#288 AC-5)."
    )


# ---------------------------------------------------------------------------
# #377's surface, unchanged
# ---------------------------------------------------------------------------


def test_build_defines_the_three_assurance_levels_and_safe_default() -> None:
    """Unknown assurance remains reviewable rather than becoming trivial."""
    text = BUILD.read_text().lower()

    for level in ("trivial", "simple", "complex"):
        assert level in text
    assert "default to `simple`" in text
    assert "trivial" in text and "certif" in text
    assert "assurance.trivial_certify" in text
    assert "git add -a && git write-tree" in text
    assert "invalidates the certificate" in text
    assert "no user-facing or as-built-record surface" in text
    assert "trivial_certify" in CONTEXT_TEMPLATE.read_text()


def test_build_isolates_design_and_review_from_implementation() -> None:
    """Complex design and every non-trivial review get a fresh agent context."""
    text = " ".join(BUILD.read_text().lower().split())

    assert "design sub-agent" in text
    assert "reviewer sub-agent" in text
    assert "do not pass the implementer's conversation" in text
    assert "inline review" not in text


def test_build_requires_visual_evidence_for_user_facing_changes() -> None:
    """A UI pass renders real state and supplies its final captures to review."""
    text = " ".join(BUILD.read_text().lower().split())

    for phrase in (
        "realistic seeded state",
        "screenshot",
        "either side of every breakpoint",
        "reference or the applicable design archetype",
        "visual evidence",
    ):
        assert phrase in text


def test_design_and_reviewer_roles_receive_the_agent_led_contract() -> None:
    """The dispatched roles know the required isolation and visual inputs."""
    assert "fresh context" in ARCHITECT.read_text().lower()
    reviewer_text = REVIEWER.read_text().lower()
    assert "visual evidence" in reviewer_text
    assert "screenshot" in reviewer_text
