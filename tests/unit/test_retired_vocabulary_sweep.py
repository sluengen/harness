"""#455 — registered prose carries no retired vocabulary as a live instruction.

Two paradigm shifts landed in the files that *decide* them and stopped there.
ADR 0015 merged the three hold labels into two (``decision`` → ``input``), and
#448 replaced the Critical/High/Medium/Low severity scale with the blocking×size
2×2 and split filing from proposing (``review-insight`` retired with it). Both
were recorded in ``review-discipline``, ``tracker`` and ``craft.md``; neither
reached the eleven adjacent files that restate the model. An agent loading
``assessment-craft`` and ``review-discipline`` in one session therefore received
contradictory instructions about the same object, and nothing in the gate could
see it — the wavefront stranded silently, and would have stranded again on the
next shift.

This is the negative-space guard that makes the *next* migration finish. It
sweeps the registered prose surface for three **retired constructions** and
fails naming the files that carry one:

1. ``severity`` (case-insensitive). The retired thing is the *concept*, not the
   four grade names, so the token itself is the signal. Bare ``high`` / ``low`` /
   ``critical`` / ``medium`` are **never** matched — they are ordinary English
   ("a high-cardinality index", "low stakes"), and a sweep that flagged them
   would be turned off within a week.
2. A **three-label hold enumeration** — ``decision`` listed alongside ``input``,
   which is ADR 0006's retired model.
3. ``review-insight``, the retired filing label.

**The exemption is earned from the text, not granted by a list.** A match is
exempt when ``retire`` / ``retired`` / ``retires`` appears in the **same
sentence**. A file that names retired vocabulary *in order to retire it* pays for
its own exemption in the sentence doing the retiring; a file that merely uses the
vocabulary cannot. There is deliberately no per-file allowlist, because an
allowlist inside a sweep is an opt-out the sweep cannot audit (``craft.md`` —
*a blacklist inversion sweep fails open on an appended grant*), and every
allowlist needs a stale-exemption guard of its own.

**Three properties of the exemption are load-bearing, and each has a test below.**

* A ``;`` is **not** a sentence terminator. ``review-discipline``'s 2×2 puts its
  retirement clause after a semicolon — *"There are no severity grades beyond
  this; …is retired vocabulary."* — and splitting there would strand the
  retirement marker away from the token it retires, failing the file that states
  the rule correctly. :func:`test_the_splitter_keeps_the_semicolon_clause_together`
  pins it against the real sentence.
* The exemption must **not** be counterfeitable by adjacency. Moving the word
  "retired" into the *neighbouring* sentence has to make the match an offender
  again, or a nearby retirement notice would launder every live use around it —
  ``craft.md``'s *the text unit is part of the predicate*, which is where a
  splitter that under-splits shows up. :func:`test_the_exemption_does_not_reach_across_a_sentence`
  is the killer for that direction.
* The exemption must be bought by a **retirement**, not by any word that sounds
  like one. Nothing in the corpus can measure this — the corpus is green, so
  every sentence in it is already a non-offender and widening the marker moves
  nothing there. It is therefore a property only a synthetic pair can hold, and
  review found it unheld: widening the marker to ``superseded`` / ``deprecated``
  / ``legacy`` ran LIVE with the suite green, which is an opt-out anyone can
  grant by editing one alternation. :func:`test_only_a_retirement_buys_the_exemption`
  is the killer for that direction (#455).

The corpus rule is ``test_distributed_prose_no_repo_ids``'s and is mirrored
rather than imported: git-tracked ``*.md`` under the universal prose dirs that
``registry.yaml`` lists under ``files:``. ``settings/*.json`` is configuration,
not prose, and stays out — its ``autoMode.allow`` clause is guarded by
``test_settings_derived_parity`` instead.

**Where the sweep does not reach, stated at its size.** It sees the *token*
``severity``, so a grade name used bare — ``**High** finding``, a
``{Critical | High | Medium | Low}`` heading slot — is invisible to it by the
same design decision that keeps "high-value" out. Those were corrected by hand in
this change; a future one could reintroduce one, and this guard would stay green.
Closing that would need the grade-name overmatch this file exists to avoid, so
the gap is recorded here rather than papered over.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._gitutil import tracked_files_under

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY = _REPO_ROOT / "registry.yaml"

#: The universal-prose directories — the same set ``test_distributed_prose_no_repo_ids``
#: sweeps, which is the hook's ``PROSE`` set.
_PROSE_DIRS = ("skills", "agents", "commands", "process", "templates")


# ---------------------------------------------------------------------------
# The corpus
# ---------------------------------------------------------------------------


def _is_registered(rel_path: str, registry_src: str) -> bool:
    """Whether ``rel_path`` is a member of ``registry.yaml``'s files block.

    The same ``<path>: {`` mapping-key rule the freshness hook uses to decide
    what "distributed" means, so this sweep and the leak sweep agree about the
    surface they police.
    """
    pattern = r"(^|\n)\s*" + re.escape(rel_path) + r":\s*\{"
    return re.search(pattern, registry_src) is not None


def _registered_prose_files() -> list[Path]:
    """Git-tracked, registry-member ``*.md`` under the universal-prose dirs."""
    registry_src = _REGISTRY.read_text()
    found: list[Path] = []
    for prose_dir in _PROSE_DIRS:
        for path in sorted(tracked_files_under(prose_dir)):
            if path.suffix != ".md":
                continue
            rel = path.relative_to(_REPO_ROOT).as_posix()
            if _is_registered(rel, registry_src):
                found.append(path)
    return found


# ---------------------------------------------------------------------------
# The unit — a sentence, terminated by `.` and deliberately not by `;`
# ---------------------------------------------------------------------------

#: A sentence boundary: a terminator, any closing markup, then whitespace or the
#: end of the block. ``;`` is absent on purpose (see the module docstring), and
#: so is ``:`` — this tree writes rules as *"X: a, b, c."* constantly.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])[*_`)\]\"'>]*(?:\s+|$)")

#: Trailing forms whose ``.`` is not a terminator. Keeping the unit together is
#: the **widening** direction, and widening is the silent one: a longer unit is a
#: wider exemption window, so a marker further away still exempts and the sweep
#: reports *fewer* offenders. It is accepted only because these forms genuinely
#: do not end a sentence — an addition to this list is a real widening of the
#: exemption, and nothing below measures it, so weigh one as an edit to the
#: predicate rather than to a spelling list. Intra-token dots (``0.5.1``,
#: ``CONTEXT.md``) need no entry: the boundary requires whitespace after the dot.
_NON_TERMINAL = ("e.g.", "i.e.", "etc.", "cf.", "vs.", "approx.", "no.", "fig.")


def _sentences(text: str) -> list[str]:
    """``text`` split into sentences, each with its internal wrapping normalized.

    Prose here is hard-wrapped and a rule routinely spans two source lines, so a
    single ``\\n`` must **not** end a unit — the hold enumerations this sweep
    looks for wrap mid-list. A blank line does, because no sentence crosses one.
    """
    units: list[str] = []
    for block in text.split("\n\n"):
        start = 0
        for match in _SENTENCE_BOUNDARY.finditer(block):
            candidate = block[start : match.start()]
            if any(candidate.rstrip().lower().endswith(a) for a in _NON_TERMINAL):
                continue
            unit = " ".join(candidate.split())
            if unit:
                units.append(unit)
            start = match.end()
        tail = " ".join(block[start:].split())
        if tail:
            units.append(tail)
    return units


# ---------------------------------------------------------------------------
# The three retired constructions
# ---------------------------------------------------------------------------

#: The exemption: a sentence that retires the vocabulary it names.
_RETIREMENT_MARKER = re.compile(r"\bretire(?:d|s|ment)?\b", re.IGNORECASE)

#: Construction 1 — the retired concept, by its own name.
_SEVERITY = re.compile(r"\bseverit(?:y|ies)\b", re.IGNORECASE)

#: Construction 3 — the retired filing label.
_REVIEW_INSIGHT = re.compile(r"\breview-insight\b", re.IGNORECASE)

#: The separator between two members of an enumeration: a list punctuation mark
#: or the word "or", either side padded with whitespace. Whitespace **alone** is
#: not a separator — "a decision input" is ordinary prose, not a label list.
_ENUM_SEP = r"(?:\s*[,|/]\s*(?:or\s+)?|\s+or\s+)"
_HOLD_LABEL = r"(?:decision|input|operator)"
#: Construction 2 — a run of two or more hold labels joined by list separators.
#: A run is an offender only when it contains **both** ``decision`` and
#: ``input``: that pair is the retired three-label model, while ``input`` beside
#: ``operator`` is the live two-label one.
_HOLD_RUN = re.compile(
    rf"\b{_HOLD_LABEL}\b(?:{_ENUM_SEP}{_HOLD_LABEL}\b)+",
    re.IGNORECASE,
)

#: Markup stripped before the enumeration match. This tree writes label names in
#: backticks and joins them with a bolded ``**or**``, so the raw text of a live
#: list is ``` `decision`, `input`, **or** `operator` ``` — neither delimiter is
#: part of the enumeration, and leaving them in makes the separator regex a
#: catalogue of markdown rather than a description of a list.
_MARKUP = re.compile(r"[`*_]+")


def _retired_hold_enumerations(sentence: str) -> list[str]:
    """Runs of hold labels in ``sentence`` that enumerate the retired third."""
    plain = _MARKUP.sub("", sentence)
    return [
        run.group(0)
        for run in _HOLD_RUN.finditer(plain)
        if re.search(r"\bdecision\b", run.group(0), re.IGNORECASE)
        and re.search(r"\binput\b", run.group(0), re.IGNORECASE)
    ]


def _retired_constructions(text: str) -> list[str]:
    """Every unexempted retired construction in ``text``, as ``<kind>: <sentence>``.

    One pass over the sentences, because the exemption is a property of the
    sentence and not of the construction: a sentence that retires its vocabulary
    is exempt for all three at once.
    """
    found: list[str] = []
    for sentence in _sentences(text):
        if _RETIREMENT_MARKER.search(sentence):
            continue
        if _SEVERITY.search(sentence):
            found.append(f"severity: {sentence}")
        for run in _retired_hold_enumerations(sentence):
            found.append(f"three-label hold enumeration ({run!r}): {sentence}")
        if _REVIEW_INSIGHT.search(sentence):
            found.append(f"review-insight: {sentence}")
    return found


# ---------------------------------------------------------------------------
# Floors — an empty corpus, or a predicate that matches nothing, passes silently
# ---------------------------------------------------------------------------


def test_the_corpus_is_non_empty_and_holds_known_members() -> None:
    """FLOOR. A broken registry parse or a wrong root makes the sweep vacuous.

    Named anchors rather than a count: a cardinality floor is the drift this
    guard exists to remove (``craft.md`` — *floors decay into decoration*). One
    anchor per entry in :data:`_PROSE_DIRS`, which is the property that makes the
    floor complete: an anchor set covering only the dirs the migration happened
    to touch leaves the untouched ones droppable in silence. Review measured that
    — deleting ``process`` from the tuple removed ``process/harness.md``, the
    source of the three root mirrors and the first file every agent reads, from
    the swept corpus with the whole suite green (#455).
    """
    rels = {p.relative_to(_REPO_ROOT).as_posix() for p in _registered_prose_files()}
    for anchor in (
        "skills/assessment-craft/SKILL.md",
        "commands/assess.md",
        "agents/steward.md",
        "templates/assessment.md",
        "process/harness.md",
    ):
        assert anchor in rels, f"{anchor} is not in the swept corpus — the sweep would miss it"


def test_the_membership_predicate_discriminates() -> None:
    """FLOOR. Registry membership accepts a real entry and rejects a made-up one.

    Without the negative half the predicate could degrade to "always true" and
    the corpus would silently widen to every tracked ``.md`` — which is not a
    failure anyone would notice, because a wider corpus stays green.
    """
    registry_src = _REGISTRY.read_text()
    assert _is_registered("commands/assess.md", registry_src)
    assert not _is_registered("commands/does-not-exist.md", registry_src)


def test_the_splitter_keeps_the_semicolon_clause_together() -> None:
    """The unit boundary, measured against the real sentence that depends on it.

    ``review-discipline``'s 2×2 retires the grade names in a clause after a
    semicolon. If ``;`` ended a unit, the retirement marker would land in a
    different sentence from ``severity`` and the file that states the rule
    correctly would be this sweep's loudest offender — the guard failing the one
    document it was derived from. Read from the real file rather than quoted, so
    a rewording of that sentence re-anchors the control instead of leaving it
    describing text that moved.
    """
    text = (_REPO_ROOT / "skills" / "review-discipline" / "SKILL.md").read_text()
    carrying = [s for s in _sentences(text) if _SEVERITY.search(s) and ";" in s]
    assert carrying, (
        "review-discipline no longer states the retirement in a semicolon clause "
        "— re-anchor this control on whatever sentence now carries it"
    )
    assert all(_RETIREMENT_MARKER.search(s) for s in carrying), (
        "a semicolon split the retirement marker away from the vocabulary it "
        "retires; `;` must not terminate a unit (#455)"
    )


def test_the_exemption_does_not_reach_across_a_sentence() -> None:
    """The exemption's own killer: adjacency must not launder a live use.

    An exemption earned from the text is only as strong as the window it is
    earned in. Here the retirement marker is moved out of the match's sentence
    into the one beside it — the cheapest counterfeit, and the one an ordinary
    edit produces by accident when it splits a long sentence in two. The paired
    assertion is what makes it a control rather than an observation: the same
    text with the marker *in* the sentence must be exempt, so the difference
    measured is the window and not the wording.
    """
    exempt = 'There are no severity grades beyond this; "Critical/High" is retired vocabulary.'
    assert _retired_constructions(exempt) == []

    laundered = (
        'There are no severity grades beyond this; "Critical/High" is old vocabulary. '
        "That scale was retired."
    )
    offenders = _retired_constructions(laundered)
    assert offenders, (
        "a retirement marker in the *neighbouring* sentence exempted a live use "
        "— the exemption window is wider than a sentence, so any file can buy "
        "blanket immunity with one nearby notice (#455)"
    )
    assert all("severity" in o for o in offenders)


def test_only_a_retirement_buys_the_exemption() -> None:
    """The exemption's *vocabulary*, which the corpus cannot measure.

    The window has two controls above; this is the third property — **which
    words** open it. A green corpus says nothing about it, because widening the
    marker can only turn non-offenders into non-offenders there; the relation is
    observable on synthetic text alone. The pair is what makes it a control
    rather than an observation: the same sentence, the same match, and only the
    candidate word changing, so what is measured is the marker set and not the
    wording. Review established the gap by mutation before closing it — the
    widened alternation was live and every other assertion stayed green (#455).
    """
    for near_miss in (
        "A finding carries a superseded severity.",
        "The deprecated `review-insight` label goes on the issue.",
        "Apply the legacy `decision`, `input` labels to a held ticket.",
    ):
        assert _retired_constructions(near_miss), (
            f"a word that is not a retirement bought the exemption: {near_miss!r} "
            "— only `retire`/`retired`/`retires`/`retirement` may, or the marker "
            "set is an opt-out anyone can widen"
        )

    # The paired half: the real marker, in the same sentences, does exempt.
    for retiring in (
        "A finding carries a retired severity.",
        "The retired `review-insight` label goes on the issue.",
        "Apply the retired `decision`, `input` labels to a held ticket.",
    ):
        assert _retired_constructions(retiring) == [], (
            f"the retirement marker no longer exempts: {retiring!r} — the pair "
            "above would then be measuring the sentence, not the marker set"
        )


def test_the_sweep_does_not_match_bare_grade_words() -> None:
    """Overmatch control, on fresh prose the corpus does not contain.

    "High", "Medium", "Low" and "Critical" are ordinary English, and the
    corpus being green says nothing about them — it would be green under a
    predicate that matches nothing at all. These samples are written here so the
    negative is measured against text chosen to be tempting, not against the
    absence of a subject.
    """
    for benign in (
        "The lookup is backed by a high-cardinality index.",
        "The stakes are low and the blast radius is contained.",
        "This is the critical path through the gate.",
        "A medium-sized diff is still one review.",
        "The operator holds it at high priority until the input arrives.",
    ):
        assert _retired_constructions(benign) == [], f"overmatched benign prose: {benign!r}"


def test_the_constructions_discriminate() -> None:
    """The controls, through the same predicate the tree assertion calls.

    Each retired construction fires, and its live counterpart does not. The
    pairs are what make the claim real: a predicate that fired on everything, or
    on nothing, would leave the tree assertion passing for the wrong reason.
    """
    # 1 — the retired concept, and the 2×2 that replaced it.
    assert _retired_constructions("Each finding carries a severity.")
    assert _retired_constructions("A finding is blocking or not, and small or large.") == []

    # 2 — the retired three-label model, in every spelling the tree uses, and
    # the live two-label one beside it.
    for enumerated in (
        "--add-label <decision|input|operator>",
        "| Hold | `decision`, `input`, `operator` | Why a human holds a ticket |",
        "skip any ticket carrying `decision`, `input`, **or** `operator`",
        "exclude `decision`/`input`/\n`operator` as an optimisation",
    ):
        assert _retired_constructions(enumerated), f"missed a hold enumeration: {enumerated!r}"
    # The pair requirement, isolated. Every sample above enumerates all three
    # labels, so none of them can tell "contains `decision` and `input`" from
    # "contains all three" — and narrowing the predicate to the latter is the
    # silent direction, since it reports *fewer* offenders. This sample is the
    # retired pair with no `operator` in it, and it is the exclusive killer for
    # that narrowing; review found the gap by mutation (#455).
    assert _retired_constructions("apply `decision`, `input` to a held ticket"), (
        "the retired pair alone is not flagged — `decision` beside `input` is "
        "the retired model whether or not `operator` is listed with them"
    )
    assert _retired_constructions("--add-label <input|operator>") == []
    assert _retired_constructions("The two hold labels are `input` and `operator`.") == []
    # Whitespace alone is not a list separator: ordinary prose putting the two
    # words near each other is not an enumeration of labels.
    assert _retired_constructions("The operator supplies a decision input to the run.") == []

    # 3 — the retired filing label, and the live one.
    assert _retired_constructions("Label the insight `review-insight` when filing it.")
    assert _retired_constructions("Label the finding `review-finding` when filing it.") == []

    # The exemption, once, for each construction.
    assert _retired_constructions("The `review-insight` label is retired vocabulary.") == []
    assert _retired_constructions("`decision`, `input`, `operator` — `decision` is retired.") == []


def test_no_registered_prose_carries_retired_vocabulary() -> None:
    """#455 AC-1/AC-2: no registered prose file states a retired model as live."""
    violations: list[str] = []
    for path in _registered_prose_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for found in _retired_constructions(path.read_text()):
            violations.append(f"{rel}\n      {found}")

    assert not violations, (
        "registered prose states retired vocabulary as a live instruction. The "
        "severity scale is retired for the blocking×size 2×2 (`review-discipline`), "
        "there are exactly two hold labels (`tracker`), and an insight is proposed "
        "rather than filed under `review-insight`. Restate the current model, or — "
        "where the file names the old vocabulary in order to retire it — say so in "
        "the same sentence (#455):\n    " + "\n    ".join(violations)
    )
