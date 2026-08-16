"""The six prevention rules from the R-ratio retrospective, one home each.

The retrospective that produced this module measured roughly one ticket spawned
per ticket closed, about half of them preventable. Six rules close the measured
generators, and the change spec's AC-1 is a *placement* claim: each rule lands in
exactly its named home, **stated once**, with cross-references allowed and
restatement forbidden. That claim is what this module measures.

**Two assertions per rule, and the second is the one that bites.** A *home*
assertion says the named file carries an instruction unit whose distinctive terms
co-occur. An *exclusivity* assertion says exactly one registered file carries such
a unit — which is the only shape that can measure "stated once, no restatement
elsewhere". A home assertion alone stays green while a second copy of the rule
grows in another file, agrees with the first the day it is written, and drifts
after.

**The subject is the registered corpus, not the whole tree.** ``registry.yaml``'s
``files:`` block is what a consuming repo actually receives, so it is the corpus a
placement claim is about. The derivation, the reader, and the repo root are
**imported** from :mod:`tests.unit.test_assurance_filing_rubric` rather than
re-spelled here — a re-implemented predicate stops protecting the one the other
module's assertions call, which is the class ``craft.md`` → *Exercise the
production path, not merely a production constant* names.

**What this module does not prove.** That a rule is *correct*, that its prose is
readable, or that an agent obeys it. It proves placement and co-occurrence, so a
unit naming every term while saying the opposite would pass here. Polarity over
these six rules is a reviewer's judgment; where a rule has a cheap inversion
(rule 4's *propose* becoming *file*) the inversion is a different rule with
different terms, which the exclusivity assertion sees as the home moving.
"""

# size: over the declarative ceiling because eleven prose predicates, their tree
# assertions and their controls are one unit. The controls feed the
# same functions the tree assertions call, so splitting them into a second module
# forks a predicate from the samples that measure it — the defect `craft.md` →
# *A positive control must exercise the predicate, not re-implement it* names,
# and the reason the two sibling filing modules split by subject rather than by
# predicate-versus-control.
from __future__ import annotations

import re

from tests.unit.test_assurance_filing_rubric import (
    _REPO_ROOT,
    _delegates_the_level_choice,
    _read,
    _registered_markdown,
)
from tests.unit.test_assurance_filing_surfaces import (
    _FILES_AN_ISSUE,
    _filing_units,
    _instruction_units,
)

# ---------------------------------------------------------------------------
# Homes
# ---------------------------------------------------------------------------

_REVIEW_DISCIPLINE = "skills/review-discipline/SKILL.md"
_CRAFT = "skills/review-discipline/references/craft.md"
_SPEC_AUTHORING = "skills/spec-authoring/SKILL.md"
_CODE_QUALITY = "skills/code-quality/SKILL.md"
_DIGEST = "commands/digest.md"
_BUILD = "commands/build.md"


# ---------------------------------------------------------------------------
# The text unit
# ---------------------------------------------------------------------------


def _units(text: str) -> list[str]:
    """Instruction units — paragraphs, list items, headings, **and table rows**.

    ``_instruction_units`` is imported, not re-spelled: it is the boundary every
    filing predicate in this tree is anchored on, and a fork of it is a fork of
    the unit those controls were written to hold. What it does not do is split a
    markdown table, because no filing instruction is a table row. Rule 4's home
    *is* a table row — the finding 2×2's large + non-blocking cell — and a merged
    table would let a term from one cell co-occur with a term from another, the
    over-wide unit ``craft.md`` → *The text unit is part of the predicate* names.
    So rows are carved out first and the imported splitter runs over what is left.
    """
    units: list[str] = []
    buffer: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("|"):
            if buffer:
                units.extend(_instruction_units("\n".join(buffer)))
                buffer = []
            units.append(" ".join(line.split()))
        else:
            buffer.append(line)
    if buffer:
        units.extend(_instruction_units("\n".join(buffer)))
    return units


# ---------------------------------------------------------------------------
# Rule 1 — the twin sweep
# ---------------------------------------------------------------------------

_TWIN = re.compile(r"\btwins?\b", re.IGNORECASE)
_SAME_BRANCH = re.compile(r"\bsame branch\b", re.IGNORECASE)
_DEFERRAL = re.compile(r"\bdefer\w*\b", re.IGNORECASE)


def _states_the_twin_sweep(text: str) -> list[str]:
    """Units requiring a mechanism's twin to move with it, or a recorded deferral.

    All three conjuncts carry weight. ``twin`` is what separates this from the
    as-built-record gate beside it in the same list — that bullet already says
    *explicit deferral naming the reason*, so a deferral-anchored predicate finds
    a home for this rule in the pre-change tree. ``same branch`` is the
    obligation and ``defer`` its only sanctioned escape: a rule that demands the
    twin move and records no alternative is a stricter, different rule.
    """
    return [
        unit
        for unit in _units(text)
        if _TWIN.search(unit) and _SAME_BRANCH.search(unit) and _DEFERRAL.search(unit)
    ]


# ---------------------------------------------------------------------------
# Rule 2 — novelty fails red
# ---------------------------------------------------------------------------

