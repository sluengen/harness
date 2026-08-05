"""``harness reclaim --undo`` — reverse a reclaim confirmed to be a false positive (#254).

``reclaim --stale`` presumes a run dead from time alone, because a dead run's
liveness is unobservable (proposal ``stale-run-reclamation`` D2). A presumption
can be wrong, and the observed case was: two live sessions were reverted out from
under themselves, and one had its finished work re-implemented by the session
that picked the "empty" ticket up. The staleness signals
(:mod:`harness.cli.reclaim_liveness`) narrow how often that happens; they cannot
make it impossible, so the reversal is the backstop.

Before this arm existed, recovery meant a hand-rolled ``git push`` plus a
hand-written tracker comment — bypassing the ledger, which is exactly what the
verb loop exists to prevent. Undo puts the reversal back inside the audit trail:

1. **Restore the ticket first**, mirroring reclaim's revert-first rule. The
   tracker is the substrate the next run actually reads, so if it fails the local
   row stays ``cancelled`` and a retry still sees work to undo. The three seam
   methods (``transition_to_in_progress`` / ``remove_label`` / ``post_comment``)
   already exist for ``start`` and ``release``, so **no backend method is added**
   and both Linear and GitHub are served unchanged. All three are idempotent, so
   a retry after a partial failure is safe.
2. **Re-open the run row second**, in one transaction shaped like
   :mod:`harness.cli._abandon`'s: guard on the observed ``cancelled`` status,
   flip to ``open``, clear ``completed_at``, and append the ``reclaim_undone``
   event — commit together or roll back together.

The worktree needs no restoration: reclaim never pruned it (proposal D4).

**Bounded authority.** Undo re-opens only a run it can *prove* was
reclaim-cancelled — ``status='cancelled'`` **and** a ``workflow_failed`` event
carrying ``reason='reclaimed'``. A run abandoned by ``harness cancel`` is an
intentional decision, not a false positive, and is refused. And when the ticket
already carries another ``open`` run — the observed duplicate-session shape —
undo **refuses** rather than arbitrating: the competing session may hold real
work, so the operator cancels it first. That refusal is checked before any write,
so a refused undo touches nothing.

**Why a flag on ``reclaim`` and not a ``harness unreclaim`` verb.** A new
registered command costs the locked CLI surface, SPEC §11, ``cli-surface.md`` and
the agent contract, for a path that is definitionally the inverse of one existing
verb. One verb keeps owning reclamation state.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
from pydantic import BaseModel

from harness._time import iso_z
from harness.cli._verb import VerbError
from harness.events.payloads import ReclaimUndoneEventData
from harness.reclaim_marker import RECLAIM_LABEL, format_unreclaim_comment
from harness.state import store
from harness.tracker import tracker_client
from harness.tracker_errors import (
    TrackerConfigError,
    TrackerNotFound,
    TrackerRequestError,
)

__all__ = [
    "UNDO_EVENT_TYPE",
    "ReclaimUndoOutput",
    "run_undo",
]

#: The event a completed reversal appends. Its *presence* is also how undo tells
#: an ``already_undone`` no-op from a run that was simply never cancelled — an
#: ``open`` status alone cannot distinguish the two.
UNDO_EVENT_TYPE = "reclaim_undone"

#: The abandon reason that marks a cancellation as a *reclamation* rather than a
#: deliberate ``harness cancel``. Only this is undoable.
_RECLAIMED_REASON = "reclaimed"


class ReclaimUndoOutput(BaseModel):
    """``--undo`` result. ``run_id`` is ``None`` for a tracker-only reversal."""

    mode: str = "undo"
    run_id: str | None
    ticket: str
    outcome: str


class _UndoError(VerbError):
    """``--undo``'s control-flow exception, carrying a machine-readable ``reason``."""


async def _abandon_reason(conn: aiosqlite.Connection, run_id: str) -> str | None:
    """The reason on the run's newest ``workflow_failed`` event, or ``None``.

    Newest wins because a run can be reclaimed, undone, and reclaimed again: the
    *current* cancellation is what undo is reversing, and an older event must not
    speak for it.
    """
    cur = await conn.execute(
        "SELECT json_extract(data_json, '$.reason') FROM events "
        "WHERE run_id = ? AND event_type = 'workflow_failed' "
        "ORDER BY timestamp DESC, id DESC LIMIT 1",
        (run_id,),
    )
    row = await cur.fetchone()
    return None if row is None or row[0] is None else str(row[0])


async def _has_undo_event(conn: aiosqlite.Connection, run_id: str) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM events WHERE run_id = ? AND event_type = ? LIMIT 1",
        (run_id, UNDO_EVENT_TYPE),
    )
    return await cur.fetchone() is not None


async def _competing_open_run(
    conn: aiosqlite.Connection, ticket: str, run_id: str
) -> str | None:
    """Another ``open`` run on the same ticket — the id, or ``None``.

    ``idx_runs_ticket_open`` is the authoritative guard (the re-open would raise
    against it); this read produces the named refusal instead of a raw integrity
    error, and lets the refusal land *before* any tracker write.
    """
    cur = await conn.execute(
        "SELECT run_id FROM runs WHERE ticket = ? AND status = 'open' "
        "AND run_id != ? LIMIT 1",
        (ticket, run_id),
    )
    row = await cur.fetchone()
    return None if row is None else str(row[0])


