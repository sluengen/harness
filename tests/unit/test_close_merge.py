"""Tests for ``harness.close_merge`` — the throwaway-worktree merge mechanics (CAL-1154).

``close`` used to merge the run branch into the base branch **inside the main
checkout** (``git checkout <base>`` → fetch → ff → ``merge --no-ff`` → push). The
main checkout is shared, mutable state no gate covers: a conflict could strand it,
and two concurrent closes merging in the same tree was undefined behaviour.

:mod:`harness.close_merge` moves the integrate-and-merge into a **detached
throwaway worktree** based on ``origin/<base>`` (mirroring :mod:`harness.promotion`),
so a close never touches the main checkout at all. These tests drive the **real**
mechanics against a real bare ``origin``:

* a clean merge lands on ``origin/<base>`` and the main checkout is byte-identical
  before and after (AC-1, AC-5);
* a real conflict is reported with the same message as before and the throwaway
  worktree is removed wholesale — no ``merge --abort`` on any shared tree, and the
  main checkout is again byte-identical (AC-2);
* two concurrent closes cannot corrupt a shared tree — the loser's push is
  rejected non-fast-forward and it fails cleanly and retryably (AC-4).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.close_merge import CloseMergeError, merge_run_branch

# ---------------------------------------------------------------------------
# git / repo helpers (mirrors test_close_integrate_base.py)
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


def _configure(repo: Path, name: str, email: str) -> None:
    _git(repo, "config", "user.email", email)
    _git(repo, "config", "user.name", name)


def _setup_origin_and_main(tmp_path: Path) -> tuple[Path, Path]:
    """A bare ``origin`` with a single ``dev`` commit and a ``main`` clone of it."""
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "dev", str(origin)],
        check=True, capture_output=True, text=True,
    )
    main = tmp_path / "main"
    subprocess.run(
        ["git", "clone", str(origin), str(main)],
        check=True, capture_output=True, text=True,
    )
    _configure(main, "Main", "main@example.com")
    (main / ".gitignore").write_text(".harness/\n.worktrees/\n")
    (main / "README.md").write_text("hello\n")
    _git(main, "add", ".gitignore", "README.md")
    _git(main, "commit", "-m", "initial")
    _git(main, "push", "origin", "dev")
    return origin, main


def _add_run_worktree(
    main: Path, run_id: str, *, filename: str, content: str
) -> tuple[Path, str]:
    """Create a run worktree off ``dev`` with one committed change; return it."""
    path = main / ".worktrees" / "harness" / run_id
    branch = f"harness/{run_id}"
    _git(main, "worktree", "add", "-b", branch, str(path), "dev")
    (path / filename).write_text(content)
    _git(path, "add", filename)
    _git(path, "commit", "-m", f"work {run_id}")
    return path, branch


def _advance_origin(
    tmp_path: Path, origin: Path, *, filename: str, content: str, name: str = "other"
) -> str:
    """Land a commit on ``origin/dev`` from a separate clone; return its SHA."""
    other = tmp_path / name
    subprocess.run(
        ["git", "clone", str(origin), str(other)],
        check=True, capture_output=True, text=True,
    )
    _configure(other, "Other", "other@example.com")
    (other / filename).write_text(content)
    _git(other, "add", filename)
    _git(other, "commit", "-m", "concurrent landing")
    _git(other, "push", "origin", "dev")
    return _git(other, "rev-parse", "HEAD").stdout.strip()


def _head(repo: Path, ref: str = "HEAD") -> str:
    return _git(repo, "rev-parse", ref).stdout.strip()


def _merge_in_progress(repo: Path) -> bool:
    return subprocess.run(
        ["git", "rev-parse", "--verify", "-q", "MERGE_HEAD"],
        cwd=repo, check=False, capture_output=True, text=True,
    ).returncode == 0


def _checkout_state(repo: Path) -> tuple[str, str]:
    """The full observable state of a working tree: (HEAD sha, porcelain status).

    Together these are what "byte-identical before and after" means for a
    checkout — the ref it points at and any dirt in the working copy.
    """
    return _head(repo), _git(repo, "status", "--porcelain").stdout


RUN_ID = "01JRUNCLOSEMERGE00000000001"


# ---------------------------------------------------------------------------
# Clean merge — lands on origin, main checkout untouched (AC-1, AC-5)
# ---------------------------------------------------------------------------


def test_clean_merge_lands_on_origin_and_leaves_main_untouched(tmp_path: Path) -> None:
    """A clean merge pushes to ``origin/<base>``; the main checkout is byte-identical."""
    origin, main = _setup_origin_and_main(tmp_path)
    _path, branch = _add_run_worktree(main, RUN_ID, filename="feature.txt", content="run\n")
    reviewed_sha = _head(main, branch)
    advanced = _advance_origin(tmp_path, origin, filename="other.txt", content="other\n")

    before = _checkout_state(main)
    merge_run_branch(
        repo_root=main, run_id=RUN_ID, base_branch="dev", worktree_branch=branch
    )
    after = _checkout_state(main)

    # AC-1/AC-5: the main checkout's working tree was not mutated at all.
    assert before == after
    assert not _merge_in_progress(main)

    # origin/dev now carries both the concurrent change and the run's work, and
    # the reviewed SHA is the merge's second parent (only reviewed content rode in).
    verify = tmp_path / "verify"
    subprocess.run(
        ["git", "clone", str(origin), str(verify)],
        check=True, capture_output=True, text=True,
    )
    assert (verify / "other.txt").exists()
    assert (verify / "feature.txt").exists()
    assert _head(verify, "HEAD^2") == reviewed_sha
    assert _head(verify, "HEAD^1") == advanced


def test_clean_merge_updates_origin_tracking_ref(tmp_path: Path) -> None:
    """The push advances local ``refs/remotes/origin/<base>`` — the AC-3 mechanism.

    Option 1 hinges on this: close's own push updates the tracking ref on the same
    machine with no fetch, so the next ``start`` / ``cleanup`` reader that bases
    off ``origin/<base>`` sees the merged work immediately.
    """
    origin, main = _setup_origin_and_main(tmp_path)
    _path, branch = _add_run_worktree(main, RUN_ID, filename="feature.txt", content="run\n")

    tracking_before = _head(main, "refs/remotes/origin/dev")
    merge_run_branch(
        repo_root=main, run_id=RUN_ID, base_branch="dev", worktree_branch=branch
    )
    tracking_after = _head(main, "refs/remotes/origin/dev")

    assert tracking_after != tracking_before
    # It points at the merge commit that carries the run's work as second parent.
    assert _head(main, "refs/remotes/origin/dev^2") == _head(main, branch)


def test_clean_merge_removes_the_throwaway_worktree(tmp_path: Path) -> None:
    """No throwaway worktree survives a successful merge (it is created and removed)."""
    origin, main = _setup_origin_and_main(tmp_path)
    _path, branch = _add_run_worktree(main, RUN_ID, filename="feature.txt", content="run\n")

    merge_run_branch(
        repo_root=main, run_id=RUN_ID, base_branch="dev", worktree_branch=branch
    )

    # Only the run's own worktree remains under .worktrees/harness/ — no <id>-close.
    survivors = sorted(p.name for p in (main / ".worktrees" / "harness").iterdir())
    assert survivors == [RUN_ID]
    # git agrees no stray worktree is registered.
    listing = _git(main, "worktree", "list", "--porcelain").stdout
    assert "-close" not in listing


# ---------------------------------------------------------------------------
# Conflict — same message, worktree removed wholesale, main untouched (AC-2)
# ---------------------------------------------------------------------------


def test_conflict_refuses_cleanly_and_removes_the_worktree(tmp_path: Path) -> None:
    """A real conflict → clear message, throwaway removed, main checkout byte-identical."""
    origin, main = _setup_origin_and_main(tmp_path)
    _path, branch = _add_run_worktree(main, RUN_ID, filename="README.md", content="run line\n")
    _advance_origin(tmp_path, origin, filename="README.md", content="other line\n")

    before = _checkout_state(main)
    with pytest.raises(CloseMergeError) as excinfo:
        merge_run_branch(
            repo_root=main, run_id=RUN_ID, base_branch="dev", worktree_branch=branch
        )
    after = _checkout_state(main)

    err = excinfo.value
    assert err.conflict is True
    # The same clear message as before — not a raw git conflict dump.
    assert "conflicts with changes that landed on origin/dev" in str(err)
    assert "CONFLICT (content)" not in str(err)
    assert "<<<<<<<" not in str(err)

    # AC-2: the main checkout was never touched, and no throwaway worktree survives.
    assert before == after
    assert not _merge_in_progress(main)
    survivors = sorted(p.name for p in (main / ".worktrees" / "harness").iterdir())
    assert survivors == [RUN_ID]


def test_conflict_message_does_not_prescribe_a_rebase(tmp_path: Path) -> None:
    """#266 AC-1: the conflict message names a remedy that rewrites no history.

    ``close`` fetches ``origin/<base>`` and merges the run branch into a detached
    throwaway worktree, so the run branch never needs rewriting. The old message
    nevertheless told the operator to *rebase the run branch on the updated base,
    re-review, and close again* — and a rebase rewrites every SHA on the branch,
    invalidating the HEAD-bound passing review for hunks it never touched.

    The property pinned here is the **absence of the word** ``rebase``, not the
    absence of one phrasing: any reworded prescription would slip past a phrase
    regex, and forcing the word out forces the author to name the non-rewriting
    route instead. The re-review itself is *not* retired — resolving the conflict
    moves HEAD, and the gate binds a pass to HEAD.
    """
    origin, main = _setup_origin_and_main(tmp_path)
    _path, branch = _add_run_worktree(main, RUN_ID, filename="README.md", content="run line\n")
    _advance_origin(tmp_path, origin, filename="README.md", content="other line\n")

    with pytest.raises(CloseMergeError) as excinfo:
        merge_run_branch(
            repo_root=main, run_id=RUN_ID, base_branch="dev", worktree_branch=branch
        )

    message = str(excinfo.value)
    # The retired prescription, in any wording.
    assert "rebase" not in message.lower()
    # Positively: it still diagnoses the conflict and names the remedy's parts.
    assert branch in message
    assert "origin/dev" in message
    assert "re-review" in message
    assert "close again" in message


# ---------------------------------------------------------------------------
# A non-conflicting base advance rewrites nothing on the run branch (#266 AC-2)
# ---------------------------------------------------------------------------


def test_nonconflicting_base_advance_leaves_the_run_worktree_untouched(
    tmp_path: Path,
) -> None:
    """#266 AC-2: base movement alone needs no rebase — the run branch is untouched.

    This is the mechanics-level half of the property the docs now assert. The
    verb-level half lives in ``test_close_integrate_base.py`` because ``close``
    tears the run worktree down on success, so HEAD-unchanged can only be
    asserted here, where the worktree survives the call.
    """
    origin, main = _setup_origin_and_main(tmp_path)
    path, branch = _add_run_worktree(main, RUN_ID, filename="feature.txt", content="run\n")
    reviewed_sha = _head(main, branch)

    _advance_origin(tmp_path, origin, filename="other.txt", content="other\n")

    before = _checkout_state(path)
    merge_run_branch(
        repo_root=main, run_id=RUN_ID, base_branch="dev", worktree_branch=branch
    )
    after = _checkout_state(path)

    # The run worktree's HEAD, its working tree, and the branch tip are identical
    # before and after — nothing was rewritten, so the passing review still covers
    # exactly what merged.
    assert before == after
    assert _head(main, branch) == reviewed_sha

    # And the merge still landed, carrying the reviewed commit as second parent.
    verify = tmp_path / "verify"
    subprocess.run(
        ["git", "clone", str(origin), str(verify)],
        check=True, capture_output=True, text=True,
    )
    assert _head(verify, "HEAD^2") == reviewed_sha
    assert (verify / "feature.txt").exists()
    assert (verify / "other.txt").exists()


# ---------------------------------------------------------------------------
# Concurrency — the loser fails cleanly and retryably (AC-4)
# ---------------------------------------------------------------------------


def test_concurrent_close_loser_is_rejected_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A base that advances between fetch and push → the loser is rejected cleanly.

    The real race: close A and close B both fetch tip T0; A pushes (origin → T1);
    B, based on T0, pushes ``HEAD:dev`` non-fast-forward and is rejected. We make
    it deterministic by landing a concurrent commit on ``origin`` *after* this
    close fetches but *before* it pushes. The loser must fail cleanly (no
    shared-tree corruption, throwaway removed) and be retryable — a second
    merge_run_branch re-fetches the winner's tip and lands.
    """
    import harness.close_merge as close_merge

    origin, main = _setup_origin_and_main(tmp_path)
    _path, branch = _add_run_worktree(main, RUN_ID, filename="feature.txt", content="run\n")

    real_run_git = close_merge.run_git
    landed = {"done": False}

    def _land_between_fetch_and_push(cwd: Path, *args: str, timeout: float | None = None):  # type: ignore[no-untyped-def]
        result = real_run_git(cwd, *args, timeout=timeout)
        # Right after this close fetches origin/dev, a concurrent session lands a
        # non-conflicting commit — so this close's push will be non-fast-forward.
        if args[:1] == ("fetch",) and not landed["done"]:
            landed["done"] = True
            _advance_origin(tmp_path, origin, filename="winner.txt", content="won\n")
        return result

    monkeypatch.setattr(close_merge, "run_git", _land_between_fetch_and_push)

    before = _checkout_state(main)
    with pytest.raises(CloseMergeError) as excinfo:
        merge_run_branch(
            repo_root=main, run_id=RUN_ID, base_branch="dev", worktree_branch=branch
        )
    after = _checkout_state(main)

    # AC-4: fails cleanly — the push was rejected, the main checkout untouched, and
    # no throwaway worktree left behind.
    assert excinfo.value.reason == "push_rejected"
    assert before == after
    assert not _merge_in_progress(main)
    survivors = sorted(p.name for p in (main / ".worktrees" / "harness").iterdir())
    assert survivors == [RUN_ID]

    # Retryable: with the interposer disarmed, a second attempt re-fetches the
    # winner's tip and lands both changes.
    monkeypatch.setattr(close_merge, "run_git", real_run_git)
    merge_run_branch(
        repo_root=main, run_id=RUN_ID, base_branch="dev", worktree_branch=branch
    )
    verify = tmp_path / "verify"
    subprocess.run(
        ["git", "clone", str(origin), str(verify)],
        check=True, capture_output=True, text=True,
    )
    assert (verify / "feature.txt").exists()
    assert (verify / "winner.txt").exists()
