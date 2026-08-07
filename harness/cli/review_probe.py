"""The reviewer's mutation budget, decided purely — no I/O, no ledger (#363).

The review engine can read a diff and reason about it. It cannot run anything, so
it can never move a finding from plausible to proven, and — the sharper gap, and
the one this repo actually pays for — nobody proposes the mutations the *builder*
did not think of. A mutation table certifies only what its author thought to
mutate, and the only party positioned to be an independent counterparty on it is
the one party that could not execute.

So ``review`` gains a bounded probe stage: the engine proposes up to
``loop.probe_max_entries`` mutation entries in #360's table format, the verb runs
them through ``scripts/mutate.py`` against a throwaway worktree at the reviewed
SHA, and a survivor comes back for a second engine pass where it may become a
finding. This module is every rule in that stage that can be decided without
spawning anything, split out on the :mod:`harness.cli.review_protocol` precedent
so the judgment is provable on its own and ``review.py`` grows only call sites.

Three properties are load-bearing, and each is a rule here rather than a habit:

**A probe must predict its outcome.** ``kills`` is #360 AC-1's contract and is
required. A reviewer that runs a suite, reads green and concludes "verified" has
produced exactly the shape this repo keeps paying for; an entry judged against a
declared prediction produces evidence. That is why an entry that kills nothing
and an entry that breaks collection are both reported as failures of *the entry*
— :func:`survivors` excludes them and :func:`build_probe_feedback` does not name
them — rather than as survivors the reviewer may cite.

**The proposal is untrusted.** It originates in an engine reading the diff and
the ticket, both injectable. :func:`screen_proposals` is the boundary, and
:func:`render_probe_table` is its sharper half: a table is a structured document,
so every proposed value is written as a *quoted* TOML string via ``json.dumps``
rather than into the ``'''literal'''`` delimiters a human tick writes by hand.
That makes a forged second entry unrepresentable rather than filtered.

**Combination is computed, not trusted.** :func:`combine_verdict` is monotone in
severity, so a second pass that was asked about the probes can never overturn the
first pass's rejection of the diff.

Everything here is pure: a dataclass, a model, or a function of its arguments and
one read-only look at the probe tree's own files. The subprocess mechanics live
in :mod:`harness.probe_tree` and in the verb.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "PROBE_SELECT",
    "ProbeOutcome",
    "ProbeProposal",
    "Screened",
    "build_probe_feedback",
    "build_probe_request",
    "combine_issues",
    "combine_verdict",
    "demonstrated_ids",
    "read_probe_report",
    "render_probe_table",
    "screen_proposals",
    "survivors",
]

#: The pytest selection every probe table runs under — **verb-owned, never
#: proposable**. A reviewer that could choose the selection could spend the whole
#: budget N+1 times over the full suite, which is the cost this stage is bounded
#: against; and a selection is not a mutation, so nothing about the counterparty
#: role needs it. It matches ``mutate``'s own default, so a predicted node id
#: outside it meets that harness's ``prediction`` refusal rather than silently
#: reading as a survivor.
PROBE_SELECT: tuple[str, ...] = ("-m", "unit or guard")

#: Written into the probe tree and declared as the table's containment sentinel.
#: Naming *this run's* tree, rather than merely "a tree the table was written
#: for", is what makes running a reviewer's table against the run worktree or the
#: primary checkout structurally impossible instead of merely unintended.
SENTINEL_FILENAME = ".harness-probe"

#: Severity order for :func:`combine_verdict`. ``defer`` sits between the two
#: because it means *shippable, with an out-of-scope finding*: strictly more than
#: a clean pass, strictly less than a rejection.
_SEVERITY: dict[str, int] = {"pass": 0, "defer": 1, "fail": 2}

#: The outcomes a survivor may have. ``killed`` is the guard working;
#: ``mispredicted`` / ``inert`` / ``errored`` are failures of the entry.
_SURVIVED = "survived"


@dataclass(frozen=True)
class ProbeProposal:
    """One screened entry, ready to render into #360's table format."""

    id: str
    file: str
    old: str
    new: str
    kills: tuple[str, ...]
    note: str = ""
    observe: tuple[str, ...] = ()


