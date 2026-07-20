"""``harness start <TICKET>`` — open a run (ticket → In Progress, worktree, ledger row).

This command is the front door for agent-led work under the harness-as-tool
model.  One call does all the setup an orchestrating agent needs before it
starts implementing:

1. Validates that ``LINEAR_API_KEY`` is set.
2. Fetches the Linear issue and normalises it to a compact context blob.
3. Resolves the canonical ticket identifier from the Linear payload (so casing
   or alias variations cannot open duplicate runs).
4. Checks for an already-open run for the same ticket (refuses to open a
   second rather than silently create a duplicate).
5. Generates a ULID run_id and creates a git worktree at
   ``.worktrees/harness/<run_id>/`` on branch ``harness/<run_id>``. A clean start
   bases the worktree off ``origin/<base>`` when it resolves — the tip ``close``
   pushes, since it no longer advances the local base (CAL-1154, Option 1) —
   falling back to the local ``base`` for offline / no-origin repos. With
   ``--resume``, a reclaimed ticket carrying a checkpoint-pushed WIP branch is
   continued from that branch (fetch + base the worktree on it) instead; the
   recorded ``base_branch`` (the merge target) stays ``base`` either way so
   ``close``'s HEAD-bound gate keeps the run safe (CAL-739).
6. Inserts an ``open`` row into ``runs`` (``status='open'``).
7. Transitions the ticket to In Progress (last — the only non-local side
   effect; local state is rolled back if it fails).
8. Prints the run context as JSON.

**Tracker-less repos (CAL-1104).** Steps 1–3 and 7 are the tracker's half of the
flow; a repo whose CONTEXT.md sets ``layers.linear: false`` has no tracker, so
they are skipped entirely — no key is required, nothing is fetched, and no
transition is made. The ``<TICKET>`` argument is then an **opaque run
identifier**: it keys the open-run index verbatim (so step 4's duplicate guard
still holds) and appears in the output with every tracker-supplied field
(``title`` / ``description`` / ``url`` / ``id``) left ``None``. ``--resume``
degrades to a clean start, both of its sources being tracker comments. The layer
defaults **on**, so a repo that has not opted out behaves exactly as before.

The whole flow runs inside a single ``asyncio.run`` event loop so all I/O —
Linear HTTP, SQLite, worktree git — is awaited rather than spread across
repeated ``asyncio.run`` calls.

Exit codes (SPEC §11):
* 0   — success; JSON context printed (a new run, or the existing run
        surfaced for a duplicate start of the same ticket — step 4).
* 1   — unexpected error (worktree creation failed, DB error, etc.).
* 2   — invocation error: missing ``LINEAR_API_KEY``, missing ticket, Linear unreachable.

The ``--json`` flag is accepted for forward-compatibility but JSON is always
the output format — the command has no human-readable fallback because it is
designed for machine consumption.
"""

from __future__ import annotations

import asyncio
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
import typer
from pydantic import BaseModel

from harness.cli._git import (
    NETWORK_GIT_TIMEOUT_SECONDS,
    preferred_base_ref,
    resolve_base_branch,
    run_git,
    teardown_worktree,
)
from harness.cli._repo import resolve_repo_root_or_exit, resolve_verb_db_path
from harness.cli._verb import VerbError, run_verb
from harness.identity import generate_run_id
from harness.identity import worktree_branch as _branch_for
from harness.layers import linear_enabled, tracker_config_error
from harness.linear import (
    LinearClient,
    LinearConfigError,
    LinearNotFound,
    LinearRequestError,
    linear_api_key,
)
from harness.state import store
from harness.worktree import WorktreeNode, WorktreeNodeError

# size: one cohesive verb — the start orchestration plus the Linear/resume
# helpers and the DB + worktree rollback that keep its side effects atomic,
# which splitting would only scatter across files. CAL-1007 un-swallowed the
# two silent DB error paths (surface a failed read, warn on a failed rollback)
# inline, pushing it just over the 500-line limit.

__all__ = ["start_command", "StartOutput", "TicketContext"]

# ---------------------------------------------------------------------------
# Context-economy: cap the description field to prevent unbounded blobs.
# Descriptions longer than this limit are truncated with a sentinel suffix.
# The limit is chosen to cover all realistic ticket descriptions while
# keeping the JSON context blob firmly within the agent's context budget.
# ---------------------------------------------------------------------------
TICKET_DESCRIPTION_MAX_CHARS = 4096
_TRUNCATION_SUFFIX = "... [truncated]"


