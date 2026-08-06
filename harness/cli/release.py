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
replaces has today.

What ``release`` does, for a ticket on this repo's Build queue:

1. **Verify Build-queue membership** — refusing a ticket not found, or found
   but off the queue (exit 2), before any write.
2. **Write the resolution into the change spec** — appending (or replacing, if
   a prior release already left one) a ``## Resolution`` section.
3. **Remove the hold label** (only the selected kind; a ticket already missing
   it is an idempotent no-op).
4. **Unassign the operator** — the load-bearing step, done last.

Since #338 the transition itself — the membership gate, the ordered bundle
(including the rule that the resolution is durable *before* the ticket stops
being held), and the translation of tracker failures into this verb's error
model — lives in :mod:`harness.cli.held_ticket`, shared with ``defer``. This
module is the CLI adapter: flags in, one seam call, one presentation line out.

**No ledger write.** A held-ticket transition records nothing in
``runs``/``events``; the tracker issue is the canonical audit trail (see the
seam module's recorded decision). ``--db`` and the ``run_id`` field are retained
as deprecated compatibility surface and are inert.

Exit codes (mirrors ``defer``):
* 0  — released (or a tracker-less clean no-op).
* 2  — invocation / refusal: neither/both of ``--resolution`` /
       ``--resolution-file``, a missing tracker credential/config, the ticket
       not found, or the ticket not on the Build queue. An absent
       ``repo.project`` is **not** a refusal — it means the whole tracker queue.
* 1  — unexpected error (an unexpected tracker transport error).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from harness.cli._repo import REPO_OPTION, repo_arg_or_cwd
from harness.cli._verb import VerbError, run_verb
from harness.cli.held_ticket import HeldTicketOutput, HoldKind, release

#: Retained name. ``ReleaseOutput`` was this module's own model before #338
#: unified it with ``defer``'s field-identical one in the shared seam.
ReleaseOutput = HeldTicketOutput

__all__ = ["ReleaseOutput", "release_command"]


def _resolve_resolution(resolution: str | None, resolution_file: Path | None) -> str:
    """Exactly one of ``--resolution`` / ``--resolution-file`` supplies the body.

    Raises :class:`VerbError` (exit 2) when neither or both is given, or when
    ``--resolution-file`` cannot be read.
    """
    if (resolution is None) == (resolution_file is None):
        raise VerbError(
            "provide exactly one of --resolution <text> or --resolution-file <path>",
            2,
        )
    if resolution is not None:
        return resolution
    assert resolution_file is not None
    try:
        return resolution_file.read_text()
    except OSError as exc:
        raise VerbError(
            f"could not read --resolution-file {str(resolution_file)!r}: {exc}", 2
        ) from exc


def release_command(
    ticket: str = typer.Argument(..., help="Tracker ticket identifier (e.g. 193)."),
    resolution: str | None = typer.Option(
        None, "--resolution", help="The operator's call, written into the change spec."
    ),
    resolution_file: Path | None = typer.Option(
        None,
        "--resolution-file",
        help="Read the resolution from a file (for a long body).",
    ),
    needs: HoldKind = typer.Option(
        HoldKind.decision,
        "--needs",
        help="The hold kind being released: `decision` (the default), `input`, "
        "or `operator`. Selects the label removed.",
    ),
    repo: Path | None = REPO_OPTION,
    db: Path | None = typer.Option(
        None,
        "--db",
        help="Deprecated and ignored: a release writes no ledger row (#338).",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Release a held ticket: write the resolution into the change spec, remove
    the hold label, and unassign the operator."""
    repo_root = repo_arg_or_cwd(repo)

    def _do() -> HeldTicketOutput:
        body = _resolve_resolution(resolution, resolution_file)
        return asyncio.run(release(repo_root, ticket, resolution=body, kind=needs))

    result = run_verb(_do, json_output=json_output)

    if json_output:
        typer.echo(result.model_dump_json())
        return

    if result.outcome == "skipped_no_tracker":
        typer.echo(f"release {ticket}: no tracker configured (no-op)")
    else:
        where = result.project if result.project is not None else "the whole tracker queue"
        typer.echo(
            f"Released {ticket} on {where} — resolution written + "
            f"`{needs.value}` label removed + unassigned"
        )