@dataclass(frozen=True)
class Screened:
    """What the screen made of the engine's ``probes`` array.

    ``proposed`` counts what the engine emitted *before* screening, so
    ``proposed - len(kept)`` and the named ``dropped`` reasons answer the
    question this whole change exists to make measurable: are the reviewer's
    proposals mostly real, or mostly no-ops and duplicates of the builder's own
    table? (The proposal names that as what would invalidate its recommendation.)
    """

    proposed: int
    kept: tuple[ProbeProposal, ...]
    dropped: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ProbeOutcome:
    """One entry's result, reduced to what may cross into the ledger.

    Counts and ids only. The full report carries node-id sets and digests; a
    ``review`` event is read into a ticket, so what travels is the classification
    and its shape, never the sets themselves and never source text.

    ``live`` is #365's liveness fork: an observable that *moved* between the
    pristine and mutated trees. ``citable`` is the narrower question the second
    pass is allowed to act on — a survivor, live or unproven; never a failure of
    the entry.
    """

    id: str
    outcome: str
    live: bool
    predicted: int
    observed: int
    duration_ms: int

    @property
    def citable(self) -> bool:
        return self.outcome == _SURVIVED

    def as_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "outcome": self.outcome,
            "live": self.live,
            "predicted": self.predicted,
            "observed": self.observed,
            "duration_ms": self.duration_ms,
        }


# ---------------------------------------------------------------------------
# The screen.
# ---------------------------------------------------------------------------


def _as_proposal(raw: Any) -> ProbeProposal | None:
    """Shape-check one element of the ``probes`` array; ``None`` if it is not one.

    Deliberately total: a malformed value is *dropped and counted*, never raised.
    ``probes`` is an addition to the SUBMIT contract, not a new way to fail it, so
    a reviewer that garbles it loses its budget and keeps its verdict.
    """
    if not isinstance(raw, dict):
        return None
    fields = {}
    for key in ("id", "file", "old", "new"):
        value = raw.get(key)
        if not isinstance(value, str):
            return None
        fields[key] = value
    kills = raw.get("kills")
    if not isinstance(kills, list) or not all(isinstance(k, str) for k in kills):
        return None
    note = raw.get("note", "")
    observe = raw.get("observe", [])
    if not isinstance(note, str):
        note = ""
    if not isinstance(observe, list) or not all(isinstance(o, str) for o in observe):
        observe = []
    return ProbeProposal(
        id=fields["id"],
        file=fields["file"],
        old=fields["old"],
        new=fields["new"],
        kills=tuple(kills),
        note=note,
        observe=tuple(observe),
    )


def _reject(proposal: ProbeProposal, tree: Path, seen: set[str]) -> str | None:
    """The semantic rejection classes, in the order that reads cheapest first.

    Every rule here is one ``mutate`` also applies — **to the whole table**. That
    is the point of duplicating them: without the pre-screen, one bad entry from
    an untrusted proposer voids the entire budget, so the cheap defect would cost
    the expensive thing. ``mutate`` remains the authority; this only stops it
    being asked a question it must answer by refusing everything.
    """
    if not proposal.id.strip():
        return "missing_id"
    if proposal.id in seen:
        return "duplicate_id"
    if not proposal.kills:
        return "no_kills"
    if proposal.new == proposal.old:
        return "identical"
    root = tree.resolve()
    candidate = (root / proposal.file).resolve()
    if candidate != root and root not in candidate.parents:
        return "file_outside_tree"
    if not candidate.is_file():
        return "file_missing"
    try:
        text = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "file_missing"
    occurrences = text.count(proposal.old)
    if occurrences == 0:
        return "old_absent"
    if occurrences > 1:
        return "old_ambiguous"
    return None


