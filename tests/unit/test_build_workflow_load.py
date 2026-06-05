"""Load + regression tests for the shipped ``workflows/build.yaml``.

Covers structural validity and the specific bug fix for commit-and-push output parsing:
the ``commit-and-push`` step must redirect all git output to stderr so
that only the ``printf`` JSON line reaches stdout and the harness can
parse it as the step's contract payload.

Also covers the Linear state-transition fixes:
- ``set-in-progress`` selects the state named "In Progress" (case-insensitive),
  falling back to the first ``started`` state.
- ``set-in-review`` (inside the fix-loop) transitions the ticket before review,
  selecting the state named "In Review" with the same fallback logic.
"""

from __future__ import annotations

import json
import shutil
import subprocess
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
# commit-and-push must not mix git stdout with JSON output
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
# version 3 structure: fix-loop inner steps, DEFER contract
# ---------------------------------------------------------------------------


def test_build_workflow_fix_loop_inner_steps(loaded_build: LoadedWorkflow) -> None:
    """fix-loop inner steps include read-target-claude-md first, then implement, review chain."""
    fix_loop = next(
        s for s in loaded_build.workflow.steps if s.id == "fix-loop"
    )
    assert isinstance(fix_loop, LoopStep), (
        f"fix-loop should be a LoopStep, got {type(fix_loop)}"
    )
    inner_ids = [s.id for s in fix_loop.loop.steps]
    assert inner_ids == [
        "read-target-claude-md",
        "implement",
        "set-in-review",
        "review",
        "gate-retry",
    ]


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


# ---------------------------------------------------------------------------
# set-in-progress — name-based state selection (bug fix)
# ---------------------------------------------------------------------------

# The jq filter used in both set-in-progress and set-in-review.
# Selects started states, preferring the one whose name matches $target
# (case-insensitive) and falling back to the first started state.
_JQ_STATE_FILTER = r"""
map(select(.type=="started"))
| (map(select((.name | ascii_downcase) == $target)) | first) // first
| .id // empty
"""


def _get_script_step(loaded_build: LoadedWorkflow, step_id: str) -> ScriptStep:
    """Return the named top-level script step, failing if absent or wrong type."""
    for step in loaded_build.workflow.steps:
        if step.id == step_id:
            assert isinstance(step, ScriptStep), (
                f"{step_id!r} step should be ScriptStep, got {type(step)}"
            )
            return step  # type: ignore[return-value]
    pytest.fail(f"{step_id!r} step not found in build workflow")


def test_set_in_progress_query_includes_state_name(
    loaded_build: LoadedWorkflow,
) -> None:
    """The set-in-progress GraphQL query must request the ``name`` field on state nodes."""
    step = _get_script_step(loaded_build, "set-in-progress")
    # The query fragment should contain `name` inside the states nodes selection.
    assert "name" in step.command, (
        "set-in-progress must request `name` in the states query so name-based "
        "filtering is possible"
    )


def test_set_in_progress_selects_in_progress_by_name(
    loaded_build: LoadedWorkflow,
) -> None:
    """set-in-progress must match on the literal name 'in progress' (case-insensitive)."""
    step = _get_script_step(loaded_build, "set-in-progress")
    cmd_lower = step.command.lower()
    assert "in progress" in cmd_lower, (
        "set-in-progress must select the state named 'In Progress' by name"
    )
    assert "ascii_downcase" in step.command, (
        "set-in-progress must use jq's ascii_downcase for case-insensitive matching"
    )


def test_set_in_progress_has_fallback_to_first_started(
    loaded_build: LoadedWorkflow,
) -> None:
    """set-in-progress must fall back to first started state when name not matched."""
    step = _get_script_step(loaded_build, "set-in-progress")
    # The jq alternative operator produces "... | first) // first" — note the
    # space before "//".  This distinguishes it from the "//" in https:// URLs.
    assert ") // first" in step.command, (
        "set-in-progress must use jq's // operator (') // first') to fall back "
        "to the first started state when no name match is found"
    )


def test_set_in_progress_is_resilient_to_missing_state(
    loaded_build: LoadedWorkflow,
) -> None:
    """set-in-progress must be a no-op when no started state exists (STATE_ID empty)."""
    step = _get_script_step(loaded_build, "set-in-progress")
    assert '[ -n "$STATE_ID" ]' in step.command or '[ -n "${STATE_ID}" ]' in step.command, (
        "set-in-progress must guard the mutation call so it is skipped when "
        "STATE_ID is empty (graceful no-op)"
    )


# ---------------------------------------------------------------------------
# fix-loop — set-in-review inserted before review
# ---------------------------------------------------------------------------


