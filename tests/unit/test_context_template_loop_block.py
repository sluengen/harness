"""Every loop knob carries one value in three places, and the prose says so — #291.

``harness/loop_budget.py`` reads a set of integers out of a ``loop:`` block —
``max_review_cycles``, ``wall_clock_budget_minutes``, ``engine_timeout_seconds``
and, since #297, ``attended_idle_minutes``. Each has a code-level constant used
when the key — or the whole ``CONTEXT.md`` — is absent, so each value exists in
three places: the constant, this repo's own ``CONTEXT.md``, and the block a
bootstrapped repo receives in ``templates/CONTEXT.template.md``.

Two of those three places were unguarded. The template shipped **no** ``loop:``
block at all, so every bootstrapped repo ran on the constants with nowhere to
see or set them — while ``harness/cli/design.py`` told a repo that just lost a
design run to *"raise ``engine_timeout_seconds`` in CONTEXT.md's ``loop:``
block"*, remediation naming a block their ``CONTEXT.md`` did not have. And the
``engine_timeout_seconds`` retune (600 → 720) moved this repo's configured value
without moving the constant, so the unconfigured path silently ran a different
ceiling from the configured one.

These guards pin all three places against **the constants**, which are the
source: ``load_loop_budget`` never reads the template (an installed repo has no
template), so the template and ``CONTEXT.md`` are copies that must not drift.
The knob table is *derived* rather than restated — the constant's name is
``DEFAULT_`` + the key upper-cased — so a knob added to ``LoopBudget`` is
covered here the day it is added rather than the day someone remembers to
extend a list. #297's ``attended_idle_minutes`` is the first knob that arrived
that way: adding the field without adding the key to both files fails this
module, which is the whole design.

The parse is single-sourced too: :data:`harness.loop_budget._KEY_PATTERN` is the
runtime reader's own regex, imported rather than recopied, so a guard cannot
pass against a pattern the engine does not use.

A second relation lives here for the same reason — #292. The
``engine_timeout_seconds`` comment did not only describe its own value; it
asserted a *relation between the two engines the one ceiling covers*, claiming
the design engine (studies a whole worktree) is systematically slower than the
review engine (reads a diff) and calling the single knob a mis-fit to revisit.
That claim was never measured — ADR 0009 records that review latency was
unreconstructable until #264/#265, so the 600 → 720 retune saw only design's
distribution. Once it could be measured it did not hold: design leads by 45s at
the median and *trails* at both q3 and max, and the tail is the only part a
timeout ceiling interacts with. ``specs/proposals/per-engine-timeout-ceiling.md``
rejected the split on that evidence.

So the prose is checked against the measurement the same way the knob prose is
checked against the constants: the premise is **derived** from the proposal's
committed latency table, and only then is the comment required not to contradict
it and required to quote it. Neither half stands alone — a derivation nothing
reads goes green while the prose rots, and a phrase pin goes green on a reword.
The coupling runs both ways on purpose: a future re-measurement that inverts the
tail fails this module, because ``CONTEXT.md`` and the rejection both rest on
the premise it would overturn.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from harness import loop_budget
from harness.loop_budget import load_loop_budget
from tests.unit.test_review_discipline_watchlist_entry_currency import _sentences

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE = _REPO_ROOT / "templates" / "CONTEXT.template.md"
_CONTEXT = _REPO_ROOT / "CONTEXT.md"
_PROPOSAL = _REPO_ROOT / "specs" / "proposals" / "per-engine-timeout-ceiling.md"

# The knobs `LoopBudget` carries, in field order. The matching constant is
# derived from the key, never written out beside it (see the module docstring).
_KEYS = (
    "max_review_cycles",
    "wall_clock_budget_minutes",
    "engine_timeout_seconds",
    "attended_idle_minutes",
    # Appended last because ``LoopBudget`` appends it last (#329) —
    # ``test_template_parses_with_the_runtime_reader`` constructs the tuple
    # positionally from this order, so the two must not drift.
    "unconditional_review_cycles",
    # …and the same rule again for #321's ``review_model``, the first knob here
    # that is not an integer. It is the reason :func:`_constant` and
    # :func:`_configured` read the *constant's* type rather than assuming ``int``:
    # a type-blind guard would have gone red the day this field landed and been
    # "fixed" by dropping the key from the table, which is exactly the drift the
    # derived table exists to prevent.
    "review_model",
)

_IDENTIFIER = re.compile(r"DEFAULT_[A-Z_]+")

# Phrases that assert two numbers are deliberately *held apart*. Applied only to
# a sentence already proven to be describing an equality, so the marker set does
# not have to distinguish a true divergence claim from a false one — by the time
# it is consulted, any divergence claim is false.
_DIVERGENCE_MARKERS = (
    "not applied",
    "unlike",
    "differs",
    "diverges",
    "held apart",
    "rather than",
)

# The engines the one ceiling covers, as the proposal's table keys them.
_ENGINES = ("design", "review")

# The statistics a timeout ceiling actually interacts with. The median is
# deliberately absent: design *does* lead there (366s vs 321s), and a predicate
# that counted it would read the honest half of the record as a contradiction.
_TAIL_STATISTICS = ("q3", "max")

# Phrases that assert one engine is durably slower than the other, or that treat
# the single ceiling as a defect awaiting a split. Applied only once the recorded
# measurement has been shown not to support such an ordering, so — as with
# `_DIVERGENCE_MARKERS` — the marker set never has to tell a true claim from a
# false one; by the time it is consulted, any such claim is false.
_ENGINE_SPEED_MARKERS = (
    "systematically slower",
    "systematically faster",
    "slower than",
    "faster than",
    "mis-fit",
    "misfit",
    "revisit separately",
)


def _constant(key: str) -> int | str:
    """The code-level fallback for ``key`` — derived from the key's own name."""
    return getattr(loop_budget, f"DEFAULT_{key.upper()}")


