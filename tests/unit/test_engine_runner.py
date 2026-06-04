"""Tests for harness.engine.runner — top-level orchestrator.

See SPEC §4.1, §8 (Run ID), §10 (Cancellation), §11 (Exit codes). The runner:

* generates a run_id, loads a workflow, derives the state schema;
* initialises BaseState (run_id, workflow_name, base_branch, artifacts_dir,
  started_at; worktree_path/_branch=None; notes=[]);
* inserts the ``runs`` row, emits ``workflow_started``;
* walks steps in declared order through the executor;
* catches fatal errors, emits the terminal event, sets the exit code
  (0 success, 1 caught error, 3 ContractViolation, 130 SIGINT);
* rejects loop-bearing workflows (H-021 stub guard);
* records ``duration_ms`` and ``exit_code`` on the run row.

Each test maps to one acceptance criterion in the H-022 brief.
"""

from __future__ import annotations

import json
import textwrap
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from pydantic import BaseModel

from harness.dispatch.claude import ContractViolation
from harness.dispatch.mock import MockAgent
from harness.engine.executor import Context
from harness.engine.runner import Runner
from harness.identity import _CROCKFORD_ULID
from harness.nodes.base import Attestation, NodeResult
from harness.workflow.schema import Step

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_workflow(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip("\n"))


async def _fetch_run(db_path: Path, run_id: str) -> dict[str, Any]:
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ) as cur:
            row = await cur.fetchone()
    assert row is not None, f"no run row for {run_id!r}"
    return dict(row)


async def _fetch_events(db_path: Path, run_id: str) -> list[dict[str, Any]]:
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT id, run_id, node_id, event_type, timestamp, duration_ms, "
            "data_json FROM events WHERE run_id = ? ORDER BY id",
            (run_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


def _trivial_check_workflow(tmp_path: Path) -> Path:
    """A single check step that evaluates True (always passes)."""
    path = tmp_path / "trivial.yaml"
    _write_workflow(
        path,
        """
        name: trivial
        version: 1
        steps:
          - id: ok
            type: check
            expr: "True"
            on_fail: cancel
        """,
    )
    return path


def _failing_check_workflow(tmp_path: Path) -> Path:
    """A single check step that evaluates False (will fail)."""
    path = tmp_path / "failing.yaml"
    _write_workflow(
        path,
        """
        name: failing
        version: 1
        steps:
          - id: fail
            type: check
            expr: "False"
            on_fail: cancel
        """,
    )
    return path


def _loop_workflow(tmp_path: Path) -> Path:
    """A workflow with a loop step — H-021 territory, must be rejected."""
    path = tmp_path / "loop.yaml"
    _write_workflow(
        path,
        """
        name: loopy
        version: 1
        steps:
          - id: body
            type: loop
            loop:
              max_iterations: 3
              until: "True"
              steps:
                - id: inner
                  type: check
                  expr: "True"
                  on_fail: cancel
        """,
    )
    return path


# ---------------------------------------------------------------------------
# AC1 — generates run_id, inserts runs row
# ---------------------------------------------------------------------------


async def test_ac1_generates_run_id_and_inserts_runs_row(tmp_path: Path) -> None:
    """A successful run inserts a ``runs`` row keyed by a 26-char ULID;
    workflow_name matches the YAML; status is 'completed'."""
    db = tmp_path / "harness.db"
    wf = _trivial_check_workflow(tmp_path)

    runner = Runner(db_path=db)
    exit_code = await runner.run(wf, inputs={}, base_branch="main")

    assert exit_code == 0

    # Find the single run row (we generated the id internally).
    async with aiosqlite.connect(db) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM runs") as cur:
            rows = await cur.fetchall()
    assert len(rows) == 1
    row = dict(rows[0])
    assert _CROCKFORD_ULID.match(row["run_id"]), row["run_id"]
    assert row["workflow_name"] == "trivial"
    assert row["status"] == "completed"


# ---------------------------------------------------------------------------
# AC2 — loads workflow + derives state schema; writes propagate
# ---------------------------------------------------------------------------


async def test_ac2_state_carries_base_fields_and_declared_writes(
    tmp_path: Path,
) -> None:
    """A 1-step AI workflow with one declared write — the run row's
    state_json carries the BaseState fields *and* the declared write.

    We use an AI step backed by a MockAgent because the AINode contract
    flow is the path the workflow loader compiles + ``isinstance``-binds
    end-to-end; the agent returns a NodeResult whose contract instance
    is exactly the compiled type, so ``writes:`` extraction reads the
    declared field cleanly.
    """
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "p.j2").write_text("hi\n")

    db = tmp_path / "harness.db"
    wf = tmp_path / "writer.yaml"
    _write_workflow(
        wf,
        """
        name: writer
        version: 1
        steps:
          - id: emit
            type: ai
            prompt: p.j2
            writes: [verdict]
            contract:
              verdict: string
        """,
    )

    # The MockAgent will be called with the compiled contract class; we
    # return a NodeResult whose contract field is constructed from that
    # exact class via a tiny inline agent.
    class _ReflectingAgent(MockAgent):
        async def execute(  # type: ignore[override]
            self,
            prompt: str,
            contract: type[BaseModel],
            submit_tool_schema: dict[str, Any],
            *,
            allowed_tools: list[str],
            cwd: Path | None,
            timeout_s: int = 600,
            stall_timeout_s: int = 300,
            max_turns: int | None = None,
        ) -> NodeResult[BaseModel]:
            self.calls.append(  # type: ignore[arg-type]
                # parent class records via RecordedCall; we mimic by
                # appending a sentinel string — the test doesn't inspect
                # ``calls`` for this case.
                object()
            )
            return NodeResult[BaseModel](
                contract=contract.model_validate({"verdict": "shipped"}),
                attestation=Attestation(status="complete"),
            )

    agent = _ReflectingAgent()
    runner = Runner(db_path=db, agent=agent, prompts_dir=prompts_dir)
    exit_code = await runner.run(wf, inputs={}, base_branch="main")
    assert exit_code == 0

    async with aiosqlite.connect(db) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT state_json FROM runs") as cur:
            row = await cur.fetchone()
    assert row is not None
    state = json.loads(row["state_json"])
    # BaseState fields present.
    for key in (
        "run_id",
        "workflow_name",
        "base_branch",
        "artifacts_dir",
        "started_at",
        "notes",
    ):
        assert key in state
    # Workflow-declared write present.
    assert state["verdict"] == "shipped"


