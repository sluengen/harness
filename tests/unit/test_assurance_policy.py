"""#352 — the assurance policy: one vocabulary, one required-stages mapping.

``harness/assurance.py`` is the single home the parent proposal
(``specs/proposals/assurance-led-lifecycle.md``) requires: the closed assurance
vocabulary, the label resolution ``start`` runs once, the ledger coercion every
later verb reads through, and the required-stages table ``design`` and ``review``
both consume. AC-7 is that there is exactly one such mapping — these tests hold
the policy to its contract *as a pure function*, with no ledger, no CLI and no
tracker, so a failure here names the policy rather than a verb that misused it.

Three properties carry the safety argument and are each measured, not implied:

* **Resolution is total** — every label list resolves to a level and a reason,
  and unrecognized, conflicting, and absent input all fail *safe* to ``simple``
  (AC-1). Nothing raises, so a hostile or mistyped label cannot wedge ``start``.
* **``trivial`` cannot escape** (AC-6). It is a recognized level that this
  increment rewrites to ``simple`` at the boundary, because the deterministic
  certification path that would make it safe is item 2 of the proposal and is
  not built. The property is asserted over a *derived* corpus of label lists
  rather than the one obvious case, so the rewrite cannot be removed for some
  input shape while a single hand-picked case keeps passing.
* **Coercion is total in the same direction** — a ``NULL``, unknown, or
  hand-edited ledger value reads as ``simple``, so a corrupted snapshot can only
  make a run *more* verified, never less.

The label corpus is derived from :data:`ASSURANCE_LEVELS` (itself derived from
the ``Assurance`` ``Literal``), so adding a level to the vocabulary extends every
property below instead of silently leaving it unasserted. :func:`test_the_label_corpus_reaches_the_levels_it_claims_to`
is the non-vacuity floor on that derivation — without it a narrowed corpus would
leave the parametrized properties green while measuring nothing.
"""

from __future__ import annotations

import itertools

import pytest

from harness.assurance import (
    ASSURANCE_LEVELS,
    ASSURANCE_LABEL_PREFIX,
    DEFAULT_ASSURANCE,
    DESIGN_NOT_USABLE_REASON,
    NO_DESIGN_REASON,
    Assurance,
    coerce_assurance,
    design_precondition,
    required_stages,
    resolve_assurance,
)


def _label(value: str) -> str:
    return f"{ASSURANCE_LABEL_PREFIX}{value}"


#: Every label list this suite's properties run over, derived from the
#: vocabulary: each level alone, every pair, plus the shapes that are *not*
#: recognized values (an unknown suffix, an empty suffix, an unrelated label)
#: and the two spellings resolution must normalize (case, surrounding space).
_CORPUS_TOKENS: tuple[str, ...] = (
    *(_label(level) for level in ASSURANCE_LEVELS),
    _label("banana"),
    _label(""),
    "bug",
    _label("TRIVIAL").upper(),
    f"  {_label('trivial')}  ",
)

LABEL_LISTS: tuple[tuple[str, ...], ...] = tuple(
    combo for size in (0, 1, 2, 3) for combo in itertools.combinations(_CORPUS_TOKENS, size)
)


# --- Floors on the derived corpus --------------------------------------------


def test_the_label_corpus_reaches_the_levels_it_claims_to() -> None:
    """Non-vacuity floor: the derived corpus really carries each level's label.

    Every property below is parametrized over :data:`LABEL_LISTS`. A derivation
    that narrowed — a renamed prefix, a vocabulary read as empty — would leave
    those parametrized cases green over a corpus that no longer contains the
    input they exist to judge. Membership, never cardinality: a hardcoded count
    is the drift this floor exists to remove.
    """
    for level in ASSURANCE_LEVELS:
        assert (_label(level),) in LABEL_LISTS, f"corpus lost the lone {level!r} label"
    assert () in LABEL_LISTS, "corpus lost the unlabelled case"
    assert (_label("trivial"), _label("complex")) in LABEL_LISTS


def test_the_vocabulary_is_the_three_decided_levels() -> None:
    """The closed vocabulary the proposal decided, derived from the ``Literal``.

    ``ASSURANCE_LEVELS`` is ``get_args(Assurance)``, so this one assertion pins
    the type and the tuple together — they cannot drift into disagreement.
    """
    assert ASSURANCE_LEVELS == ("trivial", "simple", "complex")
    assert DEFAULT_ASSURANCE == "simple"
    assert DEFAULT_ASSURANCE in ASSURANCE_LEVELS


# --- Resolution: total, and safe in one direction -----------------------------


def test_no_labels_resolve_to_simple() -> None:
    """The common case, and the tracker-less one: no labels, no stated intent."""
    resolution = resolve_assurance([])
    assert resolution.effective == "simple"
    assert resolution.reason == "no_label"


@pytest.mark.parametrize("level", ["simple", "complex"], ids=["simple", "complex"])
def test_exactly_one_recognized_label_selects_that_level(level: str) -> None:
    resolution = resolve_assurance([_label(level)])
    assert resolution.effective == level
    assert resolution.reason == "label"


