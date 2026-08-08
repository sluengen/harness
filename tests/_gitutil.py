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

That answer is only as good as the fetched history. In a shallow clone git
reports the **graft boundary** for a path whose real last commit was never
fetched — a truncated answer that looks exactly like a real one — so
:func:`last_commit_date` refuses it with :class:`ShallowHistoryError` rather than
returning it (#326). #280 returned it, which is how CI (``actions/checkout``
defaults to ``fetch-depth: 1``) read every feature spec as touched at HEAD.
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

    The branch is stated, not inherited (#369). ``git init`` alone takes its
    branch from the *host's* ``init.defaultBranch``, which made a sibling
    fixture pass locally and fail in CI for two days. No consumer of this helper
    reads the branch name today, so the value is free; what matters is that the
    suite means the same thing on every host that runs it. ``dev`` is this
    repo's integration branch, so a repo handed to a verb that resolves a base
    branch already resolves.
    """
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q", "-b", "dev"],
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


class ShallowHistoryError(RuntimeError):
    """Git's answer for a path resolves to a shallow clone's graft boundary.

    A distinct type rather than a bare :class:`RuntimeError` so a caller that
    legitimately wants to tolerate truncated history can catch exactly this. No
    caller does today, deliberately: the feature-spec currency guard must go red
    and named on a truncated tree, not skip (#326).
    """


def _graft_boundaries(repo_root: Path) -> frozenset[str]:
    """The root commits of a shallow clone — empty when history is complete.

    In a shallow clone the fetch boundary is grafted to look parentless, so
    ``rev-list --max-parents=0`` names exactly the commits whose history is
    truncated. Gated on ``--is-shallow-repository`` first, so a genuine root
    commit in a complete clone is never mistaken for a boundary.

    Both probes use ``check=True``: a git failure here must raise, not degrade
    to "not shallow", which would silently restore the swallow this exists to
    remove.
    """
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    if shallow.stdout.strip() != "true":
        return frozenset()
    roots = subprocess.run(
        ["git", "rev-list", "--max-parents=0", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return frozenset(roots.stdout.split())


def last_commit_date(
    path: str | Path,
    *,
    repo_root: Path = _DEFAULT_REPO_ROOT,
) -> date | None:
    """Return the author date of the last commit touching ``path``, or ``None``.

    ``path`` is a pathspec relative to ``repo_root``. ``None`` means git reports
    no commit for that path — a file staged but never committed. Callers must
    distinguish that from a real date rather than coercing it, because the two
    answer different questions ("never committed" vs "committed on day D").

    Raises :class:`ShallowHistoryError` when git's answer resolves to a shallow
    clone's graft boundary: the real last commit lies outside the fetched
    history, and from inside the clone a truncated answer is indistinguishable
    from a real one (#326). The imprecision is one-directional and deliberate —
    a path whose genuine last commit *is* the boundary is refused rather than
    answered. Refusing an answer that happens to be right is safe; returning one
    that is wrong is what #280 shipped.

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
        ["git", "log", "-1", "--format=%H%x09%ad", "--date=short", "--", str(path)],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    line = completed.stdout.strip()
    if not line:
        return None
    sha, _, stamp = line.partition("\t")
    # The log runs first, so a non-repository or a repository with no commits
    # still raises CalledProcessError from the same command as before — the
    # boundary probe never gets to reinterpret a git-level failure.
    if sha in _graft_boundaries(repo_root):
        raise ShallowHistoryError(
            f"git reports {sha} as the last commit touching {path}, but that is "
            f"a shallow graft boundary in {repo_root} — the real last commit is "
            "outside the fetched history. Fetch full history (actions/checkout "
            "fetch-depth: 0, or git fetch --unshallow); do not read this date as "
            "real (#326)."
        )
    return date.fromisoformat(stamp)


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