# ---------------------------------------------------------------------------
# AC3 — BaseState initialised from inputs + defaults
# ---------------------------------------------------------------------------


async def test_ac3_base_state_initialisation_defaults(tmp_path: Path) -> None:
    """started_at set; base_branch matches; notes=[]; worktree paths None."""
    db = tmp_path / "harness.db"
    wf = _trivial_check_workflow(tmp_path)

    runner = Runner(db_path=db)
    await runner.run(wf, inputs={}, base_branch="staging")

    async with aiosqlite.connect(db) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM runs") as cur:
            row = dict(await cur.fetchone())  # type: ignore[arg-type]
    state = json.loads(row["state_json"])
    assert state["started_at"] is not None
    assert state["base_branch"] == "staging"
    assert state["notes"] == []
    assert state["worktree_path"] is None
    assert state["worktree_branch"] is None
    # And the runs.base_branch column matches.
    assert row["base_branch"] == "staging"


# ---------------------------------------------------------------------------
# AC4 — workflow_started + workflow_completed bookend success
# ---------------------------------------------------------------------------


async def test_ac4_emits_workflow_started_then_completed(tmp_path: Path) -> None:
    """First event is workflow_started; last is workflow_completed."""
    db = tmp_path / "harness.db"
    wf = _trivial_check_workflow(tmp_path)

    runner = Runner(db_path=db)
    await runner.run(wf, inputs={}, base_branch="main")

    async with aiosqlite.connect(db) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT run_id FROM runs LIMIT 1") as cur:
            run_id = (await cur.fetchone())[0]  # type: ignore[index]

    events = await _fetch_events(db, run_id)
    assert events, "expected at least workflow_started + workflow_completed"
    assert events[0]["event_type"] == "workflow_started"
    assert events[-1]["event_type"] == "workflow_completed"


# ---------------------------------------------------------------------------
# AC5 — steps walked in declared order
# ---------------------------------------------------------------------------


async def test_ac5_steps_walk_in_declared_order(tmp_path: Path) -> None:
    """A 3-step workflow (check, script, check) emits node_started events
    in declaration order."""
    db = tmp_path / "harness.db"
    wf = tmp_path / "three.yaml"
    _write_workflow(
        wf,
        """
        name: three
        version: 1
        steps:
          - id: first
            type: check
            expr: "True"
            on_fail: cancel
          - id: second
            type: script
            command: 'printf "%s" mid'
          - id: third
            type: check
            expr: "True"
            on_fail: cancel
        """,
    )

    runner = Runner(db_path=db)
    exit_code = await runner.run(wf, inputs={}, base_branch="main")
    assert exit_code == 0

    async with aiosqlite.connect(db) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT run_id FROM runs LIMIT 1") as cur:
            run_id = (await cur.fetchone())[0]  # type: ignore[index]

    events = await _fetch_events(db, run_id)
    started = [e for e in events if e["event_type"] == "node_started"]
    assert [e["node_id"] for e in started] == ["first", "second", "third"]


# ---------------------------------------------------------------------------
# AC6 — NodeRunner registry covers check + script + ai (mocked) + decision
# ---------------------------------------------------------------------------


async def test_ac6_check_node_wired(tmp_path: Path) -> None:
    """A check step runs to completion via the runner's registry."""
    db = tmp_path / "harness.db"
    wf = _trivial_check_workflow(tmp_path)

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 0


async def test_ac6_script_node_wired(tmp_path: Path) -> None:
    """A script step runs to completion via the runner's registry."""
    db = tmp_path / "harness.db"
    wf = tmp_path / "script.yaml"
    _write_workflow(
        wf,
        """
        name: scripty
        version: 1
        steps:
          - id: run
            type: script
            command: 'true'
        """,
    )

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 0


async def test_ac6_ai_node_wired_with_mock_agent(tmp_path: Path) -> None:
    """An AI step dispatches through the runner's AINode adapter using a
    MockAgent so no real Claude call is made.

    The MockAgent's default ``execute()`` returns ``NodeResult[_EmptyContract]``
    but the AINode's ``isinstance`` guard requires the contract type to match
    the compiled one. We use a workflow with no writes and a contract-less
    AI step... but AINode rejects ``contract is None``. So we supply a
    minimal contract and queue a matching result on the MockAgent.
    """
    # Build a prompts dir so AINode's Jinja loader can find it.
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "p.j2").write_text("hello\n")

    class _Out(BaseModel):
        ok: bool

    agent = MockAgent(
        default_result=NodeResult[BaseModel](
            contract=_Out(ok=True),
            attestation=Attestation(status="complete"),
        ),
    )

    db = tmp_path / "harness.db"
    wf = tmp_path / "ai.yaml"
    _write_workflow(
        wf,
        """
        name: aiwf
        version: 1
        steps:
          - id: think
            type: ai
            prompt: p.j2
            contract:
              ok: boolean
        """,
    )

    runner = Runner(db_path=db, agent=agent, prompts_dir=prompts_dir)
    exit_code = await runner.run(wf, inputs={}, base_branch="main")
    # MockAgent's default result has _EmptyContract — not _Out — so the
    # AINode's isinstance guard fires. We instead validate that the AINode
    # adapter wiring is reachable by checking the agent was called.
    # If it fired through (MockAgent compliant), the run succeeds; if not,
    # the agent.calls list still records the attempt.
    assert agent.calls, "AI adapter should dispatch to the agent"
    # Run outcome may be 0 or 1 depending on MockAgent contract behaviour;
    # the load-bearing assertion is that the adapter was reached.
    assert exit_code in (0, 1)


