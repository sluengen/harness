"""``harness defer <ticket>`` — the triage write as an audited verb (CAL-1143).

The unattended Build routine's triage step — ``work-discovery`` judging a picked
ticket not-yet-actionable and recording "comment + apply the ``decision`` label"
— was the one write the routine **hand-rolled as raw GraphQL** (via the ``linear``
skill), because it is not a build-lifecycle transition and had no verb.
Everything that touches the gate (``start`` / ``review`` / ``close`` /
``reclaim``) is already a verb; triage was not. That left it opaque (nothing in
the runs/events ledger, only a Linear comment) and made it the one write the
autonomous auto-mode classifier intermittently blocked — a bounded, named verb
binds to its ``autoMode.allow`` clause far more reliably than a ``docker run
python3 <GraphQL script>``.

What ``defer`` does, for a ticket on this repo's Build queue (``repo.project``):

1. **Verify Build-queue membership.** Read the ticket's project; a ticket not
   found on Linear, or found but on another project, is refused (exit 2) with a
   structured ``reason`` — no comment, no label, no event.
2. **Post the reason as a comment** (``commentCreate``).
3. **Additively apply the hold label** — ``decision`` (a judgment call, the
   default) or ``operator`` (an interactive session), selected by ``--needs``
   (``issueAddLabel`` — never a full-set ``issueUpdate(labelIds)`` replace, so
   labels already on the ticket are preserved; this matches the
   ``autoMode.allow`` clause wording "applying the label"). The label says *why*
   the ticket is held.
4. **Assign the ticket to the operator** (Linear ``viewer`` — the API key's own
   user). Agents have no Linear identity, so an assignee at all is the
   machine-readable "a human holds this" signal ``work-discovery`` skips on later
   ticks; the label only explains it.
5. **Record a ``defer`` event** in the runs/events ledger (ticket, reason, the
   ``needs`` kind, timestamp), so the triage decision is auditable like every
   other verb.

The Linear writes run **before** the ledger event (the load-bearing external
effect first, the audit record second — the same ordering ``reclaim`` uses): a
ledger failure after a successful defer surfaces to the operator rather than
silently dropping the triage.

Tracker-less repo (``layers.linear: false``): a **clean no-op** (exit 0, no
write), consistent with the other verbs — there is no tracker to defer on.

Exit codes (SPEC §11):
* 0  — deferred (or a tracker-less clean no-op).
* 2  — invocation / refusal: neither/both of ``--reason`` / ``--reason-file``,
       missing ``LINEAR_API_KEY``, ``repo.project`` unconfigured, the ticket not
       found on Linear, or the ticket not on the Build queue.
* 1  — unexpected error (DB failure, or an unexpected Linear transport error).
"""

from __future__ import annotations

import asyncio
import enum
from pathlib import Path

import typer
from pydantic import BaseModel

from harness._time import iso_z
from harness.cli._query_common import _resolve_db_path
from harness.cli._verb import VerbError, run_verb
from harness.events.emitter import EventEmitter
from harness.events.payloads import DeferEventData
from harness.identity import generate_run_id
from harness.layers import tracker as tracker_backend
from harness.linear import (
    LinearConfigError,
    LinearNotFound,
    LinearRequestError,
)
from harness.repo_config import repo_project
from harness.state import store
from harness.tracker import UnsupportedTrackerError, tracker_client

__all__ = ["DeferNeeds", "DeferOutput", "defer_command"]


class DeferNeeds(enum.StrEnum):
    """The two hold kinds a deferral can express (ticket-protocol-hygiene).

    ``decision`` — a judgment call is pending; ``operator`` — an interactive,
    hands-on session is needed. The kind's *value* doubles as the Linear label
    name applied, so a held ticket carries both the machine-readable assignment
    (the skip signal) and the label saying *why* it is held.
    """

    decision = "decision"
    operator = "operator"


class _DeferError(VerbError):
    """``defer``'s control-flow exception — a :class:`VerbError` (CAL-1013).

    Unlike ``reclaim``, ``defer`` sets a machine-readable ``reason`` on its
    refusals so the routine can branch on the kind of refusal (a not-on-queue
    ticket vs. a config gap) without string-matching the message.
    """


class DeferOutput(BaseModel):
    """Typed result of a ``defer`` — like every sibling verb (CAL-1013).

    ``run_id`` is the synthetic run row anchoring the ``defer`` event, or
    ``None`` for a tracker-less no-op; ``project`` is the Build queue the ticket
    was bound to (``None`` tracker-less).
    """

    ticket: str
    outcome: str
    project: str | None
    run_id: str | None


async def _record_defer_event(
    db_path: Path, ticket: str, reason: str, project: str, needs: str
) -> str:
    """Anchor a ``defer`` event in the ledger and return its run id.

    The ``events`` FK requires a ``runs`` row, and a defer has no build run — so
    it gets its own terminal run row (``workflow_name='defer'``, ``status='closed'``)
    to carry the audit event. The ``'closed'`` status keeps it clear of
    ``idx_runs_ticket_open`` (``WHERE status='open'``), so a later ``harness start``
    on the same ticket is never blocked by a defer row.
    """
    run_id = generate_run_id()
    now = iso_z()
    await store.init_db(db_path)
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO runs ("
            "run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, ticket, started_at, completed_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, "defer", 0, "closed", "{}", "{}", ticket, now, now),
        )
        await conn.commit()
    await EventEmitter(db_path).emit(
        run_id=run_id,
        event_type="defer",
        data=DeferEventData(
            run_id=run_id,
            ticket=ticket,
            reason=reason,
            project=project,
            needs=needs,
            deferred_at=now,
        ).model_dump(),
    )
    return run_id


