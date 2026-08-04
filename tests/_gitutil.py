"""Shared test git helpers.

Four of them, all about not hand-rolling git in test modules.

:func:`init_repo` makes a throw-away directory a real repository. Since #214 the
verbs refuse a ``--repo`` that is not a git top-level, so any fixture handing a
bare ``tmp_path`` to a verb has to initialize it first — a need that landed in
five test modules at once, which is why the two-line call lives here instead of
being pasted into each.

:func:`tracked_files_under` enumerates the files git *tracks* under a path.

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

:func:`tracked_py_sources` is that set projected onto Python sources.

Four tree-walking guards enumerated their own ``*.py`` set with ``rglob`` and no
exclusion for a nested git worktree, so two abandoned worktrees left inside
``harness/`` made old copies of guarded sources read as living code and failed
seven tests with no regression behind them (#215). The projection lives here,
next to the tracked set it is built from, so the answer to "which files are
living sources" has one home rather than four.

:func:`last_commit_date` reports the day of the last commit that touched a path.

A doc that declares its own currency — a feature spec's ``last_updated``
frontmatter — asserts something only git can check, and until #280 nothing did:
the guard required the key to exist and never read its value, so every date
froze while the file changed underneath it. Answering "when did this file last
actually change?" needs the *author* date of the last commit touching that path,
which is the one date a writer can know at the moment they type the value.
"""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

# ``tests/_gitutil.py`` → ``parents[1]`` is the repo (or worktree) root.
_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]


def init_repo(path: Path) -> Path:
    """``git init`` a real repository at ``path`` (creating it) and return it.

    For fixtures that hand a throw-away directory to a verb's ``--repo``: since
    #214 the verbs refuse a path that is not a git top-level, so a bare
    ``tmp_path`` no longer resolves.

    A real ``git init`` rather than a hand-made ``.git`` directory, so the
    fixture stays true to the *contract* ("this is a repository root") rather
    than to one implementation of the check. ``init`` needs no user identity —
    only ``commit`` does — so this stays cheap and hermetic.
    """
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return path


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


def last_commit_date(
    path: str | Path,
    *,
    repo_root: Path = _DEFAULT_REPO_ROOT,
) -> date | None:
    """Return the author date of the last commit touching ``path``, or ``None``.

    ``path`` is a pathspec relative to ``repo_root``. ``None`` means git reports
    no commit for that path — a file staged but never committed, or a shallow
    clone whose fetched history does not reach one. Callers must distinguish
    that from a real date rather than coercing it, because the two answer
    different questions ("never committed" vs "committed on day D").

    The **author** date, not the committer date. Author date is the day the
    writer commits and survives the merge that lands it; committer date is
    rewritten by a rebase or merge the writer cannot predict at the moment they
    type a ``last_updated`` value, which would make such a field impossible to
    write correctly. The choice is about which date a human can *know*.

    Judges the **committed** tree, matching this module's purpose: an
    uncommitted working-tree edit is invisible here by construction. A git-level
    failure raises rather than degrading to ``None``, so a broken invocation can
    never read as "no history" (``engineering-principles``: errors are never
    swallowed). That covers not being a repository, git being missing, and a
    repository holding no commits at all — git refuses the last outright rather
    than reporting it as an empty result, so ``None`` always means "this path
    has no commit", never "this repo has none".
    """
    completed = subprocess.run(
        ["git", "log", "-1", "--format=%ad", "--date=short", "--", str(path)],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    stamp = completed.stdout.strip()
    return date.fromisoformat(stamp) if stamp else None


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