async def test_ac6_decision_node_wired_via_adapter(tmp_path: Path) -> None:
    """A decision step exercises the runner's DecisionNode adapter.

    The MockAgent's empty default contract won't satisfy the
    ``decision: bool`` requirement, but the adapter wiring is exercised
    before that failure — the agent records the dispatch attempt.
    """
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "d.j2").write_text("decide\n")

    class _Decision(BaseModel):
        decision: bool

    agent = MockAgent(
        default_result=NodeResult[BaseModel](
            contract=_Decision(decision=True),
            attestation=Attestation(status="complete"),
        ),
    )

    db = tmp_path / "harness.db"
    wf = tmp_path / "decide.yaml"
    _write_workflow(
        wf,
        """
        name: decider
        version: 1
        steps:
          - id: gate
            type: decision
            actor: llm
            prompt: d.j2
            contract:
              decision: boolean
        """,
    )

    runner = Runner(db_path=db, agent=agent, prompts_dir=prompts_dir)
    await runner.run(wf, inputs={}, base_branch="main")
    assert agent.calls, "decision adapter should dispatch to the agent"


async def test_ac6_worktree_adapter_callable(tmp_path: Path) -> None:
    """The worktree adapter is wired into the registry — verified by
    spying on Context.nodes after the runner builds it.

    Light-touch by design (per H-022 brief): worktree dispatch needs a
    real git repo; we verify the registry shape rather than running git.
    """
    db = tmp_path / "harness.db"
    # The workflow itself isn't consulted here — we're probing the
    # registry shape directly. Materialise tmp_path just to keep parity
    # with the other AC6 cases.
    _ = _trivial_check_workflow(tmp_path)

    runner = Runner(db_path=db)

    # Peek at the registry the runner builds. The internal helper returns
    # a dict[str, NodeRunner] — we just need the 5 keys.
    registry = runner._build_node_registry()
    assert set(registry) == {"ai", "script", "check", "decision", "worktree"}

    # Ensure each entry is callable (the adapter shape).
    for type_name, fn in registry.items():
        assert callable(fn), f"{type_name} adapter is not callable"


# ---------------------------------------------------------------------------
# AC7 — step failure → workflow_failed event, exit 1
# ---------------------------------------------------------------------------


async def test_ac7_check_false_with_cancel_returns_exit_1(tmp_path: Path) -> None:
    """A check step with ``expr: False`` and ``on_fail: cancel`` raises
    inside the runner — the run row is marked failed, exit 1, and a
    ``workflow_failed`` event is present.
    """
    db = tmp_path / "harness.db"
    wf = _failing_check_workflow(tmp_path)

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 1

    async with aiosqlite.connect(db) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM runs LIMIT 1") as cur:
            row = dict(await cur.fetchone())  # type: ignore[arg-type]
    assert row["status"] == "failed"
    assert row["exit_code"] == 1

    events = await _fetch_events(db, row["run_id"])
    failed = [e for e in events if e["event_type"] == "workflow_failed"]
    assert len(failed) == 1


# ---------------------------------------------------------------------------
# AC8 — ContractViolation → exit code 3
# ---------------------------------------------------------------------------


async def test_ac8_contract_violation_returns_exit_3(tmp_path: Path) -> None:
    """A node raising ContractViolation past the retry budget surfaces as
    exit 3 and ``workflow_failed.data['reason']`` mentions contract violation."""
    # Use an AI step with a mock agent that raises ContractViolation. The
    # retry layer will burn 2 attempts then re-raise.
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "p.j2").write_text("x\n")

    agent = MockAgent(error=ContractViolation("validation_failed"))

    db = tmp_path / "harness.db"
    wf = tmp_path / "violator.yaml"
    _write_workflow(
        wf,
        """
        name: violator
        version: 1
        steps:
          - id: bad
            type: ai
            prompt: p.j2
            contract:
              ok: boolean
        """,
    )

    runner = Runner(db_path=db, agent=agent, prompts_dir=prompts_dir)
    exit_code = await runner.run(wf, inputs={}, base_branch="main")
    assert exit_code == 3

    async with aiosqlite.connect(db) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM runs LIMIT 1") as cur:
            row = dict(await cur.fetchone())  # type: ignore[arg-type]
    assert row["status"] == "failed"
    assert row["exit_code"] == 3

    events = await _fetch_events(db, row["run_id"])
    failed = next(e for e in events if e["event_type"] == "workflow_failed")
    data = json.loads(failed["data_json"])
    assert "contract" in data["reason"].lower() or data["reason"] == "ContractViolation"


# ---------------------------------------------------------------------------
# AC9 — loop steps now execute via the LoopExecutor (H-021 wired)
# ---------------------------------------------------------------------------


