"""Shared git helpers for the verbs (CAL-606, CAL-610).

Two layers live here. :func:`run_git` is the generic *invocation* primitive —
the ``git -C <cwd> …`` argv prefix with ``check=False`` and
``capture_output=True`` — that every sync verb site shells out with. It returns
the :class:`subprocess.CompletedProcess` untouched so each caller keeps its own
error policy: raise a verb-specific exception, ignore the result for best-effort
cleanup, or inspect ``returncode`` directly. Centralising it means a change to
*how* the verbs call git (a flag, the binary path, NUL-terminated output) lands
once.

:func:`rev_parse_head` is a domain rule layered on top: ``review`` binds a
verdict to ``git rev-parse HEAD`` and ``close`` refuses to merge unless that
same SHA is still HEAD. That logic previously lived as byte-for-byte copies in
``review.py`` and ``close.py``, differing only in which verb-private exception
they raised. Giving the rule one home lets each caller re-raise :class:`GitError`
as its own verb-specific error.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
from pathlib import Path

from harness.branch_config import integration_branch
from harness.identity import WORKTREES_SUBDIR

#: The back-compat fallback base branch when neither CONTEXT.md nor the repo's
#: origin default resolves one — the harness's own integration branch (CAL-1106).
DEFAULT_BASE_BRANCH = "dev"

# Default ceiling (seconds) for a *network* git call — ``fetch`` / ``push`` /
# ``push --delete`` (CAL-1004). These reach a remote and can hang indefinitely on
# a partition or a wedged server; a local call (checkout, merge, rev-parse) does
# not and passes no timeout. 120s sits in the documented 60–120s band: generous
# for a healthy remote, bounded against a dead one. ``run_git`` forwards it to
# ``subprocess.run``, which raises ``subprocess.TimeoutExpired`` on expiry — each
# network site converts that into its own failure shape (never a raw traceback).
NETWORK_GIT_TIMEOUT_SECONDS = 120


class GitError(RuntimeError):
    """A git subprocess invocation failed.

    A plain :class:`RuntimeError` subclass so each verb can catch it and
    re-raise as its own control-flow exception (with the verb's exit code)
    without this module depending on either verb.
    """


def run_git(
    cwd: Path,
    *args: str,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``git -C <cwd> <args>`` capturing text output; never raise on non-zero.

    The shared invocation shape — the ``git -C`` prefix, ``check=False``,
    ``capture_output=True``, ``text=True`` — lives here so a change to how the
    verbs shell out to git lands once. Error handling stays with the caller: the
    :class:`subprocess.CompletedProcess` is returned untouched, so callers
    inspect ``returncode`` and raise their own verb-specific exception, ignore it
    (best-effort cleanup), or read the parsed output.

    ``timeout`` is forwarded as-is — a fired timeout raises
    :class:`subprocess.TimeoutExpired`, which the caller's guard handles; this
    helper does not swallow it.
    """
    return subprocess.run(  # noqa: S603, S607
        ["git", "-C", str(cwd), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def rev_parse_head(worktree_path: Path) -> str:
    """Return the current HEAD SHA of ``worktree_path`` (sync — run in a thread).

    Raises :class:`GitError` if ``git rev-parse HEAD`` exits non-zero.
    """
    result = run_git(worktree_path, "rev-parse", "HEAD")
    if result.returncode != 0:
        raise GitError(
            f"git rev-parse HEAD failed for {worktree_path}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def origin_default_branch(repo_root: Path) -> str | None:
    """The repo's default branch per ``origin/HEAD``, or ``None`` if unresolvable.

    Reads ``git symbolic-ref refs/remotes/origin/HEAD`` (set by ``git clone``) and
    strips the ``refs/remotes/origin/`` prefix. Returns ``None`` when there is no
    ``origin`` remote or ``origin/HEAD`` was never recorded (e.g. a repo created
    with ``git init`` and a bare ``remote add`` but no clone) — a local call, no
    timeout needed. The caller supplies the fallback.
    """
    result = run_git(repo_root, "symbolic-ref", "refs/remotes/origin/HEAD")
    if result.returncode != 0:
        return None
    ref = result.stdout.strip()
    prefix = "refs/remotes/origin/"
    branch = ref[len(prefix):] if ref.startswith(prefix) else ref
    return branch or None


def resolve_base_branch(repo_root: Path, explicit: str | None = None) -> str:
    """Resolve the base branch a run builds off / a merged worktree is reclaimed
    against, without hardcoding this repo's ``dev`` into a generic scaffold (CAL-1106).

    Resolution order (first hit wins):

    1. ``explicit`` — a caller-supplied value (``start --base``).
    2. ``branches.integration`` from the repo's CONTEXT.md
       (:func:`harness.branch_config.integration_branch`).
    3. The repo's actual default branch (:func:`origin_default_branch`).
    4. :data:`DEFAULT_BASE_BRANCH` (``"dev"``) — the back-compat fallback, so a
       repo that configures nothing behaves exactly as before.
    """
    return (
        explicit
        or integration_branch(repo_root)
        or origin_default_branch(repo_root)
        or DEFAULT_BASE_BRANCH
    )


def _is_safe_branch_arg(branch: str) -> bool:
    """True iff ``branch`` is safe to pass as a git branch-name positional.

    A run's branch is ULID-shaped (``harness/<ULID>``), but a resumed run's name
    can originate in an untrusted tracker comment (the reclaim / handoff markers
    parsed in ``harness.linear``). Such a value is already argv-safe — every git
    call here is list-form, never ``shell=True`` — but a name with a leading
    ``-`` would be read by git as an *option*, not a branch (``git branch -D
    --all``). Refusing a ``-``-prefixed name at this sink neutralises that
    flag-injection without needing to trust the source (go-public security
    review). Real branch names (``harness/…``) are never dash-prefixed, so no
    legitimate teardown is affected.
    """
    return not branch.startswith("-")


def teardown_worktree(
    repo_root: Path,
    *,
    worktree_path: Path,
    branch: str | None = None,
    delete_remote: bool = False,
) -> None:
    """Reclaim a run's worktree directory and branch — best-effort, never raises.

    One reclaim primitive for every site that finishes with a worktree it no
    longer needs: ``start`` rolling back a failed create, ``close`` after the
    merge has landed, and ``worktrees cleanup`` sweeping a merged run. It runs
    *after* the operation it follows has already succeeded, so a teardown failure
    must never mask or undo that — every git call ignores its result and no path
    here raises (CAL-767).

    Steps, in order:

    1. ``git worktree remove --force`` the directory. If that exits non-zero and
       the directory is still present, it is an **orphan** — its worktree
       registration was already pruned, so git no longer recognises it as a
       working tree — and :func:`shutil.rmtree` removes it instead. This is the
       cruft case a plain ``git worktree remove`` cannot touch.
    2. ``git worktree prune`` to drop any stale admin entry left behind.
    3. ``git branch -D <branch>`` to delete the local branch (when given).
    4. ``git push origin --delete <branch>`` when ``delete_remote`` — a
       checkpoint push may have created the branch on ``origin``; once the run is
       merged it is dead weight. A no-op (and harmless non-zero exit) when the
       remote ref does not exist.

    **Safety:** directory removal only ever touches a path *inside*
    ``<repo_root>/.worktrees/harness/``. A ``worktree_path`` that is the main
    checkout (or anything outside the run-worktree area) skips removal entirely —
    the ``rmtree`` fallback must never be able to destroy the repository itself.
    The branch operations still run (deleting a merged run branch is safe) —
    unless ``branch`` is flag-like (leading ``-``), which :func:`_is_safe_branch_arg`
    refuses so an untrusted, tracker-parsed name cannot be read by git as an
    option instead of a branch.
    """
    worktrees_area = (repo_root / WORKTREES_SUBDIR).resolve()
    resolved = worktree_path.resolve()
    within_worktrees_area = (
        resolved != worktrees_area and worktrees_area in resolved.parents
    )
    if within_worktrees_area and worktree_path.exists():
        result = run_git(repo_root, "worktree", "remove", "--force", str(worktree_path))
        if result.returncode != 0 and worktree_path.exists():
            # Orphaned directory — git won't remove what it no longer tracks.
            shutil.rmtree(worktree_path, ignore_errors=True)
    run_git(repo_root, "worktree", "prune")
    if branch and _is_safe_branch_arg(branch):
        run_git(repo_root, "branch", "-D", branch)
        if delete_remote:
            # A network op — bound it (CAL-1004). Teardown is best-effort and
            # never raises (CAL-767), so a fired timeout is swallowed here like
            # any other non-zero exit on this cleanup path.
            with contextlib.suppress(subprocess.TimeoutExpired):
                run_git(
                    repo_root,
                    "push",
                    "origin",
                    "--delete",
                    branch,
                    timeout=NETWORK_GIT_TIMEOUT_SECONDS,
                )
