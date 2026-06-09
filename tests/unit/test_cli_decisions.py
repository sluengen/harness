"""Tests for ``decisions`` / ``decision`` CLI surface — H-2-003 / H-2-004.

H-2-003 implements the read-side of the human-in-the-loop decision flow:

* ``harness decisions list``        — list paused runs (question from event)
* ``harness decision show <run-id>``— render question + display_state fields

H-2-004 implements the write-side:

* ``harness decision approve <run-id>`` — resume the workflow approved
* ``harness decision reject <run-id>``  — resume the workflow rejected

Contract:

``decisions list``
  * Exits 0 with empty output when there are no paused runs (including when
    the DB does not exist yet).
  * Exits 0 and lists one block per paused run — run_id, workflow, started,
    question — when paused runs exist.
  * ``--json`` emits a JSON array (empty ``[]`` or list of objects).
  * Non-paused runs (completed, running, failed) are excluded.
  * ``--db <path>`` overrides the default DB location.

``decision show <run-id>``
  * Exits 2 (invocation error) with a message on stderr when the run does
    not exist in the DB (or the DB does not exist).
  * Exits 2 when the run exists but is not paused.
  * Exits 0 and renders run_id, workflow, started, question, and any
    display_state field values when the run is paused.
  * ``--json`` emits a single JSON object with ``run_id``, ``workflow_name``,
    ``started_at``, ``question``, and ``display_state`` (field→value dict).
  * ``--db <path>`` overrides the default DB location.

``decision approve / reject``
  * Exits 2 when run not found.
  * Exits 2 when run is not paused.
  * Calls runner.resume() with correct approved flag and optional comment.
  * ``--json`` emits a JSON object with run_id, outcome, exit_code.

``RUN_STATUSES`` type guard:
  * ``paused`` and ``stalled`` are present in the canonical status set.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.state import store

runner = CliRunner()


# ---------------------------------------------------------------------------
# DB seeding helpers (mirrors test_cli_query.py)
# ---------------------------------------------------------------------------


def _run_sync(coro: Any) -> Any:
    """Drive a coroutine from a synchronous test function.

    pytest-asyncio (auto mode) may leave a running loop on the thread, so we
    spin up a fresh loop rather than using asyncio.run() directly.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _seed_run(
    db_path: Path,
    *,
    run_id: str = "R1",
    workflow_name: str = "build",
    workflow_version: int = 1,
    status: str = "paused",
    state_json: str = "{}",
    inputs_json: str = "{}",
    base_branch: str | None = "main",
    worktree_branch: str | None = None,
    exit_code: int | None = None,
    started_at: str = "2026-06-01T10:00:00Z",
    completed_at: str | None = None,
    duration_ms: int | None = None,
) -> None:
    async def _insert() -> None:
        await store.init_db(db_path)
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
                "state_json, inputs_json, base_branch, worktree_branch, exit_code, "
                "started_at, completed_at, duration_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    workflow_name,
                    workflow_version,
                    status,
                    state_json,
                    inputs_json,
                    base_branch,
                    worktree_branch,
                    exit_code,
                    started_at,
                    completed_at,
                    duration_ms,
                ),
            )
            await conn.commit()

    _run_sync(_insert())


def _seed_event(
    db_path: Path,
    *,
    run_id: str = "R1",
    node_id: str | None = "gate",
    event_type: str = "decision_requested",
    timestamp: str = "2026-06-01T10:05:00Z",
    data: dict[str, Any] | None = None,
) -> None:
    async def _insert() -> None:
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO events (run_id, node_id, event_type, timestamp, "
                "duration_ms, data_json) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, node_id, event_type, timestamp, None, json.dumps(data or {})),
            )
            await conn.commit()

    _run_sync(_insert())


# ---------------------------------------------------------------------------
# harness decisions list — empty / no-DB
# ---------------------------------------------------------------------------


