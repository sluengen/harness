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

``path_ever_existed`` (#451) is the fourth: whether any commit ever touched a
path, which is what an absence guard must be measured against. It is a
deliberately *different* question from the third — full-graph rather than
simplified history, and a shallow clone's graft boundary counts as an answer
rather than being refused — so the two diverge in the cases pinned below.
"""

from __future__ import annotations

import os
import subprocess
from datetime import date
from pathlib import Path

import pytest

from tests._gitutil import (
    ShallowHistoryError,
    last_commit_date,
    path_ever_existed,
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
    # Branch stated, not inherited from the host's `init.defaultBranch` (#369).
    _git(repo, "init", "-q", "-b", "dev")


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
    expected = Path(__file__).resolve().with_name("test_mutate.py")
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


def _origin_with_three_commits(tmp_path: Path) -> Path:
    """An origin repo whose history is ``spec.md`` once, then ``other.md`` twice.

    ``spec.md``'s only commit is the **root**, so a shallow clone that fetches
    fewer than three commits cannot reach it — which is what makes it the
    subject of the boundary cases below.
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    _init_repo(origin)
    (origin / "spec.md").write_text("spec\n")
    (origin / "other.md").write_text("other\n")
    _git(origin, "add", "spec.md", "other.md")
    _commit_on(origin, "spec.md", "2026-03-04T12:00:00+00:00", "add spec and other")
    (origin / "other.md").write_text("other v2\n")
    _commit_on(origin, "other.md", "2026-04-09T12:00:00+00:00", "edit other")
    (origin / "other.md").write_text("other v3\n")
    _commit_on(origin, "other.md", "2026-05-01T12:00:00+00:00", "edit other again")
    return origin


def _shallow_clone(origin: Path, dest: Path, depth: int) -> Path:
    """Clone *origin* to *dest* at ``--depth``.

    The ``file://`` URL is mandatory: a plain local-path clone hardlinks the
    object store and silently **ignores** ``--depth``, which would leave the
    clone deep and let the assertions below pass vacuously.
    """
    subprocess.run(
        ["git", "clone", "-q", "--depth", str(depth), f"file://{origin}", str(dest)],
        check=True,
        capture_output=True,
    )
    return dest


def test_last_commit_date_refuses_a_shallow_boundary_answer(tmp_path: Path) -> None:
    """A date resolving to a graft boundary is refused, not returned (#326).

    ``git log -1 -- <path>`` in a depth-1 clone reports the boundary commit for
    **every** path — a grafted commit has no known parents, so history
    simplification reads it as introducing the whole tree. #280 returned that
    date as if it were real, which is why CI (``actions/checkout`` defaults to
    ``fetch-depth: 1``) reported every feature spec as touched at HEAD.
    """
    origin = _origin_with_three_commits(tmp_path)
    clone = _shallow_clone(origin, tmp_path / "shallow", depth=1)

    # Setup assertions first: an environment that ignored --depth would make the
    # contract below pass without ever exercising it.
    is_shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert is_shallow == "true", "the clone is not shallow — --depth was ignored"
    count = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert count == "1", f"expected a depth-1 clone, got {count} commits"

    # The trap is real: git's raw answer for spec.md is not spec.md's real date.
    raw = subprocess.run(
        ["git", "log", "-1", "--format=%ad", "--date=short", "--", "spec.md"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert raw != "2026-03-04", (
        "git reported spec.md's true date in a depth-1 clone — the truncation "
        "this test exists to pin did not happen"
    )

    with pytest.raises(ShallowHistoryError):
        last_commit_date("spec.md", repo_root=clone)


def test_last_commit_date_trusts_a_non_boundary_answer_in_a_shallow_clone(
    tmp_path: Path,
) -> None:
    """Only boundary-resolving answers are refused — the flag alone is not enough.

    The harness's own checkout is shallow-*flagged* while carrying ~1200
    commits, so refusing on ``--is-shallow-repository`` alone would red the
    local gate for every spec. The refusal is scoped to answers that actually
    resolve to a graft boundary, which is the smallest correct rule.
    """
    origin = _origin_with_three_commits(tmp_path)
    clone = _shallow_clone(origin, tmp_path / "shallow2", depth=2)

    is_shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert is_shallow == "true", "the clone is not shallow — the test proves nothing"

    # other.md's last commit is HEAD, well inside the fetched window.
    assert last_commit_date("other.md", repo_root=clone) == date(2026, 5, 1)

    # spec.md's answer still resolves to the grafted commit, so it is refused.
    with pytest.raises(ShallowHistoryError):
        last_commit_date("spec.md", repo_root=clone)


# ---------------------------------------------------------------------------
# #451 — ``path_ever_existed``: the full-graph existence question an absence
# guard is measured against, and the two places it diverges from the date.


def _repo_with_a_one_sided_merge(tmp_path: Path) -> Path:
    """A repo whose HEAD is a merge pruning ``gone.md`` out of default history.

    The topology, which is the whole fixture: ``gone.md`` is created *and*
    deleted entirely on ``side``, while ``dev`` moves independently and never
    holds it. Merging ``side`` into ``dev`` with ``--no-ff`` leaves a two-parent
    commit whose tree carries no ``gone.md`` — TREESAME to the first parent for
    that path, so default history simplification follows ``dev`` alone and
    reports no commit at all.

    This is a release candidate in miniature: the merge of a release branch and
    an integration branch where a module was born and retired since the last
    release.
    """
    repo = tmp_path / "merged"
    repo.mkdir()
    _init_repo(repo)
    (repo / "base.md").write_text("base\n")
    _commit_on(repo, "base.md", "2026-01-05T12:00:00+00:00", "add base")

    _git(repo, "checkout", "-q", "-b", "side")
    (repo / "gone.md").write_text("transient\n")
    _commit_on(repo, "gone.md", "2026-02-05T12:00:00+00:00", "add gone")
    (repo / "gone.md").unlink()
    _commit_on(repo, "gone.md", "2026-02-06T12:00:00+00:00", "delete gone")

    _git(repo, "checkout", "-q", "dev")
    (repo / "base.md").write_text("base v2\n")
    _commit_on(repo, "base.md", "2026-03-05T12:00:00+00:00", "edit base")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    return repo


def test_path_ever_existed_sees_a_path_pruned_by_default_simplification(
    tmp_path: Path,
) -> None:
    """A path pruned out of simplified history is still reported as having existed.

    This is the #451 defect. ``git log -1 -- <path>`` runs under git's default
    history simplification, which stops at a merge that is TREESAME to one
    parent and walks only that side. On a release candidate — a merge of the
    release branch and the integration branch — a module born and deleted
    entirely on the integration side is invisible to that query, so an existence
    check built on it reports "this path never existed" about a path that
    demonstrably did. ``--full-history`` walks every parent, which is the only
    query whose answer does not depend on the topology it is asked over.
    """
    repo = _repo_with_a_one_sided_merge(tmp_path)

    # The trap is real: git's simplified answer for gone.md is no answer at all.
    # Without this, a fixture that failed to build the pruning topology would
    # let the contract below pass while exercising nothing.
    pruned = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", "gone.md"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert pruned == "", (
        f"git's default-simplification query still reports {pruned} for gone.md "
        f"— the fixture did not build the pruning topology this test exists to "
        f"pin, so it proves nothing"
    )

    assert path_ever_existed("gone.md", repo_root=repo) is True


def test_path_ever_existed_is_false_for_a_name_that_was_never_real(
    tmp_path: Path,
) -> None:
    """Polarity: a path git has never seen answers ``False``.

    The half that makes the helper worth calling. An existence predicate that
    answered ``True`` unconditionally would satisfy every absence guard's
    "this path was real" parameter — including the misspelled ones the guard
    exists to catch — while measuring nothing at all.

    The rename case is pinned here too, because it is the near neighbour a
    reader is most likely to file under "never existed" and it answers the
    other way.
    """
    _init_repo(tmp_path)
    (tmp_path / "keep.md").write_text("real\n")
    _commit_on(tmp_path, "keep.md", "2026-03-04T12:00:00+00:00", "add keep")

    assert path_ever_existed("keep.md", repo_root=tmp_path) is True
    assert path_ever_existed("kepp.md", repo_root=tmp_path) is False

    # A path *renamed away* is not a "never existed" case: the rename commit
    # touches the old name, so both spellings answer True. Pinned because the
    # helper's docstring draws the line there and nothing else measured it.
    _git(tmp_path, "mv", "keep.md", "moved.md")
    _commit_on(tmp_path, "moved.md", "2026-03-05T12:00:00+00:00", "rename keep.md")
    assert path_ever_existed("keep.md", repo_root=tmp_path) is True
    assert path_ever_existed("moved.md", repo_root=tmp_path) is True


def test_path_ever_existed_raises_on_a_git_level_failure(tmp_path: Path) -> None:
    """A git-level failure raises rather than degrading to ``False``.

    Same contract as ``last_commit_date``, for the same reason: a guard pointed
    at a non-repository must go red, not read as "this path never existed" and
    fail the absence check for a reason that has nothing to do with the tree.
    """
    with pytest.raises(subprocess.CalledProcessError):
        path_ever_existed("spec.md", repo_root=tmp_path)

    empty_repo = tmp_path / "empty"
    empty_repo.mkdir()
    _init_repo(empty_repo)
    with pytest.raises(subprocess.CalledProcessError):
        path_ever_existed("spec.md", repo_root=empty_repo)


def test_path_ever_existed_counts_a_shallow_boundary_answer_as_existence(
    tmp_path: Path,
) -> None:
    """A graft-boundary answer is existence here, and a refusal for the date.

    The deliberate divergence, pinned in one test so it cannot be read as an
    oversight. What a shallow clone makes untrustworthy is *when* a path last
    changed — the boundary commit stands in for however much history was never
    fetched. It does not make the answer to *whether* a commit touched the path
    untrustworthy: git found one, and existence is exactly what that proves.
    """
    origin = _origin_with_three_commits(tmp_path)
    clone = _shallow_clone(origin, tmp_path / "shallow", depth=1)

    is_shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert is_shallow == "true", "the clone is not shallow — --depth was ignored"

    assert path_ever_existed("spec.md", repo_root=clone) is True
    # The refusal below is this test's liveness control as well as half its
    # subject: it fires only when git's answer for spec.md really did resolve to
    # a graft boundary, so a clone that quietly fetched the whole history could
    # not let the assertion above pass as if it had crossed one.
    with pytest.raises(ShallowHistoryError):
        last_commit_date("spec.md", repo_root=clone)
