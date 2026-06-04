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
import tempfile
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from harness.dispatch.mock import MockAgent
from harness.engine.executor import Context, Executor
from harness.engine.loop import LoopExecutor, LoopExhausted
from harness.engine.runner import Runner
from harness.events.emitter import EventEmitter
from harness.identity import generate_run_id
from harness.state.store import init_db
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
    async with (
        aiosqlite.connect(db_path) as conn,
        conn.execute("SELECT run_id FROM runs LIMIT 1") as cur,
    ):
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


def _loop_until_bash_succeeds_workflow(tmp_path: Path) -> Path:
    """A loop with ``until_bash:`` only — the command exits 0 on iteration
    1 so the loop terminates cleanly without needing ``until:``."""
    path = tmp_path / "loopy_until_bash_ok.yaml"
    _write_workflow(
        path,
        """
        name: loopy_until_bash_ok
        version: 1
        steps:
          - id: body
            type: loop
            loop:
              max_iterations: 3
              until_bash: "true"
              steps:
                - id: noop
                  type: check
                  expr: "True"
                  on_fail: cancel
        """,
    )
    return path


def _loop_until_bash_exhausts_workflow(tmp_path: Path) -> Path:
    """A loop with ``until_bash:`` only — the command always exits non-zero,
    so the loop iterates to exhaustion."""
    path = tmp_path / "loopy_until_bash_fail.yaml"
    _write_workflow(
        path,
        """
        name: loopy_until_bash_fail
        version: 1
        steps:
          - id: body
            type: loop
            loop:
              max_iterations: 2
              until_bash: "false"
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
    async with (
        aiosqlite.connect(db) as conn,
        conn.execute(
            "SELECT state_json FROM runs WHERE run_id = ?", (run_id,)
        ) as cur,
    ):
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
# AC7 — until_bash alone runs the loop until exit 0 (H-021b)
# ---------------------------------------------------------------------------


async def test_loop_until_bash_alone_terminates_on_exit_zero(tmp_path: Path) -> None:
    """``until_bash:`` is executed each iteration; exit 0 satisfies the
    loop just like a true ``until:`` expression. No ``until:`` field is
    required."""
    db = tmp_path / "harness.db"
    wf = _loop_until_bash_succeeds_workflow(tmp_path)

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 0

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    iters = [e for e in events if e["event_type"] == "loop_iteration"]
    # ``true`` exits 0 on iteration 1; the loop must satisfy after one pass.
    assert len(iters) == 1, f"expected 1 iteration, got {len(iters)}: {iters!r}"
    data = json.loads(iters[0]["data_json"])
    assert data["until_satisfied"] is True


async def test_loop_until_bash_non_zero_iterates_until_exhaustion(
    tmp_path: Path,
) -> None:
    """A non-zero exit is treated as "not satisfied"; the loop keeps
    iterating until ``max_iterations`` and raises ``LoopExhausted``."""
    db = tmp_path / "harness.db"
    wf = _loop_until_bash_exhausts_workflow(tmp_path)

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 1

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    failed = next(e for e in events if e["event_type"] == "workflow_failed")
    data = json.loads(failed["data_json"])
    reason_blob = (data.get("reason") or "") + " " + (data.get("message") or "")
    assert "loop_exhausted" in reason_blob.lower() or "loopexhausted" in reason_blob.lower(), (
        f"expected loop_exhausted marker: {data!r}"
    )


async def test_loop_until_bash_substitutes_state_tokens(tmp_path: Path) -> None:
    """``$state.<field>`` references in the ``until_bash:`` command are
    substituted with the live state value before exec. Use a derived
    state field that ticks each iteration; satisfy when the count
    reaches a threshold."""
    db = tmp_path / "harness.db"
    counter_path = tmp_path / "subcounter"
    wf = tmp_path / "until_bash_sub.yaml"
    _write_workflow(
        wf,
        f"""
        name: until_bash_sub
        version: 1
        steps:
          - id: body
            type: loop
            loop:
              max_iterations: 5
              # Satisfy once `state.count` reaches 2. The command literally
              # contains `$state.count` and must be substituted with the
              # current integer before exec.
              until_bash: "test $state.count -ge 2"
              steps:
                - id: tick
                  type: script
                  command: |
                    n=$(cat {counter_path} 2>/dev/null || echo 0)
                    n=$((n + 1))
                    echo $n > {counter_path}
                    printf '{{"count": %d}}' $n
                  writes: [count]
                  contract:
                    count: integer
        """,
    )

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 0, "workflow did not exit 0 — substitution likely broken"

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    iters = [e for e in events if e["event_type"] == "loop_iteration"]
    # Iteration 1: count=1, test 1 -ge 2 → non-zero → continue.
    # Iteration 2: count=2, test 2 -ge 2 → zero → satisfied.
    assert len(iters) == 2, f"expected 2 iterations, got {len(iters)}"


async def test_loop_until_bash_unknown_state_field_fails_clearly(
    tmp_path: Path,
) -> None:
    """A `$state.X` reference inside `until_bash:` that names a field
    not on the state schema fails the workflow with a message naming
    the offending field (silent empty-string substitution would mask
    workflow-authoring bugs)."""
    db = tmp_path / "harness.db"
    wf = tmp_path / "until_bash_bad_sub.yaml"
    _write_workflow(
        wf,
        """
        name: until_bash_bad_sub
        version: 1
        steps:
          - id: body
            type: loop
            loop:
              max_iterations: 1
              until_bash: "test $state.no_such_field -eq 0"
              steps:
                - id: noop
                  type: check
                  expr: "True"
                  on_fail: cancel
        """,
    )

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 1

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    failed = next(e for e in events if e["event_type"] == "workflow_failed")
    data = json.loads(failed["data_json"])
    blob = (data.get("reason") or "") + " " + (data.get("message") or "")
    assert "no_such_field" in blob, (
        f"failure message should name the missing state field: {data!r}"
    )


async def test_loop_until_bash_timeout_treated_as_not_satisfied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung ``until_bash:`` command times out at the documented cap and
    is treated as "not satisfied". The boundary is visible on the
    ``loop_iteration`` event via ``data.until_bash_timeout=true``."""
    # Cap the wait at ~0.2s so a `sleep 5` is definitively a timeout.
    import harness.engine.loop as loop_mod

    monkeypatch.setattr(loop_mod, "_UNTIL_BASH_TIMEOUT_S", 0.2)

    db = tmp_path / "harness.db"
    wf = tmp_path / "until_bash_timeout.yaml"
    _write_workflow(
        wf,
        """
        name: until_bash_timeout
        version: 1
        steps:
          - id: body
            type: loop
            loop:
              max_iterations: 1
              until_bash: "sleep 5"
              steps:
                - id: noop
                  type: check
                  expr: "True"
                  on_fail: cancel
        """,
    )

    # Loop runs one iteration; until_bash times out → not satisfied →
    # max_iterations exhausted → LoopExhausted → exit 1.
    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 1

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    iters = [e for e in events if e["event_type"] == "loop_iteration"]
    assert len(iters) == 1, f"expected exactly 1 iteration, got {len(iters)}"
    data = json.loads(iters[0]["data_json"])
    assert data.get("until_bash_timeout") is True, (
        f"expected until_bash_timeout=True on iteration event: {data!r}"
    )
    assert data["until_satisfied"] is False


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
# AC10 — retry_loop:<id> from a check inside a loop drives another iteration
# ---------------------------------------------------------------------------


async def test_check_retry_loop_triggers_next_iteration(tmp_path: Path) -> None:
    """A check inside a loop with ``on_fail: retry_loop:<loop-id>`` causes
    the LoopExecutor to start another iteration of the named loop rather
    than failing the workflow.

    Flow: each iteration ticks a counter on disk and writes the value to
    state. The in-loop check is ``state.count >= 2``. On iteration 1 the
    check is False → ``on_fail: retry_loop:body`` requests another
    iteration. On iteration 2 it's True → loop satisfies via ``until``.
    """
    db = tmp_path / "harness.db"
    counter_path = tmp_path / "rl_counter"
    wf = tmp_path / "retry_loop.yaml"
    _write_workflow(
        wf,
        f"""
        name: retry_loop_wf
        version: 1
        steps:
          - id: body
            type: loop
            loop:
              max_iterations: 5
              until: "state.count >= 2"
              steps:
                - id: tick
                  type: script
                  command: |
                    n=$(cat {counter_path} 2>/dev/null || echo 0)
                    n=$((n + 1))
                    echo $n > {counter_path}
                    printf '{{"count": %d}}' $n
                  writes: [count]
                  contract:
                    count: integer
                - id: gate
                  type: check
                  expr: "state.count >= 2"
                  on_fail: "retry_loop:body"
        """,
    )

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 0, (
        "retry_loop should drive another iteration, not fail the run"
    )

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    iters = [e for e in events if e["event_type"] == "loop_iteration"]
    # Iteration 1: check False → retry_loop:body requested.
    # Iteration 2: check True → until satisfied → loop exits.
    assert len(iters) == 2, (
        f"expected 2 iterations driven by retry_loop, got {len(iters)}"
    )

    # The first iteration's loop_iteration event must mark the retry trigger.
    iter1_data = json.loads(iters[0]["data_json"])
    assert iter1_data.get("trigger") == "retry_loop_requested", (
        f"iteration 1 should record retry_loop trigger: {iter1_data!r}"
    )
    # The check id that requested the retry should be recorded.
    assert iter1_data.get("requested_by") == "gate", (
        f"iteration 1 should name the requesting check: {iter1_data!r}"
    )

    # The second iteration's loop_iteration event must NOT carry the retry
    # trigger — it exited via ``until``.
    iter2_data = json.loads(iters[1]["data_json"])
    assert iter2_data.get("trigger") != "retry_loop_requested"
    assert iter2_data.get("until_satisfied") is True


async def test_check_retry_loop_counts_against_max_iterations(
    tmp_path: Path,
) -> None:
    """retry_loop requests count against ``max_iterations``. A check that
    never passes (always requests retry_loop) exhausts the loop's
    iteration budget and raises LoopExhausted."""
    db = tmp_path / "harness.db"
    wf = tmp_path / "retry_loop_exhaust.yaml"
    _write_workflow(
        wf,
        """
        name: retry_loop_exhaust
        version: 1
        steps:
          - id: body
            type: loop
            loop:
              max_iterations: 2
              until: "state.never"
              steps:
                - id: write_never
                  type: script
                  command: 'printf "%s" "{\\"never\\": false}"'
                  writes: [never]
                  contract:
                    never: boolean
                - id: gate
                  type: check
                  expr: "False"
                  on_fail: "retry_loop:body"
        """,
    )

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 1

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    failed = next(e for e in events if e["event_type"] == "workflow_failed")
    data = json.loads(failed["data_json"])
    blob = (data.get("reason") or "") + " " + (data.get("message") or "")
    assert "loopexhausted" in blob.lower() or "loop_exhausted" in blob.lower(), (
        f"max_iterations should be honoured: {data!r}"
    )


# ---------------------------------------------------------------------------
# AC10b — cross-loop retry_loop:<other-id> fails clearly
# ---------------------------------------------------------------------------


async def test_check_retry_loop_unknown_id_fails_with_clear_message(
    tmp_path: Path,
) -> None:
    """``retry_loop:<id>`` referencing a loop that is not currently active
    fails the workflow with a message naming the offending id. The
    simplest case: a check sits outside any loop and asks to retry a
    non-existent one. The runner's generic handler maps the raise to
    exit 1; the failure reason must name ``retry_loop`` and the bad id."""
    db = tmp_path / "harness.db"
    wf = tmp_path / "retry_loop_unknown.yaml"
    _write_workflow(
        wf,
        """
        name: retry_loop_unknown
        version: 1
        steps:
          - id: gate
            type: check
            expr: "False"
            on_fail: "retry_loop:no_such_loop"
        """,
    )

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 1

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    failed = next(e for e in events if e["event_type"] == "workflow_failed")
    data = json.loads(failed["data_json"])
    blob = (data.get("reason") or "") + " " + (data.get("message") or "")
    assert "retry_loop" in blob.lower(), (
        f"failure message should mention retry_loop: {data!r}"
    )
    assert "no_such_loop" in blob, (
        f"failure message should name the bad loop id: {data!r}"
    )


# ---------------------------------------------------------------------------
# on_exhaust field — schema and engine behaviour
# ---------------------------------------------------------------------------


def test_loop_block_on_exhaust_defaults_to_cancel() -> None:
    """LoopBlock.on_exhaust defaults to 'cancel' for backwards compatibility."""
    from harness.workflow.schema import CheckStep, LoopBlock

    block = LoopBlock(
        max_iterations=2,
        until="state.never",
        steps=[CheckStep(type="check", id="noop", expr="True", on_fail="cancel")],
    )
    assert block.on_exhaust == "cancel"


async def test_on_exhaust_continue_does_not_raise_on_exhaustion(
    tmp_path: Path,
) -> None:
    """A loop with ``on_exhaust: continue`` falls through to post-loop steps
    without raising LoopExhausted. The post-loop check step must run and
    pass (exit_code == 0)."""
    db = tmp_path / "harness.db"
    wf = tmp_path / "exhaust_continue.yaml"
    _write_workflow(
        wf,
        """
        name: exhaust_continue
        version: 1
        steps:
          - id: fix-loop
            type: loop
            loop:
              max_iterations: 2
              until: "state.never"
              on_exhaust: continue
              steps:
                - id: write-false
                  type: script
                  command: 'printf "%s" "{\\"never\\": false}"'
                  writes: [never]
                  contract:
                    never: boolean
          - id: post-loop
            type: check
            expr: "True"
            on_fail: cancel
        """,
    )

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 0, "on_exhaust: continue should fall through, not fail"

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    started = [e["node_id"] for e in events if e["event_type"] == "node_started"]
    assert "post-loop" in started, (
        f"post-loop step must run after on_exhaust: continue; started={started}"
    )


async def test_on_exhaust_cancel_default_still_raises(tmp_path: Path) -> None:
    """The default on_exhaust: cancel behaviour is unchanged.

    This test verifies that existing AC2 / AC3 behaviour is preserved when
    on_exhaust is not set (it defaults to 'cancel')."""
    db = tmp_path / "harness.db"
    wf = _loop_exhaustion_workflow(tmp_path)  # uses default on_exhaust (cancel)

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 1, "default on_exhaust: cancel must still fail the run"


# ---------------------------------------------------------------------------
# Simulation tests — build workflow review-loop paths
# ---------------------------------------------------------------------------


async def test_fail_retry_pass_path(tmp_path: Path) -> None:
    """Simulate FAIL → retry → PASS: loop writes FAIL on first iteration and
    PASS on second. After the loop, gate-exhausted passes (verdict=PASS).
    Verify exit_code == 0."""
    db = tmp_path / "harness.db"
    counter_path = tmp_path / "frp_counter"
    wf = tmp_path / "fail_retry_pass.yaml"
    _write_workflow(
        wf,
        f"""
        name: fail_retry_pass
        version: 1
        steps:
          - id: fix-loop
            type: loop
            loop:
              max_iterations: 3
              until: 'state.verdict != "FAIL"'
              on_exhaust: continue
              steps:
                - id: review
                  type: script
                  command: |
                    n=$(cat {counter_path} 2>/dev/null || echo 0)
                    n=$((n + 1))
                    echo $n > {counter_path}
                    if [ "$n" -ge 2 ]; then
                      printf '{{"verdict": "PASS"}}'
                    else
                      printf '{{"verdict": "FAIL"}}'
                    fi
                  writes: [verdict]
                  contract:
                    verdict:
                      type: string
                      enum: [PASS, FAIL, DEFER]
                - id: gate-retry
                  type: check
                  expr: 'state.verdict != "FAIL"'
                  on_fail: "retry_loop:fix-loop"
          - id: gate-exhausted
            type: check
            expr: 'state.verdict != "FAIL"'
            on_fail: cancel
        """,
    )

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 0, "FAIL→retry→PASS path should exit 0"

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    started = [e["node_id"] for e in events if e["event_type"] == "node_started"]
    assert "gate-exhausted" in started, (
        f"gate-exhausted must run after the loop; started={started}"
    )


async def test_defer_no_error_path(tmp_path: Path) -> None:
    """Simulate DEFER path: loop writes DEFER (not FAIL) so gate-retry exits
    immediately. After the loop, gate-exhausted passes (DEFER != FAIL).
    Verify exit_code == 0."""
    db = tmp_path / "harness.db"
    wf = tmp_path / "defer_path.yaml"
    _write_workflow(
        wf,
        """
        name: defer_path
        version: 1
        steps:
          - id: fix-loop
            type: loop
            loop:
              max_iterations: 3
              until: 'state.verdict != "FAIL"'
              on_exhaust: continue
              steps:
                - id: review
                  type: script
                  command: 'printf "%s" "{\\"verdict\\": \\"DEFER\\"}"'
                  writes: [verdict]
                  contract:
                    verdict:
                      type: string
                      enum: [PASS, FAIL, DEFER]
                - id: gate-retry
                  type: check
                  expr: 'state.verdict != "FAIL"'
                  on_fail: "retry_loop:fix-loop"
          - id: gate-exhausted
            type: check
            expr: 'state.verdict != "FAIL"'
            on_fail: cancel
        """,
    )

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 0, "DEFER path should exit 0 (DEFER is not FAIL)"

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    started = [e["node_id"] for e in events if e["event_type"] == "node_started"]
    assert "gate-exhausted" in started, (
        f"gate-exhausted must run after the loop; started={started}"
    )


async def test_exhaustion_cancels_on_gate_exhausted(tmp_path: Path) -> None:
    """Simulate exhaustion path: loop always writes FAIL, exhausts after
    max_iterations: 2 with on_exhaust: continue. gate-exhausted cancels
    (verdict still FAIL). Verify exit_code == 1."""
    db = tmp_path / "harness.db"
    wf = tmp_path / "exhaustion_cancel.yaml"
    _write_workflow(
        wf,
        """
        name: exhaustion_cancel
        version: 1
        steps:
          - id: fix-loop
            type: loop
            loop:
              max_iterations: 2
              until: 'state.verdict != "FAIL"'
              on_exhaust: continue
              steps:
                - id: review
                  type: script
                  command: 'printf "%s" "{\\"verdict\\": \\"FAIL\\"}"'
                  writes: [verdict]
                  contract:
                    verdict:
                      type: string
                      enum: [PASS, FAIL, DEFER]
                - id: gate-retry
                  type: check
                  expr: 'state.verdict != "FAIL"'
                  on_fail: "retry_loop:fix-loop"
          - id: gate-exhausted
            type: check
            expr: 'state.verdict != "FAIL"'
            on_fail: cancel
        """,
    )

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 1, "exhaustion path should exit 1 (gate-exhausted cancels)"


async def test_loop_until_bash_substitutes_input_tokens(tmp_path: Path) -> None:
    """$inputs.<key> references in until_bash are substituted with the run's
    input value. With threshold=2 passed as an input, the loop satisfies
    when state.count reaches 2."""
    db = tmp_path / "harness.db"
    counter_path = tmp_path / "inp_counter"
    wf = tmp_path / "until_bash_input_sub.yaml"
    _write_workflow(
        wf,
        f"""
        name: until_bash_input_sub
        version: 1
        steps:
          - id: body
            type: loop
            loop:
              max_iterations: 5
              until_bash: "test $state.count -ge $inputs.threshold"
              steps:
                - id: tick
                  type: script
                  command: |
                    n=$(cat {counter_path} 2>/dev/null || echo 0)
                    n=$((n + 1))
                    echo $n > {counter_path}
                    printf '{{"count": %d}}' $n
                  writes: [count]
                  contract:
                    count: integer
        """,
    )

    exit_code = await Runner(db_path=db).run(
        wf, inputs={"threshold": "2"}, base_branch="main"
    )
    assert exit_code == 0, "inputs substitution should let the loop satisfy at count=2"

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    iters = [e for e in events if e["event_type"] == "loop_iteration"]
    # Iteration 1: count=1, test 1 -ge 2 → non-zero → continue.
    # Iteration 2: count=2, test 2 -ge 2 → zero → satisfied.
    assert len(iters) == 2, f"expected 2 iterations, got {len(iters)}"


async def test_loop_until_bash_unknown_inputs_key_fails_clearly(
    tmp_path: Path,
) -> None:
    """A $inputs.X reference inside until_bash that names a key not in run
    inputs fails the workflow with a message naming the offending key."""
    db = tmp_path / "harness.db"
    wf = tmp_path / "until_bash_bad_input.yaml"
    _write_workflow(
        wf,
        """
        name: until_bash_bad_input
        version: 1
        steps:
          - id: body
            type: loop
            loop:
              max_iterations: 1
              until_bash: "test $inputs.no_such_input -eq 0"
              steps:
                - id: noop
                  type: check
                  expr: "True"
                  on_fail: cancel
        """,
    )

    exit_code = await Runner(db_path=db).run(wf, inputs={}, base_branch="main")
    assert exit_code == 1

    run_id = await _fetch_single_run_id(db)
    events = await _fetch_events(db, run_id)
    failed = next(e for e in events if e["event_type"] == "workflow_failed")
    data = json.loads(failed["data_json"])
    blob = (data.get("reason") or "") + " " + (data.get("message") or "")
    assert "no_such_input" in blob, (
        f"failure message should name the missing inputs key: {data!r}"
    )
