"""``harness defer <ticket>`` — the triage write as an audited verb (CAL-1143).

The unattended Build routine's triage step — ``work-discovery`` judging a picked
ticket not-yet-actionable and recording "comment + apply the ``decision`` label"
— was the one write the routine **hand-rolled as raw GraphQL** (via the ``linear``
skill), because it is not a build-lifecycle transition and had no verb.
Everything that touches the gate (``start`` / ``review`` / ``close`` /
``reclaim``) is already a verb; triage was not. That left it opaque and made it
the one write the autonomous auto-mode classifier intermittently blocked — a
bounded, named verb binds to its ``autoMode.allow`` clause far more reliably
than a ``docker run python3 <GraphQL script>``.

What ``defer`` does, for a ticket on this repo's Build queue:

1. **Verify Build-queue membership** — ``repo.project`` when configured, the
   backend's natural full queue when it is not (#248) — refusing a ticket that
   is not found, or found but off the queue (exit 2), before any write.
2. **Post the reason as a comment.**
3. **Additively apply the hold label** — ``decision`` / ``input`` / ``operator``,
   selected by ``--needs`` (never a full-set replace, so existing labels
   survive). The label says *why* the ticket is held (ADR 0006).
4. **Assign the ticket to the operator.** Agents have no tracker identity, so an
   assignee at all is the machine-readable "a human holds this" signal
   ``work-discovery`` skips on later ticks; the label only explains it.

Since #338 the transition itself — the membership gate, the ordered bundle, and
the translation of tracker failures into this verb's error model — lives in
:mod:`harness.cli.held_ticket`, shared with ``release``. This module is the CLI
adapter: flags in, one seam call, one presentation line out.

**No ledger write.** A held-ticket transition records nothing in
``runs``/``events``; the tracker issue is the canonical audit trail (see the
seam module's recorded decision). ``--db`` and the ``run_id`` field are retained
as deprecated compatibility surface and are inert.

Exit codes (SPEC §11):
* 0  — deferred (or a tracker-less clean no-op).
* 2  — invocation / refusal: neither/both of ``--reason`` / ``--reason-file``,
       a missing tracker credential/config, the ticket not found, or the ticket
       not on the Build queue. An absent ``repo.project`` is **not** a refusal —
       it means the whole tracker queue (#248).
* 1  — unexpected error (an unexpected tracker transport error).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from harness.cli._repo import REPO_OPTION, repo_arg_or_cwd
from harness.cli._verb import VerbError, run_verb
from harness.cli.held_ticket import HeldTicketOutput, HoldKind, hold

#: Retained names. ``DeferNeeds`` / ``DeferOutput`` were this module's own types
#: before #338 moved them into the shared seam; the aliases keep any importer
#: and this module's ``__all__`` working without a second definition.
DeferNeeds = HoldKind
DeferOutput = HeldTicketOutput

__all__ = ["DeferNeeds", "DeferOutput", "defer_command"]


def _resolve_reason(reason: str | None, reason_file: Path | None) -> str:
    """Exactly one of ``--reason`` / ``--reason-file`` supplies the body.

    Raises :class:`VerbError` (exit 2) when neither or both is given, or when
    ``--reason-file`` cannot be read.
    """
    if (reason is None) == (reason_file is None):
        raise VerbError(
            "provide exactly one of --reason <text> or --reason-file <path>", 2
        )
    if reason is not None:
        return reason
    assert reason_file is not None
    try:
        return reason_file.read_text()
    except OSError as exc:
        raise VerbError(
            f"could not read --reason-file {str(reason_file)!r}: {exc}", 2
        ) from exc


def defer_command(
    ticket: str = typer.Argument(..., help="Tracker ticket identifier (e.g. 338)."),
    reason: str | None = typer.Option(
        None, "--reason", help="Triage rationale posted as a comment."
    ),
    reason_file: Path | None = typer.Option(
        None,
        "--reason-file",
        help="Read the triage rationale from a file (for long bodies).",
    ),
    needs: HoldKind = typer.Option(
        HoldKind.decision,
        "--needs",
        help="The hold kind: `decision` (a judgment call, the default), "
        "`input` (the operator must supply something the run cannot), or "
        "`operator` (an interactive session). Selects the label applied.",
    ),
    repo: Path | None = REPO_OPTION,
    db: Path | None = typer.Option(
        None,
        "--db",
        help="Deprecated and ignored: a defer writes no ledger row (#338).",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Defer a not-yet-actionable ticket — comment + the ``decision``/``input``/
    ``operator`` label + assign the operator."""
    repo_root = repo_arg_or_cwd(repo)

    def _do() -> HeldTicketOutput:
        body = _resolve_reason(reason, reason_file)
        return asyncio.run(hold(repo_root, ticket, reason=body, kind=needs))

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
