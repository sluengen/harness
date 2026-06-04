"""Tests for harness.nodes.worktree — see SPEC §4.6, §9.

Real git is exercised against tmp_path repos; subprocess is NOT mocked.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from harness.nodes.base import NodeResult
from harness.nodes.worktree import (
    WorktreeCleanupOutput,
    WorktreeCreateOutput,
    WorktreeNode,
    WorktreeNodeError,
)

pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Synchronous git invocation for test setup/assertions."""
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[Path]:
    """A throw-away repo with one commit on `main`."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "main")
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    (repo_root / "README.md").write_text("hello\n")
    _git(repo_root, "add", "README.md")
    _git(repo_root, "commit", "-m", "initial")
    yield repo_root


def _branch_exists(repo_root: Path, name: str) -> bool:
    proc = subprocess.run(
        ["git", "branch", "--list", name],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(proc.stdout.strip())


# ---------------------------------------------------------------------------
# Contracts (smoke)
# ---------------------------------------------------------------------------


def test_create_output_shape() -> None:
    out = WorktreeCreateOutput(
        worktree_path=Path("/tmp/wt"),
        worktree_branch="harness/run-1",
    )
    assert out.worktree_path == Path("/tmp/wt")
    assert out.worktree_branch == "harness/run-1"


def test_cleanup_output_shape() -> None:
    out = WorktreeCleanupOutput(
        worktree_removed=True,
        branch_removed=False,
        base_advanced=False,
    )
    assert out.worktree_removed is True
    assert out.branch_removed is False
    assert out.base_advanced is False


# ---------------------------------------------------------------------------
# Create — AC1..AC7
# ---------------------------------------------------------------------------


async def test_ac1_create_produces_worktree_directory(repo: Path) -> None:
    """AC1: worktree dir at <repo>/.worktrees/harness/<run_id>/ and is a git work tree."""
    node = WorktreeNode()
    result = await node.create(run_id="run-1", repo_root=repo, base="main")

    expected_path = repo / ".worktrees" / "harness" / "run-1"
    assert expected_path.exists()
    assert expected_path.is_dir()
    proc = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=expected_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert proc.stdout.strip() == "true"
    assert result.contract.worktree_path == expected_path


async def test_ac2_worktree_on_run_branch(repo: Path) -> None:
    """AC2: worktree HEAD is on `harness/<run_id>` branch."""
    node = WorktreeNode()
    await node.create(run_id="run-2", repo_root=repo, base="main")

    wt = repo / ".worktrees" / "harness" / "run-2"
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=wt,
        check=True,
        capture_output=True,
        text=True,
    )
    assert proc.stdout.strip() == "harness/run-2"


async def test_ac3_worktree_starts_at_base_sha(repo: Path) -> None:
    """AC3: worktree's initial commit equals base branch's commit."""
    base_sha = _git(repo, "rev-parse", "main").stdout.strip()

    node = WorktreeNode()
    await node.create(run_id="run-3", repo_root=repo, base="main")

    wt = repo / ".worktrees" / "harness" / "run-3"
    wt_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=wt,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert wt_sha == base_sha


async def test_ac4_node_result_contract_and_attestation(repo: Path) -> None:
    """AC4: NodeResult.contract has path/branch; attestation status is `complete`."""
    node = WorktreeNode()
    result: NodeResult[WorktreeCreateOutput] = await node.create(
        run_id="run-4", repo_root=repo, base="main"
    )

    dump = result.contract.model_dump()
    assert dump["worktree_branch"] == "harness/run-4"
    assert dump["worktree_path"] == repo / ".worktrees" / "harness" / "run-4"
    assert result.attestation.status == "complete"


async def test_ac5_concurrent_runs_do_not_collide(repo: Path) -> None:
    """AC5: two creates with different run_ids both succeed and coexist."""
    node = WorktreeNode()
    await node.create(run_id="run-A", repo_root=repo, base="main")
    await node.create(run_id="run-B", repo_root=repo, base="main")

    a = repo / ".worktrees" / "harness" / "run-A"
    b = repo / ".worktrees" / "harness" / "run-B"
    assert a.exists() and b.exists()
    assert _branch_exists(repo, "harness/run-A")
    assert _branch_exists(repo, "harness/run-B")


async def test_ac6_duplicate_run_id_raises(repo: Path) -> None:
    """AC6: re-running create with same run_id raises; existing worktree is intact."""
    node = WorktreeNode()
    await node.create(run_id="run-dup", repo_root=repo, base="main")
    wt = repo / ".worktrees" / "harness" / "run-dup"
    sentinel = wt / "sentinel.txt"
    sentinel.write_text("preserved\n")

    with pytest.raises(WorktreeNodeError):
        await node.create(run_id="run-dup", repo_root=repo, base="main")

    # The existing worktree must still be on disk and unchanged.
    assert sentinel.exists()
    assert sentinel.read_text() == "preserved\n"


async def test_ac7_missing_base_branch_raises_clean(repo: Path) -> None:
    """AC7: bad base branch raises WorktreeNodeError; no leftover worktree dir."""
    node = WorktreeNode()
    with pytest.raises(WorktreeNodeError):
        await node.create(run_id="run-bad", repo_root=repo, base="nope-not-a-branch")

    leftover = repo / ".worktrees" / "harness" / "run-bad"
    assert not leftover.exists()


# ---------------------------------------------------------------------------
# Cleanup — merge_to_base — AC8, AC9
# ---------------------------------------------------------------------------


async def test_ac8_merge_to_base_ff_advances_base(repo: Path) -> None:
    """AC8: merge_to_base ff-merges base, removes worktree dir, deletes branch."""
    node = WorktreeNode()
    create_result = await node.create(run_id="run-m", repo_root=repo, base="main")
    wt = create_result.contract.worktree_path

    # Make a commit inside the worktree.
    (wt / "feature.txt").write_text("data\n")
    _git(wt, "add", "feature.txt")
    _git(wt, "commit", "-m", "feat")
    wt_tip = _git(wt, "rev-parse", "HEAD").stdout.strip()

    cleanup = await node.cleanup(
        run_id="run-m",
        repo_root=repo,
        worktree_path=wt,
        worktree_branch="harness/run-m",
        base="main",
        policy="merge_to_base",
    )

    main_sha = _git(repo, "rev-parse", "main").stdout.strip()
    assert main_sha == wt_tip
    assert not wt.exists()
    assert not _branch_exists(repo, "harness/run-m")
    assert cleanup.contract.worktree_removed is True
    assert cleanup.contract.branch_removed is True
    assert cleanup.contract.base_advanced is True


async def test_ac9_merge_to_base_diverged_raises(repo: Path) -> None:
    """AC9: ff impossible — raise; worktree + branch preserved for investigation."""
    node = WorktreeNode()
    create_result = await node.create(run_id="run-d", repo_root=repo, base="main")
    wt = create_result.contract.worktree_path

    # Commit on the worktree branch.
    (wt / "feature.txt").write_text("data\n")
    _git(wt, "add", "feature.txt")
    _git(wt, "commit", "-m", "feat")

    # Commit on main (in the source repo) — diverges.
    (repo / "other.txt").write_text("other\n")
    _git(repo, "add", "other.txt")
    _git(repo, "commit", "-m", "other")

    with pytest.raises(WorktreeNodeError):
        await node.cleanup(
            run_id="run-d",
            repo_root=repo,
            worktree_path=wt,
            worktree_branch="harness/run-d",
            base="main",
            policy="merge_to_base",
        )

    assert wt.exists()
    assert _branch_exists(repo, "harness/run-d")


# ---------------------------------------------------------------------------
# Cleanup — leave_for_inspection — AC10, AC11
# ---------------------------------------------------------------------------


async def test_ac10_leave_for_inspection_removes_dir_keeps_branch(repo: Path) -> None:
    """AC10: worktree dir removed, branch preserved."""
    node = WorktreeNode()
    create_result = await node.create(run_id="run-l", repo_root=repo, base="main")
    wt = create_result.contract.worktree_path

    cleanup = await node.cleanup(
        run_id="run-l",
        repo_root=repo,
        worktree_path=wt,
        worktree_branch="harness/run-l",
        base=None,
        policy="leave_for_inspection",
    )

    assert not wt.exists()
    assert _branch_exists(repo, "harness/run-l")
    assert cleanup.contract.worktree_removed is True
    assert cleanup.contract.branch_removed is False
    assert cleanup.contract.base_advanced is False


async def test_ac11_leave_for_inspection_idempotent(repo: Path) -> None:
    """AC11: re-running on an already-removed worktree does not crash."""
    node = WorktreeNode()
    create_result = await node.create(run_id="run-l2", repo_root=repo, base="main")
    wt = create_result.contract.worktree_path

    # First call: removes dir.
    await node.cleanup(
        run_id="run-l2",
        repo_root=repo,
        worktree_path=wt,
        worktree_branch="harness/run-l2",
        base=None,
        policy="leave_for_inspection",
    )
    # Second call: dir is gone, branch still there.
    second = await node.cleanup(
        run_id="run-l2",
        repo_root=repo,
        worktree_path=wt,
        worktree_branch="harness/run-l2",
        base=None,
        policy="leave_for_inspection",
    )

    assert second.contract.worktree_removed is False
    assert second.contract.branch_removed is False
    assert _branch_exists(repo, "harness/run-l2")


# ---------------------------------------------------------------------------
# Cleanup — delete_unconditionally — AC12, AC13
# ---------------------------------------------------------------------------


async def test_ac12_delete_unconditionally_with_uncommitted_changes(repo: Path) -> None:
    """AC12: worktree + branch removed even when worktree has uncommitted edits."""
    node = WorktreeNode()
    create_result = await node.create(run_id="run-x", repo_root=repo, base="main")
    wt = create_result.contract.worktree_path

    # Uncommitted change.
    (wt / "dirty.txt").write_text("dirty\n")

    cleanup = await node.cleanup(
        run_id="run-x",
        repo_root=repo,
        worktree_path=wt,
        worktree_branch="harness/run-x",
        base=None,
        policy="delete_unconditionally",
    )

    assert not wt.exists()
    assert not _branch_exists(repo, "harness/run-x")
    assert cleanup.contract.worktree_removed is True
    assert cleanup.contract.branch_removed is True
    assert cleanup.contract.base_advanced is False


async def test_ac13_delete_unconditionally_force_deletes_ahead_branch(repo: Path) -> None:
    """AC13: branch ahead of base is force-deleted."""
    node = WorktreeNode()
    create_result = await node.create(run_id="run-a", repo_root=repo, base="main")
    wt = create_result.contract.worktree_path
    (wt / "feature.txt").write_text("data\n")
    _git(wt, "add", "feature.txt")
    _git(wt, "commit", "-m", "feat")

    await node.cleanup(
        run_id="run-a",
        repo_root=repo,
        worktree_path=wt,
        worktree_branch="harness/run-a",
        base=None,
        policy="delete_unconditionally",
    )

    assert not _branch_exists(repo, "harness/run-a")
    assert not wt.exists()


# ---------------------------------------------------------------------------
# Edge cases — AC14, AC15
# ---------------------------------------------------------------------------


async def test_ac14_cleanup_missing_worktree_raises(repo: Path) -> None:
    """AC14: cleanup of a never-created worktree raises (strict failure)."""
    node = WorktreeNode()
    bogus = repo / ".worktrees" / "harness" / "ghost"

    with pytest.raises(WorktreeNodeError):
        await node.cleanup(
            run_id="ghost",
            repo_root=repo,
            worktree_path=bogus,
            worktree_branch="harness/ghost",
            base="main",
            policy="merge_to_base",
        )


@pytest.mark.parametrize(
    "policy",
    ["merge_to_base", "leave_for_inspection", "delete_unconditionally"],
)
async def test_ac15_cleanup_prunes_worktree_metadata(repo: Path, policy: str) -> None:
    """AC15: after cleanup, `git worktree list --porcelain` has no stale entries."""
    node = WorktreeNode()
    create_result = await node.create(
        run_id=f"run-prune-{policy}", repo_root=repo, base="main"
    )
    wt = create_result.contract.worktree_path

    if policy == "merge_to_base":
        # ff-merge needs at least the same SHA, which it already has — no-op merge OK.
        pass

    await node.cleanup(
        run_id=f"run-prune-{policy}",
        repo_root=repo,
        worktree_path=wt,
        worktree_branch=f"harness/run-prune-{policy}",
        base="main" if policy == "merge_to_base" else None,
        policy=policy,  # type: ignore[arg-type]
    )

    proc = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    # The only listed worktree should be the main repo itself.
    assert str(wt) not in proc.stdout


# ---------------------------------------------------------------------------
# Protocol conformance — AC16
# ---------------------------------------------------------------------------


def test_ac16_node_type_is_worktree() -> None:
    """AC16: WorktreeNode declares `type: Literal['worktree']`."""
    assert WorktreeNode().type == "worktree"


# ---------------------------------------------------------------------------
# Index sync after merge_to_base — AC17
# ---------------------------------------------------------------------------


async def test_ac17_merge_to_base_index_synced_after_cleanup(repo: Path) -> None:
    """AC17: after merge_to_base the main working tree index matches HEAD.

    Before the fix, ``git update-ref`` advanced HEAD but left the index
    pointing at the old tree, so ``git diff --cached`` showed every new/changed
    file staged for reversal — phantom deletions ready to be committed.
    """
    node = WorktreeNode()
    create_result = await node.create(run_id="run-idx", repo_root=repo, base="main")
    wt = create_result.contract.worktree_path

    # Commit a new file inside the worktree so the merge advances HEAD.
    (wt / "feature.txt").write_text("new file\n")
    _git(wt, "add", "feature.txt")
    _git(wt, "commit", "-m", "feat: add feature")

    await node.cleanup(
        run_id="run-idx",
        repo_root=repo,
        worktree_path=wt,
        worktree_branch="harness/run-idx",
        base="main",
        policy="merge_to_base",
    )

    # The index must be clean relative to the new HEAD — no staged reversals.
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert proc.stdout.strip() == "", (
        f"stale staged changes after merge_to_base: {proc.stdout.strip()!r}"
    )


# ---------------------------------------------------------------------------
# merge_to_base dirty-tree guard — AC18, AC19
# ---------------------------------------------------------------------------


async def test_ac18_merge_to_base_dirty_working_tree_raises(repo: Path) -> None:
    """AC18: merge_to_base refuses when the base working tree has uncommitted
    modifications to tracked files."""
    node = WorktreeNode()
    create_result = await node.create(run_id="run-dirty-wt", repo_root=repo, base="main")
    wt = create_result.contract.worktree_path

    # Commit on the worktree branch so ff-merge would otherwise succeed.
    (wt / "feature.txt").write_text("data\n")
    _git(wt, "add", "feature.txt")
    _git(wt, "commit", "-m", "feat")

    # Dirty the base repo's working tree (modify a tracked file without staging).
    (repo / "README.md").write_text("modified content\n")

    with pytest.raises(WorktreeNodeError, match="dirty"):
        await node.cleanup(
            run_id="run-dirty-wt",
            repo_root=repo,
            worktree_path=wt,
            worktree_branch="harness/run-dirty-wt",
            base="main",
            policy="merge_to_base",
        )

    # The worktree and branch must still exist (no partial cleanup).
    assert wt.exists()
    assert _branch_exists(repo, "harness/run-dirty-wt")


async def test_ac19_merge_to_base_dirty_index_raises(repo: Path) -> None:
    """AC19: merge_to_base refuses when the base index has staged changes."""
    node = WorktreeNode()
    create_result = await node.create(run_id="run-dirty-idx", repo_root=repo, base="main")
    wt = create_result.contract.worktree_path

    # Commit on the worktree branch so ff-merge would otherwise succeed.
    (wt / "feature.txt").write_text("data\n")
    _git(wt, "add", "feature.txt")
    _git(wt, "commit", "-m", "feat")

    # Stage a new file in the base repo (dirty index, no unstaged changes).
    (repo / "staged.txt").write_text("staged content\n")
    _git(repo, "add", "staged.txt")

    with pytest.raises(WorktreeNodeError, match="dirty"):
        await node.cleanup(
            run_id="run-dirty-idx",
            repo_root=repo,
            worktree_path=wt,
            worktree_branch="harness/run-dirty-idx",
            base="main",
            policy="merge_to_base",
        )

    # Spec requires refusal to leave worktree and branch intact.
    assert wt.exists()
    assert _branch_exists(repo, "harness/run-dirty-idx")
