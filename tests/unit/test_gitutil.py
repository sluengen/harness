"""Unit tests for the shared ``tracked_files_under`` git-tracked-file helper.

The helper is the authoritative basis for retirement / hygiene guards: it must
report only files git tracks, never working-tree cruft (an untracked
``.DS_Store``, stale ``__pycache__`` bytecode left over from a deleted module).
These tests pin that contract against a throw-away git repo so they do not
depend on the harness repo's own tree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests._gitutil import tracked_files_under


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
