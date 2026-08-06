"""The one held-ticket transition seam — ``defer`` holds, ``release`` frees (#338).

``harness defer`` and ``harness release`` are two halves of one domain
operation: a ticket leaves the unattended queue into a human's hands, and later
comes back. Each was implemented as its own CLI module carrying a full copy of
the same shell — resolve the tracker and the configured queue, validate
membership, translate boundary exceptions into the verb error model, then run
three tracker mutations — plus a synthetic ``runs`` row and a ledger event.
Two copies of a rule is the threshold at which ``code-quality`` says extract,
and the copies had already drifted in wording while staying identical in
substance.

This module owns that shell once. The verb modules keep only what is genuinely
theirs: the Typer signature, the exactly-one-of ``--text``/``--file`` rule, and
their own presentation line.

**Why it lives under ``harness/cli/`` and not at the package root.** It raises
:class:`harness.cli._verb.VerbError`, and ``test_import_layering.py`` forbids a
module below the CLI from importing into it. The seam is a CLI-layer domain
module, not a root-level one.

Recorded decision — the ledger no longer records these transitions
------------------------------------------------------------------
Both verbs previously manufactured a terminal ``runs`` row
(``workflow_name='defer'|'release'``, ``status='closed'``, no worktree) purely
to satisfy the ``events.run_id`` foreign key, then hung one event off it. That
made a triage write indistinguishable from a build run in every ledger-backed
view, and nothing — not the close gate, not reclamation, not recovery — ever
read it. ADR 0009 had already declined to extend the same workaround to
run-less refusals, calling it "a workaround, not a pattern".

So a held-ticket transition now writes **nothing** to the ledger. The tracker
issue is the canonical record, and it is the stronger one: comment history,
label, assignment and project membership are server-side and append-only,
where a local SQLite row is writable by the same process that would forge it.

Historical rows are untouched — no migration, no deletion. ``EventType`` keeps
``defer`` and ``release`` (the emitter validates *writes*, never reads),
:class:`~harness.events.payloads.DeferEventData` /
:class:`~harness.events.payloads.ReleaseEventData` stay defined so past rows
parse, and ``stats_aggregate`` keeps both keys. What changes is that no live
emitter writes them.

Ordering, and why it differs between the two transitions
--------------------------------------------------------
Neither tracker API is transactional, so each bundle is ordered so that a
failure part-way through leaves the *safe* state, and the step that failed is
named rather than swallowed:

* **hold** — comment, then label, then assign. The explanation lands before the
  ticket is marked held.
* **release** — resolution into the body **first**, then remove the label, then
  unassign. The ticket stays visibly held until the answer is durable; the
  reverse order could drop the operator's decision while releasing the ticket.

A partial failure is reported with ``extra={"step": ...}`` and is never a
success: the command reports success only when every step completed.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from harness.cli._verb import VerbError
from harness.layers import tracker as tracker_backend
from harness.repo_config import repo_project
from harness.tracker import Tracker, tracker_client
from harness.tracker_errors import (
    TrackerConfigError,
    TrackerNotFound,
    TrackerRequestError,
)
from harness.tracker_queue import scope_phrase

__all__ = [
    "HeldTicketOutput",
    "HoldKind",
    "compose_resolution_body",
    "hold",
    "release",
]


class HoldKind(enum.StrEnum):
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

    Because the value is the label name and the enum is closed, the CLI can
    only ever write one of three labels — an arbitrary ``--needs`` string
    cannot reach the backend's resolve-or-create label primitive.
    """

    decision = "decision"
    input = "input"
    operator = "operator"


class HeldTicketOutput(BaseModel):
    """Typed result of a held-ticket transition — one model for both verbs.

    ``outcome`` is the field that says what happened: ``"deferred"`` /
    ``"released"`` / ``"skipped_no_tracker"``. ``project`` is the effective
    queue scope — ``repo.project`` when configured, else the ticket's own
    project as the backend reports it, else ``None`` (since #248 a successful
    transition on an unscoped repo may legitimately report ``None``, so this
    field no longer distinguishes success from the tracker-less no-op).

    ``run_id`` is a **deprecated compatibility field and is always ``None``**
    (#338). A held-ticket transition creates no run, so there is no id to
    report; the key is retained so an orchestrator already reading the envelope
    does not fail on a missing key. It is removable only in a breaking CLI
    release.
    """

    ticket: str
    outcome: str
    project: str | None
    run_id: str | None = None


