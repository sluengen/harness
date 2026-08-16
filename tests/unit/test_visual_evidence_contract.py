"""#434 — visual evidence for the agent-led review, as a prose + ignore contract.

#361 built the visual-evidence channel for the retired review engine; ADR 0015
retires the engine and keeps the capability. The obligations now live entirely in
the distributed guidance, so this module is where they are held:

* **the capture convention** — when captures are produced, where they land, that
  they are viewport-height slices, the maximum capture height and its
  measurement, and the capture-count cap — all in ``commands/build.md``, the file
  where captures are produced;
* **the handoff** — ``commands/review.md`` step 3 supplies the directory;
* **the report line** — ``skills/review-discipline/SKILL.md``'s ``Report:``
  bullet is the one home for the consulted / not-consulted reason set, rendered
  (never restated) by ``agents/reviewer.md`` and ``commands/review.md`` step 5;
* **the ignore rule** — ``.gitignore`` keeps a binary capture of seeded state out
  of a public repo's permanent history.

Every prose obligation is a **pair**: a presence assertion that dies when the
rule is deleted, and an inversion sweep that fires when a release is *appended*
while the rule survives. #288 measured why the second half is not optional — a
rule's own ``never`` shields the sentence appended after it, so a
"is this section negated" predicate is fail-open. Every negated-verb pattern here
is therefore built as a negation + :data:`_NEGATION_GAP` + the verb, and every
sweep matches **per occurrence** (``match.end() not in negated``), never per
sentence: an unanchored negation reads *"does not preclude capturing the full
page"* as a prohibition and computes the opposite boolean.

Two guards are honest exceptions, stated here rather than papered over, and
repeated in their own docstrings:
:func:`test_the_evidence_ignore_does_not_hide_a_tracked_reference_image` is an
over-breadth guard on a rule that did not exist before this change, so no edit to
the pre-change tree could redden it — it is proven by mutation, not by RED-first;
:func:`test_no_visual_evidence_is_tracked_in_the_live_repo` is a live-repo
hygiene guard that no textual mutation reaches at all.
"""

# size: one ticket's acceptance suite — four documents' worth of prose
# obligations (AC-1..AC-3), each as a *paired* presence assertion and inversion
# sweep with its own exclusive killer (AC-4 is that pairing), plus the two
# single-home guards, the behavioural ignore pair (AC-5), the paraphrase sets,
# and the one control that splices every sweep into the real file text. The
# length is that enumeration rather than accreted logic: pairing is this
# ticket's own subject, so each obligation costs two assertions and a control
# splice by construction. Splitting by AC was considered and rejected — the
# control and the polarity predicates are shared across the ACs, so a split
# would buy a shorter file at the price of a cross-module import of the very
# predicates whose honesty is the thing under test.

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests._gitutil import tracked_files_under

# `_sentences` (the unit boundary), `_section` (the scope), `_units` (the
# wrap-insensitive re-join the controls need), `_EMPHASIS` (bold stripped before
# any anchored predicate runs) and `_NEGATION_GAP` (what a negation may reach
# across, blocking verbs excluded) are #354's and #288's, and every polarity
# predicate below is only as honest as they are. Importing across test modules
# is the established pattern here — `test_assurance_filing_surfaces` imports
# from `test_assurance_filing_rubric` for the same reason. (`_units`,
# `_EMPHASIS` and `_NEGATION_GAP` were #288's and reached this module from
# `test_build_assurance_workflow` until #435 deleted it with the verb loop it
# described; they now live beside `_sentences` and `_section` in the one module
# that owns the boundary.) Re-spelling them here would fork the very boundary
# #288's controls were written to hold.
from tests.unit.test_assurance_filing_rubric import (
    _EMPHASIS,
    _NEGATION_GAP,
    _section,
    _sentences,
    _units,
)
from tests.unit.test_worktree_ignore_hygiene import _git, _init_hermetic_repo

_REPO_ROOT = Path(__file__).resolve().parents[2]

BUILD = _REPO_ROOT / "commands" / "build.md"
REVIEW = _REPO_ROOT / "commands" / "review.md"
START = _REPO_ROOT / "commands" / "start.md"
REVIEWER = _REPO_ROOT / "agents" / "reviewer.md"
DISCIPLINE = _REPO_ROOT / "skills" / "review-discipline" / "SKILL.md"

_VISUAL_SECTION = "### Visual evidence for a user-facing change"
_HANDOFF_STEP = "### 3. Run the reviewer"
_REPORT_STEP = "### 5. Report"
_OBLIGATIONS = "## Reviewer obligations"
_BUILD_STEP = "### 6. Build"

