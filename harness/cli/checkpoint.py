"""``harness checkpoint`` — push the run branch so WIP survives the container (CAL-738).

Breakdown item 5 of the accepted proposal ``stale-run-reclamation``. Decision D4
is **preserve/resume**, but resume is only real if the WIP is durable: a worktree
on a dead ephemeral container is gone, so the only recoverable work is what was
**pushed** before the run died. Without periodic checkpoint-pushing, a cloud
hard-kill leaves an unpushed branch and resume degrades to a clean restart for
exactly the failure we care about — this is the load-bearing half of D4.

What it does:

1. **Resolve the open run** — by ``--run-id`` or by ``worktree_path == --repo``,
   the same rule ``review`` / ``close`` use (:func:`harness.cli._runs.resolve_open_run`).
   No open run resolved → exit 2.
2. **Push the run branch to ``origin``.** Only the run's ``worktree_branch`` moves
   — never the base, never a merge — so the ``close`` gate (a ``pass`` whose
   reviewed SHA == HEAD, then merge to base) is wholly untouched. The push goes
   through this verb rather than a hand-rolled ``git push`` in the loop, honouring
   the routing-discipline rule (``commands/harness.md``: never raw git
   state-transitions in the run loop — route every mutation through a verb).
3. **Append a ``checkpoint`` event** bound to the pushed SHA. This is the ledger
   signal :mod:`harness.cli.reclaim` reads to report a *durable* (resumable)
   branch on a reclaimed ticket — a run with no checkpoint event has no durable
   WIP, so reclaim degrades cleanly to "no resumable branch" (proposal item 6 /
   CAL-739 then resumes from a pushed branch, or restarts clean).

Context economy: the git push output stays inside the verb and never enters the
printed JSON — only the bounded :class:`CheckpointOutput` is emitted.

Exit codes (SPEC §11):
* 0 — the branch was pushed and the checkpoint recorded.
* 2 — no open run resolved for the worktree / ``--run-id``.
* 1 — unexpected error (the ``git push`` failed, or a DB/HEAD read failed); the
       WIP-durability failure is surfaced, not silently dropped. The one push
       failure that carries a named ``reason`` is ``stale_remote`` — the
       force-with-lease lease refused because ``origin`` moved past what this run
       last saw (CAL-1162); durability lapsed but the run is otherwise unaffected.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import typer
from pydantic import BaseModel

from harness._time import iso_z
from harness.cli._git import NETWORK_GIT_TIMEOUT_SECONDS, rev_parse_head, run_git
from harness.cli._repo import resolve_repo_root_or_exit, resolve_verb_db_path
from harness.cli._runs import resolve_open_run
from harness.cli._verb import VerbError, run_verb
from harness.events.emitter import EventEmitter
from harness.events.payloads import CheckpointEventData

__all__ = ["checkpoint_command", "CheckpointOutput"]


class CheckpointOutput(BaseModel):
    """Compact checkpoint result — the ONLY thing printed on success.

    Git push output stays inside the verb and never appears here (context-economy
    AC). The fields are the bounded status an orchestrating agent needs to confirm
    the WIP was made durable.
    """

    run_id: str
    branch: str
    pushed_sha: str
    pushed: bool


class _CheckpointError(VerbError):
    """``checkpoint``'s control-flow exception — a :class:`VerbError` (CAL-1013).

    The ``(message, code)`` carrier is inherited from the base. It sets a
    machine-readable ``reason`` only for the force-with-lease refusal
    (``stale_remote``, CAL-1162); every other failure raises without one, keeping
    the historical ``{"error": ...}`` JSON byte-for-byte.
    """


def checkpoint_command(
    repo: Path = typer.Option(  # noqa: B008
        Path("."),
        "--repo",
        help="Worktree root whose run branch to push. Defaults to CWD.",
    ),
    run_id: str | None = typer.Option(
        None,
        "--run-id",
        help="Explicit run to checkpoint. Defaults to the open run whose worktree is --repo.",
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
    """Push the run branch to origin so committed WIP survives the container dying."""
    repo_root = resolve_repo_root_or_exit(repo)
    db_path = resolve_verb_db_path(db, repo_root)

    output = run_verb(
        lambda: asyncio.run(
            _run_checkpoint(repo_root=repo_root, run_id=run_id, db_path=db_path)
        ),
        json_output=json_output,
    )

    if json_output:
        typer.echo(output.model_dump_json())
    else:
        typer.echo(
            f"checkpointed {output.run_id} — pushed {output.branch} @ "
            f"{output.pushed_sha[:12]}"
        )


async def _run_checkpoint(
    *,
    repo_root: Path,
    run_id: str | None,
    db_path: Path,
) -> CheckpointOutput:
    """Push the resolved run's branch and record a ``checkpoint`` event."""
    # 1. Resolve the open run (by explicit id, else by worktree_path == repo).
    resolved = await resolve_open_run(db_path, repo_root, run_id)
    if resolved is None:
        raise _CheckpointError(
            f"no open run found for worktree {repo_root}"
            + (f" (run-id {run_id})" if run_id else ""),
            2,
        )
    resolved_run_id, worktree_path, _base_branch, worktree_branch = resolved

    # 2. Capture HEAD — the SHA the checkpoint records as durable.
    try:
        head_sha = await asyncio.to_thread(rev_parse_head, Path(worktree_path))
    except Exception as exc:  # noqa: BLE001
        raise _CheckpointError(
            f"failed to read HEAD for worktree {worktree_path}: {exc}", 1
        ) from exc

    # 3. Push the feature branch to origin (sync git, offloaded). Output is
    #    captured and discarded inside the verb — it never enters the JSON.
    try:
        await asyncio.to_thread(
            _push_branch, worktree_path=Path(worktree_path), branch=worktree_branch
        )
    except _CheckpointError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _CheckpointError(f"checkpoint push failed: {exc}", 1) from exc

    # 4. Record the checkpoint event (the durable-WIP ledger signal reclaim reads).
    try:
        await EventEmitter(db_path).emit(
            run_id=resolved_run_id,
            event_type="checkpoint",
            data=CheckpointEventData(
                run_id=resolved_run_id,
                branch=worktree_branch,
                pushed_sha=head_sha,
                pushed_at=iso_z(),
            ).model_dump(),
        )
    except Exception as exc:  # noqa: BLE001
        raise _CheckpointError(f"failed to record checkpoint event: {exc}", 1) from exc

    return CheckpointOutput(
        run_id=resolved_run_id,
        branch=worktree_branch,
        pushed_sha=head_sha,
        pushed=True,
    )