class TicketContext(BaseModel):
    """Compact Linear ticket context included in the run output."""

    id: str | None = None
    identifier: str
    title: str | None = None
    description: str | None = None
    url: str | None = None


class StartOutput(BaseModel):
    """JSON output schema for ``harness start``.

    Both the new-run path and the existing-run path emit this model so
    repeated calls share a single stable schema.
    """

    run_id: str
    ticket: TicketContext
    worktree_path: str
    worktree_branch: str
    base_branch: str


class _StartError(VerbError):
    """``start``'s control-flow exception — a :class:`VerbError` (CAL-1013).

    Raised inside the async orchestration and translated to a Typer ``Exit`` by
    :func:`start_command` via :func:`run_verb`. The ``(message, code)`` carrier
    is inherited from the base; ``start`` never sets a ``reason``.
    """


def start_command(
    ticket: str = typer.Argument(..., help="Linear ticket identifier (e.g. CAL-570)."),
    base: str | None = typer.Option(
        None,
        "--base",
        help="Base branch for the worktree (the merge target). Defaults to the "
        "repo's CONTEXT.md ``branches.integration``, then its origin default "
        "branch, then ``dev`` (CAL-1106).",
    ),
    resume: bool = typer.Option(  # noqa: B008
        False,
        "--resume",
        help="Resume a reclaimed ticket from its preserved WIP branch when one "
        "exists (fetch + continue); fall back to a clean start otherwise.",
    ),
    repo: Path = typer.Option(  # noqa: B008
        Path("."),
        "--repo",
        help="Repo root for git worktree operations. Defaults to CWD.",
    ),
    db: Path | None = typer.Option(  # noqa: B008
        None,
        "--db",
        help="Path to harness.db (defaults to .harness/harness.db under --repo).",
    ),
    json_output: bool = typer.Option(  # noqa: B008
        True,
        "--json/--no-json",
        help="Emit machine-readable JSON (default: on).",
    ),
) -> None:
    """Open a run: validate ticket, transition to In Progress, create worktree, record ledger."""
    repo_root = resolve_repo_root_or_exit(repo)
    db_path = resolve_verb_db_path(db, repo_root)
    # Resolve the base branch: an explicit --base wins, else the repo's configured
    # integration branch, else its origin default, else "dev" (CAL-1106). Done here
    # (sync, with repo_root in hand) so the async flow receives a concrete branch.
    resolved_base = resolve_base_branch(repo_root, base)

    output = run_verb(
        lambda: asyncio.run(
            _run_start(
                ticket=ticket,
                base=resolved_base,
                resume=resume,
                repo_root=repo_root,
                db_path=db_path,
            )
        ),
        json_output=json_output,
    )

    if json_output:
        typer.echo(output.model_dump_json())
    else:
        typer.echo(f"opened run {output.run_id} for {output.ticket.identifier}")


# ---------------------------------------------------------------------------
# Async orchestration — one event loop for all I/O.
# ---------------------------------------------------------------------------