def _pattern_for(key: str) -> str:
    """The runtime reader's own regex for ``key``, chosen by the constant's type.

    Which of the two patterns applies is a property of the knob, and the knob
    already declares it: its constant is an ``int`` or a ``str``. Deriving the
    choice from that — rather than from a second list of "the string keys" —
    keeps this guard's single-source property intact for the next non-integer
    knob (#321).
    """
    pattern = (
        loop_budget._KEY_PATTERN
        if isinstance(_constant(key), int)
        else loop_budget._STR_KEY_PATTERN
    )
    return pattern.format(key=re.escape(key))


def _configured(text: str, key: str) -> int | str | None:
    """The value ``key`` is set to, read with the runtime reader's own pattern.

    ``None`` when the key is absent or does not parse in the shape its own
    reader accepts — which is exactly when :func:`load_loop_budget` falls back
    to the constant, so the distinction "set to 720" versus "absent and
    defaulting to 720" is recoverable here even though the loaded budget cannot
    tell them apart.

    The returned value is coerced to the constant's own type, so a comparison
    against :func:`_constant` is like-for-like rather than ``"720" != 720``.
    """
    match = re.search(_pattern_for(key), text, re.MULTILINE)
    if match is None:
        return None
    return type(_constant(key))(match.group(1))


def _comment(text: str, key: str) -> str:
    """The inline ``#`` comment on ``key``'s line — the prose about that knob."""
    match = re.search(rf"^\s*{re.escape(key)}:[^\n]*$", text, re.MULTILINE)
    assert match is not None, f"{key} must appear in the file under test"
    _, _, comment = match.group(0).partition("#")
    return comment.strip()


def _cells(line: str) -> list[str]:
    """A Markdown table row's cells, backticks stripped (the table keys them)."""
    return [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]


