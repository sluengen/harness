"""Unit tests for the shared git helper (CAL-606, CAL-610).

Named for :mod:`harness._git`, which is where the module lives since #269 moved
it out of the ``harness.cli`` package — it is consumed from below the CLI as well
as inside it, and homing it in the CLI package made three lower modules
un-importable first (``tests/unit/test_import_layering.py`` guards that).

``harness._git.rev_parse_head`` is the single home for the HEAD-SHA read
that the ``review`` gate binds to and the ``close`` gate checks — extracted
from byte-for-byte copies that previously lived in ``review.py`` and
``close.py``. These tests pin the extracted contract directly so the helper has
coverage independent of the two verb modules that re-raise its failure.

``run_git`` (CAL-610) is the generic counterpart: the shared ``git -C <cwd>``
invocation shape — ``check=False``, ``capture_output=True`` — that the sync verb
sites hand-wrote five times. It returns the :class:`subprocess.CompletedProcess`
untouched so each caller keeps its own error policy (raise, ignore, or inspect).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness._git import (
    GitError,
    git_common_dir,
    rev_parse_head,
    run_git,
    tracked_paths,
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo with exactly one commit."""
    # Branch stated, not inherited from the host's `init.defaultBranch` (#369).
    _git(tmp_path, "init", "-q", "-b", "dev")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "f.txt").write_text("x\n")
    _git(tmp_path, "add", "f.txt")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_rev_parse_head_returns_head_sha(repo: Path) -> None:
    """The helper returns the worktree's current HEAD, stripped of whitespace."""
    expected = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert rev_parse_head(repo) == expected
    assert "\n" not in rev_parse_head(repo)


def test_rev_parse_head_raises_giterror_on_non_repo(tmp_path: Path) -> None:
    """A path that is not a git repo surfaces as ``GitError`` (a RuntimeError)."""
    not_a_repo = tmp_path / "empty"
    not_a_repo.mkdir()
    with pytest.raises(GitError) as excinfo:
        rev_parse_head(not_a_repo)
    # Message names the failing operation and the offending path.
    assert "rev-parse HEAD" in str(excinfo.value)
    assert str(not_a_repo) in str(excinfo.value)


def test_giterror_is_runtime_error() -> None:
    """``GitError`` is a ``RuntimeError`` so generic ``except`` handlers catch it."""
    assert issubclass(GitError, RuntimeError)


# ---------------------------------------------------------------------------
# run_git — the generic git invocation primitive (CAL-610)
# ---------------------------------------------------------------------------


def test_run_git_returns_completed_process(repo: Path) -> None:
    """A successful invocation returns the CompletedProcess, returncode 0."""
    result = run_git(repo, "rev-parse", "HEAD")
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 0
    expected = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert result.stdout.strip() == expected


def test_run_git_targets_the_given_cwd(repo: Path) -> None:
    """The helper prefixes ``git -C <cwd>`` so it operates on the passed repo."""
    (repo / "dirty.txt").write_text("y\n")
    result = run_git(repo, "status", "--porcelain")
    assert result.returncode == 0
    assert "dirty.txt" in result.stdout


def test_run_git_does_not_raise_on_failure(tmp_path: Path) -> None:
    """A failing git command surfaces as a non-zero returncode, not an exception.

    Error policy stays with the caller — the verb sites raise their own
    exception (or ignore the result for best-effort cleanup).
    """
    not_a_repo = tmp_path / "empty"
    not_a_repo.mkdir()
    result = run_git(not_a_repo, "rev-parse", "HEAD")
    assert result.returncode != 0
    assert isinstance(result.stderr, str)


# ---------------------------------------------------------------------------
# git_common_dir — the worktree → main-checkout resolution primitive (#179)
# ---------------------------------------------------------------------------


def test_git_common_dir_of_the_main_checkout_is_its_own_dot_git(repo: Path) -> None:
    """For the main checkout, the common dir is ``repo/.git``."""
    assert git_common_dir(repo) == (repo / ".git").resolve()


def test_git_common_dir_of_a_worktree_is_the_main_checkouts_dot_git(
    repo: Path,
) -> None:
    """For a linked worktree, the common dir is the *main checkout's* ``.git`` —
    the shared state a worktree has no copy of."""
    worktree = repo.parent / "wt"
    _git(repo, "worktree", "add", "-q", str(worktree), "-b", "feature")

    assert git_common_dir(worktree) == (repo / ".git").resolve()


def test_git_common_dir_returns_none_for_a_non_git_path(tmp_path: Path) -> None:
    """A path outside any git working tree resolves to ``None``."""
    not_a_repo = tmp_path / "empty"
    not_a_repo.mkdir()
    assert git_common_dir(not_a_repo) is None


def test_run_git_returns_text_output(repo: Path) -> None:
    """Output is captured and decoded to ``str`` (``text=True``)."""
    result = run_git(repo, "rev-parse", "HEAD")
    assert isinstance(result.stdout, str)
    assert isinstance(result.stderr, str)


