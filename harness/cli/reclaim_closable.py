"""The ``reclaim --stale`` *closable* rule — a stranded run that was only unfinished.

A run that passed ``review`` and then lost its session is still ``status='open'``,
and ``close`` has no spend breaker — so it was closable in place the whole time
(proposal ``resume-earned-stages`` F3). Reverting it to Todo throws away a
passing review and forces a fresh run to re-design and re-review to reach a
``close`` that was one command away. The sweep, keying on time alone, is what
converts a finishable run into a re-pickable one.

This module answers one question: *would ``close`` accept this run right now?*
It stays a **classifier** — it merges nothing, writes nothing, and mutates no
tracker state. Draining the classification is #256's job.

**Alive outranks finished.** :mod:`harness.cli.reclaim` checks
:func:`~harness.cli.reclaim_liveness.locally_live` *first*, so a live session
paused at a clean, previously-passed HEAD reads as ``skipped``, never
``closable``. The two answers mean opposite things downstream — *spared because
alive* must not be drained, *closable because finished* must be — and getting
that order wrong is what would turn a misclassification into a merge out from
under a working session (proposal risk section).

**Every uncertainty resolves to "not closable"**, i.e. to reclaiming as today.
Nothing here raises: the sweep is the Build routine's pre-flight, and a probe
that wedges the loop is worse than a redundant reclaim. That asymmetry is also
why the classification is safe as a *prediction* — ``close`` re-resolves HEAD,
re-checks the tree and re-runs the gate at execution time, so a session that
commits between the sweep and the close is refused ``stale_review`` rather than
merged. The report never authorizes anything.
"""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path

from harness import close_merge
from harness.cli._git import GitError, rev_parse_head, worktree_toplevel_matches
from harness.cli._review_gate import certify_head
from harness.cli.reclaim_liveness import RunLiveness

__all__ = ["ClosableRun", "closable_run"]

#: Ceiling (seconds) for both git probes. The twin of
#: :data:`harness.cli.reclaim_liveness._LS_FILES_TIMEOUT_SECONDS`, for the same
#: reason: this runs unattended every tick, so a wedged git must degrade to "not
#: closable" rather than hang the loop.
_PROBE_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class ClosableRun:
    """A run whose recorded review certifies the exact tree its worktree holds.

    Deliberately *not* ``reclaim.ClosableEntry``: :mod:`harness.cli.reclaim`
    imports this module, so this module must not import back. It reports the two
    facts only it can resolve; the caller adds the ticket it already holds.
    """

    run_id: str
    head_sha: str


def _probe_head_of_clean_worktree(worktree: Path) -> str | None:
    """The HEAD SHA of ``worktree`` iff it is its own git top-level *and* clean.

    Sync (it shells out); call it through :func:`asyncio.to_thread`.

    Two divergences from what ``close`` itself does, both strictly conservative —
    a divergence may only ever make this answer *not closable*:

    * **The top-level guard is extra.** ``close`` does not apply it, because it
      resolves a worktree it is actively driving. Here a pruned-but-present
      directory would make git walk *up* and report the **enclosing checkout's**
      HEAD — a false-positive shape, and the same trap
      :func:`~harness.cli._git.worktree_toplevel_matches` exists for (#235/#254).
    * **The probes are bounded**; ``close``'s are not.

    The clean-tree check is not extra: it is ``close``'s own second gate conjunct
    (refusal ``dirty_worktree``), and it is reachable here — a run that passed
    review and then died leaving an uncommitted edit has a HEAD-matching,
    gate-evidenced pass and a tree ``close`` will reject. Without it that ticket
    would be neither reclaimed nor closable, which is the one outcome worse than
    either.
    """
    if not worktree.is_dir() or not worktree_toplevel_matches(worktree):
        return None
    try:
        head = rev_parse_head(worktree, timeout=_PROBE_TIMEOUT_SECONDS)
        # A dirty tree is not a *failed* probe — it is a definite "no".
        if close_merge.worktree_porcelain(worktree, timeout=_PROBE_TIMEOUT_SECONDS):
            return None
    except (
        GitError,
        close_merge.CloseMergeError,
        OSError,
        subprocess.SubprocessError,
    ):
        # Includes TimeoutExpired. A probe that cannot answer has no opinion,
        # and no opinion means reclaim as today.
        return None
    return head or None


async def closable_run(db_path: Path, run: RunLiveness) -> ClosableRun | None:
    """``run`` iff ``close`` would accept it right now — else ``None``.

    ``run`` is the row the sweep has already read, so conditions "the ledger is
    reachable" and "an open run exists for this ticket" are satisfied by having a
    :class:`~harness.cli.reclaim_liveness.RunLiveness` at all. What remains: the
    worktree resolves to a clean tree at some HEAD, and the ledger certifies that
    HEAD.

    ``worktree_path`` is consumed **verbatim**, never rebased onto the repo root.
    It is recorded container-absolute (``/workspace/…``), so a predicate that
    rewrote it would resolve a different tree than the one ``close`` will merge —
    the one thing it must not do. Host-side the path simply does not resolve, the
    answer is *not closable*, and behaviour is today's (proposal risk section).
    """
    if run.worktree_path is None:
        return None
    head = await asyncio.to_thread(_probe_head_of_clean_worktree, run.worktree_path)
    if head is None:
        return None
    certification = await certify_head(db_path, run.run_id, head)
    if not certification.certified:
        return None
    return ClosableRun(run_id=run.run_id, head_sha=head)
