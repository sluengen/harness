"""Unit tests for the shared worktree+branch teardown primitive (CAL-767).

``teardown_worktree`` is the single reclaim primitive used by ``start`` rollback,
``close`` self-cleanup, and ``worktrees cleanup``. Its contract:

* remove a *registered* worktree directory and its local branch;
* delete the branch on ``origin`` when ``delete_remote`` is set (a checkpoint
  push may have created it);
* fall back to ``rmtree`` for an *orphaned* directory whose worktree
  registration is already gone — the cruft ``git worktree remove`` cannot touch;
* leave a **locked** worktree entirely alone, directory *and* registration, and
  report the refusal rather than escalating to ``remove -f -f`` (#372) — and
  fail closed the same way whenever the registry cannot be read at all;
* clear the admin entry for the worktree it removed, **and no other** (#371);
* be **best-effort**: never raise, so a teardown failure never masks or undoes
  the operation it follows (the merge in ``close``, the rollback in ``start``).

The blast-radius half of that contract is what #371 added, and it is a property
about worktrees teardown was *not* asked to touch — so the cases below assert on
a bystander, not on the target. The bystander that matters is one whose directory
is **not present in the namespace the teardown runs in**: that is the container,
where the repo is mounted at ``/workspace`` and every worktree registered at a
host path simply does not exist. ``test_a_worktree_missing_from_this_namespace_
survives_a_teardown`` reproduces that condition host-side by renaming the
directory away, so the mechanism is measured on every machine rather than only
where a Docker daemon is available (``tests/integration/test_docker_worktree_
prune.py`` runs the real thing).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import harness._git as gitmod
from harness._git import TeardownOutcome, teardown_worktree


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


def _lock(root: Path, path: Path, reason: str | None = None) -> None:
    """Lock a worktree the way an operator does — the state git refuses to
    ``remove --force`` (exit 128), whatever the directory looks like."""
    extra = ["--reason", reason] if reason is not None else []
    _git(root, "worktree", "lock", *extra, str(path))


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


def _entries(root: Path) -> set[str]:
    """The admin entries git currently has registered — one directory per
    worktree under ``<repo>/.git/worktrees/``. This is the registry #371 is
    about: teardown deleting the *directory* was never in question, deleting
    other worktrees' **registrations** was."""
    registry = root / ".git" / "worktrees"
    return {p.name for p in registry.iterdir()} if registry.is_dir() else set()


def test_removes_registered_worktree_and_local_branch(tmp_path: Path) -> None:
    root = _init_repo(tmp_path / "repo")
    path, branch = _make_worktree(root, "RUN1")
    assert path.exists()
    assert branch in _branches(root)

    outcome = teardown_worktree(root, worktree_path=path, branch=branch)

    assert not path.exists()
    assert branch not in _branches(root)
    assert outcome is TeardownOutcome.RECLAIMED


def test_a_locked_worktree_is_left_entirely_alone(tmp_path: Path) -> None:
    """#372. A lock is the operator's "hands off". ``git worktree remove
    --force`` refuses a locked worktree with exit 128 — the *same* exit an
    orphaned directory produces — so teardown used to read the refusal as
    "orphan", ``rmtree`` the live directory and leave the registration behind:
    a registration with nothing under it, which then refuses a later
    ``git worktree add`` at that path. Teardown now touches neither half."""
    root = _init_repo(tmp_path / "repo")
    path, branch = _make_worktree(root, "RUN1")
    (path / "wip.txt").write_text("unmerged work\n")
    _lock(root, path)

    outcome = teardown_worktree(root, worktree_path=path, branch=branch)

    assert path.exists(), "teardown deleted a locked worktree's directory"
    assert (path / "wip.txt").read_text() == "unmerged work\n", (
        "teardown destroyed the contents of a locked worktree"
    )
    assert _entries(root) == {"RUN1"}, "the locked worktree's registration is gone"
    assert outcome is TeardownOutcome.LOCKED


def test_a_lock_reason_is_honoured_the_same_way(tmp_path: Path) -> None:
    """A lock taken with ``--reason`` is the same refusal, but the registry
    spells it differently: ``locked <reason>`` on one line rather than a bare
    ``locked``. A parser keyed on exact equality reads the stanza as unlocked
    and destroys the directory — so the reason form gets its own case rather
    than a shared parametrize, whose empty set would report ``1 skipped``."""
    root = _init_repo(tmp_path / "repo")
    path, branch = _make_worktree(root, "RUN1")
    (path / "wip.txt").write_text("unmerged work\n")
    _lock(root, path, reason="operator is debugging this run")

    outcome = teardown_worktree(root, worktree_path=path, branch=branch)

    assert path.exists(), "teardown deleted a worktree locked with a reason"
    assert (path / "wip.txt").read_text() == "unmerged work\n"
    assert _entries(root) == {"RUN1"}
    assert outcome is TeardownOutcome.LOCKED


