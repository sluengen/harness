"""The design stage's tracker I/O — read the spec in, post the artifact out.

The ``design`` verb touches the tracker at exactly two points, and they bracket
the engine run: it **reads** the ticket's title and description (the spec the
design answers to) before designing, and **posts** the finished design back as a
marked comment after. Both are the tracker boundary, not verb orchestration, so
they live here and :mod:`harness.cli.design` keeps only the flow between them.

Since #258 there is a third, which is why the module rather than the verb is the
right home for it: ADR 0008's adopt path **reads back** a prior design comment
(:func:`fetch_prior_design`), so the comment is now something this seam both
writes and reads.

Split out of the verb in #211 so a brand-new module was not born over the repo's
500-line hard limit with a ``# size:`` justification papering over a seam that
plainly existed (``code-quality`` Part C).

The layering is deliberate one-way: this module raises tracker-shaped failures
(:class:`TicketSpecUnavailableError`) and knows nothing of exit codes or ``reason``
tags. The verb owns that vocabulary and translates — so the exit-code contract
stays in one place and there is no import cycle back into the verb.
"""

from __future__ import annotations

from pathlib import Path

from harness._time import iso_z
from harness.design_marker import ParsedDesign, format_design_comment, parse_design_comment
from harness.state import store
from harness.tracker import tracker_client
from harness.tracker_errors import (
    TrackerConfigError,
    TrackerNotFound,
    TrackerRequestError,
)

__all__ = [
    "TicketSpecUnavailableError",
    "TicketCommentFailedError",
    "fetch_prior_design",
    "fetch_ticket_spec",
    "post_design_comment",
    "read_run_ticket",
]


class TicketSpecUnavailableError(Exception):
    """The ticket's spec could not be read, so there is nothing to design against.

    Carries a human ``detail`` naming which way it failed — no tracker, no
    ticket, an unresolvable client, or a failed fetch. The verb maps this to its
    own ``no_ticket_spec`` degrade-and-record path (ADR 0007 D4).
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class TicketCommentFailedError(Exception):
    """The design was produced but could not be posted to the ticket.

    Distinct from :class:`TicketSpecUnavailableError`: the design *exists*, so this is
    not a failure to design — it is a failure to publish the artifact, which the
    verb surfaces as an error rather than a recorded design attempt.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


async def read_run_ticket(db_path: Path, run_id: str) -> str | None:
    """The ticket identifier recorded on the run row, or ``None``."""
    if not db_path.exists():
        return None
    async with (
        store.connect(db_path) as conn,
        conn.execute("SELECT ticket FROM runs WHERE run_id = ?", (run_id,)) as cur,
    ):
        row = await cur.fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0])


async def fetch_prior_design(repo_root: Path, ticket: str | None) -> ParsedDesign | None:
    """The design recovered from the ticket's latest design comment, or ``None``.

    The read half of the comment contract this module already writes. Returns
    what the comment *claims* — the parser never authenticates (#257) — so the
    caller re-hashes the recovered text and checks the claim against the ledger
    before adopting anything.

    **Best-effort, unlike :func:`fetch_ticket_spec`.** That fetch is load-bearing
    (no spec, no design), so its failures raise. This one is an optimisation: a
    tracker-less repo, an unresolvable client, a missing ticket, or a failed
    fetch all mean "no prior design to adopt", and the verb then runs the engine
    exactly as it did before #258. Costing a run its Opus saving is the right
    price for an outage; costing it the ability to design is not.
    """
    if ticket is None:
        return None
    try:
        client = tracker_client(repo_root)
    except TrackerConfigError:
        return None
    if client is None:
        return None
    try:
        body = await client.fetch_design_comment(ticket)
    except (TrackerNotFound, TrackerRequestError):
        return None
    return None if body is None else parse_design_comment(body)


async def fetch_ticket_spec(repo_root: Path, ticket: str | None) -> tuple[str, str]:
    """The ticket's ``(title, description)``, or raise :class:`TicketSpecUnavailableError`.

    Unlike ``review``'s tracker calls — bookkeeping a verdict must survive — this
    fetch is **load-bearing**: the ticket is the entire spec the design answers
    to, and ``start`` persists neither field on the run row. A tracker-less repo,
    an unresolvable tracker config, a missing ticket, or a fetch failure therefore
    all leave nothing to design against.

    Designing anyway would produce a confidently ungrounded design and post it to
    a ticket as though it answered one, so every one of those cases raises here
    and the verb degrades the same way it does for an engine failure — a recorded
    ``failed`` attempt and no comment. The ``no_design`` check (#212) is satisfied
    by that attempt, so a tracker-less repo's build is never wedged; it just
    builds without a design.
    """
    if ticket is None:
        raise TicketSpecUnavailableError(
            "the run carries no ticket, so there is no spec to design against"
        )
    try:
        client = tracker_client(repo_root)
    except TrackerConfigError as exc:
        raise TicketSpecUnavailableError(
            f"the tracker could not be resolved, so ticket {ticket}'s spec is unreadable: {exc}"
        ) from exc
    if client is None:
        raise TicketSpecUnavailableError(
            f"this repo is tracker-less, so ticket {ticket}'s spec is unreadable"
        )
    try:
        issue = await client.fetch_issue(ticket)
    except (TrackerNotFound, TrackerRequestError) as exc:
        raise TicketSpecUnavailableError(f"failed to fetch ticket {ticket}: {exc}") from exc
    return str(issue.get("title") or ""), str(issue.get("description") or "")


async def post_design_comment(
    repo_root: Path,
    ticket: str | None,
    *,
    run_id: str,
    design_markdown: str,
    design_hash: str,
    grounded_sha: str,
) -> None:
    """Post the design to the ticket as a marked comment.

    Reached only on the success path, where :func:`fetch_ticket_spec` has already
    proved both the ticket and a resolvable client — so the resolution cannot
    fail here. A *transport* failure on the post itself raises
    :class:`TicketCommentFailedError` rather than being swallowed: the comment is the
    artifact ADR 0007 specifies, so losing it silently would leave a run whose
    ledger claims a design nobody can read.
    """
    assert ticket is not None  # fetch_ticket_spec refuses a run without one
    client = tracker_client(repo_root)
    assert client is not None  # likewise: a tracker-less run never gets here
    body = format_design_comment(
        run_id,
        design_markdown,
        design_hash=design_hash,
        grounded_sha=grounded_sha,
        when=iso_z(),
    )
    try:
        await client.post_comment(ticket, body)
    except (TrackerNotFound, TrackerRequestError) as exc:
        raise TicketCommentFailedError(
            f"the design was produced but could not be posted to ticket {ticket}: "
            f"{exc}. Nothing was recorded; re-run `harness design` once the "
            f"tracker is reachable."
        ) from exc
