"""Load + regression tests for the shipped ``workflows/build.yaml``.

Covers structural validity and the specific bug fix for commit output parsing:
the ``commit`` step must redirect all git output to stderr so
that only the ``printf`` JSON line reaches stdout and the harness can
parse it as the step's contract payload.

Also covers the Linear state-transition fixes:
- ``set-in-progress`` selects the state named "In Progress" (case-insensitive),
  falling back to the first ``started`` state.
- ``set-in-review`` (now a top-level step after ``handle-deferred``) transitions
  the ticket exactly once before the commit, selecting the state named "In Review"
  with the same fallback logic.

Version 3 structural changes:
- ``read-target-claude-md`` hoisted from fix-loop to a top-level step between
  ``fetch-ticket`` and ``fix-loop`` (runs once per workflow, not per iteration).
- ``set-in-review`` hoisted from fix-loop to a top-level step between
  ``handle-deferred`` and ``commit`` (fires once on the commit path).
- ``commit-and-push`` renamed to ``commit``; git push removed (handled by
  ``push-base`` after merge).
- New merge phase: ``attempt-merge``, ``conflict-loop``, ``notify-merge-exhausted``,
  ``gate-merge-clean``, ``push-base`` inserted between ``commit`` and ``teardown``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from harness.state.schema import BaseState
from harness.state.store import _merge
from harness.workflow.derive import derive_state_schema
from harness.workflow.loader import LoadedWorkflow, load_workflow
from harness.workflow.schema import LoopStep, ScriptStep, Step

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUILD_WORKFLOW = _REPO_ROOT / "workflows" / "build.yaml"
_BUILD_CODEX_WORKFLOW = _REPO_ROOT / "workflows" / "build-codex.yaml"


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
        "read-target-claude-md",
        "fix-loop",
        "notify-exhausted",
        "gate-exhausted",
        "handle-deferred",
        "set-in-review",
        "commit",
        "attempt-merge",
        "conflict-loop",
        "notify-merge-exhausted",
        "gate-merge-clean",
        "push-base",
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
# commit step must not mix git stdout with JSON output
# ---------------------------------------------------------------------------


def _commit_step(loaded_build: LoadedWorkflow) -> ScriptStep:
    """Return the ``commit`` step from the build workflow."""
    for step in loaded_build.workflow.steps:
        if step.id == "commit":
            assert isinstance(step, ScriptStep), (
                f"commit step should be ScriptStep, got {type(step)}"
            )
            return step  # type: ignore[return-value]
    pytest.fail("commit step not found in build workflow")


# ---------------------------------------------------------------------------
# version 3 structure: fix-loop inner steps, DEFER contract
# ---------------------------------------------------------------------------


def test_build_workflow_fix_loop_inner_steps(loaded_build: LoadedWorkflow) -> None:
    """fix-loop inner steps: implement, verify, gate-verify, capture-diff, review, gate-retry.

    read-target-claude-md and set-in-review are top-level steps. The verify gate
    runs as a deterministic script step before review; capture-diff records the
    branch diff into state so the read-only review agent can see what changed.
    """
    fix_loop = next(
        s for s in loaded_build.workflow.steps if s.id == "fix-loop"
    )
    assert isinstance(fix_loop, LoopStep), (
        f"fix-loop should be a LoopStep, got {type(fix_loop)}"
    )
    inner_ids = [s.id for s in fix_loop.loop.steps]
    assert inner_ids == [
        "implement",
        "verify",
        "gate-verify",
        "capture-diff",
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
# read-target-claude-md — hoisted to top-level step
# ---------------------------------------------------------------------------


def test_read_target_claude_md_is_toplevel_between_fetch_ticket_and_fix_loop(
    loaded_build: LoadedWorkflow,
) -> None:
    """read-target-claude-md must be a top-level step between fetch-ticket and fix-loop."""
    step_ids = [s.id for s in loaded_build.workflow.steps]
    assert "read-target-claude-md" in step_ids, (
        "read-target-claude-md must be a top-level step"
    )
    rtcm_idx = step_ids.index("read-target-claude-md")
    fetch_idx = step_ids.index("fetch-ticket")
    fix_loop_idx = step_ids.index("fix-loop")
    assert fetch_idx < rtcm_idx < fix_loop_idx, (
        "read-target-claude-md must appear between fetch-ticket and fix-loop; "
        f"got order: {step_ids}"
    )


def test_read_target_claude_md_uses_repo_path_arg(
    loaded_build: LoadedWorkflow,
) -> None:
    """read-target-claude-md must pass $inputs.repo_path as its argument."""
    step = _get_script_step(loaded_build, "read-target-claude-md")
    assert "$inputs.repo_path" in step.args, (
        "read-target-claude-md must pass $inputs.repo_path so it reads from the "
        "target project root, not the harness root"
    )


def test_read_target_claude_md_writes_target_claude_md(
    loaded_build: LoadedWorkflow,
) -> None:
    """read-target-claude-md must declare target_claude_md in writes."""
    step = _get_script_step(loaded_build, "read-target-claude-md")
    write_fields = [w.field for w in step.writes]
    assert "target_claude_md" in write_fields, (
        "read-target-claude-md must write target_claude_md so it is available "
        "to the implement and review prompts"
    )


def test_read_target_claude_md_falls_back_when_no_claude_md(
    loaded_build: LoadedWorkflow,
) -> None:
    """read-target-claude-md command must not fail when CLAUDE.md is absent."""
    step = _get_script_step(loaded_build, "read-target-claude-md")
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
    step = _get_script_step(loaded_build, "read-target-claude-md")
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
    step = _get_script_step(loaded_build, "read-target-claude-md")
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
# set-in-review — hoisted to top-level step between handle-deferred and commit
# ---------------------------------------------------------------------------


def test_set_in_review_is_toplevel_between_handle_deferred_and_commit(
    loaded_build: LoadedWorkflow,
) -> None:
    """set-in-review must be a top-level step between handle-deferred and commit."""
    step_ids = [s.id for s in loaded_build.workflow.steps]
    assert "set-in-review" in step_ids, (
        "set-in-review must be a top-level step"
    )
    sir_idx = step_ids.index("set-in-review")
    handle_idx = step_ids.index("handle-deferred")
    commit_idx = step_ids.index("commit")
    assert handle_idx < sir_idx < commit_idx, (
        "set-in-review must appear between handle-deferred and commit; "
        f"got order: {step_ids}"
    )


def test_set_in_review_not_in_fix_loop(loaded_build: LoadedWorkflow) -> None:
    """set-in-review must NOT appear inside fix-loop (it was hoisted to top-level)."""
    fix_loop = next(
        s for s in loaded_build.workflow.steps if s.id == "fix-loop"
    )
    assert isinstance(fix_loop, LoopStep)
    inner_ids = [s.id for s in fix_loop.loop.steps]
    assert "set-in-review" not in inner_ids, (
        "set-in-review must not be inside fix-loop; it was hoisted to a "
        "top-level step so it fires once (not on every retry)"
    )


def test_set_in_review_selects_in_review_by_name(
    loaded_build: LoadedWorkflow,
) -> None:
    """set-in-review must match on the literal name 'in review' (case-insensitive)."""
    step = _get_script_step(loaded_build, "set-in-review")
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
    step = _get_script_step(loaded_build, "set-in-review")
    assert ") // first" in step.command, (
        "set-in-review must use jq's // operator (') // first') to fall back "
        "to the first started state when no name match is found"
    )


def test_set_in_review_is_resilient_to_missing_state(
    loaded_build: LoadedWorkflow,
) -> None:
    """set-in-review must be a no-op when no started state exists (STATE_ID empty)."""
    step = _get_script_step(loaded_build, "set-in-review")
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
# commit — stdout isolation (git output redirected to stderr)
# ---------------------------------------------------------------------------


def test_commit_git_commands_redirect_stdout_to_stderr(
    loaded_build: LoadedWorkflow,
) -> None:
    """Every git command in the commit script must redirect its
    stdout to stderr (``>&2``) so only the final ``printf`` JSON line
    reaches the harness's stdout capture.

    Without this fix the harness receives git's human-readable progress
    lines mixed with the JSON, ``json.loads`` fails, and the run is
    recorded as ``failed`` even though the commit succeeded.
    """
    step = _commit_step(loaded_build)
    assert step.command is not None, "commit step must use inline command"

    git_lines = [
        line.strip()
        for line in step.command.splitlines()
        if line.strip().startswith("git ")
    ]
    assert git_lines, "commit step has no git commands — check the YAML"

    offending = [line for line in git_lines if ">&2" not in line]
    assert not offending, (
        "These git command lines in commit do not redirect stdout to "
        "stderr (missing >&2):\n"
        + "\n".join(f"  {line}" for line in offending)
        + "\n\nFix: append >&2 to each git command so only the printf JSON "
        "line reaches stdout."
    )


def test_commit_has_no_git_push(loaded_build: LoadedWorkflow) -> None:
    """The commit step must NOT contain a git push command.

    Pushing is handled by push-base (success path) or notify-merge-exhausted
    (conflict-exhaustion rescue path). The commit step only commits and
    reports the SHA.
    """
    step = _commit_step(loaded_build)
    assert step.command is not None
    assert "git push" not in step.command, (
        "commit step must not contain 'git push' — pushing is handled by "
        "push-base after the merge phase succeeds"
    )


# ---------------------------------------------------------------------------
# fix-loop feedback fixes — applied to BOTH build.yaml and build-codex.yaml
#
# 1. review writes `issues` with merge: replace so review findings do not
#    accumulate across retry iterations (default list merge is append).
# 2. capture-diff records the branch diff into state so the read-only review
#    agent (Read/Grep/Glob, no Bash) can see what changed.
# ---------------------------------------------------------------------------

_BUILD_WORKFLOWS = pytest.mark.parametrize(
    "wf_path",
    [_BUILD_WORKFLOW, _BUILD_CODEX_WORKFLOW],
    ids=["build", "build-codex"],
)


def _fix_loop_inner(loaded: LoadedWorkflow) -> dict[str, Step]:
    """Return {step_id: step} for the steps inside the fix-loop."""
    fix_loop = next(s for s in loaded.workflow.steps if s.id == "fix-loop")
    assert isinstance(fix_loop, LoopStep), (
        f"fix-loop should be a LoopStep, got {type(fix_loop)}"
    )
    return {s.id: s for s in fix_loop.loop.steps}


@_BUILD_WORKFLOWS
def test_build_workflow_loads(wf_path: Path) -> None:
    """Both build workflows parse and pass the loader's cross-step checks."""
    loaded = load_workflow(wf_path)
    assert loaded.workflow.name in ("build", "build-codex")