@pytest.mark.parametrize(
    "labels",
    [
        [_label("COMPLEX")],
        [_label("Complex")],
        [f"  {_label('complex')}  "],
        [_label("complex"), "bug", "p1"],
    ],
    ids=["upper", "mixed", "padded", "among-unrelated"],
)
def test_resolution_normalizes_case_and_whitespace_and_ignores_other_labels(
    labels: list[str],
) -> None:
    """Case, padding, and unrelated labels must not change the answer.

    A tracker returns whatever an operator typed; the level is a closed
    vocabulary matched after normalization, so ``Assurance:Complex`` states the
    same intent as ``assurance:complex`` and neither is an ``unknown_label``.
    """
    resolution = resolve_assurance(labels)
    assert resolution.effective == "complex"
    assert resolution.reason == "label"


def test_two_distinct_recognized_labels_fail_safe() -> None:
    """Conflicting intent is not a refusal — it is a downgrade to the safe level."""
    resolution = resolve_assurance([_label("complex"), _label("simple")])
    assert resolution.effective == "simple"
    assert resolution.reason == "conflicting_labels"


def test_the_same_recognized_label_twice_is_not_a_conflict() -> None:
    """Distinct *values* conflict; a duplicated label states one intent once."""
    resolution = resolve_assurance([_label("complex"), _label("complex")])
    assert resolution.effective == "complex"
    assert resolution.reason == "label"


def test_an_unrecognized_value_fails_safe() -> None:
    resolution = resolve_assurance([_label("banana")])
    assert resolution.effective == "simple"
    assert resolution.reason == "unknown_label"


def test_an_unrecognized_value_beside_a_recognized_one_still_fails_safe() -> None:
    """Order matters: unknown is judged *before* conflict, so the recognized
    half is never honoured alongside a value the harness cannot interpret.

    Honouring it would let ``assurance:complex`` + a typo silently mean
    ``complex`` — the safe direction here is to distrust the whole statement.
    """
    resolution = resolve_assurance([_label("complex"), _label("banana")])
    assert resolution.effective == "simple"
    assert resolution.reason == "unknown_label"


def test_a_bare_prefix_with_no_value_is_unrecognized() -> None:
    resolution = resolve_assurance([_label("")])
    assert resolution.effective == "simple"
    assert resolution.reason == "unknown_label"


def test_trivial_alone_is_upgraded_to_simple() -> None:
    """AC-6: the level is *recognized*, and rewritten while the fast path is unbuilt."""
    resolution = resolve_assurance([_label("trivial")])
    assert resolution.effective == "simple"
    assert resolution.reason == "fast_path_unavailable"


@pytest.mark.parametrize("labels", LABEL_LISTS, ids=lambda labels: "+".join(labels) or "none")
def test_resolution_is_total_and_never_yields_trivial(labels: tuple[str, ...]) -> None:
    """AC-1 and AC-6 over the whole derived corpus.

    Two claims in one sweep, because they are the same safety property read
    from either end: resolution answers for *every* input (it never raises, and
    always names a level in the vocabulary and a reason in the closed set), and
    the answer is never ``trivial``. No run can bypass review before the
    certification path exists — whatever combination of labels an issue carries.
    """
    resolution = resolve_assurance(list(labels))
    assert resolution.effective in ASSURANCE_LEVELS
    assert resolution.effective != "trivial", (
        f"{labels!r} resolved to trivial — the fast path is not built, so no "
        f"run may snapshot a level that skips review"
    )
    assert resolution.reason in RESOLUTION_REASONS


#: The closed reason vocabulary. ``unrecorded`` is the only member
#: :func:`resolve_assurance` never writes — it is what a run row written before
#: the migration reads as, produced by :func:`coerce_assurance`'s caller rather
#: than by label resolution.
RESOLUTION_REASONS = frozenset(
    {
        "label",
        "no_label",
        "conflicting_labels",
        "unknown_label",
        "fast_path_unavailable",
        "unrecorded",
    }
)


@pytest.mark.parametrize("labels", LABEL_LISTS, ids=lambda labels: "+".join(labels) or "none")
def test_resolution_never_reports_unrecorded(labels: tuple[str, ...]) -> None:
    """``unrecorded`` describes a *row*, never a resolution.

    Pinned separately because the two vocabularies share a type: a resolver that
    leaked ``unrecorded`` would still satisfy the closed-set assertion above
    while making "this run predates the migration" indistinguishable from "this
    run was resolved from labels".
    """
    assert resolve_assurance(list(labels)).reason != "unrecorded"


