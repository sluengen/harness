"""``harness close <TICKET>`` — gate on a HEAD-bound pass, then merge/close.

The close verb is the enforcement linchpin of the harness-as-tool model
(proposal ``harness-as-tool.md`` decision **D5**): closing a ticket must be
impossible unless a run was *started* and the *current tree* passed review.
That is what makes interactive use auditable and unattended (Hermes-triggered)
dispatch trustworthy — a merge can never land on an unreviewed or stale tree.

The gate has two conjuncts:

1. There is an ``status='open'`` ``runs`` row for the ticket (resolved by
   ``--run-id`` or by ``worktree_path == --repo``).
2. There exists a ``review`` event for that run with ``verdict='pass'`` whose
   ``reviewed_sha`` equals ``git rev-parse HEAD`` of the run's worktree.

On pass, the verb performs the side effects in order (each kept *inside* the
verb so its output never enters the printed JSON — the context-economy
guarantee):

1. ``git`` commit any uncommitted changes in the worktree.
2. ``git merge --no-ff`` the run branch into ``base_branch``.
3. ``git push`` the base branch.
4. Transition the Linear ticket to Done.
5. Flip the ``runs`` row to ``status='closed'`` and emit a ``close`` event.

On a gate failure the verb exits non-zero with a structured refusal carrying a
``reason`` of exactly one of:

* ``no_run`` — no open run for the ticket/worktree.
* ``no_passing_review`` — no ``review`` event with ``verdict='pass'`` at all.
* ``stale_review`` — a pass exists but for a different SHA (HEAD advanced).

Exit codes (mirroring ``harness start`` / ``harness review``):
* 0 — close succeeded; the compact result JSON is printed.
* 1 — unexpected error (git failure, push failure, DB error, Linear error).
* 2 — gate refusal (``no_run`` / ``no_passing_review`` / ``stale_review``).
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import typer
from pydantic import BaseModel

from harness.events.emitter import EventEmitter
from harness.linear import (
    LinearClient,
    LinearConfigError,
    LinearNotFound,
    LinearRequestError,
    linear_api_key,
)
from harness.state import store

__all__ = ["close_command", "CloseOutput"]

# The structured refusal reasons — exactly one is reported on a gate failure.
RefusalReason = Literal["no_run", "no_passing_review", "stale_review"]


class CloseOutput(BaseModel):
    """Compact close result — the ONLY thing printed on success.

    Git merge/push output stays inside the verb and never appears here
    (context-economy AC).  The fields are the bounded status an orchestrating
    agent needs to confirm the close landed.
    """

    run_id: str
    ticket: str
    reviewed_sha: str
    merged: bool
    ticket_done: bool
    status: str


class _CloseError(Exception):
    """Internal control-flow exception carrying a message and an exit code.

    ``reason`` is set for gate refusals so the command can print the structured
    ``{"reason": ...}`` JSON; it is ``None`` for unexpected (exit 1) errors.
    """

    def __init__(self, message: str, code: int, reason: RefusalReason | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.reason = reason


def close_command(
    ticket: str = typer.Argument(..., help="Linear ticket identifier (e.g. CAL-572)."),
    repo: Path = typer.Option(  # noqa: B008
        Path("."),
        "--repo",
        help="Worktree root to close (resolves the open run by worktree_path). Defaults to CWD.",
    ),
    run_id: str | None = typer.Option(
        None,
        "--run-id",
        help="Explicit run to close. Defaults to the open run whose worktree is --repo.",
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
    """Enforce the gate, then merge/push the run, transition the ticket Done, close the run."""
    repo_root = repo.resolve()
    db_path = db if db is not None else repo_root / store.DEFAULT_DB_PATH

    try:
        output = asyncio.run(
            _run_close(
                ticket=ticket,
                repo_root=repo_root,
                run_id=run_id,
                db_path=db_path,
            )
        )
    except _CloseError as exc:
        if json_output:
            payload: dict[str, Any] = {"error": exc.message}
            if exc.reason is not None:
                payload["reason"] = exc.reason
            typer.echo(json.dumps(payload))
        else:
            typer.echo(exc.message, err=True)
        raise typer.Exit(code=exc.code) from exc

    if json_output:
        typer.echo(output.model_dump_json())
    else:
        typer.echo(f"closed {output.run_id} ({output.ticket}) — merged, ticket Done")


# ---------------------------------------------------------------------------
# Async orchestration — one event loop for all I/O.
# ---------------------------------------------------------------------------


async def _run_close(
    *,
    ticket: str,
    repo_root: Path,
    run_id: str | None,
    db_path: Path,
) -> CloseOutput:
    """Drive the close flow; raise :class:`_CloseError` on gate failure or error."""
    # 1. Resolve the open run (by explicit id, else by worktree_path == repo).
    resolved = await _resolve_open_run(db_path, repo_root, run_id)
    if resolved is None:
        raise _CloseError(
            f"no open run found for worktree {repo_root} (ticket {ticket})",
            2,
            reason="no_run",
        )
    resolved_run_id, worktree_path, base_branch, worktree_branch = resolved

    # 2. Capture HEAD of the run's worktree — the SHA the gate binds to.
    try:
        head_sha = await asyncio.to_thread(_rev_parse_head, Path(worktree_path))
    except _CloseError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _CloseError(f"failed to read HEAD for worktree {worktree_path}: {exc}", 1) from exc

    # 3. Enforce the review gate: a pass whose reviewed_sha == HEAD.
    gate = await _evaluate_gate(db_path, resolved_run_id, head_sha)
    if gate is not None:
        raise _CloseError(gate[1], 2, reason=gate[0])

    # 4. Validate Linear is configured before any local side effect, so a
    #    missing key does not leave a half-merged tree.
    try:
        api_key = linear_api_key()
    except LinearConfigError as exc:
        raise _CloseError(str(exc), 2) from exc
    client = LinearClient(api_key=api_key)

    # 5. Merge + push (sync git, offloaded to a thread).  Output is captured and
    #    discarded inside the verb — it never enters the printed JSON.
    try:
        await asyncio.to_thread(
            _merge_and_push,
            repo_root=repo_root,
            worktree_path=Path(worktree_path),
            base_branch=base_branch,
            worktree_branch=worktree_branch,
        )
    except _CloseError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _CloseError(f"merge/push failed: {exc}", 1) from exc

    # 6. Transition the ticket to Done (remote side effect).
    try:
        await client.transition_to_done(ticket)
    except (LinearNotFound, LinearRequestError) as exc:
        raise _CloseError(f"failed to transition ticket to Done: {exc}", 1) from exc

    # 7. Flip the run row to closed and record the close event (audit trail).
    closed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        await _mark_run_closed(db_path, resolved_run_id)
        await EventEmitter(db_path).emit(
            run_id=resolved_run_id,
            event_type="close",
            data={
                "run_id": resolved_run_id,
                "ticket": ticket,
                "merged_sha": head_sha,
                "closed_at": closed_at,
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise _CloseError(f"failed to record run close: {exc}", 1) from exc

    return CloseOutput(
        run_id=resolved_run_id,
        ticket=ticket,
        reviewed_sha=head_sha,
        merged=True,
        ticket_done=True,
        status="closed",
    )


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------


async def _evaluate_gate(
    db_path: Path,
    run_id: str,
    head_sha: str,
) -> tuple[RefusalReason, str] | None:
    """Evaluate the review gate; return ``(reason, message)`` on refusal else ``None``.

    A pass whose ``reviewed_sha == head_sha`` opens the gate.  Otherwise:
    ``no_passing_review`` when no pass exists at all, ``stale_review`` when a
    pass exists but only for a different SHA.
    """
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT json_extract(data_json, '$.reviewed_sha') "
            "FROM events WHERE run_id = ? AND event_type = 'review' "
            "AND json_extract(data_json, '$.verdict') = 'pass'",
            (run_id,),
        ) as cur,
    ):
        rows = await cur.fetchall()

    pass_shas = {str(r[0]) for r in rows if r[0] is not None}
    if not pass_shas:
        return ("no_passing_review", f"no passing review recorded for run {run_id}")
    if head_sha not in pass_shas:
        return (
            "stale_review",
            f"passing review is stale: HEAD {head_sha} has no pass "
            f"(reviewed SHAs: {sorted(pass_shas)})",
        )
    return None


# ---------------------------------------------------------------------------
# Async DB helpers
# ---------------------------------------------------------------------------


async def _resolve_open_run(
    db_path: Path,
    repo_root: Path,
    run_id: str | None,
) -> tuple[str, str, str, str] | None:
    """Return ``(run_id, worktree_path, base_branch, worktree_branch)`` or ``None``.

    With an explicit ``run_id`` the row must be ``status='open'``.  Otherwise the
    open run is matched by ``worktree_path`` equal to the resolved repo —
    mirroring ``harness review``'s ``_resolve_open_run`` query style.
    """
    if not db_path.exists():
        return None

    if run_id is not None:
        query = (
            "SELECT run_id, worktree_path, base_branch, worktree_branch "
            "FROM runs WHERE run_id = ? AND status = 'open'"
        )
        params: tuple[str, ...] = (run_id,)
    else:
        query = (
            "SELECT run_id, worktree_path, base_branch, worktree_branch "
            "FROM runs WHERE worktree_path = ? AND status = 'open'"
        )
        params = (str(repo_root),)

    async with store.connect(db_path) as conn, conn.execute(query, params) as cur:
        row = await cur.fetchone()

    if row is None:
        return None
    return str(row[0]), str(row[1]), str(row[2]), str(row[3])


async def _mark_run_closed(db_path: Path, run_id: str) -> None:
    """Flip the ``runs`` row for ``run_id`` to ``status='closed'``."""
    async with store.connect(db_path) as conn:
        await conn.execute(
            "UPDATE runs SET status = 'closed' WHERE run_id = ?",
            (run_id,),
        )
        await conn.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rev_parse_head(worktree_path: Path) -> str:
    """Return the current HEAD SHA of ``worktree_path`` (sync — run in a thread)."""
    result = subprocess.run(  # noqa: S603, S607
        ["git", "-C", str(worktree_path), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise _CloseError(
            f"git rev-parse HEAD failed for {worktree_path}: {result.stderr.strip()}",
            1,
        )
    return result.stdout.strip()


def _merge_and_push(
    *,
    repo_root: Path,
    worktree_path: Path,
    base_branch: str,
    worktree_branch: str,
) -> str:
    """Commit pending work, merge the run branch into ``base``, push.

    Runs entirely inside the verb (sync git, offloaded via ``asyncio.to_thread``).
    Returns the concatenated git output so the caller may log it, but that
    output is deliberately *not* propagated into the printed JSON
    (context-economy).  Raises :class:`_CloseError` on any git failure.
    """
    output: list[str] = []

    def _run(cwd: Path, *args: str) -> None:
        result = subprocess.run(  # noqa: S603, S607
            ["git", "-C", str(cwd), *args],
            check=False,
            capture_output=True,
            text=True,
        )
        output.append(result.stdout)
        output.append(result.stderr)
        if result.returncode != 0:
            raise _CloseError(
                f"git {' '.join(args)} failed in {cwd}: {result.stderr.strip()}",
                1,
            )

    # 1. Commit any uncommitted changes in the worktree (only if dirty).
    status = subprocess.run(  # noqa: S603, S607
        ["git", "-C", str(worktree_path), "status", "--porcelain"],
        check=False,
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
        _run(worktree_path, "add", "-A")
        _run(worktree_path, "commit", "-m", f"chore: finalize {worktree_branch}")

    # 2. Merge the run branch into base, then push base — operated from the
    #    main repo checkout so the base branch's working tree is what advances.
    _run(repo_root, "checkout", base_branch)
    _run(repo_root, "merge", "--no-ff", worktree_branch, "-m", f"Merge {worktree_branch}")
    _run(repo_root, "push", "origin", base_branch)

    return "".join(output)
