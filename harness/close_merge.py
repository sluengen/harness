"""Close merge mechanics — the deterministic git half of ``harness close`` (CAL-1154).

``harness close`` (:mod:`harness.cli.close`) is the audited orchestration — the
gate, the ledger transaction, the tracker transition; this module is its
**mechanics**, the close analogue of :mod:`harness.promotion` for promotions. It
owns only git: how a run branch is integrated onto the base and pushed.

The shape is the one :mod:`harness.promotion` already landed and that this ticket
brings ``close`` into line with — **the merge runs in a throwaway worktree, never
the main checkout**:

* :func:`worktree_porcelain` — the run worktree's ``git status --porcelain``, the
  clean-tree gate ``close`` enforces before any side effect (a dirty run worktree
  holds edits HEAD never saw, so the passing review never covered them).
* :func:`merge_run_branch` — fetch ``origin/<base>``, create a **detached**
  throwaway worktree at that tip under ``.worktrees/harness/<run_id>-close``, merge
  the run branch into it, push the merge commit to ``origin/<base>``, and remove
  the worktree wholesale. A conflict tears the worktree down and is reported with a
  clear message — no ``git merge --abort`` on a shared tree, because there is no
  shared tree.

Because a close never checks out the base in the main tree, the main checkout is
byte-identical before and after every close (success or refusal), two concurrent
closes cannot corrupt a shared working tree (each has its own throwaway; the
loser's push is rejected non-fast-forward and it retries), and there is no local
``<base>`` ref to advance — close's push updates ``refs/remotes/origin/<base>`` on
the same machine, which is what the ``start`` / ``worktrees cleanup`` readers now
base off (Option 1, proposal ``close-merge-in-throwaway-worktree.md``).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal

from harness._git import NETWORK_GIT_TIMEOUT_SECONDS, run_git, teardown_worktree
from harness.worktree import worktree_path

__all__ = [
    "CloseMergeError",
    "CloseMergeReason",
    "merge_run_branch",
    "worktree_porcelain",
]

#: The machine-readable failure vocabulary this module raises — named once, here,
#: where the raise sites are, so ``close`` can propagate a reason rather than
#: recompute one (#300). Every ``reason=`` on a :class:`CloseMergeError`
#: construction in this module must be a literal member: mypy strict enforces it
#: for the package, and ``test_close_merge_reason_propagation.py`` enforces it
#: against the source text, so a computed reason cannot slip past unnoticed.
#:
#: The set is deliberately disjoint from ``close``'s ticket-transition reasons.
#: That asymmetry is load-bearing: a member of this vocabulary means the merge
#: did **not** land, while a ticket-transition reason means it did.
CloseMergeReason = Literal[
    "git_status_failed",
    "network_timeout",
    "fetch_failed",
    "merge_conflict",
    "merge_failed",
    "push_rejected",
    "worktree_create_failed",
]

#: The suffix appended to a run id to name its throwaway close-merge worktree, so
#: it is distinct from the run's own ``.worktrees/harness/<run_id>`` worktree and
#: still lives inside the ``.worktrees/harness/`` area ``teardown_worktree`` guards.
_CLOSE_WORKTREE_SUFFIX = "-close"


class CloseMergeError(RuntimeError):
    """A close merge mechanic failed.

    Carries a machine-readable ``reason`` (mirroring
    :class:`harness.promotion.PromotionMechanicsError`) and a ``conflict`` flag so
    the ``close`` verb can map the failure to its own control-flow exception and
    message. A ``conflict`` is a genuine merge conflict between the reviewed run
    branch and changes that landed on ``origin/<base>`` during the run — the run
    stays resumable; every other reason is a git or push failure.
    """

    def __init__(
        self, message: str, *, reason: CloseMergeReason, conflict: bool = False
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.conflict = conflict


def worktree_porcelain(worktree: Path, *, timeout: float | None = None) -> str:
    """Return ``git status --porcelain`` for ``worktree`` (stripped).

    A non-empty result means the run worktree has uncommitted changes (staged,
    unstaged, or untracked). Raises :class:`CloseMergeError`
    (``reason='git_status_failed'``) on a git failure so the caller reports an
    error, not a false-clean.

    ``timeout`` is forwarded to :func:`run_git` and defaults to ``None``, leaving
    ``close``'s interactive call unchanged; ``reclaim --stale``'s closable
    predicate bounds it, because that probe runs unattended every tick (#255).
    A fired :class:`subprocess.TimeoutExpired` propagates rather than reading as
    a clean tree — the caller's guard decides, and its answer is *not closable*.
    """
    result = run_git(worktree, "status", "--porcelain", timeout=timeout)
    if result.returncode != 0:
        raise CloseMergeError(
            f"git status failed for {worktree}: {result.stderr.strip()}",
            reason="git_status_failed",
        )
    return result.stdout.strip()


def merge_run_branch(
    *,
    repo_root: Path,
    run_id: str,
    base_branch: str,
    worktree_branch: str,
) -> str:
    """Integrate ``origin/<base>``, merge the run branch, push — all off the main tree.

    The sequence, none of it touching the main checkout:

    1. ``git fetch origin <base>`` into ``FETCH_HEAD`` — the current remote tip,
       so a base that advanced during the run is integrated (CAL-777).
    2. Create a **detached** throwaway worktree at that tip under
       ``.worktrees/harness/<run_id>-close`` (a detached worktree sidesteps git's
       refusal to check out a branch already checked out in the main tree).
    3. ``git merge --no-ff <run-branch>`` into it. Clean → its HEAD is the merge
       commit. Conflict → the worktree is torn down wholesale and a clear
       :class:`CloseMergeError` (``conflict=True``) is raised — the run stays
       resumable (its own worktree and passing review untouched).
    4. ``git push origin HEAD:<base>``. On success this advances
       ``refs/remotes/origin/<base>`` locally, so the next reader sees the merged
       work with no fetch. A push rejected non-fast-forward (a concurrent close
       won the race) raises ``reason='push_rejected'`` — the loser fails cleanly
       and retryably; a retry re-fetches the winner's tip.

    The throwaway worktree is **always** removed (``finally``), on every path.
    Returns the concatenated git output for the caller to log (never printed —
    context economy). Raises :class:`CloseMergeError` on any git/push failure.
    """
    output: list[str] = []

    def _run_network(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        # fetch/push reach a remote and can hang; a fired timeout raises rather
        # than returning non-zero, so convert it to the same CloseMergeError shape
        # the caller handles (never a raw traceback) — mirrors close's old guard.
        try:
            return run_git(cwd, *args, timeout=NETWORK_GIT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise CloseMergeError(
                f"git {' '.join(args)} exceeded the {NETWORK_GIT_TIMEOUT_SECONDS}s "
                f"network timeout in {cwd}; the remote may be unreachable — retry "
                "close once it is back",
                reason="network_timeout",
            ) from exc

    # 1. Fetch the current origin/<base> tip.
    fetch = _run_network(repo_root, "fetch", "origin", base_branch)
    output += [fetch.stdout, fetch.stderr]
    if fetch.returncode != 0:
        raise CloseMergeError(
            f"git fetch origin {base_branch} failed in {repo_root}: "
            f"{fetch.stderr.strip()}",
            reason="fetch_failed",
        )
    tip = run_git(repo_root, "rev-parse", "FETCH_HEAD")
    if tip.returncode != 0:
        raise CloseMergeError(
            f"cannot resolve the fetched origin/{base_branch} tip in {repo_root}: "
            f"{tip.stderr.strip()}",
            reason="fetch_failed",
        )
    base_tip = tip.stdout.strip()

    # 2. Create the detached throwaway worktree at that tip.
    worktree = _create_merge_worktree(repo_root, run_id, base_tip=base_tip)
    try:
        # 3. Merge the reviewed run branch into it.
        merge = run_git(
            worktree, "merge", "--no-ff", worktree_branch, "-m", f"Merge {worktree_branch}"
        )
        output += [merge.stdout, merge.stderr]
        if merge.returncode != 0:
            if _has_unmerged_paths(worktree):
                # A genuine conflict with changes that landed on origin/<base>
                # during the run. Tearing down the whole worktree replaces the
                # main-checkout ``git merge --abort`` — nothing shared was touched.
                raise CloseMergeError(
                    f"cannot merge {worktree_branch} into {base_branch}: it conflicts "
                    f"with changes that landed on origin/{base_branch} during the run. "
                    f"close integrates origin/{base_branch} itself, so nothing already "
                    f"on {worktree_branch} needs rewriting: merge origin/{base_branch} "
                    f"into {worktree_branch}, commit the resolution, re-review (the "
                    f"resolution moved HEAD), and close again",
                    reason="merge_conflict",
                    conflict=True,
                )
            raise CloseMergeError(
                f"cannot merge {worktree_branch} into {base_branch}: git refused to "
                f"start the merge in {worktree}: {merge.stderr.strip()}",
                reason="merge_failed",
            )

        # 4. Push the merge commit to origin/<base>.
        push = _run_network(worktree, "push", "origin", f"HEAD:{base_branch}")
        output += [push.stdout, push.stderr]
        if push.returncode != 0:
            raise CloseMergeError(
                f"cannot push {base_branch}: origin/{base_branch} advanced while "
                f"this close was merging (a concurrent close landed first), so the "
                f"push was rejected. The run is untouched — close again to re-fetch "
                f"and retry:\n{push.stderr.strip()}",
                reason="push_rejected",
            )
    finally:
        # The throwaway worktree has served its purpose on every path — merged,
        # conflicted, or push-rejected. Remove it wholesale (best-effort; never
        # raises). It is detached, so there is no branch to delete.
        teardown_worktree(
            repo_root, worktree_path=worktree, branch=None, delete_remote=False
        )

    return "".join(output)


def _create_merge_worktree(repo_root: Path, run_id: str, *, base_tip: str) -> Path:
    """Create the detached throwaway close-merge worktree at ``base_tip``.

    At ``.worktrees/harness/<run_id>-close`` — inside the area
    :func:`harness._git.teardown_worktree` guards, distinct from the run's own
    worktree. Detached (no branch), so a concurrent base branch already checked out
    in the main tree is no obstacle. Writes relative worktree pointers (git ≥ 2.48)
    so the path resolves identically on host and in the container (CAL-866). Raises
    :class:`CloseMergeError` (``reason='worktree_create_failed'``) on failure,
    leaving no half-created directory behind.
    """
    path = worktree_path(repo_root, f"{run_id}{_CLOSE_WORKTREE_SUFFIX}")
    if path.exists():
        # A previous close attempt's throwaway survived (its teardown failed).
        # Reclaim it before reusing the path rather than refuse — a close must not
        # wedge on its own leftover scratch worktree.
        teardown_worktree(repo_root, worktree_path=path, branch=None)
    path.parent.mkdir(parents=True, exist_ok=True)
    result = run_git(
        repo_root,
        "-c",
        "worktree.useRelativePaths=true",
        "worktree",
        "add",
        "--detach",
        str(path),
        base_tip,
    )
    if result.returncode != 0:
        if path.exists():
            teardown_worktree(repo_root, worktree_path=path, branch=None)
        raise CloseMergeError(
            f"failed to create the close-merge worktree at {path}: "
            f"{result.stderr.strip()}",
            reason="worktree_create_failed",
        )
    return path


def _has_unmerged_paths(worktree: Path) -> bool:
    """Whether ``worktree`` has unmerged (conflicted) paths — a real content conflict.

    ``git diff --name-only --diff-filter=U`` naming any file means the merge hit a
    content conflict (as opposed to git refusing to start it — e.g. unrelated
    histories — which leaves no unmerged paths).
    """
    result = run_git(worktree, "diff", "--name-only", "--diff-filter=U")
    if result.returncode != 0:
        return False
    return any(line.strip() for line in result.stdout.splitlines())