# --- Coercion: the ledger read, total in the same direction -------------------


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (None, "simple"),
        ("", "simple"),
        ("simple", "simple"),
        ("complex", "complex"),
        ("trivial", "trivial"),
        ("garbage", "simple"),
        ("SIMPLE", "simple"),
    ],
    ids=["null", "empty", "simple", "complex", "trivial", "garbage", "upper"],
)
def test_coercion_is_total_and_falls_back_to_simple(stored: str | None, expected: str) -> None:
    """A legacy ``NULL``, an unknown value, or a hand-edited one reads as ``simple``.

    ``trivial`` round-trips deliberately: coercion describes *what the column
    says*, and the safety rewrite belongs at the one ingress
    (:func:`resolve_assurance`), not smeared across every reader. No row can
    hold ``trivial`` this increment, which is a property of the writer — pinned
    by :func:`test_resolution_is_total_and_never_yields_trivial`, not here.
    """
    assert coerce_assurance(stored) == expected


# --- The required-stages table ------------------------------------------------


#: The decided mapping (``specs/proposals/assurance-led-lifecycle.md``), stated
#: once here as the expectation. Keyed by every level, and asserted to *be*
#: keyed by every level below, so a new level cannot be added to the vocabulary
#: without deciding its stages.
EXPECTED_STAGES: dict[str, tuple[bool, bool]] = {
    # level: (design required, llm review required)
    "trivial": (False, False),
    "simple": (False, True),
    "complex": (True, True),
}


def test_the_stage_table_covers_every_level() -> None:
    """Every level in the vocabulary has decided stages — no silent default."""
    assert set(EXPECTED_STAGES) == set(ASSURANCE_LEVELS)


@pytest.mark.parametrize("level", ASSURANCE_LEVELS, ids=list(ASSURANCE_LEVELS))
def test_required_stages_matches_the_decided_mapping(level: Assurance) -> None:
    """AC-7's data: one table, all three rows, including the ``llm_review``
    column no verb consumes yet.

    It is carried because the *mapping* is the decided policy; splitting it
    across two tickets is how the two halves start disagreeing. Asserting it
    here is what makes it data rather than dead code.
    """
    design_required, review_required = EXPECTED_STAGES[level]
    stages = required_stages(level)
    assert stages.design is design_required
    assert stages.llm_review is review_required


def test_only_complex_requires_a_design() -> None:
    """The claim the ``design`` verb's skip and ``review``'s refusal both rest on."""
    requiring = [level for level in ASSURANCE_LEVELS if required_stages(level).design]
    assert requiring == ["complex"]


# --- The design precondition — the shared refusal decision --------------------


@pytest.mark.parametrize(
    "design_status",
    [None, "failed", "ok"],
    ids=["no-event", "failed-event", "ok-event"],
)
def test_a_simple_run_never_needs_a_design(design_status: str | None) -> None:
    """AC-4: design is not a required stage below ``complex``, so its absence —
    or its failure — is not a refusal."""
    precondition = design_precondition("simple", design_status)
    assert precondition.refusal_reason is None
    assert precondition.refusal_message is None
    assert precondition.satisfied is True


def test_a_complex_run_with_no_design_event_is_refused() -> None:
    precondition = design_precondition("complex", None)
    assert precondition.refusal_reason == NO_DESIGN_REASON
    assert precondition.satisfied is False
    assert precondition.refusal_message and "harness design" in precondition.refusal_message


def test_a_complex_run_with_a_failed_design_is_refused_distinctly() -> None:
    """AC-5: a *failed* attempt no longer satisfies a complex review.

    The tag differs from ``no_design`` on purpose — "the stage was skipped" and
    "the stage ran and produced nothing usable" have different remedies, and one
    string for both is unreadable in the ledger.
    """
    precondition = design_precondition("complex", "failed")
    assert precondition.refusal_reason == DESIGN_NOT_USABLE_REASON
    assert precondition.refusal_reason != NO_DESIGN_REASON
    assert precondition.satisfied is False
    assert precondition.refusal_message and "harness design" in precondition.refusal_message


def test_a_complex_run_with_a_successful_design_proceeds() -> None:
    precondition = design_precondition("complex", "ok")
    assert precondition.refusal_reason is None
    assert precondition.satisfied is True


@pytest.mark.parametrize("level", ASSURANCE_LEVELS, ids=list(ASSURANCE_LEVELS))
@pytest.mark.parametrize(
    "design_status", [None, "failed", "ok"], ids=["no-event", "failed-event", "ok-event"]
)
def test_the_precondition_refuses_exactly_where_design_is_required(
    level: Assurance, design_status: str | None
) -> None:
    """The matrix, derived rather than listed: a refusal is possible **iff** the
    level requires a design and the ledger does not show one that succeeded.

    Written as a derivation from :func:`required_stages` so the two cannot
    disagree — the refusal a verb raises and the stage the policy declares
    required are the same decision, which is the whole point of AC-7.
    """
    precondition = design_precondition(level, design_status)
    should_refuse = required_stages(level).design and design_status != "ok"
    assert (precondition.refusal_reason is not None) is should_refuse
    assert precondition.satisfied is not should_refuse
    if should_refuse:
        assert precondition.refusal_reason in {NO_DESIGN_REASON, DESIGN_NOT_USABLE_REASON}