@_BUILD_WORKFLOWS
def test_review_issues_write_uses_replace_merge(wf_path: Path) -> None:
    """The review step must write `issues` with merge: replace.

    The default list merge is append (see harness.state.store._merge), which
    made review findings accumulate across fix-loop iterations: by the last
    iteration the implement agent saw already-fixed findings mixed with the
    current ones, and notify-exhausted posted the whole pile to Linear.
    Replace makes `issues` reflect only the current review's findings.
    """
    loaded = load_workflow(wf_path)
    review = _fix_loop_inner(loaded)["review"]
    issues_writes = [w for w in review.writes if w.field == "issues"]
    assert issues_writes, f"{wf_path.name}: review step must write `issues`"
    assert issues_writes[0].merge == "replace", (
        f"{wf_path.name}: review must write `issues` with merge: replace so "
        "review findings do not accumulate across fix-loop iterations"
    )


@_BUILD_WORKFLOWS
def test_verify_issues_write_still_appends(wf_path: Path) -> None:
    """The verify step keeps default (append) merge for `issues`.

    A verify failure short-circuits before review (gate-verify), so its
    message must ride alongside the still-outstanding review findings rather
    than replacing them. Only the review write uses replace.
    """
    loaded = load_workflow(wf_path)
    verify = _fix_loop_inner(loaded)["verify"]
    issues_writes = [w for w in verify.writes if w.field == "issues"]
    assert issues_writes, f"{wf_path.name}: verify step must write `issues`"
    assert issues_writes[0].merge is None, (
        f"{wf_path.name}: verify must NOT use replace merge on `issues` — a "
        "verify failure should append to (not clobber) outstanding findings"
    )