_ENUMERABLE = re.compile(r"\benumerable\b", re.IGNORECASE)
#: The failure verb **anchored to the member it governs**. A unit merely
#: containing ``unclassified`` and ``fail`` somewhere states nothing: the defect
#: shape ("a guard silently skips an unclassified member") names both words while
#: being the opposite of the rule. Six words is the gap every legitimate spelling
#: keeps ("fails on an unclassified member", "an unclassified member fails the
#: guard"); further off, the failure governs something else.
_FAILS_ON_THE_UNCLASSIFIED = re.compile(
    r"\bfail\w*\b(?:\W+\w+){0,6}?\W+unclassified\b"
    r"|\bunclassified\b(?:\W+\w+){0,6}?\W+fail\w*\b",
    re.IGNORECASE,
)


def _states_novelty_fails_red(text: str) -> list[str]:
    """Units requiring an enumerable-dimension guard to fail on an unclassified member."""
    return [
        unit
        for unit in _units(text)
        if _ENUMERABLE.search(unit) and _FAILS_ON_THE_UNCLASSIFIED.search(unit)
    ]


# ---------------------------------------------------------------------------
# Rule 3 — instrument replacement measures reach
# ---------------------------------------------------------------------------

_REPLACES = re.compile(r"\breplac\w+\b", re.IGNORECASE)
_REACH = re.compile(r"\breach\b", re.IGNORECASE)
_OMISSION = re.compile(r"\bomit\w*\b|\bomission\w*\b|\bomits\b", re.IGNORECASE)
_CRITERION = re.compile(r"\bacceptance criteri\w+\b|\bcriterion\b", re.IGNORECASE)


def _states_the_reach_measurement(text: str) -> list[str]:
    """Units requiring a replacement to be measured against the old source's reach.

    ``reach`` and ``omit`` are the pair that makes this rule itself. Without them
    the sentence says *verify the new form* — the measurement the rule exists to
    reject, since reading a replacement can only find what it contains.
    """
    return [
        unit
        for unit in _units(text)
        if _REPLACES.search(unit)
        and _REACH.search(unit)
        and _OMISSION.search(unit)
        and _CRITERION.search(unit)
    ]


# ---------------------------------------------------------------------------
# Rule 4 — bugs are filed; improvements are proposed
# ---------------------------------------------------------------------------

_FACTUAL = re.compile(r"\bfactual\b", re.IGNORECASE)
_CONTRADICTS = re.compile(r"\bcontradict\w*\b", re.IGNORECASE)
_BUG = re.compile(r"\bbugs?\b", re.IGNORECASE)
_IMPROVEMENT = re.compile(r"\bimprovements?\b", re.IGNORECASE)
_PROPOSED = re.compile(r"\bpropos\w+\b", re.IGNORECASE)


def _states_the_bug_improvement_line(text: str) -> list[str]:
    """Units stating the factual line between a filed bug and a proposed improvement.

    ``factual`` is a conjunct rather than decoration. The rule's whole content is
    that the line is *not* a judgment call, so a unit naming bugs, improvements
    and proposals without saying the test is factual has restated the vocabulary
    and dropped the rule. It is also what separates this statement of the rule
    from the commands that *apply* it, which name the same three nouns while
    deciding nothing.
    """
    return [
        unit
        for unit in _units(text)
        if _FACTUAL.search(unit)
        and _CONTRADICTS.search(unit)
        and _BUG.search(unit)
        and _IMPROVEMENT.search(unit)
        and _PROPOSED.search(unit)
    ]


#: The consequence the rule is stated with, so a later edit cannot keep the
#: mechanism and lose the point. The quantifier is a conjunct because it *is* the
#: claim: "an agent files fewer improvements" is the posture every hardening pass
#: before this one already had, and the thing rule 4 changes is that the volume
#: is structurally none. Occurrence this guard cites: reviewer mutation on this
#: ticket replaced the whole consequence paragraph with a sentence about
#: reviewer judgment and the mutation ran LIVE with the suite green — the
#: sentence the change spec asked for "so the intent survives" was pinned by
#: nothing.
_AGENT_CAN_FILE = re.compile(r"\bagents?\b(?:\W+\w+){0,4}?\W+file\w*\b", re.IGNORECASE)
_ZERO_VOLUME = re.compile(r"\bzero\b|\bnothing at all\b", re.IGNORECASE)


def _states_the_zero_agent_volume(text: str) -> list[str]:
    """Units stating that the improvement volume an agent can file is none.

    ``_AGENT_CAN_FILE`` is the one conjunct here with no exclusive killer of its
    own — recorded rather than papered over, the same way the residual list below
    is. Widening it leaves a predicate that still has to find *improvement* and a
    zero quantifier in one unit, which no other unit in the corpus carries.
    """
    return [
        unit
        for unit in _units(text)
        if _IMPROVEMENT.search(unit) and _AGENT_CAN_FILE.search(unit) and _ZERO_VOLUME.search(unit)
    ]


_PROMOTE = re.compile(r"\bpromot\w+\b", re.IGNORECASE)
_DROP = re.compile(r"\bdrops?\b|\bdropped\b|\bdropping\b", re.IGNORECASE)
_SILENCE = re.compile(r"\bsilence\b", re.IGNORECASE)


def _states_the_ratification(text: str) -> list[str]:
    """Units carrying the proposal channel's terminal semantics.

    Promote, drop, and *silence is a drop* are one decision procedure, and the
    third term is what makes it terminal: without it a proposal nobody answers
    persists, which is the standing queue the rule replaces.
    """
    return [
        unit
        for unit in _units(text)
        if _PROPOSED.search(unit)
        and _PROMOTE.search(unit)
        and _DROP.search(unit)
        and _SILENCE.search(unit)
    ]


