"""Tests for the build workflow merge phase.

Covers:
- Structural validation of the new merge-phase steps in build.yaml.
- Unit tests for the attempt-merge script on the clean path (no conflict)
  and the conflict path (merge conflict requiring resolution).
- Integration test: clean merge end-to-end using a real git repository.

The functional tests use real git subprocesses against temporary repos;
they are marked ``@pytest.mark.slow`` to allow skipping on fast CI runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from harness.dispatch.mock import MockAgent, RecordedCall
from harness.engine.runner import Runner
from harness.nodes.base import Attestation, NodeResult
from harness.state.store import init_db
from harness.workflow.loader import load_workflow
from harness.workflow.schema import CheckStep, LoopStep, ScriptStep

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUILD_WORKFLOW = _REPO_ROOT / "workflows" / "build.yaml"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def loaded_build():  # type: ignore[return]
    """Load the shipped build workflow once per module."""
    return load_workflow(_BUILD_WORKFLOW)


def _get_top_level_step(loaded_build, step_id: str) -> ScriptStep:
    """Return the named top-level script step, failing if absent or wrong type."""
    for step in loaded_build.workflow.steps:
        if step.id == step_id:
            assert isinstance(step, ScriptStep), (
                f"{step_id!r} step should be ScriptStep, got {type(step)}"
            )
            return step  # type: ignore[return-value]
    pytest.fail(f"{step_id!r} step not found in build workflow")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command in repo, raising on non-zero exit."""
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Structural tests — attempt-merge
# ---------------------------------------------------------------------------


def test_attempt_merge_is_between_commit_and_conflict_loop(loaded_build) -> None:
    """attempt-merge must appear between commit and conflict-loop in step order."""
    step_ids = [s.id for s in loaded_build.workflow.steps]
    assert "attempt-merge" in step_ids
    commit_idx = step_ids.index("commit")
    am_idx = step_ids.index("attempt-merge")
    cl_idx = step_ids.index("conflict-loop")
    assert commit_idx < am_idx < cl_idx, (
        f"Expected commit < attempt-merge < conflict-loop; got: {step_ids}"
    )


def test_attempt_merge_contract_writes_merge_status_and_conflict_files(
    loaded_build,
) -> None:
    """attempt-merge writes merge_status and conflict_files to state."""
    step = _get_top_level_step(loaded_build, "attempt-merge")
    write_fields = [w.field for w in step.writes]
    assert "merge_status" in write_fields
    assert "conflict_files" in write_fields


def test_attempt_merge_cwd_is_main_repo(loaded_build) -> None:
    """attempt-merge must use cwd='.' to run git commands in the main repo checkout."""
    step = _get_top_level_step(loaded_build, "attempt-merge")
    assert step.cwd == ".", (
        "attempt-merge must run in the main repo (cwd='.') to perform the "
        "merge in the primary checkout, not the worktree"
    )


def test_attempt_merge_args_include_base_branch_and_feature_branch(
    loaded_build,
) -> None:
    """attempt-merge must pass $inputs.base_branch and $state.worktree_branch as args."""
    step = _get_top_level_step(loaded_build, "attempt-merge")
    assert "$inputs.base_branch" in step.args, (
        "attempt-merge must pass $inputs.base_branch to check out the base before merging"
    )
    assert "$state.worktree_branch" in step.args, (
        "attempt-merge must pass $state.worktree_branch as the feature branch to merge"
    )


def test_attempt_merge_uses_no_ff_merge(loaded_build) -> None:
    """attempt-merge must use --no-ff to always create a merge commit."""
    step = _get_top_level_step(loaded_build, "attempt-merge")
    assert step.command is not None
    assert "--no-ff" in step.command, (
        "attempt-merge must use 'git merge --no-ff' to preserve branch topology"
    )


def test_attempt_merge_git_commands_redirect_to_stderr(loaded_build) -> None:
    """attempt-merge git commands must redirect stdout to stderr."""
    step = _get_top_level_step(loaded_build, "attempt-merge")
    assert step.command is not None
    git_lines = [
        line.strip()
        for line in step.command.splitlines()
        if line.strip().startswith("git ")
    ]
    assert git_lines, "attempt-merge has no git commands"
    offending = [line for line in git_lines if ">&2" not in line]
    assert not offending, (
        "These git command lines in attempt-merge do not redirect to stderr:\n"
        + "\n".join(f"  {line}" for line in offending)
    )


# ---------------------------------------------------------------------------
# Structural tests — conflict-loop
# ---------------------------------------------------------------------------


