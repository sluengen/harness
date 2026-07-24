"""``harness release <ticket>`` — the decision-sweep return write as an audited
verb (#193, the ``defer`` shape in reverse).

``/decision`` (the versioned sweep that drains tickets held for a judgment
call, ADR 0006) needs to release a resolved ticket back to the Build queue.
That release is the load-bearing step, not a formality: it must write the
resolution into the ticket's change spec (not leave it only in a comment
thread), remove the hold label, and — critically — **unassign the operator**,
because ``work-discovery`` treats assignment as the authoritative "a human
holds this" skip signal. A sweep that records an answer without unassigning
leaves the ticket held forever — the exact failure mode the ad-hoc prompt this
replaces has today. Like ``defer``, this is a bounded, named verb rather than a
hand-rolled tracker write, so the release binds cleanly to its
``autoMode.allow`` clause and is auditable in the runs/events ledger.

What ``release`` does, for a ticket on this repo's Build queue
(``repo.project``):

1. **Verify Build-queue membership.** Read the ticket's project; a ticket not
   found, or found but on another project, is refused (exit 2) with a
   structured ``reason`` — no write, no event.
2. **Write the resolution into the change spec.** Fetch the current issue body
   and append (or replace, if a prior release already left one) a
   ``## Resolution`` section carrying the resolution text, then
   ``update_issue_body``. This is deliberately the *first* write: a crash
   between steps leaves the ticket still held (label + assignment intact) but
   never silently drops the answer.
3. **Remove the hold label** (``remove_label`` — additive removal of the
   ``needs`` kind's label; a ticket already missing it is an idempotent no-op).
4. **Unassign the operator** (``unassign_viewer``) — the load-bearing step.
5. **Record a ``release`` event** in the runs/events ledger (ticket, needs
   kind, timestamp), so the release is auditable like every other verb.

Tracker-less repo (``layers.linear: false``): a **clean no-op** (exit 0, no
write), consistent with the other verbs — there is no tracker to release on.

Exit codes (mirrors ``defer``):
* 0  — released (or a tracker-less clean no-op).
* 2  — invocation / refusal: neither/both of ``--resolution`` /
       ``--resolution-file``, ``repo.project`` unconfigured, the ticket not
       found on the tracker, or the ticket not on the Build queue.
* 1  — unexpected error (DB failure, or an unexpected tracker transport error).
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import typer
from pydantic import BaseModel

from harness._time import iso_z
from harness.cli._query_common import _resolve_db_path
from harness.cli._verb import VerbError, run_verb
from harness.cli.defer import DeferNeeds
from harness.events.emitter import EventEmitter
from harness.events.payloads import ReleaseEventData
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

__all__ = ["ReleaseOutput", "release_command"]

#: The ``## Resolution`` section heading a release writes/replaces. A prior
#: release's section (and everything after it) is dropped before the fresh one
#: is appended, so re-running release is idempotent rather than accreting.
_RESOLUTION_HEADING = "## Resolution"


def _compose_body(existing_body: str, resolution: str) -> str:
    """The issue body with a ``## Resolution`` section set to ``resolution``.

    Strips any prior ``## Resolution`` section (and everything after it —
    resolutions are always the last section a release writes) before
    appending the fresh one, so a repeated release replaces rather than
    duplicates.
    """
    base = re.split(rf"\n{re.escape(_RESOLUTION_HEADING)}\b.*", existing_body, flags=re.S)[0]
    return f"{base.rstrip()}\n\n{_RESOLUTION_HEADING}\n\n{resolution.strip()}\n"


class _ReleaseError(VerbError):
    """``release``'s control-flow exception — a :class:`VerbError` (mirrors ``defer``)."""


class ReleaseOutput(BaseModel):
    """Typed result of a ``release`` — like every sibling verb.

    ``run_id`` is the synthetic run row anchoring the ``release`` event, or
    ``None`` for a tracker-less no-op; ``project`` is the Build queue the
    ticket was bound to (``None`` tracker-less)."""

    ticket: str
    outcome: str
    project: str | None
    run_id: str | None