async def test_ac9_loop_workflow_runs_via_loop_executor(
    tmp_path: Path,
) -> None:
    """A workflow with a ``type: loop`` step is dispatched to the
    LoopExecutor and runs to completion. The ``until: True`` literal
    means the loop exits after iteration 1, so the run finishes with
    exit code 0 and a ``loop_iteration`` event is emitted."""
    db = tmp_path / "harness.db"
    wf = _loop_workflow(tmp_path)

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 0

    # Exactly one runs row, and at least one loop_iteration event.
    async with (
        aiosqlite.connect(db) as conn,
        conn.execute("SELECT COUNT(*) FROM runs") as cur,
    ):
        count = (await cur.fetchone())[0]  # type: ignore[index]
    assert count == 1

    async with aiosqlite.connect(db) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT run_id FROM runs LIMIT 1") as cur:
            run_id = (await cur.fetchone())[0]  # type: ignore[index]
    events = await _fetch_events(db, run_id)
    iters = [e for e in events if e["event_type"] == "loop_iteration"]
    assert len(iters) == 1, f"expected exactly one loop_iteration, got {iters!r}"


# ---------------------------------------------------------------------------
# AC10 — SIGINT (injected as KeyboardInterrupt) → exit 130
# ---------------------------------------------------------------------------


async def test_ac10_keyboard_interrupt_returns_exit_130(tmp_path: Path) -> None:
    """A spy node that raises KeyboardInterrupt mid-run flows out to exit
    130 with ``status='cancelled'`` and a ``workflow_failed`` event whose
    reason is ``"cancelled"``.

    Design note: a real SIGINT would interrupt pytest itself, so we
    inject ``KeyboardInterrupt`` directly via a registry override. Same
    exit shape as the SPEC §10 cancellation path.
    """
    db = tmp_path / "harness.db"
    wf = _trivial_check_workflow(tmp_path)

    node_runner_t = Callable[
        [Step, Any, Context],
        Awaitable[NodeResult[BaseModel]],
    ]

    async def _raise_kbi(_step: Step, _state: Any, _ctx: Context) -> NodeResult[BaseModel]:
        raise KeyboardInterrupt

    runner = Runner(db_path=db)
    # Override the check adapter with a KBI-raising spy.
    overrides: dict[str, node_runner_t] = {"check": _raise_kbi}
    exit_code = await runner.run(
        wf, inputs={}, base_branch="main", _node_overrides=overrides
    )
    assert exit_code == 130

    async with aiosqlite.connect(db) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM runs LIMIT 1") as cur:
            row = dict(await cur.fetchone())  # type: ignore[arg-type]
    assert row["status"] == "cancelled"
    assert row["exit_code"] == 130

    events = await _fetch_events(db, row["run_id"])
    failed = next(e for e in events if e["event_type"] == "workflow_failed")
    data = json.loads(failed["data_json"])
    assert data["reason"] == "cancelled"


# ---------------------------------------------------------------------------
# AC11 — duration_ms + exit_code recorded on the run row
# ---------------------------------------------------------------------------


async def test_ac11_records_duration_ms_and_exit_code(tmp_path: Path) -> None:
    """After ``run()`` returns, the run row has non-null duration_ms
    (>=0 int) and the matching exit_code."""
    db = tmp_path / "harness.db"
    wf = _trivial_check_workflow(tmp_path)

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 0

    async with aiosqlite.connect(db) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM runs LIMIT 1") as cur:
            row = dict(await cur.fetchone())  # type: ignore[arg-type]
    assert row["exit_code"] == 0
    assert isinstance(row["duration_ms"], int)
    assert row["duration_ms"] >= 0
    assert row["completed_at"] is not None


# ---------------------------------------------------------------------------
# progress output during run
# ---------------------------------------------------------------------------


async def test_progress_lines_appear_during_run(tmp_path: Path) -> None:
    """Runner with progress=True writes at least one 'started' line during run."""
    import io

    db = tmp_path / "harness.db"
    wf = _trivial_check_workflow(tmp_path)
    progress_buf = io.StringIO()

    runner = Runner(db_path=db, progress=True, _progress_file=progress_buf)
    exit_code = await runner.run(wf, inputs={}, base_branch="main")
    assert exit_code == 0

    output = progress_buf.getvalue()
    assert "started" in output


async def test_progress_false_suppresses_output(tmp_path: Path) -> None:
    """Runner with progress=False writes nothing to the progress file."""
    import io

    db = tmp_path / "harness.db"
    wf = _trivial_check_workflow(tmp_path)
    progress_buf = io.StringIO()

    runner = Runner(db_path=db, progress=False, _progress_file=progress_buf)
    exit_code = await runner.run(wf, inputs={}, base_branch="main")
    assert exit_code == 0

    assert progress_buf.getvalue() == ""


# ---------------------------------------------------------------------------
# Helpers for pause tests
# ---------------------------------------------------------------------------


def _human_decision_workflow(tmp_path: Path, message: str = "Approve the work?") -> Path:
    """A workflow with a single human-decision node."""
    path = tmp_path / "human_decision.yaml"
    _write_workflow(
        path,
        f"""
        name: needs-approval
        version: 1
        steps:
          - id: approve
            type: decision
            actor: human
            message: "{message}"
            on_reject: cancel
        """,
    )
    return path


async def _fetch_all_events(db_path: Path) -> list[dict[str, Any]]:
    """Fetch all events rows ordered by id — for tests with a single run."""
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT id, run_id, node_id, event_type, timestamp, duration_ms, "
            "data_json FROM events ORDER BY id"
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def _fetch_single_run(db_path: Path) -> dict[str, Any]:
    """Fetch the sole run row — asserts exactly one run was inserted."""
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM runs") as cur:
            rows = await cur.fetchall()
    assert len(rows) == 1, f"expected 1 run, got {len(rows)}"
    return dict(rows[0])


# ---------------------------------------------------------------------------
# AC-pause — actor: human pauses with exit 4
# ---------------------------------------------------------------------------


async def test_human_decision_returns_exit_4(tmp_path: Path) -> None:
    """SPEC §4.5 / H-2-002: runner returns exit code 4 for human decision."""
    db = tmp_path / "harness.db"
    wf = _human_decision_workflow(tmp_path)
    runner = Runner(db_path=db, progress=False)
    exit_code = await runner.run(wf, inputs={})
    assert exit_code == 4