#: The capture directory, keyed per ticket. Flat under the worktree root — not
#: nested under a `visual/` intermediate — so `/review` hands the reviewer one
#: path.
_EVIDENCE_DIR = ".evidence/"
#: The backstop on a single capture's height, and the review-wide capture count.
#: Both are asserted as *derived* values — parsed out of the prose that states
#: them — so a re-worded rule fails rather than a restated constant agreeing
#: with itself.
_MAX_HEIGHT_PX = 2000
_MAX_CAPTURES = 12
#: The closed reason set for a `not consulted` line. Three, not two: Codex has
#: no image-returning read tool (`specs/proposals/visual-evidence-for-review.md`),
#: so without the third a Codex reviewer must either claim `consulted` or pick a
#: false reason.
_NOT_CONSULTED_REASONS = (
    "not a user-facing change",
    "not supplied",
    "not readable by this reviewer",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The shared polarity machinery
# ---------------------------------------------------------------------------

#: What counts as a negation for the anchored predicates below. ``no`` earns its
#: place: the height rule is spelled *"**No capture exceeds 2000 px in
#: height**"*, so a predicate that cannot read ``no`` reads that sentence as an
#: un-negated capture instruction.
_NEGATION = (
    r"never|must not|may not|cannot|can not|does not|do not|is not|are not|"
    r"no|nor|without|neither"
)


def _negated(verbs: str) -> re.Pattern[str]:
    """A negation governing ``verbs``, across :data:`_NEGATION_GAP`, **at the end**.

    The gap excludes blocking verbs, which is #288's measured fix: anchored
    naively, *"does not preclude capturing the full page"* scores as *"never
    captures the full page"* — the opposite boolean — and leaves the sweep green
    on text that grants exactly what the rule forbids.

    The trailing ``\\s*$`` is this module's own addition, and it is not
    cosmetic. :func:`_ungoverned` asks about one occurrence by matching against
    the text *up to and including* it; without the anchor ``search`` is free to
    satisfy the pattern anywhere earlier in that prefix, so the predicate
    degrades to *"is there any negated verb earlier in this unit"* — the
    per-sentence fail-open shape #288 closed, where a rule's own ``Never``
    shields a release sharing its sentence. Measured, both spellings, on the
    real documents: *"Never capture the full page in one image, but capture the
    whole page when it is short."* is **one** offender anchored and **zero**
    unanchored. Anchoring makes the engine backtrack the gap onto whichever
    occurrence is being asked about, so every verb a negation reaches is covered
    and no other. Splice 10 of the control is what holds this; nothing else in
    the suite reaches it, because every real unit and every other splice puts
    the release in a sentence of its own.
    """
    return re.compile(
        rf"\b(?:{_NEGATION})\b{_NEGATION_GAP}\s+(?:{verbs})\s*$", re.IGNORECASE
    )


def _ungoverned(unit: str, verbs: str) -> list[str]:
    """Occurrences of ``verbs`` in ``unit`` that no negation governs.

    Per occurrence, never per sentence: a rule's own ``Never`` must not shield a
    clause appended after it, which is the fail-open shape #288 spent three
    review cycles closing. Each occurrence is asked about separately, by
    matching :func:`_negated` against the text *up to and including* it.
    """
    plain = _EMPHASIS.sub(" ", unit)
    governed = _negated(verbs)
    return [
        match.group(0)
        for match in re.finditer(rf"(?:{verbs})", plain, re.IGNORECASE)
        if not governed.search(plain[: match.end()])
    ]


def _released(text: str, subject: re.Pattern[str], release: str) -> list[str]:
    """Units of ``text`` that name ``subject`` and carry an un-negated ``release``.

    The inversion half of every pair below. It answers *"has anything appended
    to this document granted an exception to the rule"*, which is a different
    question from *"is the rule still stated"* — and it is the half that a
    deleted-and-replaced rule, or an exception bolted onto a surviving one,
    fails.
    """
    return [
        unit
        for unit in _sentences(text)
        if subject.search(_EMPHASIS.sub(" ", unit)) and _ungoverned(unit, release)
    ]


# ---------------------------------------------------------------------------
# AC-1 — when captures are produced, and where they land
# ---------------------------------------------------------------------------

_USER_FACING = re.compile(r"\buser[- ]facing\b", re.IGNORECASE)
_UNIVERSAL = re.compile(r"\b(?:any|every|each)\b", re.IGNORECASE)
#: The obligation verbs, as one string so :func:`_ungoverned` can build the
#: negated twin from the identical alternation.
_OBLIGES = r"\b(?:oblig\w*|requir\w*|must)\b"
#: A capture verb, likewise. ``captur\w*`` also matches the noun; that is
#: deliberate — the negated twin covers the noun's own sentences (*"**No
#: capture** exceeds…"*), and a sweep that fails closed on a noun is the safe
#: direction for a rule whose content is that it has no exceptions.
_CAPTURE_VERB = r"\b(?:captur\w*|screenshot\w*|snapshot\w*)\b"
_PLACEMENT = re.compile(r"\b(?:lands?|landing|saved?|writt?en?|retain\w*|live in|go in)\b",
                        re.IGNORECASE)
_TICKET_KEY = re.compile(r"<TICKET-ID>")
#: An add-then-capture ordering: the ignore line goes in *before* anything is
#: captured. Order is the whole content of the self-heal rule — adding the line
#: afterwards is what publishes the captures.
_SELF_HEAL = re.compile(
    r"\badd\b[^.]{0,60}?\bbefore\b[^.]{0,40}?\bcaptur\w*", re.IGNORECASE
)


def _visual_section() -> str:
    return _section(_read(BUILD), _VISUAL_SECTION)


def _unconditional_obligations(text: str) -> list[str]:
    """Units obliging visual evidence for *any* user-facing diff, un-negated.

    Co-occurrence of "user-facing" and "must" is not the rule. The universal
    quantifier is part of what is asserted: *"a user-facing change the builder
    judges risky requires this"* names both nouns and states the discretionary
    opposite.
    """
    return [
        unit
        for unit in _sentences(text)
        if _USER_FACING.search(unit)
        and _UNIVERSAL.search(_EMPHASIS.sub(" ", unit))
        and _ungoverned(unit, _OBLIGES)
    ]


def test_every_user_facing_diff_obliges_visual_evidence() -> None:
    """AC-1: the trigger is the surface the diff touches, not a risk judgment."""
    stated = _unconditional_obligations(_visual_section())
    assert stated, (
        f"`commands/build.md` → {_VISUAL_SECTION} no longer obliges visual "
        f"evidence for *every* user-facing diff. An empty result means the "
        f"trigger was narrowed to a judgment call, negated, or lost its "
        f"universal quantifier — not that the section is silent."
    )


def test_the_capture_section_names_the_documented_location() -> None:
    """AC-1: one documented, per-ticket, repo-relative home for the captures."""
    stated = [
        unit
        for unit in _sentences(_visual_section())
        if _EVIDENCE_DIR in unit and _TICKET_KEY.search(unit) and _PLACEMENT.search(unit)
    ]
    assert stated, (
        f"`commands/build.md` → {_VISUAL_SECTION} no longer says that captures "
        f"land in {_EVIDENCE_DIR}<TICKET-ID>/. Without a documented, per-ticket "
        f"location `/review` cannot hand the reviewer a directory, and a stale "
        f"capture from another ticket is indistinguishable from this change's "
        f"evidence."
    )


def test_the_section_self_heals_a_missing_ignore_rule() -> None:
    """AC-1/AC-5: a consuming repo adds the ignore line *before* it captures.

    `.gitignore` is not a `registry.yaml` entry, so neither `BOOTSTRAP.md` nor
    `/update-guidance` installs this repo's ignore line into a consuming repo.
    The remedy is in the prose, and its ordering is the whole of it: adding the
    line after capturing is exactly the sequence that publishes the captures.
    """
    stated = [
        unit
        for unit in _sentences(_visual_section())
        if ".gitignore" in unit and _EVIDENCE_DIR in unit and _SELF_HEAL.search(unit)
    ]
    assert stated, (
        f"`commands/build.md` → {_VISUAL_SECTION} no longer tells a repo whose "
        f"`.gitignore` lacks {_EVIDENCE_DIR} to add it *before* capturing. An "
        f"add-afterwards ordering satisfies the words and publishes the "
        f"captures anyway."
    )


# ---------------------------------------------------------------------------
# AC-3 — viewport slices, the height ceiling, and the capture cap
# ---------------------------------------------------------------------------

_VIEWPORT = re.compile(r"\bviewport\w*\b", re.IGNORECASE)
_SLICE = re.compile(r"\bslice\w*\b", re.IGNORECASE)
#: The height ceiling, parsed out of whatever sentence states it. The bound
#: keywords are what make this a *derived* number rather than a restated
#: constant: an arbitrary "1440 × 5726 px" in the measurement sentence is not a
#: ceiling and must not be read as one.
_HEIGHT_BOUND = re.compile(
    r"\b(?:no capture exceeds|maximum|at most|no taller than|never exceeds)\b"
    r"[^.]{0,40}?(\d+)\s*px",
    re.IGNORECASE,
)
_CAPTURE_BOUND = re.compile(r"\bat most\b[^.]{0,20}?(\d+)\s*captures?\b", re.IGNORECASE)
_MEASUREMENT = re.compile(r"\b5726\b")
_BODY_TEXT_SIZE = re.compile(r"\b16\s*px\b", re.IGNORECASE)
_FIDELITY = re.compile(r"\b7 of 8\b|\bcharacters?\b", re.IGNORECASE)
_NARROW = re.compile(r"\bnarrow\w*\b", re.IGNORECASE)
_SET_NOUN = re.compile(r"\bset\b|\bstates?\b|\bwidths?\b|\bpages?\b", re.IGNORECASE)
_SHRINK = r"\b(?:shrink\w*|downscal\w*|scale down|reduc\w*)\b"


def _height_bounds(text: str) -> set[int]:
    """Every capture-height ceiling ``text`` states, in px."""
    return {int(match.group(1)) for match in _HEIGHT_BOUND.finditer(_EMPHASIS.sub(" ", text))}


def _capture_bounds(text: str) -> set[int]:
    """Every capture-count cap ``text`` states."""
    return {int(match.group(1)) for match in _CAPTURE_BOUND.finditer(_EMPHASIS.sub(" ", text))}


def _slice_units(text: str) -> list[str]:
    """Units stating the slice rule: a viewport, a slice, and an un-negated capture."""
    return [
        unit
        for unit in _sentences(text)
        if _VIEWPORT.search(unit) and _SLICE.search(unit) and _ungoverned(unit, _CAPTURE_VERB)
    ]


def test_captures_are_viewport_height_slices() -> None:
    """AC-3: the capture unit is one viewport, numbered in scroll order."""
    stated = _slice_units(_visual_section())
    assert stated, (
        f"`commands/build.md` → {_VISUAL_SECTION} no longer states the slice "
        f"rule: capture one image per viewport, in scroll order. Without it the "
        f"builder's default is a single tall capture, which is the failure "
        f"#361 measured."
    )


def test_the_maximum_capture_height_is_two_thousand_pixels() -> None:
    """AC-3: the ceiling is a stated number, derived from the prose."""
    bounds = _height_bounds(_visual_section())
    assert bounds == {_MAX_HEIGHT_PX}, (
        f"`commands/build.md` → {_VISUAL_SECTION} states capture-height "
        f"ceilings {sorted(bounds) or 'nowhere'}; the decided backstop is "
        f"{_MAX_HEIGHT_PX} px. An empty result means the ceiling was deleted or "
        f"re-worded past its bound keyword, not that the section is silent."
    )


def test_the_height_ceiling_cites_the_measurement_that_set_it() -> None:
    """AC-3: the number carries its measurement, so it is not a magic constant.

    A ceiling with no stated evidence is re-litigated by the next author from
    scratch, and the honest answer to "why 2000?" is a real capture that failed:
    1440 × 5726 px arrived as an image content block whose 16 px body text read
    7 of 8 characters correctly.
    """
    stated = [
        unit
        for unit in _sentences(_visual_section())
        if _MEASUREMENT.search(unit) and _BODY_TEXT_SIZE.search(unit) and _FIDELITY.search(unit)
    ]
    assert stated, (
        f"`commands/build.md` → {_VISUAL_SECTION} no longer cites the #361 "
        f"measurement (1440 × 5726 px, 16 px body text, 7 of 8 characters) that "
        f"set the height ceiling. The number without its evidence is a magic "
        f"constant the next author is free to re-guess."
    )


def test_the_capture_count_cap_survives_with_its_cost_reason() -> None:
    """AC-3: the retired flag's cap survives as guidance, and says why."""
    section = _visual_section()
    bounds = _capture_bounds(section)
    assert bounds == {_MAX_CAPTURES}, (
        f"`commands/build.md` → {_VISUAL_SECTION} caps captures at "
        f"{sorted(bounds) or 'nothing'}; the decided cap is {_MAX_CAPTURES}."
    )
    reasoned = [
        unit
        for unit in _sentences(section)
        if _CAPTURE_BOUND.search(_EMPHASIS.sub(" ", unit))
        or ("token" in unit.lower() and "latency" in unit.lower())
    ]
    assert any("token" in unit.lower() and "latency" in unit.lower() for unit in reasoned), (
        "the cap no longer states its token and latency cost. A bound with no "
        "reason is the first thing a builder raises when it is inconvenient."
    )


def test_exceeding_the_cap_narrows_the_set_not_the_images() -> None:
    """AC-3: over the cap, drop states — never shrink the images.

    Shrinking to fit reintroduces the exact downscale failure the slice rule
    exists to prevent, so the two halves must be asserted together: a section
    that says "narrow" but permits shrinking has not stated the rule.
    """
    units = _sentences(_visual_section())
    narrows = [unit for unit in units if _NARROW.search(unit) and _SET_NOUN.search(unit)]
    assert narrows, (
        f"`commands/build.md` → {_VISUAL_SECTION} no longer says to narrow the "
        f"capture set when a change needs more than the cap."
    )
    forbids = [
        unit
        for unit in units
        if re.search(_SHRINK, unit, re.IGNORECASE) and not _ungoverned(unit, _SHRINK)
    ]
    assert forbids, (
        f"`commands/build.md` → {_VISUAL_SECTION} no longer forbids shrinking or "
        f"downscaling the images to fit the cap — which is the same downscale "
        f"failure the slice rule exists to prevent, reached by a different route."
    )


# ---------------------------------------------------------------------------
# AC-2 — the handoff, and the reviewer's consulted / not-consulted line
# ---------------------------------------------------------------------------

_VISUAL_EVIDENCE = re.compile(r"\bvisual[- ]evidence\b", re.IGNORECASE)
_CONSULTED = re.compile(r"\bconsult\w*\b", re.IGNORECASE)
_SUPPLY = re.compile(r"\b(?:suppl\w*|hand\w*|pass\w*|give\w*|provid\w*)\b", re.IGNORECASE)
_INCOMPLETE = re.compile(r"\bincomplete\b|\bnot an answer\b", re.IGNORECASE)


def test_review_step_three_supplies_the_capture_directory() -> None:
    """AC-2: the reviewer is handed the directory and its manifest, not a list."""
    step = _units(_section(_read(REVIEW), _HANDOFF_STEP))
    stated = [
        unit
        for unit in _sentences(step)
        if _EVIDENCE_DIR in unit and "manifest.md" in unit and _SUPPLY.search(unit)
    ]
    assert stated, (
        f"`commands/review.md` → {_HANDOFF_STEP} no longer supplies the capture "
        f"directory {_EVIDENCE_DIR}<TICKET-ID>/ and its `manifest.md`. "
        f"'Visual evidence' unqualified leaves the reviewer to guess what it "
        f"was handed, which is how a supplied capture goes unread."
    )


def _report_enumeration() -> str:
    """The `Report:` bullet's first unit — the enumeration of required items.

    Scoped to the enumeration rather than the whole bullet on purpose: the
    sentences that *follow* it describe the visual-evidence line's own grammar,
    so a whole-bullet substring check stays green after the item is struck from
    the list it belongs to.
    """
    return _sentences(_report_bullet())[0]


def test_the_report_contract_requires_a_visual_evidence_statement() -> None:
    """AC-2: the report's enumeration carries the visual-evidence item."""
    enumeration = _report_enumeration()
    assert _VISUAL_EVIDENCE.search(enumeration) and _CONSULTED.search(enumeration), (
        f"`skills/review-discipline/SKILL.md` → {_OBLIGATIONS} → `Report:` no "
        f"longer enumerates whether visual evidence was consulted:\n"
        f"{enumeration}"
    )


def test_the_report_contract_enumerates_every_not_consulted_reason() -> None:
    """AC-2: a closed set of three reasons — the third is Codex's.

    Two reasons would force a Codex reviewer, which has no image-returning read
    tool, to either claim `consulted` or pick a false reason. Equality, not
    containment: an open-ended set is the same silence the line exists to end.
    """
    stated = _stated_reasons(_report_bullet())
    assert stated == set(_NOT_CONSULTED_REASONS), (
        f"`skills/review-discipline/SKILL.md` → {_OBLIGATIONS} → `Report:` "
        f"enumerates {sorted(stated) or 'no'} `not consulted` reasons; the "
        f"decided closed set is {sorted(_NOT_CONSULTED_REASONS)}."
    )


def test_the_report_contract_names_both_visual_evidence_verdicts() -> None:
    """AC-2: the two operator-visible tokens the line is actually written in.

    The reason set above is asserted by value; the **verdicts** were not, and
    they are the half every rendering defers to — `agents/reviewer.md` and
    `commands/review.md` step 5 each say *whether visual evidence was
    consulted* and point here for the rest. Renaming `not consulted` in this
    bullet was measured during review as a **live survivor**: the whole suite
    stayed green while the contract's operator-visible half drifted, which is
    this repo's most expensive shape — right effect, wrong value.

    Both tokens, not just the negative one: they are one wiring field, and a
    field is a family rather than a line.

    Scoped to the sentence that **defines** the line's grammar, not to the
    bullet. That is part of the predicate rather than tidiness: the bullet names
    ``not consulted`` twice — once defining it, once in the closing clause about
    a reason-less one — so a whole-bullet presence check stays green after the
    defining occurrence is renamed. Measured exactly that way; this test was
    born vacuous and is here in its second form.
    """
    grammar = _verdict_grammar()
    for token in ("`consulted`", "`not consulted`"):
        assert token in grammar, (
            f"`skills/review-discipline/SKILL.md` → {_OBLIGATIONS} → `Report:` "
            f"no longer writes the visual-evidence verdict as {token}. Every "
            f"other file renders this bullet rather than restating it, so a "
            f"rename here silently re-words the contract everywhere:\n{grammar}"
        )


def test_silence_is_not_an_answer_in_the_report_contract() -> None:
    """AC-2: a report saying nothing about visual evidence is incomplete.

    Without this the line is enumerated but unenforced: a reviewer that omits it
    has broken no stated rule, and a `not consulted` with no reason is the same
    silence wearing a label.
    """
    stated = [
        unit
        for unit in _sentences(_report_bullet())
        if _VISUAL_EVIDENCE.search(unit) and _INCOMPLETE.search(unit)
    ]
    assert stated, (
        f"`skills/review-discipline/SKILL.md` → {_OBLIGATIONS} → `Report:` no "
        f"longer says that a report silent on visual evidence is incomplete. An "
        f"enumerated item with no verdict for omitting it is advisory."
    )


def test_the_reviewer_agent_report_carries_the_visual_evidence_item() -> None:
    """AC-2: the agent's own report contract renders the line."""
    reviewer = _units(_read(REVIEWER))
    stated = [
        unit
        for unit in _sentences(reviewer)
        if _VISUAL_EVIDENCE.search(unit) and _CONSULTED.search(unit)
    ]
    assert stated, (
        "`agents/reviewer.md` no longer requires its report to state whether "
        "visual evidence was consulted. The agent file is what the reviewer "
        "actually reads, so an obligation stated only in `review-discipline` "
        "reaches it only if it opens the skill."
    )


def test_the_review_command_report_step_carries_the_visual_evidence_item() -> None:
    """AC-2: `/review`'s printed report carries the line and points at its home."""
    step = _units(_section(_read(REVIEW), _REPORT_STEP))
    stated = [
        unit
        for unit in _sentences(step)
        if _VISUAL_EVIDENCE.search(unit) and "review-discipline" in unit
    ]
    assert stated, (
        f"`commands/review.md` → {_REPORT_STEP} no longer prints the "
        f"visual-evidence line, or no longer points at `review-discipline` for "
        f"its reasons. Printing the line while restating the reason set is the "
        f"other half of the same defect."
    )


# ---------------------------------------------------------------------------
# The single-home guards — one home per fact, everywhere else a pointer
# ---------------------------------------------------------------------------


def _report_bullet() -> str:
    """The `Report:` bullet of `review-discipline` → *Reviewer obligations*.

    That bullet is the declared enumeration of the report contract, which is why
    it — and not `agents/reviewer.md` or `commands/review.md` — is the home for
    the visual-evidence line and its reason set. Both of those files are
    renderings of it.
    """
    obligations = _section(_read(DISCIPLINE), _OBLIGATIONS)
    for line in obligations.splitlines():
        if line.lstrip().startswith("- **Report:**"):
            return line
    raise AssertionError(
        f"`skills/review-discipline/SKILL.md` → {_OBLIGATIONS} has no `Report:` "
        f"bullet; the report contract has no home."
    )


def _verdict_grammar() -> str:
    """The `Report:` bullet's sentence defining how the visual-evidence line reads.

    Anchored on the same ``exactly one reason`` clause :func:`_stated_reasons`
    splits on, so the sentence this asserts against and the sentence the reason
    set is parsed from cannot become two different sentences. Raising rather
    than returning ``""`` is the floor: a bullet that no longer defines the
    line's grammar must fail here, not pass an assertion over nothing.
    """
    for unit in _sentences(_report_bullet()):
        if "exactly one reason" in unit:
            return unit
    raise AssertionError(
        f"FLOOR: `skills/review-discipline/SKILL.md` → {_OBLIGATIONS} → "
        f"`Report:` no longer defines how the visual-evidence line is written, "
        f"so there is no sentence to check the verdict tokens against."
    )


def _stated_reasons(bullet: str) -> set[str]:
    """The `not consulted` reasons the bullet enumerates.

    Parsed out of the emphasised phrases that follow the "exactly one reason"
    clause, so a reason added or re-worded anywhere else in the bullet is not
    mistaken for the closed set.
    """
    tail = re.split(r"exactly one reason\s*:", bullet, maxsplit=1)
    if len(tail) < 2:
        return set()
    return {phrase.strip().lower() for phrase in re.findall(r"\*\*([^*]+)\*\*", tail[1])}


def test_the_not_consulted_reasons_live_in_exactly_one_home() -> None:
    """AC-4: the reason set is stated once and pointed at everywhere else.

    The FLOOR is load-bearing, not ceremony. Without it the second half is a
    "for each of nothing, assert nothing" loop that passes just as happily on a
    tree where the home was deleted — and the floor is also what makes this test
    RED for the right reason before the home exists.
    """
    reasons = _stated_reasons(_report_bullet())
    assert reasons, (
        f"FLOOR: `skills/review-discipline/SKILL.md` → {_OBLIGATIONS} → "
        f"`Report:` enumerates no `not consulted` reasons, so the "
        f"single-home sweep below would pass over an empty set."
    )
    for path in (REVIEW, REVIEWER, BUILD):
        text = _read(path).lower()
        restated = [reason for reason in reasons if reason in text]
        assert not restated, (
            f"{path.relative_to(_REPO_ROOT)} restates the reason set "
            f"{restated} that `review-discipline` owns. A rendering points at "
            f"the home; a second copy of a closed set is what drifts."
        )


def test_the_capture_numbers_live_in_exactly_one_file() -> None:
    """AC-4: the height ceiling and the capture cap are stated only where captures are made.

    Same FLOOR argument: derived from `commands/build.md` through the very
    parsers the AC-3 tests use, so a deleted home empties the set and fails here
    rather than silently satisfying the sweep.
    """
    section = _visual_section()
    numbers = _height_bounds(section) | _capture_bounds(section)
    assert numbers, (
        f"FLOOR: `commands/build.md` → {_VISUAL_SECTION} states neither a "
        f"capture-height ceiling nor a capture cap, so the single-home sweep "
        f"below would pass over an empty set."
    )
    restatement = re.compile(
        rf"\b{_MAX_HEIGHT_PX}\s*px\b|\b{_MAX_HEIGHT_PX:,}\s*px\b|\b\d+\s*captures?\b",
        re.IGNORECASE,
    )
    for path in (START, REVIEW, REVIEWER, DISCIPLINE):
        found = restatement.findall(_read(path))
        assert not found, (
            f"{path.relative_to(_REPO_ROOT)} restates a capture number {found}; "
            f"`commands/build.md` → {_VISUAL_SECTION} is the one home for the "
            f"ceiling and the cap, and every other file points at it."
        )


def _pointer_units(text: str) -> list[str]:
    """Units of ``text`` that point at the capture convention's home.

    Takes the text rather than reading `commands/start.md` itself, so the
    control below judges its splice through **this** predicate instead of a
    second copy of it. A guard protecting another guard has to call the same
    function; two spellings of one predicate drift the moment either is
    tightened, and the copy is exactly the one nobody re-reads.
    """
    return [
        unit
        for unit in _sentences(text)
        if "commands/build.md" in unit
        and "Visual evidence for a user-facing change" in unit
        and _VISUAL_EVIDENCE.search(unit)
    ]


def _start_pointer_units() -> list[str]:
    return _pointer_units(_units(_section(_read(START), _BUILD_STEP)))


def test_start_points_at_the_capture_convention() -> None:
    """AC-4: the attended entry point names the home instead of restating it."""
    stated = _start_pointer_units()
    assert stated, (
        f"`commands/start.md` → {_BUILD_STEP} no longer points at "
        f"`commands/build.md` → *Visual evidence for a user-facing change*. A "
        f"condensed restatement here is the drift the single-home rule exists "
        f"to prevent."
    )


# ---------------------------------------------------------------------------
# AC-5 — the ignore rule, proven behaviourally in a hermetic repo
# ---------------------------------------------------------------------------
#
# `_init_hermetic_repo` (`test_worktree_ignore_hygiene`) exists for a measured
# reason: *this* checkout's `.git/info/exclude` carries local, uncommitted rules,
# so any assertion evaluated against the live worktree passes whether or not the
# committed `.gitignore` carries the fix. The fixture copies the real
# `.gitignore` into a fresh `git init` and commits a tracked file first, so the
# rule under test is the committed one.


def test_a_capture_directory_is_invisible_to_git_status(tmp_path: Path) -> None:
    """A `.evidence/<TICKET-ID>/` tree does not read as a dirty worktree.

    The direction that bites first: a capture pass leaves a dozen PNGs at the
    worktree root, and any gate that counts untracked files then refuses the
    run — after the work is done and often after it has passed review.
    """
    repo = _init_hermetic_repo(tmp_path / "clone")
    captures = repo / ".evidence" / "434"
    captures.mkdir(parents=True)
    (captures / "settings-empty-1440w-01.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (captures / "manifest.md").write_text("| page | state | width | slice |\n")

    porcelain = _git(repo, "status", "--porcelain").stdout
    assert ".evidence" not in porcelain, (
        f".gitignore must ignore {_EVIDENCE_DIR} — a capture directory reads as "
        f"a dirty worktree:\n{porcelain}"
    )


def test_captures_are_not_swept_into_the_index_by_add_all(tmp_path: Path) -> None:
    """`git add -A` never stages a capture.

    The other, worse direction. `/build` runs `git add -A` twice — before the
    certifying tree identity and again at Ship — and this repo is public, so an
    unignored capture publishes a binary image of seeded application state into
    permanent history. That is the hazard `41d7fb6` already had to revert once
    for `gate.log`.
    """
    repo = _init_hermetic_repo(tmp_path / "clone")
    captures = repo / ".evidence" / "434"
    captures.mkdir(parents=True)
    (captures / "settings-empty-1440w-01.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (captures / "manifest.md").write_text("| page | state | width | slice |\n")

    _git(repo, "add", "-A")
    listing = _git(repo, "ls-files").stdout.splitlines()
    assert not [path for path in listing if path.startswith(".evidence/")], (
        f"`git add -A` staged a capture — it would reach public history:\n{listing}"
    )


def test_the_evidence_ignore_does_not_hide_a_tracked_reference_image(
    tmp_path: Path,
) -> None:
    """The ignore rule is `.evidence/`, not a blanket on images or evidence names.

    **Honest exception — this test is not RED-first, by construction.** It is an
    *over-breadth* guard on a `.gitignore` line that did not exist before this
    change, so no edit to the pre-change tree can make it fail for the right
    reason. It ships in the same commit as the line and is proven by mutation
    (broaden the line to ``*.png`` and this reddens while the two tests above
    stay green), in the mould of the existing
    `test_gitignore_does_not_blanket_ignore_dot_claude`. It is worth keeping
    because over-breadth is the one failure direction the behavioural pair above
    structurally cannot see: silently ignoring a design reference image, or a
    hand-written note whose name merely contains "evidence", would be a worse
    bug than the one being fixed.
    """
    repo = _init_hermetic_repo(tmp_path / "clone")
    (repo / "design").mkdir()
    (repo / "design" / "reference-1440.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (repo / "docs").mkdir()
    (repo / "docs" / "evidence-notes.md").write_text("# Notes on visual evidence\n")

    # `git check-ignore`, not `git status`: git collapses a wholly-untracked
    # directory into one `?? design/` line, so a porcelain assertion about a path
    # *under* it answers a question about the parent and would pass however
    # broad the rule got (`_init_hermetic_repo`'s docstring records the same
    # trap for `.claude/`). `check-ignore` answers per path.
    for path in ("design/reference-1440.png", "docs/evidence-notes.md"):
        probe = subprocess.run(
            ["git", "check-ignore", "-q", path],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
        )
        assert probe.returncode == 1, (
            f"the evidence ignore rule swallowed {path} — it must ignore "
            f"{_EVIDENCE_DIR} and nothing else; a design reference image or a "
            f"document named for evidence is content to track"
        )


def test_no_visual_evidence_is_tracked_in_the_live_repo() -> None:
    """The live repo's index carries nothing under `.evidence/`.

    **Honest exception — neither RED-first nor mutation-provable.** No textual
    mutation reaches this assertion: it guards a deliberate ``git add -f``,
    which an ignore rule by design does not stop. It is a live-repo hygiene
    guard in the mould of `test_no_agent_worktree_is_tracked_in_the_live_repo`,
    and it is labelled as such here rather than dressed up as proven.
    """
    assert not tracked_files_under(".evidence")


# ---------------------------------------------------------------------------
# AC-4 — the inversion half of every pair
# ---------------------------------------------------------------------------
#
# Each sweep below asks the question its presence twin cannot: *has anything
# granted an exception to the rule*. That is not the same question as "is the
# rule still stated", and #288 measured the difference — an exception appended
# after a rule leaves the rule's own words, and its `never`, entirely intact.
# Every one of them is `_released`, so every one is per-occurrence anchored.

_OPTIONAL_RELEASE = (
    r"\b(?:optional\w*|may skip|need not|skippable|nice to have|"
    r"at (?:your|the builder's|the implementer's) discretion|where useful|"
    r"if you like|when time allows)\b"
)
_LOCATION_RELEASE = (
    r"\b(?:anywhere|any convenient\w*|wherever|elsewhere|any location|any path|"
    r"a directory of your choosing|any directory)\b"
)
_HEIGHT_RELEASE = (
    r"\b(?:advisor\w*|guideline|optional\w*|may exceed|not a hard|soft limit|"
    r"rule of thumb|where necessary|as needed)\b"
)
_CAP_RELEASE = (
    r"\b(?:more than|beyond|as many as|no (?:hard )?limit|unbounded|fine|"
    r"acceptable|exceed\w*)\b"
)
_LINE_RELEASE = (
    r"\b(?:optional\w*|omit\w*|omission|need not|if applicable|where relevant|"
    r"at the reviewer's discretion|left out|only when|only where|"
    r"only if)\b"
)

_CAPTURE_SUBJECT = re.compile(_CAPTURE_VERB, re.IGNORECASE)
#: The full-page subject, in every spelling that names one image of a whole
#: surface. ``in one image`` is here because a permission needs no page noun at
#: all — *"capturing the entire scroll height in one image is fine"* was
#: measured escaping a page-noun-only subject.
_FULL_PAGE = re.compile(
    r"\bfull[-\s]?page\b|\bwhole page\b|\bentire page\b|\bin one image\b|"
    r"\b(?:entire|whole|full) scroll height\b",
    re.IGNORECASE,
)
#: What releases a full-page capture. The capture verb is one arm — an
#: un-negated *"capture the full page"* — but a permission needs no verb of its
#: own: *"a single image of the whole page is acceptable"* states the release in
#: an adjective. Measured: with the capture-verb arm alone, two of the six
#: paraphrases below escaped. The real prohibition carries none of these tokens,
#: which is what keeps the arm from flagging the rule it protects.
_FULL_PAGE_RELEASE = (
    rf"(?:{_CAPTURE_VERB}|\b(?:acceptable|fine|permitted|allowed|relax\w*|"
    r"better evidence|instead)\b)"
)
#: ``ceiling`` and ``px`` are part of the height subject: a sentence releasing
#: the bound need not repeat the word "height" — *"the 2000 px ceiling is
#: advisory"* names neither ``height`` nor ``taller``.
_HEIGHT_SUBJECT = re.compile(
    r"\btaller\b|\bheight\b|\bexceeds?\b|\bceiling\b|\bpx\b", re.IGNORECASE
)
_CAP_SUBJECT = re.compile(r"\bat most\b|\bcaps?\b|\b12\b|\btwelve\b", re.IGNORECASE)


def test_no_unit_makes_visual_capture_optional() -> None:
    """AC-4: nothing in the section turns the capture pass into a judgment call."""
    offenders = _released(_visual_section(), _CAPTURE_SUBJECT, _OPTIONAL_RELEASE)
    assert not offenders, (
        f"`commands/build.md` → {_VISUAL_SECTION} releases the capture pass:\n"
        + "\n".join(offenders)
    )


def test_no_unit_permits_captures_outside_the_documented_location() -> None:
    """AC-4: nothing in the file lets a capture land somewhere else."""
    offenders = _released(_read(BUILD), _CAPTURE_SUBJECT, _LOCATION_RELEASE)
    assert not offenders, (
        "`commands/build.md` permits captures outside the documented location:\n"
        + "\n".join(offenders)
    )


def test_no_unit_permits_a_full_page_capture() -> None:
    """AC-4: nothing in the file permits capturing a whole page in one image.

    The subject is the full-page noun and the *governed* verb is the capture
    verb, so the sweep reads polarity rather than vocabulary: the real rule's
    own `Never capture the full page in one image` is the one wording that
    passes, and any un-negated capture verb in a sentence naming the full page
    is an offender.
    """
    offenders = _released(_read(BUILD), _FULL_PAGE, _FULL_PAGE_RELEASE)
    assert not offenders, (
        "`commands/build.md` permits a full-page capture:\n" + "\n".join(offenders)
    )


def test_no_unit_releases_the_height_ceiling() -> None:
    """AC-4: the 2000 px ceiling is a bound, not advice."""
    offenders = _released(_visual_section(), _HEIGHT_SUBJECT, _HEIGHT_RELEASE)
    assert not offenders, (
        f"`commands/build.md` → {_VISUAL_SECTION} releases the height ceiling:\n"
        + "\n".join(offenders)
    )


def test_no_unit_permits_exceeding_the_capture_cap() -> None:
    """AC-4: over the cap the answer is a narrower set, never more captures."""
    offenders = _released(_visual_section(), _CAP_SUBJECT, _CAP_RELEASE)
    assert not offenders, (
        f"`commands/build.md` → {_VISUAL_SECTION} releases the capture cap:\n"
        + "\n".join(offenders)
    )


def test_no_unit_makes_the_visual_evidence_line_optional() -> None:
    """AC-4: no rendering of the report contract makes the line discretionary.

    Swept over all four files that name the line, because the cheapest way to
    undo it is not to edit its home but to add "when relevant" to whichever
    rendering an author happens to be reading.
    """
    offenders: list[str] = []
    for path in (DISCIPLINE, REVIEWER, REVIEW, BUILD):
        for unit in _released(_read(path), _VISUAL_EVIDENCE, _LINE_RELEASE):
            offenders.append(f"{path.relative_to(_REPO_ROOT)}: {unit}")
    assert not offenders, (
        "the visual-evidence line is released somewhere:\n" + "\n".join(offenders)
    )


# ---------------------------------------------------------------------------
# Paraphrase robustness — the sweeps must survive a rewrite, not one wording
# ---------------------------------------------------------------------------

#: Wordings that permit a full-page capture, each **spliced in place of the real
#: prohibition** rather than standing alone: a permission judged in isolation is
#: a different text from one sitting inside a section whose other sentences
#: already carry the vocabulary.
_FULL_PAGE_PERMISSIONS = (
    "A single image of the whole page is acceptable when the page is short.",
    "The slice rule may be relaxed for a short page, so capture the full page.",
    "Capturing the entire scroll height in one image is fine below 3000 px.",
    "Where slicing is awkward, take a full-page capture instead.",
    "A full page screenshot is the better evidence for a compact view.",
    "Only where a page is unusually long is a full-page capture ruled out.",
)

#: Wordings that make the reviewer's visual-evidence line discretionary.
_OPTIONAL_LINE_WORDINGS = (
    "The visual-evidence line may be omitted when the change is not user-facing.",
    "State the visual evidence line where relevant.",
    "Including the visual-evidence line is optional for a small diff.",
    "The reviewer need not report visual evidence it did not receive.",
    "Report the visual-evidence line only when captures were supplied.",
    "Nothing forbids omitting the visual-evidence line.",
)


def test_the_full_page_permission_wordings_are_a_populated_set() -> None:
    """FLOOR: an empty ``parametrize`` set reports ``1 skipped``, not a failure."""
    assert len(_FULL_PAGE_PERMISSIONS) >= 5, (
        f"only {len(_FULL_PAGE_PERMISSIONS)} full-page permission wordings — "
        f"the paraphrase sweep below degrades to a single-wording check."
    )
    assert any("whole page" in wording for wording in _FULL_PAGE_PERMISSIONS), (
        "the wordings no longer include the `whole page` paraphrase, which is "
        "the one that escapes a `full page` substring check."
    )


def test_the_optional_line_wordings_are_a_populated_set() -> None:
    """FLOOR: same argument, for the report-line paraphrases."""
    assert len(_OPTIONAL_LINE_WORDINGS) >= 5, (
        f"only {len(_OPTIONAL_LINE_WORDINGS)} optional-line wordings — the "
        f"paraphrase sweep below degrades to a single-wording check."
    )
    assert any("where relevant" in wording for wording in _OPTIONAL_LINE_WORDINGS), (
        "the wordings no longer include the bare `where relevant` qualifier, "
        "which releases the line without naming an exception."
    )


@pytest.mark.parametrize("permission", _FULL_PAGE_PERMISSIONS)
def test_the_full_page_sweep_catches_a_rewritten_permission(permission: str) -> None:
    """A re-worded full-page permission is caught, and the slice rule survives it.

    Both halves, because a pair where only one moves is not a pair: the sweep
    must fire on the rewrite **and** the presence half must be unchanged by it,
    which is what proves the two guards see different edits.
    """
    section = _units(_visual_section())
    prohibition = "**Never capture the full page in one image**, at any width."
    assert prohibition in section, (
        "the full-page prohibition moved — re-anchor this paraphrase sweep"
    )
    spliced = section.replace(prohibition, permission)

    before = _released(section, _FULL_PAGE, _FULL_PAGE_RELEASE)
    after = _released(spliced, _FULL_PAGE, _FULL_PAGE_RELEASE)
    assert len(after) > len(before), (
        f"a rewritten permission escapes the full-page sweep: {permission!r}"
    )
    assert _slice_units(spliced) == _slice_units(section), (
        f"replacing the prohibition changed what the slice presence half reads "
        f"({permission!r}) — then the two halves are one guard stated twice, "
        f"and the sweep is not testing anything the presence half misses."
    )


@pytest.mark.parametrize("wording", _OPTIONAL_LINE_WORDINGS)
def test_the_optional_line_sweep_catches_a_rewritten_release(wording: str) -> None:
    """A re-worded release of the report line is caught, and the item survives it."""
    reviewer = _units(_read(REVIEWER))
    spliced = f"{reviewer.rstrip()}\n\n{wording}"

    before = _released(reviewer, _VISUAL_EVIDENCE, _LINE_RELEASE)
    after = _released(spliced, _VISUAL_EVIDENCE, _LINE_RELEASE)
    assert len(after) > len(before), (
        f"a rewritten release escapes the report-line sweep: {wording!r}"
    )
    item_before = [
        unit
        for unit in _sentences(reviewer)
        if _VISUAL_EVIDENCE.search(unit) and _CONSULTED.search(unit)
    ]
    item_after = [
        unit
        for unit in _sentences(spliced)
        if _VISUAL_EVIDENCE.search(unit) and _CONSULTED.search(unit)
    ]
    assert item_after == item_before, (
        f"appending {wording!r} changed what the presence half reads — the "
        f"appended release is supposed to be invisible to it, which is exactly "
        f"why the sweep has to exist."
    )


# ---------------------------------------------------------------------------
# The control — every predicate, exercised against the real documents
# ---------------------------------------------------------------------------


def test_the_visual_predicates_read_the_real_documents_boundaries() -> None:
    """The predicates above, exercised against mutations of the real prose.

    A control fed a hand-written clean sentence can only fail for a defect in a
    predicate's *tokens*; it can never fail the way the real assertion fails,
    where units merge across a whole markdown section and a rule's own `never`
    shields the sentence appended after it (#354, #288). Every sample here is
    the real text with one edit, and every edit asserts it landed.

    Each splice is judged by the **difference** it makes — the splice adds an
    offender the unspliced text did not have — not by the spliced text being
    dirty in absolute terms. That is what makes the control answer the question
    it claims to (*can this predicate tell the splice apart from the file it was
    spliced into*) instead of restating the sweep's own baseline assertion,
    which the sweep already owns.

    The comparison is a **count**, not a set difference. Measured: with a set
    difference, an edit that appends the very sentence a splice appends leaves
    ``set(after) - set(before)`` empty — the two identical units collapse — and
    the control fails for a reason that has nothing to do with the predicate
    under test. Counting keeps the claim ("the splice adds an offender") true
    whichever offenders the file already carries.
    """
    section = _units(_visual_section())
    build = _read(BUILD)
    reviewer = _units(_read(REVIEWER))

    # 1. The capture pass, made optional by an appended sentence — the shape a
    #    `is this section negated` predicate is blind to.
    spliced = f"{section.rstrip()}\n\nFor a small change the capture pass is optional."
    assert spliced != section, "the visual section is empty — re-anchor this control"
    assert len(_released(spliced, _CAPTURE_SUBJECT, _OPTIONAL_RELEASE)) > len(
        _released(section, _CAPTURE_SUBJECT, _OPTIONAL_RELEASE)
    ), "an appended `the capture pass is optional` is invisible to the sweep."
    assert _unconditional_obligations(spliced) == _unconditional_obligations(section), (
        "appending an exception changed what the `when` presence half reads — "
        "the two halves are then one guard, and the appended release is "
        "precisely what the presence half cannot see."
    )

    # 2. A second location, granted rather than substituted.
    spliced = f"{build.rstrip()}\n\nCaptures may be saved anywhere convenient to the run."
    assert len(_released(spliced, _CAPTURE_SUBJECT, _LOCATION_RELEASE)) > len(
        _released(build, _CAPTURE_SUBJECT, _LOCATION_RELEASE)
    ), "an appended `saved anywhere convenient` is invisible to the location sweep."

    # 3. The prohibition flipped in place: the sweep fires, and the slice
    #    presence half is untouched — flipping a prohibition leaves every noun
    #    the slice rule names intact, which is why they are two guards.
    flipped = section.replace("**Never capture", "**Capture")
    assert flipped != section, "the full-page prohibition moved — re-anchor this control"
    assert len(_released(flipped, _FULL_PAGE, _FULL_PAGE_RELEASE)) > len(
        _released(section, _FULL_PAGE, _FULL_PAGE_RELEASE)
    ), (
        "`Capture the full page in one image` reads as the prohibition intact — "
        "the negation is not anchored to the verb it governs."
    )
    assert _slice_units(flipped) == _slice_units(section), (
        "flipping the prohibition changed what the slice presence half reads — "
        "it is reading the prohibition rather than the slice rule, and the two "
        "guards are then one stated twice."
    )

    # 4. The ceiling turned advisory.
    spliced = (
        f"{section.rstrip()}\n\nThe 2000 px ceiling is advisory for a page that nearly fits."
    )
    assert len(_released(spliced, _HEIGHT_SUBJECT, _HEIGHT_RELEASE)) > len(
        _released(section, _HEIGHT_SUBJECT, _HEIGHT_RELEASE)
    ), "an appended `the ceiling is advisory` is invisible to the height sweep."
    assert _height_bounds(spliced) == _height_bounds(section), (
        "the advisory sentence changed the parsed ceiling — the number parser "
        "is reading prose about the bound as a statement of it."
    )

    # 5. The cap, released.
    spliced = f"{section.rstrip()}\n\nMore than twelve captures are fine when the change is large."
    assert len(_released(spliced, _CAP_SUBJECT, _CAP_RELEASE)) > len(
        _released(section, _CAP_SUBJECT, _CAP_RELEASE)
    ), "an appended `more than twelve captures are fine` is invisible to the cap sweep."
    assert _capture_bounds(spliced) == _capture_bounds(section), (
        "the release sentence changed the parsed cap — the parser is reading a "
        "sentence *about* the cap as the cap."
    )

    # 6. The report line, made conditional in the file the reviewer actually reads.
    spliced = (
        f"{reviewer.rstrip()}\n\nThe visual-evidence line may be omitted when the "
        f"change is not user-facing."
    )
    assert len(_released(spliced, _VISUAL_EVIDENCE, _LINE_RELEASE)) > len(
        _released(reviewer, _VISUAL_EVIDENCE, _LINE_RELEASE)
    ), "an appended `the line may be omitted` is invisible to the report-line sweep."

    # 7. The false converse, per negation predicate. Each was #288's measured
    #    escape: a negation whose object is a *blocking verb* governs the
    #    blocking, not the verb beyond it, and grants exactly what it appears to
    #    forbid. `_NEGATION_GAP`'s exclusion is what closes them.
    converse = f"{section.rstrip()}\n\nA tall surface does not preclude capturing the full page."
    assert len(_released(converse, _FULL_PAGE, _FULL_PAGE_RELEASE)) > len(
        _released(section, _FULL_PAGE, _FULL_PAGE_RELEASE)
    ), (
        "`does not preclude capturing the full page` reads as a prohibition — "
        "the negation is being credited with governing the verb beyond the "
        "blocking one, which computes the opposite boolean."
    )
    converse = f"{reviewer.rstrip()}\n\nNothing forbids omitting the visual-evidence line."
    assert len(_released(converse, _VISUAL_EVIDENCE, _LINE_RELEASE)) > len(
        _released(reviewer, _VISUAL_EVIDENCE, _LINE_RELEASE)
    ), "`Nothing forbids omitting the visual-evidence line` escapes the sweep."

    # 8. The fronted qualifier. A qualifier that *fronts* the clause has no
    #    bounded token distance to the verb, so a forwards-only anchor never
    #    sees it; this is the control that proves the release arm reads both
    #    word orders.
    fronted = (
        f"{section.rstrip()}\n\nOnly where a page is unusually long is a "
        f"full-page capture ruled out."
    )
    assert len(_released(fronted, _FULL_PAGE, _FULL_PAGE_RELEASE)) > len(
        _released(section, _FULL_PAGE, _FULL_PAGE_RELEASE)
    ), (
        "a fronted `Only where …` qualifier leaves the full-page rule reading "
        "as unconditional — the sweep is anchored in one word order only."
    )

    # 9. The single-home guards, from the other direction: a reason pasted into
    #    a rendering must be seen, and a pointer deleted must be missed.
    pasted = _read(REVIEWER).replace(
        "`review-discipline`'s reasons applies",
        "`review-discipline`'s reasons applies — not supplied, for instance",
    )
    assert pasted != _read(REVIEWER), "the reviewer pointer moved — re-anchor this control"
    assert any(reason in pasted.lower() for reason in _stated_reasons(_report_bullet())), (
        "a reason phrase pasted into `agents/reviewer.md` is invisible to the "
        "single-home sweep — it is matching the home rather than the rendering."
    )
    unpointed = _units(_section(_read(START), _BUILD_STEP)).replace(
        "*Visual evidence for a user-facing change*", "the capture rules"
    )
    assert unpointed != _units(_section(_read(START), _BUILD_STEP)), (
        "the start pointer moved — re-anchor this control"
    )
    assert not _pointer_units(unpointed), (
        "the pointer predicate still fires after the section title was dropped "
        "— naming the file alone is not a pointer, since `commands/start.md` "
        "already names `commands/build.md` elsewhere."
    )

    # 10. A prohibition and its release in **one unit**. Every other splice here
    #     appends a sentence of its own, and so does every paraphrase in §7.3 —
    #     which leaves the one shape `_negated`'s `\s*$` anchor exists for
    #     untested. Without that anchor `_ungoverned` answers "is there any
    #     negated verb earlier in this unit" rather than "is *this* occurrence
    #     governed", and the rule's own `Never` shields the clause sharing its
    #     sentence. Measured: one offender anchored, zero unanchored.
    compound = section.replace(
        "**Never capture the full page in one image**, at any width.",
        "**Never capture the full page in one image**, at any width, but "
        "capture the whole page when it is short.",
    )
    assert compound != section, "the full-page prohibition moved — re-anchor this control"
    assert len(_released(compound, _FULL_PAGE, _FULL_PAGE_RELEASE)) > len(
        _released(section, _FULL_PAGE, _FULL_PAGE_RELEASE)
    ), (
        "a release sharing a sentence with the prohibition escapes the "
        "full-page sweep — the negation is being credited with governing every "
        "capture verb after it, which is the per-sentence fail-open #288 closed."
    )

    # 11. Emphasis *inside* the anchor window — the one property `_EMPHASIS`
    #     exists for, and the one nothing else in this tree reaches. Every real
    #     unit and every splice above bolds a rule at its edges (`**Never
    #     capture … image**`), where the asterisks fall outside the negation-to-
    #     verb gap and stripping them changes nothing. Put emphasis *between*
    #     the negation and the verb it governs and the anchor must still cross
    #     it: unstripped, `\w+` cannot match `*ever*`, the gap closes, the
    #     negation stops reaching `capture`, and the rule reads as its own
    #     release. Measured on the merged tree: `_EMPHASIS` compiled to a
    #     pattern that never matches, and to `\*\*` alone, both leave the whole
    #     suite green without this splice — the control that held them lived in
    #     `test_build_assurance_workflow`, which #435 deleted with the verb loop
    #     it described, and the primitive outlived its guard.
    emphasised = section.replace("**Never capture", "**Never *ever* capture")
    assert emphasised != section, "the full-page prohibition moved — re-anchor this control"
    assert len(_released(emphasised, _FULL_PAGE, _FULL_PAGE_RELEASE)) == len(
        _released(section, _FULL_PAGE, _FULL_PAGE_RELEASE)
    ), (
        "emphasis between the negation and the verb it governs makes the "
        "prohibition read as released — `_EMPHASIS` is not stripping every "
        "spelling this tree bolds its rules with, so an anchored predicate "
        "cannot cross it."
    )
    #     The exclusive killer for that equality: the sweep must still *reach*
    #     the emphasised unit, or the count above matches for the reason that it
    #     stopped looking rather than the reason that it looked and found
    #     nothing.
    released = emphasised.replace("**Never *ever* capture", "**Capture")
    assert released != emphasised, "the emphasis splice moved — re-anchor this control"
    assert len(_released(released, _FULL_PAGE, _FULL_PAGE_RELEASE)) > len(
        _released(section, _FULL_PAGE, _FULL_PAGE_RELEASE)
    ), (
        "flipping the emphasised prohibition releases nothing — the sweep is "
        "not reading the emphasised unit at all, so the equality above holds "
        "vacuously."
    )