@_BUILD_WORKFLOWS
def test_capture_diff_step_present_before_review(wf_path: Path) -> None:
    """capture-diff must run after gate-verify and before review, writing `diff`."""
    loaded = load_workflow(wf_path)
    fix_loop = next(s for s in loaded.workflow.steps if s.id == "fix-loop")
    assert isinstance(fix_loop, LoopStep)
    inner_ids = [s.id for s in fix_loop.loop.steps]
    assert "capture-diff" in inner_ids, (
        f"{wf_path.name}: fix-loop must contain a capture-diff step"
    )
    assert (
        inner_ids.index("gate-verify")
        < inner_ids.index("capture-diff")
        < inner_ids.index("review")
    ), (
        f"{wf_path.name}: capture-diff must run after gate-verify and before "
        f"review; got order {inner_ids}"
    )


@_BUILD_WORKFLOWS
def test_capture_diff_step_writes_diff_against_base(wf_path: Path) -> None:
    """capture-diff writes only `diff` and diffs against the base branch."""
    loaded = load_workflow(wf_path)
    step = _fix_loop_inner(loaded)["capture-diff"]
    assert isinstance(step, ScriptStep), (
        f"{wf_path.name}: capture-diff should be a ScriptStep, got {type(step)}"
    )
    write_fields = [w.field for w in step.writes]
    assert write_fields == ["diff"], (
        f"{wf_path.name}: capture-diff must write only `diff`, got {write_fields}"
    )
    assert step.command is not None and "git diff" in step.command, (
        f"{wf_path.name}: capture-diff must run `git diff`"
    )
    assert "$inputs.base_branch" in step.args, (
        f"{wf_path.name}: capture-diff must diff against $inputs.base_branch"
    )


