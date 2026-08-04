"""Unit tests for the shared git-tracked-file helpers.

``tracked_files_under`` is the authoritative basis for retirement / hygiene
guards: it must report only files git tracks, never working-tree cruft (an
untracked ``.DS_Store``, stale ``__pycache__`` bytecode left over from a deleted
module). ``tracked_py_sources`` is its Python-source projection, the single home
for "which files are living package/test sources" (#215). These tests pin both
contracts against a throw-away git repo so they do not depend on the harness
repo's own tree — plus an adoption lock proving the tree-walking guards derive
their file set from the helper rather than re-inlining a working-tree walk.

``last_commit_date`` (#280) is the third contract pinned here: the day a path
last actually changed, which is what a doc declaring its own currency must be
measured against. Its commits pin ``GIT_AUTHOR_DATE`` so the assertions read a
known day rather than whenever the suite runs.
"""

from __future__ import annotations

import os
import subprocess
from datetime import date
from pathlib import Path

import pytest

from tests._gitutil import (
    last_commit_date,
    tracked_files_under,
    tracked_py_sources,
)


def _git(repo: Path, *args: str) -> None:
    """Run a git command in ``repo`` with a deterministic identity."""
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=Test", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-q")


def test_lists_tracked_files(tmp_path: Path) -> None:
    """A committed file under the queried path is reported (absolute, resolved)."""
    _init_repo(tmp_path)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text("x = 1\n")
    _git(tmp_path, "add", "pkg/mod.py")
    _git(tmp_path, "commit", "-q", "-m", "add mod")

    result = tracked_files_under("pkg", repo_root=tmp_path)

    assert result == {(pkg / "mod.py").resolve()}


def test_excludes_untracked_files(tmp_path: Path) -> None:
    """An untracked sibling (e.g. OS cruft) is never reported."""
    _init_repo(tmp_path)
    (tmp_path / "tracked.py").write_text("x = 1\n")
    _git(tmp_path, "add", "tracked.py")
    _git(tmp_path, "commit", "-q", "-m", "add tracked")
    (tmp_path / ".DS_Store").write_bytes(b"\x00")  # untracked OS cruft

    result = tracked_files_under(".", repo_root=tmp_path)

    assert (tmp_path / "tracked.py").resolve() in result
    assert (tmp_path / ".DS_Store").resolve() not in result


def test_excludes_untracked_pycache(tmp_path: Path) -> None:
    """Stale ``__pycache__`` bytecode under a tracked package is not reported.

    This is the CODE-3 regression: a guard scanning the working tree fails on a
    leftover ``__pycache__`` for a module that is gone from the committed tree.
    """
    _init_repo(tmp_path)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text("x = 1\n")
    _git(tmp_path, "add", "pkg/mod.py")
    _git(tmp_path, "commit", "-q", "-m", "add mod")
    cache = pkg / "__pycache__"
    cache.mkdir()
    (cache / "mod.cpython-311.pyc").write_bytes(b"\x00")  # untracked bytecode

    result = tracked_files_under("pkg", repo_root=tmp_path)

    assert result == {(pkg / "mod.py").resolve()}


def test_removed_path_returns_empty(tmp_path: Path) -> None:
    """A path with no tracked files (deleted / never-existed module) returns the empty set."""
    _init_repo(tmp_path)
    (tmp_path / "keep.py").write_text("x = 1\n")
    _git(tmp_path, "add", "keep.py")
    _git(tmp_path, "commit", "-q", "-m", "init")

    assert tracked_files_under("intake", repo_root=tmp_path) == set()


def test_default_repo_root_sees_a_tracked_test() -> None:
    """With no explicit ``repo_root``, the helper resolves the harness repo and
    reports its own tracked tests — proving the default root discovery works."""
    tracked = tracked_files_under("tests/unit")

    # A committed sibling guard module — present in the index, so reported.
    expected = Path(__file__).resolve().with_name("test_package_hygiene.py")
    assert expected in tracked


# ---------------------------------------------------------------------------
# #215 — ``tracked_py_sources``: the Python-source projection the tree-walking
# guards enumerate from, and the adoption lock that keeps them on it.