def _latency_table(text: str) -> dict[str, dict[str, int]]:
    """The proposal's measured per-engine duration table, parsed.

    Selected by *shape*, not by line number: the header row is the one naming
    every statistic in :data:`_TAIL_STATISTICS`, and the data rows are the ones
    whose first cell is an engine name. The Open-decisions table further down
    shares neither, so it cannot be picked up by accident.

    Returns ``{}`` when no such table is found. Every caller asserts on the
    parse first (:func:`test_measured_latency_table_parses`), so a proposal that
    is renamed or reshaped fails loudly instead of letting the derivations below
    range over an empty dict and pass vacuously.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        header = _cells(line)
        if not set(_TAIL_STATISTICS) <= set(header):
            continue
        table: dict[str, dict[str, int]] = {}
        for row in lines[index + 1 :]:
            cells = _cells(row)
            if len(cells) != len(header) or cells[0] not in _ENGINES:
                if table:
                    break
                continue
            table[cells[0]] = {
                name: int(value.rstrip("s"))
                for name, value in zip(header[1:], cells[1:], strict=True)
                if re.fullmatch(r"\d+s?", value)
            }
        return table
    return {}


def _tail_favours_design(table: dict[str, dict[str, int]]) -> bool:
    """Does the record show design out-running review where a ceiling bites?

    True only when design's value exceeds review's at **every** tail statistic —
    the shape of the claim ``CONTEXT.md`` used to make. One statistic going the
    other way is enough to make "systematically slower" the wrong description,
    which is exactly what the 2026-08-02 measurement found.
    """
    return all(
        table["design"][statistic] > table["review"][statistic]
        for statistic in _TAIL_STATISTICS
    )


def _frontmatter_status(text: str) -> str | None:
    """``status:`` from a spec's leading ``---`` block, or ``None``."""
    block = re.search(r"^---$(.*?)^---$", text, re.MULTILINE | re.DOTALL)
    if block is None:
        return None
    status = re.search(r"^status:\s*(\S+)", block.group(1), re.MULTILINE)
    return status.group(1) if status else None


def _quotes_number(sentence: str, value: int) -> bool:
    """Is ``value`` quoted in ``sentence`` as a whole number?

    Digit-bounded rather than a plain substring test, so ``561`` does not match
    inside ``5610`` while ``561s`` still counts.
    """
    return re.search(rf"(?<!\d){value}(?!\d)", sentence) is not None


# --- AC-2: the template ships the block ---------------------------------------


def test_template_declares_every_loop_key() -> None:
    """The bootstrap template carries every knob as a bare integer (AC-2).

    Presence is asserted *directly* rather than through
    :func:`load_loop_budget`, because a missing key falls back to its constant —
    so a loaded budget that reads ``(6, 110, 720)`` proves nothing about whether
    the template says anything at all.
    :func:`test_the_parse_finds_nothing_when_the_block_is_missing` is the
    negative control that pins that reasoning.
    """
    text = _TEMPLATE.read_text(encoding="utf-8")

    missing = [key for key in _KEYS if _configured(text, key) is None]
    assert not missing, (
        f"templates/CONTEXT.template.md must declare {sorted(missing)} in its "
        "`loop:` block as bare integers. A repo bootstrapped from the template "
        "otherwise has no place to set the knobs, and `harness design`'s "
        "engine_timeout remediation names a block it does not have."
    )


def test_template_values_match_the_constants() -> None:
    """Every value shipped in the template equals its code constant (AC-3).

    This is the anti-drift half: a future retune that moves a constant without
    moving the template hands every bootstrapped repo a block that *looks*
    configured while describing a budget the harness no longer runs.
    """
    text = _TEMPLATE.read_text(encoding="utf-8")

    for key in _KEYS:
        assert _configured(text, key) == _constant(key), (
            f"templates/CONTEXT.template.md sets `{key}` to "
            f"{_configured(text, key)} but harness/loop_budget.py's "
            f"DEFAULT_{key.upper()} is {_constant(key)}. Move them together."
        )


def test_template_parses_with_the_runtime_reader(tmp_path: Path) -> None:
    """The shipped block is readable *in situ*, not merely present (AC-2/AC-3).

    Copying the template verbatim to a repo's ``CONTEXT.md`` is what a bootstrap
    does, so this feeds the whole file to the **real loader** rather than to
    :func:`_configured`'s re-application of its regex. That is what makes it a
    distinct measure: ``_configured`` only proves the pattern matches somewhere,
    while ``load_loop_budget`` also wires each key name to a ``LoopBudget``
    field. Mutating the loader to read ``engine_timeout_seconds`` from the
    ``max_review_cycles`` key kills this test and
    :func:`test_shipped_context_matches_the_constants` while every pattern-based
    test above stays green — a mis-wiring only the loader can show.
    """
    (tmp_path / "CONTEXT.md").write_text(
        _TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8"
    )

    budget = load_loop_budget(tmp_path)

    assert budget == loop_budget.LoopBudget(*(_constant(key) for key in _KEYS))


