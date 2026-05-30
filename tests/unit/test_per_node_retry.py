"""Tests for per-node retry configuration — H-1.5-005.

YAML knobs (``retry.transient.attempts: N``) override v1's fixed defaults
on a per-step basis.  Acceptance criteria:

AC1  ``RetryTransientConfig`` accepts a positive integer ``attempts``.
AC2  ``RetryConfig`` with ``transient:`` block parses correctly; bare form also valid.
AC3  All ``_BaseStep`` subclasses accept an optional ``retry:`` field.
AC4  Steps without ``retry:`` remain unchanged (backwards compat, default=None).
AC5  ``retry.transient.attempts`` is carried through to the schema model.
AC6  Extra fields inside ``RetryConfig`` / ``RetryTransientConfig`` are rejected.
AC7  ``retry.transient.attempts`` must be ≥ 1.
AC8  Executor uses per-step ``retry.transient.attempts`` when set, producing that many
     node calls on repeated transient failures.
AC9  Executor falls back to the default 3-attempt policy when the step has no
     ``retry:`` field.
AC10 Only ``transient_attempts`` is overridden; ``contract_violation_attempts`` stays
     at the v1 default (2) even when ``retry.transient.attempts`` is set.
AC11 Round-trip via ``Workflow.model_validate`` with raw YAML dict works end-to-end.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from harness.workflow.schema import (
    AIStep,
    CheckStep,
    DecisionStep,
    LoopBlock,
    LoopStep,
    RetryConfig,
    RetryTransientConfig,
    ScriptStep,
    Workflow,
    WorktreeStep,
)

# ---------------------------------------------------------------------------
# AC1 — RetryTransientConfig
# ---------------------------------------------------------------------------


def test_ac1_retry_transient_config_accepts_positive_attempts() -> None:
    """RetryTransientConfig(attempts=5) is valid."""
    cfg = RetryTransientConfig(attempts=5)
    assert cfg.attempts == 5


def test_ac1_retry_transient_config_none_attempts_is_valid() -> None:
    """attempts=None means 'use the global default' — should be accepted."""
    cfg = RetryTransientConfig(attempts=None)
    assert cfg.attempts is None


def test_ac1_retry_transient_config_defaults_to_none() -> None:
    """With no args, attempts defaults to None (inherit from global policy)."""
    cfg = RetryTransientConfig()
    assert cfg.attempts is None


# ---------------------------------------------------------------------------
# AC2 — RetryConfig
# ---------------------------------------------------------------------------


def test_ac2_retry_config_with_transient_block() -> None:
    """RetryConfig with a transient sub-block parses correctly."""
    cfg = RetryConfig(transient=RetryTransientConfig(attempts=4))
    assert cfg.transient is not None
    assert cfg.transient.attempts == 4


def test_ac2_retry_config_bare_no_transient() -> None:
    """RetryConfig() with no transient block is valid; transient defaults to None."""
    cfg = RetryConfig()
    assert cfg.transient is None


def test_ac2_retry_config_from_dict() -> None:
    """RetryConfig can be constructed from a plain dict (as YAML would provide)."""
    cfg = RetryConfig.model_validate({"transient": {"attempts": 2}})
    assert cfg.transient is not None
    assert cfg.transient.attempts == 2


# ---------------------------------------------------------------------------
# AC3 + AC4 — Step acceptance and backward compat
# ---------------------------------------------------------------------------


def test_ac3_ai_step_accepts_retry_field() -> None:
    """AIStep accepts ``retry: RetryConfig``."""
    step = AIStep(
        type="ai",
        id="s",
        prompt="p.j2",
        retry=RetryConfig(transient=RetryTransientConfig(attempts=5)),
    )
    assert step.retry is not None
    assert step.retry.transient is not None
    assert step.retry.transient.attempts == 5


def test_ac4_ai_step_without_retry_defaults_to_none() -> None:
    """AIStep without ``retry:`` still works; ``retry`` defaults to None."""
    step = AIStep(type="ai", id="s", prompt="p.j2")
    assert step.retry is None


def test_ac3_script_step_accepts_retry_field() -> None:
    """ScriptStep accepts ``retry: RetryConfig``."""
    step = ScriptStep(
        type="script",
        id="s",
        command="pytest",
        retry=RetryConfig(transient=RetryTransientConfig(attempts=2)),
    )
    assert step.retry is not None
    assert step.retry.transient is not None
    assert step.retry.transient.attempts == 2


def test_ac3_check_step_accepts_retry_field() -> None:
    """CheckStep accepts ``retry: RetryConfig``."""
    step = CheckStep(
        type="check",
        id="gate",
        expr="True",
        retry=RetryConfig(transient=RetryTransientConfig(attempts=1)),
    )
    assert step.retry is not None


def test_ac3_decision_step_accepts_retry_field() -> None:
    """DecisionStep accepts ``retry: RetryConfig``."""
    step = DecisionStep(
        type="decision",
        id="proceed",
        actor="llm",
        prompt="p.j2",
        retry=RetryConfig(transient=RetryTransientConfig(attempts=3)),
    )
    assert step.retry is not None


def test_ac3_worktree_step_accepts_retry_field() -> None:
    """WorktreeStep accepts ``retry: RetryConfig``."""
    step = WorktreeStep(
        type="worktree",
        id="setup",
        action="create",
        base="main",
        retry=RetryConfig(transient=RetryTransientConfig(attempts=2)),
    )
    assert step.retry is not None


def test_ac3_loop_step_accepts_retry_field() -> None:
    """LoopStep accepts ``retry: RetryConfig``."""
    step = LoopStep(
        type="loop",
        id="impl",
        retry=RetryConfig(transient=RetryTransientConfig(attempts=4)),
        loop=LoopBlock(
            max_iterations=3,
            until="state.done",
            steps=[AIStep(type="ai", id="work", prompt="p.j2")],
        ),
    )
    assert step.retry is not None


# ---------------------------------------------------------------------------
# AC5 — attempts value propagated correctly
# ---------------------------------------------------------------------------


def test_ac5_retry_transient_attempts_carried_through_model() -> None:
    """The attempts value set in YAML is accessible after model_validate."""
    step = AIStep.model_validate(
        {
            "type": "ai",
            "id": "s",
            "prompt": "p.j2",
            "retry": {"transient": {"attempts": 7}},
        }
    )
    assert step.retry is not None
    assert step.retry.transient is not None
    assert step.retry.transient.attempts == 7


# ---------------------------------------------------------------------------
# AC6 — extra fields rejected
# ---------------------------------------------------------------------------


def test_ac6_retry_transient_config_rejects_extra_fields() -> None:
    """Extra fields inside RetryTransientConfig are rejected (extra='forbid')."""
    with pytest.raises(ValidationError, match="extra"):
        RetryTransientConfig.model_validate({"attempts": 3, "garbage": True})


def test_ac6_retry_config_rejects_extra_fields() -> None:
    """Extra fields inside RetryConfig are rejected (extra='forbid')."""
    with pytest.raises(ValidationError, match="extra"):
        RetryConfig.model_validate({"transient": {"attempts": 3}, "unknown": True})


# ---------------------------------------------------------------------------
# AC7 — attempts must be ≥ 1
# ---------------------------------------------------------------------------


def test_ac7_retry_transient_config_rejects_zero_attempts() -> None:
    """attempts=0 is rejected; must be a positive integer."""
    with pytest.raises(ValidationError):
        RetryTransientConfig(attempts=0)


def test_ac7_retry_transient_config_rejects_negative_attempts() -> None:
    """attempts=-1 is rejected."""
    with pytest.raises(ValidationError):
        RetryTransientConfig(attempts=-1)


# ---------------------------------------------------------------------------
# AC8 — Executor respects per-step transient_attempts
# ---------------------------------------------------------------------------


async def test_ac8_executor_uses_per_step_retry_transient_attempts(
    tmp_path: Path,
) -> None:
    """Step with ``retry.transient.attempts=5`` → 5 node calls on repeated OSError.

    The executor builds a per-step policy from the step's ``retry`` config,
    overriding the v1 default of 3 attempts.
    """
    from datetime import UTC, datetime

    from pydantic import BaseModel, ConfigDict

    from harness.engine.executor import Context, Executor
    from harness.nodes.base import NodeResult
    from harness.state import store
    from harness.state.schema import BaseState
    from harness.workflow.schema import Step

    class _S(BaseState):
        model_config = ConfigDict(extra="forbid")

    db = tmp_path / "harness.db"
    run_id = "R1"
    state = _S(
        run_id=run_id,
        workflow_name="test",
        base_branch="main",
        artifacts_dir=tmp_path / "art",
        started_at=datetime.now(UTC),
    )
    await store.init_db(db)
    async with store.connect(db) as conn:
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, started_at) VALUES (?,?,?,?,?,?,?)",
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

    calls = 0

    async def always_fails(
        step: Step, s: BaseState, ctx: Context
    ) -> NodeResult[BaseModel]:
        nonlocal calls
        calls += 1
        raise OSError("network blip")

    step = AIStep(
        type="ai",
        id="s1",
        prompt="p.j2",
        retry=RetryConfig(transient=RetryTransientConfig(attempts=5)),
    )
    ctx = Context(
        run_id=run_id,
        db_path=db,
        contracts={},
        state_schema=_S,
        nodes={"ai": always_fails},
    )

    with pytest.raises(OSError):
        await Executor().execute(step, ctx)

    # 5 attempts total (1 original + 4 retries).
    assert calls == 5


# ---------------------------------------------------------------------------
# AC9 — Executor falls back to default when no retry config on step
# ---------------------------------------------------------------------------


async def test_ac9_executor_uses_default_when_no_retry_field_on_step(
    tmp_path: Path,
) -> None:
    """Step without ``retry:`` gets the v1 default of 3 transient attempts."""
    from datetime import UTC, datetime

    from pydantic import BaseModel, ConfigDict

    from harness.engine.executor import Context, Executor
    from harness.nodes.base import NodeResult
    from harness.state import store
    from harness.state.schema import BaseState
    from harness.workflow.schema import Step

    class _S2(BaseState):
        model_config = ConfigDict(extra="forbid")

    db = tmp_path / "harness.db"
    run_id = "R1"
    state = _S2(
        run_id=run_id,
        workflow_name="test",
        base_branch="main",
        artifacts_dir=tmp_path / "art",
        started_at=datetime.now(UTC),
    )
    await store.init_db(db)
    async with store.connect(db) as conn:
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, started_at) VALUES (?,?,?,?,?,?,?)",
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

    calls = 0

    async def always_fails(
        step: Step, s: BaseState, ctx: Context
    ) -> NodeResult[BaseModel]:
        nonlocal calls
        calls += 1
        raise OSError("network blip")

    # No ``retry:`` on this step — should use default 3 attempts.
    step = AIStep(type="ai", id="s1", prompt="p.j2")
    ctx = Context(
        run_id=run_id,
        db_path=db,
        contracts={},
        state_schema=_S2,
        nodes={"ai": always_fails},
    )

    with pytest.raises(OSError):
        await Executor().execute(step, ctx)

    assert calls == 3


# ---------------------------------------------------------------------------
# AC10 — Only transient_attempts overridden; contract_violation_attempts stays at 2
# ---------------------------------------------------------------------------


async def test_ac10_only_transient_attempts_overridden(
    tmp_path: Path,
) -> None:
    """Step with ``retry.transient.attempts=5`` leaves contract_violation_attempts at 2.

    Verify by exhausting the contract-violation budget: 2 ContractViolation
    raises → 2 calls total (1 original + 1 retry). The transient override of 5
    should not bleed into the contract-violation layer.
    """
    from datetime import UTC, datetime

    from pydantic import BaseModel, ConfigDict

    from harness.dispatch.claude import ContractViolation
    from harness.engine.executor import Context, Executor
    from harness.nodes.base import NodeResult
    from harness.state import store
    from harness.state.schema import BaseState
    from harness.workflow.schema import Step

    class _S3(BaseState):
        model_config = ConfigDict(extra="forbid")

    db = tmp_path / "harness.db"
    run_id = "R1"
    state = _S3(
        run_id=run_id,
        workflow_name="test",
        base_branch="main",
        artifacts_dir=tmp_path / "art",
        started_at=datetime.now(UTC),
    )
    await store.init_db(db)
    async with store.connect(db) as conn:
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, started_at) VALUES (?,?,?,?,?,?,?)",
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

    calls = 0

    async def always_contract_violation(
        step: Step, s: BaseState, ctx: Context
    ) -> NodeResult[BaseModel]:
        nonlocal calls
        calls += 1
        raise ContractViolation("validation_failed")

    # transient.attempts=5 — should NOT affect contract_violation budget (stays 2).
    step = AIStep(
        type="ai",
        id="s1",
        prompt="p.j2",
        retry=RetryConfig(transient=RetryTransientConfig(attempts=5)),
    )
    ctx = Context(
        run_id=run_id,
        db_path=db,
        contracts={},
        state_schema=_S3,
        nodes={"ai": always_contract_violation},
    )

    with pytest.raises(ContractViolation):
        await Executor().execute(step, ctx)

    # Default contract_violation_attempts=2 → 2 total calls.
    assert calls == 2


# ---------------------------------------------------------------------------
# AC11 — Workflow round-trip via model_validate
# ---------------------------------------------------------------------------


def test_ac11_workflow_round_trip_with_retry_config() -> None:
    """Full YAML-shaped dict with ``retry.transient.attempts`` survives
    ``Workflow.model_validate`` and produces the correct step retry config."""
    raw: dict[str, Any] = {
        "name": "feature",
        "version": 1,
        "steps": [
            {
                "id": "implement",
                "type": "ai",
                "prompt": "p.j2",
                "retry": {"transient": {"attempts": 6}},
            },
            {
                "id": "test",
                "type": "script",
                "command": "pytest",
                # no retry — should default to None
            },
        ],
    }
    wf = Workflow.model_validate(raw)
    assert isinstance(wf.steps[0], AIStep)
    assert wf.steps[0].retry is not None
    assert wf.steps[0].retry.transient is not None
    assert wf.steps[0].retry.transient.attempts == 6

    assert isinstance(wf.steps[1], ScriptStep)
    assert wf.steps[1].retry is None
