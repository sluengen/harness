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


def git_common_dir(repo_root: Path) -> Path | None:
    """The resolved absolute ``.git`` common directory for ``repo_root``, or
    ``None`` when ``repo_root`` is not inside a git working tree.

    For the main checkout this is ``repo_root/.git``; for a linked worktree
    (``git worktree add``) it is the **main checkout's** ``.git`` — the shared
    state git itself resolves a worktree's ledger/refs/objects against. Callers
    that need the main checkout root read this dir's parent
    (:func:`resolve_ledger_root` in ``harness.cli._repo``).

    ``git rev-parse --git-common-dir`` prints an already-absolute path when the
    common dir lies outside ``repo_root`` (the worktree case) and a
    ``repo_root``-relative one otherwise (the main-checkout case, ``.git``) — so
    a relative result is joined onto ``repo_root`` before resolving. Returns
    ``None`` on any non-zero exit (not a git repo, ``repo_root`` does not exist)
    so a non-git caller falls back to its pre-existing behaviour.
    """
    result = run_git(repo_root, "rev-parse", "--git-common-dir")
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    common_dir = Path(raw)
    if not common_dir.is_absolute():
        common_dir = repo_root / common_dir
    return common_dir.resolve()


def worktree_toplevel_matches(worktree_path: Path) -> bool:
    """True iff ``git -C worktree_path rev-parse --show-toplevel`` resolves
    back to ``worktree_path`` itself.

    The anchoring guard every probe that reads ``git`` state *at a worktree* needs
    first. Without it, a directory whose worktree registration was already pruned
    (or that never was a proper worktree) has ``git`` walk **up** and report the
    *main checkout's* state instead. Both existing callers rely on that:
    ``worktrees cleanup --merged``'s stash / dirty-tree vetoes (#235) would
    otherwise veto an orphaned directory whenever the operator's own tree happens
    to be dirty, and ``reclaim --stale``'s worktree-mtime signal (#254) would read
    the main checkout's index — almost always freshly edited — and so spare every
    stale ticket, silently switching the sweep off.

    Lives here rather than in either caller because reaching into a command
    module's private helper is exactly what the CLI module-boundary guard forbids,
    and a second copy of a check whose failure mode is "the feature silently
    stops working" is worse than a shared one.
    """
    proc = run_git(worktree_path, "rev-parse", "--show-toplevel")
    if proc.returncode != 0:
        return False
    try:
        return Path(proc.stdout.strip()).resolve() == worktree_path.resolve()
    except OSError:
        return False


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


def preferred_base_ref(repo_root: Path, base: str) -> str:
    """The most-current ref for ``base`` a reader should read: ``origin/<base>``
    when it resolves, else the local ``base`` branch (CAL-1154, Option 1).

    Since CAL-1154 ``close`` no longer advances the local ``<base>`` branch — it
    merges in a throwaway worktree and pushes ``origin/<base>``, which updates the
    local ``refs/remotes/origin/<base>`` tracking ref on the same machine with no
    fetch. So a reader that must see merged work — ``start`` basing a run worktree,
    ``worktrees cleanup --merged`` checking ancestry — reads ``origin/<base>``, not
    the local branch the merge no longer touches.

    Falls back to the local ``base`` when ``origin/<base>`` does not resolve — a
    repo with no ``origin`` remote, an offline clone, a fresh ``git init``, or the
    ``origin`` present but that branch never pushed — mirroring
    :func:`resolve_base_branch`'s fallback chain so those repos behave exactly as
    before. A local call, no timeout: it reads the already-fetched tracking ref
    (close's push keeps it current), never the network.
    """
    result = run_git(repo_root, "rev-parse", "--verify", "--quiet", f"origin/{base}")
    if result.returncode == 0:
        return f"origin/{base}"
    return base


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
