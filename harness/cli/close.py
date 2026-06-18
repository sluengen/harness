"""``harness close <TICKET>`` — gate on a HEAD-bound pass, then merge/close.

The close verb is the enforcement linchpin of the harness-as-tool model
(proposal ``harness-as-tool.md`` decision **D2**): closing a ticket must be
impossible unless a run was *started* and the *current tree* passed review.
That is what makes interactive use auditable and unattended (Hermes-triggered)
dispatch trustworthy — a merge can never land on an unreviewed or stale tree.

The gate has three conjuncts:

1. There is an ``status='open'`` ``runs`` row for the ticket (resolved by
   ``--run-id`` or by ``worktree_path == --repo``).
2. The run's worktree is clean (``git status --porcelain`` is empty) — so what
   merges is exactly what HEAD, and therefore the review, covers. The verb does
   **not** auto-commit a dirty tree: uncommitted edits are not in HEAD, so a
   pass for HEAD never reviewed them, and ``stale_review`` cannot catch
   edit-without-committing (HEAD is unchanged). A guardrail self-enforces its
   invariant rather than trusting the caller to have committed (CAL-586 /
   CODE-1; CODE-INSIGHT-2).
3. There exists a ``review`` event for that run with ``verdict='pass'`` whose
   ``reviewed_sha`` equals ``git rev-parse HEAD`` of the run's worktree.

On pass, the verb performs the side effects in order (each kept *inside* the
verb so its output never enters the printed JSON — the context-economy
guarantee):

1. Integrate the current ``origin/<base_branch>`` (``git fetch`` then a
   ``--ff-only`` fast-forward of the local base), so a base branch that advanced
   during the run does not reject the push non-fast-forward (CAL-777), then
   ``git merge --no-ff`` the run branch into ``base_branch``.
2. ``git push`` the base branch.
3. Transition the Linear ticket to Done.
4. Flip the ``runs`` row to ``status='closed'`` and emit a ``close`` event.
5. Reclaim the run's worktree and branch (``teardown_worktree``): the merge has
   landed, so the worktree directory and the branch — local, and on ``origin``
   if a checkpoint pushed it — are removed. This step is **best-effort**: a
   failure never fails the close (the merge/Done/ledger already succeeded), and
   the ``harness worktrees cleanup`` sweep reclaims anything left behind. Without
   it every closed run leaks a ``.worktrees/harness/<id>/`` directory and a
   branch (CAL-767).

On a gate failure the verb exits non-zero with a structured refusal carrying a
``reason`` of exactly one of:

* ``no_run`` — no open run for the ticket/worktree.
* ``dirty_worktree`` — the worktree has uncommitted changes; commit and
  re-review before close.
* ``no_passing_review`` — no ``review`` event with ``verdict='pass'`` at all.
* ``stale_review`` — a pass exists but for a different SHA (HEAD advanced).

Exit codes (mirroring ``harness start`` / ``harness review``):
* 0 — close succeeded; the compact result JSON is printed.
* 1 — unexpected error (git failure, push failure, DB error, or a Linear
  transition/request error while marking the ticket Done).
* 2 — gate refusal (``no_run`` / ``dirty_worktree`` / ``no_passing_review`` /
  ``stale_review``), or Linear is unconfigured (a missing ``LINEAR_API_KEY``);
  the latter carries no ``reason`` and is checked before any side effect.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any, Literal

import typer
from pydantic import BaseModel

from harness._time import iso_z
from harness.cli._git import rev_parse_head, run_git, teardown_worktree
from harness.cli._repo import resolve_repo_root_or_exit, resolve_verb_db_path
from harness.cli._runs import resolve_open_run
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
RefusalReason = Literal["no_run", "dirty_worktree", "no_passing_review", "stale_review"]


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
    repo_root = resolve_repo_root_or_exit(repo)
    db_path = resolve_verb_db_path(db, repo_root)

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
    resolved = await resolve_open_run(db_path, repo_root, run_id)
    if resolved is None:
        raise _CloseError(
            f"no open run found for worktree {repo_root} (ticket {ticket})",
            2,
            reason="no_run",
        )
    resolved_run_id, worktree_path, base_branch, worktree_branch = resolved

    # 2. Capture HEAD of the run's worktree — the SHA the gate binds to.
    try:
        head_sha = await asyncio.to_thread(rev_parse_head, Path(worktree_path))
    except Exception as exc:  # noqa: BLE001
        raise _CloseError(f"failed to read HEAD for worktree {worktree_path}: {exc}", 1) from exc

    # 3. Refuse a dirty worktree. The gate binds to HEAD, but uncommitted edits
    #    are not in HEAD — a pass for HEAD never reviewed them. ``stale_review``
    #    catches commit-after-review (HEAD advanced); it cannot catch
    #    edit-without-committing (HEAD unchanged). So the close verb must
    #    self-enforce a clean tree rather than auto-commit unreviewed content
    #    (CAL-586 / CODE-1; CODE-INSIGHT-2: a guardrail self-enforces).
    try:
        dirty = await asyncio.to_thread(_status_porcelain, Path(worktree_path))
    except _CloseError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _CloseError(
            f"failed to read git status for worktree {worktree_path}: {exc}", 1
        ) from exc
    if dirty:
        raise _CloseError(
            f"worktree {worktree_path} has uncommitted changes; commit and "
            f"re-review before close",
            2,
            reason="dirty_worktree",
        )

    # 4. Enforce the review gate: a pass whose reviewed_sha == HEAD.
    gate = await _evaluate_gate(db_path, resolved_run_id, head_sha)
    if gate is not None:
        raise _CloseError(gate[1], 2, reason=gate[0])

    # 5. Validate Linear is configured before any local side effect, so a
    #    missing key does not leave a half-merged tree.
    try:
        api_key = linear_api_key()
    except LinearConfigError as exc:
        raise _CloseError(str(exc), 2) from exc
    client = LinearClient(api_key=api_key)

    # 6. Merge + push (sync git, offloaded to a thread).  Output is captured and
    #    discarded inside the verb — it never enters the printed JSON.
    try:
        await asyncio.to_thread(
            _merge_and_push,
            repo_root=repo_root,
            base_branch=base_branch,
            worktree_branch=worktree_branch,
        )
    except _CloseError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _CloseError(f"merge/push failed: {exc}", 1) from exc

    # 7. Transition the ticket to Done (remote side effect).
    try:
        await client.transition_to_done(ticket)
    except (LinearNotFound, LinearRequestError) as exc:
        raise _CloseError(f"failed to transition ticket to Done: {exc}", 1) from exc

    # 8. Flip the run row to closed and record the close event (audit trail).
    closed_at = iso_z()
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

    # 9. Reclaim the run's worktree + branch now the merge has landed. The branch
    #    is merged into base, so deleting it (local, and remote if a checkpoint
    #    pushed it) is safe. This is best-effort housekeeping AFTER an already
    #    successful close: a teardown failure must never flip a closed run to an
    #    error or undo the merge/Done/ledger — the safety-net sweep
    #    (`harness worktrees cleanup`) reclaims anything left behind (CAL-767).
    # ``teardown_worktree`` is best-effort internally; suppress here too so even
    # an unexpected failure (e.g. a thread/loop error) cannot fail a close that
    # has already merged, transitioned the ticket, and closed the ledger row.
    with contextlib.suppress(Exception):
        await asyncio.to_thread(
            teardown_worktree,
            repo_root,
            worktree_path=Path(worktree_path),
            branch=worktree_branch,
            delete_remote=True,
        )

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


def _status_porcelain(worktree_path: Path) -> str:
    """Return ``git status --porcelain`` output for ``worktree_path`` (stripped).

    A non-empty result means the worktree has uncommitted changes (staged,
    unstaged, or untracked). Sync — run in a thread. Raises :class:`_CloseError`
    on a git failure so the caller reports an exit-1 error, not a false-clean.
    """
    result = run_git(worktree_path, "status", "--porcelain")
    if result.returncode != 0:
        raise _CloseError(
            f"git status failed for {worktree_path}: {result.stderr.strip()}",
            1,
        )
    return result.stdout.strip()


def _merge_and_push(
    *,
    repo_root: Path,
    base_branch: str,
    worktree_branch: str,
) -> str:
    """Integrate the current ``origin/<base>``, merge the run branch, and push.

    The worktree is guaranteed clean by the time this runs — ``_run_close``
    refuses a dirty tree (``dirty_worktree``) before any side effect, so there
    is nothing to commit here. Runs entirely inside the verb (sync git,
    offloaded via ``asyncio.to_thread``). Returns the concatenated git output so
    the caller may log it, but that output is deliberately *not* propagated into
    the printed JSON (context-economy). Raises :class:`_CloseError` on any git
    failure.

    ``origin/<base>`` can advance *during* the run — a concurrent
    ``/harness routine build`` or another session landing a ticket. The base SHA
    captured at ``start`` is then stale, and a plain ``push`` is rejected
    non-fast-forward, failing the close with the reviewed work stranded
    (CAL-777). So before merging we ``fetch`` the current ``origin/<base>`` and
    **fast-forward** the local base to it; merging the run branch on top then
    pushes cleanly. The HEAD-bound gate is untouched: the run branch tip is the
    reviewed SHA and becomes the merge's second parent, so only the reviewed
    commit's content rides in — the integration only adds work already on
    ``origin/<base>`` (each merged through its own gate).
    """
    output: list[str] = []

    def _run(cwd: Path, *args: str) -> None:
        result = run_git(cwd, *args)
        output.append(result.stdout)
        output.append(result.stderr)
        if result.returncode != 0:
            raise _CloseError(
                f"git {' '.join(args)} failed in {cwd}: {result.stderr.strip()}",
                1,
            )

    # Operate from the main repo checkout so the base branch's working tree is
    # what advances.
    _run(repo_root, "checkout", base_branch)

    # Integrate the current origin/<base> BEFORE merging, so a base that advanced
    # during the run does not reject the push as non-fast-forward (CAL-777). Fetch
    # the remote tip into FETCH_HEAD and fast-forward the local base to it.
    _run(repo_root, "fetch", "origin", base_branch)
    ff = run_git(repo_root, "merge", "--ff-only", "FETCH_HEAD")
    output.append(ff.stdout)
    output.append(ff.stderr)
    if ff.returncode != 0:
        # The harness never commits to the local base directly, so a fast-forward
        # to origin always applies. A failure here means the local base and
        # origin/<base> have genuinely diverged — an unexpected state we refuse
        # cleanly rather than force, leaving the base checkout untouched.
        raise _CloseError(
            f"cannot integrate origin/{base_branch}: local {base_branch} has "
            f"diverged from origin and cannot be fast-forwarded; reconcile "
            f"{base_branch} with origin and re-review before closing",
            1,
        )

    # Merge the reviewed run branch into the now-current base.
    merge = run_git(
        repo_root, "merge", "--no-ff", worktree_branch, "-m", f"Merge {worktree_branch}"
    )
    output.append(merge.stdout)
    output.append(merge.stderr)
    if merge.returncode != 0:
        # A genuine conflict between the reviewed run branch and the changes that
        # landed on origin/<base> during the run. Abort to leave the checkout
        # clean (the run stays resumable — the worktree and the passing review
        # are untouched), and fail with a clear message rather than the raw git
        # conflict dump. Recovery: rebase the run branch on the updated base,
        # re-review (a fresh HEAD → a fresh pass), and close again.
        run_git(repo_root, "merge", "--abort")
        raise _CloseError(
            f"cannot merge {worktree_branch} into {base_branch}: it conflicts "
            f"with changes that landed on origin/{base_branch} during the run; "
            f"rebase the run branch on the updated {base_branch}, re-review, and "
            f"close again",
            1,
        )

    _run(repo_root, "push", "origin", base_branch)

    return "".join(output)
