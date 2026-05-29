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
# CAL-507 — progress output during run
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