#: The 2×2's non-blocking row, and the verdict its **large-fix** cell has to
#: carry. Matched against that one cell rather than the whole row: the row also
#: holds the small-fix verdict, so a row-wide search would read *propose it*
#: written in the wrong cell as the rule — the over-wide unit ``craft.md`` →
#: *The text unit is part of the predicate* names, one level below the unit
#: boundary :func:`_units` already draws.
_NON_BLOCKING_ROW = re.compile(r"^\|\s*\*{0,2}Non-blocking\*{0,2}\s*\|", re.IGNORECASE)
_PROPOSE_VERDICT = re.compile(r"\bpropose it\b", re.IGNORECASE)


def _non_blocking_large_verdict_proposes(text: str) -> list[str]:
    """Non-blocking rows of a 2×2 whose large-fix cell says *propose it* and files nothing.

    Two conditions on the same cell. *Propose it* is the verdict; the absence of
    a filing instruction is what makes it the rule rather than a renamed
    write-up, since a cell that proposes **and** files has closed nothing. The
    filing predicate is :data:`_FILES_AN_ISSUE`, imported — the same one that
    decides what a filing surface is everywhere else in this tree.
    """
    rows = [unit for unit in _units(text) if _NON_BLOCKING_ROW.match(unit)]
    return [
        row
        for row in rows
        if _PROPOSE_VERDICT.search(row.rsplit("|", 2)[-2])
        and not _FILES_AN_ISSUE.search(row.rsplit("|", 2)[-2])
    ]


#: The report contract's Proposals section, and the clause that makes it
#: mandatory. Both are conjuncts: a report shape that mentions a Proposals
#: section without saying what an empty one looks like is an optional section,
#: and an optional section is the silence the channel cannot afford — a proposal
#: raised into a section nobody had to write is dropped before `/digest` sees it.
_PROPOSALS_SECTION = re.compile(r"\bproposals\b\**\s+section\b", re.IGNORECASE)
_SECTION_IS_MANDATORY = re.compile(
    r"\bnone\b(?:\W+\w+){0,6}?\W+omitted\b|\bomitted\b(?:\W+\w+){0,6}?\W+none\b",
    re.IGNORECASE,
)


def _states_the_report_carries_proposals(text: str) -> list[str]:
    """Units defining a report shape that must carry a Proposals section."""
    return [
        unit
        for unit in _units(text)
        if _PROPOSALS_SECTION.search(unit) and _SECTION_IS_MANDATORY.search(unit)
    ]


def _splits_deferral_by_class(text: str) -> list[str]:
    """Filing units that route bugs and improvements down different paths.

    Derived from ``_filing_units`` — the imported predicate that decides what a
    filing surface *is* — rather than from every unit, because the claim is about
    the instruction that files: the bug branch must still file, in the same unit,
    or the surface stops being a filing surface at all.
    """
    return [
        unit
        for unit in _filing_units(text)
        if _BUG.search(unit) and _IMPROVEMENT.search(unit) and _PROPOSED.search(unit)
    ]


# ---------------------------------------------------------------------------
# Rule 5 — the R line
# ---------------------------------------------------------------------------

_OPENED = re.compile(r"\bopened\b", re.IGNORECASE)
_CLOSED = re.compile(r"\bclosed\b", re.IGNORECASE)
_PROMOTED_SOURCE = re.compile(r"\boperator-promoted\b", re.IGNORECASE)
_DIRECT_SOURCE = re.compile(r"\boperator-direct\b", re.IGNORECASE)


def _states_the_r_line(text: str) -> list[str]:
    """Units requiring opened-versus-closed counts, split by source.

    The two source names are conjuncts because the ratio is the point: an
    opened-versus-closed count with no source split cannot distinguish a queue
    the operator chose to grow from one the agents grew by themselves.
    """
    return [
        unit
        for unit in _units(text)
        if _OPENED.search(unit)
        and _CLOSED.search(unit)
        and _PROMOTED_SOURCE.search(unit)
        and _DIRECT_SOURCE.search(unit)
    ]


# ---------------------------------------------------------------------------
# Rule 6 — a guard cites the occurrence it prevents
# ---------------------------------------------------------------------------

_SPECULATIVE = re.compile(r"\bspeculative\w*\b", re.IGNORECASE)
_GUARD = re.compile(r"\bguards?\b", re.IGNORECASE)
_OCCURRENCE = re.compile(r"\boccurr\w*\b", re.IGNORECASE)


def _states_the_occurrence_citation(text: str) -> list[str]:
    """Units requiring a new guard to cite the defect class that already occurred."""
    return [
        unit
        for unit in _units(text)
        if _SPECULATIVE.search(unit) and _GUARD.search(unit) and _OCCURRENCE.search(unit)
    ]


# ---------------------------------------------------------------------------
# The corpus floor
# ---------------------------------------------------------------------------

#: Measured at 52 registered markdown files, with the floor just under it.
#: Membership is pinned separately: a cardinality floor alone is satisfied by a
#: corpus that swapped every home for an unrelated file.
_CORPUS_FLOOR = 50

#: The six homes plus one file that must stay *outside* every home — pinned by
#: name so a narrowed derivation names itself instead of shrinking behind a count.
_KNOWN_CORPUS_MEMBERS = (
    _REVIEW_DISCIPLINE,
    _CRAFT,
    _SPEC_AUTHORING,
    _CODE_QUALITY,
    _DIGEST,
    _BUILD,
    "skills/tracker/SKILL.md",
)


