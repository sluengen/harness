"""Tests for harness.engine.loop — see SPEC §10 "Loop blocks".

The :class:`LoopExecutor` iterates a loop block's child steps until the
``until:`` expression evaluates true against state, or ``max_iterations``
is reached. On exhaustion it raises :class:`LoopExhausted`; the runner
maps that to exit code 1 + a ``workflow_failed`` event whose ``reason``
identifies the loop_exhausted condition.

Tests are written against the public seam: a ``LoopExecutor`` plus
``LoopExhausted`` are imported from :mod:`harness.engine.loop`. State
propagation between iterations rides the existing executor + state-store
pipeline; this module does not re-implement state writes.

A handful of cases exercise integration with the runner — see
``test_engine_runner.py`` for the AC9 update that replaces the old
"loop rejected" behaviour.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from harness.dispatch.mock import MockAgent
from harness.engine.loop import LoopExecutor, LoopExhausted
from harness.engine.runner import LoopNotImplemented, Runner
from harness.workflow.derive import derive_state_schema
from harness.workflow.loader import load_workflow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_workflow(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip("\n"))


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


async def _fetch_single_run_id(db_path: Path) -> str:
    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute("SELECT run_id FROM runs LIMIT 1") as cur:
            row = await cur.fetchone()
    assert row is not None, "no run row found"
    return str(row[0])


def _loop_until_true_after_two_iterations_workflow(tmp_path: Path) -> Path:
    """A loop whose body writes ``flipped: true`` once a sidecar file exists.

    Iteration 1: ``[ -f tmp/marker ]`` fails → script writes ``flipped: false``.
    Iteration 2: outer side-effect (a touch step before the loop, but we use
    the loop body itself) creates the marker, then the writer sees it and
    writes ``flipped: true`` → loop exits.

    Simpler: each loop body has two children — a "touch the marker" step
    that runs only on iteration 2 by checking a counter file, and a
    "report" step that writes the boolean. We keep it pragmatic: a single
    script that increments a counter file and writes ``flipped: true``
    once the counter reaches 2.
    """
    path = tmp_path / "loopy_two.yaml"
    counter_path = tmp_path / "counter"
    _write_workflow(
        path,
        f"""
        name: loopy_two
        version: 1
        steps:
          - id: body
            type: loop
            loop:
              max_iterations: 5
              until: "state.flipped"
              steps:
                - id: tick
                  type: script
                  command: |
                    n=$(cat {counter_path} 2>/dev/null || echo 0)
                    n=$((n + 1))
                    echo $n > {counter_path}
                    if [ "$n" -ge 2 ]; then
                      printf '{{"flipped": true}}'
                    else
                      printf '{{"flipped": false}}'
                    fi
                  writes: [flipped]
                  contract:
                    flipped: boolean
          - id: after
            type: check
            expr: "state.flipped"
            on_fail: cancel
        """,
    )
    return path


def _loop_exhaustion_workflow(tmp_path: Path) -> Path:
    """A loop whose ``until:`` never becomes true."""
    path = tmp_path / "loopy_exhaust.yaml"
    _write_workflow(
        path,
        """
        name: loopy_exhaust
        version: 1
        steps:
          - id: body
            type: loop
            loop:
              max_iterations: 2
              until: "state.never"
              steps:
                - id: write_false
                  type: script
                  command: 'printf "%s" "{\\"never\\": false}"'
                  writes: [never]
                  contract:
                    never: boolean
        """,
    )
    return path


def _loop_until_bash_only_workflow(tmp_path: Path) -> Path:
    """A loop with ``until_bash:`` only, ``until:`` set to an unreachable
    sentinel expression — the schema requires ``until:`` so we can't omit
    it. The LoopExecutor must still reject ``until_bash:`` as deferred."""
    path = tmp_path / "loopy_until_bash.yaml"
    # The schema requires until: str — we use the empty string sentinel
    # the LoopExecutor treats as "use until_bash instead". The executor
    # may also key off `until_bash is not None` and reject regardless;
    # both shapes are covered.
    _write_workflow(
        path,
        """
        name: loopy_until_bash
        version: 1
        steps:
          - id: body
            type: loop
            loop:
              max_iterations: 1
              until: ""
              until_bash: "true"
              steps:
                - id: noop
                  type: check
                  expr: "True"
                  on_fail: cancel
        """,
    )
    return path


def _loop_both_until_and_until_bash_workflow(tmp_path: Path) -> Path:
    """A loop with both ``until:`` and ``until_bash:`` set."""
    path = tmp_path / "loopy_both.yaml"
    _write_workflow(
        path,
        """
        name: loopy_both
        version: 1
        steps:
          - id: body
            type: loop
            loop:
              max_iterations: 1
              until: "state.flipped"
              until_bash: "true"
              steps:
                - id: noop
                  type: check
                  expr: "True"
                  on_fail: cancel
        """,
    )
    return path


def _loop_child_error_workflow(tmp_path: Path) -> Path:
    """A loop whose first child step exits non-zero — the loop must
    propagate the error immediately."""
    path = tmp_path / "loopy_err.yaml"
    _write_workflow(
        path,
        """
        name: loopy_err
        version: 1
        steps:
          - id: body
            type: loop
            loop:
              max_iterations: 5
              until: "state.flipped"
              steps:
                - id: boom
                  type: script
                  command: 'exit 7'
        """,
    )
    return path


# ---------------------------------------------------------------------------
# AC1 — until-true exits loop, parent continues
# ---------------------------------------------------------------------------


async def test_loop_runs_until_condition_true(tmp_path: Path) -> None:
    """A loop whose ``until:`` flips true after iteration 2 exits cleanly
    and the next workflow step runs."""
    db = tmp_path / "harness.db"
    wf = _loop_until_true_after_two_iterations_workflow(tmp_path)

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 0

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)

    # The post-loop ``after`` check step must have run — its node_started
    # event proves the loop exited and the parent continued.
    started = [
        e["node_id"] for e in events if e["event_type"] == "node_started"
    ]
    assert "after" in started, f"post-loop step did not run; started={started}"


# ---------------------------------------------------------------------------
# AC2 — max_iterations exhaustion raises LoopExhausted
# ---------------------------------------------------------------------------


async def test_loop_exhaustion_raises_loop_exhausted() -> None:
    """When ``until:`` never becomes true and max_iterations is reached,
    the LoopExecutor raises :class:`LoopExhausted` with a message naming
    the step id and iteration count.

    Tested at the LoopExecutor level for the raw exception shape; the
    runner-level exit-1 + event behaviour has its own test below.
    """
    # We need a LoopExecutor + a Context to feed it. Build a minimal
    # workflow via the loader so the contracts compile and state schema
    # is real.
    import tempfile
    from datetime import UTC, datetime

    from harness.dispatch.mock import MockAgent
    from harness.engine.executor import Context, Executor
    from harness.engine.runner import Runner
    from harness.events.emitter import EventEmitter
    from harness.identity import generate_run_id
    from harness.state.store import init_db

    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        db = tmp_path / "harness.db"
        wf = _loop_exhaustion_workflow(tmp_path)

        loaded = load_workflow(wf)
        state_schema = derive_state_schema(loaded)
        run_id = generate_run_id()

        await init_db(db)
        # Insert the runs row directly so the executor / loop can read state.
        async with aiosqlite.connect(db) as conn:
            initial_state = state_schema.model_validate(
                {
                    "run_id": run_id,
                    "workflow_name": loaded.workflow.name,
                    "base_branch": "main",
                    "artifacts_dir": str(tmp_path / "artifacts"),
                    "started_at": datetime.now(UTC),
                    "notes": [],
                }
            )
            await conn.execute(
                "INSERT INTO runs ("
                "run_id, workflow_name, workflow_version, status, "
                "state_json, inputs_json, base_branch, started_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    loaded.workflow.name,
                    loaded.workflow.version,
                    "running",
                    initial_state.model_dump_json(),
                    "{}",
                    "main",
                    datetime.now(UTC).isoformat(),
                ),
            )
            await conn.commit()

        runner = Runner(db_path=db)
        registry = runner._build_node_registry(  # noqa: SLF001 — test seam
            inputs={},
            workflow_path=wf,
            run_id=run_id,
        )
        ctx = Context(
            run_id=run_id,
            db_path=db,
            contracts=loaded.contracts,
            state_schema=state_schema,
            nodes=registry,
        )
        executor = Executor()
        emitter = EventEmitter(db)
        agent = MockAgent()

        loop_step = loaded.workflow.steps[0]
        loop_executor = LoopExecutor(executor=executor, agent=agent, emitter=emitter)

        with pytest.raises(LoopExhausted) as exc_info:
            await loop_executor.execute(loop_step, ctx)

        msg = str(exc_info.value)
        assert "body" in msg, f"missing step id in message: {msg!r}"
        # iteration count (2) should be mentioned somewhere
        assert "2" in msg, f"missing iteration count in message: {msg!r}"


# ---------------------------------------------------------------------------
# AC3 — runner maps LoopExhausted → exit 1 + workflow_failed/loop_exhausted
# ---------------------------------------------------------------------------


async def test_loop_exhaustion_emits_workflow_failed_with_loop_exhausted_reason(
    tmp_path: Path,
) -> None:
    """At the runner level, an exhausted loop yields exit 1 + a
    ``workflow_failed`` event whose ``reason`` identifies loop_exhausted.
    """
    db = tmp_path / "harness.db"
    wf = _loop_exhaustion_workflow(tmp_path)

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 1

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    failed = next(e for e in events if e["event_type"] == "workflow_failed")
    data = json.loads(failed["data_json"])
    # The reason field carries an identifiable marker. Either the literal
    # ``loop_exhausted`` (preferred) or the class name ``LoopExhausted``.
    reason_blob = (data.get("reason") or "") + " " + (data.get("message") or "")
    assert "loop_exhausted" in reason_blob.lower() or "loopexhausted" in reason_blob.lower(), (
        f"expected loop_exhausted marker in workflow_failed data: {data!r}"
    )


# ---------------------------------------------------------------------------
# AC4 — loop_iteration events emitted per iteration
# ---------------------------------------------------------------------------


async def test_loop_emits_loop_iteration_per_iteration(tmp_path: Path) -> None:
    """The loop emits one ``loop_iteration`` event per iteration boundary,
    each carrying the iteration index."""
    db = tmp_path / "harness.db"
    wf = _loop_until_true_after_two_iterations_workflow(tmp_path)

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 0

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    iters = [e for e in events if e["event_type"] == "loop_iteration"]

    # Two iterations: the second sets flipped=true.
    assert len(iters) == 2, f"expected 2 loop_iteration events, got {len(iters)}: {iters!r}"

    # Each event must carry an iteration index in its data payload.
    for e in iters:
        data = json.loads(e["data_json"])
        assert "iteration" in data, f"loop_iteration missing iteration key: {data!r}"
        assert isinstance(data["iteration"], int)

    # Indices are sequential (1-based per the chosen convention).
    indices = [json.loads(e["data_json"])["iteration"] for e in iters]
    assert indices == [1, 2], f"unexpected iteration ordering: {indices!r}"


# ---------------------------------------------------------------------------
# AC5 — state propagates between iterations
# ---------------------------------------------------------------------------


async def test_loop_state_propagates_between_iterations(tmp_path: Path) -> None:
    """Iteration N's state writes are visible to iteration N+1 via the
    ``until:`` expression. The 'flip after 2 iterations' workflow is the
    direct proof: iteration 1 writes ``flipped=false``; iteration 2's
    own write becomes ``flipped=true`` after observing the side-effect
    counter ticked to 2."""
    db = tmp_path / "harness.db"
    wf = _loop_until_true_after_two_iterations_workflow(tmp_path)

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 0

    # Confirm only two iterations occurred (not more — i.e. state really
    # flipped to true on iteration 2 and the loop honoured it).
    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    iters = [e for e in events if e["event_type"] == "loop_iteration"]
    assert len(iters) == 2, f"expected exactly 2 iterations, got {len(iters)}"

    # And the final state has flipped=true.
    async with aiosqlite.connect(db) as conn:
        async with conn.execute("SELECT state_json FROM runs WHERE run_id = ?", (run_id,)) as cur:
            row = await cur.fetchone()
    assert row is not None
    state = json.loads(row[0])
    assert state["flipped"] is True


# ---------------------------------------------------------------------------
# AC6 — fresh_context: true resets the agent between iterations
# ---------------------------------------------------------------------------


class _RecordingAgent(MockAgent):
    """A MockAgent that records reset() calls."""

    def __init__(self) -> None:
        super().__init__()
        self.reset_calls: int = 0

    def reset(self) -> None:
        self.reset_calls += 1


async def test_loop_fresh_context_resets_agent(tmp_path: Path) -> None:
    """With ``fresh_context: true``, the agent's ``reset()`` is invoked
    between iterations.

    The loop body is a single check step (no agent dispatch needed) so
    we keep the test focused on the reset call count.
    """
    db = tmp_path / "harness.db"
    wf = tmp_path / "fresh.yaml"
    counter_path = tmp_path / "fresh_counter"
    _write_workflow(
        wf,
        f"""
        name: freshy
        version: 1
        steps:
          - id: body
            type: loop
            loop:
              max_iterations: 3
              until: "state.done"
              fresh_context: true
              steps:
                - id: tick
                  type: script
                  command: |
                    n=$(cat {counter_path} 2>/dev/null || echo 0)
                    n=$((n + 1))
                    echo $n > {counter_path}
                    if [ "$n" -ge 3 ]; then
                      printf '{{"done": true}}'
                    else
                      printf '{{"done": false}}'
                    fi
                  writes: [done]
                  contract:
                    done: boolean
        """,
    )

    agent = _RecordingAgent()
    runner = Runner(db_path=db, agent=agent)
    exit_code = await runner.run(wf, inputs={}, base_branch="main")
    assert exit_code == 0

    # Three iterations ran. Reset is called at the *start* of each new
    # iteration after the first — so two resets across iterations 2 and 3.
    # (The first iteration uses the existing context; reset is between
    # iterations, not before iteration 1.)
    assert agent.reset_calls == 2, (
        f"expected 2 inter-iteration resets, got {agent.reset_calls}"
    )


# ---------------------------------------------------------------------------
# AC7 — until_bash alone raises NotImplementedError
# ---------------------------------------------------------------------------


async def test_loop_until_bash_alone_raises_not_implemented(tmp_path: Path) -> None:
    """``until_bash:`` execution is deferred to a follow-up. When the
    loop block declares ``until_bash:`` with an empty ``until:``, the
    LoopExecutor raises :class:`NotImplementedError`."""
    db = tmp_path / "harness.db"
    wf = _loop_until_bash_only_workflow(tmp_path)

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    # Runner translates NotImplementedError into exit 1 via the generic
    # BaseException arm.
    assert exit_code == 1

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    failed = next(e for e in events if e["event_type"] == "workflow_failed")
    data = json.loads(failed["data_json"])
    blob = (data.get("reason") or "") + " " + (data.get("message") or "")
    assert "NotImplementedError" in blob or "until_bash" in blob.lower(), (
        f"workflow_failed data should mention until_bash: {data!r}"
    )


# ---------------------------------------------------------------------------
# AC8 — both until and until_bash are rejected
# ---------------------------------------------------------------------------


async def test_loop_both_until_and_until_bash_rejected(tmp_path: Path) -> None:
    """When a loop declares both ``until:`` and ``until_bash:``, the
    LoopExecutor refuses to dispatch — both at once is ambiguous, not
    yet supported."""
    db = tmp_path / "harness.db"
    wf = _loop_both_until_and_until_bash_workflow(tmp_path)

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 1

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    failed = next(e for e in events if e["event_type"] == "workflow_failed")
    data = json.loads(failed["data_json"])
    blob = (data.get("reason") or "") + " " + (data.get("message") or "")
    assert "until_bash" in blob.lower() or "ambig" in blob.lower(), (
        f"expected both-set rejection in failure data: {data!r}"
    )


# ---------------------------------------------------------------------------
# AC9 — child error propagates immediately, no further iterations
# ---------------------------------------------------------------------------


async def test_loop_child_error_propagates_immediately(tmp_path: Path) -> None:
    """A child step raising past its retry budget propagates out of the
    loop on the first iteration — no second iteration runs."""
    db = tmp_path / "harness.db"
    wf = _loop_child_error_workflow(tmp_path)

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 1

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    iters = [e for e in events if e["event_type"] == "loop_iteration"]
    # At most one iteration event (the first iteration, started but never
    # completed cleanly — depending on emission strategy we may see 1 or
    # 0 events, never more).
    assert len(iters) <= 1, (
        f"loop continued past failing child step: {len(iters)} iterations"
    )

    # The failure surfaced on a child step, not a re-raised LoopExhausted.
    failed = next(e for e in events if e["event_type"] == "workflow_failed")
    data = json.loads(failed["data_json"])
    reason = (data.get("reason") or "") + " " + (data.get("message") or "")
    assert "loop_exhausted" not in reason.lower(), (
        f"child-error path should not surface as loop_exhausted: {data!r}"
    )


# ---------------------------------------------------------------------------
# AC10 — retry_loop:<id> path on check_adapter still raises LoopNotImplemented
# ---------------------------------------------------------------------------


async def test_check_retry_loop_still_raises_loop_not_implemented(
    tmp_path: Path,
) -> None:
    """A check step whose ``on_fail: retry_loop:<id>`` resolves at runtime
    still raises :class:`LoopNotImplemented` — that integration is owned
    by a separate ticket, not H-021."""
    db = tmp_path / "harness.db"
    wf = tmp_path / "retryloop.yaml"
    _write_workflow(
        wf,
        """
        name: retryloopwf
        version: 1
        steps:
          - id: gate
            type: check
            expr: "False"
            on_fail: "retry_loop:body"
        """,
    )

    # The check_adapter's branch is reached when the check is False AND
    # the on_fail string begins with retry_loop:. The exception propagates
    # to the runner's generic BaseException handler — exit code 1, with
    # a workflow_failed event whose reason is LoopNotImplemented.
    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 1

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    failed = next(e for e in events if e["event_type"] == "workflow_failed")
    data = json.loads(failed["data_json"])
    assert data.get("reason") == "LoopNotImplemented", (
        f"expected LoopNotImplemented marker, got {data!r}"
    )


# ---------------------------------------------------------------------------
# AC11 — LoopNotImplemented export remains usable
# ---------------------------------------------------------------------------


def test_loop_not_implemented_still_exported() -> None:
    """The legacy :class:`LoopNotImplemented` sentinel still exists on
    :mod:`harness.engine.runner` (a separate ticket cleans up the
    ``retry_loop:`` path)."""
    assert issubclass(LoopNotImplemented, Exception)