async def _run_start(
    *,
    ticket: str,
    base: str,
    resume: bool = False,
    repo_root: Path,
    db_path: Path,
) -> StartOutput:
    """Drive the full start flow; raise :class:`_StartError` on any failure."""
    # 0. Read the tracker switch (CAL-1104, CAL-1164). ``tracker: none`` (or the
    # ``layers.linear: false`` back-compat) means the repo has no tracker, so
    # steps 1–3 have nothing to talk to: the argument is an opaque run identifier
    # rather than a ticket to fetch. The switch defaults on, so a repo that has
    # not opted out is unaffected. First reject an incoherent switch/address pair
    # up front, before any key check or side effect — a run must not start on a
    # config that contradicts itself.
    config_error = tracker_config_error(repo_root)
    if config_error is not None:
        raise _StartError(config_error, 2)
    tracker = linear_enabled(repo_root)

    client: LinearClient | None = None
    if tracker:
        # 1. Validate Linear API key is present.
        try:
            api_key = linear_api_key()
        except LinearConfigError as exc:
            raise _StartError(str(exc), 2) from exc

        client = LinearClient(api_key=api_key)

        # 2. Fetch ticket from Linear.
        try:
            ticket_data = await client.fetch_issue(ticket)
        except LinearNotFound as exc:
            raise _StartError(str(exc), 2) from exc
        except LinearRequestError as exc:
            raise _StartError(f"Linear API error: {exc}", 2) from exc

        # 3. Resolve the canonical identifier from the Linear payload.  Using the
        # caller-supplied string would let "cal-570" and "CAL-570" open two runs
        # for the same issue; the Linear identifier is the single source of truth.
        canonical = ticket_data.get("identifier") or ""
        if not canonical:
            raise _StartError(f"Linear returned no identifier for {ticket!r}", 2)
    else:
        # Tracker-less: with no payload to canonicalise against, the argument
        # *is* the identifier — taken verbatim so it still keys the open-run
        # index (the duplicate-start guard holds), and carried into the output
        # with every tracker-supplied field left unset rather than invented.
        ticket_data = {"identifier": ticket}
        canonical = ticket

    # 4. Check for an existing open run for this ticket (keyed on canonical).
    existing = await _find_open_run(db_path, canonical, ticket_data)
    if existing is not None:
        return existing

    # 4b. Resume resolution (--resume only): if this is a reclaimed ticket whose
    # dead run left a checkpoint-pushed branch, base the worktree on that branch
    # so the new run continues the recovered work. Best-effort — any failure
    # (not reclaimed, no durable WIP, a branch that no longer fetches, or a
    # Linear probe error) falls back to a clean start off ``base`` rather than
    # blocking the queue. ``base`` (the merge target) is unchanged either way.
    # Tracker-less, both resume sources are tracker comments, so there is
    # nothing to read: resume degrades to the clean start it already falls back
    # to for a ticket with no durable WIP.
    start_point: str | None = None
    if resume and client is not None:
        start_point = await _resolve_resume_start_point(client, canonical, repo_root)

    # 4c. Clean start (no resume WIP): base the worktree off ``origin/<base>`` when
    # it resolves, so the run starts from the tip ``close`` pushed there. Since
    # CAL-1154 ``close`` merges in a throwaway worktree and no longer advances the
    # local ``<base>`` branch, basing off the local branch would start every run on
    # a tree that lags the merged work (Option 1). ``preferred_base_ref`` falls back
    # to the local ``<base>`` for offline / no-origin repos, so those are unchanged.
    # The recorded ``base_branch`` (the merge target) stays ``base`` either way.
    if start_point is None:
        start_point = await asyncio.to_thread(preferred_base_ref, repo_root, base)

    # 5. Create worktree (local side effect — rolled back on any later failure).
    run_id = generate_run_id()
    node = WorktreeNode()
    try:
        result = await node.create(
            run_id=run_id, repo_root=repo_root, base=base, start_point=start_point
        )
    except WorktreeNodeError as exc:
        # No local state created yet — no rollback needed.
        raise _StartError(f"worktree creation failed: {exc}", 1) from exc

    worktree_path = str(result.worktree_path)
    worktree_branch = result.worktree_branch

    # 6. Insert open run row (local side effect, keyed on canonical identifier).
    started_at = datetime.now(UTC).isoformat()
    try:
        await _insert_open_run(
            db_path=db_path,
            run_id=run_id,
            ticket=canonical,
            base_branch=base,
            worktree_path=worktree_path,
            worktree_branch=worktree_branch,
            started_at=started_at,
        )
    except aiosqlite.IntegrityError:
        # A concurrent start process won the race — the unique partial index on
        # (ticket) WHERE status='open' prevented a duplicate insert.  Clean up
        # the losing worktree and surface the run that beat us.
        await asyncio.to_thread(_cleanup_worktree_sync, repo_root, worktree_path)
        existing = await _find_open_run(db_path, canonical, ticket_data)
        if existing is not None:
            return existing
        # Very unlikely: index fired but row already gone — treat as error.
        raise _StartError("concurrent start conflict but no existing run found", 1) from None
    except Exception as exc:
        # Roll back the worktree on DB failure — keep side effects atomic.
        await asyncio.to_thread(_cleanup_worktree_sync, repo_root, worktree_path)
        raise _StartError(f"failed to record run in database: {exc}", 1) from exc

    # 7. Transition ticket to In Progress (remote side effect — last, as it is
    # the only non-local operation).  Roll back ALL local state on any failure,
    # including unexpected transport errors, so no dangling open run is left.
    # Tracker-less there is no remote side effect at all: the run is complete
    # once the worktree and ledger row exist.
    if client is not None:
        try:
            await client.transition_to_in_progress(canonical)
        except Exception as exc:
            await _delete_run_row(db_path, run_id)
            await asyncio.to_thread(_cleanup_worktree_sync, repo_root, worktree_path)
            # Linear boundary errors are an invocation problem (exit 2); anything
            # else is unexpected (exit 1).  Either way local state is rolled back.
            code = 2 if isinstance(exc, LinearNotFound | LinearRequestError) else 1
            raise _StartError(f"failed to transition ticket: {exc}", code) from exc

    # 8. Build compact output context — only the fields the agent needs.
    return StartOutput(
        run_id=run_id,
        ticket=_compact_ticket(ticket_data),
        worktree_path=worktree_path,
        worktree_branch=worktree_branch,
        base_branch=base,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compact_ticket(ticket_data: dict[str, Any]) -> TicketContext:
    """Build a :class:`TicketContext` from a raw Linear ticket dict.

    The ``description`` is capped at :data:`TICKET_DESCRIPTION_MAX_CHARS`
    characters.  All other fields are taken verbatim from the five declared
    ticket keys so no extra Linear fields leak into the output.
    """
    raw_desc: str | None = ticket_data.get("description")
    if raw_desc is not None and len(raw_desc) > TICKET_DESCRIPTION_MAX_CHARS:
        raw_desc = raw_desc[:TICKET_DESCRIPTION_MAX_CHARS] + _TRUNCATION_SUFFIX
    return TicketContext(
        id=ticket_data.get("id"),
        identifier=ticket_data.get("identifier", ""),
        title=ticket_data.get("title"),
        description=raw_desc,
        url=ticket_data.get("url"),
    )


# ---------------------------------------------------------------------------
# Resume resolution (--resume) — continue a reclaimed run from its WIP branch
# ---------------------------------------------------------------------------


async def _resolve_resume_start_point(
    client: LinearClient, ticket: str, repo_root: Path
) -> str | None:
    """The git commit a resumed run starts from, or ``None`` for a clean start.

    Reads the ticket's preserved (checkpoint-pushed) branch from Linear and
    fetches it from ``origin``, returning the fetched tip SHA. Two sources feed
    resume, tried in order:

    1. **Death-keyed reclamation** (``fetch_resume_branch`` — proposal
       ``stale-run-reclamation`` D4 / CAL-739): a ``reclaimed`` ticket whose dead
       run left a checkpoint-pushed branch.
    2. **Proactive context-rollover handoff** (``fetch_handoff_branch`` —
       proposal ``ground-specs-and-context-rollover`` WS-B / CAL-923): an alive
       session near its context limit handed off the **same** (still In-Progress)
       ticket. Its handoff marker carries no ``reclaimed`` label, so the
       reclamation reader skips it — hence the explicit fall-through here.

    Best-effort throughout: no preserved branch from either source, a branch that
    no longer fetches, or a Linear probe error all return ``None`` so the run
    restarts clean rather than block the queue. ``base`` (the merge target) is
    unchanged either way, so ``close``'s HEAD-bound gate keeps the resumed run
    safe from double-merge whichever source supplied the branch.
    """
    try:
        branch = await client.fetch_resume_branch(ticket)
        if not branch:
            branch = await client.fetch_handoff_branch(ticket)
    except (LinearNotFound, LinearRequestError):
        return None
    if not branch:
        return None
    return await asyncio.to_thread(_fetch_origin_branch, repo_root, branch)


def _fetch_origin_branch(repo_root: Path, branch: str) -> str | None:
    """``git fetch origin <branch>`` then resolve its tip SHA, or ``None`` on failure.

    Returns the fetched commit SHA so the worktree starts at the exact tip — not a
    branch name a later op could move. A non-zero fetch (the branch is no longer
    on ``origin``) or an unresolvable ``FETCH_HEAD`` returns ``None``: a clean
    restart, not an error. Sync — offloaded via :func:`asyncio.to_thread`.

    The fetch is a network op, so it carries a timeout (CAL-1004); a fired
    timeout is the same ``None`` a failed fetch already returns — resume degrades
    to a clean start rather than hanging or raising.
    """
    try:
        fetch = run_git(
            repo_root, "fetch", "origin", branch, timeout=NETWORK_GIT_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        return None
    if fetch.returncode != 0:
        return None
    head = run_git(repo_root, "rev-parse", "FETCH_HEAD")
    if head.returncode != 0:
        return None
    return head.stdout.strip() or None


# ---------------------------------------------------------------------------
# Async DB helpers
# ---------------------------------------------------------------------------


async def _find_open_run(
    db_path: Path,
    ticket: str,
    ticket_data: dict[str, Any] | None = None,
) -> StartOutput | None:
    """Return the :class:`StartOutput` for an existing open run, or ``None``.

    ``ticket`` is the canonical Linear identifier.  ``ticket_data`` is the
    already-fetched compact ticket dict; when supplied it populates the
    ``ticket`` sub-model so the existing-run response carries the same full
    context as a fresh run.  When absent only ``identifier`` is set.
    """
    if not db_path.exists():
        return None
    try:
        async with (
            store.connect(db_path) as conn,
            conn.execute(
                "SELECT run_id, ticket, base_branch, worktree_path, worktree_branch, "
                "started_at FROM runs WHERE ticket = ? AND status = 'open'",
                (ticket,),
            ) as cur,
        ):
            row = await cur.fetchone()
    except aiosqlite.Error as exc:
        # An uninitialized DB (the file exists but the `runs` table was never
        # created) genuinely has no open run — treat that one case as empty.
        # Every other read failure (a locked or corrupt DB) is a real error:
        # surface it with its cause rather than masquerading as "no existing
        # run", which would let start proceed and later report the misleading
        # "concurrent start conflict but no existing run found".
        if isinstance(exc, aiosqlite.OperationalError) and "no such table" in str(exc).lower():
            return None
        raise _StartError(f"failed to read run database: {exc}", 1) from exc

    if row is None:
        return None

    run_id, _ticket, base_branch, wt_path, wt_branch, _started_at = row
    ticket_ctx = _compact_ticket(ticket_data) if ticket_data else TicketContext(identifier=ticket)
    return StartOutput(
        run_id=run_id,
        ticket=ticket_ctx,
        worktree_path=wt_path,
        worktree_branch=wt_branch,
        base_branch=base_branch,
    )


async def _insert_open_run(
    *,
    db_path: Path,
    run_id: str,
    ticket: str,
    base_branch: str,
    worktree_path: str,
    worktree_branch: str,
    started_at: str,
) -> None:
    """Insert a ``status='open'`` row into ``runs``."""
    await store.init_db(db_path)
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO runs ("
            "run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, base_branch, worktree_path, "
            "worktree_branch, ticket, started_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                "",          # workflow_name — not yet known at open time
                0,           # workflow_version — not yet known
                "open",
                "{}",        # state_json — empty until a workflow runs
                "{}",        # inputs_json — populated when workflow starts
                base_branch,
                worktree_path,
                worktree_branch,
                ticket,
                started_at,
            ),
        )
        await conn.commit()


async def _delete_run_row(db_path: Path, run_id: str) -> None:
    """Delete the ``runs`` row for ``run_id``, best-effort — never raises.

    A failed rollback is not re-raised: the original error that triggered the
    rollback keeps priority. But it is no longer silent — a failed delete leaves
    an orphan ``open`` row whose partial unique index blocks *every* future
    ``start`` for that ticket, so it warns to stderr naming the ``run_id`` and
    the manual remedy instead of swallowing the failure.
    """
    try:
        if not db_path.exists():
            return
        async with store.connect(db_path) as conn:
            await conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            await conn.commit()
    except Exception as exc:  # noqa: BLE001 — best-effort: must not mask the original error
        typer.echo(
            f"warning: failed to roll back run row {run_id!r}: {exc}. "
            f"An orphaned open run may remain and block future starts for this "
            f"ticket — clear it with `harness cancel {run_id}` or `harness reclaim`.",
            err=True,
        )


# ---------------------------------------------------------------------------
# Worktree rollback helper (sync — offloaded via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _cleanup_worktree_sync(repo_root: Path, worktree_path: str) -> None:
    """Best-effort rollback of a failed ``start`` create: remove the worktree.

    Delegates to the shared :func:`harness.cli._git.teardown_worktree` so the
    reclaim logic — worktree-remove (with an orphan ``rmtree`` fallback), prune,
    and local ``branch -D`` — has one home (CAL-767). ``start`` never pushed the
    branch, so ``delete_remote`` stays ``False``. Kept as a named wrapper so the
    rollback call sites (and the test that patches it) have a stable seam.
    """
    path = Path(worktree_path)
    teardown_worktree(
        repo_root,
        worktree_path=path,
        branch=_branch_for(path.name),
        delete_remote=False,
    )