def test_the_registered_corpus_is_populated() -> None:
    """FLOOR. Every exclusivity assertion below searches this set.

    A derivation narrowed to ``[]`` fails those loudly; one narrowed to
    *everything except the homes* fails them for a reason nobody could read.
    Both are excluded here, once, so the per-rule failures mean what they say.
    """
    corpus = _registered_markdown()
    assert len(corpus) >= _CORPUS_FLOOR, (
        f"only {len(corpus)} registered markdown files derived from registry.yaml, "
        f"under the floor of {_CORPUS_FLOOR} — the placement sweeps below would be "
        f"searching a corpus that is no longer the installed surface"
    )
    missing = [rel for rel in _KNOWN_CORPUS_MEMBERS if rel not in corpus]
    assert not missing, f"the registered corpus lost known member(s): {missing}"


def test_the_twin_sweep_has_a_home() -> None:
    """R1: the reviewer's obligations require a mechanism's twin to move with it."""
    assert _states_the_twin_sweep(_read(_REVIEW_DISCIPLINE)), (
        f"{_REVIEW_DISCIPLINE} does not require the twin of a changed mechanism to "
        f"be updated in the same branch or explicitly deferred. A template, a "
        f"mirror, or a hook's guard left behind ships green — the guard over the "
        f"original still passes and the stale copy is what the next reader reaches."
    )


def test_the_twin_sweep_has_exactly_one_home() -> None:
    """R1 is stated once — AC-1's no-restatement half, which the home test cannot see."""
    homes = {rel for rel in _registered_markdown() if _states_the_twin_sweep(_read(rel))}
    assert homes == {_REVIEW_DISCIPLINE}, (
        f"the twin sweep is stated in {sorted(homes)}; it belongs in "
        f"{_REVIEW_DISCIPLINE} alone."
    )


def test_novelty_fails_red_has_a_home() -> None:
    """R2: the craft reference carries the unclassified-member class."""
    assert _states_novelty_fails_red(_read(_CRAFT)), (
        f"{_CRAFT} does not require a guard over an enumerable dimension to fail on "
        f"an unclassified member. A classifier whose default branch means 'not my "
        f"subject' stops covering a whole class the day one is added, and reports "
        f"green over the members it still knows."
    )


def test_novelty_fails_red_has_exactly_one_home() -> None:
    """R2 is stated once."""
    homes = {rel for rel in _registered_markdown() if _states_novelty_fails_red(_read(rel))}
    assert homes == {_CRAFT}, (
        f"the unclassified-member rule is stated in {sorted(homes)}; it belongs in "
        f"{_CRAFT} alone."
    )


def test_the_reach_measurement_has_a_home() -> None:
    """R3: spec-authoring requires a replacement to be measured against the old reach."""
    assert _states_the_reach_measurement(_read(_SPEC_AUTHORING)), (
        f"{_SPEC_AUTHORING} does not require an acceptance criterion measuring a "
        f"replacement source against what the old one held. Verifying the new "
        f"form's content passes over every omission by construction."
    )


def test_the_reach_measurement_has_exactly_one_home() -> None:
    """R3 is stated once."""
    homes = {rel for rel in _registered_markdown() if _states_the_reach_measurement(_read(rel))}
    assert homes == {_SPEC_AUTHORING}, (
        f"the reach-measurement rule is stated in {sorted(homes)}; it belongs in "
        f"{_SPEC_AUTHORING} alone."
    )


# ---------------------------------------------------------------------------
# Rule 4 — the line, the ratification step, and the aligned DEFER path
# ---------------------------------------------------------------------------


def test_the_bug_improvement_line_has_a_home() -> None:
    """R4: the factual line between filing a bug and proposing an improvement."""
    assert _states_the_bug_improvement_line(_read(_REVIEW_DISCIPLINE)), (
        f"{_REVIEW_DISCIPLINE} does not state the factual line between a bug, which "
        f"any agent files, and an improvement, which is proposed and never filed. "
        f"Without it the split is a judgment call, and a judgment call is how every "
        f"finding became a ticket."
    )


def test_the_bug_improvement_line_has_exactly_one_home() -> None:
    """R4's rule is stated once; the commands that apply it point at it instead."""
    homes = {rel for rel in _registered_markdown() if _states_the_bug_improvement_line(_read(rel))}
    assert homes == {_REVIEW_DISCIPLINE}, (
        f"the bug/improvement line is stated in {sorted(homes)}; it belongs in "
        f"{_REVIEW_DISCIPLINE} alone — the surfaces that apply it cross-reference it."
    )


def test_the_non_blocking_large_cell_proposes() -> None:
    """R4 in the 2×2 itself: the cell the rule renames, read from the shipped table.

    The bug/improvement line above is a paragraph, and a paragraph can state the
    rule while the table a reviewer actually reads still routes the finding to a
    ticket. This asserts the cell, which is the surface that decides.
    """
    rows = _non_blocking_large_verdict_proposes(_read(_REVIEW_DISCIPLINE))
    assert len(rows) == 1, (
        f"{_REVIEW_DISCIPLINE}'s finding 2×2 has {len(rows)} non-blocking rows whose "
        f"large-fix cell proposes without filing; it must have exactly one. A cell "
        f"that still writes the finding up through the tracker is the filing path "
        f"rule 4 closes, wearing the new vocabulary."
    )