@_BUILD_WORKFLOWS
def test_capture_diff_command_emits_branch_diff(wf_path: Path, tmp_path: Path) -> None:
    """The capture-diff command emits valid JSON whose `diff` holds the
    branch's changes against the base branch (functional test against git)."""
    if not shutil.which("jq") or not shutil.which("git"):
        pytest.skip("git or jq not installed")
    loaded = load_workflow(wf_path)
    step = _fix_loop_inner(loaded)["capture-diff"]
    assert isinstance(step, ScriptStep)
    assert step.command is not None

    def _git(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
        )

    _git("init", "-q")
    _git("config", "user.email", "t@example.com")
    _git("config", "user.name", "Test")
    (tmp_path / "f.py").write_text("original\n")
    _git("add", "-A")
    _git("commit", "-q", "-m", "base")
    _git("branch", "base")
    _git("checkout", "-q", "-b", "feature")
    (tmp_path / "f.py").write_text("changed-by-implement\n")
    _git("add", "-A")
    _git("commit", "-q", "-m", "wip: implement")

    # $0="cd", $1="base" — mirrors how the script node invokes the command.
    result = subprocess.run(
        ["bash", "-c", step.command, "cd", "base"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"capture-diff command failed: {result.stderr}"
    payload = json.loads(result.stdout)
    assert "diff" in payload
    assert "changed-by-implement" in payload["diff"], (
        f"{wf_path.name}: capture-diff must capture the branch's changes against "
        f"the base; got: {payload['diff']!r}"
    )


def _apply_step_writes(
    schema: type[BaseState], state: BaseState, step: Step, payload: dict[str, object]
) -> BaseState:
    """Apply a step's declared writes to state the way the executor does.

    Mirrors harness.engine.executor.Executor._apply_writes: collect the
    per-write merge overrides from the step's WriteSpecs, then run the real
    harness.state.store._merge (the same function update_state calls).
    """
    overrides = {w.field: w.merge for w in step.writes if w.merge is not None}
    merged = _merge(schema, state, payload, overrides)
    return schema.model_validate(merged)


@_BUILD_WORKFLOWS
def test_issues_do_not_accumulate_across_fix_loop_iterations(wf_path: Path) -> None:
    """End-to-end: with the shipped workflow's merge config, review findings
    reflect only the current iteration — they do not pile up.

    Drives the real derive + merge path with the merge overrides extracted
    from the actual workflow steps. Before the fix (append merge) iteration 2
    would see ['A', 'B', 'C']; with review using replace it sees ['C'].
    """
    loaded = load_workflow(wf_path)
    schema = derive_state_schema(loaded)
    inner = _fix_loop_inner(loaded)
    verify, review = inner["verify"], inner["review"]

    state: BaseState = schema.model_validate(
        {
            "run_id": "r",
            "workflow_name": loaded.workflow.name,
            "base_branch": "dev",
            "artifacts_dir": "/tmp",
            "started_at": "2026-01-01T00:00:00Z",
            "notes": [],
        }
    )

    # Iteration 1: verify passes (issues=[]), review FAILs with two findings.
    state = _apply_step_writes(
        schema, state, verify,
        {"verify_exit_code": 0, "verify_output": "ok", "issues": []},
    )
    state = _apply_step_writes(
        schema, state, review,
        {"verdict": "FAIL", "issues": ["A", "B"], "commit_message": "", "deferred_brief": ""},
    )
    assert state.issues == ["A", "B"]  # type: ignore[attr-defined]

    # Iteration 2: A and B fixed; verify passes; review FAILs with new finding C.
    state = _apply_step_writes(
        schema, state, verify,
        {"verify_exit_code": 0, "verify_output": "ok", "issues": []},
    )
    state = _apply_step_writes(
        schema, state, review,
        {"verdict": "FAIL", "issues": ["C"], "commit_message": "", "deferred_brief": ""},
    )
    assert state.issues == ["C"], (  # type: ignore[attr-defined]
        f"{wf_path.name}: review findings accumulated across iterations "
        f"(got {state.issues!r}); the review `issues` write must use merge: replace"  # type: ignore[attr-defined]
    )


@_BUILD_WORKFLOWS
def test_review_step_has_no_bash(wf_path: Path) -> None:
    """The review agent must stay read-only (no Bash).

    A prior run gave review Bash and it destructively deleted a branch. The
    diff now reaches review via the capture-diff state field, not by letting
    the agent run git itself.
    """
    loaded = load_workflow(wf_path)
    review = _fix_loop_inner(loaded)["review"]
    allowed = list(getattr(review, "allowed_tools", []))
    assert "Bash" not in allowed, (
        f"{wf_path.name}: review must not have Bash in allowed_tools "
        f"(got {allowed}); the diff is provided via state.diff instead"
    )


@_BUILD_WORKFLOWS
def test_implement_persists_session_review_stays_fresh(wf_path: Path) -> None:
    """implement resumes its conversation across fix-loop retries
    (persist_session=True); review stays fresh so it never anchors on a
    prior verdict."""
    loaded = load_workflow(wf_path)
    inner = _fix_loop_inner(loaded)
    assert inner["implement"].persist_session is True, (
        f"{wf_path.name}: implement must set persist_session: true so a retry "
        "keeps the reasoning/history of its prior attempt"
    )
    assert inner["review"].persist_session is False, (
        f"{wf_path.name}: review must stay fresh (persist_session: false)"
    )