def test_decisions_list_empty_when_no_db(tmp_path: Path) -> None:
    """No DB file → empty output, exit 0."""
    db = tmp_path / "harness.db"
    result = runner.invoke(app, ["decisions", "list", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == ""


def test_decisions_list_empty_when_no_paused_runs(tmp_path: Path) -> None:
    """DB exists with non-paused runs → empty output, exit 0."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="completed")
    _seed_run(db, run_id="R2", status="running")
    result = runner.invoke(app, ["decisions", "list", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == ""


def test_decisions_list_json_empty_returns_array(tmp_path: Path) -> None:
    """No paused runs → ``--json`` emits ``[]``."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="completed")
    result = runner.invoke(app, ["decisions", "list", "--db", str(db), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == []


# ---------------------------------------------------------------------------
# harness decisions list — with paused runs
# ---------------------------------------------------------------------------


def test_decisions_list_shows_paused_run(tmp_path: Path) -> None:
    """A paused run appears in human output."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", workflow_name="build", status="paused")
    result = runner.invoke(app, ["decisions", "list", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "R1" in result.stdout
    assert "build" in result.stdout


def test_decisions_list_excludes_non_paused_runs(tmp_path: Path) -> None:
    """Only paused runs appear; completed/running are filtered out."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="PAUSED", status="paused")
    _seed_run(db, run_id="DONE", status="completed")
    _seed_run(db, run_id="RUN", status="running")
    result = runner.invoke(app, ["decisions", "list", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "PAUSED" in result.stdout
    assert "DONE" not in result.stdout
    assert "RUN" not in result.stdout


def test_decisions_list_shows_question_from_event(tmp_path: Path) -> None:
    """The question from the ``decision_requested`` event is rendered."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="paused")
    _seed_event(
        db,
        run_id="R1",
        event_type="decision_requested",
        data={"message": "Should we deploy?", "display_state": []},
    )
    result = runner.invoke(app, ["decisions", "list", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "Should we deploy?" in result.stdout


def test_decisions_list_question_placeholder_when_no_event(tmp_path: Path) -> None:
    """When no ``decision_requested`` event exists, question renders as ``-``."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="paused")
    result = runner.invoke(app, ["decisions", "list", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "R1" in result.stdout
    assert "question:" in result.stdout


def test_decisions_list_json_includes_question(tmp_path: Path) -> None:
    """``--json`` includes ``run_id``, ``workflow_name``, ``started_at``, ``question``."""
    db = tmp_path / "harness.db"
    _seed_run(
        db,
        run_id="R1",
        workflow_name="release",
        status="paused",
        started_at="2026-06-01T10:00:00Z",
    )
    _seed_event(
        db,
        run_id="R1",
        event_type="decision_requested",
        data={"message": "Ready to release?", "display_state": []},
    )
    result = runner.invoke(app, ["decisions", "list", "--db", str(db), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert len(payload) == 1
    item = payload[0]
    assert item["run_id"] == "R1"
    assert item["workflow_name"] == "release"
    assert item["started_at"] == "2026-06-01T10:00:00Z"
    assert item["question"] == "Ready to release?"


def test_decisions_list_json_null_question_when_no_event(tmp_path: Path) -> None:
    """``--json`` emits ``null`` for ``question`` when no event exists."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="paused")
    result = runner.invoke(app, ["decisions", "list", "--db", str(db), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload[0]["question"] is None


def test_decisions_list_db_flag(tmp_path: Path) -> None:
    """``--db`` points to a non-default DB path."""
    db = tmp_path / "custom.db"
    _seed_run(db, run_id="R99", workflow_name="custom", status="paused")
    result = runner.invoke(app, ["decisions", "list", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "R99" in result.stdout


def test_decisions_list_bulk_query_multiple_runs(tmp_path: Path) -> None:
    """Two paused runs each with a distinct question are both rendered.

    This exercises the ``IN (?, ...)`` clause and correlated ``MAX(id)``
    subquery in ``_fetch_decision_requested_events_bulk`` with more than
    one run_id — the scenario that motivated replacing the N+1 loop.
    """
    db = tmp_path / "harness.db"
    _seed_run(
        db,
        run_id="R1",
        workflow_name="build",
        status="paused",
        started_at="2026-06-01T09:00:00Z",
    )
    _seed_event(
        db,
        run_id="R1",
        event_type="decision_requested",
        data={"message": "Deploy to staging?", "display_state": []},
    )
    _seed_run(
        db,
        run_id="R2",
        workflow_name="release",
        status="paused",
        started_at="2026-06-01T10:00:00Z",
    )
    _seed_event(
        db,
        run_id="R2",
        event_type="decision_requested",
        data={"message": "Tag the release?", "display_state": []},
    )

    result = runner.invoke(app, ["decisions", "list", "--db", str(db)])

    assert result.exit_code == 0, result.output
    assert "R1" in result.stdout
    assert "Deploy to staging?" in result.stdout
    assert "R2" in result.stdout
    assert "Tag the release?" in result.stdout


def test_decisions_list_bulk_query_json_multiple_runs(tmp_path: Path) -> None:
    """``--json`` with two paused runs returns both entries with correct questions.

    Verifies the bulk event fetch returns per-run data without cross-contamination.
    """
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="A1", workflow_name="alpha", status="paused")
    _seed_event(
        db,
        run_id="A1",
        event_type="decision_requested",
        data={"message": "Approve alpha?", "display_state": []},
    )
    _seed_run(db, run_id="B2", workflow_name="beta", status="paused")
    _seed_event(
        db,
        run_id="B2",
        event_type="decision_requested",
        data={"message": "Approve beta?", "display_state": []},
    )

    result = runner.invoke(app, ["decisions", "list", "--db", str(db), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert len(payload) == 2
    by_run = {item["run_id"]: item for item in payload}
    assert by_run["A1"]["question"] == "Approve alpha?"
    assert by_run["B2"]["question"] == "Approve beta?"


# ---------------------------------------------------------------------------
# harness decision show — error cases
# ---------------------------------------------------------------------------


def test_decision_show_no_db_exits_2(tmp_path: Path) -> None:
    """DB does not exist → exits 2, message on stderr."""
    db = tmp_path / "missing.db"
    result = runner.invoke(app, ["decision", "show", "R1", "--db", str(db)])
    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    assert "R1" in result.stderr


def test_decision_show_unknown_run_exits_2(tmp_path: Path) -> None:
    """DB exists but run_id not found → exits 2, message on stderr."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="OTHER", status="paused")
    result = runner.invoke(app, ["decision", "show", "MISSING", "--db", str(db)])
    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    assert "MISSING" in result.stderr


def test_decision_show_non_paused_run_exits_2(tmp_path: Path) -> None:
    """Run exists but is not paused → exits 2, message on stderr."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="completed")
    result = runner.invoke(app, ["decision", "show", "R1", "--db", str(db)])
    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    assert "paused" in result.stderr.lower()


# ---------------------------------------------------------------------------
# harness decision show — success cases
# ---------------------------------------------------------------------------


def test_decision_show_paused_run_exits_0(tmp_path: Path) -> None:
    """Paused run → exits 0."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="paused")
    result = runner.invoke(app, ["decision", "show", "R1", "--db", str(db)])
    assert result.exit_code == 0, result.output


def test_decision_show_renders_question(tmp_path: Path) -> None:
    """The question from ``decision_requested`` event is shown."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", workflow_name="build", status="paused")
    _seed_event(
        db,
        run_id="R1",
        event_type="decision_requested",
        data={"message": "Approve the PR?", "display_state": []},
    )
    result = runner.invoke(app, ["decision", "show", "R1", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "Approve the PR?" in result.stdout
    assert "R1" in result.stdout
    assert "build" in result.stdout


def test_decision_show_renders_display_state_values(tmp_path: Path) -> None:
    """Fields listed in ``display_state`` are resolved from state_json and shown."""
    db = tmp_path / "harness.db"
    state = {"ticket": "PROJ-123", "notes": ["patch applied"], "score": 42}
    _seed_run(
        db,
        run_id="R1",
        status="paused",
        state_json=json.dumps(state),
    )
    _seed_event(
        db,
        run_id="R1",
        event_type="decision_requested",
        data={
            "message": "Merge?",
            "display_state": ["ticket", "score"],
        },
    )
    result = runner.invoke(app, ["decision", "show", "R1", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "ticket" in result.stdout
    assert "PROJ-123" in result.stdout
    assert "score" in result.stdout
    assert "42" in result.stdout
    # notes is not in display_state, should be absent
    assert "notes" not in result.stdout


def test_decision_show_json_output(tmp_path: Path) -> None:
    """``--json`` emits a single object with all required keys."""
    db = tmp_path / "harness.db"
    _seed_run(
        db,
        run_id="R1",
        workflow_name="build",
        status="paused",
        started_at="2026-06-01T10:00:00Z",
        state_json=json.dumps({"reviewer_score": 9}),
    )
    _seed_event(
        db,
        run_id="R1",
        event_type="decision_requested",
        data={
            "message": "Ship it?",
            "display_state": ["reviewer_score"],
        },
    )
    result = runner.invoke(app, ["decision", "show", "R1", "--db", str(db), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["run_id"] == "R1"
    assert payload["workflow_name"] == "build"
    assert payload["started_at"] == "2026-06-01T10:00:00Z"
    assert payload["question"] == "Ship it?"
    assert payload["display_state"] == {"reviewer_score": 9}


def test_decision_show_json_empty_display_state(tmp_path: Path) -> None:
    """``--json`` with no display_state fields emits an empty dict."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="paused")
    _seed_event(
        db,
        run_id="R1",
        event_type="decision_requested",
        data={"message": "Go?", "display_state": []},
    )
    result = runner.invoke(app, ["decision", "show", "R1", "--db", str(db), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["display_state"] == {}


def test_decision_show_json_no_event_null_question(tmp_path: Path) -> None:
    """``--json`` with no ``decision_requested`` event → ``question: null``."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="paused")
    result = runner.invoke(app, ["decision", "show", "R1", "--db", str(db), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["question"] is None
    assert payload["display_state"] == {}


def test_decision_show_db_flag(tmp_path: Path) -> None:
    """``--db`` points to a non-default DB path."""
    db = tmp_path / "alt.db"
    _seed_run(db, run_id="R42", status="paused")
    result = runner.invoke(app, ["decision", "show", "R42", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "R42" in result.stdout


# ---------------------------------------------------------------------------
# harness decision approve / reject — H-2-004 spy helpers
# ---------------------------------------------------------------------------


class _ResumeRunnerSpy:
    """Minimal Runner stand-in that records resume() calls."""

    def __init__(self, *, exit_code: int = 0) -> None:
        self._exit_code = exit_code
        self.calls: list[dict[str, Any]] = []

    async def resume(
        self,
        run_id: str,
        *,
        approved: bool,
        comment: str | None = None,
        workflows_dir: Any = None,
    ) -> int:
        self.calls.append(
            {
                "run_id": run_id,
                "approved": approved,
                "comment": comment,
                "workflows_dir": workflows_dir,
            }
        )
        return self._exit_code


# ---------------------------------------------------------------------------
# harness decision approve — error cases
# ---------------------------------------------------------------------------


def test_decision_approve_run_not_found_exits_2(tmp_path: Path) -> None:
    """Run not in DB → exit 2, run_id mentioned on stderr."""
    db = tmp_path / "harness.db"
    result = runner.invoke(
        app, ["decision", "approve", "MISSING", "--db", str(db)]
    )
    assert result.exit_code == 2
    assert "MISSING" in result.stderr


def test_decision_approve_run_not_paused_exits_2(tmp_path: Path) -> None:
    """Run exists but is not paused → exit 2, 'paused' mentioned on stderr."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="completed")
    result = runner.invoke(
        app, ["decision", "approve", "R1", "--db", str(db)]
    )
    assert result.exit_code == 2
    assert "paused" in result.stderr.lower()


# ---------------------------------------------------------------------------
# harness decision approve — success cases (spy)
# ---------------------------------------------------------------------------


def test_decision_approve_calls_resume_with_approved_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """approve calls runner.resume(approved=True, comment=None), exits 0."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="paused")

    spy = _ResumeRunnerSpy(exit_code=0)

    import harness.cli.decisions as decisions_mod

    monkeypatch.setattr(decisions_mod, "_build_decision_runner", lambda db_path: spy)

    result = runner.invoke(app, ["decision", "approve", "R1", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert len(spy.calls) == 1
    assert spy.calls[0]["approved"] is True
    assert spy.calls[0]["comment"] is None


def test_decision_approve_with_comment_passes_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--comment passed → spy captures comment value."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="paused")

    spy = _ResumeRunnerSpy(exit_code=0)

    import harness.cli.decisions as decisions_mod

    monkeypatch.setattr(decisions_mod, "_build_decision_runner", lambda db_path: spy)

    result = runner.invoke(
        app, ["decision", "approve", "R1", "--comment", "lgtm", "--db", str(db)]
    )
    assert result.exit_code == 0, result.output
    assert spy.calls[0]["comment"] == "lgtm"


def test_decision_approve_json_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--json emits JSON object with outcome='approved' and exit_code."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="paused")

    spy = _ResumeRunnerSpy(exit_code=0)

    import harness.cli.decisions as decisions_mod

    monkeypatch.setattr(decisions_mod, "_build_decision_runner", lambda db_path: spy)

    result = runner.invoke(
        app, ["decision", "approve", "R1", "--json", "--db", str(db)]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["run_id"] == "R1"
    assert payload["outcome"] == "approved"
    assert payload["exit_code"] == 0


# ---------------------------------------------------------------------------
# harness decision reject — error cases
# ---------------------------------------------------------------------------


def test_decision_reject_run_not_found_exits_2(tmp_path: Path) -> None:
    """Run not in DB → exit 2, run_id mentioned on stderr."""
    db = tmp_path / "harness.db"
    result = runner.invoke(
        app, ["decision", "reject", "MISSING", "--db", str(db)]
    )
    assert result.exit_code == 2
    assert "MISSING" in result.stderr


def test_decision_reject_run_not_paused_exits_2(tmp_path: Path) -> None:
    """Run exists but is not paused → exit 2."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="completed")
    result = runner.invoke(
        app, ["decision", "reject", "R1", "--db", str(db)]
    )
    assert result.exit_code == 2
    assert "paused" in result.stderr.lower()


# ---------------------------------------------------------------------------
# harness decision reject — success cases (spy)
# ---------------------------------------------------------------------------


def test_decision_reject_calls_resume_with_approved_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """reject calls runner.resume(approved=False), exits with runner's code."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="paused")

    spy = _ResumeRunnerSpy(exit_code=1)

    import harness.cli.decisions as decisions_mod

    monkeypatch.setattr(decisions_mod, "_build_decision_runner", lambda db_path: spy)

    result = runner.invoke(app, ["decision", "reject", "R1", "--db", str(db)])
    assert result.exit_code == 1
    assert len(spy.calls) == 1
    assert spy.calls[0]["approved"] is False


def test_decision_reject_with_comment_passes_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--comment passed to reject → spy captures comment."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="paused")

    spy = _ResumeRunnerSpy(exit_code=1)

    import harness.cli.decisions as decisions_mod

    monkeypatch.setattr(decisions_mod, "_build_decision_runner", lambda db_path: spy)

    result = runner.invoke(
        app, ["decision", "reject", "R1", "--comment", "not ready", "--db", str(db)]
    )
    assert result.exit_code == 1
    assert spy.calls[0]["comment"] == "not ready"


def test_decision_reject_json_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--json emits JSON object with outcome='rejected'."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="paused")

    spy = _ResumeRunnerSpy(exit_code=1)

    import harness.cli.decisions as decisions_mod

    monkeypatch.setattr(decisions_mod, "_build_decision_runner", lambda db_path: spy)

    result = runner.invoke(
        app, ["decision", "reject", "R1", "--json", "--db", str(db)]
    )
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["run_id"] == "R1"
    assert payload["outcome"] == "rejected"
    assert payload["exit_code"] == 1


# ---------------------------------------------------------------------------
# harness decision approve / reject — HARNESS_WORKFLOWS_DIR resolution
# ---------------------------------------------------------------------------


def test_decision_approve_respects_harness_workflows_dir_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HARNESS_WORKFLOWS_DIR is honoured when ``--workflows-dir`` is not given.

    ``decision approve`` must use the four-step resolution chain
    (``_resolve_workflows_dir``) rather than the hardcoded
    ``DEFAULT_WORKFLOWS_DIR``, so ``$HARNESS_WORKFLOWS_DIR`` wins when set.
    """
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="paused")

    env_wf_dir = tmp_path / "custom_wf"
    env_wf_dir.mkdir()
    monkeypatch.setenv("HARNESS_WORKFLOWS_DIR", str(env_wf_dir))
    monkeypatch.chdir(tmp_path)  # no ./workflows/ here — step 3 skips

    spy = _ResumeRunnerSpy(exit_code=0)

    import harness.cli.decisions as decisions_mod

    monkeypatch.setattr(decisions_mod, "_build_decision_runner", lambda db_path: spy)

    result = runner.invoke(app, ["decision", "approve", "R1", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert len(spy.calls) == 1
    assert spy.calls[0]["workflows_dir"] == env_wf_dir


def test_decision_reject_respects_harness_workflows_dir_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HARNESS_WORKFLOWS_DIR is honoured when ``--workflows-dir`` is not given.

    Parallel to the approve test — verifies both commands use the same
    resolution chain.
    """
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="paused")

    env_wf_dir = tmp_path / "custom_wf"
    env_wf_dir.mkdir()
    monkeypatch.setenv("HARNESS_WORKFLOWS_DIR", str(env_wf_dir))
    monkeypatch.chdir(tmp_path)  # no ./workflows/ here — step 3 skips

    spy = _ResumeRunnerSpy(exit_code=1)

    import harness.cli.decisions as decisions_mod

    monkeypatch.setattr(decisions_mod, "_build_decision_runner", lambda db_path: spy)

    result = runner.invoke(app, ["decision", "reject", "R1", "--db", str(db)])
    assert result.exit_code == 1
    assert len(spy.calls) == 1
    assert spy.calls[0]["workflows_dir"] == env_wf_dir


# ---------------------------------------------------------------------------
# runs.status enum recognises ``paused`` and ``stalled``.
# ---------------------------------------------------------------------------


def test_run_status_literal_includes_paused_and_stalled() -> None:
    """The type-safe view of the status enum exposes both v1.5 values."""
    from harness.state.schema import RUN_STATUSES

    assert "paused" in RUN_STATUSES
    assert "stalled" in RUN_STATUSES
    for canonical in ("pending", "running", "completed", "failed", "cancelled"):
        assert canonical in RUN_STATUSES