def test_the_report_contract_requires_a_proposals_section() -> None:
    """R4's other half: a proposal has a place to land in the report, always.

    The channel is one line in a report section, so the report contract is the
    only thing that makes a proposal exist at all. Stated as an optional section
    it would be indistinguishable from the write-ups it replaces — raised when
    someone remembered, invisible when nobody did.
    """
    assert _states_the_report_carries_proposals(_read(_REVIEW_DISCIPLINE)), (
        f"{_REVIEW_DISCIPLINE}'s report contract does not require a Proposals "
        f"section that is written even when empty. A section a report may omit "
        f"gives `/digest` nothing to read and no way to tell an empty window from "
        f"a forgotten one."
    )


def test_the_zero_agent_volume_consequence_is_stated() -> None:
    """R4's consequence, which is the half a later edit drops while keeping the rest.

    The mechanism — propose, ratify, promote — reads as a routing change on its
    own, and a routing change survives being routed back. What makes it rule 4 is
    that the improvement volume an agent can file is **none**, and that sentence
    is the only thing in the file that says so.
    """
    assert _states_the_zero_agent_volume(_read(_REVIEW_DISCIPLINE)), (
        f"{_REVIEW_DISCIPLINE} no longer states that the improvement volume an "
        f"agent can file is zero. Without it the file describes a channel and not "
        f"a bound, and a later edit can keep every step of the mechanism while "
        f"handing the filing grant back."
    )


def test_the_report_contract_predicates_discriminate() -> None:
    """Paired controls for the two report-contract predicates above.

    Each negative is the near-miss the cheaper predicate accepts: the verdict
    written into the wrong cell of the right row, a cell that proposes *and*
    files, and a Proposals section nobody has to write.
    """
    row = (
        "| **Non-blocking** | Fix now, in this branch | **Propose it** — one line in "
        "the report's **Proposals** section, and nowhere else |"
    )
    assert _non_blocking_large_verdict_proposes(row) == [" ".join(row.split())]

    wrong_cell = (
        "| **Non-blocking** | Propose it, in this branch | Write it up as a ticket |"
    )
    assert _non_blocking_large_verdict_proposes(wrong_cell) == [], (
        "the verdict is being read from the whole row — a `propose it` in the "
        "small-fix cell satisfies a claim about the large-fix cell"
    )

    proposes_and_files = (
        "| **Non-blocking** | Fix now, in this branch | **Propose it** — one line in "
        "the report, then create the follow-up through `tracker` |"
    )
    assert _non_blocking_large_verdict_proposes(proposes_and_files) == [], (
        "a cell that proposes and files is read as the rule — the renamed cell "
        "still queues, which is the grant rule 4 exists to close"
    )

    contract = (
        "- **Report:** a one-line verdict, a **Proposals** section carrying every "
        "improvement this review proposes — one line each, or the word `none`, "
        "never an omitted section — and the verification output."
    )
    assert _states_the_report_carries_proposals(contract) == [" ".join(contract.split())]

    optional = (
        "- **Report:** a one-line verdict, a **Proposals** section where the review "
        "has improvements to raise, and the verification output."
    )
    assert _states_the_report_carries_proposals(optional) == [], (
        "an optional Proposals section is read as the contract — nothing then "
        "distinguishes an empty window from a report that forgot the section"
    )

    consequence = (
        "State the consequence with the rule: the improvement volume an agent can "
        "file is structurally zero, and the queue holds nothing else."
    )
    assert _states_the_zero_agent_volume(consequence) == [" ".join(consequence.split())]

    softened = (
        "State the consequence with the rule: the improvement volume an agent can "
        "file is kept as low as the review process can push it."
    )
    assert _states_the_zero_agent_volume(softened) == [], (
        "the quantifier is not a conjunct — a bound softened from none to fewer "
        "reads as the rule, which is the posture every earlier hardening pass had"
    )

    not_improvements = (
        "State the consequence with the rule: the ticket volume an agent can file "
        "is structurally zero."
    )
    assert _states_the_zero_agent_volume(not_improvements) == [], (
        "a claim about tickets in general is read as the claim about improvements "
        "— the bug half of the rule files tickets, and always did"
    )


def test_the_ratification_step_has_a_home() -> None:
    """R4: the digest is where a proposal is promoted or dropped, and silence drops it."""
    assert _states_the_ratification(_read(_DIGEST)), (
        f"{_DIGEST} does not carry the proposal ratification step — promote, drop, "
        f"and silence is a drop. A proposal with no terminal answer is the standing "
        f"queue this rule replaces, wearing a different name."
    )


def test_the_ratification_step_has_exactly_one_home() -> None:
    """R4's ratification semantics are stated once, in the command that performs them."""
    homes = {rel for rel in _registered_markdown() if _states_the_ratification(_read(rel))}
    assert homes == {_DIGEST}, (
        f"the ratification semantics are stated in {sorted(homes)}; they belong in "
        f"{_DIGEST} alone."
    )


def test_the_defer_path_splits_bugs_from_improvements() -> None:
    """R4's alignment: the build command's DEFER path routes the two classes apart.

    Home only, with no exclusivity companion, and the asymmetry is deliberate: the
    *rule* has one home and is asserted exclusive above, while *applying* it is
    something several surfaces may legitimately do. An exclusivity assertion here
    would go red the first time another command aligned correctly.
    """
    assert _splits_deferral_by_class(_read(_BUILD)), (
        f"{_BUILD}'s DEFER path does not separate a bug, which files, from an "
        f"improvement, which is proposed. Routing both through `tracker.create` is "
        f"the agent-filing grant rule 4 closes."
    )


