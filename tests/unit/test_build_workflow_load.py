"""Load + regression tests for the shipped ``workflows/build.yaml``.

Covers structural validity and the specific bug fix for CAL-506:
the ``commit-and-push`` step must redirect all git output to stderr so
that only the ``printf`` JSON line reaches stdout and the harness can
parse it as the step's contract payload.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.workflow.loader import LoadedWorkflow, load_workflow
from harness.workflow.schema import LoopStep, ScriptStep

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUILD_WORKFLOW = _REPO_ROOT / "workflows" / "build.yaml"


@pytest.fixture(scope="module")
def loaded_build() -> LoadedWorkflow:
    """Load the shipped build workflow once per test module."""
    assert _BUILD_WORKFLOW.is_file(), (
        f"workflows/build.yaml missing at {_BUILD_WORKFLOW}"
    )
    return load_workflow(_BUILD_WORKFLOW)


# ---------------------------------------------------------------------------
# Structural validity
# ---------------------------------------------------------------------------


def test_build_workflow_loads_without_error(loaded_build: LoadedWorkflow) -> None:
    """The shipped YAML parses and all loader cross-step checks pass."""
    assert loaded_build.workflow.name == "build"
    assert loaded_build.workflow.version == 3


def test_build_workflow_step_ids(loaded_build: LoadedWorkflow) -> None:
    """Steps are declared in the expected order (version 3 structure)."""
    step_ids = [s.id for s in loaded_build.workflow.steps]
    assert step_ids == [
        "setup",
        "set-in-progress",
        "fetch-ticket",
        "fix-loop",
        "notify-exhausted",
        "gate-exhausted",
        "handle-deferred",
        "commit-and-push",
        "teardown",
        "close-task",
    ]


def test_build_workflow_has_linear_id_input(loaded_build: LoadedWorkflow) -> None:
    """``linear_id`` is a required string input with a flag."""
    inputs = loaded_build.workflow.inputs
    assert "linear_id" in inputs
    spec = inputs["linear_id"]
    assert spec.type == "string"
    assert spec.required is True
    assert spec.flag == "--linear"


# ---------------------------------------------------------------------------
# CAL-506 — commit-and-push must not mix git stdout with JSON output
# ---------------------------------------------------------------------------


def _commit_and_push_step(loaded_build: LoadedWorkflow) -> ScriptStep:
    """Return the ``commit-and-push`` step from the build workflow."""
    for step in loaded_build.workflow.steps:
        if step.id == "commit-and-push":
            assert isinstance(step, ScriptStep), (
                f"commit-and-push step should be ScriptStep, got {type(step)}"
            )
            return step  # type: ignore[return-value]
    pytest.fail("commit-and-push step not found in build workflow")


# ---------------------------------------------------------------------------
# CAL-511 — version 3 structure: fix-loop inner steps, DEFER contract
# ---------------------------------------------------------------------------


def test_build_workflow_fix_loop_inner_steps(loaded_build: LoadedWorkflow) -> None:
    """The fix-loop block's inner steps are implement, review, and gate-retry."""
    fix_loop = next(
        s for s in loaded_build.workflow.steps if s.id == "fix-loop"
    )
    assert isinstance(fix_loop, LoopStep), (
        f"fix-loop should be a LoopStep, got {type(fix_loop)}"
    )
    inner_ids = [s.id for s in fix_loop.loop.steps]
    assert inner_ids == ["implement", "review", "gate-retry"]


def test_build_workflow_review_contract_has_defer(loaded_build: LoadedWorkflow) -> None:
    """The review step's contract includes DEFER in the verdict enum."""
    review_contract = loaded_build.contracts.get("review")
    assert review_contract is not None, "review step must have a contract"
    verdict_field = review_contract.model_fields.get("verdict")
    assert verdict_field is not None, "review contract must have a verdict field"
    # The annotation is Literal["PASS", "FAIL", "DEFER"] (or similar).
    annotation_str = str(verdict_field.annotation)
    assert "DEFER" in annotation_str, (
        f"verdict annotation must include DEFER: {annotation_str!r}"
    )


def test_build_workflow_review_contract_has_deferred_brief(
    loaded_build: LoadedWorkflow,
) -> None:
    """The review step's contract includes the deferred_brief field."""
    review_contract = loaded_build.contracts.get("review")
    assert review_contract is not None, "review step must have a contract"
    assert "deferred_brief" in review_contract.model_fields, (
        "review contract must have a deferred_brief field"
    )


def test_commit_and_push_git_commands_redirect_stdout_to_stderr(
    loaded_build: LoadedWorkflow,
) -> None:
    """Every git command in the commit-and-push script must redirect its
    stdout to stderr (``>&2``) so only the final ``printf`` JSON line
    reaches the harness's stdout capture.

    Without this fix the harness receives git's human-readable progress
    lines mixed with the JSON, ``json.loads`` fails, and the run is
    recorded as ``failed`` even though the commit and push both succeeded
    (CAL-506).
    """
    step = _commit_and_push_step(loaded_build)
    assert step.command is not None, "commit-and-push step must use inline command"

    git_lines = [
        line.strip()
        for line in step.command.splitlines()
        if line.strip().startswith("git ")
    ]
    assert git_lines, "commit-and-push step has no git commands — check the YAML"

    offending = [line for line in git_lines if ">&2" not in line]
    assert not offending, (
        "These git command lines in commit-and-push do not redirect stdout to "
        "stderr (missing >&2):\n"
        + "\n".join(f"  {line}" for line in offending)
        + "\n\nFix: append >&2 to each git command so only the printf JSON "
        "line reaches stdout."
    )
