"""The review-craft reference: its structure, its named patterns, its two roots.

What this module pins:

* the family headings (``## ``) are derived from the file and equal the recorded
  set — a renamed or dropped family fails here rather than quietly re-homing its
  patterns;
* the pattern set (``### ``) is derived from the file, not hand-listed, is
  non-empty, and sits above a floor set just under the measured count — the two
  conditions kept in separate tests so neither hides the other from mutation;
* the named anchors the change spec requires are present **by membership**, so a
  rename names itself instead of shrinking the set behind a count that still
  passes;
* every pattern body clears a character floor;
* the survivor-ambiguity entry points at the inert-survivor entry **by its exact
  heading**, the counterfeited-delimiter entry points at the text-unit entry the
  same way, and the two constant-predicate entries point at each other the same
  way in **both** directions, so no pair can drift into unrelated advice about the
  question it shares;
* the two constant-predicate entries are **neighbours**, in that order, pinned by
  the other's name rather than by a position — the family grouping settles which
  family, and nothing else settles that nothing sits between them;
* the three survivor entries sit under ``Mutation discipline``, the ordinal entry
  under ``Unmeasured claims``, the counterfeited-delimiter entry under
  ``Prose predicates and text guards``, and the frame-mismatch and
  unclassified-member entries under ``Vacuity`` — the family set and the pattern
  set are each derived alone, and neither knows a heading's *home*, so a pattern
  can migrate between existing families with both of them green;
* the header states the admission rule — additions are raised as proposals for an
  operator call rather than self-filed — in the prose above the first family
  heading, where a reader deciding whether to add an entry is looking;
* both citing roots name the reference by its repo-relative path.

What this module does **not** prove:

* **That a pattern carries a falsifying example.** The body assertion measures
  *length*. A long body with nothing concrete in it passes. No predicate short
  of reading the entry distinguishes an example from a restatement, and a
  keyword sweep for one would be exactly the fail-open blacklist the reference
  itself warns about. The floor catches the class it can catch: a pattern
  degraded to its one-line statement, which is the shape a distillation rots
  into.
* That the patterns are correct, mutually exclusive, or free of restatement of
  what the core skill already owns. Those are review judgments over prose, not
  properties of the tracked tree.
* **That the cross-referenced entries agree.** A link assertion proves one entry
  *names* another; it cannot read either and decide they say compatible things.
  The ambiguity entry could name an inert-survivor entry that contradicts it, and
  the counterfeited-delimiter entry could name the text-unit entry while
  describing the same mechanism rather than the neighbouring one it is supposed to
  distinguish itself from. Both pass here, and only a reviewer catches either.
* **That the admission rule is obeyed.** The header assertion reads the file's
  own prose. Whether a given entry was in fact held for an operator call is a
  property of how the change was filed, which no tree-reader can see.
* That any reader loads the file. A root naming the path is necessary, not
  sufficient.
* That a root names the path in every place it should. The build command cites
  it at both the implementation and the review brief; this asserts only that the
  path is *somewhere* in the file, so deleting one of the two cites survives.
  Measured, and left deliberately: a count is the cardinality floor the reference
  itself warns against, and it would rot the first time a third brief is added.

Registration, versioning and the one-level nesting rule are owned by the
guidance-topology guard; the app-cite and repo-id sweeps own this file's prose
constraints. None of that is re-asserted here.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

_CRAFT_REL = "skills/review-discipline/references/craft.md"
_CRAFT = REPO_ROOT / _CRAFT_REL

#: The roots that must brief a reader on the reference, each by path.
_CITING_ROOTS = ("skills/review-discipline/SKILL.md", "commands/build.md")

#: Spelled once each, because the family-membership assertions below need them by
#: exact heading as well and a heading spelled twice drifts once.
_MUTATION_FAMILY = "Mutation discipline"
_UNMEASURED_FAMILY = "Unmeasured claims — prose asserting what nothing checks"
_PROSE_FAMILY = "Prose predicates and text guards"
_VACUITY_FAMILY = "Vacuity — the test that cannot fail"

#: The families the reference is organised into, in order. Pinned as an
#: equality, so both a lost family and an unrecorded new one go red.
_FAMILIES = (
    _VACUITY_FAMILY,
    _PROSE_FAMILY,
    "Deletion, retirement, and re-homing",
    _MUTATION_FAMILY,
    "The ticket and its criteria",
    _UNMEASURED_FAMILY,
)

#: The three entries that between them decide what a surviving mutation means.
#: Named apart from the membership tuple below because the link assertion needs
#: two of them by exact heading and the family assertion needs all three, and a
#: heading spelled twice drifts once.
_AMBIGUITY_PATTERN = "A survivor is ambiguous"
_INERT_PATTERN = "An inert mutation reports a survivor it never earned"
_PAIRED_SPLICE_PATTERN = "A prose mutation needs a paired splice to prove it was live"

#: The entry naming the ordinal class. Spelled apart from the membership tuple
#: below for the same reason as the three above: the family pairing needs it by
#: exact heading too, and a heading spelled twice drifts once.
_ORDINAL_PATTERN = "An ordinal reference into an enumeration is invalidated by a correct insertion"

#: The two prose-predicate entries that divide the ways a text guard can read the
#: wrong span: one reads too much as a single unit, the other never opens part of
#: the corpus at all. Spelled apart from the membership tuple below because the
#: family pin and the link assertion each need them by exact heading, and a
#: heading spelled twice drifts once.
_TEXT_UNIT_PATTERN = "The text unit is part of the predicate"
_DELIMITER_PATTERN = "A paired delimiter can be counterfeited by prose that mentions it"

#: The two constant-predicate entries — an assertion that holds for every input,
#: which is the deadliest vacuity direction. One is constancy from an empty
#: subject, the other from operands that do not share a frame. Spelled apart from
#: the membership tuple below because the family pin and both link assertions need
#: them by exact heading, and a heading spelled twice drifts once.
_EMPTY_ITERABLE_PATTERN = "`all()` over a possibly-empty iterable is constant-true"
_FRAME_MISMATCH_PATTERN = "A comparison whose operands live in different frames is constant"

#: The entry naming the unclassified-member class. Spelled apart from the
#: membership tuple below for the same reason as the entries above: the family pin
#: needs it by exact heading too, and a heading spelled twice drifts once.
_UNCLASSIFIED_PATTERN = "A guard over an enumerable dimension must fail on an unclassified member"

#: Named patterns pinned by membership — one per family at minimum, covering the
#: lesson classes the change spec names. A rename shows up here as a missing
#: name rather than as a set that silently lost an entry.
_REQUIRED_PATTERNS = (
    "Exercise the production path, not merely a production constant",
    "The empty comparison set",
    _EMPTY_ITERABLE_PATTERN,
    _FRAME_MISMATCH_PATTERN,
    _UNCLASSIFIED_PATTERN,
    "A blacklist inversion sweep fails open on an appended grant",
    "The negation window assumes a false converse",
    _TEXT_UNIT_PATTERN,
    _DELIMITER_PATTERN,
    "A deletion pass that moves a definition must move its killer",
    "The wiring-field survivor",
    "Never re-run the builder's table as verification",
    _AMBIGUITY_PATTERN,
    _INERT_PATTERN,
    _PAIRED_SPLICE_PATTERN,
    "A ticket's grounding is its least reliable part",
    "A declined action is not a prevented one",
    _ORDINAL_PATTERN,
)

#: Measured at 46 patterns. The floor sits just under that: a slack floor set
#: far below the real count swallows whole families without going red. Re-derived
#: from the count on each addition rather than incremented, so the slack stays the
#: two entries it was measured at instead of growing by one every time.
_PATTERN_FLOOR = 44

#: Measured shortest body is 357 characters. The floor sits just under it. A
#: pattern stripped back to its one-line statement — the rule with the
#: falsifying example dropped — lands around 120 and trips this.
_BODY_FLOOR = 320

_HEADING = re.compile(r"^(#{2,3}) (.+)$", re.MULTILINE)


def _craft_text() -> str:
    return _CRAFT.read_text(encoding="utf-8")


def _sections() -> list[tuple[int, str, str]]:
    """``(level, heading, body)`` for every ``##``/``###`` section, in order.

    A section's body ends at the next heading of *either* level, so a pattern
    that happens to sit last under a family does not absorb the family heading
    that follows it.
    """
    text = _craft_text()
    marks = list(_HEADING.finditer(text))
    sections: list[tuple[int, str, str]] = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        sections.append((len(mark.group(1)), mark.group(2).strip(), text[mark.end() : end].strip()))
    return sections


def _header() -> str:
    """The prose above the first ``## `` family heading.

    Derived from the same heading scan as the sections, so a change to the file's
    heading shape moves both together. Returns ``""`` when no family heading is
    found at all, which the header assertion below rejects rather than treating
    as an empty header that trivially satisfies nothing.
    """
    text = _craft_text()
    first_family = next((m for m in _HEADING.finditer(text) if len(m.group(1)) == 2), None)
    return text[: first_family.start()] if first_family is not None else ""


def _families() -> list[str]:
    return [heading for level, heading, _ in _sections() if level == 2]


def _patterns() -> dict[str, str]:
    return {heading: body for level, heading, body in _sections() if level == 3}


def _patterns_by_family() -> dict[str, list[str]]:
    """``family -> [pattern, ...]``, from the same derivation as the two above.

    The two sets above are derived independently of each other, so between them
    they know every heading and no heading's *home*. This pairs them.
    """
    grouped: dict[str, list[str]] = {}
    family: str | None = None
    for level, heading, _ in _sections():
        if level == 2:
            family = heading
            grouped.setdefault(family, [])
        elif family is not None:
            grouped[family].append(heading)
    return grouped


def test_families_are_the_recorded_set() -> None:
    """The derived family set equals the recorded one, in both directions."""
    derived = _families()
    assert derived == list(_FAMILIES), f"family headings drifted: {derived}"


def test_pattern_derivation_is_non_vacuous() -> None:
    """The derivation found patterns at all.

    Kept apart from the floor below so each has its own killer. A heading-shape
    change that makes ``_patterns()`` derive to ``{}`` leaves the body sweep
    iterating over nothing — passing while measuring nothing — and this is the
    assertion that catches it.
    """
    assert _patterns(), "no ### patterns derived — the parser or the file's shape changed"


def test_pattern_count_is_above_its_floor() -> None:
    """Enough patterns survive, measured against a floor set just under the count."""
    patterns = _patterns()
    assert len(patterns) >= _PATTERN_FLOOR, (
        f"the reference carries {len(patterns)} patterns, under the floor of {_PATTERN_FLOOR}"
    )


def test_required_patterns_are_present_by_name() -> None:
    """The lesson classes the change spec names are present, pinned by membership."""
    derived = set(_patterns())
    missing = [name for name in _REQUIRED_PATTERNS if name not in derived]
    assert not missing, f"the reference lost required pattern(s): {missing}"


def test_every_pattern_body_clears_the_floor() -> None:
    """No pattern is reduced to its one-line statement.

    This measures length, not the presence of a falsifying example — see the
    module docstring. It catches the degradation a distillation actually
    suffers: an entry trimmed to its rule with the concrete case dropped.
    """
    thin = {name: len(body) for name, body in _patterns().items() if len(body) < _BODY_FLOOR}
    assert not thin, (
        f"pattern bodies under {_BODY_FLOOR} chars (statement with no example?): {thin}"
    )


def test_survivor_ambiguity_points_at_the_inert_reading() -> None:
    """The ambiguity entry names the inert entry, by its exact heading.

    A reader who lands on *A survivor is ambiguous* is choosing between readings
    of a survivor, and "the mutation changed nothing" is a reading — the one
    that makes the other three moot. Left unlinked, the two entries sit in the
    same family answering the same question without either mentioning the other,
    and a reader working from the ambiguity entry alone never reaches the check
    that would have voided their evidence.

    Pinned as a link rather than a keyword sweep for the *idea*: the heading is
    a string the file already commits to, so a rename fails here loudly instead
    of leaving a dangling pointer. What it cannot prove is that the two agree —
    see the module docstring.
    """
    patterns = _patterns()
    assert _AMBIGUITY_PATTERN in patterns, f"the reference lost {_AMBIGUITY_PATTERN!r}"
    assert _INERT_PATTERN in patterns, f"the reference lost {_INERT_PATTERN!r}"
    assert _INERT_PATTERN in patterns[_AMBIGUITY_PATTERN], (
        f"{_AMBIGUITY_PATTERN!r} does not point at {_INERT_PATTERN!r} — a reader "
        "choosing between readings of a survivor is never sent to the inert one"
    )


def test_the_delimiter_entry_points_at_the_text_unit_entry() -> None:
    """The counterfeited-delimiter entry names the text-unit entry, exactly.

    The two are neighbours answering the same reader question — *my text guard
    read the wrong span* — with opposite mechanisms and opposite remedies. The
    text-unit entry is a splitter reading too much as one unit, remedied by
    choosing the unit and pinning it; this one is the corpus silently shrinking
    before any unit is chosen, remedied by anchoring the delimiter and
    splice-proving the interior is reachable. A reader who lands on either and is
    not sent to the other will apply the remedy for the defect they do not have.

    Pinned as a link on the exact heading, like the survivor pair above, so a
    rename fails here loudly rather than leaving a dangling pointer. What it
    cannot prove is that the entry actually draws the distinction rather than
    merely mentioning the neighbour — see the module docstring.
    """
    patterns = _patterns()
    assert _DELIMITER_PATTERN in patterns, f"the reference lost {_DELIMITER_PATTERN!r}"
    assert _TEXT_UNIT_PATTERN in patterns, f"the reference lost {_TEXT_UNIT_PATTERN!r}"
    assert _TEXT_UNIT_PATTERN in patterns[_DELIMITER_PATTERN], (
        f"{_DELIMITER_PATTERN!r} does not name {_TEXT_UNIT_PATTERN!r} — a reader "
        "reaching one of the two ways a text guard reads the wrong span is never "
        "sent to the other, and the remedies are not interchangeable"
    )


def test_the_delimiter_entry_sits_under_prose_predicates() -> None:
    """The counterfeited-delimiter entry is in that family, not merely in the file.

    Its home was argued on its ticket and the alternative was rejected there: the
    class was assessed as an instance of *The text unit is part of the predicate*
    — foldable into that entry as a cross-referenced paragraph — and accepted
    instead as a sibling beside it, on the grounds that the mechanism and the
    remedy both differ and a folded paragraph would bury the remedy. Both halves
    of that call are structural: the family, and the adjacency the link assertion
    above depends on. A silent re-home would quietly re-decide the first half
    while leaving the link green.

    Kept apart from the two family pins above so each has its own killer: moving
    any one family's heading past its entries must go red on its own test rather
    than on a shared one.

    Like those two, this pins the family and not the position within it. The
    ticket settled which family; where the entry sits among its siblings is not a
    decision anyone made, and pinning a neighbour's index is the rot the ordinal
    entry names.
    """
    grouped = _patterns_by_family()
    assert _PROSE_FAMILY in grouped, f"no {_PROSE_FAMILY!r} family: {list(grouped)}"
    assert _DELIMITER_PATTERN in grouped[_PROSE_FAMILY], (
        f"{_DELIMITER_PATTERN!r} is no longer under {_PROSE_FAMILY!r} — "
        f"found under {[f for f, names in grouped.items() if _DELIMITER_PATTERN in names]}"
    )


def test_the_frame_entry_points_at_the_empty_iterable_entry() -> None:
    """The frame-mismatch entry names the empty-iterable entry, exactly.

    The two are the file's constant-predicate pair: both name an assertion that
    holds for every input, and a reader who has just watched one of them pass over
    a defect is one step from the other. The mechanisms and the remedies differ —
    an empty subject, remedied by asserting the subject is non-empty; operands in
    different frames, remedied by resolving both to a common root — so a reader
    sent to neither will reach for the wrong remedy.

    Pinned as a link on the exact heading, like the two pairs above, so a rename
    fails here loudly rather than leaving a dangling pointer. What it cannot prove
    is that the entry draws the distinction rather than merely mentioning its
    neighbour — see the module docstring.
    """
    patterns = _patterns()
    assert _FRAME_MISMATCH_PATTERN in patterns, f"the reference lost {_FRAME_MISMATCH_PATTERN!r}"
    assert _EMPTY_ITERABLE_PATTERN in patterns, f"the reference lost {_EMPTY_ITERABLE_PATTERN!r}"
    assert _EMPTY_ITERABLE_PATTERN in patterns[_FRAME_MISMATCH_PATTERN], (
        f"{_FRAME_MISMATCH_PATTERN!r} does not name {_EMPTY_ITERABLE_PATTERN!r} — a "
        "reader reaching one of the two ways an assertion becomes constant is never "
        "sent to the other, and the remedies are not interchangeable"
    )


def test_the_empty_iterable_entry_points_back_at_the_frame_entry() -> None:
    """The empty-iterable entry names the frame-mismatch entry, exactly.

    The other direction of the same pair, and a separate test because it is a
    separate obligation with a separate killer: deleting either sentence must go
    red on its own assertion rather than on a shared one that a surviving
    half keeps green.

    Both directions are pinned on the exact heading deliberately. Measured on the
    survivor pair, whose forward link is a heading and whose back-pointer is a
    description: nothing catches the description drifting into advice about
    something else, and the record says so. A pair asked for in both directions is
    two links, not a link and a gesture.
    """
    patterns = _patterns()
    assert _EMPTY_ITERABLE_PATTERN in patterns, f"the reference lost {_EMPTY_ITERABLE_PATTERN!r}"
    assert _FRAME_MISMATCH_PATTERN in patterns, f"the reference lost {_FRAME_MISMATCH_PATTERN!r}"
    assert _FRAME_MISMATCH_PATTERN in patterns[_EMPTY_ITERABLE_PATTERN], (
        f"{_EMPTY_ITERABLE_PATTERN!r} does not name {_FRAME_MISMATCH_PATTERN!r} — the "
        "back half of a cross-reference asked for in both directions is missing"
    )


def test_the_frame_entry_sits_under_vacuity() -> None:
    """The frame-mismatch entry is in that family, not merely in the file.

    Its home was argued on its ticket and the alternative was rejected there: the
    class was assessed as an instance of *A green mutation table certifies only
    what its author thought to mutate* — the entry naming why such a defect is
    missed — and accepted instead as a constant-predicate class in its own right,
    on the grounds that being missed by a table is true of every entry in the file
    and so decides nothing. The vacuity family, beside the empty-iterable entry, is
    the other half of that call.

    Kept apart from the three family pins above so each has its own killer: moving
    any one family's heading past its entries must go red on its own test.

    Like those, this pins the family and nothing about the position within it. The
    ticket settled which family *and* asked for adjacency; adjacency is not
    something the two links buy — measured at review, an entry interposed between
    the pair left every assertion in this module green — so it is pinned
    separately, by the neighbour's name, in the test below.
    """
    grouped = _patterns_by_family()
    assert _VACUITY_FAMILY in grouped, f"no {_VACUITY_FAMILY!r} family: {list(grouped)}"
    assert _FRAME_MISMATCH_PATTERN in grouped[_VACUITY_FAMILY], (
        f"{_FRAME_MISMATCH_PATTERN!r} is no longer under {_VACUITY_FAMILY!r} — "
        f"found under {[f for f, names in grouped.items() if _FRAME_MISMATCH_PATTERN in names]}"
    )


def test_the_unclassified_member_entry_sits_under_vacuity() -> None:
    """The unclassified-member entry is in that family, not merely in the file.

    Its home was argued on its ticket, and the ticket's own routing was wrong: it
    sent the entry to a "floors and controls family", which this file does not
    have. The correction was recorded before the build — the floors-and-controls
    entries are a *cluster inside* ``Vacuity``, not a family — so the family is a
    decision that took an argument to reach, and the class itself earns it: a
    classifier that skips what it cannot place makes its guard's assertion hold
    over a shrinking subject, which is the constant-predicate direction every
    entry in this family names. A silent re-home to the deletion or
    prose-predicate family would quietly re-decide that.

    Kept apart from the other family pins so each has its own killer: moving any
    one family's heading past its entries must go red on its own test.

    Position within the family is deliberately not pinned. The entry sits after
    *Floors decay into decoration*, which is where the cluster it belongs to ends
    — but the only positional fact anyone argued is that it must not land between
    the constant-predicate pair, and ``test_the_constant_predicate_pair_is_adjacent``
    already owns that. A second pin would guard the same event twice and start the
    duplicate map of the file's structure this module declines to keep.
    """
    grouped = _patterns_by_family()
    assert _VACUITY_FAMILY in grouped, f"no {_VACUITY_FAMILY!r} family: {list(grouped)}"
    assert _UNCLASSIFIED_PATTERN in grouped[_VACUITY_FAMILY], (
        f"{_UNCLASSIFIED_PATTERN!r} is no longer under {_VACUITY_FAMILY!r} — "
        f"found under {[f for f, names in grouped.items() if _UNCLASSIFIED_PATTERN in names]}"
    )


def test_the_constant_predicate_pair_is_adjacent() -> None:
    """Nothing sits between the two constant-predicate entries, in that order.

    The family pin above settles *which* family. The change spec asked for two
    things — the entry in that family and **adjacent to** the constant-true entry
    — and only the first was derivable from the family grouping. Measured at
    review by an interposed entry: the family set, the membership tuple, both
    links, both floors and every family pin stayed green while the pair stopped
    being neighbours, so each entry's `above`/`below` locator for the other went
    stale with nothing red.

    Pinned by the neighbour's **name**, never by a position, which is the
    distinction the ordinal entry draws. A name-pinned neighbour goes red only on
    an insertion *between the two* — the event this exists to detect — where a
    pinned index rots on any insertion anywhere above it. That is also why this is
    admissible here and was declined for the ordinal entry: there the ticket said
    nothing about a neighbour, so a pin would have guarded a decision nobody made.

    The order is part of the claim, not incidental: the constant-true entry
    locates its sibling *below* and the frame entry locates its sibling *above*,
    so a swap leaves two sentences that name the right heading and point the wrong
    way.
    """
    under = _patterns_by_family().get(_VACUITY_FAMILY, [])
    for name in (_EMPTY_ITERABLE_PATTERN, _FRAME_MISMATCH_PATTERN):
        assert name in under, f"{name!r} is not under {_VACUITY_FAMILY!r}: {under}"
    after = under[under.index(_EMPTY_ITERABLE_PATTERN) + 1 :]
    assert after[:1] == [_FRAME_MISMATCH_PATTERN], (
        f"{_FRAME_MISMATCH_PATTERN!r} no longer follows {_EMPTY_ITERABLE_PATTERN!r} "
        f"immediately — {after[:1] or ['nothing']} does — so each entry's locator "
        "for the other is stale while both links stay green"
    )


def test_the_header_states_the_admission_rule() -> None:
    """The header says additions are proposed for an operator call, not self-filed.

    Asserted against the header specifically — the prose above the first family
    heading — because the rule governs whether to add an entry at all, so it has
    to reach a reader before they are inside a family reading entries. Somewhere
    in the file is not the same claim: below the first heading it is a footnote to
    a reader who has already decided.

    Narrowed twice — to the one header paragraph naming ``self-filed``, then to
    the one *sentence* of it that does — because three file-wide containments are
    satisfied by three unrelated sentences, and so, measured, is the paragraph:
    the paragraph's closing sentence names the operator again for a different
    reason, so a rule rewritten to hold additions for somebody else kept the
    paragraph-scoped assertion green. The sentence is the unit that makes the
    terms co-occur *in the rule*. What it does not prove is that the rule was
    obeyed — see the module docstring.

    **The named mechanism changed, so this assertion changed with it.** The rule
    used to hold a candidate on the tracker under the ``input`` label, and the
    term this required was ``` `input` ```. Under the bugs-are-filed /
    improvements-are-proposed rule an addition to this file is an improvement, so
    it may not be filed at all: it is a **proposal**, raised in a report and
    ratified by the operator, and there is no held ticket to label. Requiring the
    retired term would now pin the retired mechanism, which is the drift a version
    stamp cannot see — so the required term is the one that names the channel.
    """
    header = _header()
    assert header.strip(), "no header derived — the file has no ## family heading"

    paragraphs = [block.strip() for block in header.split("\n\n") if block.strip()]
    stating = [block for block in paragraphs if "self-filed" in block]
    assert len(stating) == 1, (
        "the header must carry exactly one paragraph stating the admission rule; "
        f"found {len(stating)} mentioning 'self-filed'"
    )

    sentences = re.split(r"(?<=\.)\s+", stating[0])
    rule = next((sentence for sentence in sentences if "self-filed" in sentence), "")
    assert rule, (
        "the admission paragraph did not split into a sentence naming 'self-filed' — "
        f"the sentence unit stopped resolving over {len(sentences)} part(s)"
    )

    missing = [term for term in ("operator", "proposal") if term not in rule]
    assert not missing, (
        f"the admission rule does not name {missing} — an addition held for "
        "nobody in particular, by no named mechanism, is not held"
    )


def test_the_survivor_entries_sit_under_mutation_discipline() -> None:
    """The three survivor entries are in that family, not merely in the file.

    Membership above proves a name exists *somewhere*; the family equality proves
    no family was gained or lost. Neither pairs the two, so a pattern can migrate
    to a different existing family with the set, the order, the count and every
    required name unchanged — measured, by moving the family heading past a
    pattern and watching every assertion in this module stay green.

    That matters here because "in the Mutation discipline family" is the wording
    of the criteria these three entries answer to, and because the link between
    the ambiguity entry and the inert one is argued from their sharing a family:
    a reader who reaches one is meant to be one heading away from the other.

    Only the entries whose family is argued for on their ticket are pinned to a
    home — these three, and the ordinal entry. A hand-written family for
    all forty-odd would be a second copy of the file's structure, and it would
    rot into a maintenance tax that teaches a later editor to re-point the map
    rather than to question the move.
    """
    grouped = _patterns_by_family()
    assert _MUTATION_FAMILY in grouped, f"no {_MUTATION_FAMILY!r} family: {list(grouped)}"
    under = grouped[_MUTATION_FAMILY]
    strays = [
        name
        for name in (_AMBIGUITY_PATTERN, _INERT_PATTERN, _PAIRED_SPLICE_PATTERN)
        if name not in under
    ]
    assert not strays, f"pattern(s) no longer under {_MUTATION_FAMILY!r}: {strays}"


def test_the_ordinal_entry_sits_under_unmeasured_claims() -> None:
    """The ordinal entry is in that family, not merely in the file.

    Its home was the open question on its ticket: the deletion family would hold
    it if the class is read as a structural edit alongside deletion and
    relocation, and the unmeasured-claims family holds it if the class is read as
    an internal document reference nothing checks. The document-reference reading
    was the call, on the boundary that a forward reference was *never* true while
    an ordinal reference *was* true and a later, individually correct edit
    invalidated it. A decision that took an argument to
    reach is pinned, so a silent re-home fails rather than quietly re-deciding it.

    Kept apart from the survivor-family assertion above so each has its own
    killer: moving either family's heading past its entries must go red on its
    own test rather than on a shared one.

    Deliberately absent: any pin on where the entry sits *within* the family.
    Not because adjacency cannot be pinned safely: pinned by a neighbour's
    *name*, it would go red only on an insertion between the two, which is the
    event it would be detecting rather than rot — the entry's own rule is that a
    referent named survives what an index does not. The reason is narrower. The
    ticket settled this entry's family and said nothing about its neighbour, so a
    neighbour pin would guard a decision nobody made, and it would start the
    second copy of the file's structure the paragraph above declines to keep.
    """
    grouped = _patterns_by_family()
    assert _UNMEASURED_FAMILY in grouped, f"no {_UNMEASURED_FAMILY!r} family: {list(grouped)}"
    assert _ORDINAL_PATTERN in grouped[_UNMEASURED_FAMILY], (
        f"{_ORDINAL_PATTERN!r} is no longer under {_UNMEASURED_FAMILY!r} — "
        f"found under {[f for f, names in grouped.items() if _ORDINAL_PATTERN in names]}"
    )


def test_both_citing_roots_name_the_reference() -> None:
    """`review-discipline` and the build command each link the file by path."""
    for root in _CITING_ROOTS:
        text = (REPO_ROOT / root).read_text(encoding="utf-8")
        assert _CRAFT_REL in text, f"{root} does not name {_CRAFT_REL}"


def test_version_header_is_the_first_line() -> None:
    """The guidance stamp leads the file, where the freshness hook reads it."""
    first = _craft_text().splitlines()[0]
    assert re.fullmatch(r"<!-- guidance:review-discipline-craft@\d+\.\d+\.\d+ -->", first), (
        f"first line is not the guidance stamp: {first!r}"
    )