#: The ``## Resolution`` section heading a release writes/replaces. A prior
#: release's section (and everything after it) is dropped before the fresh one
#: is appended, so re-running release is idempotent rather than accreting.
_RESOLUTION_HEADING = "## Resolution"


def compose_resolution_body(existing_body: str, resolution: str) -> str:
    """The issue body with a ``## Resolution`` section set to ``resolution``.

    Strips any prior ``## Resolution`` section (and everything after it —
    resolutions are always the last section a release writes) before appending
    the fresh one, so a repeated release replaces rather than duplicates.
    """
    base = re.split(
        rf"\n{re.escape(_RESOLUTION_HEADING)}\b.*", existing_body, flags=re.S
    )[0]
    return f"{base.rstrip()}\n\n{_RESOLUTION_HEADING}\n\n{resolution.strip()}\n"


@dataclass(frozen=True)
class _Words:
    """The two words a transition interpolates into its error messages.

    Both verbs' wording is preserved byte-for-byte from one code path, so the
    extraction is not observable in any message a caller already matches on.
    """

    verb: str  # "defer" / "release" — "refusing to <verb>", "failed to <verb>"
    gerund: str  # "deferring" / "releasing" — "unexpected error <gerund>"


@dataclass(frozen=True)
class _Bound:
    """A resolved transition context: whom to talk to, and about which queue."""

    client: Tracker
    project: str | None


#: One ordered mutation: its stable step name, and the coroutine that runs it.
_Step = tuple[str, Callable[[], Awaitable[None]]]


async def _bind(repo_root: Path, ticket: str, words: _Words) -> _Bound | None:
    """Resolve the tracker and validate queue membership, or raise.

    Returns ``None`` for a ``tracker: none`` repo — the caller's cue to emit a
    clean ``skipped_no_tracker`` no-op. Because both transitions enter through
    here, the membership gate cannot be present in one verb and missing in the
    other: it is the only thing standing between an arbitrary ticket
    identifier and three authenticated mutations.
    """
    # Only ``tracker: none`` is a clean tracker-less skip. A configured backend
    # (linear or github) resolves a real client below; a *misconfigured* one
    # (missing credential/config) fails loudly there, never silently no-ops.
    if tracker_backend(repo_root) == "none":
        return None

    # The scope is nullable (#248, mirroring #174): set → that one project;
    # unset → the backend's natural full queue. The seam owns what "unset"
    # means per backend, so this layer just passes the scope through.
    project = repo_project(repo_root)

    try:
        client = tracker_client(repo_root)
    except TrackerConfigError as exc:
        # A missing credential or config block is a config gap the routine can
        # branch on.
        raise VerbError(str(exc), 2, reason="tracker_config") from exc

    # The ``tracker: none`` guard above already returned, so a real client is
    # resolved here (linear or github, never ``None``).
    assert client is not None

    try:
        membership = await client.fetch_queue_membership(ticket, project=project)
    except TrackerNotFound as exc:
        raise VerbError(
            f"ticket {ticket!r} not found on the tracker", 2, reason="ticket_not_found"
        ) from exc
    except TrackerRequestError as exc:
        raise VerbError(
            f"failed to look up ticket {ticket!r} on the tracker: {exc}",
            2,
            reason="tracker_error",
        ) from exc

    if not membership.on_queue:
        raise VerbError(
            f"ticket {ticket!r} is not on {scope_phrase(project)} "
            f"(project: {membership.project!r}); refusing to {words.verb}",
            2,
            reason="not_on_build_queue",
        )

    # The value returned in ``--json``: the configured scope when there is one,
    # else the ticket's own project as the backend reports it.
    return _Bound(
        client=client,
        project=project if project is not None else membership.project,
    )


