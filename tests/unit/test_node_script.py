"""Tests for harness.nodes.script — see SPEC §4.3, §5.

Real subprocesses are exercised; nothing is mocked. Each test maps to one
acceptance criterion in the H-015 brief.

H-027 extends the suite with three tests for the optional
``contract_override`` parameter — when supplied, ScriptNode parses stdout
as JSON and validates it against the override Pydantic model, returning
a NodeResult whose contract is the override instance.
"""

from __future__ import annotations

import inspect
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

from harness.nodes.base import NodeResult
from harness.nodes.script import (
    ScriptNode,
    ScriptNodeError,
    ScriptOutput,
)
from harness.state.schema import BaseState
from harness.workflow.schema import ScriptStep

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _state(tmp_path: Path, **overrides: object) -> BaseState:
    """A minimal BaseState; tests override worktree_path or extra fields."""
    base = {
        "run_id": "run-script-test",
        "workflow_name": "test_workflow",
        "base_branch": "main",
        "artifacts_dir": tmp_path / "artifacts",
        "started_at": datetime.now(UTC),
    }
    base.update(overrides)  # type: ignore[arg-type]
    return BaseState(**base)  # type: ignore[arg-type]


def _step(**fields: object) -> ScriptStep:
    """Build a ScriptStep with sensible defaults."""
    payload: dict[str, object] = {"id": "test-step", "type": "script"}
    payload.update(fields)
    return ScriptStep(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC1 — Node protocol conformance
# ---------------------------------------------------------------------------


def test_ac1_node_type_is_script() -> None:
    """ScriptNode declares ``type: Literal['script']``."""
    assert ScriptNode().type == "script"


def test_ac1_execute_is_async() -> None:
    node = ScriptNode()
    assert inspect.iscoroutinefunction(node.execute)


# ---------------------------------------------------------------------------
# AC2 — bash command success
# ---------------------------------------------------------------------------


async def test_ac2_bash_command_success_captures_stdout(tmp_path: Path) -> None:
    node = ScriptNode()
    step = _step(runtime="bash", command="echo hello")

    result: NodeResult[ScriptOutput] = await node.execute(
        step=step, state=_state(tmp_path)
    )

    assert result.contract.stdout == "hello\n"
    assert result.contract.stderr == ""
    assert result.contract.exit_code == 0
    assert result.attestation.status == "complete"


# ---------------------------------------------------------------------------
# AC3 — non-zero exit raises
# ---------------------------------------------------------------------------


async def test_ac3_non_zero_exit_raises_with_exit_code_and_stderr(
    tmp_path: Path,
) -> None:
    node = ScriptNode()
    step = _step(runtime="bash", command="echo boom >&2; exit 7")

    with pytest.raises(ScriptNodeError) as excinfo:
        await node.execute(step=step, state=_state(tmp_path))

    msg = str(excinfo.value)
    assert "7" in msg
    assert "boom" in msg


# ---------------------------------------------------------------------------
# AC4 — bash script path with args
# ---------------------------------------------------------------------------


async def test_ac4_bash_script_path_with_args(tmp_path: Path) -> None:
    script = tmp_path / "echo.sh"
    script.write_text("#!/bin/bash\necho hi $1\n")
    script.chmod(0o755)

    node = ScriptNode()
    step = _step(runtime="bash", script=str(script), args=["world"])

    result = await node.execute(step=step, state=_state(tmp_path))

    assert result.contract.stdout == "hi world\n"
    assert result.contract.exit_code == 0


# ---------------------------------------------------------------------------
# AC5 — python script path
# ---------------------------------------------------------------------------


async def test_ac5_python_script_path(tmp_path: Path) -> None:
    script = tmp_path / "echo.py"
    script.write_text('print("py", end="")\n')

    node = ScriptNode()
    step = _step(runtime="python", script=str(script))

    result = await node.execute(step=step, state=_state(tmp_path))

    assert result.contract.stdout == "py"
    assert result.contract.exit_code == 0


# ---------------------------------------------------------------------------
# AC6 — python -c command
# ---------------------------------------------------------------------------


async def test_ac6_python_dash_c_command(tmp_path: Path) -> None:
    node = ScriptNode()
    step = _step(runtime="python", command='import sys; print("z")')

    result = await node.execute(step=step, state=_state(tmp_path))

    assert result.contract.stdout == "z\n"
    assert result.contract.exit_code == 0


# ---------------------------------------------------------------------------
# AC7 — stderr captured
# ---------------------------------------------------------------------------


async def test_ac7_stderr_captured(tmp_path: Path) -> None:
    node = ScriptNode()
    step = _step(runtime="bash", command="echo err >&2; exit 0")

    result = await node.execute(step=step, state=_state(tmp_path))

    assert result.contract.stdout == ""
    assert result.contract.stderr == "err\n"
    assert result.contract.exit_code == 0


# ---------------------------------------------------------------------------
# AC8 — cwd resolution (step.cwd, state.worktree_path, neither)
# ---------------------------------------------------------------------------


async def test_ac8_cwd_from_step_cwd(tmp_path: Path) -> None:
    """``step.cwd`` (when set) is the subprocess working directory."""
    sub = tmp_path / "explicit"
    sub.mkdir()
    node = ScriptNode()
    step = _step(runtime="bash", command="pwd", cwd=str(sub))

    result = await node.execute(step=step, state=_state(tmp_path))

    # macOS may resolve /tmp to /private/tmp; compare via Path resolution.
    assert Path(result.contract.stdout.strip()).resolve() == sub.resolve()


async def test_ac8_cwd_from_state_worktree_path_when_step_cwd_missing(
    tmp_path: Path,
) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    node = ScriptNode()
    step = _step(runtime="bash", command="pwd")

    result = await node.execute(
        step=step, state=_state(tmp_path, worktree_path=wt)
    )

    assert Path(result.contract.stdout.strip()).resolve() == wt.resolve()


async def test_ac8_cwd_falls_back_to_process_cwd_when_neither_set(
    tmp_path: Path,
) -> None:
    """No step.cwd, no state.worktree_path → cwd defaults to process cwd."""
    node = ScriptNode()
    step = _step(runtime="bash", command="pwd")

    result = await node.execute(step=step, state=_state(tmp_path))

    assert Path(result.contract.stdout.strip()).resolve() == Path(os.getcwd()).resolve()


# ---------------------------------------------------------------------------
# AC9 — arg substitution
# ---------------------------------------------------------------------------


async def test_ac9_arg_substitution_state_and_inputs(tmp_path: Path) -> None:
    script = tmp_path / "show.sh"
    script.write_text('#!/bin/bash\necho "$1 $2"\n')
    script.chmod(0o755)

    node = ScriptNode()
    step = _step(
        runtime="bash",
        script=str(script),
        args=["$state.run_id", "$inputs.bar"],
    )
    state = _state(tmp_path)
    state = state.model_copy(update={"run_id": "X"})

    result = await node.execute(step=step, state=state, inputs={"bar": "Y"})

    assert result.contract.stdout == "X Y\n"


# ---------------------------------------------------------------------------
# AC10 — missing variable raises
# ---------------------------------------------------------------------------


async def test_ac10_missing_state_field_raises_clean(tmp_path: Path) -> None:
    node = ScriptNode()
    step = _step(runtime="bash", command="true", args=["$state.does_not_exist"])

    with pytest.raises(ScriptNodeError) as excinfo:
        await node.execute(step=step, state=_state(tmp_path))

    msg = str(excinfo.value)
    assert "does_not_exist" in msg
    assert "state" in msg


async def test_ac10_missing_inputs_key_raises_clean(tmp_path: Path) -> None:
    node = ScriptNode()
    step = _step(runtime="bash", command="true", args=["$inputs.nope"])

    with pytest.raises(ScriptNodeError) as excinfo:
        await node.execute(step=step, state=_state(tmp_path), inputs={})

    msg = str(excinfo.value)
    assert "nope" in msg
    assert "inputs" in msg


# ---------------------------------------------------------------------------
# AC11 — timeout
# ---------------------------------------------------------------------------


async def test_ac11_timeout_kills_process_and_raises(tmp_path: Path) -> None:
    node = ScriptNode(timeout_s=1.0)
    step = _step(runtime="bash", command="sleep 5")

    with pytest.raises(ScriptNodeError) as excinfo:
        await node.execute(step=step, state=_state(tmp_path))

    assert "timed out" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# AC12 — stdout truncation
# ---------------------------------------------------------------------------


async def test_ac12_stdout_truncated_when_over_cap(tmp_path: Path) -> None:
    """Output exceeding ``max_output_bytes`` is truncated with a marker."""
    node = ScriptNode(max_output_bytes=64)
    # Print 200 bytes of "A".
    step = _step(
        runtime="python",
        command='import sys; sys.stdout.write("A" * 200)',
    )

    result = await node.execute(step=step, state=_state(tmp_path))

    assert len(result.contract.stdout.encode("utf-8")) > 64  # marker added
    # Truncation marker is human-visible.
    assert "truncated" in result.contract.stdout.lower()
    # The head of the captured output is preserved.
    assert result.contract.stdout.startswith("A" * 64)


# ---------------------------------------------------------------------------
# H-027 — contract_override seam (mirrors AINode / DecisionNode)
#
# When the executor wants a script's stdout treated as a typed payload — e.g.
# the steward workflow's ``write-report`` step that declares
# ``contract: { report_path: string }`` — it passes ``contract_override``.
# ScriptNode parses stdout as JSON, validates against the override, and
# returns NodeResult[override]. The three failure modes (no contract, bad
# JSON, schema mismatch) each have a distinct expected error.
# ---------------------------------------------------------------------------


class _ReportContract(BaseModel):
    report_path: str


async def test_contract_override_parses_json_stdout_against_model(
    tmp_path: Path,
) -> None:
    """Script prints valid JSON matching the override schema → NodeResult
    whose contract is an instance of the override class."""
    node = ScriptNode()
    step = _step(
        runtime="python",
        command='import json; print(json.dumps({"report_path": "/tmp/report.md"}))',
    )

    result = await node.execute(
        step=step,
        state=_state(tmp_path),
        contract_override=_ReportContract,
    )

    assert isinstance(result.contract, _ReportContract)
    assert result.contract.report_path == "/tmp/report.md"
    assert result.attestation.status == "complete"


async def test_contract_override_malformed_json_raises_clean(
    tmp_path: Path,
) -> None:
    """Script prints non-JSON → raises with a message that includes the
    head of stdout so the workflow author can spot the offending line."""
    node = ScriptNode()
    step = _step(runtime="python", command='print("not json at all")')

    with pytest.raises(ScriptNodeError) as excinfo:
        await node.execute(
            step=step,
            state=_state(tmp_path),
            contract_override=_ReportContract,
        )

    msg = str(excinfo.value)
    assert "json" in msg.lower()
    assert "not json" in msg


async def test_contract_override_schema_mismatch_raises_clean(
    tmp_path: Path,
) -> None:
    """Script prints valid JSON but missing the required field →
    raises with a Pydantic-derived message."""
    node = ScriptNode()
    step = _step(
        runtime="python",
        command='import json; print(json.dumps({"wrong_key": "x"}))',
    )

    with pytest.raises(ScriptNodeError) as excinfo:
        await node.execute(
            step=step,
            state=_state(tmp_path),
            contract_override=_ReportContract,
        )

    msg = str(excinfo.value)
    # Pydantic's error message will mention the missing field or the
    # extra key. Either is acceptable evidence the validation fired.
    assert "report_path" in msg or "validation" in msg.lower()


async def test_contract_override_none_preserves_legacy_behaviour(
    tmp_path: Path,
) -> None:
    """Without ``contract_override`` ScriptNode still returns
    ``NodeResult[ScriptOutput]`` exactly as before — load-bearing for
    every existing script step in the codebase."""
    node = ScriptNode()
    step = _step(runtime="bash", command='echo "free-form text"')

    result = await node.execute(step=step, state=_state(tmp_path))

    assert isinstance(result.contract, ScriptOutput)
    assert result.contract.stdout == "free-form text\n"