class _Target(BaseModel):
    """A resolved undo target. ``run_id`` ``None`` → tracker-only reversal."""

    run_id: str | None
    ticket: str
    already_undone: bool = False


async def _resolve_by_run_id(conn: aiosqlite.Connection, run_id: str) -> _Target:
    cur = await conn.execute(
        "SELECT status, ticket FROM runs WHERE run_id = ?", (run_id,)
    )
    row = await cur.fetchone()
    if row is None:
        raise _UndoError(f"no run with run_id={run_id!r}", 2, reason="unknown_run")
    status, ticket = str(row[0]), row[1]
    if not ticket:
        raise _UndoError(
            f"run {run_id!r} has no associated ticket; there is nothing to restore",
            2,
            reason="unknown_run",
        )
    ticket = str(ticket)

    if status != "cancelled":
        # An already-``open`` run is 'not cancelled' too, so the idempotent no-op
        # is distinguished on *evidence* — a recorded prior reversal — rather than
        # on status alone. Without that, undoing a perfectly live run would report
        # success while doing nothing.
        if status == "open" and await _has_undo_event(conn, run_id):
            return _Target(run_id=run_id, ticket=ticket, already_undone=True)
        raise _UndoError(
            f"run {run_id!r} is {status!r}, not a reclaimed run; only a run "
            "cancelled by `harness reclaim` can be undone",
            2,
            reason="not_reclaimed",
        )

    reason = await _abandon_reason(conn, run_id)
    if reason != _RECLAIMED_REASON:
        detail = (
            f"its cancellation reason is {reason!r}"
            if reason is not None
            else "it carries no abandonment event"
        )
        raise _UndoError(
            f"run {run_id!r} was not reclaimed ({detail}); a deliberate "
            "`harness cancel` is not a false positive",
            2,
            reason="not_reclaimed",
        )
    return _Target(run_id=run_id, ticket=ticket)


async def _resolve_by_ticket(conn: aiosqlite.Connection, ticket: str) -> _Target:
    """The ticket's newest cancelled run, validated by the same gate as a run-id.

    Selects the newest **cancelled** run and then delegates to
    :func:`_resolve_by_run_id`, so the "is this a reclamation?" question is asked
    in exactly one place. Selecting instead on *"has a reclaimed event anywhere in
    its history"* would be a way around the bounded-authority rule: a run that was
    reclaimed, undone, and then deliberately cancelled still carries the old
    ``reclaimed`` event, so a history-wide match would re-open something the
    operator chose to abandon. Only the **newest** abandon reason speaks for the
    current cancellation.

    Choosing the newest cancelled run — rather than the newest *reclaimed* one —
    is what makes that delegation meaningful: it refuses when the ticket's current
    state came from a deliberate ``cancel``, instead of silently reaching past it
    to an older reclamation. Naming the run directly stays available for that case.

    With no cancelled run at all the target is tracker-only (the cloud regime,
    mirroring reclaim's revert-only arm).
    """
    cur = await conn.execute(
        "SELECT run_id FROM runs WHERE ticket = ? AND status = 'cancelled' "
        "ORDER BY completed_at DESC, started_at DESC LIMIT 1",
        (ticket,),
    )
    row = await cur.fetchone()
    if row is None:
        return _Target(run_id=None, ticket=ticket)
    return await _resolve_by_run_id(conn, str(row[0]))


