"""Verb-contract lock — the surface is a versioned interface (CAL-649, decision D3).

The `/harness <verb>` JSON output and the `close` refusal-reason enum are the
machine-readable **app contract** that orchestrating agents — and, once the
stopgap commands become thin clients over the harness app, consuming repos —
parse. The "Surface is a versioned interface" principle
(``specs/architecture-principles.md``) makes that contract a versioned one: a
change to it is a *major*-level interface event that must surface as a deliberate
version decision on the exposing surface unit, never an unannounced break.

This guard mirrors the CLI-surface-lock (CAL-603, ``test_cli_surface_locked.py``):
that one locks the *command names*; this one locks the *verb output shape* and
the *refusal-reason enum*. It binds to the **JSON the production CLI actually
emits** — each verb is driven through ``CliRunner`` with its orchestration mocked,
and the asserted keys come from the command's real ``stdout`` (the
``typer.echo(output.model_dump_json())`` line), not from re-serializing a model in
the test. So a serialization alias, a custom serializer, a field exclusion (e.g. a
switch to ``model_dump_json(exclude_none=True)``), or a payload wrap before
``typer.echo`` is caught — not only a renamed attribute. A change fails the test
until the pinned snapshot below is deliberately updated — and that update is
exactly where the patch/minor/major decision is made. A golden snapshot cannot
mechanically force a header bump (nothing can), but it guarantees the contract
change is *visible in review* rather than silent drift.

``test_docs_consistency.py`` checks docs are present; the surface-lock checks the
command set; this checks the *data* an agent reads back off each verb.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import get_args
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel
from typer.testing import CliRunner

from harness.cli import app
from harness.cli.close import (
    CloseOutput,
    FailureReason,
    MergeFailureReason,
    RefusalReason,
    TicketFailureReason,
)
from harness.cli.review import Engine, ReviewOutput, Verdict
from harness.cli.start import StartOutput, TicketContext
from harness.state import store
from tests._gitutil import init_repo

REPO_ROOT = Path(__file__).parent.parent.parent
PRINCIPLES = REPO_ROOT / "specs" / "architecture-principles.md"

cli_runner = CliRunner()


# --- Verb output keys (emitted by the production CLI) -------------------------

#: One minimal-but-valid output instance per verb — the canned return the mocked
#: orchestration hands back, so the command serializes and echoes it through its
#: real ``typer.echo(output.model_dump_json())`` path.
_INSTANCES: dict[str, BaseModel] = {
    "start": StartOutput(
        run_id="r",
        ticket=TicketContext(identifier="CAL-1"),
        worktree_path="/w",
        worktree_branch="b",
        base_branch="dev",
    ),
    "review": ReviewOutput(
        verdict="pass", issues=[], reviewed_sha="sha", run_id="r", engine="claude"
    ),
    "close": CloseOutput(
        run_id="r",
        ticket="CAL-1",
        reviewed_sha="sha",
        merged=True,
        ticket_done=True,
        status="closed",
    ),
}

#: The CLI argv that drives each verb to its emission path (the success path is
#: reached because its orchestration is mocked to return ``_INSTANCES[verb]``).
#: ``--repo``/``--db`` are filled with the tmp paths at call time.
_ARGV: dict[str, list[str]] = {
    "start": ["start", "CAL-1"],
    "review": ["review"],
    "close": ["close", "CAL-1"],
}

#: The module attribute (the async orchestration entry) each command awaits via
#: ``asyncio.run`` before echoing the result. Mocking it isolates the *emission*.
_ORCH: dict[str, str] = {
    "start": "harness.cli.start._run_start",
    "review": "harness.cli.review._run_review",
    "close": "harness.cli.close._run_close",
}

#: The locked top-level JSON keys each verb emits, as-built
#: (``harness/cli/{start,review,close}.py``). Adding, dropping, or renaming a key
#: — whether via a field, an alias, a serializer, or an exclusion — is an
#: output-contract change: a *major*-level event under the "Surface is a versioned
#: interface" principle. Update this snapshot only alongside that deliberate
#: version decision.
EXPECTED_VERB_OUTPUT_KEYS: dict[str, set[str]] = {
    # ``attended`` added with #295 (ADR 0011) — the run's declared attendance
    # mode, emitted on both the new-run and existing-run path. Additive and
    # always present (never omitted when false), so a consumer reads the mode
    # from a field rather than inferring it from absence.
    # ``assurance`` / ``assurance_reason`` added with #352 — the level the run
    # was opened under and why, snapshotted at start so the orchestrator follows
    # the recorded plan rather than re-reading the issue's labels. Additive and
    # always present (a run predating the migration reports ``simple`` /
    # ``unrecorded``), so a consumer reads the level from a field rather than
    # inferring it from absence — the same shape ``attended`` took.
    "start": {
        "run_id",
        "ticket",
        "worktree_path",
        "worktree_branch",
        "base_branch",
        "attended",
        "assurance",
        "assurance_reason",
    },
    # ``convergence_check_required`` added with the CAL-906 spend breakers — a
    # bounded advisory bool prompting the build agent to assess convergence on a
    # fail past the unconditional review→fix cycles (a deliberate, additive
    # output-contract extension). ``cycles_exhausted`` is its #329 terminal
    # counterpart, added the same way: a fail that spent the last allowed cycle.
    "review": {
        "verdict",
        "issues",
        "reviewed_sha",
        "run_id",
        "engine",
        "convergence_check_required",
        "cycles_exhausted",
    },
    "close": {"run_id", "ticket", "reviewed_sha", "merged", "ticket_done", "status"},
}

#: ``StartOutput.ticket`` serializes to a nested object; its keys are part of the
#: start output JSON a consumer parses (``ticket.identifier`` etc.), so the nested
#: contract is locked too — an unlocked nested object is a silent gap.
EXPECTED_TICKET_CONTEXT_KEYS = {"id", "identifier", "title", "description", "url"}


def _emit_via_cli(
    verb: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, object]:
    """Drive ``verb`` through the real CLI with its orchestration mocked; return
    the JSON object the command actually echoed to stdout."""
    init_repo(tmp_path)  # the verbs refuse a --repo that is not a git top-level (#214)
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))
    monkeypatch.setattr(_ORCH[verb], AsyncMock(return_value=_INSTANCES[verb]))
    db = tmp_path / "harness.db"
    asyncio.run(store.init_db(db))
    result = cli_runner.invoke(
        app, [*_ARGV[verb], "--repo", str(tmp_path), "--db", str(db)]
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


@pytest.mark.parametrize("verb", sorted(EXPECTED_VERB_OUTPUT_KEYS))
def test_verb_emits_locked_output_keys(
    verb: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each verb's *real CLI stdout* exposes exactly its locked top-level key set.

    Reads the JSON the production ``typer.echo(output.model_dump_json())`` emits,
    so aliases / serializers / exclusions / a payload wrap are in scope. Fails on
    any added / dropped / renamed emitted key — version the exposing surface unit
    (major bump) and update ``EXPECTED_VERB_OUTPUT_KEYS`` in the same change.
    """
    emitted = _emit_via_cli(verb, tmp_path, monkeypatch)
    assert set(emitted) == EXPECTED_VERB_OUTPUT_KEYS[verb]


