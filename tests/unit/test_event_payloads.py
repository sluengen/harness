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
  reader modules (``close.py``, ``query_status.py``) hold no raw json-extract key
  literal; they import the constants from the one payload module.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from harness.cli import close as close_mod
from harness.cli import query_status as query_status_mod
from harness.events.emitter import EventEmitter
from harness.events.payloads import (
    REVIEW_REVIEWED_SHA_PATH,
    REVIEW_VERDICT_PATH,
    WORKFLOW_FAILED_REASON_KEY,
    CheckpointEventData,
    CloseEventData,
    DeferEventData,
    ReviewEventData,
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
    recorded design.
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
    }


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

    for optional in ("fallback_from", "commit_message", "deferred_brief"):
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
    ).model_dump(exclude_none=True)

    assert dumped["fallback_from"] == "codex"
    assert dumped["commit_message"] == "msg"
    assert dumped["deferred_brief"] == "brief"
    assert dumped["gate_command"] == "bash scripts/verify.sh"
    assert dumped["gate_exit_code"] == 0


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
    assert CloseEventData(
        run_id="R1", ticket="CAL-1", merged_sha="s", closed_at="t"
    ).model_dump() == {
        "run_id": "R1",
        "ticket": "CAL-1",
        "merged_sha": "s",
        "closed_at": "t",
    }


def test_workflow_failed_event_data_keys() -> None:
    assert WorkflowFailedEventData(reason="reclaimed").model_dump() == {
        "reason": "reclaimed"
    }


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