def test_tracked_py_sources_excludes_a_nested_worktree(tmp_path: Path) -> None:
    """A stray git worktree left under the scanned package is not enumerated.

    The #215 defect: two abandoned promotion worktrees nested inside ``harness/``
    carried *old copies* of guarded sources, and each guard's ``rglob`` walk
    happily scanned them — failing seven tests that had no code regression
    behind them. A worktree's contents are absent from the parent repo's index,
    so the tracked-set basis excludes them by construction.
    """
    _init_repo(tmp_path)
    pkg = tmp_path / "harness"
    pkg.mkdir()
    (pkg / "live.py").write_text("x = 1\n")
    _git(tmp_path, "add", "harness/live.py")

    zombie = pkg / ".worktrees" / "harness" / "01ABC" / "harness"
    zombie.mkdir(parents=True)
    (zombie / "stale.py").write_text('s.replace("+00:00", "Z")\n')

    assert tracked_py_sources("harness", repo_root=tmp_path) == [
        (pkg / "live.py").resolve()
    ]


def test_tracked_py_sources_excludes_an_untracked_non_dot_path(
    tmp_path: Path,
) -> None:
    """Exclusion does not depend on the stray path being dot-prefixed.

    This is the property that separates the tracked-set basis from the
    ``startswith(".")`` filter the ticket offered as the alternative: a worktree
    parked at ``harness/tmp-promote/`` has no dot segment, so a name-shaped
    filter would scan it. Being untracked is the real invariant.
    """
    _init_repo(tmp_path)
    pkg = tmp_path / "harness"
    pkg.mkdir()
    (pkg / "live.py").write_text("x = 1\n")
    _git(tmp_path, "add", "harness/live.py")

    stray = pkg / "tmp-promote" / "harness"
    stray.mkdir(parents=True)
    (stray / "stale.py").write_text('s.replace("+00:00", "Z")\n')

    assert tracked_py_sources("harness", repo_root=tmp_path) == [
        (pkg / "live.py").resolve()
    ]


def test_tracked_py_sources_keeps_only_python(tmp_path: Path) -> None:
    """Tracked non-``.py`` siblings are filtered out of the projection."""
    _init_repo(tmp_path)
    pkg = tmp_path / "harness"
    pkg.mkdir()
    (pkg / "mod.py").write_text("x = 1\n")
    (pkg / "notes.md").write_text("prose\n")
    (pkg / "data.json").write_text("{}\n")
    _git(tmp_path, "add", "harness")

    assert tracked_py_sources("harness", repo_root=tmp_path) == [
        (pkg / "mod.py").resolve()
    ]


def test_tracked_py_sources_unions_bases_sorted_without_duplicates(
    tmp_path: Path,
) -> None:
    """Multiple bases union, sort, and dedupe — the parametrize-source contract.

    Two call sites feed the result straight into ``pytest.mark.parametrize``, so
    a duplicate would collect the same case twice and an unstable order would
    make collection IDs vary between runs. Overlapping bases (``.`` covers
    ``harness``) must not double-report.
    """
    _init_repo(tmp_path)
    for base in ("harness", "tests"):
        (tmp_path / base).mkdir()
        (tmp_path / base / "mod.py").write_text("x = 1\n")
    _git(tmp_path, "add", "harness", "tests")

    result = tracked_py_sources("harness", "tests", ".", repo_root=tmp_path)

    assert result == sorted(result)
    assert len(result) == len(set(result))
    assert result == [
        (tmp_path / "harness" / "mod.py").resolve(),
        (tmp_path / "tests" / "mod.py").resolve(),
    ]


def test_tracked_py_sources_with_no_match_is_empty(tmp_path: Path) -> None:
    """A base holding no tracked Python — and no bases at all — yields ``[]``."""
    _init_repo(tmp_path)
    (tmp_path / "keep.md").write_text("prose\n")
    _git(tmp_path, "add", "keep.md")

    assert tracked_py_sources("harness", repo_root=tmp_path) == []
    assert tracked_py_sources(repo_root=tmp_path) == []


def _commit_on(repo: Path, relpath: str, stamp: str, message: str) -> None:
    """Stage ``relpath`` and commit it with author+committer date ``stamp``.

    Both dates are pinned so the assertions below are on a known day rather than
    on whenever the suite happens to run.
    """
    _git(repo, "add", relpath)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=Test",
            "commit",
            "-q",
            "-m",
            message,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
        },
    )


def test_last_commit_date_reports_the_commit_day(tmp_path: Path) -> None:
    """A committed file reports the author date of the commit that touched it."""
    _init_repo(tmp_path)
    (tmp_path / "spec.md").write_text("first\n")
    _commit_on(tmp_path, "spec.md", "2026-03-04T12:00:00+00:00", "add spec")

    assert last_commit_date("spec.md", repo_root=tmp_path) == date(2026, 3, 4)


