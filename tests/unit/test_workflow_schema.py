"""Tests for harness.workflow.schema — Pydantic models for SPEC §5."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from harness.workflow.schema import (
    AIStep,
    CheckStep,
    DecisionStep,
    InputSpec,
    LoopBlock,
    LoopStep,
    ScriptStep,
    Workflow,
    WorktreeStep,
    WriteSpec,
)

# ---------------------------------------------------------------------------
# InputSpec
# ---------------------------------------------------------------------------


def test_input_spec_minimal() -> None:
    inp = InputSpec(type="string")
    assert inp.type == "string"
    assert inp.required is True
    assert inp.flag is None
    assert inp.position is None


def test_input_spec_with_flag() -> None:
    inp = InputSpec(type="string", flag="--linear", required=False)
    assert inp.flag == "--linear"


def test_input_spec_with_position() -> None:
    inp = InputSpec(type="string", position=1, required=False)
    assert inp.position == 1


def test_input_spec_rejects_both_flag_and_position() -> None:
    with pytest.raises(ValidationError, match="both `flag` and `position`"):
        InputSpec(type="string", flag="--x", position=1)


def test_input_spec_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        InputSpec(type="float")  # type: ignore[arg-type]


def test_input_spec_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="extra"):
        InputSpec.model_validate({"type": "string", "garbage": True})


# ---------------------------------------------------------------------------
# AIStep
# ---------------------------------------------------------------------------


def test_ai_step_minimal() -> None:
    step = AIStep(type="ai", id="investigate", prompt="prompts/foo.j2")
    assert step.allowed_tools == ["Read", "Grep", "Glob"]
    assert step.stall_timeout_s == 300
    assert step.timeout_s == 600
    assert step.writes_files is False


def test_ai_step_with_inline_contract() -> None:
    step = AIStep(
        type="ai",
        id="x",
        prompt="p.j2",
        contract={"summary": "string", "items": {"type": "list", "of": "string"}},
        writes=["summary", "items"],
    )
    assert isinstance(step.contract, dict)
    # writes is normalised to list[WriteSpec]; field names match originals.
    assert [w.field for w in step.writes] == ["summary", "items"]


def test_ai_step_with_dotted_contract_reference() -> None:
    step = AIStep(
        type="ai",
        id="x",
        prompt="p.j2",
        contract="$contracts/review-verdict",
    )
    assert step.contract == "$contracts/review-verdict"


# ---------------------------------------------------------------------------
# ScriptStep
# ---------------------------------------------------------------------------


def test_script_step_with_command() -> None:
    step = ScriptStep(type="script", id="t", command="pytest -x")
    assert step.runtime == "bash"


def test_script_step_with_script_and_python_runtime() -> None:
    step = ScriptStep(
        type="script", id="x", script="scripts/fetch.py", runtime="python"
    )
    assert step.runtime == "python"


def test_script_step_requires_command_or_script() -> None:
    with pytest.raises(ValidationError, match="`command` or `script`"):
        ScriptStep(type="script", id="x")


def test_script_step_rejects_both_command_and_script() -> None:
    with pytest.raises(ValidationError, match="cannot declare both"):
        ScriptStep(type="script", id="x", command="ls", script="s.py")


# ---------------------------------------------------------------------------
# CheckStep
# ---------------------------------------------------------------------------


def test_check_step() -> None:
    step = CheckStep(type="check", id="gate", expr="state.tests_pass == True")
    assert step.on_fail == "cancel"


# ---------------------------------------------------------------------------
# DecisionStep
# ---------------------------------------------------------------------------


def test_decision_llm_minimal() -> None:
    step = DecisionStep(
        type="decision",
        id="proceed",
        actor="llm",
        prompt="prompts/can_proceed.j2",
        contract={"decision": "boolean", "reasoning": "string"},
    )
    assert step.actor == "llm"
    assert step.on_reject == "cancel"


def test_decision_llm_requires_prompt() -> None:
    with pytest.raises(ValidationError, match="actor=llm requires `prompt`"):
        DecisionStep(type="decision", id="x", actor="llm")


def test_decision_human_minimal() -> None:
    step = DecisionStep(
        type="decision",
        id="confirm",
        actor="human",
        message="Approve this report?",
        via="cli",
    )
    assert step.actor == "human"


def test_decision_human_requires_message() -> None:
    with pytest.raises(ValidationError, match="actor=human requires `message`"):
        DecisionStep(type="decision", id="x", actor="human", via="cli")


# ---------------------------------------------------------------------------
# WorktreeStep
# ---------------------------------------------------------------------------


def test_worktree_create() -> None:
    step = WorktreeStep(type="worktree", id="setup", action="create", base="main")
    assert step.action == "create"


def test_worktree_create_requires_base() -> None:
    with pytest.raises(ValidationError, match="action=create requires `base`"):
        WorktreeStep(type="worktree", id="x", action="create")


def test_worktree_cleanup() -> None:
    step = WorktreeStep(
        type="worktree", id="teardown", action="cleanup", policy="merge_to_base"
    )
    assert step.policy == "merge_to_base"


def test_worktree_cleanup_requires_policy() -> None:
    with pytest.raises(ValidationError, match="action=cleanup requires `policy`"):
        WorktreeStep(type="worktree", id="x", action="cleanup")


# ---------------------------------------------------------------------------
# LoopStep + LoopBlock
# ---------------------------------------------------------------------------


def test_loop_step_with_nested_steps() -> None:
    step = LoopStep(
        type="loop",
        id="implement-and-test",
        loop=LoopBlock(
            max_iterations=5,
            until="state.tests_pass",
            steps=[
                AIStep(type="ai", id="implement", prompt="p.j2", writes_files=True),
                ScriptStep(type="script", id="run-tests", command="pytest -x"),
            ],
        ),
    )
    assert len(step.loop.steps) == 2


def test_loop_block_rejects_zero_max_iterations() -> None:
    with pytest.raises(ValidationError):
        LoopBlock(max_iterations=0, until="x", steps=[])


# ---------------------------------------------------------------------------
# Workflow root + discriminated union
# ---------------------------------------------------------------------------


def test_workflow_minimal() -> None:
    wf = Workflow(
        name="bugfix",
        version=1,
        steps=[ScriptStep(type="script", id="run", command="ls")],
    )
    assert wf.name == "bugfix"
    assert wf.description == ""


def test_workflow_rejects_invalid_name() -> None:
    with pytest.raises(ValidationError):
        Workflow(
            name="Bug-Fix",  # capital letter not allowed
            version=1,
            steps=[ScriptStep(type="script", id="r", command="ls")],
        )


def test_workflow_rejects_zero_version() -> None:
    with pytest.raises(ValidationError):
        Workflow(
            name="x", version=0, steps=[ScriptStep(type="script", id="r", command="ls")]
        )


def test_workflow_rejects_empty_steps() -> None:
    with pytest.raises(ValidationError):
        Workflow(name="x", version=1, steps=[])


def test_workflow_rejects_duplicate_step_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate step ids"):
        Workflow(
            name="x",
            version=1,
            steps=[
                ScriptStep(type="script", id="dup", command="a"),
                ScriptStep(type="script", id="dup", command="b"),
            ],
        )


def test_workflow_dispatches_via_discriminator() -> None:
    """Validate from raw dict — ensures discriminator picks the right Step subclass."""
    raw = {
        "name": "feature",
        "version": 1,
        "inputs": {"linear_id": {"type": "string", "flag": "--linear"}},
        "steps": [
            {"id": "setup", "type": "worktree", "action": "create", "base": "main"},
            {
                "id": "investigate",
                "type": "ai",
                "prompt": "prompts/x.j2",
                "contract": {"root_cause": "string"},
                "writes": ["root_cause"],
            },
            {
                "id": "loop",
                "type": "loop",
                "loop": {
                    "max_iterations": 3,
                    "until": "state.done",
                    "steps": [
                        {
                            "id": "do",
                            "type": "ai",
                            "prompt": "p.j2",
                            "writes_files": True,
                        }
                    ],
                },
            },
            {
                "id": "gate",
                "type": "check",
                "expr": "state.done == True",
                "on_fail": "cancel",
            },
            {
                "id": "teardown",
                "type": "worktree",
                "action": "cleanup",
                "policy": "merge_to_base",
            },
        ],
    }
    wf = Workflow.model_validate(raw)
    assert isinstance(wf.steps[0], WorktreeStep)
    assert isinstance(wf.steps[1], AIStep)
    assert isinstance(wf.steps[2], LoopStep)
    assert isinstance(wf.steps[3], CheckStep)
    assert isinstance(wf.steps[4], WorktreeStep)


def test_workflow_rejects_unknown_step_type() -> None:
    raw = {
        "name": "x",
        "version": 1,
        "steps": [{"id": "bad", "type": "totally-not-a-step-type"}],
    }
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        Workflow.model_validate(raw)


def test_workflow_rejects_extra_fields() -> None:
    raw = {
        "name": "x",
        "version": 1,
        "steps": [{"id": "r", "type": "script", "command": "ls"}],
        "garbage": True,
    }
    with pytest.raises(ValidationError, match="extra"):
        Workflow.model_validate(raw)


# ---------------------------------------------------------------------------
# WriteSpec — H-1.5-004 per-write merge override
# ---------------------------------------------------------------------------


def test_write_spec_minimal() -> None:
    """Short-form string normalises to WriteSpec with no merge override."""
    spec = WriteSpec(field="plan")
    assert spec.field == "plan"
    assert spec.merge is None


def test_write_spec_replace_override() -> None:
    """Long-form with merge=replace parses correctly."""
    spec = WriteSpec(field="plan", merge="replace")
    assert spec.field == "plan"
    assert spec.merge == "replace"


def test_write_spec_rejects_unknown_merge_value() -> None:
    """merge must be one of the allowed literals (only 'replace' for v1.5)."""
    with pytest.raises(ValidationError):
        WriteSpec(field="plan", merge="append")  # type: ignore[arg-type]


def test_write_spec_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        WriteSpec.model_validate({"field": "plan", "unknown": True})


def test_ai_step_writes_short_form_normalised_to_write_spec() -> None:
    """Short-form strings in writes: are normalised to WriteSpec(field=..., merge=None)."""
    step = AIStep(type="ai", id="s", prompt="p.j2", writes=["foo", "bar"])
    assert all(isinstance(w, WriteSpec) for w in step.writes)
    assert step.writes[0].field == "foo"
    assert step.writes[0].merge is None
    assert step.writes[1].field == "bar"


def test_ai_step_writes_long_form_accepted() -> None:
    """Long-form dict entries in writes: are parsed to WriteSpec correctly."""
    step = AIStep(
        type="ai",
        id="s",
        prompt="p.j2",
        writes=[{"field": "plan", "merge": "replace"}],
    )
    assert len(step.writes) == 1
    assert step.writes[0].field == "plan"
    assert step.writes[0].merge == "replace"


def test_ai_step_writes_mixed_form_accepted() -> None:
    """Short-form and long-form can be mixed in the same writes: list."""
    step = AIStep(
        type="ai",
        id="s",
        prompt="p.j2",
        writes=["summary", {"field": "plan", "merge": "replace"}],
    )
    assert len(step.writes) == 2
    assert step.writes[0].field == "summary"
    assert step.writes[0].merge is None
    assert step.writes[1].field == "plan"
    assert step.writes[1].merge == "replace"


def test_ai_step_writes_empty_list_accepted() -> None:
    """Empty writes: [] is still valid."""
    step = AIStep(type="ai", id="s", prompt="p.j2", writes=[])
    assert step.writes == []


def test_workflow_yaml_long_form_writes_parses_correctly() -> None:
    """End-to-end: YAML-shaped dict round-trips through Workflow.model_validate."""
    raw = {
        "name": "feature",
        "version": 1,
        "steps": [
            {
                "id": "implement",
                "type": "ai",
                "prompt": "p.j2",
                "writes": [
                    "summary",
                    {"field": "plan", "merge": "replace"},
                ],
            }
        ],
    }
    wf = Workflow.model_validate(raw)
    step = wf.steps[0]
    assert isinstance(step, AIStep)
    assert step.writes[0].field == "summary"
    assert step.writes[0].merge is None
    assert step.writes[1].field == "plan"
    assert step.writes[1].merge == "replace"
