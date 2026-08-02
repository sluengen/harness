"""Typed event-payload contract (CAL-1012).

The event ``data_json`` shapes were an *implicit* dict-literal contract between
the verb that emits an event and the reader that later json_extracts a key back
out — coupled across modules through bare strings, where a key rename silently
broke the reader (for the close gate, every close degraded to
``no_passing_review``: fail-safe, but undiagnosable from types).

:mod:`harness.events.payloads` makes the shape the single source of truth. These
tests pin the two guarantees the ticket's acceptance criteria state:

* **A rename breaks at type/constant level** — the reader path/key constants are
  derived from the model fields via :func:`_field_path` / :func:`_field_name`,
  which raise at import if the field is gone (so a rename cannot silently drift).
* **No raw payload key strings duplicated across writer/reader modules** — the
  reader modules (``close.py``, ``query_status.py``, ``review_protocol.py``) hold
  no raw payload key literal; they import the constants from the one payload
  module.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from harness.cli import close as close_mod
from harness.cli import query_status as query_status_mod
from harness.cli import review_protocol as review_protocol_mod
from harness.events.emitter import EventEmitter
from harness.events.payloads import (
    CLOSE_OUTCOME_FAILED,
    CLOSE_OUTCOME_OK,
    CLOSE_OUTCOME_REFUSED,
    REVIEW_OUTCOME_FAILED,
    REVIEW_OUTCOME_OK,
    REVIEW_OUTCOME_PATH,
    REVIEW_REVIEWED_SHA_PATH,
    REVIEW_VERDICT_PATH,
    WORKFLOW_FAILED_REASON_KEY,
    CheckpointEventData,
    CloseEventData,
    CloseFailureEventData,
    DeferEventData,
    DesignEventData,
    ReleaseEventData,
    ReviewEventData,
    ReviewRefusalEventData,
    WorkflowFailedEventData,
    _field_name,
    _field_path,
)
from harness.state import store


def _sync(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# The models reproduce the exact payloads the verbs emit today.
# ---------------------------------------------------------------------------


def test_review_event_data_required_keys() -> None:
    """A minimal review payload dumps exactly the always-present keys.

    ``gate_ran`` is among them (CAL-1082): it is a non-optional bool, so a new
    event always states its verify-gate evidence — there is no shape in which a
    fresh ``review`` event stays silent about whether the gate ran.
    ``design_context`` (#212) is the same, for whether the review saw the run's
    recorded design. ``outcome`` (#262) joins them: it defaults rather than being
    optional, so every fresh event states which half of the denominator it is,
    and a row that predates the field still validates as the verdict it was.
    """
    dumped = ReviewEventData(
        run_id="R1",
        reviewed_sha="abc123",
        verdict="pass",
        issues=[],
        engine="claude",
        convergence_check_required=False,
        created_at="2026-06-10T00:00:00Z",
        gate_ran=False,
    ).model_dump(exclude_none=True)

    assert dumped == {
        "run_id": "R1",
        "reviewed_sha": "abc123",
        "verdict": "pass",
        "issues": [],
        "engine": "claude",
        "convergence_check_required": False,
        "created_at": "2026-06-10T00:00:00Z",
        "gate_ran": False,
        "design_context": False,
        "outcome": REVIEW_OUTCOME_OK,
    }


def test_both_review_shapes_discriminate_on_the_same_outcome_key() -> None:
    """One ``event_type``, two models — but they must agree on the key (#262).

    ``REVIEW_OUTCOME_PATH`` is derived from :class:`ReviewEventData`, and every
    aggregate over the denominator reads that one path. If
    :class:`ReviewRefusalEventData` ever renamed its own field, the guard in
    ``payloads`` would raise at import — this asserts the property that guard
    protects, so the intent survives even if the guard is refactored: a query on
    one path sees **both** shapes, and the two values are distinct.
    """
    refusal = ReviewRefusalEventData(
        run_id="R1",
        reason="engine_timeout",
        detail="killed",
        created_at="2026-06-10T00:00:00Z",
    ).model_dump(exclude_none=True)
    success = ReviewEventData(
        run_id="R1",
        reviewed_sha="abc123",
        verdict="pass",
        issues=[],
        engine="claude",
        convergence_check_required=False,
        created_at="2026-06-10T00:00:00Z",
        gate_ran=False,
    ).model_dump(exclude_none=True)

    key = REVIEW_OUTCOME_PATH.removeprefix("$.")
    assert refusal[key] == REVIEW_OUTCOME_FAILED
    assert success[key] == REVIEW_OUTCOME_OK
    assert REVIEW_OUTCOME_OK != REVIEW_OUTCOME_FAILED
    # The refusal shape carries neither field the close gate reads.
    assert "verdict" not in refusal
    assert "reviewed_sha" not in refusal


def test_review_event_data_omits_unset_optionals() -> None:
    """``exclude_none=True`` drops the optionals the verb adds only when set —
    reproducing today's conditional ``if x is not None`` dict-building."""
    dumped = ReviewEventData(
        run_id="R1",
        reviewed_sha="abc123",
        verdict="fail",
        issues=["x"],
        engine="claude",
        convergence_check_required=True,
        created_at="2026-06-10T00:00:00Z",
        gate_ran=True,
    ).model_dump(exclude_none=True)

    for optional in ("fallback_from", "commit_message", "deferred_brief", "model"):
        assert optional not in dumped
    # The gate optionals behave the same way: unset stays absent, so a payload
    # never claims an exit code for a gate that reported none.
    for gate_optional in ("gate_command", "gate_exit_code", "gate_reason"):
        assert gate_optional not in dumped


def test_review_event_data_includes_set_optionals() -> None:
    dumped = ReviewEventData(
        run_id="R1",
        reviewed_sha="abc123",
        verdict="pass",
        issues=[],
        engine="claude",
        convergence_check_required=False,
        created_at="2026-06-10T00:00:00Z",
        gate_ran=True,
        gate_command="bash scripts/verify.sh",
        gate_exit_code=0,
        fallback_from="codex",
        commit_message="msg",
        deferred_brief="brief",
        model="opus",
    ).model_dump(exclude_none=True)

    assert dumped["fallback_from"] == "codex"
    assert dumped["commit_message"] == "msg"
    assert dumped["deferred_brief"] == "brief"
    assert dumped["gate_command"] == "bash scripts/verify.sh"
    assert dumped["gate_exit_code"] == 0
    assert dumped["model"] == "opus"


def test_review_event_data_reads_a_pre_293_row_back_as_unknown_model() -> None:
    """AC-4 (#293): no backfill, expressed as a test rather than as prose.

    A row written before the field existed validates with ``model is None``, and
    a re-dump reproduces it **without inventing the key** — so the absence keeps
    reading as *unknown*, never as a default. That is the property that stops a
    later analysis pass from ``COALESCE``-ing the very confound this field
    exists to remove.
    """
    pre_existing = {
        "run_id": "R1",
        "reviewed_sha": "abc123",
        "verdict": "pass",
        "issues": [],
        "engine": "claude",
        "convergence_check_required": False,
        "created_at": "2026-06-10T00:00:00Z",
        "gate_ran": True,
    }

    parsed = ReviewEventData(**pre_existing)

    assert parsed.model is None
    assert "model" not in parsed.model_dump(exclude_none=True)


def test_review_event_data_omits_design_context_reason_by_default() -> None:
    """AC-1 (#247): the reason a design was not applied is optional and absent
    on a payload built before the field existed, or on a review that applied
    the design successfully — only the *unset* case had no reason to record."""
    dumped = ReviewEventData(
        run_id="R1",
        reviewed_sha="abc123",
        verdict="pass",
        issues=[],
        engine="claude",
        convergence_check_required=False,
        created_at="2026-06-10T00:00:00Z",
        gate_ran=False,
    ).model_dump(exclude_none=True)

    assert "design_context_reason" not in dumped


def test_review_event_data_includes_design_context_reason_when_set() -> None:
    dumped = ReviewEventData(
        run_id="R1",
        reviewed_sha="abc123",
        verdict="pass",
        issues=[],
        engine="claude",
        convergence_check_required=False,
        created_at="2026-06-10T00:00:00Z",
        gate_ran=False,
        design_context_reason="hash_mismatch",
    ).model_dump(exclude_none=True)

    assert dumped["design_context_reason"] == "hash_mismatch"


def test_design_event_data_omits_unset_concurrency_fields() -> None:
    """#236: ``invoked_at``/``concurrent_prior_at`` default absent, not null —
    the normal (non-concurrent) design event's key set stays unchanged."""
    dumped = DesignEventData(
        run_id="R1",
        status="ok",
        engine="claude",
        model="opus",
        designed_at="2026-07-28T00:00:00Z",
        design_hash="abc123",
        grounded_sha="def456",
    ).model_dump(exclude_none=True)

    assert "invoked_at" not in dumped
    assert "concurrent_prior_at" not in dumped


def test_design_event_data_includes_set_concurrency_fields() -> None:
    dumped = DesignEventData(
        run_id="R1",
        status="ok",
        engine="claude",
        model="opus",
        designed_at="2026-07-28T00:00:05Z",
        design_hash="abc123",
        grounded_sha="def456",
        invoked_at="2026-07-28T00:00:00Z",
        concurrent_prior_at="2026-07-28T00:00:02Z",
    ).model_dump(exclude_none=True)

    assert dumped["invoked_at"] == "2026-07-28T00:00:00Z"
    assert dumped["concurrent_prior_at"] == "2026-07-28T00:00:02Z"


def test_design_event_data_omits_unset_inherited_from() -> None:
    """AC-8 (#258): an engine-produced event dumps **no** ``inherited_from`` key.

    The field is additive to the ``ok`` shape, so every existing reader must see
    the key set it has always seen — absent, not an explicit ``null``. This is
    what makes ``inherited_from``'s *presence* a reliable "this design was
    adopted, not designed" signal for a ledger reader.
    """
    dumped = DesignEventData(
        run_id="R1",
        status="ok",
        engine="claude",
        model="opus",
        designed_at="2026-07-28T00:00:00Z",
        design_hash="abc123",
        grounded_sha="def456",
    ).model_dump(exclude_none=True)

    assert "inherited_from" not in dumped


def test_design_event_data_includes_set_inherited_from() -> None:
    """AC-1 (#258): an adopted event carries the source run id, and stays ``ok``.

    ``status`` deliberately does **not** gain a third value: ``resolve_design_gate``
    keys on ``!= 'ok'`` and would read ``status='inherited'`` as a failed attempt,
    silently dropping the design from every resumed review.
    """
    dumped = DesignEventData(
        run_id="R2",
        status="ok",
        engine="claude",
        model="opus",
        designed_at="2026-07-28T00:00:00Z",
        design_hash="abc123",
        grounded_sha="def456",
        inherited_from="R1",
    ).model_dump(exclude_none=True)

    assert dumped["inherited_from"] == "R1"
    assert dumped["status"] == "ok"


def test_checkpoint_event_data_keys() -> None:
    assert CheckpointEventData(
        run_id="R1", branch="b", pushed_sha="s", pushed_at="t"
    ).model_dump() == {
        "run_id": "R1",
        "branch": "b",
        "pushed_sha": "s",
        "pushed_at": "t",
    }


def test_close_event_data_keys() -> None:
    """The landed-close shape. ``outcome`` defaults to ``ok`` (#263) so a row
    written before the field existed reads as the landed close it was; the
    latency pair is absent unless supplied, via ``exclude_none``."""
    assert CloseEventData(
        run_id="R1", ticket="CAL-1", merged_sha="s", closed_at="t"
    ).model_dump(exclude_none=True) == {
        "run_id": "R1",
        "ticket": "CAL-1",
        "merged_sha": "s",
        "closed_at": "t",
        "outcome": CLOSE_OUTCOME_OK,
    }


def test_close_failure_event_data_keys() -> None:
    """The non-landed shape (#263). ``outcome`` has no default — the writer must
    choose ``refused`` (exit 2) or ``failed`` (exit 1) rather than inheriting
    whichever was listed first."""
    assert CloseFailureEventData(
        run_id="R1",
        ticket="CAL-1",
        outcome=CLOSE_OUTCOME_REFUSED,
        reason="stale_review",
        detail="passing review is stale",
        created_at="t",
    ).model_dump(exclude_none=True) == {
        "run_id": "R1",
        "ticket": "CAL-1",
        "outcome": CLOSE_OUTCOME_REFUSED,
        "reason": "stale_review",
        "detail": "passing review is stale",
        "created_at": "t",
    }


def test_close_failure_payload_carries_no_merged_sha_when_nothing_landed() -> None:
    """Enforcement by absence: a gate refusal omits ``merged_sha`` entirely, so a
    reader keying on the merged SHA to mean "this run landed" (#233's claim)
    cannot be satisfied by a refusal row — whatever its ``reason``."""
    dumped = CloseFailureEventData(
        run_id="R1",
        ticket="CAL-1",
        outcome=CLOSE_OUTCOME_REFUSED,
        reason="dirty_worktree",
        detail="uncommitted changes",
        created_at="t",
    ).model_dump(exclude_none=True)
    assert "merged_sha" not in dumped

    landed = CloseFailureEventData(
        run_id="R1",
        ticket="CAL-1",
        outcome=CLOSE_OUTCOME_FAILED,
        reason="ticket_transition_failed",
        detail="tracker refused",
        created_at="t",
        merged_sha="abc123",
    ).model_dump(exclude_none=True)
    assert landed["merged_sha"] == "abc123", "a post-merge failure must say it landed"


def test_workflow_failed_event_data_keys() -> None:
    assert WorkflowFailedEventData(reason="reclaimed").model_dump() == {
        "reason": "reclaimed"
    }


def test_defer_event_data_project_is_nullable() -> None:
    """An unscoped repo records `project: null` (#248), not a validation error.

    `repo.project` is optional, so the effective scope a defer records can be
    absent. Existing rows carry strings and still validate — the widening is
    additive, so no migration.
    """
    dumped = DeferEventData(
        run_id="R1", ticket="ERP-221", reason="needs a call", project=None,
        needs="decision", deferred_at="t",
    ).model_dump()
    assert dumped["project"] is None


def test_release_event_data_keys() -> None:
    assert ReleaseEventData(
        run_id="R1", ticket="CAL-193", project="Harness v3",
        needs="decision", released_at="t",
    ).model_dump() == {
        "run_id": "R1",
        "ticket": "CAL-193",
        "project": "Harness v3",
        "needs": "decision",
        "released_at": "t",
    }


def test_release_event_data_project_is_nullable() -> None:
    """`defer`'s mirror — see its docstring (#248)."""
    dumped = ReleaseEventData(
        run_id="R1", ticket="ERP-221", project=None, needs="decision", released_at="t",
    ).model_dump()
    assert dumped["project"] is None


def test_defer_event_data_keys() -> None:
    assert DeferEventData(
        run_id="R1", ticket="CAL-1143", reason="needs a decision", project="Harness v3",
        needs="operator", deferred_at="t",
    ).model_dump() == {
        "run_id": "R1",
        "ticket": "CAL-1143",
        "reason": "needs a decision",
        "project": "Harness v3",
        "needs": "operator",
        "deferred_at": "t",
    }


# ---------------------------------------------------------------------------
# Reader constants are single-sourced from the models (the rename guard).
# ---------------------------------------------------------------------------


def test_reader_constants_derive_from_model_fields() -> None:
    assert REVIEW_REVIEWED_SHA_PATH == "$.reviewed_sha"
    assert REVIEW_VERDICT_PATH == "$.verdict"
    assert WORKFLOW_FAILED_REASON_KEY == "reason"
    assert "reviewed_sha" in ReviewEventData.model_fields
    assert "verdict" in ReviewEventData.model_fields
    assert "reason" in WorkflowFailedEventData.model_fields


def test_field_path_raises_on_unknown_field() -> None:
    """A field rename that misses a derived constant fails at import, not at
    runtime — the guarantee behind 'a rename breaks at constant level'."""
    with pytest.raises(ValueError, match="no field"):
        _field_path(ReviewEventData, "does_not_exist")
    with pytest.raises(ValueError, match="no field"):
        _field_name(WorkflowFailedEventData, "does_not_exist")


def test_field_path_and_name_agree() -> None:
    assert _field_path(ReviewEventData, "verdict") == "$.verdict"
    assert _field_name(ReviewEventData, "verdict") == "verdict"


# ---------------------------------------------------------------------------
# Writer→reader end to end: a review payload built from the model is read
# correctly by the close gate through the shared path constants.
# ---------------------------------------------------------------------------


def _seed_run(db_path: Path, run_id: str) -> None:
    async def _insert() -> None:
        await store.init_db(db_path)
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs ("
                "run_id, workflow_name, workflow_version, status, state_json, "
                "inputs_json, base_branch, worktree_path, worktree_branch, "
                "ticket, started_at, pid"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id, "", 0, "open", "{}", "{}", "dev",
                    "/tmp/wt", f"harness/{run_id}", "CAL-1012",
                    "2026-06-10T00:00:00Z", 1234,
                ),
            )
            await conn.commit()

    _sync(_insert())


def _emit_review_via_model(
    db_path: Path, run_id: str, reviewed_sha: str, verdict: str
) -> None:
    async def _emit() -> None:
        data = ReviewEventData(
            run_id=run_id,
            reviewed_sha=reviewed_sha,
            verdict=verdict,
            issues=[],
            engine="claude",
            convergence_check_required=False,
            created_at="2026-06-10T00:00:00Z",
            gate_ran=True,
            gate_command="bash scripts/verify.sh",
            gate_exit_code=0,
        ).model_dump(exclude_none=True)
        await EventEmitter(db_path).emit(
            run_id=run_id, event_type="review", data=data
        )

    _sync(_emit())


def test_close_gate_opens_on_model_written_pass(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    run_id = "01JRUNPAYLOADXXXXXXXXXXX01"
    _seed_run(db_path, run_id)
    _emit_review_via_model(db_path, run_id, "headsha", "pass")

    assert _sync(close_mod._evaluate_gate(db_path, run_id, "headsha")) is None


def test_close_gate_no_passing_review_when_fail(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    run_id = "01JRUNPAYLOADXXXXXXXXXXX02"
    _seed_run(db_path, run_id)
    _emit_review_via_model(db_path, run_id, "headsha", "fail")

    result = _sync(close_mod._evaluate_gate(db_path, run_id, "headsha"))
    assert result is not None and result[0] == "no_passing_review"


def test_close_gate_stale_when_sha_moved(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    run_id = "01JRUNPAYLOADXXXXXXXXXXX03"
    _seed_run(db_path, run_id)
    _emit_review_via_model(db_path, run_id, "oldsha", "pass")

    result = _sync(close_mod._evaluate_gate(db_path, run_id, "newsha"))
    assert result is not None and result[0] == "stale_review"


# ---------------------------------------------------------------------------
# AC-1 measure: the payload key strings are NOT duplicated in reader modules.
# ---------------------------------------------------------------------------


def test_close_gate_source_holds_no_raw_review_key_literals() -> None:
    """close.py must reach the review payload only through the shared constants —
    no ``$.reviewed_sha`` / ``$.verdict`` literal of its own (AC-1)."""
    src = Path(close_mod.__file__).read_text()
    assert "$.reviewed_sha" not in src
    assert "$.verdict" not in src
    assert "from harness.events.payloads import" in src


def test_query_status_source_holds_no_raw_reason_extraction() -> None:
    """query_status.py must read ``reason`` via the shared key constant (AC-1)."""
    src = Path(query_status_mod.__file__).read_text()
    assert '.get("reason")' not in src
    assert "from harness.events.payloads import" in src


def test_design_gate_source_holds_no_raw_design_key_literals() -> None:
    """review_protocol.py must reach the ``design`` payload only through the
    shared key constants — no raw ``status`` / ``design_hash`` read of its own
    (AC-1, extended to the third reader module by #217).

    The forbidden set is those two keys specifically, not the ``.get`` idiom:
    :func:`~harness.cli.review_protocol.scan_submit_line` legitimately reads the
    engine's SUBMIT JSON (``payload.get("verdict")`` and friends), a different
    contract with no payload model behind it.
    """
    src = Path(review_protocol_mod.__file__).read_text()
    assert '.get("status")' not in src
    assert '.get("design_hash")' not in src
    assert "from harness.events.payloads import" in src
