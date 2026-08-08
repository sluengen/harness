"""The throwaway probe tree, and the run worktree's identity check (#363).

``harness review``'s probe stage needs somewhere to apply a reviewer-proposed
mutation. That somewhere is a ``git worktree add --detach`` at the reviewed SHA —
**not** a copy — and the choice buys three properties by construction rather than
by configuration:

* the probe tree is provably at the SHA under review, so a mutation is applied to
  the code the verdict will be bound to;
* the reviewed worktree is untouched because nothing ever writes to it, rather
  than because something was told not to;
* the probe tree starts **clean**, which matters because a polluted run worktree
  is the known cause of the review hang :mod:`harness.cli.review_pollution`
  exists to refuse.

It sits at the package root beside :mod:`harness.close_merge`, which set the
precedent for verb-adjacent git mechanics: ``close`` merges in a detached
throwaway worktree by the same reasoning, and the general probe callback that may
follow this change reuses the tree without wanting the review protocol.

The identity check
------------------

Granting the reviewer a way to cause execution removes a defence that was
previously absolute — the engine could not write at all. What remains is
``close``'s two conjuncts (a pass bound to current HEAD, **and** a refusal of a
dirty worktree), so the failure mode of a misbehaving prober is a **wedged run,
not a laundered merge**. That is a better property than it looks, and this module
must not weaken it.

:func:`snapshot_tree` exists so the wedge surfaces *where it happened* rather than
at the end of the run. Be plain about what it is: it detects what **git can see**
— a tracked edit, a deletion, an untracked addition, HEAD moving — and not a
write inside a gitignored path. It is a detector at the boundary; ``close``
remains the boundary. That is the same honesty ``design``'s single-file write
grant states about itself ("an agent-layer control, not a filesystem boundary").
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from harness._git import run_git, teardown_worktree
from harness.worktree import worktree_path

__all__ = [
    "PROBE_WORKTREE_SUFFIX",
    "ProbeTreeError",
    "create_probe_tree",
    "snapshot_tree",
    "teardown_probe_tree",
]

#: Sibling of ``close``'s ``-close``: inside the area
#: :func:`harness._git.teardown_worktree` guards, and distinct from the run's own
#: worktree so no sweep can confuse the two.
PROBE_WORKTREE_SUFFIX = "-probe"


class ProbeTreeError(Exception):
    """The probe tree could not be created. The stage degrades; it never wedges."""


def create_probe_tree(repo_root: Path, run_id: str, reviewed_sha: str) -> Path:
    """Create the detached probe worktree at ``reviewed_sha``.

    Reclaims a leftover at the same path rather than refusing: a previous
    review's scratch tree whose teardown failed must not wedge the next review.
    Writes relative worktree pointers (git ≥ 2.48) so the path resolves
    identically on the host and under the container mount (CAL-866).

    Raises :class:`ProbeTreeError` on failure, leaving no half-created directory.
    """
    path = worktree_path(repo_root, f"{run_id}{PROBE_WORKTREE_SUFFIX}")
    if path.exists():
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
        reviewed_sha,
    )
    if result.returncode != 0:
        if path.exists():
            teardown_worktree(repo_root, worktree_path=path, branch=None)
        raise ProbeTreeError(
            f"failed to create the probe worktree at {path}: {result.stderr.strip()}"
        )
    return path


def teardown_probe_tree(repo_root: Path, path: Path) -> None:
    """Remove the probe tree — best-effort, never raises.

    Called from a ``finally`` on every path, including ones where the tree was
    never created, so it tolerates an absent directory. Detached, so there is no
    branch to delete.
    """
    teardown_worktree(repo_root, worktree_path=path, branch=None, delete_remote=False)


def snapshot_tree(worktree: Path) -> str | None:
    """A digest of everything git can see about ``worktree``'s working state.

    ``git status --porcelain -z --untracked-files=all`` plus ``git rev-parse
    HEAD``. Both halves are needed and neither is redundant: the porcelain sees
    an uncommitted edit that leaves HEAD alone, and HEAD sees a *clean commit*
    that leaves the porcelain empty. A check on either alone has a hole shaped
    like the other.

    ``None`` when git cannot answer — not a repository, a wedged index, a path
    that vanished. The caller then **skips** the comparison rather than reading a
    failed probe as a mismatch: fail-open is the same asymmetry every other
    measurement ``review`` makes about a tree it did not create, and a guard that
    stops a run may rest only on evidence it actually gathered.
    """
    status = run_git(worktree, "status", "--porcelain", "-z", "--untracked-files=all")
    if status.returncode != 0:
        return None
    head = run_git(worktree, "rev-parse", "HEAD")
    if head.returncode != 0:
        return None
    digest = hashlib.sha256()
    digest.update(head.stdout.strip().encode("utf-8"))
    digest.update(b"\x00")
    digest.update(status.stdout.encode("utf-8"))
    return digest.hexdigest()
