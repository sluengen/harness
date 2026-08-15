"""The assurance policy — which lifecycle stages a run is required to pay for.

#352, from ``specs/proposals/assurance-led-lifecycle.md`` (item 1). Before this,
``design`` ran on every run and ``review`` accepted a *failed* design attempt as
satisfying its gate (ADR 0007 D1/D4): the stage proved invocation rather than a
usable outcome, so small changes paid for an engine call they did not need while
complex ones could ship after the stage produced nothing.

An issue now carries its intent as an ``assurance:<level>`` label, ``start``
resolves that intent **once** and snapshots it on the run, and the later verbs
read the snapshot. This module is the single home for all four pieces — the
vocabulary, the resolution, the ledger coercion, and the required-stages
mapping — so ``start``, ``design`` and ``review`` cannot grow three opinions
about what a level means (the ticket's watchlist trigger: ``review.py`` keeps
only orchestration and refusal *mapping*, never the decision).

It is deliberately **pure**: no ledger, no tracker, no filesystem, no clock. The
one ledger read the policy needs lives with the other shared run-row rules in
``harness/cli/_runs.py`` (``read_run_assurance``) and calls
:func:`coerce_assurance` here, so this module stays testable as a table of
inputs and answers.

**Everything unresolved fails safe, in one direction.** A missing, conflicting,
unrecognized, or corrupted value resolves to :data:`DEFAULT_ASSURANCE` —
``simple`` — which requires an LLM review. Labels are third-party input anyone
with issue-write access can set, so the worst a hostile or mistaken one can buy
is ``complex`` → ``simple``, i.e. skipping the *design* stage. It cannot skip the
review engine, the verify-gate evidence check, or ``close``'s SHA-bound gate.

**``trivial`` is honoured where the repo can certify one** (#353). It resolves
like any other stated level; whether the *repo* can act on it is a separate
question — it needs a usable ``assurance.trivial_paths`` allowlist — and the
answer lives in :func:`apply_fast_path_availability`, a second pure function
taking a boolean. That split is what keeps this module free of the filesystem
while still letting ``fast_path_unavailable`` mean what it says: the operator
stated an intent the repo could not honour, rather than an intent nothing could
ever honour.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, get_args

#: The closed assurance vocabulary. ``trivial`` skips design *and* the LLM
#: review, ``simple`` requires the review, ``complex`` additionally requires a
#: design that succeeded.
Assurance = Literal["trivial", "simple", "complex"]

#: The vocabulary as data, derived from the type so the two cannot drift.
ASSURANCE_LEVELS: tuple[Assurance, ...] = get_args(Assurance)

#: Where every unresolved case lands: the level that still requires a review.
DEFAULT_ASSURANCE: Assurance = "simple"

#: The label namespace on the issue, e.g. ``assurance:complex``.
ASSURANCE_LABEL_PREFIX = "assurance:"

#: Why a run carries the assurance it does. Closed, and stable — these tags
#: reach ``StartOutput`` and the ledger, so a consumer branches on them.
#:
#: ``label``: exactly one recognized level was stated. ``no_label``: none was
#: (including every tracker-less run, which has no labels to read).
#: ``conflicting_labels``: two or more distinct recognized levels.
#: ``unknown_label``: some ``assurance:*`` label carried a value outside the
#: vocabulary. ``fast_path_unavailable``: ``trivial`` was stated in a repo that
#: declares no usable trivial allowlist, so there is nothing it could certify.
#: ``unrecorded``: read off a run row written before the migration.
#: ``diff_ineligible``: the run stated ``trivial``, the repo could certify one,
#: and the run's actual diff turned out not to be — the first member produced by
#: a verb other than ``start`` (``certify``, #353), and the only one that ever
#: replaces a value already on the row.
#:
#: ``unrecorded`` and ``diff_ineligible`` are the two members
#: :func:`resolve_assurance` never produces.
ResolutionReason = Literal[
    "label",
    "no_label",
    "conflicting_labels",
    "unknown_label",
    "fast_path_unavailable",
    "unrecorded",
    "diff_ineligible",
]

#: What ``certify`` records when it upgrades a run whose diff is not certifiable.
DIFF_INELIGIBLE_REASON: ResolutionReason = "diff_ineligible"

#: What a run row that predates the assurance columns reports as its reason.
UNRECORDED_REASON: ResolutionReason = "unrecorded"

#: ``review``'s refusal when a run that requires a design recorded none. Defined
#: here rather than in ``review_protocol`` (which re-exports it for its existing
#: importers) because whether the stage is required is this module's decision.
NO_DESIGN_REASON = "no_design"

#: ``review``'s refusal when a run that requires a design recorded an attempt
#: that did not succeed. Distinct from :data:`NO_DESIGN_REASON` on purpose: "the
#: stage was skipped" and "the stage ran and produced nothing usable" have
#: different remedies, and distinct from the ``design_failed`` *context* reason,
#: which names a review that proceeded — one string meaning both "refused" and
#: "continued" is unreadable in the ledger.
DESIGN_NOT_USABLE_REASON = "design_not_usable"

#: The ``design`` event status that counts as a usable design artifact.
_DESIGN_OK = "ok"


@dataclass(frozen=True)
class RequiredStages:
    """Which lifecycle stages a level obliges the run to pay for."""

    #: A design that *succeeded* is required before ``review`` will run.
    design: bool
    #: An engine review is required before ``close`` will open its gate.
    llm_review: bool


#: The decided mapping. ``llm_review`` gained its consumer in #353: ``certify``
#: guards on ``required_stages(assurance).llm_review`` rather than comparing the
#: level to a string, so the table — not a scattered set of equality checks — is
#: what decides which runs may take the fast path.
#: ``test_assurance_policy.py`` pins all three rows.
_REQUIRED_STAGES: dict[Assurance, RequiredStages] = {
    "trivial": RequiredStages(design=False, llm_review=False),
    "simple": RequiredStages(design=False, llm_review=True),
    "complex": RequiredStages(design=True, llm_review=True),
}


@dataclass(frozen=True)
class AssuranceResolution:
    """The level a run snapshots, and why it carries that level."""

    effective: Assurance
    reason: ResolutionReason


@dataclass(frozen=True)
class DesignPrecondition:
    """Whether a run's design stage lets ``review`` proceed.

    ``refusal_reason`` is ``None`` exactly when :attr:`satisfied` is true, so a
    caller may branch on either — ``review`` maps the reason onto its refusal
    contract, while ``review_inherit`` only needs the boolean.
    """

    refusal_reason: str | None = None
    refusal_message: str | None = None

    @property
    def satisfied(self) -> bool:
        return self.refusal_reason is None


def required_stages(assurance: Assurance) -> RequiredStages:
    """The stages ``assurance`` requires. Total over the vocabulary."""
    return _REQUIRED_STAGES[assurance]


def resolve_assurance(labels: Iterable[str]) -> AssuranceResolution:
    """Resolve an issue's labels to the level a run snapshots, and why.

    Total: every input answers, nothing raises. Labels are normalized (stripped
    and lowercased) before matching, so ``Assurance:Complex`` states the same
    intent as ``assurance:complex``; labels outside the namespace are ignored.

    The order of the checks is load-bearing. An unrecognized ``assurance:*``
    value is judged **before** a conflict between recognized ones, so
    ``assurance:complex`` + ``assurance:banana`` fails safe rather than honouring
    the half the harness happens to understand — a statement carrying a value we
    cannot interpret is not a statement to act on. Distinct recognized values
    then conflict; a level repeated is one intent stated once.

    Since #353 it *may* return ``trivial``, and whether the repo can act on that
    is :func:`apply_fast_path_availability`'s question, not this one.
    """
    stated: set[str] = set()
    unknown = False
    for raw in labels:
        normalized = raw.strip().lower()
        if not normalized.startswith(ASSURANCE_LABEL_PREFIX):
            continue
        value = normalized[len(ASSURANCE_LABEL_PREFIX) :]
        if value in ASSURANCE_LEVELS:
            stated.add(value)
        else:
            unknown = True

    if unknown:
        return AssuranceResolution(DEFAULT_ASSURANCE, "unknown_label")
    if not stated:
        return AssuranceResolution(DEFAULT_ASSURANCE, "no_label")
    if len(stated) > 1:
        return AssuranceResolution(DEFAULT_ASSURANCE, "conflicting_labels")

    (selected,) = stated
    # ``selected`` came out of ASSURANCE_LEVELS, so it is an Assurance.
    return AssuranceResolution(selected, "label")  # type: ignore[arg-type]


def apply_fast_path_availability(
    resolution: AssuranceResolution, *, fast_path_available: bool
) -> AssuranceResolution:
    """Downgrade a ``trivial`` resolution where the repo cannot certify one (#353).

    A repo that declares no valid ``assurance.trivial_paths`` allowlist can never
    certify a diff, so opening a ``trivial`` run there would buy the operator
    nothing except an extra verb call and a tracker write on every single run,
    forever. The intent was stated and not honoured, which is exactly what
    ``fast_path_unavailable`` has always meant — so the tag keeps its meaning and
    regains a live producer, and ``start``'s existing stderr warning
    (``_UNHONOURED_INTENT_REASONS``) fires unchanged and now says something
    actionable.

    Pure, and total: it never reads the repo. The caller supplies the boolean,
    the same way ``review`` supplies ``design_status`` rather than this module
    querying the ledger for it — which is what keeps this module's stated purity
    contract intact while the decision it feeds is about the filesystem.

    Touches nothing but a ``trivial`` resolution: a ``simple`` or ``complex`` run
    is unaffected by whether a fast path exists.
    """
    if resolution.effective != "trivial" or fast_path_available:
        return resolution
    return AssuranceResolution(DEFAULT_ASSURANCE, "fast_path_unavailable")


def coerce_assurance(stored: str | None) -> Assurance:
    """Read a level off a ledger column. Total, and falls back to ``simple``.

    ``None`` is a run row written before the migration; an unrecognized string is
    a corrupted or hand-edited one. Both read as :data:`DEFAULT_ASSURANCE`, so a
    damaged snapshot can only make a run *more* verified, never less — the same
    fail-toward-the-bound posture ``resolve_attended`` takes.

    ``trivial`` round-trips rather than being rewritten here, because coercion
    describes what the column *says* — and that is why #353 could start writing
    the value without touching this function. Since #353 a row can hold it: in a
    repo that declares a usable trivial allowlist, ``start`` snapshots the level
    the issue stated. Keeping the availability decision at the single ingress
    rather than smearing it across every reader is what keeps it auditable.
    """
    if stored is None:
        return DEFAULT_ASSURANCE
    normalized = stored.strip().lower()
    if normalized in ASSURANCE_LEVELS:
        return normalized
    return DEFAULT_ASSURANCE


def design_precondition(assurance: Assurance, design_status: str | None) -> DesignPrecondition:
    """Whether the run's design stage lets ``review`` proceed.

    ``design_status`` is the ``status`` of the run's *latest* ``design`` event —
    ``None`` when it recorded none. The latest event is authoritative, as it
    already is for design *context*, so a failed attempt followed by a successful
    one satisfies this.

    Where design is not a required stage the answer is always "proceed": a
    ``simple`` run with no design event is the normal shape after #352, not a
    malformed one. Where it is required, absence and failure refuse with distinct
    tags — both before any engine runs, and neither recording a verdict.
    """
    if not required_stages(assurance).design:
        return DesignPrecondition()
    if design_status is None:
        return DesignPrecondition(
            refusal_reason=NO_DESIGN_REASON,
            refusal_message=(
                "this run is assurance:complex and has no recorded design "
                "attempt. Run `harness design --run-id <id>` and review again. "
                "No engine was invoked and no verdict was recorded — silence is "
                "not a pass."
            ),
        )
    if design_status != _DESIGN_OK:
        return DesignPrecondition(
            refusal_reason=DESIGN_NOT_USABLE_REASON,
            refusal_message=(
                "this run is assurance:complex and its design attempt did not "
                f"succeed (status={design_status!r}), so there is no design to "
                "review against. Re-run `harness design --run-id <id>`; if the "
                "engine keeps failing, the run's assurance is the thing to "
                "revisit, not this gate. No engine was invoked and no verdict "
                "was recorded."
            ),
        )
    return DesignPrecondition()