async def _run_steps(steps: tuple[_Step, ...], ticket: str, words: _Words) -> None:
    """Run ``steps`` in order, stopping at the first failure and naming it.

    The tracker APIs are not transactional, so a bundle can fail part-way. The
    honest report is *which* step failed — carried as ``extra={"step": ...}``
    so a caller branches on the field rather than parsing the message — and no
    success: a later step is never attempted after an earlier one raised, and
    the caller never sees a result object.
    """
    for name, run in steps:
        try:
            await run()
        except TrackerNotFound as exc:
            raise VerbError(
                f"ticket {ticket!r} not found on the tracker: {exc} (step: {name})",
                2,
                reason="ticket_not_found",
                extra={"step": name},
            ) from exc
        except TrackerRequestError as exc:
            raise VerbError(
                f"failed to {words.verb} ticket {ticket!r} on the tracker: {exc} "
                f"(step: {name})",
                2,
                reason="tracker_error",
                extra={"step": name},
            ) from exc
        except Exception as exc:  # noqa: BLE001 — map any transport surprise
            raise VerbError(
                f"unexpected error {words.gerund} ticket {ticket!r}: {exc} "
                f"(step: {name})",
                1,
                extra={"step": name},
            ) from exc


_HOLD_WORDS = _Words(verb="defer", gerund="deferring")
_RELEASE_WORDS = _Words(verb="release", gerund="releasing")


async def hold(
    repo_root: Path, ticket: str, *, reason: str, kind: HoldKind
) -> HeldTicketOutput:
    """Hold ``ticket``: comment the reason, apply the hold label, assign.

    The order is load-bearing: the explanation is on the ticket before it is
    marked held, so a failure part-way never leaves a ticket held with no
    stated reason.

    Idempotent in the two places that matter — ``apply_label`` is additive
    (never a full-set replace, so unrelated labels survive) and assignment
    converges. A repeated hold *does* append a second comment, deliberately:
    a repeated reason is new information, and the comment stream is history.
    """
    bound = await _bind(repo_root, ticket, _HOLD_WORDS)
    if bound is None:
        return HeldTicketOutput(
            ticket=ticket, outcome="skipped_no_tracker", project=None
        )

    client = bound.client
    await _run_steps(
        (
            ("comment", lambda: client.post_comment(ticket, reason)),
            ("label", lambda: client.apply_label(ticket, kind.value)),
            ("assign", lambda: client.assign_to_viewer(ticket)),
        ),
        ticket,
        _HOLD_WORDS,
    )
    return HeldTicketOutput(ticket=ticket, outcome="deferred", project=bound.project)


async def release(
    repo_root: Path, ticket: str, *, resolution: str, kind: HoldKind
) -> HeldTicketOutput:
    """Release ``ticket``: persist the resolution, drop the label, unassign.

    The resolution is written **first** and the operator unassigned **last**.
    Assignment is the authoritative "a human holds this" signal
    ``work-discovery`` reads, so clearing it before the answer is durable could
    return a ticket to the queue with the decision lost. Failing part-way here
    leaves the ticket visibly held, which is the recoverable state.
    """
    bound = await _bind(repo_root, ticket, _RELEASE_WORDS)
    if bound is None:
        return HeldTicketOutput(
            ticket=ticket, outcome="skipped_no_tracker", project=None
        )

    client = bound.client

    async def _write_resolution() -> None:
        issue = await client.fetch_issue(ticket)
        body = compose_resolution_body(issue.get("description") or "", resolution)
        await client.update_issue_body(ticket, body)

    await _run_steps(
        (
            ("resolution", _write_resolution),
            ("label", lambda: client.remove_label(ticket, kind.value)),
            ("unassign", lambda: client.unassign_viewer(ticket)),
        ),
        ticket,
        _RELEASE_WORDS,
    )
    return HeldTicketOutput(ticket=ticket, outcome="released", project=bound.project)
