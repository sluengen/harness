"""The ``reclaim --stale`` liveness rule — the local signals that *spare* a run.

``reclaim --stale`` cannot observe whether a run's orchestrator is alive: it died
in an ephemeral container with no shared state, so liveness is unobservable and
time is the only signal (proposal ``stale-run-reclamation`` D2). The sweep
therefore reads clocks, and every clock it adds is **additive in one direction
only** — it can spare a run the other clocks would have reclaimed, never condemn
one they would have kept. That asymmetry is what lets the sweep stay safe in the
cloud regime, where none of the local signals are reachable at all.

Three signals, newest wins, evaluated in cost order (:mod:`harness.cli.reclaim`
owns the ordering; this module owns each signal):

1. **The tracker's ``updatedAt``** — the baseline every regime has. Read by the
   sweep itself, not here.
2. **The ledger's last activity** (#216) — ``max(runs.started_at,
   MAX(events.timestamp))`` for the ticket's open run. The tracker is *not* a
   heartbeat on the ``github`` backend: ``start`` transitions a ticket by writing
   the Projects-v2 *Status* field, an item-level mutation that leaves the issue's
   ``updatedAt`` alone, and ``checkpoint`` / ``design`` / ``review`` / ``close``
   never touch the issue at all.
3. **The worktree's newest tracked-file mtime** (#254) — what the session was
   actually *touching*. Signal 2 covers a run with no event **yet**; it does not
   cover a run whose last event has already aged past the threshold while the
   session keeps working. The observed case ran ``design``, implemented every
   acceptance criterion, then spent ~3h retrying a contended verify gate — zero
   commits, zero further events — so both clocks agreed the ticket looked
   abandoned and it was reclaimed out from under a live session.

Why *tracked* files, and not the cheaper primitives nearby:

* A **directory** mtime (what ``worktrees cleanup --age`` reads) tracks entries
  being created and removed, not edits to existing files — so it would have
  missed the exact observed case, a retry loop editing files in place.
* A **recursive walk** of the whole worktree is unbounded (``.git``,
  ``node_modules``, build output) and, worse, background git or tooling churn
  inside ``.git`` would make a genuinely dead worktree look alive — silently
  disabling the sweep. ``git ls-files`` bounds the scan to the index.
* **Dirtiness** (``git status --porcelain``) is not recency: a worktree left
  dirty by a run that died two days ago would be spared forever.

The accepted limit: a session whose only activity is an untracked, never-``git
add``ed file is still reclaimed. The index is what bounds the scan, and
``reclaim --undo`` (:mod:`harness.cli.reclaim_undo`) is the backstop.
"""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from harness._time import parse_iso_z
from harness.cli._git import run_git, worktree_toplevel_matches
from harness.state import store

__all__ = [
    "RunLiveness",
    "locally_live",
    "open_run_liveness",
    "worktree_last_activity",
]

#: Ceiling (seconds) for the ``git ls-files`` probe. Matches the bound
#: ``_git_worktree_branches`` puts on its own local ``git worktree list``: a local
#: call does not reach a remote, but the Build routine runs this sweep as a
#: pre-flight every tick, so a wedged git must degrade to "no opinion" rather
#: than hang the loop the sweep exists to unblock.
_LS_FILES_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class RunLiveness:
    """What the **local** ledger knows about a ticket's open run.

    Both fields come from one query. ``last_activity`` is signal 2
    (``max(runs.started_at, MAX(events.timestamp))``); ``worktree_path`` is the
    *address* of signal 3, ``None`` when the run recorded none.
    """

    last_activity: datetime
    worktree_path: Path | None


async def open_run_liveness(db_path: Path, ticket: str) -> RunLiveness | None:
    """The local signals for ``ticket``'s open run — or ``None`` for *no opinion*.

    ``None`` means the ledger has nothing to say: no DB (the cloud regime,
    proposal D3 — a fresh container never had the dead run's database) or no open
    run for this ticket. The caller then keys on the tracker timestamp alone,
    which is exactly the pre-#216 behaviour, so neither local signal can ever
    *condemn* a run the tracker-only path would have kept.

    ``started_at`` is load-bearing rather than a belt-and-braces extra — ``start``
    emits no event, so it is the **only** liveness signal a run has before its
    first ``design`` / ``checkpoint``.
    """
    if not db_path.exists():
        return None
    async with store.connect(db_path) as conn:
        cur = await conn.execute(
            "SELECT r.started_at, MAX(e.timestamp), r.worktree_path FROM runs r "
            "LEFT JOIN events e ON e.run_id = r.run_id "
            "WHERE r.ticket = ? AND r.status = 'open'",
            (ticket,),
        )
        row = await cur.fetchone()
    # The bare aggregate always yields one row; an all-NULL one means no open run
    # matched, which is the ledger having no opinion rather than a zero timestamp.
    if row is None or row[0] is None:
        return None
    stamps = [parse_iso_z(str(row[0]))]
    if row[1] is not None:
        stamps.append(parse_iso_z(str(row[1])))
    raw_path = row[2]
    return RunLiveness(
        last_activity=max(stamps),
        worktree_path=Path(str(raw_path)) if raw_path else None,
    )


def worktree_last_activity(worktree: Path) -> datetime | None:
    """Newest mtime among ``worktree``'s **tracked** files — or ``None``.

    Sync (it shells out and stats); call it through :func:`asyncio.to_thread`.
    Every failure mode collapses to ``None`` (*no opinion*, so the sweep falls
    back to the other signals) rather than raising, because this runs inside the
    Build routine's pre-flight: a probe that can wedge the loop is worse than a
    probe that occasionally has nothing to say.

    ``None`` is returned when the path is not a directory; when it is not itself a
    git top-level (see below); when ``git ls-files`` fails or times out; or when
    the index is empty.

    The top-level check is the load-bearing guard, not defensive padding. ``git``
    walks *up* from a directory whose worktree registration was pruned, so
    ``ls-files`` there would report the **main checkout's** index — whose files
    the operator is almost always editing — and the sweep would spare every stale
    ticket while looking like it still worked.
    """
    if not worktree.is_dir() or not worktree_toplevel_matches(worktree):
        return None
    try:
        proc = run_git(
            worktree, "ls-files", "-z", timeout=_LS_FILES_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.SubprocessError):
        # Includes TimeoutExpired: a wedged git is no opinion, not a failure.
        return None
    if proc.returncode != 0:
        return None
    newest: float | None = None
    # ``-z`` is NUL-terminated, so a newline in a tracked filename cannot forge a
    # second entry. The trailing separator yields one empty field — skip it.
    for name in proc.stdout.split("\0"):
        if not name:
            continue
        with contextlib.suppress(OSError):
            # A tracked path that is deleted or unreadable in the working tree is
            # simply not a signal; it must not abort the whole probe.
            mtime = (worktree / name).stat().st_mtime
            if newest is None or mtime > newest:
                newest = mtime
    if newest is None:
        return None
    return datetime.fromtimestamp(newest, tz=UTC)


async def locally_live(run: RunLiveness, cutoff: datetime) -> bool:
    """True iff either local signal puts ``run`` at or after ``cutoff``.

    The ledger is checked first because it is already in memory; the worktree
    probe (a subprocess plus a ``stat`` per tracked file) runs only when the
    ledger is stale *and* the run recorded a worktree path.
    """
    if run.last_activity >= cutoff:
        return True
    if run.worktree_path is None:
        return False
    activity = await asyncio.to_thread(worktree_last_activity, run.worktree_path)
    return activity is not None and activity >= cutoff