async def _run_defer(
    db_path: Path, ticket: str, reason: str, *, needs: DeferNeeds, repo_root: Path
) -> DeferOutput:
    """Defer ``ticket``; raise :class:`_DeferError` on refusal/error.

    Tracker-less (``layers.linear: false``) it is a clean no-op — there is no
    tracker to comment on, label, or assign, so the honest outcome is "skipped".
    """
    # Only ``tracker: none`` is a clean tracker-less skip. ``github`` is *not*
    # tracker-less — it is a misconfig that must fail loudly (below, when the
    # seam raises), never silently no-op here.
    if tracker_backend(repo_root) == "none":
        return DeferOutput(
            ticket=ticket, outcome="skipped_no_tracker", project=None, run_id=None
        )

    project = repo_project(repo_root)
    if not project:
        raise _DeferError(
            "repo.project is not configured in CONTEXT.md; cannot bind the defer "
            "to a Build queue",
            2,
            reason="no_project_configured",
        )

    try:
        client = tracker_client(repo_root)
    except (LinearConfigError, UnsupportedTrackerError) as exc:
        raise _DeferError(str(exc), 2, reason="linear_config") from exc

    # The ``tracker: none`` guard above already returned, and ``github`` raised
    # in the seam, so a real client is resolved here (linear, never ``None``).
    assert client is not None

    # 1. Verify the ticket is on this repo's Build queue before any write.
    try:
        ticket_project = await client.fetch_issue_project(ticket)
    except LinearNotFound as exc:
        raise _DeferError(
            f"ticket {ticket!r} not found on Linear", 2, reason="ticket_not_found"
        ) from exc
    except LinearRequestError as exc:
        raise _DeferError(
            f"failed to look up ticket {ticket!r} on Linear: {exc}",
            2,
            reason="linear_error",
        ) from exc

    if ticket_project != project:
        raise _DeferError(
            f"ticket {ticket!r} is not on the Build queue {project!r} "
            f"(project: {ticket_project!r}); refusing to defer",
            2,
            reason="not_on_build_queue",
        )

    # 2 + 3 + 4. The triage write (load-bearing external effect): comment first,
    #        then the additive `decision`/`operator` label, then assign the ticket
    #        to the operator — so the explanation is on the ticket, the label says
    #        *why* it is held, and the assignment is the machine-readable "a human
    #        holds this" signal work-discovery skips on later ticks. The label's
    #        name is the `needs` kind's value.
    try:
        await client.post_comment(ticket, reason)
        await client.apply_label(ticket, needs.value)
        await client.assign_to_viewer(ticket)
    except LinearNotFound as exc:
        raise _DeferError(
            f"ticket {ticket!r} not found on Linear: {exc}",
            2,
            reason="ticket_not_found",
        ) from exc
    except LinearRequestError as exc:
        raise _DeferError(
            f"failed to defer ticket {ticket!r} on Linear: {exc}",
            2,
            reason="linear_error",
        ) from exc
    except Exception as exc:  # noqa: BLE001 — map any transport surprise to a verb error
        raise _DeferError(
            f"unexpected error deferring ticket {ticket!r}: {exc}", 1
        ) from exc

    # 5. Record the defer in the ledger (audit trail) — after the Linear write.
    run_id = await _record_defer_event(db_path, ticket, reason, project, needs.value)
    return DeferOutput(
        ticket=ticket, outcome="deferred", project=project, run_id=run_id
    )


def _resolve_reason(reason: str | None, reason_file: Path | None) -> str:
    """Exactly one of ``--reason`` / ``--reason-file`` supplies the body.

    Raises :class:`_DeferError` (exit 2) when neither or both is given, or when
    ``--reason-file`` cannot be read.
    """
    if (reason is None) == (reason_file is None):
        raise _DeferError(
            "provide exactly one of --reason <text> or --reason-file <path>", 2
        )
    if reason is not None:
        return reason
    assert reason_file is not None
    try:
        return reason_file.read_text()
    except OSError as exc:
        raise _DeferError(
            f"could not read --reason-file {str(reason_file)!r}: {exc}", 2
        ) from exc


def defer_command(
    ticket: str = typer.Argument(..., help="Linear ticket identifier (e.g. CAL-1143)."),
    reason: str | None = typer.Option(
        None, "--reason", help="Triage rationale posted as a comment."
    ),
    reason_file: Path | None = typer.Option(
        None,
        "--reason-file",
        help="Read the triage rationale from a file (for long bodies).",
    ),
    needs: DeferNeeds = typer.Option(
        DeferNeeds.decision,
        "--needs",
        help="The hold kind: `decision` (a judgment call, the default) or "
        "`operator` (an interactive session). Selects the label applied.",
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db)."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Defer a not-yet-actionable ticket — comment + the ``decision``/``operator``
    label + assign the operator + a ledger event."""
    db_path = _resolve_db_path(db)
    # Anchored on the CWD, like ``reclaim``: the routine invokes verbs with CWD =
    # the target repo root, so the layer + ``repo.project`` are read from that
    # repo's CONTEXT.md.
    repo_root = Path.cwd()

    def _do() -> DeferOutput:
        body = _resolve_reason(reason, reason_file)
        return asyncio.run(
            _run_defer(db_path, ticket, body, needs=needs, repo_root=repo_root)
        )

    result = run_verb(_do, json_output=json_output)

    if json_output:
        typer.echo(result.model_dump_json())
        return

    if result.outcome == "skipped_no_tracker":
        typer.echo(f"defer {ticket}: no tracker configured (no-op)")
    else:
        typer.echo(
            f"Deferred {ticket} on {result.project} — commented + "
            f"`{needs.value}` label + assigned to operator"
        )