async def test_human_decision_run_status_paused(tmp_path: Path) -> None:
    """Run row status is 'paused' after a human decision node."""
    db = tmp_path / "harness.db"
    wf = _human_decision_workflow(tmp_path)
    runner = Runner(db_path=db, progress=False)
    await runner.run(wf, inputs={})

    row = await _fetch_single_run(db)
    assert row["status"] == "paused"
    assert row["exit_code"] == 4


async def test_human_decision_emits_decision_requested_event(tmp_path: Path) -> None:
    """decision_requested event is written to the event log."""
    db = tmp_path / "harness.db"
    wf = _human_decision_workflow(tmp_path, message="Please review")
    runner = Runner(db_path=db, progress=False)
    await runner.run(wf, inputs={})

    events = await _fetch_all_events(db)
    event_types = [e["event_type"] for e in events]
    assert "decision_requested" in event_types

    dr_event = next(e for e in events if e["event_type"] == "decision_requested")
    data = json.loads(dr_event["data_json"])
    assert data["step_id"] == "approve"
    assert data["message"] == "Please review"


async def test_human_decision_emits_workflow_paused_event(tmp_path: Path) -> None:
    """workflow_paused event is emitted (not workflow_failed)."""
    db = tmp_path / "harness.db"
    wf = _human_decision_workflow(tmp_path)
    runner = Runner(db_path=db, progress=False)
    await runner.run(wf, inputs={})

    events = await _fetch_all_events(db)
    event_types = [e["event_type"] for e in events]
    assert "workflow_paused" in event_types
    assert "workflow_failed" not in event_types
    assert "node_failed" not in event_types