def test_the_defer_path_stays_a_filing_surface_with_its_rubric_pointer() -> None:
    """R4's alignment must not cost the build command its filing-surface status.

    ``test_assurance_filing_surfaces`` derives filing surfaces from the registry
    and names this file in a membership floor, then requires the *filing
    instruction itself* to name the assurance rubric. Splitting the DEFER path
    could satisfy rule 4 by routing everything to proposals — which would delete a
    filing surface and take its rubric pointer with it. Both halves are asserted
    on the same unit, because that is the unit the other module measures.
    """
    units = _splits_deferral_by_class(_read(_BUILD))
    assert units, "no split DEFER filing unit — see the test above"
    assert any(_delegates_the_level_choice(unit) for unit in units), (
        f"{_BUILD}'s split DEFER path files without naming `spec-authoring` → "
        f"*Choosing assurance* in the instruction that files. The bug branch still "
        f"creates a ticket, so it still owes the level choice to the one rubric."
    )


def test_the_r_line_has_a_home() -> None:
    """R5: the digest reports opened versus closed, split by source."""
    assert _states_the_r_line(_read(_DIGEST)), (
        f"{_DIGEST} does not report the window's tickets opened versus closed with "
        f"the opened count split by source. The retrospective that produced these "
        f"rules was done by eyeball; the line is what makes it ambient."
    )


def test_the_r_line_has_exactly_one_home() -> None:
    """R5 is stated once."""
    homes = {rel for rel in _registered_markdown() if _states_the_r_line(_read(rel))}
    assert homes == {_DIGEST}, (
        f"the R line is stated in {sorted(homes)}; it belongs in {_DIGEST} alone."
    )


def test_the_occurrence_citation_has_a_home() -> None:
    """R6: a new guard names the occurred defect class it prevents."""
    assert _states_the_occurrence_citation(_read(_CODE_QUALITY)), (
        f"{_CODE_QUALITY} does not require a new guard to cite the occurrence it "
        f"prevents. A speculative guard costs the same to read, run, and maintain "
        f"as a real one while defending nothing."
    )


def test_the_occurrence_citation_has_exactly_one_home() -> None:
    """R6 is stated once — and deliberately not restated in the assess command."""
    homes = {rel for rel in _registered_markdown() if _states_the_occurrence_citation(_read(rel))}
    assert homes == {_CODE_QUALITY}, (
        f"the occurrence-citation rule is stated in {sorted(homes)}; it belongs in "
        f"{_CODE_QUALITY} alone. Its retirement consequence is stated there too, "
        f"not copied into the command that acts on it."
    )


# ---------------------------------------------------------------------------
# The digest's derived twin: its section count and the number word claiming it
# ---------------------------------------------------------------------------

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_NUMBER_ALTERNATION = "|".join(_NUMBER_WORDS)
_NUMBERED_SECTION = re.compile(r"^\d+\.\s+\*\*", re.MULTILINE)
#: Both spellings the document uses to claim its own section count: the intro's
#: *"always all four"* and the output line's *"the four sections"*. Written as two
#: anchored alternatives rather than one loose window, because a window wide
#: enough to catch *"Sections — always all four"* backwards also catches
#: *"sections, each item one or two lines"* and demands a count of one.
_SECTION_COUNT_CLAIM = re.compile(
    rf"\ball ({_NUMBER_ALTERNATION})\b|\b({_NUMBER_ALTERNATION}) sections?\b",
    re.IGNORECASE,
)


def _numbered_sections(text: str) -> list[str]:
    """The document's own numbered section headings."""
    return _NUMBERED_SECTION.findall(text)


def _claimed_section_counts(text: str) -> list[int]:
    """Every count this document claims about its own sections, as integers."""
    return [
        _NUMBER_WORDS[(match.group(1) or match.group(2)).lower()]
        for match in _SECTION_COUNT_CLAIM.finditer(text)
    ]


def test_the_digest_section_count_matches_every_claim_it_makes() -> None:
    """The digest's prose count is a derived twin of its own numbered sections.

    The document says *"always all four, in this order"* and, further down,
    *"Then the four sections"*. Both are restatements of a fact the numbered
    headings already carry, and both are the shape rule 1 exists to catch: adding
    a section updates the list and leaves the two number words stale, with nothing
    red. Deriving the count and comparing it against every claim is the cheap
    version of the sweep the rule asks a reviewer to do by hand — and it is this
    change's own twin, since this change adds the section.
    """
    text = _read(_DIGEST)
    derived = len(_numbered_sections(text))
    assert derived >= 4, (
        f"only {derived} numbered sections derived from {_DIGEST} — the heading "
        f"shape changed, and the comparison below would be measuring nothing"
    )
    claims = _claimed_section_counts(text)
    assert claims, f"{_DIGEST} makes no numeric claim about its section count to check"
    wrong = [claimed for claimed in claims if claimed != derived]
    assert not wrong, (
        f"{_DIGEST} carries {derived} numbered sections but claims {wrong} — the "
        f"prose count and the list it describes have drifted apart"
    )


# ---------------------------------------------------------------------------
# The controls — every predicate, positive and negative, through the real function
# ---------------------------------------------------------------------------


