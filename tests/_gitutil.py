"""Shared test git helpers.

Three of them. Two derive file sets from git instead of the filesystem; the
third reads one tracked file's staged bytes.

:func:`tracked_files_under` enumerates the files git *tracks* under a path.

Tree-reading guards must judge the **committed** tree, not the working tree. A
guard whose contract is "this module is gone from the repo" must pass on a
clean checkout even when untracked cruft lingers on disk — an editor's
``.DS_Store``, or a stale ``__pycache__`` left behind when the ``.py`` source
was deleted. Scanning the working tree with ``Path.exists()`` / ``rglob``
conflates the two and fails the canonical local gate on cruft (CAL-619 /
CODE-INSIGHT-1). ``git ls-files`` is the authoritative tracked set; this helper
wraps it so every guard derives its file set from the same source instead of
hand-rolling dotfile / ``__pycache__`` skips.

:func:`tracked_py_sources` is that set projected onto Python sources.

:func:`indexed_text` is the same choice made about the *other* operand of a
comparison: the bytes git has staged for a path, never ``Path.read_text``.
``git write-tree`` certifies the index and the gate marker is named after the
tree it produces, so a guard reading the working file certifies bytes that may
never be committed (#482). It moved here from
``tests/unit/test_landing_page_inventory.py`` at #490, when the shipped Stop
hook's source became a second subject needing it.

Four tree-walking guards enumerated their own ``*.py`` set with ``rglob`` and no
exclusion for a nested git worktree, so two abandoned worktrees made old copies
of guarded sources read as living code and failed seven tests with no
regression behind them (#215). The projection lives here, next to the tracked
set it is built from, so the answer to "which files are living sources" has one
home rather than four.

The history readers this module once carried (``last_commit_date``,
``path_ever_existed``, the graft-boundary probe) served the feature-spec
currency and absence guards; ADR 0017 D5 deleted those guards with their
subjects, and the chunk-4 audit removed the then-importerless helpers. The
repo-fixture builders (``init_repo``, ``init_hermetic_repo``, ``git``) went the
same way — the surviving hook tests build their fixtures locally, against the
payload shapes each hook actually reads.
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


def tracked_py_sources(
    *bases: str,
    repo_root: Path = _DEFAULT_REPO_ROOT,
) -> list[Path]:
    """Return the git-tracked ``*.py`` files under each of ``bases``, sorted.

    The enumeration basis for guards that scan living Python source. Anything
    absent from the index — a nested worktree, ``__pycache__`` bytecode, a
    ``.venv`` — is excluded by construction rather than by an enumerated skip
    list, so a stray tree at an unanticipated path cannot be read as source
    (#215). A dot-prefix filter would have missed exactly that: a worktree
    parked at ``harness/tmp-promote/`` has no dot segment.

    The result is sorted, deduplicated, and absolute: two callers feed it to
    ``pytest.mark.parametrize``, where a duplicate collects a case twice and an
    unstable order makes collection IDs vary between runs. Overlapping bases are
    therefore safe.
    """
    found: set[Path] = set()
    for base in bases:
        found |= tracked_files_under(base, repo_root=repo_root)
    return sorted(path for path in found if path.suffix == ".py")


def indexed_text(path: str, *, repo_root: Path = _DEFAULT_REPO_ROOT) -> str:
    """The bytes git has **staged** for ``path``.

    Not ``Path.read_text``. ``git write-tree`` certifies the index, the gate
    marker is named after the tree that write-tree produces, and a review
    verdict binds to that same oid — so the index is the only operand that
    answers "what will ship". Reading the working file instead certifies bytes
    that may never be committed: measured at the #482 review, a tree staging a
    page with a skill deleted, with the correct page restored on disk unstaged,
    passed that module 12/12 while ``git write-tree`` reported an oid whose page
    was wrong.

    It sits here, beside :func:`tracked_files_under`, because the two are the
    same choice made about the two halves of a comparison, and #490 needed the
    index-reading half for a second subject (the shipped Stop hook's source).
    A guard reading one operand from the index and the other from disk is the
    #482 defect wearing a different hat.
    """
    completed = subprocess.run(
        ["git", "show", f":{path}"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout
