"""``harness design`` — the design stage, recorded before a line is implemented.

ADR 0007 adds a fourth verb between ``start`` and implement, making the run
lifecycle ``start → design → implement → review → (fix → review)* → close``. A
read-only **Opus** engine studies the run's worktree and its ticket in a fresh,
dedicated context and produces the change spec's technical Design section; the
build session then implements against that, instead of designing by rejection
across ``(fix → review)*`` cycles.

The verb's job is to make that stage *deterministic and auditable*. It records
the outcome in three places, every run:

1. the **ticket**, as a marked comment carrying the design verbatim
   (:mod:`harness.design_marker`) — the artifact is the change spec's Design
   section, not a new artifact class and not a file under ``specs/``;
2. the **ledger**, as a ``design`` event (:class:`~harness.events.payloads.DesignEventData`)
   carrying the design's content hash and the ``grounded_sha`` the engine studied;
3. **stdout**, as :class:`DesignOutput` — the design the calling session
   implements from.

Flow (one ``asyncio.run`` event loop for all I/O):

1. Resolve "the current run" — the ``status='open'`` runs row whose
   ``worktree_path`` matches the resolved ``--repo`` (or ``--run-id`` override),
   through the same shared resolver ``review`` and ``close`` use.
2. Fetch the ticket's title + description: they are the spec the design answers
   to, and ``start`` persists neither on the run row.
3. Capture ``git rev-parse HEAD`` in the worktree as ``grounded_sha``.
4. Run the read-only claude engine (``claude -p --permission-mode plan --model
   opus``, built by :mod:`harness.cli.design_protocol`) under the configured
   ``engine_timeout_seconds`` ceiling, and scan its stdout for the ``SUBMIT:``
   line.
5. Post the marked comment, append the ``design`` event, print ``DesignOutput``.

**Degrade and record (ADR 0007 D4).** The design stage must never wedge a run.
Every way it can fail to produce a design — a killed engine, an engine that
cannot be spawned, no ``SUBMIT`` line, a malformed one, or a ticket spec that
cannot be read — appends a ``design`` event with ``status='failed'`` and a stable
``reason``, posts **no** comment, and exits :data:`EXIT_DESIGN_FAILED`. The
recorded *attempt* is what the review verb's ``no_design`` enforcement (#212)
checks, so a failure costs the run its design but never its ability to ship.

**Idempotent re-run.** Running ``design`` again appends a new event and posts a
new comment; the latest event is authoritative, and no prior event is mutated —
the ``review`` verdict pattern, on an append-only ledger.

Exit codes (mirroring ``harness review``):

* 0 — a design was produced, commented, and recorded.
* 1 — unexpected error (git failure, DB error).
* 2 — invocation error: no open run resolved for the worktree.
* 3 — no design was produced; the failed attempt is recorded and the carried
      ``reason`` names which failure it was (:data:`EXIT_DESIGN_FAILED`).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

import typer
from pydantic import BaseModel

from harness._time import iso_z
from harness.cli._engine import EngineTimeoutError, Runner, RunResult, run_engine_subprocess
from harness.cli._git import rev_parse_head
from harness.cli._repo import resolve_repo_root_or_exit, resolve_verb_db_path
from harness.cli._runs import resolve_open_run
from harness.cli._verb import VerbError, run_verb
from harness.cli.design_protocol import (
    DESIGN_MODEL_DEFAULT,
    MALFORMED_SUBMIT_SENTINEL,
    NO_SUBMIT_SENTINEL,
    build_design_cmd,
    build_design_prompt,
    parse_design_submit,
)
from harness.cli.design_tracker import (
    TicketCommentFailedError,
    TicketSpecUnavailableError,
    fetch_ticket_spec,
    post_design_comment,
    read_run_ticket,
)
from harness.events.emitter import EventEmitter
from harness.events.payloads import DesignEventData
from harness.loop_budget import load_loop_budget

__all__ = [
    "DESIGN_ENGINE",
    "DesignOutput",
    "EXIT_DESIGN_FAILED",
    "EngineTimeoutError",
    "RunResult",
    "design_command",
]

# The design engine. Claude only — ADR 0002 keeps the in-container engine
# unprivileged, where codex's bwrap sandbox cannot start, so unlike ``review``
# there is no engine union and no ``--engine`` flag to select one.
DESIGN_ENGINE = "claude"

# Exit code for "no design was produced". One code for every degrade-and-record
# path (ADR 0007 D4) — a timeout, an unspawnable engine, unusable output, or an
# unreadable ticket spec all leave the run in the same place: a recorded failed
# attempt and no design. The carried ``reason`` is what distinguishes them, so an
# orchestrator branches on the tag rather than on five exit codes that would all
# call for the same response (proceed to implement without a design).
EXIT_DESIGN_FAILED = 3

# The stable, machine-readable ``reason`` tags carried on a failed attempt — on
# both the error JSON and the ledger event. The design-protocol module notes that
# the recorded reason is the only evidence of which failure happened, so each
# distinguishable failure gets its own tag.
ENGINE_TIMEOUT_REASON = "engine_timeout"
ENGINE_ERROR_REASON = "engine_error"
NO_SUBMIT_REASON = "no_submit"
MALFORMED_SUBMIT_REASON = "malformed_submit"
NO_TICKET_SPEC_REASON = "no_ticket_spec"

# Maps the design protocol's two failure sentinels onto their reason tags. The
# protocol layer reports failures as human sentinels (it is pure and knows
# nothing of exit codes); the verb owns the machine-readable contract.
_SUBMIT_FAILURE_REASONS = {
    NO_SUBMIT_SENTINEL: NO_SUBMIT_REASON,
    MALFORMED_SUBMIT_SENTINEL: MALFORMED_SUBMIT_REASON,
}


class DesignOutput(BaseModel):
    """The design the calling session implements from, plus its provenance.

    Unlike ``review`` — which prints only a bounded verdict and keeps the
    engine's output inside the verb — the design *is* the deliverable, so
    ``design_markdown`` is on the printed contract by design (ADR 0007). The
    context-economy guarantee still holds: what escapes is the engine's parsed
    ``SUBMIT`` payload, never its reasoning, tool calls, or file reads.
    """

    run_id: str
    design_markdown: str
    design_hash: str
    grounded_sha: str
    model: str
    status: str


class _DesignError(VerbError):
    """``design``'s control-flow exception — a :class:`VerbError` (CAL-1013).

    Carries a machine-readable ``reason`` on every failure that has one, so the
    orchestrator branches on the *kind* of failure rather than string-matching the
    message — the shape ``review`` and ``close`` already use.
    """


class _DesignNotProducedError(Exception):
    """Internal: the engine did not deliver a design (the degrade-and-record path).

    Raised by the steps that can fail to produce one and caught by the single
    handler that records the failed attempt, so the "append a ``failed`` event,
    post no comment, exit 3" contract lives in exactly one place instead of being
    re-implemented at each of the five failure sites.
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