def test_the_parse_finds_nothing_when_the_block_is_missing(tmp_path: Path) -> None:
    """Negative control — the three tests above cannot pass off the fallback.

    Strip the knobs from the template and two things must hold: the direct parse
    finds nothing (so the presence check is a real measure), while
    :func:`load_loop_budget` still returns the very same numbers the tests above
    assert (so a check written only through the loader would be satisfied by a
    template that says nothing). That gap is the whole reason the presence and
    the in-situ checks are separate tests.
    """
    text = _TEMPLATE.read_text(encoding="utf-8")
    for key in _KEYS:
        text = re.sub(
            _pattern_for(key),
            "",
            text,
            flags=re.MULTILINE,
        )
    (tmp_path / "CONTEXT.md").write_text(text, encoding="utf-8")

    assert [_configured(text, key) for key in _KEYS] == [None] * len(_KEYS)
    assert load_loop_budget(tmp_path) == loop_budget.LoopBudget(
        *(_constant(key) for key in _KEYS)
    )


# --- AC-1 / AC-4: this repo's own CONTEXT.md ----------------------------------


def test_shipped_context_matches_the_constants() -> None:
    """This repo configures exactly what an unconfigured repo falls back to (AC-1).

    Generalises ``test_shipped_context_configures_the_same_value_the_code_defaults_to``
    (``tests/unit/test_cli_reclaim.py``, #260) from the wall clock to all three
    knobs. Where the two diverge, this repo's ledger evidence — the only evidence
    there is — has been used to tune a value that no consuming repo receives.
    """
    budget = load_loop_budget(_REPO_ROOT)

    assert budget == loop_budget.LoopBudget(*(_constant(key) for key in _KEYS))


def test_context_prose_asserts_no_divergence_that_does_not_exist() -> None:
    """A knob's comment may not deny an equality the same line establishes (AC-4).

    Two steps, and both are needed. First the relation is **derived**: every
    ``DEFAULT_*`` identifier a knob's comment names must resolve in
    ``harness.loop_budget`` and must equal the value configured on that same
    line. Only then — knowing the measured relation *is* equality — is the
    sentence naming that identifier required to carry no divergence marker.

    Step one alone goes green the moment the constant is flipped, without the
    comment being touched at all, so it cannot stand for AC-4's requirement that
    the *correction* be measured. Step two alone is a phrase pin that a reword
    slips past. Together they derive the claim from the numbers and then require
    the prose not to contradict it.

    Honest residual: a false claim phrased without any of the markers still
    passes. This covers the class the ticket names — an explicit "held apart"
    assertion beside numbers that are equal — not all possible false prose.
    """
    text = _CONTEXT.read_text(encoding="utf-8")

    named_anywhere = 0
    for key in _KEYS:
        comment = _comment(text, key)
        configured = _configured(text, key)
        for identifier in _IDENTIFIER.findall(comment):
            named_anywhere += 1
            assert hasattr(loop_budget, identifier), (
                f"CONTEXT.md's `{key}` comment names {identifier}, which no "
                "longer exists in harness/loop_budget.py — prose that names "
                "code is checked against the code."
            )
            assert getattr(loop_budget, identifier) == configured, (
                f"CONTEXT.md sets `{key}` to {configured} while the "
                f"{identifier} it names is {getattr(loop_budget, identifier)}."
            )
            for sentence in _sentences(comment):
                if identifier not in sentence:
                    continue
                lowered = sentence.lower()
                marker = next(
                    (m for m in _DIVERGENCE_MARKERS if m in lowered), None
                )
                assert marker is None, (
                    f"CONTEXT.md's `{key}` comment says {marker!r} about "
                    f"{identifier}, but that constant and the configured value "
                    f"are both {configured}. The sentence asserts a divergence "
                    "that does not exist."
                )

    assert named_anywhere, (
        "no `loop:` comment names its DEFAULT_* constant, so this guard "
        "measured nothing. The engine-timeout comment in particular must state "
        "the lockstep it now keeps, naming the constant it keeps step with."
    )


# --- the nesting the retune must not invert -----------------------------------