def screen_proposals(raw: Any, *, tree: Path, cap: int) -> Screened:
    """Screen the engine's ``probes`` array against the probe tree and the cap.

    ``cap`` is ``loop.probe_max_entries``; ``0`` keeps nothing, which is the
    stage's disable switch — one knob rather than a knob plus a flag that can
    disagree with it (``untracked_file_limit``'s convention).

    Truncation is **reported**, never silent: a bound that drops work without
    saying so reads as "everything was covered" when it was not.
    """
    if not isinstance(raw, list):
        return Screened(proposed=0, kept=(), dropped=())

    kept: list[ProbeProposal] = []
    dropped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, element in enumerate(raw):
        proposal = _as_proposal(element)
        if proposal is None:
            identifier = element.get("id") if isinstance(element, dict) else None
            dropped.append((str(identifier or f"<entry {index}>"), "malformed"))
            continue
        reason = _reject(proposal, tree, seen)
        if reason is not None:
            dropped.append((proposal.id or f"<entry {index}>", reason))
            continue
        seen.add(proposal.id)
        if len(kept) >= cap:
            dropped.append((proposal.id, "over_cap"))
            continue
        kept.append(proposal)
    return Screened(proposed=len(raw), kept=tuple(kept), dropped=tuple(dropped))


# ---------------------------------------------------------------------------
# The table renderer.
# ---------------------------------------------------------------------------


def _toml_string(value: str) -> str:
    """One untrusted string as a TOML **basic** string.

    ``json.dumps`` emits exactly the escape set TOML basic strings accept
    (``\\"``, ``\\\\``, ``\\b``, ``\\f``, ``\\n``, ``\\r``, ``\\t``, ``\\uXXXX``)
    and escapes non-ASCII to ``\\uXXXX`` by default, so every ``str`` has a
    representation and none of them can terminate the string early.

    The alternative — the ``'''literal'''`` delimiters a human tick writes by
    hand — is what makes a proposal containing that delimiter able to close the
    string and open a ``[[mutation]]`` of its own, escaping the cap, the screen
    and the verb-owned ``select`` in one step. Making the injection
    unrepresentable is a boundary; filtering the delimiter would be a blocklist.
    """
    return json.dumps(value)


def _toml_array(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_toml_string(v) for v in values) + "]"


