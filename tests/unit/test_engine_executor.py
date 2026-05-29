"""Tests for harness.engine.executor — per-node execution + contract validation.

See SPEC §4.2. The executor:

* resolves ``depends_on`` against state (raises :class:`DependencyNotSatisfied`
  when a referenced field is unset / None);
* dispatches to the matching node by ``step.type`` via a node registry
  carried on the :class:`Context`;
* wraps the node call in :func:`harness.engine.retry.run_with_retry`;
* verifies the runtime result's contract type matches
  ``ctx.contracts[step.id]`` (raises :class:`ContractMismatch` otherwise);
* applies only declared ``writes:`` fields via
  :func:`harness.state.store.update_state`;
* emits ``node_started`` / ``node_completed`` / ``node_failed`` events.

Each test maps to one acceptance criterion in the H-020 brief.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from pydantic import BaseModel, ConfigDict

from harness.dispatch.claude import ContractViolation
from harness.engine.executor import (
    Context,
    ContractMismatch,
    DependencyNotSatisfied,
    Executor,
)
from harness.nodes.base import Attestation, NodeResult
from harness.nodes.worktree import WorktreeCreateOutput
from harness.state import store
from harness.state.schema import BaseState
from harness.workflow.schema import (
    AIStep,
    CheckStep,
    DecisionStep,
    ScriptStep,
    Step,
    WorktreeStep,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _AContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: int


class _BContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    b: str


class _ABCContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: int
    b: str
    c: float


class _DerivedState(BaseState):
    """Stand-in for a workflow-derived state class (per H-009).

    Carries the union of contract fields the executor tests reference.
    All optional / nullable to match the derive_state_schema rule.
    """

    model_config = ConfigDict(extra="forbid")

    a: int | None = None
    b: str | None = None
    c: float | None = None
    target: str | None = None


def _base_state(tmp_path: Path, **overrides: Any) -> _DerivedState:
    base: dict[str, Any] = {
        "run_id": "R1",
        "workflow_name": "test_workflow",
        "base_branch": "main",
        "artifacts_dir": tmp_path / "artifacts",
        "started_at": datetime.now(UTC),
    }
    base.update(overrides)
    return _DerivedState(**base)


async def _init_db_with_run(
    db_path: Path,
    state: _DerivedState,
    run_id: str = "R1",
) -> None:
    """Initialise the schema and insert a ``runs`` row carrying ``state``."""
    await store.init_db(db_path)
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                state.workflow_name,
                1,
                "running",
                state.model_dump_json(),
                "{}",
                state.started_at.isoformat(),
            ),
        )
        await conn.commit()


async def _fetch_events(db_path: Path) -> list[dict[str, Any]]:
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT id, run_id, node_id, event_type, timestamp, duration_ms, "
            "data_json FROM events ORDER BY id"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


class _SpyNode:
    """A spy/fake node that records every call and returns a queued result.

    The executor sees a registry mapping ``step.type`` → callable conforming
    to ``async def(step, state, ctx) -> NodeResult``. Each ``_SpyNode``
    implements that callable shape directly. ``set_result`` queues the next
    return value; ``set_results`` queues a sequence (used by retry tests).
    Setting an ``error`` plus a ``result`` makes the spy raise the error on
    the next call and return the result on subsequent calls.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[Step, BaseState]] = []
        self._results: list[NodeResult[BaseModel]] = []
        self._errors: list[BaseException | None] = []

    def queue(
        self,
        *,
        result: NodeResult[BaseModel] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self._results.append(
            result
            if result is not None
            else NodeResult[BaseModel](
                contract=_AContract(a=0),
                attestation=Attestation(status="complete"),
            )
        )
        self._errors.append(error)

    async def execute(
        self, step: Step, state: BaseState, ctx: Context
    ) -> NodeResult[BaseModel]:
        self.calls.append((step, state))
        # Pop next planned response. Errors take precedence so the test can
        # queue (error, then result) for retry scenarios.
        idx = len(self.calls) - 1
        err = self._errors[idx] if idx < len(self._errors) else None
        if err is not None:
            raise err
        if idx < len(self._results):
            return self._results[idx]
        return NodeResult[BaseModel](
            contract=_AContract(a=0),
            attestation=Attestation(status="complete"),
        )


NodeRunner = Callable[[Step, BaseState, Context], Awaitable[NodeResult[BaseModel]]]


def _make_ctx(
    *,
    db_path: Path,
    contracts: dict[str, type[BaseModel]] | None = None,
    nodes: dict[str, NodeRunner] | None = None,
    run_id: str = "R1",
) -> Context:
    return Context(
        run_id=run_id,
        db_path=db_path,
        contracts=contracts or {},
        state_schema=_DerivedState,
        nodes=nodes or {},
    )


def _ai_step(
    step_id: str = "s1",
    *,
    depends_on: list[str] | None = None,
    writes: list[str] | None = None,
) -> AIStep:
    return AIStep(
        id=step_id,
        type="ai",
        prompt="x.j2",
        depends_on=list(depends_on or []),
        writes=list(writes or []),
    )


def _result(contract: BaseModel) -> NodeResult[BaseModel]:
    return NodeResult[BaseModel](
        contract=contract,
        attestation=Attestation(status="complete"),
    )


# ---------------------------------------------------------------------------
# AC1 — depends_on resolution
# ---------------------------------------------------------------------------


async def test_ac1_missing_dependency_raises_dependency_not_satisfied(
    tmp_path: Path,
) -> None:
    """``depends_on: [missing_field]`` against unset state raises."""
    db = tmp_path / "harness.db"
    state = _base_state(tmp_path)  # target is None
    await _init_db_with_run(db, state)

    spy = _SpyNode()
    step = _ai_step(depends_on=["target"])
    ctx = _make_ctx(
        db_path=db,
        contracts={step.id: _AContract},
        nodes={"ai": spy.execute},
    )

    executor = Executor()
    with pytest.raises(DependencyNotSatisfied, match="target"):
        await executor.execute(step, ctx)

    # And dispatch did NOT happen.
    assert spy.calls == []


async def test_ac1_satisfied_dependency_proceeds(tmp_path: Path) -> None:
    """A non-None state field satisfies the dependency."""
    db = tmp_path / "harness.db"
    state = _base_state(tmp_path, target="ready")
    await _init_db_with_run(db, state)

    spy = _SpyNode()
    spy.queue(result=_result(_AContract(a=1)))
    step = _ai_step(depends_on=["target"])
    ctx = _make_ctx(
        db_path=db,
        contracts={step.id: _AContract},
        nodes={"ai": spy.execute},
    )

    await Executor().execute(step, ctx)
    assert len(spy.calls) == 1


# ---------------------------------------------------------------------------
# AC2 — dispatch by step.type
# ---------------------------------------------------------------------------


def _step_of_type(step_type: str) -> Step:
    """Build a minimal valid Step of each type for dispatch tests."""
    if step_type == "ai":
        return AIStep(id="s", type="ai", prompt="p.j2")
    if step_type == "script":
        return ScriptStep(id="s", type="script", command="echo x")
    if step_type == "check":
        return CheckStep(id="s", type="check", expr="True")
    if step_type == "decision":
        return DecisionStep(
            id="s",
            type="decision",
            actor="llm",
            prompt="p.j2",
        )
    if step_type == "worktree":
        return WorktreeStep(
            id="s",
            type="worktree",
            action="create",
            base="main",
        )
    raise AssertionError(step_type)


@pytest.mark.parametrize(
    "step_type",
    ["ai", "script", "check", "decision", "worktree"],
)
async def test_ac2_dispatches_by_step_type(
    tmp_path: Path, step_type: str
) -> None:
    """Each step type routes to the matching registered node — and only that one."""
    db = tmp_path / "harness.db"
    state = _base_state(tmp_path)
    await _init_db_with_run(db, state)

    spies: dict[str, _SpyNode] = {
        t: _SpyNode() for t in ("ai", "script", "check", "decision", "worktree")
    }
    # Queue an _AContract result so the matched type returns successfully.
    spies[step_type].queue(result=_result(_AContract(a=0)))

    step = _step_of_type(step_type)
    ctx = _make_ctx(
        db_path=db,
        contracts={step.id: _AContract},
        nodes={t: spy.execute for t, spy in spies.items()},
    )

    await Executor().execute(step, ctx)

    for t, spy in spies.items():
        if t == step_type:
            assert len(spy.calls) == 1, f"{t} should have been called once"
        else:
            assert spy.calls == [], f"{t} should not have been called"


# ---------------------------------------------------------------------------
# AC3 — wraps in run_with_retry; transient retry emits one retry_attempted event
# ---------------------------------------------------------------------------


async def test_ac3_transient_then_success_emits_one_retry_attempted_event(
    tmp_path: Path,
) -> None:
    """A spy raising OSError on first call, succeeding on second, is retried.

    The executor returns the success result and emits exactly one
    ``retry_attempted`` event with ``reason='transient'``.
    """
    db = tmp_path / "harness.db"
    state = _base_state(tmp_path)
    await _init_db_with_run(db, state)

    spy = _SpyNode()
    spy.queue(error=OSError("network"))
    spy.queue(result=_result(_AContract(a=42)))

    step = _ai_step()
    ctx = _make_ctx(
        db_path=db,
        contracts={step.id: _AContract},
        nodes={"ai": spy.execute},
    )

    result = await Executor().execute(step, ctx)
    assert isinstance(result.contract, _AContract)
    assert result.contract.a == 42
    assert len(spy.calls) == 2

    rows = await _fetch_events(db)
    retry_rows = [r for r in rows if r["event_type"] == "retry_attempted"]
    assert len(retry_rows) == 1, retry_rows
    data = json.loads(str(retry_rows[0]["data_json"]))
    assert data["reason"] == "transient"


# ---------------------------------------------------------------------------
# AC4 — runtime contract type mismatch → ContractMismatch
# ---------------------------------------------------------------------------


async def test_ac4_runtime_contract_type_mismatch_raises(tmp_path: Path) -> None:
    """Node returns NodeResult[_AContract] but loader declares _BContract."""
    db = tmp_path / "harness.db"
    state = _base_state(tmp_path)
    await _init_db_with_run(db, state)

    spy = _SpyNode()
    spy.queue(result=_result(_AContract(a=1)))

    step = _ai_step()
    ctx = _make_ctx(
        db_path=db,
        contracts={step.id: _BContract},  # mismatched
        nodes={"ai": spy.execute},
    )

    with pytest.raises(ContractMismatch):
        await Executor().execute(step, ctx)


# ---------------------------------------------------------------------------
# AC5 — only declared `writes:` fields propagate to state
# ---------------------------------------------------------------------------


async def test_ac5_only_declared_writes_propagate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A contract with three fields ``a``, ``b``, ``c``; writes only ``a``, ``b``.

    The executor's call to :func:`update_state` must carry exactly
    ``a`` and ``b`` (no ``c``).
    """
    db = tmp_path / "harness.db"
    state = _base_state(tmp_path)
    await _init_db_with_run(db, state)

    captured: list[dict[str, Any]] = []
    real_update = store.update_state

    async def spy_update_state(
        run_id: str,
        schema: type[BaseState],
        *,
        db_path: Path = store.DEFAULT_DB_PATH,
        emit_event: bool = True,
        merge_overrides: dict[str, str] | None = None,
        **fields: Any,
    ) -> BaseState:
        captured.append(dict(fields))
        return await real_update(
            run_id,
            schema,
            db_path=db_path,
            emit_event=emit_event,
            merge_overrides=merge_overrides,
            **fields,
        )

    monkeypatch.setattr(
        "harness.engine.executor.update_state",
        spy_update_state,
        raising=True,
    )

    spy = _SpyNode()
    spy.queue(result=_result(_ABCContract(a=1, b="two", c=3.0)))

    step = _ai_step(writes=["a", "b"])
    ctx = _make_ctx(
        db_path=db,
        contracts={step.id: _ABCContract},
        nodes={"ai": spy.execute},
    )

    await Executor().execute(step, ctx)

    assert len(captured) == 1
    assert captured[0] == {"a": 1, "b": "two"}


# ---------------------------------------------------------------------------
# AC6 — writes referencing a non-existent contract field is rejected
# ---------------------------------------------------------------------------


async def test_ac6_writes_referencing_unknown_contract_field_raises_contract_mismatch(
    tmp_path: Path,
) -> None:
    """``writes: ['zzz']`` against a contract without ``zzz`` is a
    :class:`ContractMismatch` (design choice: ContractMismatch covers both
    runtime-type and writes-key shape errors at the boundary).
    """
    db = tmp_path / "harness.db"
    state = _base_state(tmp_path)
    await _init_db_with_run(db, state)

    spy = _SpyNode()
    spy.queue(result=_result(_AContract(a=1)))

    step = _ai_step(writes=["zzz"])
    ctx = _make_ctx(
        db_path=db,
        contracts={step.id: _AContract},
        nodes={"ai": spy.execute},
    )

    with pytest.raises(ContractMismatch, match="zzz"):
        await Executor().execute(step, ctx)


async def test_writes_validation_failure_closes_node_lifecycle(
    tmp_path: Path,
) -> None:
    """Post-dispatch ``ContractMismatch`` still pairs ``node_started`` with
    ``node_failed`` (SPEC §4.2 / §4.9 lifecycle invariant).

    Regression: an earlier version raised ``ContractMismatch`` from the
    writes-validation path *after* ``node_started`` was emitted but *before*
    any terminal event, orphaning the lifecycle.
    """
    db = tmp_path / "harness.db"
    state = _base_state(tmp_path)
    await _init_db_with_run(db, state)

    spy = _SpyNode()
    spy.queue(result=_result(_AContract(a=1)))

    step = _ai_step("the-step", writes=["zzz"])
    ctx = _make_ctx(
        db_path=db,
        contracts={step.id: _AContract},  # _AContract has no 'zzz'
        nodes={"ai": spy.execute},
    )

    with pytest.raises(ContractMismatch, match="zzz"):
        await Executor().execute(step, ctx)

    rows = await _fetch_events(db)
    lifecycle_kinds = ("node_started", "node_completed", "node_failed")
    lifecycle = [
        r for r in rows if r["event_type"] in lifecycle_kinds and r["node_id"] == "the-step"
    ]
    assert [r["event_type"] for r in lifecycle] == [
        "node_started",
        "node_failed",
    ]
    data = json.loads(str(lifecycle[1]["data_json"]))
    assert data["reason"] == "ContractMismatch"
    assert "zzz" in data["message"]


# ---------------------------------------------------------------------------
# AC7 — node_started + node_completed events emitted on success
# ---------------------------------------------------------------------------


async def test_ac7_emits_node_started_then_node_completed_on_success(
    tmp_path: Path,
) -> None:
    """Two events: ``node_started`` and ``node_completed`` with non-null
    ``duration_ms`` on completion, both carrying ``node_id == step.id``."""
    db = tmp_path / "harness.db"
    state = _base_state(tmp_path)
    await _init_db_with_run(db, state)

    spy = _SpyNode()
    spy.queue(result=_result(_AContract(a=1)))

    step = _ai_step("the-step")
    ctx = _make_ctx(
        db_path=db,
        contracts={step.id: _AContract},
        nodes={"ai": spy.execute},
    )

    await Executor().execute(step, ctx)

    rows = await _fetch_events(db)
    # Filter to only the node lifecycle events (state_changed may also appear).
    lifecycle_kinds = ("node_started", "node_completed", "node_failed")
    lifecycle = [r for r in rows if r["event_type"] in lifecycle_kinds]
    assert [r["event_type"] for r in lifecycle] == ["node_started", "node_completed"]
    for r in lifecycle:
        assert r["node_id"] == "the-step"
    completed = lifecycle[1]
    assert completed["duration_ms"] is not None


# ---------------------------------------------------------------------------
# AC8 — node_failed on exception + re-raised
# ---------------------------------------------------------------------------


async def test_ac8_emits_node_failed_on_exception_and_re_raises(
    tmp_path: Path,
) -> None:
    """A ``ContractViolation`` from the spy (after retry exhaustion) is
    re-raised, and one ``node_failed`` event lands with the exception's
    class name in ``data['reason']``."""
    db = tmp_path / "harness.db"
    state = _base_state(tmp_path)
    await _init_db_with_run(db, state)

    spy = _SpyNode()
    # Two attempts to exhaust the contract-violation budget (2).
    spy.queue(error=ContractViolation("validation_failed"))
    spy.queue(error=ContractViolation("validation_failed"))

    step = _ai_step("the-step")
    ctx = _make_ctx(
        db_path=db,
        contracts={step.id: _AContract},
        nodes={"ai": spy.execute},
    )

    with pytest.raises(ContractViolation):
        await Executor().execute(step, ctx)

    rows = await _fetch_events(db)
    failed = [r for r in rows if r["event_type"] == "node_failed"]
    assert len(failed) == 1
    data = json.loads(str(failed[0]["data_json"]))
    assert data["reason"] == "ContractViolation"
    assert failed[0]["node_id"] == "the-step"


# ---------------------------------------------------------------------------
# AC9 — node never calls update_state directly; executor is the only writer
# ---------------------------------------------------------------------------


async def test_ac9_executor_is_the_only_state_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A node returns ``contract.a = 5``; ``writes = ['a']``. The executor's
    single call to :func:`update_state` carries ``a=5`` and the node itself
    does not call ``update_state`` (the spy doesn't reach the store)."""
    db = tmp_path / "harness.db"
    state = _base_state(tmp_path)
    await _init_db_with_run(db, state)

    captured: list[dict[str, Any]] = []
    real_update = store.update_state

    async def spy_update_state(
        run_id: str,
        schema: type[BaseState],
        *,
        db_path: Path = store.DEFAULT_DB_PATH,
        emit_event: bool = True,
        merge_overrides: dict[str, str] | None = None,
        **fields: Any,
    ) -> BaseState:
        captured.append(dict(fields))
        return await real_update(
            run_id,
            schema,
            db_path=db_path,
            emit_event=emit_event,
            merge_overrides=merge_overrides,
            **fields,
        )

    monkeypatch.setattr(
        "harness.engine.executor.update_state",
        spy_update_state,
        raising=True,
    )

    spy = _SpyNode()
    spy.queue(result=_result(_AContract(a=5)))

    step = _ai_step(writes=["a"])
    ctx = _make_ctx(
        db_path=db,
        contracts={step.id: _AContract},
        nodes={"ai": spy.execute},
    )

    await Executor().execute(step, ctx)

    assert captured == [{"a": 5}]


async def test_ac9b_no_writes_means_no_update_state_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A step with ``writes: []`` should not invoke update_state at all —
    no spurious event, no churn on the DB."""
    db = tmp_path / "harness.db"
    state = _base_state(tmp_path)
    await _init_db_with_run(db, state)

    calls = 0
    real_update = store.update_state

    async def spy_update_state(
        run_id: str,
        schema: type[BaseState],
        *,
        db_path: Path = store.DEFAULT_DB_PATH,
        emit_event: bool = True,
        **fields: Any,
    ) -> BaseState:
        nonlocal calls
        calls += 1
        return await real_update(
            run_id, schema, db_path=db_path, emit_event=emit_event, **fields
        )

    monkeypatch.setattr(
        "harness.engine.executor.update_state",
        spy_update_state,
        raising=True,
    )

    spy = _SpyNode()
    spy.queue(result=_result(_AContract(a=99)))

    step = _ai_step(writes=[])
    ctx = _make_ctx(
        db_path=db,
        contracts={step.id: _AContract},
        nodes={"ai": spy.execute},
    )

    await Executor().execute(step, ctx)
    assert calls == 0


# ---------------------------------------------------------------------------
# AC10 — executor reads ctx.contracts[step.id] for validation
# ---------------------------------------------------------------------------


async def test_ac10_executor_reads_contract_from_context(tmp_path: Path) -> None:
    """The executor reads :attr:`Context.contracts` for the per-step contract.

    Same node output type passes when contracts[step.id] = _AContract,
    fails when contracts[step.id] = _BContract — proving the lookup goes
    through the supplied Context rather than e.g. step.contract.
    """
    db = tmp_path / "harness.db"
    state = _base_state(tmp_path)
    await _init_db_with_run(db, state)

    # Pass — contract matches.
    spy_pass = _SpyNode()
    spy_pass.queue(result=_result(_AContract(a=1)))
    step = _ai_step()
    ctx_ok = _make_ctx(
        db_path=db,
        contracts={step.id: _AContract},
        nodes={"ai": spy_pass.execute},
    )
    res = await Executor().execute(step, ctx_ok)
    assert isinstance(res.contract, _AContract)

    # Fail — contract differs.
    # Reset DB to keep state isolated.
    db2 = tmp_path / "harness2.db"
    await _init_db_with_run(db2, state)
    spy_fail = _SpyNode()
    spy_fail.queue(result=_result(_AContract(a=1)))
    ctx_bad = _make_ctx(
        db_path=db2,
        contracts={step.id: _BContract},
        nodes={"ai": spy_fail.execute},
    )
    with pytest.raises(ContractMismatch):
        await Executor().execute(step, ctx_bad)


async def test_ac10_missing_contract_for_writing_step_raises(tmp_path: Path) -> None:
    """A step with ``writes`` but no entry in ``ctx.contracts`` is a
    ContractMismatch — the executor cannot validate without a declared
    contract."""
    db = tmp_path / "harness.db"
    state = _base_state(tmp_path)
    await _init_db_with_run(db, state)

    spy = _SpyNode()
    spy.queue(result=_result(_AContract(a=1)))

    step = _ai_step(writes=["a"])
    ctx = _make_ctx(
        db_path=db,
        contracts={},  # no entry for step.id
        nodes={"ai": spy.execute},
    )

    with pytest.raises(ContractMismatch):
        await Executor().execute(step, ctx)


# ---------------------------------------------------------------------------
# CAL-497 — WorktreeStep with writes: [...] needs no registered contract
# ---------------------------------------------------------------------------


async def test_worktree_step_with_writes_succeeds_without_registered_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WorktreeStep with ``writes: [worktree_path, worktree_branch]`` must
    succeed even though no contract is registered in ctx.contracts (CAL-497).

    The executor should validate the writes against ``WorktreeCreateOutput``
    (the node's result type) and project the values into state.
    """
    from pathlib import Path as FsPath

    db = tmp_path / "harness.db"
    state = _base_state(tmp_path)
    await _init_db_with_run(db, state)

    captured: list[dict[str, Any]] = []
    real_update = store.update_state

    async def spy_update_state(
        run_id: str,
        schema: type[BaseState],
        *,
        db_path: FsPath = store.DEFAULT_DB_PATH,
        emit_event: bool = True,
        merge_overrides: dict[str, str] | None = None,
        **fields: Any,
    ) -> BaseState:
        captured.append(dict(fields))
        return await real_update(
            run_id,
            schema,
            db_path=db_path,
            emit_event=emit_event,
            merge_overrides=merge_overrides,
            **fields,
        )

    monkeypatch.setattr(
        "harness.engine.executor.update_state",
        spy_update_state,
        raising=True,
    )

    fake_path = tmp_path / ".worktrees" / "harness" / "R1"
    fake_branch = "harness/R1"
    spy = _SpyNode()
    spy.queue(
        result=NodeResult(
            contract=WorktreeCreateOutput(
                worktree_path=fake_path,
                worktree_branch=fake_branch,
            ),
            attestation=Attestation(status="complete"),
        )
    )

    step = WorktreeStep(
        id="setup",
        type="worktree",
        action="create",
        base="main",
        writes=["worktree_path", "worktree_branch"],
    )
    ctx = _make_ctx(
        db_path=db,
        contracts={},  # no entry for WorktreeStep — that's the point
        nodes={"worktree": spy.execute},
    )

    result = await Executor().execute(step, ctx)
    assert isinstance(result.contract, WorktreeCreateOutput)

    # The declared writes fields must have been projected into state.
    assert len(captured) == 1
    assert captured[0] == {
        "worktree_path": fake_path,
        "worktree_branch": fake_branch,
    }


async def test_worktree_step_with_empty_writes_still_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WorktreeStep with ``writes: []`` (default) must not call update_state —
    backward-compatibility check (CAL-497)."""
    from pathlib import Path as FsPath

    db = tmp_path / "harness.db"
    state = _base_state(tmp_path)
    await _init_db_with_run(db, state)

    calls = 0
    real_update = store.update_state

    async def spy_update_state(
        run_id: str,
        schema: type[BaseState],
        *,
        db_path: FsPath = store.DEFAULT_DB_PATH,
        emit_event: bool = True,
        **fields: Any,
    ) -> BaseState:
        nonlocal calls
        calls += 1
        return await real_update(
            run_id, schema, db_path=db_path, emit_event=emit_event, **fields
        )

    monkeypatch.setattr(
        "harness.engine.executor.update_state",
        spy_update_state,
        raising=True,
    )

    fake_path = tmp_path / ".worktrees" / "harness" / "R1"
    spy = _SpyNode()
    spy.queue(
        result=NodeResult(
            contract=WorktreeCreateOutput(
                worktree_path=fake_path,
                worktree_branch="harness/R1",
            ),
            attestation=Attestation(status="complete"),
        )
    )

    step = WorktreeStep(
        id="setup",
        type="worktree",
        action="create",
        base="main",
        writes=[],  # no writes — old pattern
    )
    ctx = _make_ctx(
        db_path=db,
        contracts={},
        nodes={"worktree": spy.execute},
    )

    await Executor().execute(step, ctx)
    assert calls == 0


# ---------------------------------------------------------------------------
# Defence-in-depth — dispatch with an unknown type raises
# ---------------------------------------------------------------------------


async def test_unregistered_step_type_raises(tmp_path: Path) -> None:
    """No node registered for ``step.type`` — surface a clear error
    rather than silently no-op."""
    db = tmp_path / "harness.db"
    state = _base_state(tmp_path)
    await _init_db_with_run(db, state)

    step = _ai_step()
    ctx = _make_ctx(
        db_path=db,
        contracts={step.id: _AContract},
        nodes={},  # empty registry
    )

    with pytest.raises(RuntimeError, match="no node registered"):
        await Executor().execute(step, ctx)


# ---------------------------------------------------------------------------
# AC-merge-override — executor passes WriteSpec.merge to update_state
# (H-1.5-004)
# ---------------------------------------------------------------------------


async def test_merge_override_replace_passed_to_update_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a write entry carries merge=replace, the executor passes
    merge_overrides={"<field>": "replace"} to update_state."""
    from harness.workflow.schema import WriteSpec

    db = tmp_path / "harness.db"
    state = _base_state(tmp_path)
    await _init_db_with_run(db, state)

    captured_overrides: list[dict[str, str] | None] = []
    real_update = store.update_state

    async def spy_update_state(
        run_id: str,
        schema: type[BaseState],
        *,
        db_path: Path = store.DEFAULT_DB_PATH,
        emit_event: bool = True,
        merge_overrides: dict[str, str] | None = None,
        **fields: Any,
    ) -> BaseState:
        captured_overrides.append(merge_overrides)
        return await real_update(
            run_id,
            schema,
            db_path=db_path,
            emit_event=emit_event,
            merge_overrides=merge_overrides,
            **fields,
        )

    monkeypatch.setattr(
        "harness.engine.executor.update_state",
        spy_update_state,
        raising=True,
    )

    spy = _SpyNode()
    spy.queue(result=_result(_AContract(a=7)))

    # Build an AIStep with a long-form write entry (merge=replace).
    step = AIStep(
        id="s1",
        type="ai",
        prompt="x.j2",
        writes=[WriteSpec(field="a", merge="replace")],
    )
    ctx = _make_ctx(
        db_path=db,
        contracts={step.id: _AContract},
        nodes={"ai": spy.execute},
    )

    await Executor().execute(step, ctx)

    assert len(captured_overrides) == 1
    assert captured_overrides[0] == {"a": "replace"}


async def test_no_merge_override_passes_none_to_update_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When all writes use the short-form (no merge override), the executor
    passes merge_overrides=None to update_state."""
    db = tmp_path / "harness.db"
    state = _base_state(tmp_path)
    await _init_db_with_run(db, state)

    captured_overrides: list[dict[str, str] | None] = []
    real_update = store.update_state

    async def spy_update_state(
        run_id: str,
        schema: type[BaseState],
        *,
        db_path: Path = store.DEFAULT_DB_PATH,
        emit_event: bool = True,
        merge_overrides: dict[str, str] | None = None,
        **fields: Any,
    ) -> BaseState:
        captured_overrides.append(merge_overrides)
        return await real_update(
            run_id,
            schema,
            db_path=db_path,
            emit_event=emit_event,
            merge_overrides=merge_overrides,
            **fields,
        )

    monkeypatch.setattr(
        "harness.engine.executor.update_state",
        spy_update_state,
        raising=True,
    )

    spy = _SpyNode()
    spy.queue(result=_result(_AContract(a=3)))

    step = _ai_step(writes=["a"])
    ctx = _make_ctx(
        db_path=db,
        contracts={step.id: _AContract},
        nodes={"ai": spy.execute},
    )

    await Executor().execute(step, ctx)

    assert len(captured_overrides) == 1
    assert captured_overrides[0] is None