def test_conflict_loop_exists_with_correct_inner_steps(loaded_build) -> None:
    """conflict-loop inner steps: gate-still-conflicted, resolve-conflicts, gate-conflict-resolved.
    """
    conflict_loop = next(
        (s for s in loaded_build.workflow.steps if s.id == "conflict-loop"), None
    )
    assert conflict_loop is not None, "conflict-loop step not found in build workflow"
    assert isinstance(conflict_loop, LoopStep), (
        f"conflict-loop should be a LoopStep, got {type(conflict_loop)}"
    )
    inner_ids = [s.id for s in conflict_loop.loop.steps]
    assert inner_ids == ["gate-still-conflicted", "resolve-conflicts", "gate-conflict-resolved"], (
        f"conflict-loop inner steps must be [gate-still-conflicted, resolve-conflicts, "
        f"gate-conflict-resolved]; got {inner_ids}"
    )


def test_conflict_loop_max_iterations_is_2(loaded_build) -> None:
    """conflict-loop allows at most 2 AI resolution attempts."""
    conflict_loop = next(s for s in loaded_build.workflow.steps if s.id == "conflict-loop")
    assert isinstance(conflict_loop, LoopStep)
    assert conflict_loop.loop.max_iterations == 2, (
        "conflict-loop must cap at 2 iterations — a third attempt with the same "
        "context won't help and the conflict is likely semantic"
    )


def test_conflict_loop_on_exhaust_is_continue(loaded_build) -> None:
    """conflict-loop uses on_exhaust: continue so post-loop steps handle failure."""
    conflict_loop = next(s for s in loaded_build.workflow.steps if s.id == "conflict-loop")
    assert isinstance(conflict_loop, LoopStep)
    assert conflict_loop.loop.on_exhaust == "continue", (
        "conflict-loop must use on_exhaust: continue so notify-merge-exhausted "
        "and gate-merge-clean can handle the failure path"
    )


def test_conflict_loop_until_predicate(loaded_build) -> None:
    """conflict-loop exits when merge_status is clean."""
    conflict_loop = next(s for s in loaded_build.workflow.steps if s.id == "conflict-loop")
    assert isinstance(conflict_loop, LoopStep)
    assert conflict_loop.loop.until is not None
    assert "merge_status" in conflict_loop.loop.until
    assert "clean" in conflict_loop.loop.until


def test_gate_conflict_resolved_retries_loop_on_fail(loaded_build) -> None:
    """gate-conflict-resolved must retry conflict-loop on failure."""
    conflict_loop = next(s for s in loaded_build.workflow.steps if s.id == "conflict-loop")
    assert isinstance(conflict_loop, LoopStep)
    gate = next(s for s in conflict_loop.loop.steps if s.id == "gate-conflict-resolved")
    assert isinstance(gate, CheckStep)
    assert gate.on_fail == "retry_loop:conflict-loop", (
        "gate-conflict-resolved must retry the conflict-loop when merge is still conflicted"
    )


def test_gate_still_conflicted_prevents_ai_on_clean_path(loaded_build) -> None:
    """gate-still-conflicted must use on_fail: retry_loop:conflict-loop.

    When merge_status is 'clean', the expr evaluates False and on_fail fires,
    skipping resolve-conflicts. This prevents the AI from running unnecessarily
    on the clean path through the loop.
    """
    conflict_loop = next(s for s in loaded_build.workflow.steps if s.id == "conflict-loop")
    assert isinstance(conflict_loop, LoopStep)
    gate = next(s for s in conflict_loop.loop.steps if s.id == "gate-still-conflicted")
    assert isinstance(gate, CheckStep)
    assert gate.on_fail == "retry_loop:conflict-loop", (
        "gate-still-conflicted must use on_fail: retry_loop:conflict-loop so "
        "that when merge_status is 'clean' the loop skips resolve-conflicts"
    )
    assert "merge_status" in gate.expr, (
        "gate-still-conflicted must check state.merge_status"
    )
    assert "conflict" in gate.expr, (
        "gate-still-conflicted must test for 'conflict' status"
    )


# ---------------------------------------------------------------------------
# Structural tests — notify-merge-exhausted, gate-merge-clean, push-base
# ---------------------------------------------------------------------------