async def _default_runner(
    *,
    cmd: list[str],
    stdin: str,
    env: dict[str, str],
    cwd: Path | None,
    timeout: float | None = None,
) -> RunResult:
    """Run the design engine on the shared driver; translate a timeout.

    The subprocess mechanics live in
    :func:`~harness.cli._engine.run_engine_subprocess`, shared with ``review``
    (#211). The one design-specific part is that a killed engine is *not* an
    unrecoverable infra failure here: it is a failure to produce a design, which
    ADR 0007 degrades and records — so the neutral timeout is re-raised as
    :class:`EngineTimeoutError` for the orchestration to record, not converted to
    a verb error that would skip the ledger write.
    """
    return await run_engine_subprocess(
        cmd=cmd, stdin=stdin, env=env, cwd=cwd, timeout=timeout
    )


def design_command(
    repo: Path = typer.Option(  # noqa: B008
        Path("."),
        "--repo",
        help="Worktree root to design for (resolves the open run by worktree_path). Defaults to CWD.",  # noqa: E501
    ),
    run_id: str | None = typer.Option(
        None,
        "--run-id",
        help="Explicit run to design for. Defaults to the open run whose worktree is --repo.",
    ),
    db: Path | None = typer.Option(  # noqa: B008
        None,
        "--db",
        help="Path to harness.db (defaults to .harness/harness.db under --repo).",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help=(
            f"Model alias for the design engine (host/testing override). "
            f"Defaults to {DESIGN_MODEL_DEFAULT!r} on every run — ADR 0007 makes "
            f"the design tier unconditional, not label-gated."
        ),
    ),
    json_output: bool = typer.Option(  # noqa: B008
        True,
        "--json/--no-json",
        help="Emit machine-readable JSON (default: on).",
    ),
) -> None:
    """Produce the run's Design section; record it on the ticket and the ledger.

    The engine is a read-only ``claude -p --permission-mode plan`` subprocess
    emitting the ``SUBMIT:`` contract — it designs, it does not implement. A run
    whose design cannot be produced records the failed attempt and exits 3; the
    build then proceeds without one rather than stalling (ADR 0007 D4).
    """
    repo_root = resolve_repo_root_or_exit(repo)
    db_path = resolve_verb_db_path(db, repo_root)

    output = run_verb(
        lambda: asyncio.run(
            _run_design(
                repo_root=repo_root,
                run_id=run_id,
                db_path=db_path,
                model=model,
                runner=_default_runner,
            )
        ),
        json_output=json_output,
    )

    if json_output:
        typer.echo(output.model_dump_json())
    else:
        typer.echo(
            f"design recorded ({output.design_hash[:12]}) grounded at "
            f"{output.grounded_sha[:12]}"
        )


