"""Unit tests for the shared worktree+branch teardown primitive (CAL-767).

``teardown_worktree`` is the single reclaim primitive used by ``start`` rollback,
``close`` self-cleanup, and ``worktrees cleanup``. Its contract:

* remove a *registered* worktree directory and its local branch;
* delete the branch on ``origin`` when ``delete_remote`` is set (a checkpoint
  push may have created it);
* fall back to ``rmtree`` for an *orphaned* directory whose worktree
  registration is already gone — the cruft ``git worktree remove`` cannot touch;
* be **best-effort**: never raise, so a teardown failure never masks or undoes
  the operation it follows (the merge in ``close``, the rollback in ``start``).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import harness._git as gitmod
from harness._git import teardown_worktree


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


def _init_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-b", "dev")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "README.md").write_text("hi\n")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "init")
    return root


def _branches(root: Path) -> set[str]:
    out = _git(root, "branch", "--format=%(refname:short)").stdout
    return set(out.split())


def _make_worktree(root: Path, run_id: str) -> tuple[Path, str]:
    path = root / ".worktrees" / "harness" / run_id
    branch = f"harness/{run_id}"
    _git(root, "worktree", "add", "-b", branch, str(path), "dev")
    return path, branch


def test_removes_registered_worktree_and_local_branch(tmp_path: Path) -> None:
    root = _init_repo(tmp_path / "repo")
    path, branch = _make_worktree(root, "RUN1")
    assert path.exists()
    assert branch in _branches(root)

    teardown_worktree(root, worktree_path=path, branch=branch)

    assert not path.exists()
    assert branch not in _branches(root)


def test_orphaned_dir_removed_via_rmtree_fallback(tmp_path: Path) -> None:
    """A directory that is NOT a registered worktree (its admin entry is gone)
    is still removed — ``git worktree remove`` errors on it, so teardown falls
    back to ``rmtree``. This is the 3 GB-of-cruft case the manual sweep hit."""
    root = _init_repo(tmp_path / "repo")
    orphan = root / ".worktrees" / "harness" / "ORPHAN"
    orphan.mkdir(parents=True)
    (orphan / "leftover.txt").write_text("cruft\n")
    assert orphan.exists()

    teardown_worktree(root, worktree_path=orphan, branch=None)

    assert not orphan.exists()


def test_refuses_to_remove_the_main_checkout(tmp_path: Path) -> None:
    """The rmtree fallback must NEVER destroy the repo. A ``worktree_path`` that
    is the main checkout itself (a misconfig, and what the close unit tests use)
    skips directory removal entirely — only paths under .worktrees/harness/ are
    removable. The local branch op still runs (harmless)."""
    root = _init_repo(tmp_path / "repo")
    (root / "README.md").write_text("hi\n")  # ensure content present

    teardown_worktree(root, worktree_path=root, branch=None)

    assert root.exists()
    assert (root / "README.md").exists()
    # A path outside .worktrees/ but not the root is likewise left untouched.
    outside = tmp_path / "sibling"
    outside.mkdir()
    teardown_worktree(root, worktree_path=outside, branch=None)
    assert outside.exists()


def test_best_effort_never_raises(tmp_path: Path) -> None:
    """Nonexistent path + branch + a remote-delete with no remote configured —
    every git call fails, and teardown must still return without raising."""
    root = _init_repo(tmp_path / "repo")
    teardown_worktree(
        root,
        worktree_path=root / ".worktrees" / "harness" / "NOPE",
        branch="harness/NOPE",
        delete_remote=True,
    )


@pytest.mark.parametrize("hostile", ["--all", "-D", "--force", "-"])
def test_refuses_flag_like_branch_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hostile: str
) -> None:
    """A branch name parsed from an untrusted tracker comment is argv-safe but a
    leading ``-`` could be read by git as an *option* rather than a branch (e.g.
    ``git branch -D --all``). teardown refuses such a name: no ``branch -D`` and
    no ``push --delete`` git command may carry it (go-public security review)."""
    root = _init_repo(tmp_path / "repo")
    calls: list[tuple[str, ...]] = []
    real = gitmod.run_git

    def spy(repo_root: Path, *args: str, **kwargs: object) -> object:
        calls.append(args)
        return real(repo_root, *args, **kwargs)

    monkeypatch.setattr(gitmod, "run_git", spy)

    # Best-effort contract holds — a hostile name never raises.
    teardown_worktree(
        root,
        worktree_path=root / ".worktrees" / "harness" / "X",
        branch=hostile,
        delete_remote=True,
    )

    assert not any(a[:2] == ("branch", "-D") for a in calls), (
        f"a flag-like branch name {hostile!r} reached `git branch -D`"
    )
    assert not any("--delete" in a for a in calls), (
        f"a flag-like branch name {hostile!r} reached `git push ... --delete`"
    )


def test_deletes_remote_branch_when_requested(tmp_path: Path) -> None:
    root = _init_repo(tmp_path / "repo")
    bare = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", str(bare)], check=True, capture_output=True
    )
    _git(root, "remote", "add", "origin", str(bare))
    path, branch = _make_worktree(root, "RUN3")
    _git(root, "push", "origin", branch)
    assert branch in _git(root, "ls-remote", "--heads", "origin", branch).stdout

    teardown_worktree(root, worktree_path=path, branch=branch, delete_remote=True)

    assert branch not in _git(root, "ls-remote", "--heads", "origin", branch).stdout
    assert not path.exists()
    assert branch not in _branches(root)