def test_last_commit_date_reports_the_most_recent_commit(tmp_path: Path) -> None:
    """With several commits touching the path, the latest one wins."""
    _init_repo(tmp_path)
    (tmp_path / "spec.md").write_text("first\n")
    _commit_on(tmp_path, "spec.md", "2026-03-04T12:00:00+00:00", "add spec")
    (tmp_path / "other.md").write_text("unrelated\n")
    _commit_on(tmp_path, "other.md", "2026-05-01T12:00:00+00:00", "add other")
    (tmp_path / "spec.md").write_text("second\n")
    _commit_on(tmp_path, "spec.md", "2026-04-09T12:00:00+00:00", "edit spec")

    # The later commit on *this* path — not the repo's newest commit, which
    # touched a different file.
    assert last_commit_date("spec.md", repo_root=tmp_path) == date(2026, 4, 9)


def test_last_commit_date_is_none_for_a_staged_but_uncommitted_path(
    tmp_path: Path,
) -> None:
    """A tracked-but-never-committed path reports ``None``, not a date.

    This is the case the feature-spec guard skips on: ``tracked_files_under``
    reads the *index*, so a newly ``git add``ed spec is already a subject while
    having no commit to be measured against. "Never committed" and "committed on
    day D" answer different questions, so the helper keeps them distinguishable
    rather than coercing the first.

    The repo needs at least one commit for the question to be askable at all —
    ``git log`` fails outright on a repository with no commits, which is why
    that state is covered by the raising test below rather than by this one.
    """
    _init_repo(tmp_path)
    (tmp_path / "other.md").write_text("history exists\n")
    _commit_on(tmp_path, "other.md", "2026-03-04T12:00:00+00:00", "add other")
    (tmp_path / "spec.md").write_text("staged only\n")
    _git(tmp_path, "add", "spec.md")

    assert last_commit_date("spec.md", repo_root=tmp_path) is None


def test_last_commit_date_ignores_uncommitted_edits(tmp_path: Path) -> None:
    """A working-tree edit does not move the date — the committed tree is judged."""
    _init_repo(tmp_path)
    (tmp_path / "spec.md").write_text("first\n")
    _commit_on(tmp_path, "spec.md", "2026-03-04T12:00:00+00:00", "add spec")
    (tmp_path / "spec.md").write_text("edited, not committed\n")

    assert last_commit_date("spec.md", repo_root=tmp_path) == date(2026, 3, 4)


def test_last_commit_date_raises_on_a_git_level_failure(tmp_path: Path) -> None:
    """A git-level failure raises rather than degrading to ``None``.

    If it degraded, a guard pointed at a non-repository would read as "no
    history" and pass, certifying a check that never ran. Both git-level
    failures are pinned: a path outside any repository, and a repository
    carrying no commits at all — ``git log`` refuses the latter rather than
    reporting it as an empty result, which is why the ``None`` contract above
    is about a path without history and not about a repo without history.
    """
    with pytest.raises(subprocess.CalledProcessError):
        last_commit_date("spec.md", repo_root=tmp_path)

    empty_repo = tmp_path / "empty"
    empty_repo.mkdir()
    _init_repo(empty_repo)
    with pytest.raises(subprocess.CalledProcessError):
        last_commit_date("spec.md", repo_root=empty_repo)


#: The guards whose file set must come from ``tracked_py_sources``. Each walked
#: the working tree with ``rglob("*.py")`` before #215 — the same missing
#: exclusion independently absent in four modules, which is why the fix is one
#: shared helper rather than a filter pasted four times.
_TREE_WALKING_GUARDS = (
    "tests/unit/test_time.py",
    "tests/unit/test_cli_surface_locked.py",
    "tests/unit/test_engine_retired.py",
    "tests/unit/test_design_marker.py",
)


@pytest.mark.parametrize("relpath", _TREE_WALKING_GUARDS)
def test_tree_walking_guards_enumerate_from_the_tracked_helper(
    relpath: str,
) -> None:
    """No guard re-inlines a working-tree Python walk.

    Locks the adoption, not just the current behaviour: a future guard added by
    copying one of these would reintroduce the defect silently. Scoped to the
    named modules so this lock's own pattern literal cannot self-trip, and
    matched on ``*.py`` specifically so ``_living_doc_relpaths``'s legitimate
    ``rglob("*.md")`` walk stays untouched.
    """
    source = (Path(__file__).resolve().parents[2] / relpath).read_text()

    assert 'rglob("*.py")' not in source, (
        f"{relpath} walks the working tree for Python sources; a stray worktree "
        "or other untracked cruft under the scanned root then reads as living "
        "source (#215). Enumerate from tests._gitutil.tracked_py_sources instead."
    )