# ---------------------------------------------------------------------------
# Async orchestration — one event loop for all I/O.
# ---------------------------------------------------------------------------


async def _run_design(
    *,
    repo_root: Path,
    run_id: str | None,
    db_path: Path,
    model: str | None,
    runner: Runner,
) -> DesignOutput:
    """Drive the design flow; raise :class:`_DesignError` on failure."""
    # 1. Resolve the open run (by explicit id, else by worktree_path == repo) —
    #    the shared resolver, so "which run is this" cannot drift between verbs.
    resolved = await resolve_open_run(db_path, repo_root, run_id)
    if resolved is None:
        raise _DesignError(
            f"no open run found for worktree {repo_root} (run_id={run_id!r})"
            if run_id
            else f"no open run found for worktree {repo_root}",
            2,
        )
    resolved_run_id, worktree_path = resolved[0], resolved[1]
    resolved_model = model if model is not None else DESIGN_MODEL_DEFAULT

    # Everything from here on is recordable: a failure to produce a design is
    # data, not an error, so it appends its event before surfacing (ADR 0007 D4).
    try:
        return await _produce_design(
            repo_root=repo_root,
            db_path=db_path,
            run_id=resolved_run_id,
            worktree_path=Path(worktree_path),
            model=resolved_model,
            runner=runner,
        )
    except _DesignNotProducedError as exc:
        await _record_design_event(
            db_path,
            DesignEventData(
                run_id=resolved_run_id,
                status="failed",
                engine=DESIGN_ENGINE,
                model=resolved_model,
                designed_at=iso_z(),
                reason=exc.reason,
                detail=exc.detail,
            ),
        )
        raise _DesignError(
            f"no design was produced for run {resolved_run_id}: {exc.detail}. The "
            f"attempt is recorded in the ledger, so the run may proceed to "
            f"implement without a design (ADR 0007 D4).",
            EXIT_DESIGN_FAILED,
            reason=exc.reason,
        ) from exc


