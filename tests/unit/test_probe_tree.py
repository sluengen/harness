"""#363 — the throwaway probe tree, and the run worktree's identity check.

Two mechanics, driven against **real git** because both claims are about git's
behaviour and a stub could only restate them.

**The probe tree** is a `git worktree add --detach` at the reviewed SHA, not a
copy. Three properties fall out of that choice rather than out of configuration:
it is provably at the SHA under review, the reviewed worktree is untouched by
construction, and it starts clean — which matters, because a polluted run
worktree is the known cause of the review hang #359 exists to refuse.

**The identity check** is the defence that becomes load-bearing the moment the
reviewer can cause execution. `close` already refuses a dirty worktree, so the
failure mode of a misbehaving prober was always a wedged run rather than a
laundered merge — but discovering it at `close` means discovering it at the end
of a run. This surfaces it where it happened.

Be honest about what it is: it detects **what git can see** — a tracked edit, a
deletion, an untracked addition, HEAD moving — and not a write inside a
gitignored path. It is a detector at the boundary, not the boundary.

The fixtures deliberately include the **linked-worktree** shape, where `.git` is
a *file* holding a gitdir pointer rather than a directory. Every `git init`
fixture makes it a directory, so the production shape a harness run actually has
is the one a naive fixture never exercises (#359's most expensive lesson).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.probe_tree import (
    ProbeTreeError,
    create_probe_tree,
    snapshot_tree,
    teardown_probe_tree,
)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real repository with one commit, and identity configured."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "pkg.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "one")
    return root


@pytest.fixture
def run_worktree(repo: Path) -> Path:
    """The production shape: a linked worktree whose ``.git`` is a **file**."""
    path = repo / ".worktrees" / "harness" / "01RUN"
    path.parent.mkdir(parents=True)
    _git(repo, "worktree", "add", "-q", "-b", "harness/01RUN", str(path))
    assert (path / ".git").is_file(), "fixture must reproduce the linked-worktree shape"
    return path


def test_the_probe_tree_is_created_detached_at_the_reviewed_sha(repo: Path) -> None:
    sha = _git(repo, "rev-parse", "HEAD")

    probe = create_probe_tree(repo, "01RUN", sha)

    assert probe.is_dir()
    assert _git(probe, "rev-parse", "HEAD") == sha
    # Detached: no branch to collide with one already checked out elsewhere.
    # `symbolic-ref` exits non-zero exactly when HEAD is not a symbolic ref.
    detached = subprocess.run(
        ["git", "-C", str(probe), "symbolic-ref", "--quiet", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert detached.returncode != 0, detached.stdout
    assert (probe / "pkg.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_the_probe_tree_starts_clean(repo: Path) -> None:
    """The property #359 exists to protect, obtained by construction."""
    probe = create_probe_tree(repo, "01RUN", _git(repo, "rev-parse", "HEAD"))

    assert _git(probe, "status", "--porcelain", "--untracked-files=all") == ""


def test_a_leftover_probe_tree_is_reclaimed_rather_than_refused(repo: Path) -> None:
    """A previous review's scratch tree must not wedge the next one."""
    sha = _git(repo, "rev-parse", "HEAD")
    first = create_probe_tree(repo, "01RUN", sha)
    (first / "leftover.txt").write_text("stale", encoding="utf-8")

    second = create_probe_tree(repo, "01RUN", sha)

    assert second == first
    assert not (second / "leftover.txt").exists()


def test_an_unknown_sha_raises_and_leaves_no_directory(repo: Path) -> None:
    with pytest.raises(ProbeTreeError):
        create_probe_tree(repo, "01RUN", "0" * 40)

    assert not (repo / ".worktrees" / "harness" / "01RUN-probe").exists()


def test_teardown_removes_the_directory_and_the_registration(repo: Path) -> None:
    probe = create_probe_tree(repo, "01RUN", _git(repo, "rev-parse", "HEAD"))

    teardown_probe_tree(repo, probe)

    assert not probe.exists()
    assert "-probe" not in _git(repo, "worktree", "list")


def test_teardown_of_an_absent_tree_does_not_raise(repo: Path) -> None:
    """Called from a ``finally`` on every path, including ones that never got a tree."""
    teardown_probe_tree(repo, repo / ".worktrees" / "harness" / "never-made")


# ---------------------------------------------------------------------------
# The identity check.
# ---------------------------------------------------------------------------


def test_an_unchanged_worktree_snapshots_identically(run_worktree: Path) -> None:
    assert snapshot_tree(run_worktree) == snapshot_tree(run_worktree)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda w: (w / "pkg.py").write_text("VALUE = 2\n", encoding="utf-8"),
        lambda w: (w / "scratch.txt").write_text("written by the engine\n", encoding="utf-8"),
        lambda w: (w / "pkg.py").unlink(),
    ],
    ids=["tracked-edit", "untracked-addition", "deletion"],
)
def test_every_git_visible_write_moves_the_snapshot(run_worktree: Path, mutate) -> None:  # type: ignore[no-untyped-def]
    """The realistic accident: an engine or an observable writing into the tree."""
    before = snapshot_tree(run_worktree)

    mutate(run_worktree)

    assert snapshot_tree(run_worktree) != before


def test_a_moving_head_moves_the_snapshot(run_worktree: Path) -> None:
    """The porcelain alone cannot see this: a clean commit leaves it empty."""
    before = snapshot_tree(run_worktree)
    (run_worktree / "pkg.py").write_text("VALUE = 3\n", encoding="utf-8")
    _git(run_worktree, "add", "-A")
    _git(run_worktree, "commit", "-qm", "two")

    assert _git(run_worktree, "status", "--porcelain") == ""
    assert snapshot_tree(run_worktree) != before


def test_a_gitignored_write_is_the_stated_blind_spot(run_worktree: Path) -> None:
    """Recorded, not hidden. This is why `close`'s conjuncts stay the enforcement.

    A guard whose limits are undocumented gets cited for a property it does not
    have — the #291 defect class. The check is a detector at the boundary; the
    boundary is `close` refusing a dirty worktree and a pass bound to HEAD.
    """
    (run_worktree / ".gitignore").write_text("scratch/\n", encoding="utf-8")
    _git(run_worktree, "add", "-A")
    _git(run_worktree, "commit", "-qm", "ignore")
    before = snapshot_tree(run_worktree)

    (run_worktree / "scratch").mkdir()
    (run_worktree / "scratch" / "x").write_text("invisible", encoding="utf-8")

    assert snapshot_tree(run_worktree) == before


def test_a_path_git_cannot_read_snapshots_as_unknown(tmp_path: Path) -> None:
    """``None``, not a digest — so the caller skips the comparison rather than
    inventing a mismatch out of a failed probe. Fail-open, like every other
    measurement `review` makes about a tree it did not create."""
    assert snapshot_tree(tmp_path / "not-a-repo") is None