def test_build_workflow_fix_loop_inner_steps_include_set_in_review(
    loaded_build: LoadedWorkflow,
) -> None:
    """fix-loop must contain set-in-review between implement and review."""
    fix_loop = next(
        s for s in loaded_build.workflow.steps if s.id == "fix-loop"
    )
    assert isinstance(fix_loop, LoopStep)
    inner_ids = [s.id for s in fix_loop.loop.steps]
    assert "set-in-review" in inner_ids, (
        "fix-loop must include a set-in-review step"
    )
    implement_idx = inner_ids.index("implement")
    review_idx = inner_ids.index("review")
    set_in_review_idx = inner_ids.index("set-in-review")
    assert implement_idx < set_in_review_idx < review_idx, (
        "set-in-review must appear between implement and review in fix-loop; "
        f"got order: {inner_ids}"
    )


# ---------------------------------------------------------------------------
# fix-loop — read-target-claude-md inserted before implement
# ---------------------------------------------------------------------------


def test_read_target_claude_md_is_first_in_fix_loop(
    loaded_build: LoadedWorkflow,
) -> None:
    """read-target-claude-md must be the first step inside fix-loop."""
    fix_loop = next(
        s for s in loaded_build.workflow.steps if s.id == "fix-loop"
    )
    assert isinstance(fix_loop, LoopStep)
    first_step = fix_loop.loop.steps[0]
    assert first_step.id == "read-target-claude-md", (
        f"Expected first inner step to be read-target-claude-md, got {first_step.id!r}"
    )


def test_read_target_claude_md_uses_repo_path_arg(
    loaded_build: LoadedWorkflow,
) -> None:
    """read-target-claude-md must pass $inputs.repo_path as its argument."""
    step = _get_loop_script_step(loaded_build, "read-target-claude-md")
    assert "$inputs.repo_path" in step.args, (
        "read-target-claude-md must pass $inputs.repo_path so it reads from the "
        "target project root, not the harness root"
    )


def test_read_target_claude_md_writes_target_claude_md(
    loaded_build: LoadedWorkflow,
) -> None:
    """read-target-claude-md must declare target_claude_md in writes."""
    step = _get_loop_script_step(loaded_build, "read-target-claude-md")
    write_fields = [w.field for w in step.writes]
    assert "target_claude_md" in write_fields, (
        "read-target-claude-md must write target_claude_md so it is available "
        "to the implement and review prompts"
    )


def test_read_target_claude_md_falls_back_when_no_claude_md(
    loaded_build: LoadedWorkflow,
) -> None:
    """read-target-claude-md command must not fail when CLAUDE.md is absent."""
    step = _get_loop_script_step(loaded_build, "read-target-claude-md")
    assert step.command is not None
    # The 2>/dev/null || echo fallback makes the command always succeed.
    assert "2>/dev/null" in step.command, (
        "read-target-claude-md must suppress cat errors via 2>/dev/null"
    )
    assert "no CLAUDE.md found" in step.command or "echo" in step.command, (
        "read-target-claude-md must produce a non-empty fallback output when "
        "CLAUDE.md is absent"
    )


