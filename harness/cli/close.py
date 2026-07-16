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
4. Flip the ``runs`` row to ``status='closed'`` and record a ``close`` event in
   one transaction (CAL-1002), so a failed ledger write never strands a terminal
   run with no close event.
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
import subprocess
from pathlib import Path
from typing import Any, Literal

import typer
from pydantic import BaseModel

from harness._time import iso_z
from harness.cli._git import (
    NETWORK_GIT_TIMEOUT_SECONDS,
    rev_parse_head,
    run_git,
    teardown_worktree,
)
from harness.cli._repo import resolve_repo_root_or_exit, resolve_verb_db_path
from harness.cli._runs import resolve_open_run
from harness.cli._verb import VerbError, run_verb
from harness.events.payloads import (
    REVIEW_GATE_RAN_PATH,
    REVIEW_GATE_REASON_PATH,
    REVIEW_REVIEWED_SHA_PATH,
    REVIEW_VERDICT_PATH,
    CloseEventData,
)
from harness.events.schema import EVENT_TYPES
from harness.gate import GATE_NOT_CONFIGURED_REASON
from harness.layers import linear_enabled
from harness.linear import (
    LinearClient,
    LinearConfigError,
    LinearNotFound,
    LinearRequestError,
    linear_api_key,
)
from harness.state import store

# size: one cohesive verb — the close gate plus the integrate → merge → push →
# teardown lifecycle it guards, which splitting would only scatter across files.
# CAL-1004 added the network-timeout guards (fetch/push) inline, per run_git's
# caller-owns-error-policy contract, pushing it just over the 500-line limit.

__all__ = ["close_command", "CloseOutput"]

# The structured refusal reasons — exactly one is reported on a gate failure.
RefusalReason = Literal[
    "no_run",
    "dirty_worktree",
    "no_passing_review",
    "stale_review",
    "no_gate_evidence",
]

#: The audit event a successful close appends. A member of ``EVENT_TYPES``; the
#: assert guards against a rename drifting the inlined INSERT away from the
#: canonical set (mirrors :data:`harness.cli._abandon.ABANDON_EVENT_TYPE`).
_CLOSE_EVENT_TYPE = "close"
assert _CLOSE_EVENT_TYPE in EVENT_TYPES


class CloseOutput(BaseModel):
    """Compact close result — the ONLY thing printed on success.

    Git merge/push output stays inside the verb and never appears here
    (context-economy AC).  The fields are the bounded status an orchestrating
    agent needs to confirm the close landed.

    ``ticket_done`` records whether a tracker transition actually happened, so a
    tracker-less close (``layers.linear: false``, CAL-1104) reports ``False`` —
    the merge still landed. It is not a success flag: read ``merged`` /
    ``status`` for that.
    """

    run_id: str
    ticket: str
    reviewed_sha: str
    merged: bool
    ticket_done: bool
    status: str