def test_start_emits_locked_nested_ticket_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``start``'s real CLI stdout nests a ``ticket`` object with exactly its
    locked key set (the nested contract a consumer parses)."""
    emitted = _emit_via_cli("start", tmp_path, monkeypatch)
    assert set(emitted["ticket"]) == EXPECTED_TICKET_CONTEXT_KEYS  # type: ignore[arg-type]


# --- Refusal-reason enum + emitted refusal payload ----------------------------

#: The structured ``close`` refusal reasons (``harness/cli/close.py``). Exactly
#: one is emitted in the ``{"reason": ...}`` JSON on a gate failure, and an
#: orchestrating agent branches on the value — so the enum is interface. Adding,
#: dropping, or renaming a reason is a *major*-level event.
EXPECTED_REFUSAL_REASONS = {
    "no_run",
    "dirty_worktree",
    "no_passing_review",
    "stale_review",
    # CAL-1082 — the verify-gate backstop: a pass that cannot show the repo's
    # gate ran is refused rather than trusted. A deliberate contract addition.
    "no_gate_evidence",
    # CAL-1154 REMOVED ``dirty_base_checkout`` (added by CAL-1151): close now
    # merges in a throwaway worktree and never mutates the main checkout, so the
    # base-checkout precondition is unreachable and was removed deliberately, with
    # this locked snapshot updated in the same change. A refusal-reason *removal*
    # is a major-level interface event exactly as an addition is.
}


def test_refusal_reason_enum_matches_the_locked_contract() -> None:
    """The ``close`` refusal-reason type holds exactly the locked members.

    Fails on any added / dropped / renamed reason — a refusal-reason change is an
    interface change (major); version the exposing unit and update the snapshot.
    """
    assert set(get_args(RefusalReason)) == EXPECTED_REFUSAL_REASONS


#: The structured ``close`` ticket-transition **failure** reasons (#233) —
#: exit 1, not exit 2, because the merge has already landed by the time either
#: fires. Deliberately a *separate* locked set from ``EXPECTED_REFUSAL_REASONS``:
#: folding them together would let a caller that correctly reads "a reason
#: means no side effects" draw that conclusion at exactly the moment it is
#: false.
EXPECTED_CLOSE_FAILURE_REASONS = {
    "ticket_transition_failed",
    "ticket_transition_unconfirmed",
}

#: The structured ``close`` **merge/push** failure reasons (#300) — also exit 1,
#: and also a separate locked set, because they mean the opposite thing about
#: the merge: a member here means the merge did **not** land, while a member of
#: ``EXPECTED_CLOSE_FAILURE_REASONS`` means it did and only the ticket lagged.
#: ``close_merge`` owns the strings; ``close`` propagates them unchanged, so
#: this snapshot is what makes a new reason a deliberate contract event rather
#: than a silent one.
EXPECTED_CLOSE_MERGE_FAILURE_REASONS = {
    "git_status_failed",
    "network_timeout",
    "fetch_failed",
    "merge_conflict",
    "merge_failed",
    "push_rejected",
    "worktree_create_failed",
}


def _flattened(union: object) -> set[str]:
    """The string members of a union of ``Literal``s.

    ``get_args`` on such a union yields the member ``Literal`` *types*, not the
    strings, so the values need one more unwrap.
    """
    return {value for literal in get_args(union) for value in get_args(literal)}


def test_close_failure_reason_enum_matches_the_locked_contract() -> None:
    """The ``close`` ticket-transition failure-reason type holds exactly the
    locked members — the exit-1 counterpart to the exit-2 refusal-reason lock
    above. Fails on any added / dropped / renamed reason."""
    assert set(get_args(TicketFailureReason)) == EXPECTED_CLOSE_FAILURE_REASONS


def test_close_merge_failure_reason_enum_matches_the_locked_contract() -> None:
    """The ``close`` merge/push failure-reason type holds exactly the locked
    members (#300). Fails on any added / dropped / renamed reason — the same
    major-level event as its two sibling locks."""
    assert set(get_args(MergeFailureReason)) == EXPECTED_CLOSE_MERGE_FAILURE_REASONS


def test_the_exit_one_vocabulary_is_exactly_its_two_families() -> None:
    """``FailureReason`` — the exit-1 vocabulary as a whole — is the disjoint
    union of the two locked families, and neither overlaps the exit-2 refusals.

    A reason that landed in both families, or in a refusal *and* a failure,
    would make "which side of the merge am I on?" unanswerable from the wire.
    """
    assert _flattened(FailureReason) == (
        EXPECTED_CLOSE_FAILURE_REASONS | EXPECTED_CLOSE_MERGE_FAILURE_REASONS
    )
    assert not (EXPECTED_CLOSE_FAILURE_REASONS & EXPECTED_CLOSE_MERGE_FAILURE_REASONS)
    assert not (EXPECTED_REFUSAL_REASONS & _flattened(FailureReason))


#: The ``review`` verdict values (``harness/cli/review.py``). An orchestrating
#: agent branches on ``pass`` / ``fail`` / ``defer`` exactly as it branches on a
#: refusal reason, so the *values* — not just the ``verdict`` key — are interface.
#: Adding, dropping, or renaming a verdict is a *major*-level event.
EXPECTED_REVIEW_VERDICTS = {"pass", "fail", "defer"}


def test_review_verdict_enum_matches_the_locked_contract() -> None:
    """The ``review`` verdict type holds exactly the locked values.

    The output-key lock pins the ``verdict`` *key*; this pins its *values*, so a
    new or renamed verdict cannot drift silently past the suite.
    """
    assert set(get_args(Verdict)) == EXPECTED_REVIEW_VERDICTS


#: The ``review`` engine-provenance values (``harness/cli/review.py``). An
#: orchestrating agent reads ``engine`` back to know which engine produced the
#: verdict (and, with CAL-702, whether a fallback occurred), so the *values* are
#: interface exactly as the verdicts are. Adding, dropping, or renaming an engine
#: is a *major*-level event.
EXPECTED_REVIEW_ENGINES = {"claude", "codex"}


def test_review_engine_enum_matches_the_locked_contract() -> None:
    """The ``review`` engine type holds exactly the locked values.

    The output-key lock pins the ``engine`` *key*; this pins its *values*, so a
    new or renamed engine cannot drift silently past the suite.
    """
    assert set(get_args(Engine)) == EXPECTED_REVIEW_ENGINES


def test_close_emits_a_locked_refusal_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``close`` on a no-open-run worktree emits a ``reason`` that is a locked
    member — binding the emitted ``{"reason": ...}`` payload to the enum snapshot,
    not just the ``Literal`` type. Self-contained: an empty initialized ledger
    refuses with ``no_run`` before any Linear or git side effect.
    """
    init_repo(tmp_path)  # the verbs refuse a --repo that is not a git top-level (#214)
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))
    db = tmp_path / "harness.db"
    asyncio.run(store.init_db(db))

    result = cli_runner.invoke(
        app,
        ["close", "CAL-1", "--repo", str(tmp_path), "--db", str(db)],
    )
    assert result.exit_code != 0
    reason = json.loads(result.output)["reason"]
    assert reason in EXPECTED_REFUSAL_REASONS
    assert reason == "no_run"