def test_a_locked_worktree_whose_directory_is_gone_is_still_honoured(
    tmp_path: Path,
) -> None:
    """The lock, not the directory, is what teardown answers to. git keeps a
    locked registration when the directory disappears and still refuses to
    remove it (exit 128) — so an outcome derived from ``path.exists()`` would
    call this reclaimed while the entry it never cleared still blocks the path.
    """
    root = _init_repo(tmp_path / "repo")
    path, branch = _make_worktree(root, "RUN1")
    _lock(root, path)
    shutil.rmtree(path)

    outcome = teardown_worktree(root, worktree_path=path, branch=branch)

    assert not path.exists(), "the precondition — the directory was already gone"
    assert _entries(root) == {"RUN1"}, "a locked registration was cleared"
    assert outcome is TeardownOutcome.LOCKED


def test_a_locked_worktree_reached_via_a_symlinked_path_is_honoured(
    tmp_path: Path,
) -> None:
    """``git worktree list --porcelain`` prints **realpaths**. A worktree added
    through a symlinked parent — ``/tmp`` on macOS, and any operator whose
    checkout sits behind one — is therefore listed at a path that does not
    string-match the one teardown was handed, so a comparison without
    ``Path.resolve()`` finds no stanza, concludes "unregistered", and deletes a
    locked worktree. Linux CI would ship that; this reproduces it anywhere."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    root = _init_repo(link / "repo")
    path, branch = _make_worktree(root, "RUN1")
    (path / "wip.txt").write_text("unmerged work\n")
    _lock(root, path)
    assert str(path).startswith(str(link)), "the path under test goes via the symlink"

    outcome = teardown_worktree(root, worktree_path=path, branch=branch)

    assert path.exists(), "teardown deleted a locked worktree reached via a symlink"
    assert (path / "wip.txt").read_text() == "unmerged work\n"
    assert _entries(real / "repo") == {"RUN1"}
    assert outcome is TeardownOutcome.LOCKED


def test_the_lock_is_released_and_the_next_teardown_reclaims(tmp_path: Path) -> None:
    """The escape hatch, exercised for real. ``LOCKED`` must not be sticky: once
    the operator runs ``git worktree unlock``, the very next teardown reclaims
    both halves — proven through the consequence the whole ticket is about, a
    ``git worktree add`` at that path being accepted again."""
    root = _init_repo(tmp_path / "repo")
    path, branch = _make_worktree(root, "RUN1")
    _lock(root, path)
    assert teardown_worktree(root, worktree_path=path) is TeardownOutcome.LOCKED

    _git(root, "worktree", "unlock", str(path))
    outcome = teardown_worktree(root, worktree_path=path, branch=branch)

    assert outcome is TeardownOutcome.RECLAIMED
    assert not path.exists()
    assert _entries(root) == set()
    _git(root, "worktree", "add", "-b", "harness/RUN1b", str(path), "dev")
    assert path.exists(), "the reclaimed path is usable again"


def _failing_remove(
    monkeypatch: pytest.MonkeyPatch, *, on_list: object = None
) -> None:
    """Make ``git worktree remove`` fail like a refusal, and optionally break the
    registry probe. Only the failure is injected — every other git call, the
    ``worktree list`` probe included unless ``on_list`` says otherwise, runs for
    real against the repo on disk."""
    real = gitmod.run_git

    def spy(repo_root: Path, *args: str, **kwargs: object) -> object:
        if args[:2] == ("worktree", "remove"):
            return subprocess.CompletedProcess(
                args=["git"], returncode=128, stdout="", stderr="fatal: nope\n"
            )
        if args[:2] == ("worktree", "list") and on_list is not None:
            if isinstance(on_list, BaseException):
                raise on_list
            return on_list
        return real(repo_root, *args, **kwargs)

    monkeypatch.setattr(gitmod, "run_git", spy)


def test_a_registered_worktree_that_fails_removal_is_not_rmtreed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Removal can refuse for reasons that are neither a lock nor an orphan.
    Whatever the reason, a path git **still tracks** is not cruft: the old guard
    read "non-zero exit + directory present" as orphan and destroyed it, leaving
    the registration behind. The discriminator is the registry, not the exit
    code and not ``stderr`` — this stanza carries no ``locked`` line and no
    stderr hint, so only a registry lookup can classify it."""
    root = _init_repo(tmp_path / "repo")
    path, branch = _make_worktree(root, "RUN1")
    (path / "wip.txt").write_text("unmerged work\n")
    _failing_remove(monkeypatch)

    outcome = teardown_worktree(root, worktree_path=path, branch=branch)

    assert path.exists(), "a still-registered worktree was rmtree'd"
    assert (path / "wip.txt").read_text() == "unmerged work\n"
    assert _entries(root) == {"RUN1"}
    assert outcome is TeardownOutcome.UNKNOWN