def test_the_engine_ceiling_nests_inside_the_wall_clock() -> None:
    """A per-subprocess ceiling only means something inside a larger per-run one.

    Pins the *ordering*, not the numbers, in the spirit of
    ``tests/unit/test_timeout_budgets_coherent.py``: either knob may be retuned
    as long as a single engine invocation still cannot outlast the run budget
    that encloses it.
    """
    assert (
        loop_budget.DEFAULT_ENGINE_TIMEOUT_SECONDS
        < loop_budget.DEFAULT_WALL_CLOCK_BUDGET_MINUTES * 60
    )


# --- #292: the one ceiling's rationale, against the measurement ---------------


def test_measured_latency_table_parses() -> None:
    """The proposal's latency table is readable — the non-vacuity anchor.

    Every derivation below ranges over this table, and
    :func:`_latency_table` answers ``{}`` rather than raising when the proposal
    is renamed or its table reshaped. Without this test that ``{}`` would make
    the tail predicate trivially true and the guard silently stop measuring —
    the same role ``named_anywhere`` plays in
    :func:`test_context_prose_asserts_no_divergence_that_does_not_exist`.
    """
    table = _latency_table(_PROPOSAL.read_text(encoding="utf-8"))

    assert set(table) == set(_ENGINES), (
        f"{_PROPOSAL.relative_to(_REPO_ROOT)} must carry a per-engine latency "
        f"table keyed `design` / `review`; parsed {sorted(table)}. It is the "
        "record CONTEXT.md's engine_timeout_seconds rationale is checked "
        "against — if it moved, point this guard at where it moved to."
    )
    for engine in _ENGINES:
        missing = [s for s in _TAIL_STATISTICS if s not in table[engine]]
        assert not missing, (
            f"the `{engine}` row must report {sorted(missing)} — the tail is "
            "the only part a timeout ceiling interacts with, so a table "
            "without it cannot settle the claim the ceiling's prose makes."
        )


def test_tail_predicate_flags_a_table_where_design_dominates() -> None:
    """Negative control — :func:`_tail_favours_design` is a measure, not ``False``.

    Fed a synthetic table in which design leads at every tail statistic, the
    predicate must say so. Without this, the derivation test below would pass
    just as happily against a predicate hardcoded to ``False``, and the
    "measured, not hand-checked" requirement would be unmet.
    """
    dominating = {
        "design": {"q3": 500, "max": 700},
        "review": {"q3": 400, "max": 600},
    }

    assert _tail_favours_design(dominating)
    assert not _tail_favours_design(
        {"design": {"q3": 500, "max": 500}, "review": {"q3": 400, "max": 600}}
    )


def test_the_recorded_measurement_does_not_show_design_dominating_the_tail() -> None:
    """The derivation: the record does not support a design-is-slower claim.

    This is the step that makes the correction *measured*. It is not a
    restatement of today's numbers — it is the premise both ``CONTEXT.md:42``
    and the proposal's rejection rest on, re-derived from the committed record
    every run. A re-measurement that inverts the tail fails here, which is the
    signal that the rejection and the prose both need revisiting rather than
    that this guard needs relaxing.
    """
    table = _latency_table(_PROPOSAL.read_text(encoding="utf-8"))

    assert not _tail_favours_design(table), (
        "the recorded measurement now shows the design engine leading review at "
        f"every tail statistic ({', '.join(_TAIL_STATISTICS)}): design "
        f"{ {s: table['design'][s] for s in _TAIL_STATISTICS} } vs review "
        f"{ {s: table['review'][s] for s in _TAIL_STATISTICS} }. That is the "
        "premise the per-engine split was rejected for lacking — revisit "
        f"{_PROPOSAL.relative_to(_REPO_ROOT)} and CONTEXT.md's "
        "engine_timeout_seconds rationale together, rather than editing this "
        "assertion."
    )