async def _record_release_event(
    db_path: Path, ticket: str, project: str, needs: str
) -> str:
    """Anchor a ``release`` event in the ledger and return its run id.

    Mirrors ``defer``'s ``_record_defer_event``: a release has no build run, so
    it gets its own terminal run row (``workflow_name='release'``,
    ``status='closed'``) to carry the audit event, keeping it clear of
    ``idx_runs_ticket_open`` so a later ``harness start`` on the same ticket is
    never blocked.
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
            (run_id, "release", 0, "closed", "{}", "{}", ticket, now, now),
        )
        await conn.commit()
    await EventEmitter(db_path).emit(
        run_id=run_id,
        event_type="release",
        data=ReleaseEventData(
            run_id=run_id,
            ticket=ticket,
            project=project,
            needs=needs,
            released_at=now,
        ).model_dump(),
    )
    return run_id


async def _run_release(
    db_path: Path,
    ticket: str,
    resolution: str,
    *,
    needs: DeferNeeds,
    repo_root: Path,
) -> ReleaseOutput:
    """Release ``ticket``; raise :class:`_ReleaseError` on refusal/error.

    Tracker-less (``layers.linear: false``) it is a clean no-op — there is no
    tracker to write to, so the honest outcome is "skipped".
    """
    if tracker_backend(repo_root) == "none":
        return ReleaseOutput(
            ticket=ticket, outcome="skipped_no_tracker", project=None, run_id=None
        )

    project = repo_project(repo_root)
    if not project:
        raise _ReleaseError(
            "repo.project is not configured in CONTEXT.md; cannot bind the "
            "release to a Build queue",
            2,
            reason="no_project_configured",
        )

    try:
        client = tracker_client(repo_root)
    except TrackerConfigError as exc:
        raise _ReleaseError(str(exc), 2, reason="tracker_config") from exc

    assert client is not None

    # 1. Verify the ticket is on this repo's Build queue before any write.
    try:
        ticket_project = await client.fetch_issue_project(ticket)
    except TrackerNotFound as exc:
        raise _ReleaseError(
            f"ticket {ticket!r} not found on the tracker", 2, reason="ticket_not_found"
        ) from exc
    except TrackerRequestError as exc:
        raise _ReleaseError(
            f"failed to look up ticket {ticket!r} on the tracker: {exc}",
            2,
            reason="tracker_error",
        ) from exc

    if ticket_project != project:
        raise _ReleaseError(
            f"ticket {ticket!r} is not on the Build queue {project!r} "
            f"(project: {ticket_project!r}); refusing to release",
            2,
            reason="not_on_build_queue",
        )

    # 2 + 3 + 4. The release write (load-bearing external effect): the
    #        resolution lands in the change spec first, then the hold label is
    #        removed, then the operator is unassigned — the authoritative
    #        "a human holds this" signal work-discovery reads, cleared last so
    #        a mid-sequence failure leaves the ticket still (visibly) held
    #        rather than silently dropped with no recorded answer.
    try:
        issue = await client.fetch_issue(ticket)
        new_body = _compose_body(issue.get("description") or "", resolution)
        await client.update_issue_body(ticket, new_body)
        await client.remove_label(ticket, needs.value)
        await client.unassign_viewer(ticket)
    except TrackerNotFound as exc:
        raise _ReleaseError(
            f"ticket {ticket!r} not found on the tracker: {exc}",
            2,
            reason="ticket_not_found",
        ) from exc
    except TrackerRequestError as exc:
        raise _ReleaseError(
            f"failed to release ticket {ticket!r} on the tracker: {exc}",
            2,
            reason="tracker_error",
        ) from exc
    except Exception as exc:  # noqa: BLE001 — map any transport surprise to a verb error
        raise _ReleaseError(
            f"unexpected error releasing ticket {ticket!r}: {exc}", 1
        ) from exc

    # 5. Record the release in the ledger (audit trail) — after the tracker write.
    run_id = await _record_release_event(db_path, ticket, project, needs.value)
    return ReleaseOutput(
        ticket=ticket, outcome="released", project=project, run_id=run_id
    )


def _resolve_resolution(resolution: str | None, resolution_file: Path | None) -> str:
    """Exactly one of ``--resolution`` / ``--resolution-file`` supplies the body.

    Raises :class:`_ReleaseError` (exit 2) when neither or both is given, or
    when ``--resolution-file`` cannot be read.
    """
    if (resolution is None) == (resolution_file is None):
        raise _ReleaseError(
            "provide exactly one of --resolution <text> or --resolution-file <path>",
            2,
        )
    if resolution is not None:
        return resolution
    assert resolution_file is not None
    try:
        return resolution_file.read_text()
    except OSError as exc:
        raise _ReleaseError(
            f"could not read --resolution-file {str(resolution_file)!r}: {exc}", 2
        ) from exc


def release_command(
    ticket: str = typer.Argument(..., help="Tracker ticket identifier (e.g. CAL-193, 193)."),
    resolution: str | None = typer.Option(
        None, "--resolution", help="The operator's call, written into the change spec."
    ),
    resolution_file: Path | None = typer.Option(
        None,
        "--resolution-file",
        help="Read the resolution from a file (for a long body).",
    ),
    needs: DeferNeeds = typer.Option(
        DeferNeeds.decision,
        "--needs",
        help="The hold kind being released: `decision` (the default), `input`, "
        "or `operator`. Selects the label removed.",
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db)."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Release a held ticket: write the resolution into the change spec, remove
    the hold label, unassign the operator, and record a ledger event."""
    db_path = _resolve_db_path(db)
    repo_root = Path.cwd()

    def _do() -> ReleaseOutput:
        body = _resolve_resolution(resolution, resolution_file)
        return asyncio.run(
            _run_release(db_path, ticket, body, needs=needs, repo_root=repo_root)
        )

    result = run_verb(_do, json_output=json_output)

    if json_output:
        typer.echo(result.model_dump_json())
        return

    if result.outcome == "skipped_no_tracker":
        typer.echo(f"release {ticket}: no tracker configured (no-op)")
    else:
        typer.echo(
            f"Released {ticket} on {result.project} — resolution written + "
            f"`{needs.value}` label removed + unassigned"
        )
