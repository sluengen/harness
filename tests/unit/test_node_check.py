"""Tests for harness.nodes.check — see SPEC §4.3, §5.

The CheckNode evaluator is exercised end-to-end against real
:class:`BaseState` (and ad-hoc subclasses for derived-state cases).
Nothing is mocked. Each test maps to one acceptance criterion in the
H-016 brief.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ConfigDict

from harness.nodes.base import NodeResult
from harness.nodes.check import CheckNode, CheckNodeError, CheckOutput
from harness.state.schema import BaseState
from harness.workflow.schema import CheckStep

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _state(tmp_path: Path, **overrides: object) -> BaseState:
    """A minimal BaseState; tests override ``workflow_name`` etc."""
    base = {
        "run_id": "run-check-test",
        "workflow_name": "test_workflow",
        "base_branch": "main",
        "artifacts_dir": tmp_path / "artifacts",
        "started_at": datetime.now(UTC),
    }
    base.update(overrides)  # type: ignore[arg-type]
    return BaseState(**base)  # type: ignore[arg-type]


class _DerivedState(BaseState):
    """Stand-in for a workflow-derived state class.

    The framework's :func:`harness.workflow.derive.derive_state_schema`
    builds something like this from a workflow's collected ``writes:``
    declarations; we hand-roll one here so the check tests stay
    independent of the loader.
    """

    model_config = ConfigDict(extra="forbid")

    passed_field: bool = False
    a: bool = False
    b: bool = False
    kind: str = "bug"
    count: int = 0


def _derived_state(tmp_path: Path, **overrides: object) -> _DerivedState:
    base = {
        "run_id": "run-check-test",
        "workflow_name": "test_workflow",
        "base_branch": "main",
        "artifacts_dir": tmp_path / "artifacts",
        "started_at": datetime.now(UTC),
    }
    base.update(overrides)  # type: ignore[arg-type]
    return _DerivedState(**base)  # type: ignore[arg-type]


def _step(expr: str, *, on_fail: str = "cancel", step_id: str = "gate") -> CheckStep:
    return CheckStep(id=step_id, type="check", expr=expr, on_fail=on_fail)


# ---------------------------------------------------------------------------
# AC1 — Node protocol conformance
# ---------------------------------------------------------------------------


def test_ac1_node_type_is_check() -> None:
    """CheckNode declares ``type: Literal['check']``."""
    assert CheckNode().type == "check"


def test_ac1_execute_is_async() -> None:
    node = CheckNode()
    assert inspect.iscoroutinefunction(node.execute)


# ---------------------------------------------------------------------------
# AC2 — trivially-true expression
# ---------------------------------------------------------------------------


async def test_ac2_true_literal_passes(tmp_path: Path) -> None:
    node = CheckNode()
    step = _step("True", on_fail="cancel")

    result: NodeResult[CheckOutput] = await node.execute(
        step=step, state=_state(tmp_path)
    )

    assert result.contract.passed is True
    assert result.contract.expr == "True"
    assert result.contract.on_fail == "cancel"
    assert result.attestation.status == "complete"


# ---------------------------------------------------------------------------
# AC3 — trivially-false expression
# ---------------------------------------------------------------------------


async def test_ac3_false_literal_fails_but_attestation_complete(tmp_path: Path) -> None:
    node = CheckNode()
    step = _step("False", on_fail="cancel")

    result = await node.execute(step=step, state=_state(tmp_path))

    assert result.contract.passed is False
    # Crucial: passed=False is a *successful* evaluation. The attestation
    # must still report `complete`; the executor uses `passed` for routing.
    assert result.attestation.status == "complete"


# ---------------------------------------------------------------------------
# AC4 — state attribute equality
# ---------------------------------------------------------------------------


async def test_ac4_state_string_attribute_equality_true(tmp_path: Path) -> None:
    node = CheckNode()
    state = _state(tmp_path, workflow_name="hello")
    step = _step('state.workflow_name == "hello"')

    result = await node.execute(step=step, state=state)

    assert result.contract.passed is True


async def test_ac4_state_string_attribute_equality_false(tmp_path: Path) -> None:
    node = CheckNode()
    state = _state(tmp_path, workflow_name="hello")
    step = _step('state.workflow_name == "world"')

    result = await node.execute(step=step, state=state)

    assert result.contract.passed is False


# ---------------------------------------------------------------------------
# AC5 — state boolean attribute (derived state)
# ---------------------------------------------------------------------------


async def test_ac5_state_bool_attribute_true(tmp_path: Path) -> None:
    node = CheckNode()
    state = _derived_state(tmp_path, passed_field=True)
    step = _step("state.passed_field")

    result = await node.execute(step=step, state=state)

    assert result.contract.passed is True


async def test_ac5_state_bool_attribute_false(tmp_path: Path) -> None:
    node = CheckNode()
    state = _derived_state(tmp_path, passed_field=False)
    step = _step("state.passed_field")

    result = await node.execute(step=step, state=state)

    assert result.contract.passed is False


# ---------------------------------------------------------------------------
# AC6 — comparison operators
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expr", "count", "expected"),
    [
        ("state.count == 5", 5, True),
        ("state.count == 5", 4, False),
        ("state.count != 5", 4, True),
        ("state.count < 10", 5, True),
        ("state.count <= 5", 5, True),
        ("state.count > 0", 5, True),
        ("state.count >= 5", 5, True),
        ("state.count > 10", 5, False),
        ('state.kind in ["bug", "feature"]', 0, True),
        ('state.kind not in ["chore", "docs"]', 0, True),
    ],
)
async def test_ac6_comparison_operators(
    tmp_path: Path, expr: str, count: int, expected: bool
) -> None:
    node = CheckNode()
    state = _derived_state(tmp_path, count=count)
    step = _step(expr)

    result = await node.execute(step=step, state=state)

    assert result.contract.passed is expected


async def test_ac6_is_and_is_not_with_none(tmp_path: Path) -> None:
    """``is`` / ``is not`` against ``None`` (worktree_path defaults to None)."""
    node = CheckNode()

    is_step = _step("state.worktree_path is None")
    result_is = await node.execute(step=is_step, state=_state(tmp_path))
    assert result_is.contract.passed is True

    isnot_step = _step("state.worktree_path is not None")
    result_isnot = await node.execute(step=isnot_step, state=_state(tmp_path))
    assert result_isnot.contract.passed is False


# ---------------------------------------------------------------------------
# AC7 — boolean composition
# ---------------------------------------------------------------------------


async def test_ac7_and(tmp_path: Path) -> None:
    node = CheckNode()
    state = _derived_state(tmp_path, a=True, b=True)
    step = _step("state.a and state.b")

    result = await node.execute(step=step, state=state)

    assert result.contract.passed is True


async def test_ac7_and_short_circuits_to_false(tmp_path: Path) -> None:
    node = CheckNode()
    state = _derived_state(tmp_path, a=True, b=False)
    step = _step("state.a and state.b")

    result = await node.execute(step=step, state=state)

    assert result.contract.passed is False


async def test_ac7_or(tmp_path: Path) -> None:
    node = CheckNode()
    state = _derived_state(tmp_path, a=False, b=True)
    step = _step("state.a or state.b")

    result = await node.execute(step=step, state=state)

    assert result.contract.passed is True


async def test_ac7_not(tmp_path: Path) -> None:
    node = CheckNode()
    state = _derived_state(tmp_path, a=False)
    step = _step("not state.a")

    result = await node.execute(step=step, state=state)

    assert result.contract.passed is True


# ---------------------------------------------------------------------------
# AC8 — list literal containment
# ---------------------------------------------------------------------------


async def test_ac8_list_literal_in(tmp_path: Path) -> None:
    node = CheckNode()
    state = _derived_state(tmp_path, kind="bug")
    step = _step('state.kind in ["bug", "feature"]')

    result = await node.execute(step=step, state=state)

    assert result.contract.passed is True


async def test_ac8_tuple_literal_in(tmp_path: Path) -> None:
    node = CheckNode()
    state = _derived_state(tmp_path, kind="chore")
    step = _step('state.kind in ("bug", "feature")')

    result = await node.execute(step=step, state=state)

    assert result.contract.passed is False


# ---------------------------------------------------------------------------
# AC9 — on_fail echo
# ---------------------------------------------------------------------------


async def test_ac9_on_fail_retry_loop_preserved(tmp_path: Path) -> None:
    node = CheckNode()
    step = _step("True", on_fail="retry_loop:investigate")

    result = await node.execute(step=step, state=_state(tmp_path))

    assert result.contract.on_fail == "retry_loop:investigate"


# ---------------------------------------------------------------------------
# AC10 — syntax error
# ---------------------------------------------------------------------------


async def test_ac10_syntax_error_raises_with_expr(tmp_path: Path) -> None:
    node = CheckNode()
    step = _step("state.foo ==")  # incomplete expression

    with pytest.raises(CheckNodeError) as excinfo:
        await node.execute(step=step, state=_state(tmp_path))

    msg = str(excinfo.value)
    assert "state.foo ==" in msg


# ---------------------------------------------------------------------------
# AC11 — disallowed AST nodes
# ---------------------------------------------------------------------------


async def test_ac11_function_call_rejected(tmp_path: Path) -> None:
    node = CheckNode()
    step = _step("len(state.notes) > 0")

    with pytest.raises(CheckNodeError) as excinfo:
        await node.execute(step=step, state=_state(tmp_path))

    assert "Call" in str(excinfo.value)


async def test_ac11_subscript_rejected(tmp_path: Path) -> None:
    node = CheckNode()
    step = _step("state.notes[0]")

    with pytest.raises(CheckNodeError) as excinfo:
        await node.execute(step=step, state=_state(tmp_path))

    assert "Subscript" in str(excinfo.value) or "disallowed" in str(excinfo.value)


async def test_ac11_dunder_attribute_rejected(tmp_path: Path) -> None:
    node = CheckNode()
    step = _step("state.__class__")

    with pytest.raises(CheckNodeError) as excinfo:
        await node.execute(step=step, state=_state(tmp_path))

    assert "__class__" in str(excinfo.value) or "dunder" in str(excinfo.value).lower()


async def test_ac11_non_state_name_rejected(tmp_path: Path) -> None:
    node = CheckNode()
    step = _step("os.getcwd()")

    with pytest.raises(CheckNodeError) as excinfo:
        await node.execute(step=step, state=_state(tmp_path))

    # Either the Name(os) is rejected first or Call is — both acceptable.
    msg = str(excinfo.value)
    assert "os" in msg or "Call" in msg or "disallowed" in msg


async def test_ac11_dict_literal_rejected(tmp_path: Path) -> None:
    """A dict literal isn't on the allow-list and must be rejected."""
    node = CheckNode()
    step = _step('{"a": 1} == state.workflow_name')

    with pytest.raises(CheckNodeError):
        await node.execute(step=step, state=_state(tmp_path))


