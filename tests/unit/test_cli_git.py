"""Unit tests for the shared CLI git helper (CAL-606, CAL-610).

``harness.cli._git.rev_parse_head`` is the single home for the HEAD-SHA read
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

from harness.cli._git import GitError, git_common_dir, rev_parse_head, run_git


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
    _git(tmp_path, "init", "-q")
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
