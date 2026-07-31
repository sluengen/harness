"""``harness reclaim`` — reclaim a run whose orchestrator died (CAL-735 + CAL-736).

Breakdown items 2 + 3 of the accepted proposal ``stale-run-reclamation``. When the
Claude session driving a run stops without finishing (usage limit, crash,
container timeout) it strands three pieces of state: a Linear ticket stuck *In
Progress*, an ``open`` ``runs`` row, and a git worktree/branch. ``harness
cancel`` flips only the local row — it never touches Linear, so the ticket stays
In Progress and every dependent stays blocked. ``reclaim`` is the one auditable
verb that reverts the ticket and reconciles the local ledger.

What it does:

1. **Revert the Linear ticket first.** Linear is the substrate the next run
   actually reads (the proposal's load-bearing insight), so above all the ticket
   must move: ``transition_to_unstarted`` (→ Todo), ``apply_label('reclaimed')``,
   and a comment naming when it was reclaimed and the preserved branch ref. This
   runs *before* the local reconcile so that if Linear fails the run stays
   in-flight and a retry still sees work to reclaim.
2. **Reconcile the local ledger second.** In one transaction (the same one
   ``cancel`` uses — :mod:`harness.cli._abandon`) flip the matching ``open`` run
   to ``cancelled`` + stamp ``completed_at`` + emit ``workflow_failed`` with
   ``reason='reclaimed'``, so ``idx_runs_ticket_open`` no longer blocks a fresh
   ``harness start`` on that ticket.
3. **Preserve the branch.** Proposal D4 — reclaim never prunes the worktree or
   branch; the work is kept for a later resume (CAL-739). The comment names the
   branch as resumable **only when it was checkpoint-pushed** (a ``checkpoint``
   event exists, CAL-738) — a run that never pushed has no durable WIP, so reclaim
   reports "no resumable branch" rather than promising a ref a later pick could
   not fetch.

Targeting:

* ``harness reclaim <run-id>`` — resolve the run by id (the row carries the
  ticket + branch). Unknown id refuses.
* ``harness reclaim --ticket <ID>`` — resolve the ``open`` run for the ticket.
  When there is **no** local open run (the cloud regime, where a fresh container
  never had the dead run's DB) it still reverts the ticket on Linear — the
  contract the ``--stale`` sweep builds on.
* ``harness reclaim --stale [--project <name>] [--older-than 90m]`` — the **sweep**
  (CAL-736, breakdown item 3). Enumerate the active tickets in scope — both
  transient ``started`` states, In Progress **and** In Review (CAL-1103: ``review``
  parks a reviewed ticket In Review, so a dead orchestrator can strand it there) —
  and reclaim each idle past the threshold, *reusing* the single-target
  ``--ticket`` path per ticket (no second reclaim
  implementation). ``--project`` is optional (#174): supplied → scope to one
  project; omitted → the backend's natural full queue (the ``repo.linear`` team
  for Linear; the board for GitHub). Liveness of a dead run cannot be observed
  directly (ephemeral container, no shared DB); the only signal is time — a
  ticket idle longer than any legitimate run takes is presumed abandoned
  (proposal D2). "Idle" reads **three** clocks (#216, #254): the tracker's
  ``updatedAt`` and — for tracker-stale candidates only — the ledger's last
  activity and the newest mtime among the run's worktree's tracked files, because
  a Projects-v2 Status write never bumps a GitHub issue's ``updatedAt`` and a
  session can work for hours without committing or invoking a verb. The two local
  signals live in :mod:`harness.cli.reclaim_liveness`. The bulk
  arm the hourly Build routine's pre-flight will call (CAL-737).
* ``harness reclaim --undo (<run-id> | --ticket <ID>)`` — the **reversal** (#254).
  A confirmed false positive is put back: ticket to In Progress, ``reclaimed``
  label dropped, a correcting comment posted, and the local ``runs`` row
  re-opened. See :mod:`harness.cli.reclaim_undo`.

Idempotent: reclaiming a run already ``cancelled`` is a safe no-op (no second
Linear revert, no duplicate event). The sweep is idempotent the same way — once
reverted a ticket is Todo, so the next sweep's enumeration no longer returns it.

Exit codes (SPEC §11):
* 0  — reclaimed or undone (or an idempotent no-op / a revert-only when no local run).
* 2  — invocation error: neither or both selectors, unknown run-id, a run with
       no associated ticket, a terminal/unrecognised run status, missing
       ``LINEAR_API_KEY``, or the ticket is not found on Linear. ``--undo``'s
       refusals carry a machine-readable ``reason`` (``ambiguous_mode``,
       ``ambiguous_selector``, ``unknown_run``, ``not_reclaimed``,
       ``ticket_has_open_run``, ``tracker_config``, ``ticket_not_found``,
       ``tracker_error``).
* 1  — unexpected error (DB failure, or an unexpected Linear transport error).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import aiosqlite
import typer
from pydantic import BaseModel

from harness._time import iso_z, parse_iso_z
from harness.cli._abandon import CANCELLABLE_STATUSES, AbandonError
from harness.cli._abandon import abandon_run_in_ledger as _abandon_in_ledger
from harness.cli._duration import _parse_duration
from harness.cli._query_common import _resolve_db_path
from harness.cli._verb import VerbError, run_verb
from harness.cli.reclaim_closable import closable_run
from harness.cli.reclaim_liveness import locally_live, open_run_liveness
from harness.cli.reclaim_undo import ReclaimUndoOutput, run_undo
from harness.cli.reclaim_undo import describe as describe_undo
from harness.layers import tracker as tracker_backend
from harness.loop_budget import load_loop_budget
from harness.reclaim_marker import RECLAIM_LABEL, format_reclaim_comment
from harness.state import store
from harness.state.schema import RUN_STATUSES
from harness.tracker import tracker_client
from harness.tracker_errors import (
    TrackerConfigError,
    TrackerNotFound,
    TrackerRequestError,
)

# size: one cohesive verb — the single-target reclaim (revert → reconcile →
# preserve) plus the --stale sweep that is defined as an enumerate-and-filter
# layer *over* that same path, which splitting would only scatter across files.
# CAL-1104 threaded the tracker layer through both arms so a tracker-less repo
# reclaims locally, pushing it just over the 500-line limit. #254 added two more
# arms without adding net length: the liveness rule moved out to
# ``reclaim_liveness.py`` and the whole ``--undo`` path lives in
# ``reclaim_undo.py``, so what remains here is the Typer surface, the mode/selector
# validation, and the printing — the composer, not the mechanics. #255 added the
# third sweep outcome the same way: the closable predicate lives in
# ``reclaim_closable.py`` and only its one call site and output model are here.

__all__ = [
    "ClosableEntry",
    "ReclaimOutput",
    "ReclaimedEntry",
    "SweepOutput",
    "reclaim_command",
]

#: The reason recorded on the ``workflow_failed`` event a reclaim emits — distinct
#: from ``cancel``'s ``'cancelled'`` so ``harness status`` surfaces
#: ``failure_reason='reclaimed'`` and the ledger says *why* the run ended. This is
#: the ledger-event reason, separate from the Linear ``reclaimed`` *label*
#: (:data:`harness.reclaim_marker.RECLAIM_LABEL`), which is the reader's re-pick gate.
_RECLAIM_REASON = "reclaimed"


class _ReclaimError(VerbError):
    """``reclaim``'s control-flow exception — a :class:`VerbError` (CAL-1013).

    The ``(message, code)`` carrier is inherited from the base. The reclaim and
    sweep arms set no ``reason`` (their refusals are invocation errors a human
    reads); the ``--undo`` arm does, because a caller branches on its refusals —
    ``ambiguous_mode`` is raised here and the rest in
    :mod:`harness.cli.reclaim_undo`.
    """


class ReclaimedEntry(BaseModel):
    """One reclaimed ticket inside a ``--stale`` sweep (no ``run_id`` — the sweep
    reclaims by ticket)."""

    ticket: str
    outcome: str
    branch_preserved: str | None


class ReclaimOutput(BaseModel):
    """Single-target reclaim result (``<run-id>`` or ``--ticket``).

    Gives ``reclaim`` a typed output like every sibling verb (CAL-1013). ``run_id``
    is ``None`` for a revert-only target (a ``--ticket`` with no local open run);
    ``branch_preserved`` is the checkpoint-pushed WIP branch or ``None``.
    """

    run_id: str | None
    ticket: str
    outcome: str
    branch_preserved: str | None


class ClosableEntry(BaseModel):
    """One ticket a ``--stale`` sweep found **closable** rather than stale (#255).

    Its run passed ``review`` and then lost its session; it is still ``open`` and
    ``close`` would accept it, so reverting it to Todo would throw away a passing
    review. Carries the two addresses a caller needs to finish it — the run and
    the exact HEAD the pass covers.
    """

    ticket: str
    run_id: str
    head_sha: str


class SweepOutput(BaseModel):
    """``--stale`` sweep result over a project's active (In Progress / In Review) tickets.

    Every scanned ticket lands in exactly one of ``reclaimed`` / ``skipped`` /
    ``closable``, so ``scanned == len(reclaimed) + len(skipped) + len(closable)``.
    That totality is what lets a caller trust the report rather than re-deriving
    the classification.
    """

    mode: Literal["stale-sweep"] = "stale-sweep"
    project: str | None
    older_than: str
    scanned: int
    reclaimed: list[ReclaimedEntry]
    skipped: list[str]
    #: Defaulted and additive, so an existing ``--json`` consumer is unaffected
    #: and the tracker-less no-op keeps its shape.
    closable: list[ClosableEntry] = []


async def _resumable_branch(
    conn: aiosqlite.Connection, run_id: str, branch: str | None
) -> str | None:
    """The run's branch *iff* it was checkpoint-pushed — else ``None`` (CAL-738).

    A branch is resumable only if it is durable off the dead container, and the
    only durable branch is one a ``harness checkpoint`` pushed to ``origin``. The
    ledger records each push as a ``checkpoint`` event, so its presence is the
    durable-WIP signal. A run that committed locally but never checkpoint-pushed
    has a ``worktree_branch`` that a later (different-container) pick could not
    fetch — reporting it would be a false promise. So with no ``checkpoint``
    event reclaim reports ``None`` and degrades cleanly to "no resumable branch"
    (proposal D4 / CAL-738 AC3); CAL-739's resume then restarts clean.
    """
    if not branch:
        return None
    cur = await conn.execute(
        "SELECT 1 FROM events WHERE run_id = ? AND event_type = 'checkpoint' LIMIT 1",
        (run_id,),
    )
    return branch if await cur.fetchone() is not None else None


async def _resolve_target(
    db_path: Path, run_id_arg: str | None, ticket_arg: str | None
) -> tuple[str | None, str | None, str, str | None]:
    """Resolve the reclaim target → ``(run_id, status, ticket, branch)``.

    The returned ``branch`` is the *resumable* ref — the run's ``worktree_branch``
    only when it was checkpoint-pushed (durable WIP), else ``None`` (CAL-738). For
    ``--ticket`` with no local open run, ``run_id`` / ``status`` / ``branch`` are
    ``None`` (a revert-only target). Raises :class:`_ReclaimError` for an unknown
    run-id or a run with no associated ticket.
    """
    if run_id_arg is not None:
        if not db_path.exists():
            raise _ReclaimError(f"no run with run_id={run_id_arg!r}", 2)
        async with store.connect(db_path) as conn:
            cur = await conn.execute(
                "SELECT status, ticket, worktree_branch FROM runs WHERE run_id = ?",
                (run_id_arg,),
            )
            row = await cur.fetchone()
            if row is None:
                raise _ReclaimError(f"no run with run_id={run_id_arg!r}", 2)
            status, ticket, branch = str(row[0]), row[1], row[2]
            if not ticket:
                raise _ReclaimError(
                    f"run {run_id_arg!r} has no associated ticket; "
                    "there is no Linear ticket to revert",
                    2,
                )
            resumable = await _resumable_branch(conn, run_id_arg, branch)
        return run_id_arg, status, str(ticket), resumable

    assert ticket_arg is not None  # the command guarantees exactly one selector
    if not db_path.exists():
        return None, None, ticket_arg, None
    async with store.connect(db_path) as conn:
        cur = await conn.execute(
            "SELECT run_id, worktree_branch FROM runs "
            "WHERE ticket = ? AND status = 'open'",
            (ticket_arg,),
        )
        row = await cur.fetchone()
        if row is None:
            return None, None, ticket_arg, None
        run_id = str(row[0])
        resumable = await _resumable_branch(conn, run_id, row[1])
    return run_id, "open", ticket_arg, resumable


async def _revert_ticket(ticket: str, run_id: str | None, branch: str | None) -> None:
    """Revert ``ticket`` to Todo + ``reclaimed`` label + a comment (the load-bearing
    side effect — done before the local reconcile)."""
    try:
        client = tracker_client(Path.cwd())
    except TrackerConfigError as exc:
        raise _ReclaimError(str(exc), 2) from exc

    # Reached only in the has-tracker path (the ``if tracker:`` gate above, which
    # is true for linear *and* github), so a real client is resolved here (a
    # configured linear or github backend, never ``None``).
    assert client is not None
    try:
        await client.transition_to_unstarted(ticket)
        await client.apply_label(ticket, RECLAIM_LABEL)
        await client.post_comment(
            ticket, format_reclaim_comment(run_id, branch, when=iso_z())
        )
    except TrackerNotFound as exc:
        raise _ReclaimError(f"ticket {ticket!r} not found on the tracker: {exc}", 2) from exc
    except TrackerRequestError as exc:
        raise _ReclaimError(
            f"failed to revert ticket {ticket!r} on the tracker: {exc}", 2
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise _ReclaimError(
            f"unexpected error reverting ticket {ticket!r}: {exc}", 1
        ) from exc


async def _run_reclaim(
    db_path: Path,
    run_id_arg: str | None,
    ticket_arg: str | None,
    *,
    tracker: bool = True,
) -> ReclaimOutput:
    """Reclaim the resolved target; raise :class:`_ReclaimError` on refusal/error.

    ``tracker`` is ``True`` when a tracker is configured — ``tracker: linear`` or
    ``github`` (CAL-1104, CAL-1197); only ``tracker: none`` sets it ``False``. With
    it off there is no ticket to revert, so step 1 is skipped and reclaim reduces
    to its local half — reconcile the ledger, preserve the branch — which is the
    half that unblocks a fresh ``start`` on the same identifier. (For ``github``
    the tracker step is attempted and then fails loudly at the seam, since the
    backend is not implemented yet.)
    """
    run_id, status, ticket, branch = await _resolve_target(
        db_path, run_id_arg, ticket_arg
    )

    # Idempotent no-op: an already-``cancelled`` run has already been abandoned
    # (by a prior reclaim/cancel), so there is nothing left to do — re-reverting
    # Linear and re-posting the comment would be noise.
    if status == "cancelled":
        return ReclaimOutput(
            run_id=run_id,
            ticket=ticket,
            outcome="already_reclaimed",
            branch_preserved=branch,
        )

    # Validate the run status (when a run row is in play). Refuse a finished
    # terminal run or an unrecognised status — only an in-flight run is reclaimed.
    in_flight = False
    if status is not None:
        if status in CANCELLABLE_STATUSES:
            in_flight = True
        elif status in RUN_STATUSES:
            raise _ReclaimError(
                f"run {run_id!r} is already terminal (status={status!r}); "
                "only an in-flight run can be reclaimed",
                2,
            )
        else:
            raise _ReclaimError(
                f"run {run_id!r} has an unrecognised status {status!r}; "
                "refusing to reclaim",
                2,
            )

    # 1. Revert the ticket FIRST (load-bearing — see module docstring). Skipped
    #    tracker-less: there is no ticket state for the next run to read, so the
    #    ordering the revert-first rule protects does not arise.
    if tracker:
        await _revert_ticket(ticket, run_id, branch)

    # 2. Reconcile the local ledger SECOND (secondary cleanup), only when there
    #    is an in-flight run to flip. The branch/worktree are left intact (D4).
    outcome = "reverted"
    if in_flight and run_id is not None:
        completed_at = datetime.now(UTC).isoformat()
        event_ts = iso_z()
        async with store.connect(db_path) as conn:
            try:
                await _abandon_in_ledger(
                    conn,
                    run_id,
                    reason=_RECLAIM_REASON,
                    completed_at=completed_at,
                    event_ts=event_ts,
                )
            except AbandonError as exc:
                raise _ReclaimError(exc.message, exc.code) from exc
        outcome = "reclaimed"

    return ReclaimOutput(
        run_id=run_id,
        ticket=ticket,
        outcome=outcome,
        branch_preserved=branch,
    )


async def _run_stale_sweep(
    db_path: Path,
    *,
    project: str | None,
    older_than: str,
    threshold: timedelta,
    tracker: bool = True,
) -> SweepOutput:
    """Enumerate the active tickets in scope and reclaim each idle past
    ``threshold``; raise :class:`_ReclaimError` on a tracker/config failure.

    The scope is nullable (#174): ``project`` set → that one project; ``project``
    ``None`` → the backend's natural full queue (Linear: the ``repo.linear`` team;
    GitHub: the board, which already *is* the queue). The seam handles the
    per-backend meaning; this layer just passes the scope through.

    "Active" is both transient ``started`` states — **In Progress** and **In
    Review** (CAL-1103): ``review`` now parks a reviewed ticket In Review, so a
    dead orchestrator between ``review`` and ``close`` can strand a ticket there,
    not only In Progress. Both are swept the same way.

    The enumerate-and-filter layer (CAL-736) on top of the single-target reclaim:
    every stale ticket is reclaimed through :func:`_run_reclaim`'s ``--ticket``
    arm, so the revert + ledger-reconcile + branch-preserve behaviour is shared,
    not re-implemented — and it reverts to Todo identically whichever started
    state the ticket was stranded in. A ticket inside the threshold is left
    untouched.

    Staleness is judged on the newest of three clocks (#216, #254): the tracker's
    ``updatedAt``, and — consulted **only** for a ticket the tracker already
    considers stale — the two local signals in
    :mod:`harness.cli.reclaim_liveness` (the ledger's last activity for that
    ticket's open run, then that run's worktree's newest tracked-file mtime).
    Ordering the checks this way keeps the local signals a pure rescue: a
    tracker-fresh ticket short-circuits without a DB read or a filesystem touch,
    and neither local signal can ever condemn a run the tracker-only path would
    have kept — a ticket is reclaimed iff it is tracker-stale **and** the ledger
    is absent or stale **and** the worktree is unreachable or stale.

    Tracker-less (``tracker: none``, CAL-1104/CAL-1197) the sweep is a **clean
    no-op**: enumeration is the tracker's job (proposal D2), so with no tracker
    there is no active ticket state to enumerate and
    the honest result is "scanned nothing". It reports empty rather than failing
    because the Build routine runs this every tick as a pre-flight — an error
    here would wedge the loop it exists to unblock.
    """
    if not tracker:
        return SweepOutput(
            project=project,
            older_than=older_than,
            scanned=0,
            reclaimed=[],
            skipped=[],
            closable=[],
        )

    try:
        client = tracker_client(Path.cwd())
    except TrackerConfigError as exc:
        raise _ReclaimError(str(exc), 2) from exc

    # Reached only in the has-tracker path (the ``if tracker:`` gate above, which
    # is true for linear *and* github), so a real client is resolved here (a
    # configured linear or github backend, never ``None``).
    assert client is not None
    scope = f"project {project!r}" if project is not None else "the whole tracker queue"
    try:
        issues = await client.fetch_reclaimable_issues(project=project)
    except TrackerRequestError as exc:
        raise _ReclaimError(
            f"failed to list active issues for {scope}: {exc}", 2
        ) from exc

    # Staleness keys on time only (proposal D2): a ticket idle longer than the
    # threshold is presumed abandoned. ``updatedAt`` is parsed through the
    # ``_time`` seam; both sides of the comparison are aware-UTC.
    cutoff = datetime.now(UTC) - threshold

    reclaimed: list[ReclaimedEntry] = []
    skipped: list[str] = []
    closable: list[ClosableEntry] = []
    for issue in issues:
        identifier = str(issue["identifier"])
        updated = parse_iso_z(str(issue["updated_at"]))
        if updated >= cutoff:
            # The tracker itself says the ticket is active — no second opinion
            # needed, and no ledger round-trip spent on it.
            skipped.append(identifier)
            continue
        # Tracker-stale is only a *candidate* (#216). The tracker timestamp is not
        # a heartbeat on the github backend, so consult the local signals before
        # reverting: the ledger's last activity, then — since #254 — the newest
        # mtime among the run's worktree's tracked files, which is the only signal
        # that sees a session working without committing or invoking a verb.
        liveness = await open_run_liveness(db_path, identifier)
        if liveness is not None and await locally_live(liveness, cutoff):
            skipped.append(identifier)
            continue
        # Dead by every clock — but a run that passed review and then lost its
        # session was never *stranded*, only unfinished (#255). Checked after
        # liveness, never before: a live session paused at a clean,
        # previously-passed HEAD must read as spared, not as drainable.
        if liveness is not None:
            finishable = await closable_run(db_path, liveness)
            if finishable is not None:
                closable.append(
                    ClosableEntry(
                        ticket=identifier,
                        run_id=finishable.run_id,
                        head_sha=finishable.head_sha,
                    )
                )
                continue
        result = await _run_reclaim(db_path, None, identifier)
        reclaimed.append(
            ReclaimedEntry(
                ticket=identifier,
                outcome=result.outcome,
                branch_preserved=result.branch_preserved,
            )
        )

    return SweepOutput(
        project=project,
        older_than=older_than,
        scanned=len(issues),
        reclaimed=reclaimed,
        skipped=skipped,
        closable=closable,
    )


def _print_sweep(result: SweepOutput) -> None:
    """Human-readable summary of a ``--stale`` sweep (``--json`` emits ``result``)."""
    scope = repr(result.project) if result.project is not None else "the whole tracker queue"
    typer.echo(
        f"Swept {result.scanned} active ticket(s) in {scope} "
        f"(threshold {result.older_than}): {len(result.reclaimed)} reclaimed, "
        f"{len(result.skipped)} left in-flight, {len(result.closable)} closable."
    )
    for entry in result.reclaimed:
        typer.echo(f"  reclaimed {entry.ticket} ({entry.outcome})")
    for ident in result.skipped:
        typer.echo(f"  skipped   {ident} (within threshold)")
    for closable in result.closable:
        typer.echo(
            f"  closable  {closable.ticket} (run {closable.run_id} at "
            f"{closable.head_sha}) — review covers HEAD; harness close will finish it"
        )


def reclaim_command(
    run_id: str | None = typer.Argument(
        None, help="Run identifier (ULID). Provide this or --ticket, not both."
    ),
    ticket: str | None = typer.Option(
        None,
        "--ticket",
        help="Linear ticket identifier (e.g. CAL-735) — reclaim the open run for it.",
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db)."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
    stale: bool = typer.Option(
        False,
        "--stale",
        help="Sweep mode: reclaim every active (In Progress / In Review) ticket "
        "in scope idle past --older-than. Mutually exclusive with <run-id>/--ticket.",
    ),
    project: str | None = typer.Option(
        None,
        "--project",
        help="Scope the --stale sweep to one project; omit to sweep the whole "
        "tracker queue (the repo.linear team for Linear; the board for GitHub).",
    ),
    older_than: str | None = typer.Option(
        None,
        "--older-than",
        help="Staleness threshold for --stale (e.g. 110m, 12h, 7d). Omit to use "
        "CONTEXT.md's loop.wall_clock_budget_minutes — the single source of truth "
        "this mirrors.",
    ),
    undo: bool = typer.Option(
        False,
        "--undo",
        help="Reverse a reclaim confirmed to be a false positive: restore the "
        "ticket to In Progress, drop the reclaimed label, re-open the run. "
        "Takes <run-id> or --ticket; mutually exclusive with --stale.",
    ),
) -> None:
    """Reclaim a stranded run — revert its ticket to Todo and reconcile the ledger."""
    db_path = _resolve_db_path(db)
    # ``reclaim`` has no ``--repo`` flag: like its read-side siblings it is
    # anchored on the CWD (the same place ``_resolve_db_path`` defaults the
    # ledger to), so the layer is read from the CWD's CONTEXT.md (CAL-1104).
    # A tracker is present for linear *and* github (only ``none`` is tracker-less);
    # github then fails loudly when the seam resolves the client, rather than
    # silently taking the tracker-less no-op path.
    tracker = tracker_backend(Path.cwd()) != "none"

    def _do() -> SweepOutput | ReclaimOutput | ReclaimUndoOutput:
        if undo:
            # ``--stale`` sweeps the queue; ``--undo`` reverses one target. There is
            # no coherent bulk reversal — a false positive is confirmed per ticket
            # by a human — so the combination is refused rather than interpreted.
            if stale:
                raise _ReclaimError(
                    "--undo reverses one reclaim; do not combine it with --stale",
                    2,
                    reason="ambiguous_mode",
                )
            return asyncio.run(run_undo(db_path, run_id, ticket, tracker=tracker))
        if stale:
            # Sweep mode owns the scope; a single-target selector is ambiguous.
            if run_id is not None or ticket is not None:
                raise _ReclaimError(
                    "--stale sweeps the queue; do not combine it with "
                    "<run-id> or --ticket",
                    2,
                )
            # ``--project`` is optional (#174): supplied → scope to that project;
            # omitted → the backend's natural full queue (the seam decides what
            # "unset" means per backend). The old required-project validation is
            # gone — an unscoped sweep is now a first-class mode.
            # Parse the duration outside the event loop so a bad value exits 2
            # via typer.BadParameter, exactly like ``worktrees cleanup --age``.
            # ``run_verb`` only catches ``VerbError``, so BadParameter propagates
            # to Typer's own handler as before.
            # ``--older-than`` defaults to a *sentinel*, not a duration string:
            # reclamation staleness and the ``review`` wall-clock breaker are one
            # quantity read from two directions, so an omitted flag resolves from
            # the same ``loop.wall_clock_budget_minutes`` the breaker reads (#260).
            # Defaulting to a string built from the config would merely move the
            # literal rather than delete it. CWD-anchored like the tracker read
            # above — ``reclaim`` has no ``--repo`` (CAL-1104).
            resolved_older_than = (
                older_than
                if older_than is not None
                else f"{load_loop_budget(Path.cwd()).wall_clock_budget_minutes}m"
            )
            threshold = _parse_duration(resolved_older_than)
            return asyncio.run(
                _run_stale_sweep(
                    db_path,
                    project=project,
                    older_than=resolved_older_than,
                    threshold=threshold,
                    tracker=tracker,
                )
            )
        # Exactly one selector: a bare run-id or --ticket, never both or neither.
        if (run_id is None) == (ticket is None):
            raise _ReclaimError("provide exactly one of <run-id> or --ticket <ID>", 2)
        return asyncio.run(_run_reclaim(db_path, run_id, ticket, tracker=tracker))

    result = run_verb(_do, json_output=json_output)

    if json_output:
        typer.echo(result.model_dump_json())
        return

    if isinstance(result, SweepOutput):
        _print_sweep(result)
        return

    if isinstance(result, ReclaimUndoOutput):
        typer.echo(describe_undo(result))
        return

    if result.outcome == "already_reclaimed":
        typer.echo(
            f"Run {result.run_id} already reclaimed (no-op); "
            f"ticket {result.ticket} left as-is"
        )
    elif result.outcome == "reverted":
        typer.echo(
            f"Reverted ticket {result.ticket} to Todo + reclaimed "
            "(no local run to reconcile)"
        )
    else:
        typer.echo(
            f"Reclaimed run {result.run_id} — ticket {result.ticket} reverted "
            f"to Todo; branch {result.branch_preserved!r} preserved"
        )