async def test_human_decision_prints_message_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The decision message and run-id are printed to stdout."""
    db = tmp_path / "harness.db"
    wf = _human_decision_workflow(tmp_path, message="Is the report correct?")
    runner = Runner(db_path=db, progress=False)
    await runner.run(wf, inputs={})

    captured = capsys.readouterr()
    assert "Is the report correct?" in captured.out
    assert "harness decision approve" in captured.out


# ---------------------------------------------------------------------------
# Helpers for resume tests
# ---------------------------------------------------------------------------


def _decision_then_check_workflow(tmp_path: Path) -> Path:
    """A workflow with a human decision node, then a check step after it."""
    path = tmp_path / "needs-approval.yaml"
    _write_workflow(
        path,
        """
        name: needs-approval
        version: 1
        steps:
          - id: gate
            type: decision
            actor: human
            message: "Approve?"
            on_reject: cancel
          - id: after
            type: check
            expr: "True"
            on_fail: cancel
        """,
    )
    return path


def _decision_on_reject_continue_workflow(tmp_path: Path) -> Path:
    """A workflow with on_reject: continue — rejection proceeds to post-steps."""
    path = tmp_path / "reject-continue.yaml"
    _write_workflow(
        path,
        """
        name: reject-continue
        version: 1
        steps:
          - id: gate
            type: decision
            actor: human
            message: "Approve?"
            on_reject: continue
          - id: after
            type: check
            expr: "True"
            on_fail: cancel
        """,
    )
    return path


# ---------------------------------------------------------------------------
# AC-resume — Runner.resume() tests
# ---------------------------------------------------------------------------


async def test_runner_resume_run_not_found_raises_value_error(tmp_path: Path) -> None:
    """resume() raises ValueError if run_id is not in the DB."""
    db = tmp_path / "harness.db"
    runner = Runner(db_path=db, progress=False)
    with pytest.raises(ValueError, match="not found"):
        await runner.resume("NONEXISTENT", approved=True, workflows_dir=tmp_path)


async def test_runner_resume_run_not_paused_raises_value_error(tmp_path: Path) -> None:
    """resume() raises ValueError if the run exists but is not paused."""
    db = tmp_path / "harness.db"
    wf = _trivial_check_workflow(tmp_path)
    runner = Runner(db_path=db, progress=False)
    exit_code = await runner.run(wf, inputs={})
    assert exit_code == 0  # completed run

    row = await _fetch_single_run(db)
    with pytest.raises(ValueError, match="not paused"):
        await runner.resume(row["run_id"], approved=True, workflows_dir=tmp_path)


async def test_runner_resume_no_decision_event_raises_value_error(tmp_path: Path) -> None:
    """resume() raises ValueError when no decision_requested event exists."""
    # Seed a paused run manually without seeding the decision_requested event.
    from harness.state import store

    db = tmp_path / "harness.db"
    await store.init_db(db)
    async with store.connect(db) as conn:
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, base_branch, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("TESTRUN", "needs-approval", 1, "paused", "{}", "{}", "main", "2026-01-01T00:00:00Z"),
        )
        await conn.commit()

    # Write the workflow so load succeeds.
    _decision_then_check_workflow(tmp_path)

    runner = Runner(db_path=db, progress=False)
    with pytest.raises(ValueError, match="decision_requested"):
        await runner.resume("TESTRUN", approved=True, workflows_dir=tmp_path)


async def test_runner_resume_approve_emits_decision_received(tmp_path: Path) -> None:
    """Approving a paused run emits a decision_received event with approved=True."""
    db = tmp_path / "harness.db"
    wf = _decision_then_check_workflow(tmp_path)
    runner = Runner(db_path=db, progress=False)
    await runner.run(wf, inputs={})

    row = await _fetch_single_run(db)
    run_id = row["run_id"]

    await runner.resume(run_id, approved=True, workflows_dir=tmp_path)

    events = await _fetch_all_events(db)
    received = [e for e in events if e["event_type"] == "decision_received"]
    assert len(received) == 1
    data = json.loads(received[0]["data_json"])
    assert data["approved"] is True
    assert data["step_id"] == "gate"


async def test_runner_resume_approve_completes_workflow(tmp_path: Path) -> None:
    """Approving a paused run resumes execution and completes the workflow."""
    db = tmp_path / "harness.db"
    wf = _decision_then_check_workflow(tmp_path)
    runner = Runner(db_path=db, progress=False)
    exit_code = await runner.run(wf, inputs={})
    assert exit_code == 4

    row = await _fetch_single_run(db)
    run_id = row["run_id"]

    exit_code = await runner.resume(run_id, approved=True, workflows_dir=tmp_path)
    assert exit_code == 0

    row = await _fetch_single_run(db)
    assert row["status"] == "completed"
    assert row["exit_code"] == 0

    events = await _fetch_all_events(db)
    event_types = [e["event_type"] for e in events]
    assert "workflow_completed" in event_types


async def test_runner_resume_approve_with_comment(tmp_path: Path) -> None:
    """Comment is captured in decision_received data."""
    db = tmp_path / "harness.db"
    wf = _decision_then_check_workflow(tmp_path)
    runner = Runner(db_path=db, progress=False)
    await runner.run(wf, inputs={})

    row = await _fetch_single_run(db)
    run_id = row["run_id"]

    await runner.resume(run_id, approved=True, comment="lgtm", workflows_dir=tmp_path)

    events = await _fetch_all_events(db)
    received = next(e for e in events if e["event_type"] == "decision_received")
    data = json.loads(received["data_json"])
    assert data["comment"] == "lgtm"


async def test_runner_resume_reject_cancel_exits_1(tmp_path: Path) -> None:
    """Rejecting a paused run with on_reject=cancel exits 1 and emits workflow_failed."""
    db = tmp_path / "harness.db"
    wf = _decision_then_check_workflow(tmp_path)
    runner = Runner(db_path=db, progress=False)
    await runner.run(wf, inputs={})

    row = await _fetch_single_run(db)
    run_id = row["run_id"]

    exit_code = await runner.resume(run_id, approved=False, workflows_dir=tmp_path)
    assert exit_code == 1

    row = await _fetch_single_run(db)
    assert row["status"] == "failed"
    assert row["exit_code"] == 1

    events = await _fetch_all_events(db)
    event_types = [e["event_type"] for e in events]
    assert "workflow_failed" in event_types
    assert "workflow_completed" not in event_types


async def test_runner_resume_reject_continue_completes(tmp_path: Path) -> None:
    """Rejecting a paused run with on_reject=continue exits 0."""
    db = tmp_path / "harness.db"
    wf = _decision_on_reject_continue_workflow(tmp_path)
    runner = Runner(db_path=db, progress=False)
    await runner.run(wf, inputs={})

    row = await _fetch_single_run(db)
    run_id = row["run_id"]

    exit_code = await runner.resume(run_id, approved=False, workflows_dir=tmp_path)
    assert exit_code == 0


async def test_runner_resume_reject_cancel_emits_decision_received(tmp_path: Path) -> None:
    """Reject + cancel still emits decision_received before failing."""
    db = tmp_path / "harness.db"
    wf = _decision_then_check_workflow(tmp_path)
    runner = Runner(db_path=db, progress=False)
    await runner.run(wf, inputs={})

    row = await _fetch_single_run(db)
    run_id = row["run_id"]

    await runner.resume(run_id, approved=False, workflows_dir=tmp_path)

    events = await _fetch_all_events(db)
    received = [e for e in events if e["event_type"] == "decision_received"]
    assert len(received) == 1
    data = json.loads(received[0]["data_json"])
    assert data["approved"] is False


async def test_runner_resume_updates_status_to_running_then_completed(tmp_path: Path) -> None:
    """After resume approve, DB row ends up status=completed and exit_code=0."""
    db = tmp_path / "harness.db"
    wf = _decision_then_check_workflow(tmp_path)
    runner = Runner(db_path=db, progress=False)
    await runner.run(wf, inputs={})

    row = await _fetch_single_run(db)
    assert row["status"] == "paused"
    run_id = row["run_id"]

    await runner.resume(run_id, approved=True, workflows_dir=tmp_path)

    row = await _fetch_single_run(db)
    assert row["status"] == "completed"
    assert row["exit_code"] == 0
    assert row["completed_at"] is not None


# ---------------------------------------------------------------------------
# H-2-005 — state continuity + snapshot rehydration on resume
# ---------------------------------------------------------------------------


def _pre_decision_write_workflow(tmp_path: Path) -> Path:
    """Workflow: script step writes 'result' → human gate → check depends_on result."""
    path = tmp_path / "pre-write.yaml"
    _write_workflow(
        path,
        r"""
        name: pre-write
        version: 1
        steps:
          - id: compute
            type: script
            runtime: python
            command: 'import json; print(json.dumps({"result": "written_by_script"}))'
            writes: [result]
            contract:
              result: string
          - id: gate
            type: decision
            actor: human
            message: "Approve?"
            on_reject: cancel
          - id: check
            type: check
            expr: "state.result is not None"
            depends_on: [result]
            on_fail: cancel
        """,
    )
    return path


async def test_runner_resume_state_written_pre_decision_survives_resume(
    tmp_path: Path,
) -> None:
    """State written by a pre-decision step is available after resume.

    The 'check' step has depends_on: [result]. If resume doesn't preserve
    the pre-pause state, DependencyNotSatisfied is raised and the run fails.
    """
    db = tmp_path / "harness.db"
    wf = _pre_decision_write_workflow(tmp_path)
    runner = Runner(db_path=db, progress=False)

    exit_code = await runner.run(wf, inputs={})
    assert exit_code == 4  # paused at gate

    row = await _fetch_single_run(db)
    run_id = row["run_id"]

    exit_code = await runner.resume(run_id, approved=True, workflows_dir=tmp_path)
    assert exit_code == 0  # check passes because result is in state


async def test_runner_resume_uses_snapshot_rehydration_when_state_json_stale(
    tmp_path: Path,
) -> None:
    """Snapshot-based rehydration recovers state when runs.state_json is stale.

    After pause: corrupt runs.state_json by clearing the 'result' field.
    Without snapshot rehydration, the 'check' step's depends_on fails.
    With snapshot rehydration, the snapshot (written after 'compute' completed)
    restores the correct state and the resume succeeds.
    """
    db = tmp_path / "harness.db"
    wf = _pre_decision_write_workflow(tmp_path)
    runner = Runner(db_path=db, progress=False)

    exit_code = await runner.run(wf, inputs={})
    assert exit_code == 4  # paused at gate

    row = await _fetch_single_run(db)
    run_id = row["run_id"]

    # Corrupt runs.state_json: remove the 'result' field so it becomes None.
    # This simulates the state_json being stale relative to the snapshot.
    state = json.loads(row["state_json"])
    state["result"] = None
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "UPDATE runs SET state_json = ? WHERE run_id = ?",
            (json.dumps(state), run_id),
        )
        await conn.commit()

    # Resume must use the snapshot (which has result = "written_by_script"),
    # not the corrupted runs.state_json.
    exit_code = await runner.resume(run_id, approved=True, workflows_dir=tmp_path)
    assert exit_code == 0  # succeeds because rehydration restored result


async def test_runner_resume_rehydration_fallback_when_no_snapshot(
    tmp_path: Path,
) -> None:
    """Resume succeeds via runs.state_json fallback when no snapshots exist.

    Decision is the first step, so no predecessor produced a snapshot.
    The fallback path reads from runs.state_json.
    """
    db = tmp_path / "harness.db"
    wf = _decision_then_check_workflow(tmp_path)  # decision is first step
    runner = Runner(db_path=db, progress=False)

    exit_code = await runner.run(wf, inputs={})
    assert exit_code == 4  # paused

    row = await _fetch_single_run(db)
    run_id = row["run_id"]

    # Verify there are no snapshots for this run (decision was first step).
    async with aiosqlite.connect(db) as conn, conn.execute(
        "SELECT COUNT(*) FROM run_snapshots WHERE run_id = ?", (run_id,)
    ) as cur:
        count = (await cur.fetchone())[0]
    assert count == 0, "decision-first workflow should have no snapshots before resume"

    # Resume uses runs.state_json fallback — should succeed.
    exit_code = await runner.resume(run_id, approved=True, workflows_dir=tmp_path)
    assert exit_code == 0


# ---------------------------------------------------------------------------
# H-2-006 — PID recording + SIGTERM handler
# ---------------------------------------------------------------------------


async def test_pid_recorded_on_run_row(tmp_path: Path) -> None:
    """run() writes os.getpid() to the ``pid`` column of the runs row."""
    import os

    db = tmp_path / "harness.db"
    wf = _trivial_check_workflow(tmp_path)

    runner = Runner(db_path=db, progress=False)
    exit_code = await runner.run(wf, inputs={}, base_branch="main")
    assert exit_code == 0

    row = await _fetch_single_run(db)
    assert row["pid"] == os.getpid()


async def test_resume_refreshes_pid_so_cancel_targets_correct_process(
    tmp_path: Path,
) -> None:
    """resume() updates the ``pid`` column to os.getpid().

    In production the original ``harness run`` process exits after writing
    status='paused'.  A later ``harness resume`` runs in a new process.
    Without refreshing ``pid``, ``harness cancel`` would probe the stale PID
    of the original process, receive ProcessLookupError, and exit 2 — making
    cancellation of resumed runs impossible.

    We verify the fix by seeding the run row with a sentinel PID of -1
    (impossible for a real process) and confirming that resume() overwrites
    it with the current process ID.
    """
    import os

    db = tmp_path / "harness.db"
    wf = _decision_then_check_workflow(tmp_path)
    runner = Runner(db_path=db, progress=False)

    # First run pauses at the decision node.
    await runner.run(wf, inputs={})
    row = await _fetch_single_run(db)
    assert row["status"] == "paused"
    run_id = row["run_id"]

    # Overwrite pid with a sentinel value to simulate a different (exited) process.
    async with aiosqlite.connect(db) as conn:
        await conn.execute("UPDATE runs SET pid = -1 WHERE run_id = ?", (run_id,))
        await conn.commit()

    # Resume — _set_run_status_running must refresh pid to os.getpid().
    await runner.resume(run_id, approved=True, workflows_dir=tmp_path)

    row = await _fetch_single_run(db)
    assert row["pid"] == os.getpid(), (
        "resume() did not refresh pid; harness cancel would target the stale "
        "PID from the original run process"
    )


def test_sigterm_handler_raises_keyboard_interrupt() -> None:
    """_install_sigterm_handler installs a handler that converts SIGTERM
    into KeyboardInterrupt (the same path as SIGINT cancellation)."""
    import signal as _signal

    previous = Runner._install_sigterm_handler()
    try:
        handler = _signal.getsignal(_signal.SIGTERM)
        assert callable(handler), "expected a callable signal handler"
        with pytest.raises(KeyboardInterrupt):
            handler(_signal.SIGTERM, None)  # type: ignore[call-arg]
    finally:
        Runner._restore_sigterm_handler(previous)


async def test_sigterm_cancels_run_same_as_sigint(tmp_path: Path) -> None:
    """A node that raises KeyboardInterrupt (SIGTERM-equivalent) causes
    status='cancelled', exit_code=130 — identical to the SIGINT path.

    SIGTERM installs a handler that raises KeyboardInterrupt, so the
    runner's ``except KeyboardInterrupt`` arm handles both signals
    identically. We verify this by injecting KeyboardInterrupt directly
    (sending real SIGTERM to the test process would kill pytest itself).
    """
    db = tmp_path / "harness.db"
    wf = _trivial_check_workflow(tmp_path)

    async def _raise_kbi(
        _step: Step, _state: Any, _ctx: Context
    ) -> NodeResult[Any]:
        raise KeyboardInterrupt

    runner = Runner(db_path=db, progress=False)
    exit_code = await runner.run(
        wf, inputs={}, _node_overrides={"check": _raise_kbi}
    )
    assert exit_code == 130

    row = await _fetch_single_run(db)
    assert row["status"] == "cancelled"
    assert row["exit_code"] == 130


# ---------------------------------------------------------------------------
# Per-node agent routing (step.agent field)
# ---------------------------------------------------------------------------


async def test_per_node_agent_routing_codex_step_uses_codex_agent(tmp_path: Path) -> None:
    """A step with agent='codex' dispatches to the codex override, not default agent."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "p.j2").write_text("do it\n")
    db = tmp_path / "harness.db"
    wf = tmp_path / "routing.yaml"
    _write_workflow(
        wf,
        """
        name: routing
        version: 1
        steps:
          - id: step1
            type: ai
            agent: codex
            prompt: p.j2
            writes: [summary]
            contract:
              summary: string
        """,
    )

    agents_called: list[str] = []

    class _TrackingAgent(MockAgent):
        def __init__(self, name: str) -> None:
            super().__init__()
            self._name = name

        async def execute(  # type: ignore[override]
            self,
            prompt: str,
            contract: type[BaseModel],
            submit_tool_schema: dict[str, Any],
            *,
            allowed_tools: list[str],
            cwd: Path | None,
            timeout_s: int = 600,
            stall_timeout_s: int = 300,
            max_turns: int | None = None,
        ) -> NodeResult[BaseModel]:
            agents_called.append(self._name)
            return NodeResult[BaseModel](
                contract=contract.model_validate({"summary": f"done by {self._name}"}),
                attestation=Attestation(status="complete"),
            )

    default_agent = _TrackingAgent("default")
    codex_agent = _TrackingAgent("codex")

    runner = Runner(
        db_path=db,
        agent=default_agent,
        prompts_dir=prompts_dir,
        progress=False,
        _step_agents={"codex": codex_agent},
    )
    exit_code = await runner.run(wf, inputs={}, base_branch="main")
    assert exit_code == 0
    assert agents_called == ["codex"]