async def _produce_design(
    *,
    repo_root: Path,
    db_path: Path,
    run_id: str,
    worktree_path: Path,
    model: str,
    runner: Runner,
) -> DesignOutput:
    """The success path: engine → comment → event → output.

    Every failure to produce a design raises :class:`_DesignNotProducedError`, which
    the caller turns into the one recorded ``failed`` attempt.
    """
    # 2. The ticket is the spec the design answers to. ``start`` persists no
    #    title/description on the run row, so they are fetched here.
    ticket = await read_run_ticket(db_path, run_id)
    try:
        title, description = await fetch_ticket_spec(repo_root, ticket)
    except TicketSpecUnavailableError as exc:
        raise _DesignNotProducedError(NO_TICKET_SPEC_REASON, exc.detail) from exc

    # 3. Capture the tree the engine designs against, so the recorded design can
    #    later be told apart from one grounded in a different HEAD.
    try:
        grounded_sha = await asyncio.to_thread(rev_parse_head, worktree_path)
    except Exception as exc:  # noqa: BLE001
        raise _DesignError(
            f"failed to read HEAD for worktree {worktree_path}: {exc}", 1
        ) from exc

    # 4. Run the read-only engine under the configured ceiling and parse its one
    #    SUBMIT line. A hung engine is killed rather than hanging the verb.
    budget = load_loop_budget(repo_root)
    try:
        result = await runner(
            cmd=build_design_cmd(model=model),
            stdin=build_design_prompt(title, description),
            env=dict(os.environ),
            cwd=worktree_path,
            timeout=budget.engine_timeout_seconds,
        )
    except EngineTimeoutError as exc:
        raise _DesignNotProducedError(
            ENGINE_TIMEOUT_REASON,
            f"the design engine exceeded its {exc.timeout:.0f}s timeout and was "
            f"killed; raise engine_timeout_seconds in CONTEXT.md's loop: block if "
            f"it legitimately needs longer",
        ) from None
    except Exception as exc:  # noqa: BLE001
        raise _DesignNotProducedError(
            ENGINE_ERROR_REASON, f"the design engine could not be run: {exc}"
        ) from exc

    parsed = parse_design_submit(result.stdout)
    if parsed.design_markdown is None:
        sentinel = parsed.error or NO_SUBMIT_SENTINEL
        raise _DesignNotProducedError(
            _SUBMIT_FAILURE_REASONS.get(sentinel, NO_SUBMIT_REASON), sentinel
        )
    design_markdown = parsed.design_markdown
    design_hash = hashlib.sha256(design_markdown.encode("utf-8")).hexdigest()

    # 5. Post the artifact, then record the event — the external effect first and
    #    the audit record second, the ordering ``defer`` and ``reclaim`` use, so a
    #    ledger failure surfaces rather than silently dropping a posted design.
    try:
        await post_design_comment(
            repo_root,
            ticket,
            run_id=run_id,
            design_markdown=design_markdown,
            design_hash=design_hash,
            grounded_sha=grounded_sha,
        )
    except TicketCommentFailedError as exc:
        raise _DesignError(exc.detail, 1) from exc
    await _record_design_event(
        db_path,
        DesignEventData(
            run_id=run_id,
            status="ok",
            engine=DESIGN_ENGINE,
            model=model,
            designed_at=iso_z(),
            design_hash=design_hash,
            grounded_sha=grounded_sha,
        ),
    )

    return DesignOutput(
        run_id=run_id,
        design_markdown=design_markdown,
        design_hash=design_hash,
        grounded_sha=grounded_sha,
        model=model,
        status="ok",
    )


# ---------------------------------------------------------------------------
# The ledger recording (the ticket comment lives in design_tracker)
# ---------------------------------------------------------------------------


async def _record_design_event(db_path: Path, data: DesignEventData) -> None:
    """Append the ``design`` event — the run's recorded design attempt.

    ``exclude_none=True`` keeps each status's unused fields out of the JSON: an
    ``ok`` event carries no ``reason``/``detail``, a ``failed`` one no
    ``design_hash``/``grounded_sha``, rather than either reading as an explicit
    ``null``.
    """
    try:
        await EventEmitter(db_path).emit(
            run_id=data.run_id,
            event_type="design",
            data=data.model_dump(exclude_none=True),
        )
    except Exception as exc:  # noqa: BLE001
        raise _DesignError(f"failed to record design event: {exc}", 1) from exc
