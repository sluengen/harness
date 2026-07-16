"""Tests for harness.worktree (re-homed from harness.nodes.worktree) — SPEC §4.5.

Real git is exercised against tmp_path repos; subprocess is NOT mocked. Since
CAL-574 the worktree lifecycle returns its output models directly (no
``NodeResult`` wrapper) — the verbs call it as a standalone helper.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from harness.worktree import (
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


def _git_version() -> tuple[int, int]:
    """The (major, minor) of the git on PATH — for gating relative-worktree assertions."""
    out = subprocess.run(
        ["git", "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    # "git version 2.50.1 (Apple Git-155)" -> (2, 50)
    parts = out.split()[2].split(".")
    return int(parts[0]), int(parts[1])


_SUPPORTS_RELATIVE_WORKTREES = _git_version() >= (2, 48)


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
# Output models (smoke)
# ---------------------------------------------------------------------------


def test_create_output_shape() -> None:
    out = WorktreeCreateOutput(
        worktree_path=Path("/tmp/wt"),
        worktree_branch="harness/run-1",
    )
    assert out.worktree_path == Path("/tmp/wt")
    assert out.worktree_branch == "harness/run-1"

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
    assert result.worktree_path == expected_path


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


async def test_ac4_create_output_carries_path_and_branch(repo: Path) -> None:
    """AC4: create returns a WorktreeCreateOutput with path/branch."""
    node = WorktreeNode()
    result = await node.create(run_id="run-4", repo_root=repo, base="main")

    dump = result.model_dump()
    assert dump["worktree_branch"] == "harness/run-4"
    assert dump["worktree_path"] == repo / ".worktrees" / "harness" / "run-4"


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
# Relative, prune-safe pointers (CAL-935)
#
# The worktree `.git` file and the admin `gitdir` pointer must be written in
# RELATIVE form so they resolve identically across the host<->container mount
# boundary (/Users/... vs /workspace) — eliminating the manual gitdir-pointer
# flip. Relative pointers are also prune-safe: an absolute pointer that does not
# resolve in the current namespace makes `git worktree list` mark the worktree
# `prunable`, and a concurrent prune then deletes its admin dir (CAL-866).
# Requires git >= 2.48 (worktree.useRelativePaths); skipped otherwise.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _SUPPORTS_RELATIVE_WORKTREES,
    reason="git < 2.48 has no worktree.useRelativePaths; the image mandates >= 2.48",
)
async def test_create_writes_relative_prune_safe_pointers(repo: Path) -> None:
    """create() writes relative worktree pointers, and the worktree is not prunable."""
    node = WorktreeNode()
    await node.create(run_id="run-rel", repo_root=repo, base="main")

    wt = repo / ".worktrees" / "harness" / "run-rel"

    # 1. The worktree's `.git` pointer is relative (no leading '/').
    dotgit = (wt / ".git").read_text().strip()
    assert dotgit.startswith("gitdir: ")
    wt_target = dotgit[len("gitdir: ") :]
    assert not wt_target.startswith("/"), f"worktree .git is absolute: {wt_target!r}"

    # 2. The admin gitdir pointer (repo/.git/worktrees/<id>/gitdir) is relative.
    admin_gitdir = (repo / ".git" / "worktrees" / "run-rel" / "gitdir").read_text().strip()
    assert not admin_gitdir.startswith("/"), f"admin gitdir is absolute: {admin_gitdir!r}"

    # 3. git does not consider the worktree prunable (the CAL-866 data-loss trigger).
    listing = _git(repo, "worktree", "list", "--porcelain").stdout
    assert "prunable" not in listing, f"worktree marked prunable:\n{listing}"


# ---------------------------------------------------------------------------
# branch_prefix parameter
# ---------------------------------------------------------------------------


async def test_create_branch_prefix_default(repo: Path) -> None:
    """When branch_prefix is omitted, branch name starts with 'harness/'."""
    node = WorktreeNode()
    result = await node.create(run_id="run-x", repo_root=repo, base="main")
    assert result.worktree_branch == "harness/run-x"


async def test_create_custom_branch_prefix(repo: Path) -> None:
    """branch_prefix overrides the 'harness' prefix in the branch name."""
    node = WorktreeNode()
    result = await node.create(run_id="run-y", repo_root=repo, base="main", branch_prefix="slate")
    assert result.worktree_branch == "slate/run-y"
    assert _branch_exists(repo, "slate/run-y")
    assert not _branch_exists(repo, "harness/run-y")


# ---------------------------------------------------------------------------
# start_point parameter — resume continues the worktree from a preserved branch
# (CAL-739). The recorded base (the merge target) is decoupled from the git
# commit the worktree's branch starts at.
# ---------------------------------------------------------------------------


async def test_start_point_bases_the_branch_off_a_different_commit(repo: Path) -> None:
    """With ``start_point``, the new branch starts at that commit, not at ``base``.

    Simulates resuming a reclaimed run: a preserved WIP branch carries a commit
    that ``main`` does not, and the new run's worktree must continue from it.
    """
    # A "WIP" branch off main with one extra commit that main lacks.
    _git(repo, "checkout", "-b", "harness/wip")
    (repo / "wip.txt").write_text("work in progress\n")
    _git(repo, "add", "wip.txt")
    _git(repo, "commit", "-m", "wip checkpoint")
    wip_sha = _git(repo, "rev-parse", "harness/wip").stdout.strip()
    main_sha = _git(repo, "rev-parse", "main").stdout.strip()
    assert wip_sha != main_sha
    _git(repo, "checkout", "main")

    node = WorktreeNode()
    result = await node.create(
        run_id="run-resume", repo_root=repo, base="main", start_point="harness/wip"
    )

    wt = repo / ".worktrees" / "harness" / "run-resume"
    wt_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=wt,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    # The worktree continues from the WIP tip, not from base.
    assert wt_sha == wip_sha
    assert wt_sha != main_sha
    # The new run still gets its own canonical branch name.
    assert result.worktree_branch == "harness/run-resume"
    # The WIP file is present in the resumed worktree.
    assert (wt / "wip.txt").exists()


async def test_start_point_none_falls_back_to_base(repo: Path) -> None:
    """``start_point=None`` is identical to the default — the worktree starts at base."""
    base_sha = _git(repo, "rev-parse", "main").stdout.strip()
    node = WorktreeNode()
    await node.create(run_id="run-clean", repo_root=repo, base="main", start_point=None)

    wt = repo / ".worktrees" / "harness" / "run-clean"
    wt_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=wt,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert wt_sha == base_sha


def test_branch_for_default_sources_identity_prefix() -> None:
    """The lifecycle helper's default prefix is the shared identity.BRANCH_PREFIX (CAL-719).

    The configurable-prefix contract is preserved; only the *default* now sources
    the single literal home rather than re-spelling ``"harness"``.
    """
    from harness import identity
    from harness.worktree import _branch_for

    assert _branch_for("run-z") == f"{identity.BRANCH_PREFIX}/run-z"
