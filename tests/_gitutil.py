"""Shared test helper: enumerate the files git *tracks* under a path.

Retirement / hygiene guards must judge the **committed** tree, not the working
tree. A guard whose contract is "this module is gone from the repo" must pass on
a clean checkout even when untracked cruft lingers on disk — an editor's
``.DS_Store``, or a stale ``__pycache__`` left behind when the ``.py`` source was
deleted. Scanning the working tree with ``Path.exists()`` / ``rglob`` conflates
the two and fails the canonical local gate on cruft (CAL-619 / CODE-INSIGHT-1;
the CODE-3 ``intake/__pycache__`` papercut and the PR #72 ``.DS_Store`` papercut).

``git ls-files`` is the authoritative tracked set. This helper wraps it so every
guard derives its file set from the same source instead of hand-rolling
dotfile / ``__pycache__`` skips.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# ``tests/_gitutil.py`` → ``parents[1]`` is the repo (or worktree) root.
_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]


def tracked_files_under(
    path: str | Path,
    *,
    repo_root: Path = _DEFAULT_REPO_ROOT,
) -> set[Path]:
    """Return the absolute, resolved paths git tracks under ``path``.

    ``path`` is a pathspec relative to ``repo_root`` (``"."`` for the whole
    tree). The result contains only files present in the git index — untracked
    files (OS cruft, build bytecode) are excluded by construction, and a path
    with no tracked files (a deleted or never-existed module) yields the empty
    set.

    ``repo_root`` defaults to the harness repo/worktree root containing this
    helper; tests override it to point at a throw-away repo.
    """
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", str(path)],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        (repo_root / rel).resolve()
        for rel in completed.stdout.split("\0")
        if rel
    }