async def _restore_ticket(
    ticket: str, run_id: str | None, *, repo_root: Path
) -> None:
    """Ticket → In Progress, drop the ``reclaimed`` label, post the correction."""
    try:
        client = tracker_client(repo_root)
    except TrackerConfigError as exc:
        raise _UndoError(str(exc), 2, reason="tracker_config") from exc

    # Reached only in the has-tracker path, so a real client is resolved here.
    assert client is not None
    try:
        await client.transition_to_in_progress(ticket)
        await client.remove_label(ticket, RECLAIM_LABEL)
        await client.post_comment(
            ticket, format_unreclaim_comment(run_id, when=iso_z())
        )
    except TrackerNotFound as exc:
        raise _UndoError(
            f"ticket {ticket!r} not found on the tracker: {exc}",
            2,
            reason="ticket_not_found",
        ) from exc
    except TrackerRequestError as exc:
        raise _UndoError(
            f"failed to restore ticket {ticket!r} on the tracker: {exc}",
            2,
            reason="tracker_error",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise _UndoError(
            f"unexpected error restoring ticket {ticket!r}: {exc}", 1
        ) from exc


async def _reopen_in_ledger(
    conn: aiosqlite.Connection, run_id: str, ticket: str
) -> None:
    """Flip ``cancelled → open`` and append the reversal event, in one transaction.

    Shaped exactly like :func:`harness.cli._abandon.abandon_run_in_ledger`, and for
    the same reason: a row re-opened without its ``reclaim_undone`` event is an
    inconsistent ledger a retry cannot repair, because the run no longer looks
    reclaimed and every later undo would refuse it.
    """
    event_data = ReclaimUndoneEventData(
        run_id=run_id, ticket=ticket, undone_at=iso_z()
    ).model_dump_json()

    await conn.execute("BEGIN IMMEDIATE")
    try:
        # Optimistic concurrency on the exact status observed: if a concurrent
        # close/cancel/start raced in, zero rows change and we refuse rather than
        # overwrite. The ``NOT EXISTS`` clause re-checks the competing-open-run
        # condition inside the transaction, so the pre-check's friendly message
        # and this authoritative guard cannot disagree under a race.
        update = await conn.execute(
            "UPDATE runs SET status = 'open', completed_at = NULL "
            "WHERE run_id = ? AND status = 'cancelled' AND NOT EXISTS ("
            "SELECT 1 FROM runs o WHERE o.ticket = ? AND o.status = 'open' "
            "AND o.run_id != ?)",
            (run_id, ticket, run_id),
        )
        if update.rowcount == 0:
            raise _UndoError(
                f"run {run_id!r} could not be re-opened: it changed state "
                f"concurrently, or another open run appeared on ticket {ticket!r}",
                2,
                reason="ticket_has_open_run",
            )
        await conn.execute(
            "INSERT INTO events (run_id, node_id, event_type, timestamp, "
            "duration_ms, data_json) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, None, UNDO_EVENT_TYPE, iso_z(), None, event_data),
        )
        await conn.commit()
    except _UndoError:
        await conn.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        await conn.rollback()
        raise _UndoError(f"failed to record the reversal: {exc}", 1) from exc


async def run_undo(
    db_path: Path,
    run_id_arg: str | None,
    ticket_arg: str | None,
    *,
    repo_root: Path,
    tracker: bool = True,
) -> ReclaimUndoOutput:
    """Reverse the resolved reclaim; raise :class:`_UndoError` on refusal/error.

    ``tracker`` is ``False`` only for ``tracker: none``, where there is no ticket
    state to restore and undo reduces to its local half.
    """
    if (run_id_arg is None) == (ticket_arg is None):
        raise _UndoError(
            "provide exactly one of <run-id> or --ticket <ID>",
            2,
            reason="ambiguous_selector",
        )

    # --- Read-only preconditions. No writes yet, so a refusal here changes
    #     nothing at all — which is what lets the competing-open-run check happen
    #     before the tracker is touched.
    target = _Target(run_id=None, ticket=str(ticket_arg))
    if db_path.exists():
        async with store.connect(db_path) as conn:
            if run_id_arg is not None:
                target = await _resolve_by_run_id(conn, run_id_arg)
            else:
                assert ticket_arg is not None
                target = await _resolve_by_ticket(conn, ticket_arg)
            if target.run_id is not None and not target.already_undone:
                competing = await _competing_open_run(
                    conn, target.ticket, target.run_id
                )
                if competing is not None:
                    raise _UndoError(
                        f"ticket {target.ticket!r} already has an open run "
                        f"({competing}); cancel it before undoing {target.run_id} — "
                        "undo will not choose between two sessions",
                        2,
                        reason="ticket_has_open_run",
                    )
    elif run_id_arg is not None:
        # A run-id selector names a specific local row; with no ledger there is
        # nothing to name. (``--ticket`` legitimately degrades to tracker-only.)
        raise _UndoError(
            f"no run with run_id={run_id_arg!r}", 2, reason="unknown_run"
        )

    if target.already_undone:
        return ReclaimUndoOutput(
            run_id=target.run_id, ticket=target.ticket, outcome="already_undone"
        )

    # --- 1. Restore the ticket FIRST (see the module docstring).
    if tracker:
        await _restore_ticket(target.ticket, target.run_id, repo_root=repo_root)

    # --- 2. Re-open the run row SECOND, when there is one to re-open.
    if target.run_id is None:
        return ReclaimUndoOutput(
            run_id=None, ticket=target.ticket, outcome="unreverted"
        )
    async with store.connect(db_path) as conn:
        await _reopen_in_ledger(conn, target.run_id, target.ticket)
    return ReclaimUndoOutput(
        run_id=target.run_id, ticket=target.ticket, outcome="undone"
    )


def describe(result: ReclaimUndoOutput) -> str:
    """The human (non-``--json``) summary line for a reversal."""
    if result.outcome == "already_undone":
        return (
            f"Run {result.run_id} already un-reclaimed (no-op); "
            f"ticket {result.ticket} left as-is"
        )
    if result.outcome == "unreverted":
        return (
            f"Restored ticket {result.ticket} to In Progress and dropped the "
            f"`{RECLAIM_LABEL}` label (no local run to re-open)"
        )
    return (
        f"Undid the reclaim of run {result.run_id} — ticket {result.ticket} is "
        "In Progress again and the run is re-opened"
    )