def test_read_target_claude_md_command_emits_valid_json(
    loaded_build: LoadedWorkflow,
    tmp_path: Path,
) -> None:
    """The command must emit valid JSON with a target_claude_md key when CLAUDE.md exists."""
    if not shutil.which("jq"):
        pytest.skip("jq not installed")
    step = _get_loop_script_step(loaded_build, "read-target-claude-md")
    assert step.command is not None
    (tmp_path / "CLAUDE.md").write_text("# Project\n\nUse TDD.\n")
    result = subprocess.run(
        ["bash", "-c", step.command, "test", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    payload = json.loads(result.stdout)
    assert "target_claude_md" in payload
    assert "Use TDD." in payload["target_claude_md"]


def test_read_target_claude_md_command_emits_valid_json_fallback(
    loaded_build: LoadedWorkflow,
    tmp_path: Path,
) -> None:
    """The command must emit valid JSON even when CLAUDE.md is absent."""
    if not shutil.which("jq"):
        pytest.skip("jq not installed")
    step = _get_loop_script_step(loaded_build, "read-target-claude-md")
    assert step.command is not None
    # tmp_path has no CLAUDE.md — tests the fallback path
    result = subprocess.run(
        ["bash", "-c", step.command, "test", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    payload = json.loads(result.stdout)
    assert "target_claude_md" in payload
    assert payload["target_claude_md"]  # non-empty fallback message


# ---------------------------------------------------------------------------
# set-in-review — name-based state selection
# ---------------------------------------------------------------------------


def _get_loop_script_step(loaded_build: LoadedWorkflow, step_id: str) -> ScriptStep:
    """Return the named script step from inside fix-loop."""
    fix_loop = next(
        s for s in loaded_build.workflow.steps if s.id == "fix-loop"
    )
    assert isinstance(fix_loop, LoopStep)
    for step in fix_loop.loop.steps:
        if step.id == step_id:
            assert isinstance(step, ScriptStep), (
                f"{step_id!r} inner step should be ScriptStep, got {type(step)}"
            )
            return step  # type: ignore[return-value]
    pytest.fail(f"{step_id!r} step not found inside fix-loop")


def test_set_in_review_selects_in_review_by_name(
    loaded_build: LoadedWorkflow,
) -> None:
    """set-in-review must match on the literal name 'in review' (case-insensitive)."""
    step = _get_loop_script_step(loaded_build, "set-in-review")
    cmd_lower = step.command.lower()
    assert "in review" in cmd_lower, (
        "set-in-review must select the state named 'In Review' by name"
    )
    assert "ascii_downcase" in step.command, (
        "set-in-review must use jq's ascii_downcase for case-insensitive matching"
    )


def test_set_in_review_has_fallback_to_first_started(
    loaded_build: LoadedWorkflow,
) -> None:
    """set-in-review must fall back to first started state when name not matched."""
    step = _get_loop_script_step(loaded_build, "set-in-review")
    assert ") // first" in step.command, (
        "set-in-review must use jq's // operator (') // first') to fall back "
        "to the first started state when no name match is found"
    )


def test_set_in_review_is_resilient_to_missing_state(
    loaded_build: LoadedWorkflow,
) -> None:
    """set-in-review must be a no-op when no started state exists (STATE_ID empty)."""
    step = _get_loop_script_step(loaded_build, "set-in-review")
    assert '[ -n "$STATE_ID" ]' in step.command or '[ -n "${STATE_ID}" ]' in step.command, (
        "set-in-review must guard the mutation call so it is skipped when "
        "STATE_ID is empty (graceful no-op)"
    )


# ---------------------------------------------------------------------------
# jq state-selection logic — functional tests against real jq
# ---------------------------------------------------------------------------

_SAMPLE_STATES = [
    {"id": "ip-1", "name": "In Progress", "type": "started"},
    {"id": "ir-2", "name": "In Review", "type": "started"},
    {"id": "done-3", "name": "Done", "type": "completed"},
]


@pytest.mark.parametrize(
    "target,expected_id",
    [
        ("in progress", "ip-1"),   # exact name match (case-insensitive)
        ("IN PROGRESS", "ip-1"),   # upper-case input works via ascii_downcase
        ("in review", "ir-2"),     # different started state matched by name
        ("nonexistent", "ip-1"),   # unknown name → fall back to first started
    ],
)
def test_jq_state_name_selection_logic(target: str, expected_id: str) -> None:
    """The shared jq filter picks the right state ID or falls back correctly."""
    if not shutil.which("jq"):
        pytest.skip("jq not installed")

    result = subprocess.run(
        ["jq", "-r", "--arg", "target", target.lower(), _JQ_STATE_FILTER],
        input=json.dumps(_SAMPLE_STATES),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"jq failed: {result.stderr}"
    assert result.stdout.strip() == expected_id


def test_jq_state_name_selection_empty_when_no_started_states() -> None:
    """The jq filter produces no output when there are no started-type states."""
    if not shutil.which("jq"):
        pytest.skip("jq not installed")

    states = [{"id": "done-3", "name": "Done", "type": "completed"}]
    result = subprocess.run(
        ["jq", "-r", "--arg", "target", "in progress", _JQ_STATE_FILTER],
        input=json.dumps(states),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"jq failed: {result.stderr}"
    assert result.stdout.strip() == "", (
        "Expected empty output when no started states exist, "
        f"got: {result.stdout.strip()!r}"
    )


# ---------------------------------------------------------------------------
# commit-and-push — stdout isolation (existing regression test)
# ---------------------------------------------------------------------------


def test_commit_and_push_git_commands_redirect_stdout_to_stderr(
    loaded_build: LoadedWorkflow,
) -> None:
    """Every git command in the commit-and-push script must redirect its
    stdout to stderr (``>&2``) so only the final ``printf`` JSON line
    reaches the harness's stdout capture.

    Without this fix the harness receives git's human-readable progress
    lines mixed with the JSON, ``json.loads`` fails, and the run is
    recorded as ``failed`` even though the commit and push both succeeded.
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