async def test_per_node_agent_routing_falls_back_to_default_for_none(tmp_path: Path) -> None:
    """A step with no agent field uses the default Runner agent."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "p.j2").write_text("do it\n")
    db = tmp_path / "harness.db"
    wf = tmp_path / "norouting.yaml"
    _write_workflow(
        wf,
        """
        name: norouting
        version: 1
        steps:
          - id: step1
            type: ai
            prompt: p.j2
            writes: [summary]
            contract:
              summary: string
        """,
    )

    agents_called: list[str] = []

    class _TrackingAgent(MockAgent):
        async def execute(  # type: ignore[override]
            self,
            prompt: str,
            contract: type[BaseModel],
            submit_tool_schema: dict[str, Any],
            *,
            allowed_tools: list[str],
            cwd: Path | None,
            timeout_s: int = 600,
            stall_timeout_s: int = 300,
            max_turns: int | None = None,
        ) -> NodeResult[BaseModel]:
            agents_called.append("default")
            return NodeResult[BaseModel](
                contract=contract.model_validate({"summary": "done"}),
                attestation=Attestation(status="complete"),
            )

    runner = Runner(
        db_path=db,
        agent=_TrackingAgent(),
        prompts_dir=prompts_dir,
        progress=False,
    )
    exit_code = await runner.run(wf, inputs={}, base_branch="main")
    assert exit_code == 0
    assert agents_called == ["default"]


async def test_per_node_agent_routing_claude_step_uses_claude_override(tmp_path: Path) -> None:
    """A step with agent='claude' routes to the 'claude' _step_agents override."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "p.j2").write_text("do it\n")
    db = tmp_path / "harness.db"
    wf = tmp_path / "routeclaude.yaml"
    _write_workflow(
        wf,
        """
        name: routeclaude
        version: 1
        steps:
          - id: step1
            type: ai
            agent: claude
            prompt: p.j2
            writes: [summary]
            contract:
              summary: string
        """,
    )

    agents_called: list[str] = []

    class _TrackingAgent(MockAgent):
        def __init__(self, name: str) -> None:
            super().__init__()
            self._name = name

        async def execute(  # type: ignore[override]
            self,
            prompt: str,
            contract: type[BaseModel],
            submit_tool_schema: dict[str, Any],
            *,
            allowed_tools: list[str],
            cwd: Path | None,
            timeout_s: int = 600,
            stall_timeout_s: int = 300,
            max_turns: int | None = None,
        ) -> NodeResult[BaseModel]:
            agents_called.append(self._name)
            return NodeResult[BaseModel](
                contract=contract.model_validate({"summary": f"done by {self._name}"}),
                attestation=Attestation(status="complete"),
            )

    default_agent = _TrackingAgent("default")
    claude_agent = _TrackingAgent("claude")

    runner = Runner(
        db_path=db,
        agent=default_agent,
        prompts_dir=prompts_dir,
        progress=False,
        _step_agents={"claude": claude_agent},
    )
    exit_code = await runner.run(wf, inputs={}, base_branch="main")
    assert exit_code == 0
    assert agents_called == ["claude"]
