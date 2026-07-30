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

What ``defer`` does, for a ticket on this repo's Build queue:

1. **Verify Build-queue membership.** Ask the tracker seam whether the ticket is
   on the queue in force — ``repo.project`` when it is configured, the backend's
   natural full queue when it is not (#248) — and refuse a ticket that is not
   found, or found but off the queue (exit 2) with a structured ``reason``: no
   comment, no label, no event.
2. **Post the reason as a comment** (``commentCreate``).
3. **Additively apply the hold label** — ``decision`` (a judgment call, the
   default), ``input`` (the operator must supply something the run cannot), or
   ``operator`` (an interactive session), selected by ``--needs``
   (``issueAddLabel`` — never a full-set ``issueUpdate(labelIds)`` replace, so
   labels already on the ticket are preserved; this matches the
   ``autoMode.allow`` clause wording "applying the label"). The label says *why*
   the ticket is held. (ADR 0006 — the three kinds partition held work by what
   kind of human input the ticket waits on; ``operator``'s meaning narrows to
   *interactive session only*, no longer "a human owes this something".)
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
       missing ``LINEAR_API_KEY``, the ticket not found on Linear, or the ticket
       not on the Build queue. An absent ``repo.project`` is **not** a refusal —
       it means the whole tracker queue (#248).
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
from harness.repo_config import repo_project
from harness.state import store
from harness.tracker import tracker_client
from harness.tracker_errors import (
    TrackerConfigError,
    TrackerNotFound,
    TrackerRequestError,
)
from harness.tracker_queue import scope_phrase

__all__ = ["DeferNeeds", "DeferOutput", "defer_command"]


class DeferNeeds(enum.StrEnum):
    """The three hold kinds a deferral can express (ADR 0006, #191).

    ``decision`` — a judgment call is pending; clearable by answering, from the
    ticket alone. ``input`` — the operator must supply something the run
    cannot (a work item, a credential, infrastructure stood up); not
    answerable in a turn. ``operator`` — an interactive, hands-on session is
    needed; this meaning is **narrower** than it once was — it no longer covers
    "a human owes this ticket something" (that is ``input`` now).

    The kind's *value* doubles as the tracker label name applied, so a held
    ticket carries both the machine-readable assignment (the skip signal) and
    the label saying *why* it is held. ``work-discovery`` skips all three; only
    the return path (``/decision``, #193) distinguishes between them.
    """

    decision = "decision"
    input = "input"
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
    db_path: Path, ticket: str, reason: str, project: str | None, needs: str
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
    # Only ``tracker: none`` is a clean tracker-less skip. A configured backend
    # (linear or github) resolves a real client below; a *misconfigured* one
    # (missing credential/config) fails loudly there, never silently no-ops here.
    if tracker_backend(repo_root) == "none":
        return DeferOutput(
            ticket=ticket, outcome="skipped_no_tracker", project=None, run_id=None
        )

    # The scope is nullable (#248, mirroring #174): set → that one project;
    # unset → the backend's natural full queue. The seam owns what "unset" means
    # per backend, so this layer just passes the scope through.
    project = repo_project(repo_root)

    try:
        client = tracker_client(repo_root)
    except TrackerConfigError as exc:
        # A missing credential or config block (LinearConfigError /
        # GitHubConfigError) is a config gap the routine can branch on.
        raise _DeferError(str(exc), 2, reason="tracker_config") from exc

    # The ``tracker: none`` guard above already returned, so a real client is
    # resolved here (linear or github, never ``None``).
    assert client is not None

    # 1. Verify the ticket is on this repo's Build queue before any write.
    try:
        membership = await client.fetch_queue_membership(ticket, project=project)
    except TrackerNotFound as exc:
        raise _DeferError(
            f"ticket {ticket!r} not found on the tracker", 2, reason="ticket_not_found"
        ) from exc
    except TrackerRequestError as exc:
        raise _DeferError(
            f"failed to look up ticket {ticket!r} on the tracker: {exc}",
            2,
            reason="tracker_error",
        ) from exc

    if not membership.on_queue:
        raise _DeferError(
            f"ticket {ticket!r} is not on {scope_phrase(project)} "
            f"(project: {membership.project!r}); refusing to defer",
            2,
            reason="not_on_build_queue",
        )

    # The value recorded in the ledger and returned in ``--json``: the configured
    # scope when there is one, else the ticket's own project as the backend
    # reports it. Preferring the configured value keeps the scoped path recording
    # byte-identical values to before #248.
    effective_project = project if project is not None else membership.project

    # 2 + 3 + 4. The triage write (load-bearing external effect): comment first,
    #        then the additive `decision`/`input`/`operator` label, then assign
    #        the ticket to the operator — so the explanation is on the ticket, the
    #        label says *why* it is held, and the assignment is the
    #        machine-readable "a human holds this" signal work-discovery skips on
    #        later ticks. The label's name is the `needs` kind's value.
    try:
        await client.post_comment(ticket, reason)
        await client.apply_label(ticket, needs.value)
        await client.assign_to_viewer(ticket)
    except TrackerNotFound as exc:
        raise _DeferError(
            f"ticket {ticket!r} not found on the tracker: {exc}",
            2,
            reason="ticket_not_found",
        ) from exc
    except TrackerRequestError as exc:
        raise _DeferError(
            f"failed to defer ticket {ticket!r} on the tracker: {exc}",
            2,
            reason="tracker_error",
        ) from exc
    except Exception as exc:  # noqa: BLE001 — map any transport surprise to a verb error
        raise _DeferError(
            f"unexpected error deferring ticket {ticket!r}: {exc}", 1
        ) from exc

    # 5. Record the defer in the ledger (audit trail) — after the Linear write.
    run_id = await _record_defer_event(
        db_path, ticket, reason, effective_project, needs.value
    )
    return DeferOutput(
        ticket=ticket, outcome="deferred", project=effective_project, run_id=run_id
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
        help="The hold kind: `decision` (a judgment call, the default), "
        "`input` (the operator must supply something the run cannot), or "
        "`operator` (an interactive session). Selects the label applied.",
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db)."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Defer a not-yet-actionable ticket — comment + the ``decision``/``input``/
    ``operator`` label + assign the operator + a ledger event."""
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
        where = result.project if result.project is not None else "the whole tracker queue"
        typer.echo(
            f"Deferred {ticket} on {where} — commented + "
            f"`{needs.value}` label + assigned to operator"
        )