def test_context_engine_rationale_carries_no_refuted_speed_claim() -> None:
    """The comment may not assert an ordering the measurement does not show (AC-1).

    Two steps, as in the divergence guard above: the relation is derived from
    the table first, and only then is the prose required not to contradict it.
    Step one alone would go green while the sentence rotted; step two alone
    would be a phrase pin that any reword slips past.

    Honest residual: a false claim phrased without any of the markers — "design
    takes appreciably longer, so one knob is a compromise" — still passes here.
    It is caught, if at all, by
    :func:`test_context_engine_rationale_quotes_a_measured_tail_pair`, which
    requires the numbers that refute it to be on the same line. This covers the
    class the ticket names, not all possible false prose.
    """
    table = _latency_table(_PROPOSAL.read_text(encoding="utf-8"))
    assert not _tail_favours_design(table)

    comment = _comment(_CONTEXT.read_text(encoding="utf-8"), "engine_timeout_seconds")

    lowered = comment.lower()
    marker = next((m for m in _ENGINE_SPEED_MARKERS if m in lowered), None)
    assert marker is None, (
        f"CONTEXT.md's engine_timeout_seconds comment says {marker!r}, but the "
        "measurement it would have to rest on shows the opposite where a "
        f"ceiling bites: design q3 {table['design']['q3']}s / max "
        f"{table['design']['max']}s against review q3 {table['review']['q3']}s "
        f"/ max {table['review']['max']}s. Reword the comment — the split was "
        "rejected on exactly this evidence."
    )


def test_context_engine_rationale_quotes_a_measured_tail_pair() -> None:
    """The comment cites the measurement rather than gesturing at it (AC-2).

    Some one sentence must quote **both** engines' values for the same tail
    statistic. The same-sentence rule is what stops the historical 600 → 720
    clause from satisfying this by accident: it already contains ``561`` (design's
    max) but says nothing about review's ``587``, so a half-pair drawn from two
    unrelated clauses does not count as a citation.
    """
    table = _latency_table(_PROPOSAL.read_text(encoding="utf-8"))
    comment = _comment(_CONTEXT.read_text(encoding="utf-8"), "engine_timeout_seconds")

    cited = [
        statistic
        for statistic in _TAIL_STATISTICS
        if any(
            _quotes_number(sentence, table["design"][statistic])
            and _quotes_number(sentence, table["review"][statistic])
            for sentence in _sentences(comment)
        )
    ]

    assert cited, (
        "CONTEXT.md's engine_timeout_seconds comment must quote both engines' "
        "measured values for at least one tail statistic in a single sentence "
        "— e.g. "
        + ", ".join(
            f"{s} {table['design'][s]}s vs {table['review'][s]}s"
            for s in _TAIL_STATISTICS
        )
        + f" — so the next reader finds the evidence in place rather than "
        f"re-deriving it from {_PROPOSAL.relative_to(_REPO_ROOT)}."
    )


def test_context_engine_rationale_cites_the_rejected_proposal() -> None:
    """The comment points at the record, and the record still says *rejected* (AC-2).

    The path is required to resolve, so a moved or deleted proposal fails here
    instead of leaving a dead reference in the file every agent reads first. The
    status is checked because the sentence presents it as the record of a
    rejection: were the split later accepted, this comment would be describing
    a decision that no longer holds.
    """
    relative = _PROPOSAL.relative_to(_REPO_ROOT).as_posix()
    comment = _comment(_CONTEXT.read_text(encoding="utf-8"), "engine_timeout_seconds")

    assert relative in comment, (
        "CONTEXT.md's engine_timeout_seconds comment must cite "
        f"`{relative}` as the record of why one ceiling covers both engines."
    )
    assert _PROPOSAL.exists(), f"{relative} is cited by CONTEXT.md but does not exist"
    status = _frontmatter_status(_PROPOSAL.read_text(encoding="utf-8"))
    assert status == "rejected", (
        f"{relative} now reads `status: {status}`, but CONTEXT.md cites it as "
        "the record of a *rejected* split. Whichever moved, the other must "
        "follow."
    )


# --- #299: the wall clock's own comment states the mode it bounds -------------
#
# ADR 0011 narrowed `wall_clock_budget_minutes` to unattended runs, but the
# comment that *defines* the knob still opened universal — "THE single source of
# truth for the longest a legitimate run may take, read by BOTH consumers" — with
# the qualifier appended several sentences later. A reader who stops at the
# defining sentence learns the rule ADR 0011 retired, and the template (the copy
# every self-hosting repo actually receives) carried no qualifier at all.
#
# The predicate is **positional**, not a containment test over the whole comment.
# A whole-comment test passes today on `CONTEXT.md` — the word is present in the
# appended tail — so it would certify the exact defect this guards against.