def test_an_unreadable_registry_does_not_rmtree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fail-closed case. When ``git worktree list`` cannot be read, the
    probe has *no opinion* — and a probe that answered "unregistered" instead
    would turn every unreadable registry into a delete. No opinion means touch
    nothing and say so."""
    root = _init_repo(tmp_path / "repo")
    path, branch = _make_worktree(root, "RUN1")
    (path / "wip.txt").write_text("unmerged work\n")
    _failing_remove(
        monkeypatch,
        on_list=subprocess.CompletedProcess(
            args=["git"], returncode=1, stdout="", stderr="fatal: broken\n"
        ),
    )

    outcome = teardown_worktree(root, worktree_path=path, branch=branch)

    assert path.exists(), "an unreadable registry was read as permission to delete"
    assert (path / "wip.txt").read_text() == "unmerged work\n"
    assert outcome is TeardownOutcome.UNKNOWN


def test_a_registry_that_lists_nothing_does_not_rmtree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The *other* unreadable shape, and the one an exit code cannot catch: git
    exits 0 but prints output carrying no ``worktree`` stanza at all. git always
    lists at least the main checkout, so that is a failed read wearing a success
    exit — and reading it as "nothing is registered here" hands the ``rmtree``
    branch a green light. Its own case, because the returncode test above
    returns before this branch is ever reached."""
    root = _init_repo(tmp_path / "repo")
    path, branch = _make_worktree(root, "RUN1")
    (path / "wip.txt").write_text("unmerged work\n")
    _failing_remove(
        monkeypatch,
        on_list=subprocess.CompletedProcess(
            args=["git"], returncode=0, stdout="", stderr=""
        ),
    )

    outcome = teardown_worktree(root, worktree_path=path, branch=branch)

    assert path.exists(), "an empty registry listing was read as permission to delete"
    assert (path / "wip.txt").read_text() == "unmerged work\n"
    assert _entries(root) == {"RUN1"}
    assert outcome is TeardownOutcome.UNKNOWN


