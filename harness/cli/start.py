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
   ``.worktrees/harness/<run_id>/`` on branch ``harness/<run_id>``.
6. Inserts an ``open`` row into ``runs`` (``status='open'``).
7. Transitions the ticket to In Progress (last — the only non-local side
   effect; local state is rolled back if it fails).
8. Prints the run context as JSON.

The whole flow runs inside a single ``asyncio.run`` event loop so all I/O —
Linear HTTP, SQLite, worktree git — is awaited rather than spread across
repeated ``asyncio.run`` calls.

Exit codes (SPEC §11):
* 0   — success; JSON context printed (new or existing run).
* 1   — unexpected error (worktree creation failed, DB error, etc.).
* 2   — invocation error: missing ticket, duplicate run, Linear unreachable.

The ``--json`` flag is accepted for forward-compatibility but JSON is always
the output format — the command has no human-readable fallback because it is
designed for machine consumption.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
import typer
from pydantic import BaseModel

from harness.cli._repo import resolve_repo_root_or_exit
from harness.identity import generate_run_id
from harness.identity import worktree_branch as _branch_for
from harness.linear import (
    LinearClient,
    LinearConfigError,
    LinearNotFound,
    LinearRequestError,
    linear_api_key,
)
from harness.state import store
from harness.worktree import WorktreeNode, WorktreeNodeError

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


class _StartError(Exception):
    """Internal control-flow exception carrying a message and an exit code.

    Raised inside the async orchestration and translated to a Typer ``Exit``
    by :func:`start_command`.
    """

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def start_command(
    ticket: str = typer.Argument(..., help="Linear ticket identifier (e.g. CAL-570)."),
    base: str = typer.Option(
        "dev",
        "--base",
        help="Base branch for the worktree. Defaults to ``dev``.",
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
    db_path = db if db is not None else repo_root / store.DEFAULT_DB_PATH

    try:
        output = asyncio.run(
            _run_start(
                ticket=ticket,
                base=base,
                repo_root=repo_root,
                db_path=db_path,
            )
        )
    except _StartError as exc:
        if json_output:
            typer.echo(json.dumps({"error": exc.message}))
        else:
            typer.echo(exc.message, err=True)
        raise typer.Exit(code=exc.code) from exc

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
    repo_root: Path,
    db_path: Path,
) -> StartOutput:
    """Drive the full start flow; raise :class:`_StartError` on any failure."""
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

    # 4. Check for an existing open run for this ticket (keyed on canonical).
    existing = await _find_open_run(db_path, canonical, ticket_data)
    if existing is not None:
        return existing

    # 5. Create worktree (local side effect — rolled back on any later failure).
    run_id = generate_run_id()
    node = WorktreeNode()
    try:
        result = await node.create(run_id=run_id, repo_root=repo_root, base=base)
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
    except Exception:
        return None

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
    """Delete the ``runs`` row for ``run_id``, best-effort (no exception on failure)."""
    try:
        if not db_path.exists():
            return
        async with store.connect(db_path) as conn:
            await conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            await conn.commit()
    except Exception:  # noqa: BLE001, S110
        pass  # Best-effort rollback — original error takes priority.


# ---------------------------------------------------------------------------
# Worktree rollback helper (sync — offloaded via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _cleanup_worktree_sync(repo_root: Path, worktree_path: str) -> None:
    """Best-effort cleanup: remove the worktree if a later step failed."""
    import subprocess

    path = Path(worktree_path)
    if not path.exists():
        return
    subprocess.run(  # noqa: S603, S607
        ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(path)],
        check=False,
        capture_output=True,
    )
    # Also prune the stale worktree entry from git's index.
    subprocess.run(  # noqa: S603, S607
        ["git", "-C", str(repo_root), "worktree", "prune"],
        check=False,
        capture_output=True,
    )
    # Remove the branch if it was created.
    branch = _branch_for(path.name)
    subprocess.run(  # noqa: S603, S607
        ["git", "-C", str(repo_root), "branch", "-D", branch],
        check=False,
        capture_output=True,
    )