#: The knob ADR 0011 scoped, and the knob carrying the other half of the rule.
#: Both are asserted to be real loop knobs below, so a rename cannot leave this
#: guard pointing at a key `LoopBudget` no longer has.
_SCOPED_KEY = "wall_clock_budget_minutes"
_ATTENDED_KEY = "attended_idle_minutes"

#: The mode the wall clock bounds, since ADR 0011.
_MODE = "unattended"

#: Both places the block lives — this repo's own, and the copy a bootstrapped
#: repo receives. The template is not optional here: the ticket's Problem names
#: the inheritance, and a repo installing the template inherits the prose too.
_LOOP_BLOCK_FILES = (_CONTEXT, _TEMPLATE)


def _first_sentence(comment: str) -> str:
    """The comment's defining sentence — the one a reader reaches first."""
    sentences = _sentences(comment)
    assert sentences, (
        "the knob's inline comment must carry prose to scope; an empty comment "
        "would let every assertion below pass on nothing"
    )
    return sentences[0]


def test_the_scoped_keys_are_real_loop_knobs() -> None:
    """Floor: both names this guard reasons about are knobs `LoopBudget` carries.

    Without it a rename empties the subject of every assertion below — `_comment`
    would fail, but on a message about a missing key rather than about the scope
    rule going unenforced, and a future edit could "fix" that by dropping the
    guard rather than the rename.
    """
    assert {_SCOPED_KEY, _ATTENDED_KEY} <= set(_KEYS), (
        f"{_SCOPED_KEY!r} and {_ATTENDED_KEY!r} must both be knobs in `_KEYS` "
        f"(derived from `LoopBudget`); got {_KEYS}"
    )


def test_the_scope_predicate_can_fail() -> None:
    """Positive control: the predicate rejects an unscoped defining sentence.

    The pre-#299 `CONTEXT.md` wording, verbatim in shape — universal head clause,
    qualifier appended after. It must be judged *unscoped*, or the two guards
    below prove nothing about where the qualifier sits.
    """
    unscoped = (
        "THE single source of truth for the longest a legitimate run may take "
        "— read by BOTH consumers. Scope, since ADR 0011: this bounds "
        "unattended runs."
    )
    assert _MODE not in _first_sentence(unscoped), (
        "the positional predicate must reject a comment whose defining sentence "
        "is universal even when the qualifier appears later — otherwise it is "
        "just a containment test over the whole comment"
    )
    assert _MODE in unscoped, (
        "and the same text must contain the word overall, which is precisely "
        "why a whole-comment containment test would certify the defect"
    )


@pytest.mark.parametrize("path", _LOOP_BLOCK_FILES, ids=lambda p: p.name)
def test_the_wall_clock_comment_scopes_itself_in_its_defining_sentence(
    path: Path,
) -> None:
    """The sentence that defines the wall clock says which runs it bounds (AC-2)."""
    comment = _comment(path.read_text(encoding="utf-8"), _SCOPED_KEY)
    defining = _first_sentence(comment)

    assert _MODE in defining, (
        f"{path.relative_to(_REPO_ROOT)}'s `{_SCOPED_KEY}` comment must scope "
        f"itself to {_MODE} runs in its *first* sentence, not in a qualifier "
        "appended after a universal head clause (ADR 0011). A reader who stops "
        f"at the definition otherwise learns the rule ADR 0011 retired. Got: "
        f"{defining!r}"
    )


@pytest.mark.parametrize("path", _LOOP_BLOCK_FILES, ids=lambda p: p.name)
def test_the_wall_clock_comment_names_where_the_attended_rule_lives(
    path: Path,
) -> None:
    """Scoping a rule to one mode obliges saying where the other one lives (AC-2).

    Otherwise the correction trades a wrong rule for an incomplete one: the
    reader learns the clock does not bound their attended run and is told
    nothing about what does.
    """
    comment = _comment(path.read_text(encoding="utf-8"), _SCOPED_KEY)

    assert _ATTENDED_KEY in comment, (
        f"{path.relative_to(_REPO_ROOT)}'s `{_SCOPED_KEY}` comment must name "
        f"`{_ATTENDED_KEY}` — the knob that bounds the mode it just excluded — "
        "so the scope correction points somewhere instead of leaving a gap."
    )
