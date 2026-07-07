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
* ``harness reclaim --stale --project <name> [--older-than 90m]`` — the **sweep**
  (CAL-736, breakdown item 3). Enumerate the project's In-Progress tickets and
  reclaim each whose Linear ``updatedAt`` is older than the threshold, *reusing*
  the single-target ``--ticket`` path per ticket (no second reclaim
  implementation). Liveness of a dead run cannot be observed (ephemeral
  container, no shared DB); the only signal is time — a ticket idle longer than
  any legitimate run takes is presumed abandoned (proposal D2). The bulk arm the
  hourly Build routine's pre-flight will call (CAL-737).

Idempotent: reclaiming a run already ``cancelled`` is a safe no-op (no second
Linear revert, no duplicate event). The sweep is idempotent the same way — once
reverted a ticket is Todo, so the next sweep's enumeration no longer returns it.

Exit codes (SPEC §11):
* 0  — reclaimed (or an idempotent no-op / a revert-only when no local run).
* 2  — invocation error: neither or both selectors, unknown run-id, a run with
       no associated ticket, a terminal/unrecognised run status, missing
       ``LINEAR_API_KEY``, or the ticket is not found on Linear.
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
from harness.linear import (
    LinearClient,
    LinearConfigError,
    LinearNotFound,
    LinearRequestError,
    linear_api_key,
)
from harness.reclaim_marker import RECLAIM_LABEL, format_reclaim_comment
from harness.state import store
from harness.state.schema import RUN_STATUSES

__all__ = [
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

    The ``(message, code)`` carrier is inherited from the base; ``reclaim`` never
    sets a ``reason``.
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


class SweepOutput(BaseModel):
    """``--stale`` sweep result over a project's In-Progress tickets."""

    mode: Literal["stale-sweep"] = "stale-sweep"
    project: str
    older_than: str
    scanned: int
    reclaimed: list[ReclaimedEntry]
    skipped: list[str]


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
        api_key = linear_api_key()
    except LinearConfigError as exc:
        raise _ReclaimError(str(exc), 2) from exc

    client = LinearClient(api_key=api_key)
    try:
        await client.transition_to_unstarted(ticket)
        await client.apply_label(ticket, RECLAIM_LABEL)
        await client.post_comment(
            ticket, format_reclaim_comment(run_id, branch, when=iso_z())
        )
    except LinearNotFound as exc:
        raise _ReclaimError(f"ticket {ticket!r} not found on Linear: {exc}", 2) from exc
    except LinearRequestError as exc:
        raise _ReclaimError(
            f"failed to revert ticket {ticket!r} on Linear: {exc}", 2
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise _ReclaimError(
            f"unexpected error reverting ticket {ticket!r}: {exc}", 1
        ) from exc


async def _run_reclaim(
    db_path: Path, run_id_arg: str | None, ticket_arg: str | None
) -> ReclaimOutput:
    """Reclaim the resolved target; raise :class:`_ReclaimError` on refusal/error."""
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

    # 1. Revert the ticket FIRST (load-bearing — see module docstring).
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
    db_path: Path, *, project: str, older_than: str, threshold: timedelta
) -> SweepOutput:
    """Enumerate the project's In-Progress tickets and reclaim each idle past
    ``threshold``; raise :class:`_ReclaimError` on a Linear/config failure.

    The enumerate-and-filter layer (CAL-736) on top of the single-target reclaim:
    every stale ticket is reclaimed through :func:`_run_reclaim`'s ``--ticket``
    arm, so the revert + ledger-reconcile + branch-preserve behaviour is shared,
    not re-implemented. A ticket inside the threshold is left untouched.
    """
    try:
        api_key = linear_api_key()
    except LinearConfigError as exc:
        raise _ReclaimError(str(exc), 2) from exc

    client = LinearClient(api_key=api_key)
    try:
        issues = await client.fetch_in_progress_issues(project=project)
    except LinearRequestError as exc:
        raise _ReclaimError(
            f"failed to list In-Progress issues for project {project!r}: {exc}", 2
        ) from exc

    # Staleness keys on time only (proposal D2): a ticket idle longer than the
    # threshold is presumed abandoned. ``updatedAt`` is parsed through the
    # ``_time`` seam; both sides of the comparison are aware-UTC.
    cutoff = datetime.now(UTC) - threshold

    reclaimed: list[ReclaimedEntry] = []
    skipped: list[str] = []
    for issue in issues:
        identifier = str(issue["identifier"])
        updated = parse_iso_z(str(issue["updated_at"]))
        if updated < cutoff:
            result = await _run_reclaim(db_path, None, identifier)
            reclaimed.append(
                ReclaimedEntry(
                    ticket=identifier,
                    outcome=result.outcome,
                    branch_preserved=result.branch_preserved,
                )
            )
        else:
            skipped.append(identifier)

    return SweepOutput(
        project=project,
        older_than=older_than,
        scanned=len(issues),
        reclaimed=reclaimed,
        skipped=skipped,
    )


def _print_sweep(result: SweepOutput) -> None:
    """Human-readable summary of a ``--stale`` sweep (``--json`` emits ``result``)."""
    typer.echo(
        f"Swept {result.scanned} In-Progress ticket(s) in {result.project!r} "
        f"(threshold {result.older_than}): {len(result.reclaimed)} reclaimed, "
        f"{len(result.skipped)} left in-flight."
    )
    for entry in result.reclaimed:
        typer.echo(f"  reclaimed {entry.ticket} ({entry.outcome})")
    for ident in result.skipped:
        typer.echo(f"  skipped   {ident} (within threshold)")


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
        help="Sweep mode: reclaim every In-Progress ticket in --project idle "
        "past --older-than. Mutually exclusive with <run-id>/--ticket.",
    ),
    project: str | None = typer.Option(
        None,
        "--project",
        help="Project name to scope the --stale sweep (required with --stale).",
    ),
    older_than: str = typer.Option(
        "90m",
        "--older-than",
        help="Staleness threshold for --stale (e.g. 90m, 12h, 7d). Default 90m.",
    ),
) -> None:
    """Reclaim a stranded run — revert its ticket to Todo and reconcile the ledger."""
    db_path = _resolve_db_path(db)

    def _do() -> SweepOutput | ReclaimOutput:
        if stale:
            # Sweep mode owns the project; a single-target selector is ambiguous.
            if run_id is not None or ticket is not None:
                raise _ReclaimError(
                    "--stale sweeps the project; do not combine it with "
                    "<run-id> or --ticket",
                    2,
                )
            if not project:
                raise _ReclaimError(
                    "--stale requires --project <name> to scope the sweep", 2
                )
            # Parse the duration outside the event loop so a bad value exits 2
            # via typer.BadParameter, exactly like ``worktrees cleanup --age``.
            # ``run_verb`` only catches ``VerbError``, so BadParameter propagates
            # to Typer's own handler as before.
            threshold = _parse_duration(older_than)
            return asyncio.run(
                _run_stale_sweep(
                    db_path,
                    project=project,
                    older_than=older_than,
                    threshold=threshold,
                )
            )
        # Exactly one selector: a bare run-id or --ticket, never both or neither.
        if (run_id is None) == (ticket is None):
            raise _ReclaimError("provide exactly one of <run-id> or --ticket <ID>", 2)
        return asyncio.run(_run_reclaim(db_path, run_id, ticket))

    result = run_verb(_do, json_output=json_output)

    if json_output:
        typer.echo(result.model_dump_json())
        return

    if isinstance(result, SweepOutput):
        _print_sweep(result)
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