def test_merge_phase_step_order(loaded_build) -> None:
    """Merge phase steps appear in the correct order after commit."""
    step_ids = [s.id for s in loaded_build.workflow.steps]
    expected_sequence = [
        "commit",
        "attempt-merge",
        "conflict-loop",
        "notify-merge-exhausted",
        "gate-merge-clean",
        "push-base",
        "teardown",
    ]
    # Find positions for all expected steps
    positions = {sid: step_ids.index(sid) for sid in expected_sequence if sid in step_ids}
    missing = [sid for sid in expected_sequence if sid not in positions]
    assert not missing, f"Missing merge phase steps: {missing}"

    # Verify monotonically increasing order
    ordered = sorted(expected_sequence, key=lambda s: positions[s])
    assert ordered == expected_sequence, (
        f"Merge phase steps out of order. Expected {expected_sequence}, "
        f"got positions: {positions}"
    )


def test_notify_merge_exhausted_is_noop_on_clean(loaded_build) -> None:
    """notify-merge-exhausted must guard on merge_status == 'conflict' to be a no-op on clean."""
    step = _get_top_level_step(loaded_build, "notify-merge-exhausted")
    assert step.command is not None
    assert "conflict" in step.command, (
        "notify-merge-exhausted must check merge_status before taking action "
        "so it is a no-op on the clean path"
    )


def test_notify_merge_exhausted_rescue_pushes_feature_branch(loaded_build) -> None:
    """notify-merge-exhausted must push the feature branch for manual inspection."""
    step = _get_top_level_step(loaded_build, "notify-merge-exhausted")
    assert step.command is not None
    assert "git push" in step.command, (
        "notify-merge-exhausted must rescue-push the feature branch so work "
        "is accessible for manual conflict resolution"
    )


def test_gate_merge_clean_cancels_on_conflict(loaded_build) -> None:
    """gate-merge-clean must cancel when merge is still conflicted."""
    gate = next(
        (s for s in loaded_build.workflow.steps if s.id == "gate-merge-clean"), None
    )
    assert gate is not None, "gate-merge-clean not found in workflow"
    assert isinstance(gate, CheckStep)
    assert gate.on_fail == "cancel", (
        "gate-merge-clean must cancel on conflict — the rescue push has already "
        "been done by notify-merge-exhausted"
    )
    assert "merge_status" in gate.expr
    assert "clean" in gate.expr


def test_push_base_pushes_base_branch_arg(loaded_build) -> None:
    """push-base must use $inputs.base_branch as its argument."""
    step = _get_top_level_step(loaded_build, "push-base")
    assert "$inputs.base_branch" in step.args, (
        "push-base must push $inputs.base_branch to origin"
    )


def test_push_base_git_commands_redirect_to_stderr(loaded_build) -> None:
    """push-base git commands must redirect stdout to stderr."""
    step = _get_top_level_step(loaded_build, "push-base")
    assert step.command is not None
    git_lines = [
        line.strip()
        for line in step.command.splitlines()
        if line.strip().startswith("git ")
    ]
    assert git_lines, "push-base has no git commands"
    offending = [line for line in git_lines if ">&2" not in line]
    assert not offending, (
        "push-base git commands must redirect stdout to stderr (>&2)"
    )


# ---------------------------------------------------------------------------
# Functional tests — attempt-merge script (real git)
# ---------------------------------------------------------------------------


def _make_repo_with_clean_feature_branch(tmp_path: Path) -> tuple[Path, str, str]:
    """Create a test repo where feature branch merges cleanly into base.

    Returns (repo_path, base_branch, feature_branch).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "dev")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    # Initial commit on dev
    (repo / "README.md").write_text("base content\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    # Create feature branch with a new file (no conflict)
    _git(repo, "checkout", "-b", "feature/HAR-99-test")
    (repo / "feature.txt").write_text("new feature\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "add feature")
    # Switch back to dev
    _git(repo, "checkout", "dev")
    return repo, "dev", "feature/HAR-99-test"


def _make_repo_with_conflicting_feature_branch(
    tmp_path: Path,
) -> tuple[Path, str, str]:
    """Create a test repo where feature branch conflicts with base.

    Both branches modify the same file on the same line.
    Returns (repo_path, base_branch, feature_branch).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "dev")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    # Initial commit
    (repo / "shared.txt").write_text("original content\n")
    _git(repo, "add", "shared.txt")
    _git(repo, "commit", "-m", "initial")
    # Feature branch: modify shared.txt
    _git(repo, "checkout", "-b", "feature/conflict-test")
    (repo / "shared.txt").write_text("feature version\n")
    _git(repo, "add", "shared.txt")
    _git(repo, "commit", "-m", "feature changes shared.txt")
    # Back on dev: also modify shared.txt → creates a conflict
    _git(repo, "checkout", "dev")
    (repo / "shared.txt").write_text("dev version\n")
    _git(repo, "add", "shared.txt")
    _git(repo, "commit", "-m", "dev changes shared.txt")
    return repo, "dev", "feature/conflict-test"