def render_probe_table(
    proposals: tuple[ProbeProposal, ...], *, sentinel_file: str, sentinel_text: str
) -> str:
    """Render screened proposals as a ``scripts/mutate.py`` table.

    ``select`` is written from :data:`PROBE_SELECT`, never from the proposal.
    ``sentinel_file`` / ``sentinel_text`` name this run's probe tree, so
    ``mutate``'s containment refusal certifies the tree's identity rather than
    merely its shape.
    """
    lines = [
        "# Generated by `harness review` (#363) from the review engine's proposal.",
        "# Every value below is untrusted input, quoted rather than delimited.",
        f"select = {_toml_array(PROBE_SELECT)}",
        f"sentinel_file = {_toml_string(sentinel_file)}",
        f"sentinel_text = {_toml_string(sentinel_text)}",
    ]
    for proposal in proposals:
        lines += [
            "",
            "[[mutation]]",
            f"id = {_toml_string(proposal.id)}",
            f"file = {_toml_string(proposal.file)}",
            f"old = {_toml_string(proposal.old)}",
            f"new = {_toml_string(proposal.new)}",
            f"kills = {_toml_array(proposal.kills)}",
        ]
        if proposal.note:
            lines.append(f"note = {_toml_string(proposal.note)}")
        if proposal.observe:
            lines.append(f"observe = {_toml_array(proposal.observe)}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Reading the report.
# ---------------------------------------------------------------------------


def read_probe_report(payload: Any) -> tuple[ProbeOutcome, ...]:
    """Classify ``scripts/mutate.py --json``'s report; ``()`` when unreadable.

    Total by construction. Every way this stage can fail to produce a report
    degrades — the review keeps the first pass's verdict — on ADR 0007 D4's
    precedent that an instrument's failure must never wedge the thing it
    observes.

    The liveness fork is read from the two digests rather than re-derived: a
    survivor whose observable moved is ``live``; one with no observable digests
    identically to nothing on both sides and stays a lead.
    """
    if not isinstance(payload, dict):
        return ()
    rows = payload.get("results")
    if not isinstance(rows, list):
        return ()
    outcomes: list[ProbeOutcome] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifier = row.get("id")
        outcome = row.get("outcome")
        if not isinstance(identifier, str) or not isinstance(outcome, str):
            continue
        pristine = row.get("pristine_digest") or ""
        mutated = row.get("mutated_digest") or ""
        predicted = row.get("predicted")
        observed = row.get("observed")
        duration = row.get("duration_s")
        outcomes.append(
            ProbeOutcome(
                id=identifier,
                outcome=outcome,
                live=bool(pristine) and bool(mutated) and pristine != mutated,
                predicted=len(predicted) if isinstance(predicted, list) else 0,
                observed=len(observed) if isinstance(observed, list) else 0,
                duration_ms=int(duration * 1000) if isinstance(duration, int | float) else 0,
            )
        )
    return tuple(outcomes)


def survivors(outcomes: tuple[ProbeOutcome, ...]) -> tuple[ProbeOutcome, ...]:
    """The entries the second pass may act on — survivors only.

    A ``mispredicted``, ``inert`` or ``errored`` entry is a failure of the entry
    (#360 AC-1, #365's fork). Letting one through here is precisely how the
    vacuity problem relocates into review: the reviewer would cite as a hole a
    mutation nobody showed was live.
    """
    return tuple(o for o in outcomes if o.citable)


def demonstrated_ids(outcomes: tuple[ProbeOutcome, ...]) -> tuple[str, ...]:
    """Survivors whose observable moved — the ledger's *demonstrated* set."""
    return tuple(o.id for o in outcomes if o.citable and o.live)


# ---------------------------------------------------------------------------
# The prompts.
# ---------------------------------------------------------------------------

_PROBE_REQUEST_TEMPLATE = """
You may also propose up to {cap} **mutation entries** — deliberate edits to the
code under review that a good test suite must catch. They will be applied, one at
a time, to a throwaway worktree at the reviewed commit and the suite will be run
against each; the reviewed worktree is never touched. This is the one thing you
can cause to be executed, and it exists because a mutation table certifies only
what its author thought to mutate, and the author is the person you are reviewing.

Emit them as a `probes` array on the SUBMIT line's JSON object. Each entry:

  - id: a short unique handle, e.g. "cap-constant"
  - file: a path relative to the repository root
  - old: an exact source substring occurring EXACTLY ONCE in that file
  - new: what to replace it with (must differ from old)
  - kills: a non-empty array of the pytest node ids this edit MUST make fail
  - note: one sentence on what the edit means (optional)
  - observe: argv appended to `python`, printing something the edit should change
    (optional but strongly advised), e.g. ["-c", "import m; print(m.LIMIT)"]

Two rules decide whether an entry is worth anything:

  1. **Predict.** An entry whose observed failures are not exactly `kills` is
     reported as a failure of YOUR entry — an empty set (it killed nothing) and a
     superset (it broke collection) both fail the same comparison. Running
     something and reading the result is not evidence; predicting an outcome and
     being judged against it is.
  2. **Prove the edit was live.** Without `observe`, a mutation that survives is
     indistinguishable from one that changed nothing — four of one past run's
     twenty entries evaluated to the original value and reported SURVIVED. State
     what your edit EVALUATES TO, not what you would name it.

The suite runs under `-m "unit or guard"`, so `kills` must name node ids inside
that selection. Propose entries targeting code this diff ADDED or CHANGED, and
prefer the ones the author's own tests look least likely to catch. Omit the array
entirely if you have nothing worth spending it on.
"""

_PROBE_FEEDBACK_HEADER = """
The mutations you proposed have been run against a throwaway worktree at the
reviewed commit. Below is what happened. Revise your verdict and findings in the
light of it, then emit a single new SUBMIT line.

"""

_PROBE_FEEDBACK_RULES = """
Rules for using this, in order of how easy each is to get wrong:

  - A **demonstrated** survivor is a proven gap: the edit was shown to change
    behaviour and the suite stayed green. Raise it as a finding.
  - An **unproven** survivor is a lead, not proof. The suite stayed green, but
    nothing showed the edit changed anything, so it may simply have evaluated to
    the original value. Raise it only if you can argue from the code that the
    edit was live, and say so in the finding.
  - Entries not listed here either did their job (the suite caught them) or were
    defects in the entry itself. Neither is a finding; do not cite them.

Prefix every finding derived from a probe with `[probe:<id>]`. Findings you
already made stand whether or not the probes bear on them — this pass adds
evidence, it does not withdraw anything.
"""


def build_probe_request(cap: int) -> str:
    """The block appended to the first-pass prompt when probing is enabled."""
    return _PROBE_REQUEST_TEMPLATE.format(cap=cap)


def build_probe_feedback(
    outcomes: tuple[ProbeOutcome, ...],
    *,
    first_verdict: str = "",
    first_issues: tuple[str, ...] = (),
) -> str:
    """The second-pass block: the rules, plus the citable entries only.

    Entries that were failures of the entry are deliberately **absent** rather
    than listed as rejected. A reviewer handed a table of raw outcomes reads
    every non-``killed`` row as a hole; naming a defect at all invites it to be
    raised with a caveat, and a finding with a caveat is still a finding.

    ``first_verdict`` / ``first_issues`` restate what this same engine already
    concluded. The second pass runs in a **fresh** subprocess with no memory of
    the first, so without them it would be re-reviewing the diff from nothing
    while being handed probe outcomes it never proposed — and a finding it made
    an hour of tokens ago would read as a new one. Restating them is also what
    makes :func:`combine_issues` a deduplication rather than a concatenation.
    """
    lines = [_PROBE_FEEDBACK_HEADER.rstrip("\n")]
    if first_verdict:
        lines.append(f"Your first-pass verdict on this diff was: {first_verdict}")
        if first_issues:
            lines.append("Your first-pass findings were:")
            lines += [f"  - {issue}" for issue in first_issues]
        else:
            lines.append("You raised no findings.")
        lines.append("")
    if outcomes:
        lines.append("Probe outcomes:")
    for outcome in survivors(outcomes):
        label = "demonstrated" if outcome.live else "unproven"
        lines.append(
            f"  - [probe:{outcome.id}] SURVIVED ({label}) — the suite stayed green "
            f"against this edit; {outcome.predicted} test(s) were predicted to fail "
            f"and {outcome.observed} did."
        )
    lines.append(_PROBE_FEEDBACK_RULES)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Combination.
# ---------------------------------------------------------------------------


def combine_verdict(first: str, second: str | None) -> str:
    """The more severe of the two verdicts (``pass`` < ``defer`` < ``fail``).

    Monotone deliberately. The second pass is asked about the probe outcomes, not
    re-asked about the diff, so it must not be able to overturn the first pass's
    rejection — an engine that has just been told its own proposals mostly failed
    is exactly the one most likely to soften. A second pass that produced nothing
    (``None``) leaves the first pass's verdict standing.
    """
    if second is None or second not in _SEVERITY:
        return first
    return first if _SEVERITY.get(first, 0) >= _SEVERITY[second] else second


def combine_issues(first: list[str], second: list[str] | None) -> list[str]:
    """The first pass's findings, plus the second's that are not restatements.

    Order-stable and deduplicating on the exact string: a second pass that
    repeats a finding verbatim must not double it, and one that drops a finding
    must not lose it.
    """
    combined = list(first)
    for issue in second or []:
        if issue not in combined:
            combined.append(issue)
    return combined