def test_the_placement_predicates_discriminate() -> None:
    """Paired controls for the seven placement predicates, through the real functions.

    Each negative is a **near-miss**: prose about the rule's own subject that a
    looser predicate — one conjunct short, or one anchor unanchored — would
    accept. A control that fed each predicate obviously unrelated text would pass
    forever while the predicate degraded into a keyword sweep.
    """
    # R1. The near-miss is the obligation with no sanctioned escape: a rule that
    # cannot be deferred is one people quietly skip rather than record.
    twin = (
        "- **Sweep for twins.** A mechanism with a derived or distributed twin — a "
        "template, a mirror, a hook and its guard — has that twin updated in the "
        "same branch, or the review records an explicit deferral naming the reason."
    )
    assert _states_the_twin_sweep(twin) == [" ".join(twin.split())]
    no_escape = (
        "- A mechanism with a distributed twin has that twin updated in the same branch."
    )
    assert _states_the_twin_sweep(no_escape) == []
    # ...and the neighbour a twin-blind predicate takes for a home: the
    # as-built-record gate states the same obligation, in the same branch, with
    # the same recorded escape, about a subject that is not a twin. Measured —
    # dropping the `twin` conjunct survived every other control in this test.
    as_built = (
        "- **Record reality on PASS.** The as-built-record update lands in the "
        "same branch as the behaviour it documents, or the review records an "
        "explicit deferral naming the reason."
    )
    assert _states_the_twin_sweep(as_built) == [], (
        "the twin sweep's predicate reads any same-branch-or-defer obligation as "
        "its home — `twin` is what makes it this rule and not the one beside it"
    )

    # R2. The near-miss names both words while stating the defect, not the rule.
    novelty = (
        "A guard over an enumerable dimension fails on an unclassified member "
        "rather than skipping it."
    )
    assert _states_novelty_fails_red(novelty) == [novelty]
    describes_the_defect = (
        "A guard over an enumerable dimension is free to fail for any of the usual "
        "reasons, and it silently skips an unclassified member."
    )
    assert _states_novelty_fails_red(describes_the_defect) == [], (
        "the predicate accepts a sentence describing the defect as the rule — the "
        "failure verb is not anchored to the member it has to govern"
    )

    # R3. The near-miss is the wrong measurement, which is the whole point of the
    # rule: verifying the replacement can only find what the replacement holds.
    reach = (
        "When a change replaces an information source, one acceptance criterion "
        "measures the new form against the old one's reach: what did the source "
        "hold that the replacement omits?"
    )
    assert _states_the_reach_measurement(reach) == [reach]
    verifies_content = (
        "When a change replaces an information source, an acceptance criterion "
        "verifies that the new form states the rules it should."
    )
    assert _states_the_reach_measurement(verifies_content) == []

    # R4's line. The near-miss names all three nouns and drops the one word that
    # makes the split a test rather than a preference.
    line = (
        "The line is factual, not judged: a tree that contradicts its own contract "
        "today is a bug and any agent files it; everything else is an improvement, "
        "and an improvement is proposed, never filed."
    )
    assert _states_the_bug_improvement_line(line) == [line]
    judged = (
        "A tree that contradicts its own contract is a bug; anything else is an "
        "improvement, and the reviewer decides whether to propose it."
    )
    assert _states_the_bug_improvement_line(judged) == []

    # R4's ratification. The near-miss is the same procedure with no terminal
    # answer for the proposal nobody responds to.
    ratified = (
        "The operator promotes the proposal — it becomes a ticket — or drops it, "
        "and silence is a drop."
    )
    assert _states_the_ratification(ratified) == [ratified]
    no_terminal = "The operator promotes the proposal into a ticket, or drops it."
    assert _states_the_ratification(no_terminal) == []

    # R4's DEFER split, through `_filing_units` — so the control also proves the
    # bug branch is still a filing instruction, which is the constraint the
    # neighbouring module measures.
    defer = (
        "- **DEFER:** a bug is filed — create the follow-up through `tracker` with "
        "exactly one assurance level, chosen per `spec-authoring` → *Choosing "
        "assurance*. An improvement is proposed instead."
    )
    split = _splits_deferral_by_class(defer)
    assert split, "the split-DEFER predicate no longer matches a real filing spelling"
    assert any(_delegates_the_level_choice(unit) for unit in split)
    proposals_only = (
        "- **DEFER:** every out-of-scope finding is proposed rather than filed, bug "
        "or improvement alike."
    )
    assert _splits_deferral_by_class(proposals_only) == [], (
        "a DEFER path that files nothing is read as a split — it is a deleted "
        "filing surface, and the rubric-pointer assertion would go with it"
    )

    # R5. The near-miss is the ratio with no source split, which cannot tell a
    # queue the operator grew from one the agents grew.
    r_line = (
        "Close with the R line: tickets opened versus closed this window, the "
        "opened count split by source — use, operator-promoted, operator-direct."
    )
    assert _states_the_r_line(r_line) == [r_line]
    unsplit = "Close with the count of tickets opened and closed this window."
    assert _states_the_r_line(unsplit) == []

    # R6. The near-miss names the guard and the occurrence without the polarity
    # that makes an uncitable guard a deletion candidate.
    citation = (
        "A guard nobody can trace to an occurrence — a `craft.md` entry, a red "
        "gate, a shipped bug — is speculative, and a speculative guard defends "
        "nothing."
    )
    assert _states_the_occurrence_citation(citation) == [citation]
    no_speculation = "A guard should cite the occurrence that motivated it."
    assert _states_the_occurrence_citation(no_speculation) == []