class _CloseError(VerbError):
    """``close``'s control-flow exception — a :class:`VerbError` (CAL-1013).

    ``close`` *sets* ``reason`` for gate refusals (a :data:`RefusalReason`) so
    the structured ``{"error", "reason"}`` JSON names the refusal kind; it is
    left ``None`` for unexpected (exit 1) errors. The ``(message, code, reason)``
    carrier is inherited from the base; every raise site passes ``reason=`` by
    keyword.
    """


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

    output = run_verb(
        lambda: asyncio.run(
            _run_close(
                ticket=ticket,
                repo_root=repo_root,
                run_id=run_id,
                db_path=db_path,
            )
        ),
        json_output=json_output,
    )

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
    #    missing key does not leave a half-merged tree. Tracker-less
    #    (``layers.linear: false``, CAL-1104) there is nothing to configure and
    #    nothing to transition — the gate above is unchanged, so the merge is
    #    protected exactly as it is with a tracker.
    client: LinearClient | None = None
    if linear_enabled(repo_root):
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

    # 7. Transition the ticket to Done (remote side effect). Skipped tracker-less
    #    — and reported as such in step 10 rather than claimed.
    ticket_done = False
    if client is not None:
        try:
            await client.transition_to_done(ticket)
        except (LinearNotFound, LinearRequestError) as exc:
            raise _CloseError(f"failed to transition ticket to Done: {exc}", 1) from exc
        ticket_done = True

    # 8. Flip the run row to closed and record the close event in one
    #    transaction — see ``_mark_run_closed`` (CAL-1002).
    closed_at = iso_z()
    try:
        await _mark_run_closed(
            db_path,
            resolved_run_id,
            event_data=CloseEventData(
                run_id=resolved_run_id,
                ticket=ticket,
                merged_sha=head_sha,
                closed_at=closed_at,
            ).model_dump(),
            event_ts=closed_at,
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
        ticket_done=ticket_done,
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

    A pass whose ``reviewed_sha == head_sha`` **and** which carries verify-gate
    evidence opens the gate.  Otherwise: ``no_passing_review`` when no pass
    exists at all, ``stale_review`` when a pass exists but only for a different
    SHA, ``no_gate_evidence`` when the pass covering HEAD cannot show that the
    repo's gate ran (CAL-1082).
    """
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            # The json paths are the single-sourced payload-key constants
            # (CAL-1012), passed as bound parameters — SQLite accepts a bound
            # json_extract path, so the gate holds no raw ``$.<key>`` literal.
            "SELECT json_extract(data_json, ?), json_extract(data_json, ?), "
            "json_extract(data_json, ?) "
            "FROM events WHERE run_id = ? AND event_type = 'review' "
            "AND json_extract(data_json, ?) = 'pass'",
            (
                REVIEW_REVIEWED_SHA_PATH,
                REVIEW_GATE_RAN_PATH,
                REVIEW_GATE_REASON_PATH,
                run_id,
                REVIEW_VERDICT_PATH,
            ),
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
    # The verify-gate backstop (CAL-1082): a pass is only evidence that the tree
    # is green if the review that recorded it actually ran the repo's gate.  A
    # pass written by an older harness carries no ``gate_ran`` key at all —
    # ``json_extract`` yields NULL — and is refused rather than trusted, so the
    # change is fail-safe with no ledger migration.
    if not any(
        _has_gate_evidence(gate_ran, gate_reason)
        for sha, gate_ran, gate_reason in rows
        if str(sha) == head_sha
    ):
        return (
            "no_gate_evidence",
            f"passing review for HEAD {head_sha} carries no verify-gate "
            f"evidence: it was recorded without running the repo's gate (or by a "
            f"harness that predates it). Re-run review to record a pass backed by "
            f"a green gate.",
        )
    return None


def _has_gate_evidence(gate_ran: Any, gate_reason: Any) -> bool:
    """Whether a pass row shows its verify gate was accounted for.

    Two shapes qualify. A gate that **ran** green (``gate_ran`` true — a red gate
    never gets an event at all, so a recorded run is a passing one). Or a repo
    that defines **no** gate (``gate_reason='not_configured'``): the harness
    cannot gate what a repo does not define, so it allows the close and the
    ledger records the absence honestly rather than implying a gate ran.
    Tightening that is a separate decision — it would strand every repo without a
    ``verify:``.

    ``gate_ran`` arrives from SQLite's ``json_extract`` as ``1`` / ``0`` / ``None``.
    """
    if gate_ran == 1:
        return True
    return bool(gate_reason == GATE_NOT_CONFIGURED_REASON)


# ---------------------------------------------------------------------------
# Async DB helpers
# ---------------------------------------------------------------------------


async def _mark_run_closed(
    db_path: Path,
    run_id: str,
    *,
    event_data: dict[str, Any],
    event_ts: str,
) -> None:
    """Flip the ``runs`` row to ``status='closed'`` and append its ``close`` event.

    Both writes share **one** ``BEGIN IMMEDIATE`` transaction — commit once, or
    roll back together (CAL-1002). Split across two connections, a crash between
    the flip and the event stranded a terminal ``closed`` run with no ``close``
    event: an inconsistent ledger no retry can repair (nothing re-drives a
    terminal run). Mirrors the shared abandon transaction
    (:func:`harness.cli._abandon.abandon_run_in_ledger`); the event INSERT is
    inlined here — not via :class:`~harness.events.emitter.EventEmitter`, which
    opens its own connection — so it shares this commit.
    """
    data_json = json.dumps(event_data)
    async with store.connect(db_path) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            await conn.execute(
                "UPDATE runs SET status = 'closed' WHERE run_id = ?",
                (run_id,),
            )
            await conn.execute(
                "INSERT INTO events (run_id, node_id, event_type, timestamp, "
                "duration_ms, data_json) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, None, _CLOSE_EVENT_TYPE, event_ts, None, data_json),
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise


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

    def _run(cwd: Path, *args: str, timeout: float | None = None) -> None:
        # A fired network timeout (fetch/push) raises TimeoutExpired rather than
        # returning a non-zero result — convert it to the same _CloseError shape
        # so close fails cleanly instead of leaking a raw traceback (CAL-1004).
        try:
            result = run_git(cwd, *args, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise _CloseError(
                f"git {' '.join(args)} exceeded the {timeout:.0f}s network "
                f"timeout in {cwd}; the remote may be unreachable — retry close "
                "once it is back",
                1,
            ) from exc
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
    _run(repo_root, "fetch", "origin", base_branch, timeout=NETWORK_GIT_TIMEOUT_SECONDS)
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

    _run(repo_root, "push", "origin", base_branch, timeout=NETWORK_GIT_TIMEOUT_SECONDS)

    return "".join(output)
