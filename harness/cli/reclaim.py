"""``harness reclaim`` — reclaim a run whose orchestrator died (CAL-735).

Breakdown item 2 of the accepted proposal ``stale-run-reclamation``. When the
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
   branch; the work is kept for a later resume (CAL-739).

Targeting:

* ``harness reclaim <run-id>`` — resolve the run by id (the row carries the
  ticket + branch). Unknown id refuses.
* ``harness reclaim --ticket <ID>`` — resolve the ``open`` run for the ticket.
  When there is **no** local open run (the cloud regime, where a fresh container
  never had the dead run's DB) it still reverts the ticket on Linear — the
  contract the ``--stale`` sweep (CAL-736) builds on.

Idempotent: reclaiming a run already ``cancelled`` is a safe no-op (no second
Linear revert, no duplicate event).

Exit codes (SPEC §11):
* 0  — reclaimed (or an idempotent no-op / a revert-only when no local run).
* 2  — invocation error: neither or both selectors, unknown run-id, a run with
       no associated ticket, a terminal/unrecognised run status, missing
       ``LINEAR_API_KEY``, or the ticket is not found on Linear.
* 1  — unexpected error (DB failure, or an unexpected Linear transport error).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import typer

from harness._time import iso_z
from harness.cli._abandon import CANCELLABLE_STATUSES, AbandonError
from harness.cli._abandon import abandon_run_in_ledger as _abandon_in_ledger
from harness.cli._query_common import _resolve_db_path
from harness.linear import (
    LinearClient,
    LinearConfigError,
    LinearNotFound,
    LinearRequestError,
    linear_api_key,
)
from harness.state import store
from harness.state.schema import RUN_STATUSES

__all__ = ["reclaim_command"]

#: The reason recorded on the ``workflow_failed`` event a reclaim emits — distinct
#: from ``cancel``'s ``'cancelled'`` so ``harness status`` surfaces
#: ``failure_reason='reclaimed'`` and the ledger says *why* the run ended.
_RECLAIM_REASON = "reclaimed"

#: The label reclaim applies to a reverted ticket so a re-picked ticket is
#: visibly marked (proposal D1).
_RECLAIM_LABEL = "reclaimed"


class _ReclaimError(Exception):
    """Internal control-flow exception carrying a message and an exit code."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _comment_body(run_id: str | None, branch: str | None) -> str:
    """A reclamation comment naming when it happened and the preserved branch."""
    run_clause = f"run `{run_id}`" if run_id else "no local run row found"
    ref = branch if branch else "(none — clean restart on next pick)"
    return (
        f"Reclaimed by `harness reclaim` at {iso_z()}. The orchestrating session "
        f"is presumed dead ({run_clause}); the ticket is reverted to **Todo** and "
        f"labelled `reclaimed` so it can be re-picked. Preserved branch: `{ref}`."
    )


async def _resolve_target(
    db_path: Path, run_id_arg: str | None, ticket_arg: str | None
) -> tuple[str | None, str | None, str, str | None]:
    """Resolve the reclaim target → ``(run_id, status, ticket, branch)``.

    For ``--ticket`` with no local open run, ``run_id`` / ``status`` / ``branch``
    are ``None`` (a revert-only target). Raises :class:`_ReclaimError` for an
    unknown run-id or a run with no associated ticket.
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
        return run_id_arg, status, str(ticket), branch

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
    return str(row[0]), "open", ticket_arg, row[1]


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
        await client.apply_label(ticket, _RECLAIM_LABEL)
        await client.post_comment(ticket, _comment_body(run_id, branch))
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
) -> dict[str, object]:
    """Reclaim the resolved target; raise :class:`_ReclaimError` on refusal/error."""
    run_id, status, ticket, branch = await _resolve_target(
        db_path, run_id_arg, ticket_arg
    )

    # Idempotent no-op: an already-``cancelled`` run has already been abandoned
    # (by a prior reclaim/cancel), so there is nothing left to do — re-reverting
    # Linear and re-posting the comment would be noise.
    if status == "cancelled":
        return {
            "run_id": run_id,
            "ticket": ticket,
            "outcome": "already_reclaimed",
            "branch_preserved": branch,
        }

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

    return {
        "run_id": run_id,
        "ticket": ticket,
        "outcome": outcome,
        "branch_preserved": branch,
    }


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
) -> None:
    """Reclaim a stranded run — revert its ticket to Todo and reconcile the ledger."""
    db_path = _resolve_db_path(db)

    try:
        # Exactly one selector: a bare run-id or --ticket, never both or neither.
        if (run_id is None) == (ticket is None):
            raise _ReclaimError(
                "provide exactly one of <run-id> or --ticket <ID>", 2
            )
        result = asyncio.run(_run_reclaim(db_path, run_id, ticket))
    except _ReclaimError as exc:
        if json_output:
            typer.echo(json.dumps({"error": exc.message}))
        else:
            typer.echo(exc.message, err=True)
        raise typer.Exit(code=exc.code) from exc

    if json_output:
        typer.echo(json.dumps(result))
        return

    outcome = result["outcome"]
    if outcome == "already_reclaimed":
        typer.echo(
            f"Run {result['run_id']} already reclaimed (no-op); "
            f"ticket {result['ticket']} left as-is"
        )
    elif outcome == "reverted":
        typer.echo(
            f"Reverted ticket {result['ticket']} to Todo + reclaimed "
            "(no local run to reconcile)"
        )
    else:
        typer.echo(
            f"Reclaimed run {result['run_id']} — ticket {result['ticket']} reverted "
            f"to Todo; branch {result['branch_preserved']!r} preserved"
        )