@pytest.mark.slow
def test_attempt_merge_clean_path(tmp_path: Path) -> None:
    """attempt-merge emits {merge_status: clean, conflict_files: ''} when no conflict."""
    repo, base_branch, feature_branch = _make_repo_with_clean_feature_branch(tmp_path)

    loaded = load_workflow(_BUILD_WORKFLOW)
    step = _get_top_level_step(loaded, "attempt-merge")
    assert step.command is not None

    result = subprocess.run(
        ["bash", "-c", step.command, "test", base_branch, feature_branch],
        capture_output=True,
        text=True,
        cwd=str(repo),
    )
    assert result.returncode == 0, (
        f"attempt-merge script failed (exit {result.returncode}):\n{result.stderr}"
    )
    payload = json.loads(result.stdout)
    assert payload["merge_status"] == "clean", (
        f"Expected merge_status='clean' for a non-conflicting merge, got {payload!r}"
    )
    assert payload["conflict_files"] == "", (
        f"Expected empty conflict_files for clean merge, got {payload['conflict_files']!r}"
    )

    # Verify the merge commit was created on the base branch
    log = subprocess.run(
        ["git", "log", "--oneline", "-3"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    # With --no-ff, a merge commit is always created
    assert "Merge" in log.stdout or "merge" in log.stdout.lower() or "feature" in log.stdout, (
        f"Expected a merge commit on dev after clean merge, got:\n{log.stdout}"
    )


@pytest.mark.slow
def test_attempt_merge_conflict_path(tmp_path: Path) -> None:
    """attempt-merge emits {merge_status: conflict, conflict_files: <list>} on conflict."""
    repo, base_branch, feature_branch = _make_repo_with_conflicting_feature_branch(tmp_path)

    loaded = load_workflow(_BUILD_WORKFLOW)
    step = _get_top_level_step(loaded, "attempt-merge")
    assert step.command is not None

    result = subprocess.run(
        ["bash", "-c", step.command, "test", base_branch, feature_branch],
        capture_output=True,
        text=True,
        cwd=str(repo),
    )
    # The script always exits 0 (conflict is handled in the else branch)
    assert result.returncode == 0, (
        f"attempt-merge script exited non-zero (exit {result.returncode}):\n{result.stderr}"
    )
    payload = json.loads(result.stdout)
    assert payload["merge_status"] == "conflict", (
        f"Expected merge_status='conflict' for conflicting branches, got {payload!r}"
    )
    assert "shared.txt" in payload["conflict_files"], (
        f"Expected 'shared.txt' in conflict_files, got {payload['conflict_files']!r}"
    )

    # Clean up the failed merge so the tmp repo is consistent
    subprocess.run(["git", "merge", "--abort"], cwd=repo, capture_output=True)


@pytest.mark.slow
def test_attempt_merge_clean_path_updates_base_branch(tmp_path: Path) -> None:
    """After a clean merge, the base branch HEAD is a merge commit containing the feature."""
    repo, base_branch, feature_branch = _make_repo_with_clean_feature_branch(tmp_path)

    loaded = load_workflow(_BUILD_WORKFLOW)
    step = _get_top_level_step(loaded, "attempt-merge")
    assert step.command is not None

    subprocess.run(
        ["bash", "-c", step.command, "test", base_branch, feature_branch],
        capture_output=True,
        text=True,
        cwd=str(repo),
        check=True,
    )

    # After merge: feature.txt must exist on the base branch
    assert (repo / "feature.txt").exists(), (
        "feature.txt must exist on dev after merging the feature branch"
    )

    # The base branch HEAD should be a merge commit (two parents)
    parents = subprocess.run(
        ["git", "log", "--pretty=%P", "-1"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    parent_list = parents.stdout.strip().split()
    assert len(parent_list) == 2, (
        f"Expected merge commit with 2 parents (--no-ff), got: {parents.stdout.strip()!r}"
    )


# ---------------------------------------------------------------------------
# Integration test — clean merge end-to-end via Runner
# ---------------------------------------------------------------------------


def _make_repo_with_feature_branch_for_runner(
    tmp_path: Path,
) -> tuple[Path, Path, str, str]:
    """Set up a repo + bare remote for the Runner integration test.

    Creates:
    - ``repo/``: main repo with a feature branch that merges cleanly into dev.
    - ``bare/``: bare clone acting as the origin remote.

    The feature branch is checked out as a worktree-style setup: the repo is
    left on ``dev`` so ``attempt-merge`` can do ``git checkout dev`` + merge.

    Returns (repo, bare, base_branch, feature_branch).
    """
    repo = tmp_path / "repo"
    bare = tmp_path / "bare.git"
    repo.mkdir()

    # Init repo on dev with initial commit
    _git(repo, "init", "-b", "dev")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("base content\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")

    # Create feature branch with a new file (clean merge)
    _git(repo, "checkout", "-b", "harness/feat-123")
    (repo / "feature.txt").write_text("new feature\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "add feature")
    # Return to dev so attempt-merge can proceed
    _git(repo, "checkout", "dev")

    # Create bare repo and add as origin remote
    _git(repo, "init", "--bare", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    # Push dev to remote so push-base has an upstream ref
    _git(repo, "push", "origin", "dev")

    return repo, bare, "dev", "harness/feat-123"


def _make_merge_test_workflow(tmp_path: Path, prompts_dir: Path) -> Path:
    """Write a minimal merge-phase workflow YAML to tmp_path.

    This workflow contains ONLY the merge-phase steps (no Linear API calls).
    It uses a stub close-task that outputs {} without external calls.
    """
    wf_path = tmp_path / "merge_test.yaml"
    wf_path.write_text(textwrap.dedent("""\
        name: merge-test
        version: 1
        inputs:
          base_branch:
            type: string
            default: dev
            required: false
          feature_branch:
            type: string
            required: true
        steps:
          - id: setup
            type: worktree
            action: create
            base: $inputs.base_branch
            writes: [worktree_path, worktree_branch]

          - id: make-feature-commit
            type: script
            command: |
              echo "worktree change" > worktree_change.txt
              git add worktree_change.txt
              git commit -m "add worktree change" >&2
              printf '{}'
            writes: []

          - id: attempt-merge
            type: script
            cwd: "."
            command: |
              git checkout "$1" >&2
              if git merge --no-ff "$2" >&2; then
                printf '{"merge_status": "clean", "conflict_files": ""}'
              else
                CONFLICTS=$(git diff --name-only --diff-filter=U | tr '\\n' ',' | sed 's/,$//')
                printf '{"merge_status": "conflict", "conflict_files": "%s"}' "$CONFLICTS"
              fi
            args: ["$inputs.base_branch", "$state.worktree_branch"]
            contract:
              merge_status:
                type: string
                enum: [clean, conflict]
              conflict_files: string
            writes: [merge_status, conflict_files]

          - id: conflict-loop
            type: loop
            loop:
              max_iterations: 2
              until: 'state.merge_status == "clean"'
              on_exhaust: continue
              steps:

                - id: gate-still-conflicted
                  type: check
                  expr: 'state.merge_status == "conflict"'
                  on_fail: "retry_loop:conflict-loop"

                - id: resolve-conflicts
                  type: ai
                  agent: claude
                  model: sonnet
                  cwd: "."
                  prompt: prompts/build/resolve-conflicts.j2
                  allowed_tools: [Read, Write, Edit, Bash, Grep, Glob]
                  writes_files: true
                  contract:
                    merge_status:
                      type: string
                      enum: [clean, conflict]
                    merge_commit_message: string
                  writes: [merge_status, merge_commit_message]

                - id: gate-conflict-resolved
                  type: check
                  expr: 'state.merge_status == "clean"'
                  on_fail: "retry_loop:conflict-loop"

          - id: notify-merge-exhausted
            type: script
            cwd: "."
            command: |
              if [ "$1" = "conflict" ]; then
                printf '{}' >&2
                exit 1
              fi
              printf '{}'
            args: ["$state.merge_status"]
            writes: []

          - id: gate-merge-clean
            type: check
            expr: 'state.merge_status == "clean"'
            on_fail: cancel

          - id: push-base
            type: script
            cwd: "."
            command: |
              git push origin "$1" >&2
              printf '{}'
            args: ["$inputs.base_branch"]
            writes: []

          - id: teardown
            type: worktree
            action: cleanup
            policy: delete_unconditionally

          - id: close-task
            type: script
            cwd: "."
            command: |
              printf '{}'
            writes: []
    """))

    # Write stub prompt file so AINode can render it (won't be called on clean path)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "build").mkdir(parents=True, exist_ok=True)
    (prompts_dir / "build" / "resolve-conflicts.j2").write_text(
        "Resolve conflicts in {{ state.conflict_files }}\n"
    )

    return wf_path


@pytest.mark.slow
async def test_clean_merge_end_to_end_via_runner(tmp_path: Path) -> None:
    """Runner executes the full merge phase end-to-end on the clean path.

    Verifies:
    - exit_code == 0
    - The feature commit is now on the base branch (dev) locally
    - The base branch HEAD is a merge commit (--no-ff)
    - The worktree directory has been removed (teardown ran)
    - The run-id worktree branch has been deleted locally
    - Remote dev (bare) was updated by push-base
    - No remote feature/worktree branch was created on the success path
    - The resolve-conflicts AI step was NOT called (clean path)
    """
    repo, bare, base_branch, feature_branch = _make_repo_with_feature_branch_for_runner(
        tmp_path
    )

    db = tmp_path / "harness.db"
    await init_db(db)

    prompts_dir = tmp_path / "prompts"
    wf_path = _make_merge_test_workflow(tmp_path, prompts_dir)

    # MockAgent with empty queue — resolve-conflicts won't be called on clean path
    agent = MockAgent()

    runner = Runner(
        agent=agent,
        db_path=db,
        repo_root=repo,
        prompts_dir=prompts_dir,
        progress=False,
    )
    exit_code = await runner.run(
        wf_path,
        inputs={
            "base_branch": base_branch,
            "feature_branch": feature_branch,
        },
        base_branch=base_branch,
    )

    assert exit_code == 0, (
        f"Expected exit_code=0 on clean merge, got {exit_code}"
    )

    # The commit made in the worktree (worktree_change.txt) should now be on dev
    # after the no-ff merge of the worktree branch into dev.
    assert (repo / "worktree_change.txt").exists(), (
        "worktree_change.txt must be present on dev after clean merge of worktree branch"
    )

    # The base branch (dev) HEAD should be a merge commit (two parents, --no-ff)
    parents = subprocess.run(
        ["git", "log", "--pretty=%P", "-1"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    parent_list = parents.stdout.strip().split()
    assert len(parent_list) == 2, (
        f"Expected merge commit with 2 parents (--no-ff) on dev, "
        f"got: {parents.stdout.strip()!r}"
    )

    # Worktree directory should be removed (teardown with delete_unconditionally ran)
    worktrees_dir = repo / ".worktrees" / "harness"
    if worktrees_dir.exists():
        remaining = list(worktrees_dir.iterdir())
        assert not remaining, (
            f"Expected all worktrees removed after teardown, found: {remaining}"
        )

    # The worktree branch (harness/<run_id>) should have been deleted by teardown
    # We check that no harness/* branches remain (excluding harness/feat-123 which we
    # set up as the external feature branch — that's unrelated to the workflow's worktree)
    branches_result = subprocess.run(
        ["git", "branch", "--list"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    all_branches = [
        b.strip().lstrip("* ")
        for b in branches_result.stdout.splitlines()
        if b.strip()
    ]
    # The run-id branch (harness/<run_id>) should be gone; only dev (and possibly
    # harness/feat-123 from setup) remain
    run_branches = [b for b in all_branches if b.startswith("harness/") and b != "harness/feat-123"]
    assert not run_branches, (
        f"Expected harness run branch deleted after teardown, found: {run_branches}"
    )

    # --- Remote ref assertions (Issues 4/6) ---

    # push-base must have pushed dev to the bare remote; verify the remote
    # dev SHA matches the local dev HEAD (merge commit).
    # Use --git-dir so git commands work against a bare repository.
    local_dev_sha = subprocess.run(
        ["git", "rev-parse", f"refs/heads/{base_branch}"],
        cwd=repo,
        capture_output=True,
        text=True,
    ).stdout.strip()

    remote_dev_sha = subprocess.run(
        ["git", "--git-dir", str(bare), "rev-parse", f"refs/heads/{base_branch}"],
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert remote_dev_sha == local_dev_sha, (
        f"Remote dev ({remote_dev_sha!r}) must match local dev ({local_dev_sha!r}) "
        "after push-base — push-base must have pushed to origin"
    )

    # On the success path, no feature/worktree branch must be pushed to the remote.
    # The remote should only have the dev branch; the worktree branch is deleted
    # locally by teardown and is never pushed (only rescue-pushed on failure).
    remote_refs_result = subprocess.run(
        ["git", "--git-dir", str(bare), "for-each-ref",
         "--format=%(refname:short)", "refs/heads/"],
        capture_output=True,
        text=True,
    )
    remote_branches = [
        b.strip()
        for b in remote_refs_result.stdout.splitlines()
        if b.strip()
    ]
    # The only remote branch should be dev; no harness/* branch should appear
    # (the worktree branch is never pushed on the clean/success path).
    remote_harness_branches = [b for b in remote_branches if b.startswith("harness/")]
    assert not remote_harness_branches, (
        f"No remote harness/* branch should be created on the success path "
        f"(feature branch is never pushed on success); found: {remote_harness_branches}"
    )

    # The resolve-conflicts AI step must NOT be called on the clean path
    assert agent.calls == [], (
        "resolve-conflicts AI step must NOT be called on the clean path"
    )


# ---------------------------------------------------------------------------
# Behavioral tests — conflict-loop orchestration
# ---------------------------------------------------------------------------


class _ConflictReturningAgent(MockAgent):
    """Stand-in that always reports merge_status=conflict from resolve-conflicts."""

    async def execute(  # type: ignore[override]
        self,
        prompt: str,
        contract: type[BaseModel],
        submit_tool_schema: dict[str, Any],
        *,
        allowed_tools: list[str],
        cwd: Path | None,
        timeout_s: int = 600,
        stall_timeout_s: int = 300,
        max_turns: int | None = None,
    ) -> NodeResult[BaseModel]:
        self.calls.append(
            RecordedCall(
                prompt=prompt,
                contract=contract,
                submit_tool_schema=submit_tool_schema,
                allowed_tools=list(allowed_tools),
                cwd=cwd,
                timeout_s=timeout_s,
                stall_timeout_s=stall_timeout_s,
                max_turns=max_turns,
            )
        )
        return NodeResult[BaseModel](
            contract=contract.model_validate(
                {"merge_status": "conflict", "merge_commit_message": "still conflicted"}
            ),
            attestation=Attestation(status="complete"),
        )


def _make_conflict_loop_only_workflow(tmp_path: Path, prompts_dir: Path) -> Path:
    """Minimal workflow: set merge_status=conflict, run conflict-loop, gate-merge-clean.

    No worktree or Linear calls — isolates conflict orchestration behavior.
    """
    wf_path = tmp_path / "conflict_loop_only.yaml"
    wf_path.write_text(textwrap.dedent("""\
        name: conflict-loop-only
        version: 1
        inputs: {}
        steps:
          - id: set-conflict
            type: script
            command: |
              printf '{"merge_status": "conflict", "conflict_files": "foo.txt"}'
            contract:
              merge_status:
                type: string
                enum: [clean, conflict]
              conflict_files: string
            writes: [merge_status, conflict_files]

          - id: conflict-loop
            type: loop
            loop:
              max_iterations: 2
              until: 'state.merge_status == "clean"'
              on_exhaust: continue
              steps:

                - id: gate-still-conflicted
                  type: check
                  expr: 'state.merge_status == "conflict"'
                  on_fail: "retry_loop:conflict-loop"

                - id: resolve-conflicts
                  type: ai
                  agent: claude
                  model: sonnet
                  prompt: build/resolve-conflicts.j2
                  allowed_tools: [Read, Write, Edit, Bash, Grep, Glob]
                  contract:
                    merge_status:
                      type: string
                      enum: [clean, conflict]
                    merge_commit_message: string
                  writes: [merge_status, merge_commit_message]

                - id: gate-conflict-resolved
                  type: check
                  expr: 'state.merge_status == "clean"'
                  on_fail: "retry_loop:conflict-loop"

          - id: gate-merge-clean
            type: check
            expr: 'state.merge_status == "clean"'
            on_fail: cancel
    """))

    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "build").mkdir(parents=True, exist_ok=True)
    (prompts_dir / "build" / "resolve-conflicts.j2").write_text(
        "Resolve conflicts in {{ state.conflict_files }}\n"
    )
    return wf_path


@pytest.mark.slow
async def test_conflict_loop_limits_ai_to_two_attempts(tmp_path: Path) -> None:
    """conflict-loop caps resolve-conflicts at max_iterations=2 then cancels.

    Verifies:
    - resolve-conflicts is called exactly 2 times (max_iterations=2)
    - exit_code == 1 (gate-merge-clean cancels after loop exhausts with conflict)
    """
    db = tmp_path / "harness.db"
    await init_db(db)

    prompts_dir = tmp_path / "prompts"
    wf_path = _make_conflict_loop_only_workflow(tmp_path, prompts_dir)

    agent = _ConflictReturningAgent()
    runner = Runner(
        agent=agent,
        db_path=db,
        prompts_dir=prompts_dir,
        progress=False,
    )
    exit_code = await runner.run(wf_path, inputs={})

    assert len(agent.calls) == 2, (
        f"resolve-conflicts must be called exactly twice (max_iterations=2), "
        f"but was called {len(agent.calls)} time(s)"
    )
    assert exit_code == 1, (
        "Runner must exit with code 1 when conflict-loop exhausts without resolution"
    )


@pytest.mark.slow
def test_notify_merge_exhausted_script_rescue_pushes_feature_branch(tmp_path: Path) -> None:
    """notify-merge-exhausted git-pushes the feature branch to origin on the conflict path.

    Uses a fake LINEAR_API_KEY intentionally — the git rescue push is the critical
    operation; Linear comment and Todo reset are best-effort and not asserted here.
    """
    repo = tmp_path / "repo"
    bare = tmp_path / "bare.git"
    repo.mkdir()

    _git(repo, "init", "-b", "dev")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("initial\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")

    feature_branch = "harness/feat-conflict"
    _git(repo, "checkout", "-b", feature_branch)
    (repo / "conflict.txt").write_text("conflict work\n")
    _git(repo, "add", "conflict.txt")
    _git(repo, "commit", "-m", "conflict work")
    _git(repo, "checkout", "dev")

    # Bare remote; feature branch intentionally not pushed yet (local-only)
    _git(repo, "init", "--bare", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "origin", "dev")

    loaded = load_workflow(_BUILD_WORKFLOW)
    notify_step = _get_top_level_step(loaded, "notify-merge-exhausted")
    assert notify_step.command is not None

    # LINEAR_API_KEY is fake — curl calls fail silently, git push is real
    env = {**os.environ, "LINEAR_API_KEY": "fake-key"}
    result = subprocess.run(
        [
            "bash", "-c", notify_step.command, "harness-script",
            "conflict", "HAR-TEST", feature_branch, "conflict.txt",
        ],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=env,
    )

    assert result.returncode == 0, (
        f"notify-merge-exhausted script failed (exit {result.returncode}):\n{result.stderr}"
    )

    remote_refs = subprocess.run(
        [
            "git", "--git-dir", str(bare),
            "for-each-ref", "--format=%(refname:short)", "refs/heads/",
        ],
        capture_output=True,
        text=True,
    )
    remote_branches = {b.strip() for b in remote_refs.stdout.splitlines() if b.strip()}
    assert feature_branch in remote_branches, (
        f"notify-merge-exhausted must rescue-push {feature_branch!r} to origin on conflict; "
        f"remote branches found: {sorted(remote_branches)}"
    )


@pytest.mark.slow
def test_notify_merge_exhausted_script_is_noop_on_clean_path(tmp_path: Path) -> None:
    """notify-merge-exhausted skips git push and exits 0 when merge_status is clean."""
    repo = tmp_path / "repo"
    bare = tmp_path / "bare.git"
    repo.mkdir()

    _git(repo, "init", "-b", "dev")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("initial\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")

    _git(repo, "init", "--bare", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "origin", "dev")

    loaded = load_workflow(_BUILD_WORKFLOW)
    notify_step = _get_top_level_step(loaded, "notify-merge-exhausted")
    assert notify_step.command is not None

    env = {**os.environ, "LINEAR_API_KEY": "fake-key"}
    result = subprocess.run(
        [
            "bash", "-c", notify_step.command, "harness-script",
            "clean", "HAR-TEST", "harness/feat", "",
        ],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=env,
    )

    assert result.returncode == 0, (
        f"notify-merge-exhausted should exit 0 on clean path "
        f"(exit {result.returncode}):\n{result.stderr}"
    )
    remote_refs = subprocess.run(
        [
            "git", "--git-dir", str(bare),
            "for-each-ref", "--format=%(refname:short)", "refs/heads/",
        ],
        capture_output=True,
        text=True,
    )
    remote_branches = {b.strip() for b in remote_refs.stdout.splitlines() if b.strip()}
    assert remote_branches == {"dev"}, (
        f"notify-merge-exhausted must not push anything on clean path; "
        f"remote branches: {sorted(remote_branches)}"
    )
    assert result.stdout == "{}", (
        f"notify-merge-exhausted must output '{{}}' on clean path, got: {result.stdout!r}"
    )