# git's rejection reason when ``--force-with-lease`` refuses a push because the
# remote ref moved past the value the run last saw. Stable git text; matched
# case-insensitively so the divergence maps to a named outcome, not a raw blob.
_STALE_LEASE_MARKER = "stale info"


def _push_branch(*, worktree_path: Path, branch: str) -> str:
    """``git push --force-with-lease origin <branch>`` from the run's worktree.

    A **force-with-lease** push (sync — run in a thread). The run branch is the
    run's own private, rewritable WIP ref, not a shared branch — so when
    rebase-before-close rewrites it (the standing move when ``dev`` advances
    mid-run), the checkpoint must still be able to re-push the rewritten tip;
    a plain push is rejected non-fast-forward and durability silently reverts to
    the pre-rebase commit (CAL-1162). The lease keeps the push safe: it still
    **refuses** if ``origin`` carries a commit this run has not seen — that
    refusal is surfaced as the named ``reason='stale_remote'`` outcome rather than
    a raw git error blob, so a run knows its durability lapsed instead of learning
    it silently at resume time.

    Pushes nothing but the run's feature branch — never the base, never a merge —
    so the ``close`` gate is untouched. First checkpoint creates the branch on
    ``origin``; later ones update it (a fast-forward, or a lease-checked force
    after a rebase). Returns the git output for logging; that output is
    deliberately *not* propagated into the printed JSON (context-economy).
    """
    # A network op — bound it (CAL-1004). A fired timeout becomes the same
    # _CheckpointError a non-zero push already raises; the checkpoint is
    # best-effort, so the caller notes it and keeps working either way.
    try:
        result = run_git(
            worktree_path,
            "push",
            "--force-with-lease",
            "origin",
            branch,
            timeout=NETWORK_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise _CheckpointError(
            f"git push origin {branch} exceeded the "
            f"{NETWORK_GIT_TIMEOUT_SECONDS:.0f}s network timeout in {worktree_path}",
            1,
        ) from exc
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if _STALE_LEASE_MARKER in stderr.lower():
            # The lease refused: origin advanced past what this run last pushed.
            # A named, machine-readable outcome (not a raw git blob) so the run
            # knows its WIP durability lapsed — a resume would fetch the stale
            # pre-rebase tip.
            raise _CheckpointError(
                f"checkpoint refused for {branch}: origin carries a commit this "
                f"run has not seen, so the force-with-lease push was rejected — "
                f"the branch's WIP durability has lapsed (a resume would fetch "
                f"the stale pre-rebase tip)",
                1,
                reason="stale_remote",
            )
        raise _CheckpointError(
            f"git push origin {branch} failed in {worktree_path}: {stderr}",
            1,
        )
    return result.stdout + result.stderr