def test_the_registry_probe_raising_does_not_break_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The probe is a new raising surface. It passes a ``timeout``, so it can
    raise :class:`subprocess.TimeoutExpired` — which no suppression on this path
    covered before #372, and which would propagate out of a primitive whose
    whole contract is that it never raises (CAL-767) and therefore never masks
    the merge or rollback it follows."""
    root = _init_repo(tmp_path / "repo")
    path, branch = _make_worktree(root, "RUN1")
    _failing_remove(
        monkeypatch, on_list=subprocess.TimeoutExpired(cmd=["git"], timeout=15)
    )

    outcome = teardown_worktree(root, worktree_path=path, branch=branch)

    assert path.exists()
    assert outcome is TeardownOutcome.UNKNOWN


def test_orphaned_dir_removed_via_rmtree_fallback(tmp_path: Path) -> None:
    """A directory that is NOT a registered worktree (its admin entry is gone)
    is still removed — ``git worktree remove`` errors on it, so teardown falls
    back to ``rmtree``. This is the 3 GB-of-cruft case the manual sweep hit."""
    root = _init_repo(tmp_path / "repo")
    orphan = root / ".worktrees" / "harness" / "ORPHAN"
    orphan.mkdir(parents=True)
    (orphan / "leftover.txt").write_text("cruft\n")
    assert orphan.exists()

    outcome = teardown_worktree(root, worktree_path=orphan, branch=None)

    assert not orphan.exists()
    assert outcome is TeardownOutcome.ORPHAN_REMOVED


def test_refuses_to_remove_the_main_checkout(tmp_path: Path) -> None:
    """The rmtree fallback must NEVER destroy the repo. A ``worktree_path`` that
    is the main checkout itself (a misconfig, and what the close unit tests use)
    skips directory removal entirely — only paths under .worktrees/harness/ are
    removable. The local branch op still runs (harmless)."""
    root = _init_repo(tmp_path / "repo")
    (root / "README.md").write_text("hi\n")  # ensure content present

    outcome = teardown_worktree(root, worktree_path=root, branch=None)

    assert root.exists()
    assert (root / "README.md").exists()
    assert outcome is TeardownOutcome.SKIPPED_AREA
    # A path outside .worktrees/ but not the root is likewise left untouched.
    outside = tmp_path / "sibling"
    outside.mkdir()
    assert (
        teardown_worktree(root, worktree_path=outside, branch=None)
        is TeardownOutcome.SKIPPED_AREA
    )
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


def test_clears_the_admin_entry_for_the_worktree_it_removed(tmp_path: Path) -> None:
    """AC-2. Removing the directory is only half the job: a registration left
    behind is why a later ``git worktree add`` at the same path is refused as
    already registered — which is exactly how ``probe_tree.create`` reclaims a
    leftover from a previous review."""
    root = _init_repo(tmp_path / "repo")
    path, branch = _make_worktree(root, "RUN1")
    assert _entries(root) == {"RUN1"}

    teardown_worktree(root, worktree_path=path, branch=branch)

    assert _entries(root) == set()


def test_clears_a_stale_entry_when_the_directory_is_already_gone(
    tmp_path: Path,
) -> None:
    """AC-2, the case that used to depend on the repo-wide prune. An operator
    (or a dead container) removed the directory, leaving a registration with
    nothing behind it. Asserted through the observable consequence — a fresh
    worktree at the same path must be creatable — rather than only through the
    registry, so the criterion cannot be met by a change that merely looks right.
    """
    root = _init_repo(tmp_path / "repo")
    path, branch = _make_worktree(root, "RUN1")
    shutil.rmtree(path)
    assert _entries(root) == {"RUN1"}, "the stale entry is the precondition"

    outcome = teardown_worktree(root, worktree_path=path, branch=branch)

    assert _entries(root) == set()
    assert outcome is TeardownOutcome.RECLAIMED
    # The consequence: git accepts the path again.
    _git(root, "worktree", "add", "-b", "harness/RUN1b", str(path), "dev")
    assert path.exists()


def test_a_sibling_run_worktree_survives_a_teardown(tmp_path: Path) -> None:
    """The narrow blast-radius claim: tearing down one run must leave another
    run's worktree registered and usable. Both live inside the worktrees area,
    so this is the case a path-scoped removal gets right by construction."""
    root = _init_repo(tmp_path / "repo")
    doomed, doomed_branch = _make_worktree(root, "RUN1")
    survivor, _ = _make_worktree(root, "RUN2")

    teardown_worktree(root, worktree_path=doomed, branch=doomed_branch)

    assert _entries(root) == {"RUN2"}
    assert survivor.exists()
    _git(survivor, "ls-files")  # check=True — a deregistered worktree exits 128


def test_a_worktree_missing_from_this_namespace_survives_a_teardown(
    tmp_path: Path,
) -> None:
    """AC-1's mechanism, reproduced without a container.

    The container's whole effect on this code is that a worktree registered at a
    host path **is not present** in the namespace the verb runs in. Renaming the
    directory away creates that exact condition on any machine: git now
    classifies the entry prunable, and a repo-wide ``git worktree prune`` — what
    teardown used to issue — deletes the registration of a worktree the verb was
    never asked to touch. The directory survives, so nothing looks wrong until
    something reads the tree and git answers ``fatal: not a git repository``
    with exit 128.

    The bystander is deliberately registered with git's **default absolute**
    pointer rather than the harness's relative one: that is what an operator's
    own ``git worktree add`` produces, and it is the shape that was lost.
    """
    root = _init_repo(tmp_path / "repo")
    doomed, doomed_branch = _make_worktree(root, "RUN1")
    bystander = tmp_path / "gate-wt"
    _git(root, "worktree", "add", "--detach", str(bystander), "dev")
    assert _entries(root) == {"RUN1", "gate-wt"}

    # Make the bystander invisible in this namespace, as the mount does.
    hidden = tmp_path / "gate-wt-elsewhere"
    bystander.rename(hidden)

    teardown_worktree(root, worktree_path=doomed, branch=doomed_branch)

    assert "gate-wt" in _entries(root), (
        "teardown deregistered a worktree it was not asked to touch — the one "
        "thing it could not see (#371)"
    )
    hidden.rename(bystander)
    _git(bystander, "ls-files")  # check=True — this is the exit-128 signature


def test_leaves_the_registry_alone_for_a_path_outside_the_worktrees_area(
    tmp_path: Path,
) -> None:
    """The area guard now gates the registry too, not only the directory.

    Directory removal has always skipped a path outside ``.worktrees/harness/``.
    Clearing entries while refusing to remove directories would produce exactly
    the broken half-state this ticket is about — a live directory with no
    registration — so both steps answer to the same guard.
    """
    root = _init_repo(tmp_path / "repo")
    _make_worktree(root, "RUN1")
    outside = tmp_path / "sibling"
    outside.mkdir()

    outcome = teardown_worktree(root, worktree_path=outside, branch=None)

    assert _entries(root) == {"RUN1"}
    assert outside.exists()
    assert outcome is TeardownOutcome.SKIPPED_AREA