# --- Drift detection self-test ------------------------------------------------
# Proves the lock actually catches a change, rather than only asserting the
# current snapshot matches itself: a perturbed emitted-key set / refusal set must
# be flagged by the same set-equality the locks above rely on.


def test_the_lock_catches_an_added_key() -> None:
    """An emitted-key set with an extra key does not equal its locked snapshot."""
    drifted = EXPECTED_VERB_OUTPUT_KEYS["close"] | {"leaked"}
    assert drifted != EXPECTED_VERB_OUTPUT_KEYS["close"]


def test_the_lock_catches_a_renamed_refusal_reason() -> None:
    """A refusal-reason set with a renamed member is flagged."""
    renamed = (EXPECTED_REFUSAL_REASONS - {"no_run"}) | {"missing_run"}
    assert renamed != EXPECTED_REFUSAL_REASONS


# --- The semver principle is recorded (AC-1) ----------------------------------

#: AC-1: the "Surface is a versioned interface" semver principle is recorded as a
#: first-class principle (not only inside the merge decision block) with all three
#: bump levels named. A structural check so deleting it fails the suite.
_PRINCIPLE_HEADING = re.compile(r"^### Surface is a versioned interface\b", re.M)


def test_versioned_interface_principle_is_recorded() -> None:
    """``architecture-principles.md`` records the semver principle with all three
    bump levels (patch / minor / major) named."""
    text = PRINCIPLES.read_text()
    heading = _PRINCIPLE_HEADING.search(text)
    assert heading, (
        "The 'Surface is a versioned interface' principle is missing from "
        "specs/architecture-principles.md (CAL-649 AC-1)."
    )
    # Scope to the principle's own section so the three levels are asserted in
    # context, not matched incidentally elsewhere in the spec.
    start = heading.start()
    nxt = re.search(r"^### ", text[start + 3 :], re.M)
    section = text[start : start + 3 + nxt.start()] if nxt else text[start:]
    for level in ("patch", "minor", "major"):
        assert level in section.lower(), (
            f"The versioned-interface principle must name the '{level}' bump level."
        )
