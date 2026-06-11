"""Unit tests for the shared CLI git helper (CAL-606).

``harness.cli._git.rev_parse_head`` is the single home for the HEAD-SHA read
that the ``review`` gate binds to and the ``close`` gate checks — extracted
from byte-for-byte copies that previously lived in ``review.py`` and
``close.py``. These tests pin the extracted contract directly so the helper has
coverage independent of the two verb modules that re-raise its failure.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.cli._git import GitError, rev_parse_head


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