def test_the_subject_conjuncts_are_not_redundant() -> None:
    """Each near-miss keeps every discriminating term and drops the subject noun.

    Measured before this test existed: widening any of these conjuncts to match
    everything survived *both* the control test above and every exclusivity
    assertion, because the remaining conjuncts still identify the one home in
    today's tree. That is two redundant conditions hiding each other from
    mutation (``craft.md``), and the fix is a sample that only the dropped
    conjunct excludes.

    What is still not pinned this way, measured one conjunct at a time and
    recorded rather than papered over: ``replaces``, ``reach``, ``omit``,
    ``bug``, ``contradicts``, ``promote``, ``drop``, ``opened``,
    ``operator-promoted``, ``operator-direct`` and ``occurrence`` each survive
    being widened alone, because a sibling conjunct still identifies the home —
    ``reach``/``omit`` and the two source names are each other's redundancy, and
    die when widened as a pair. Closing the rest takes one bespoke sample per
    term and buys a predicate no better at telling the rule from its neighbour,
    which is the only thing these predicates have to do.
    """
    for predicate, near_miss in (
        # R2 without its dimension: one token classifier, not an enumerable set.
        (_states_novelty_fails_red, "A parser fails on an unclassified token."),
        # R3 without its obligation: an observation about reach, not a criterion.
        (
            _states_the_reach_measurement,
            "A distillation replaces its source and its reach shrinks; what it "
            "omits is invisible to a reader of the new form.",
        ),
        # R4's line without the improvement half: a bug rule with nothing opposite.
        (
            _states_the_bug_improvement_line,
            "The line is factual, not judged: a tree that contradicts its own "
            "contract is a bug, and the proposal to fix it is the ticket.",
        ),
        # R4's ratification applied to tickets, which have their own procedure.
        (
            _states_the_ratification,
            "The operator promotes the ticket or drops it, and silence is a drop.",
        ),
        # R5 without the closing half: an intake count, which is not a ratio.
        (
            _states_the_r_line,
            "Count tickets opened by source — operator-promoted, operator-direct.",
        ),
        # R6 without its subject: a rule about speculative work in general.
        (
            _states_the_occurrence_citation,
            "A speculative feature nobody can trace to an occurrence is deleted.",
        ),
    ):
        assert predicate(near_miss) == [], (
            f"{predicate.__name__} matched a near-miss that drops its subject "
            f"noun: {near_miss!r}"
        )


def test_the_unit_boundary_splits_table_rows() -> None:
    """The 2×2's cells are separate units, which the imported splitter alone does not do.

    Rule 4's home is a table cell. If the table merged into one unit, a term in
    the blocking row would co-occur with a term in the non-blocking row, and the
    home assertion would pass on a table that states the rule nowhere. Measured
    both ways here: the merged reading finds a home in a table that has none, and
    the split reading does not.
    """
    table = (
        "|  | Small fix | Large fix |\n"
        "|---|---|---|\n"
        "| **Blocking** | Fix now | FAIL — the ticket cannot ship as scoped |\n"
        "| **Non-blocking** | Fix now | Propose it |\n"
    )
    rows = [unit for unit in _units(table) if unit.startswith("|")]
    assert len(rows) == 4, f"the table did not split into its four rows: {rows}"
    assert not any("Blocking" in row and "Propose it" in row for row in rows[:3]), (
        "a cell from the blocking row is sharing a unit with the non-blocking "
        "verdict — the table is being read as one span"
    )
    assert _instruction_units(table) == [" ".join(table.split())], (
        "the imported splitter no longer merges a table — this module's extra "
        "carve-out is now a second, redundant boundary and should be dropped"
    )


def test_the_section_count_predicates_discriminate() -> None:
    """The derived-twin comparison, both ways, on synthetic documents."""
    drifted = (
        "## Sections — always all four, in this order\n\n"
        "1. **A.** x\n2. **B.** y\n3. **C.** z\n4. **D.** w\n5. **E.** v\n\n"
        "Then the four sections, each item one or two lines.\n"
    )
    assert len(_numbered_sections(drifted)) == 5
    assert _claimed_section_counts(drifted) == [4, 4]

    consistent = drifted.replace("all four", "all five").replace(
        "the four sections", "the five sections"
    )
    assert _claimed_section_counts(consistent) == [5, 5]

    # Discrimination: the claim reader must not invent a count out of prose that
    # is not about sections. "each item one or two lines" trails the word
    # `sections` closely enough for a backwards window to swallow it.
    assert _claimed_section_counts("Then the sections, each item one or two lines.\n") == []


def test_the_module_reads_the_repo_it_is_checked_into() -> None:
    """The imported repo root resolves to a tree carrying the registry.

    A floor on the import itself: every read above goes through `_read`, which
    joins onto `_REPO_ROOT`. If that resolved somewhere without a `registry.yaml`,
    the corpus derivation would raise rather than pass — but a *different* harness
    checkout would resolve fine and quietly measure the wrong tree.
    """
    assert (_REPO_ROOT / "registry.yaml").is_file()
    assert (_REPO_ROOT / _DIGEST).is_file(), f"{_DIGEST} is not in the tree {_REPO_ROOT}"
