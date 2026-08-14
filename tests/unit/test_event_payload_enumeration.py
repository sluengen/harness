"""#282 — no live doc hand-lists a subset of the event-payload class set.

``specs/features/run-ledger.md`` named eight payload contracts in one comma run
while :mod:`harness.events.payloads` defined **ten**. The two it omitted —
``CloseFailureEventData`` (#263's close-refusal telemetry) and
``ReclaimUndoneEventData`` (#254) — appeared nowhere in ``specs/``, and one of
them describes a close-gate surface. Nothing measured the list, so it fell two
behind silently and the suite stayed green.

This is the enumeration idiom the repo has mechanized twice before (#219/#220):
*a hand-written set of guarded subjects falls behind silently, and the guard
then reads green because it never checked.* ``test_cli_surface_locked.py`` locks
live docs against hand-listing a **command** subset; nothing covered the payload
models.

The fix this guard enforces is deletion, not maintenance. A doc may state the
emitter/reader rule and point at the module; a *complete* list is still legal,
because the failure mode is the subset, not the naming. But a complete list is a
second copy of a set with one home, kept true only by a test — so the paragraph
now names the module and no subset of it, and this guard re-arms automatically
if an enumeration ever returns.

**What counts as an enumeration is a *run*** — two or more backticked
``*EventData`` tokens joined only by whitespace, ``,``, ``/`` or ``and``. A lone
reference is not an enumeration: ``run-ledger.md`` legitimately names
``ReviewRefusalEventData`` when arguing why the refusal shape is a separate
model, and two proposals each name one model in passing. Flagging per-document
instead would turn those into false positives and pressure authors to delete
prose that says something.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from tests.unit.test_cli_surface_locked import (
    _live_docs,
    _live_text,
    _parametrized_argvalues,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: The as-built record that carried the stale list — pinned so the corpus floor
#: below asserts the guard still covers the doc that motivated it.
_RUN_LEDGER_SPEC = _REPO_ROOT / "specs" / "features" / "run-ledger.md"

#: A single backticked payload-class token, e.g. ``` `ReviewEventData` ```.
_PAYLOAD_TOKEN = re.compile(r"`(\w*EventData)`")

#: Two or more payload tokens joined **only** by list punctuation — the shape of
#: an enumeration, as opposed to a reference. Anything else between two tokens
#: (a verb, a clause, a sentence break) means the doc is talking about them, not
#: listing them.
_PAYLOAD_RUN = re.compile(
    r"`\w*EventData`(?:\s*(?:,\s*and|,|/|and)\s*`\w*EventData`)+"
)


def _payload_models() -> set[str]:
    """Every payload model class name declared in :mod:`harness.events.payloads`.

    Derived by import rather than by parsing the source: the import is the same
    fact mypy checks, so it cannot disagree with the code. ``__module__`` is
    checked so a model merely *re-exported* through the module never joins the
    set.
    """
    from harness.events import payloads

    return {
        name
        for name, obj in vars(payloads).items()
        if isinstance(obj, type)
        and issubclass(obj, BaseModel)
        and obj.__module__ == payloads.__name__
        and name.endswith("EventData")
    }


def _offenders(text: str) -> list[list[str]]:
    """Every payload run in *text* that is not the complete class set.

    Both drift directions fail the same way, because the comparison is equality
    rather than containment: a proper subset (the #282 defect) and a name no
    longer defined in ``payloads.py`` (a rename or removal that left the prose
    behind) both make ``names != derived``.
    """
    derived = _payload_models()
    runs = [_PAYLOAD_TOKEN.findall(run) for run in _PAYLOAD_RUN.findall(text)]
    return [names for names in runs if set(names) != derived]


@pytest.mark.parametrize(
    "doc", _live_docs(), ids=lambda p: str(p.relative_to(_REPO_ROOT))
)
def test_no_live_doc_handlists_a_payload_subset(doc: Path) -> None:
    """No live doc enumerates a proper subset of the payload-class set."""
    offenders = _offenders(_live_text(doc))
    assert not offenders, (
        f"{doc.relative_to(_REPO_ROOT)} enumerates payload classes without "
        f"naming the whole set. Runs found: {offenders}; missing from the first: "
        f"{sorted(_payload_models() - set(offenders[0]))}. Delete the list and "
        f"point at harness/events/payloads.py as the source — a subset here goes "
        f"stale silently every time a payload model is added."
    )


def test_the_payload_model_derivation_finds_its_subjects() -> None:
    """The derivation is non-vacuous (AC-2).

    A parametrized guard over an empty derived set *skips* rather than fails, so
    a derivation that silently found nothing would announce success. No
    cardinality is asserted — a hardcoded count is the drift this ticket exists
    to remove — but the set must be non-empty and must contain the model the
    close gate reads, so a rename of that model names itself here instead of
    quietly shrinking the set.
    """
    derived = _payload_models()
    assert derived, (
        "no *EventData models derived from harness.events.payloads — the "
        "derivation found no subjects, so every guard over it passes vacuously"
    )
    assert "ReviewEventData" in derived, (
        f"ReviewEventData (the model the close gate reads) is missing from the "
        f"derived set {sorted(derived)} — the derivation is looking in the wrong "
        f"place, or the model was renamed without updating its readers"
    )


def test_a_stale_payload_list_is_caught() -> None:
    """The scan flags the pre-fix sentence verbatim (positive control).

    Calls the same :func:`_offenders` the live guard calls, so a control that
    re-implemented the scan cannot go green over a guard that never fires.
    """
    pre_fix = (
        "Each event payload's shape is a **typed contract** in "
        "[`harness/events/payloads.py`](../../harness/events/payloads.py) "
        "(CAL-1012) — `ReviewEventData`, `ReviewRefusalEventData`, "
        "`CheckpointEventData`, `WorkflowFailedEventData`, `CloseEventData`, "
        "`DeferEventData`, `DesignEventData`, `ReleaseEventData`."
    )
    offenders = _offenders(pre_fix)
    assert len(offenders) == 1, f"expected the stale run to be flagged, got {offenders}"
    assert set(_payload_models()) - set(offenders[0]) == {
        "CloseFailureEventData",
        "ReclaimUndoneEventData",
        # #353's ``CertifyEventData`` postdates the pre-fix sentence, so it is a
        # third model the stale list could not have named. Listed rather than
        # derived-around on purpose: this control's whole subject is *which*
        # models a fixed historical sentence omitted, and computing that from
        # today's module would make it agree with itself.
        "CertifyEventData",
    }


_COMPLETE_RUN = ", ".join(f"`{name}`" for name in sorted(_payload_models()))

_SCAN_CASES = [
    pytest.param(_COMPLETE_RUN, False, id="complete-run-is-not-a-subset"),
    pytest.param(
        "The refusal shape is `ReviewRefusalEventData`.", False, id="lone-reference"
    ),
    pytest.param(
        "`DesignEventData` carries the hash. Separately, `ReviewEventData` "
        "carries the verdict.",
        False,
        id="two-lone-references-in-separate-sentences",
    ),
    pytest.param(
        "`ReviewEventData`, `CloseEventData`", True, id="run-of-two-is-a-subset"
    ),
    pytest.param(
        "`ReviewEventData` and `CloseEventData`", True, id="and-joined-run"
    ),
    pytest.param(
        "`ReviewEventData` / `CloseEventData`", True, id="slash-joined-run"
    ),
    pytest.param(
        _COMPLETE_RUN + ", `LegacyEventData`", True, id="undefined-name-in-a-run"
    ),
]


@pytest.mark.parametrize("text, flagged", _SCAN_CASES)
def test_the_scan_distinguishes_a_run_from_a_reference(text: str, flagged: bool) -> None:
    """A run is flagged against the whole set; a reference is left alone."""
    assert bool(_offenders(text)) is flagged


def test_the_payload_guard_is_parametrized_over_the_whole_live_doc_corpus() -> None:
    """The guard's corpus **is** ``_live_docs()`` — the floor, pinned.

    Read off the captured parametrize mark rather than recomputed, so narrowing
    the guard to a hand-listed tuple fails here instead of silently dropping
    most of the corpus (the #249/#252 failure mode).
    """
    captured = _parametrized_argvalues(test_no_live_doc_handlists_a_payload_subset, "doc")
    assert captured == _live_docs()
    assert _RUN_LEDGER_SPEC in captured, (
        "run-ledger.md — the record this guard was written for — is not in the "
        "scanned corpus"
    )