async def test_ac11_lambda_rejected(tmp_path: Path) -> None:
    node = CheckNode()
    step = _step("(lambda: True)()")

    with pytest.raises(CheckNodeError):
        await node.execute(step=step, state=_state(tmp_path))


# ---------------------------------------------------------------------------
# AC12 — missing attribute
# ---------------------------------------------------------------------------


async def test_ac12_missing_state_attribute_raises(tmp_path: Path) -> None:
    """A BaseState (not derived) genuinely lacks ``fictitious``."""
    node = CheckNode()
    step = _step("state.fictitious")

    with pytest.raises(CheckNodeError) as excinfo:
        await node.execute(step=step, state=_state(tmp_path))

    assert "fictitious" in str(excinfo.value)


# ---------------------------------------------------------------------------
# AC13 — non-bool result
# ---------------------------------------------------------------------------


async def test_ac13_non_bool_result_raises(tmp_path: Path) -> None:
    """``state.workflow_name`` is a str — must not be coerced to bool."""
    node = CheckNode()
    step = _step("state.workflow_name")

    with pytest.raises(CheckNodeError) as excinfo:
        await node.execute(step=step, state=_state(tmp_path))

    msg = str(excinfo.value).lower()
    assert "bool" in msg


# ---------------------------------------------------------------------------
# AC14 — malformed on_fail
# ---------------------------------------------------------------------------


async def test_ac14_malformed_on_fail_rejected(tmp_path: Path) -> None:
    node = CheckNode()
    step = _step("True", on_fail="explode")

    with pytest.raises(CheckNodeError) as excinfo:
        await node.execute(step=step, state=_state(tmp_path))

    assert "on_fail" in str(excinfo.value).lower() or "explode" in str(excinfo.value)


async def test_ac14_empty_retry_loop_id_rejected(tmp_path: Path) -> None:
    node = CheckNode()
    step = _step("True", on_fail="retry_loop:")

    with pytest.raises(CheckNodeError):
        await node.execute(step=step, state=_state(tmp_path))


# ---------------------------------------------------------------------------
# AC15 — valid on_fail formats accepted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "on_fail",
    [
        "cancel",
        "continue",
        "retry_loop:foo",
        "retry_loop:bar-1",
        "retry_loop:investigate_more",
    ],
)
async def test_ac15_valid_on_fail_accepted(tmp_path: Path, on_fail: str) -> None:
    node = CheckNode()
    step = _step("True", on_fail=on_fail)

    result = await node.execute(step=step, state=_state(tmp_path))

    assert result.contract.on_fail == on_fail
    assert result.contract.passed is True