# --- tracked_paths (#359) ------------------------------------------------------
#
# The worktree index enumeration, extracted here from
# ``reclaim_liveness.worktree_last_activity`` when ``review``'s polluted-worktree
# guard became its second caller. The extraction is what makes the two agree on
# *which* paths count as the worktree's own — including the load-bearing
# ``worktree_toplevel_matches`` anchor, without which git walks **up** from a
# pruned worktree and reports the main checkout's index.


def test_tracked_paths_lists_the_index(repo: Path) -> None:
    """The tracked set is returned as repo-relative paths."""
    (repo / "sub").mkdir()
    (repo / "sub" / "b.txt").write_text("b\n")
    _git(repo, "add", "sub/b.txt")
    _git(repo, "-c", "user.email=t@e.c", "-c", "user.name=T", "commit", "-m", "add")

    paths = tracked_paths(repo)

    assert paths is not None
    assert "sub/b.txt" in paths


def test_tracked_paths_is_none_for_a_non_directory(tmp_path: Path) -> None:
    """A path that is not a directory is *no opinion*, never an empty index."""
    plain = tmp_path / "file"
    plain.write_text("x\n")
    assert tracked_paths(plain) is None


def test_tracked_paths_is_none_for_a_plain_directory(tmp_path: Path) -> None:
    """A directory that is not itself a git top-level answers ``None``.

    The anchor that stops git walking **up**: without it a pruned worktree
    directory reports the *main checkout's* index, and every consumer silently
    measures the wrong tree.
    """
    plain = tmp_path / "empty"
    plain.mkdir()
    assert tracked_paths(plain) is None


def test_tracked_paths_is_none_for_an_empty_index(tmp_path: Path) -> None:
    """A git top-level with nothing tracked is *no opinion*, not ``[]``.

    An empty list would read as "0 tracked files", which is the input that makes
    every on-disk file look like excess.
    """
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    _git(fresh, "init", "-b", "dev")
    assert tracked_paths(fresh) is None


def test_tracked_paths_splits_on_nul_so_a_newline_in_a_name_is_one_entry(
    repo: Path,
) -> None:
    """``-z`` output is NUL-separated, so a newline in a filename cannot forge
    a second entry (and cannot inflate the tracked count)."""
    weird = repo / "two\nlines.txt"
    weird.write_text("x\n")
    _git(repo, "add", "--", str(weird))
    _git(repo, "-c", "user.email=t@e.c", "-c", "user.name=T", "commit", "-m", "weird")

    paths = tracked_paths(repo)

    assert paths is not None
    assert "two\nlines.txt" in paths


def test_tracked_paths_is_none_when_git_fails(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero ``git ls-files`` is *no opinion* — the caller must fail open."""
    import harness._git as git_mod

    real = git_mod.run_git

    def _fail(cwd: Path, *args: str, **kwargs: object) -> object:
        if args and args[0] == "ls-files":
            return subprocess.CompletedProcess(["git"], 1, "", "boom")
        return real(cwd, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(git_mod, "run_git", _fail)
    assert tracked_paths(repo) is None


def test_tracked_paths_is_none_when_git_times_out(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wedged git is *no opinion* rather than an exception reaching the verb."""
    import harness._git as git_mod

    real = git_mod.run_git

    def _hang(cwd: Path, *args: str, **kwargs: object) -> object:
        if args and args[0] == "ls-files":
            raise subprocess.TimeoutExpired(["git", "ls-files"], 15)
        return real(cwd, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(git_mod, "run_git", _hang)
    assert tracked_paths(repo) is None


def test_tracked_paths_is_none_for_a_subdirectory_of_a_repo(repo: Path) -> None:
    """The anchor's real hazard: a directory *inside* a worktree, not its top.

    The plain-directory case above is not this one. There ``git ls-files`` fails
    outright, so ``None`` comes back whether the anchor exists or not — it cannot
    tell an anchored implementation from an unanchored one. Here git walks **up**,
    finds the repo, and answers *successfully* with a subset: only the paths under
    this subdirectory, spelled relative to it.

    That is the silent wrong answer, and it is wrong in the dangerous direction.
    A consumer counting tracked files gets an **undercount** while its own view of
    what is on disk does not shrink to match — which for ``review``'s pollution
    guard means an overstated excess and a clean worktree refused.
    """
    (repo / "sub").mkdir()
    (repo / "sub" / "b.txt").write_text("b\n")
    _git(repo, "add", "sub/b.txt")
    _git(repo, "-c", "user.email=t@e.c", "-c", "user.name=T", "commit", "-m", "add")

    # The premise, asserted rather than assumed: from in here git succeeds and
    # reports a partial index — ``sub``'s own file, not the repo's README.
    walked_up = run_git(repo / "sub", "ls-files", "-z")
    assert walked_up.returncode == 0
    assert "b.txt" in walked_up.stdout
    assert "README.md" not in walked_up.stdout

    assert tracked_paths(repo / "sub") is None
