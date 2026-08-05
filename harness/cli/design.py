"""``harness design`` — the design stage, recorded before a line is implemented.

ADR 0007 adds a fourth verb between ``start`` and implement, making the run
lifecycle ``start → design → implement → review → (fix → review)* → close``. A
dedicated **Opus** engine studies the run's worktree and its ticket in a fresh
context and produces the change spec's technical Design section; the
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
2. Try the **adopt path** (:mod:`harness.cli.design_adopt`, ADR 0008 D1): a run
   that resumed from a preserved WIP branch, whose ticket carries a design that
   authenticates against a recorded ``ok`` event, records its **own** ``design``
   event marked ``inherited_from`` and returns the recovered design — no engine,
   no comment. Every other run falls through to steps 3–6 unchanged.
3. Fetch the ticket's title + description: they are the spec the design answers
   to, and ``start`` persists neither on the run row.
4. Capture ``git rev-parse HEAD`` in the worktree as ``grounded_sha``.
5. Allocate the run's output channel — a file in a fresh directory outside the
   worktree — and run the claude engine (built by
   :mod:`harness.cli.design_protocol`, granted write capability to that one
   path) under the configured ``engine_timeout_seconds`` ceiling.
6. Collect the design from that file, or from the stdout fallback if the write
   did not take; remove the directory either way.
7. Post the marked comment, append the ``design`` event, print ``DesignOutput``.

**The channel is a file (#294).** It used to be a single final ``SUBMIT: <json>``
line on stdout — ``review``'s contract, inherited by a verb whose payload is a
14–17 KB Markdown document rather than a fixed 100-character verdict. That cost
12.5% of design attempts on this repo's ledger against ``review``'s 0.24%, and
one run lost 12m44s of Opus and a complete design to a single missing brace.
See :mod:`harness.cli.design_protocol` for the contract and what replaced it.

**Degrade and record (ADR 0007 D4).** The design stage must never wedge a run.
Every way it can fail to produce a design — a killed engine, an engine that
cannot be spawned, no design on either channel, or a ticket spec that cannot be
read — appends a ``design`` event with ``status='failed'`` and a stable
``reason``, posts **no** comment, and exits :data:`EXIT_DESIGN_FAILED`. The
recorded *attempt* is what the review verb's ``no_design`` enforcement (#212)
checks, so a failure costs the run its design but never its ability to ship.

**Idempotent re-run.** Running ``design`` again appends a new event and posts a
new comment; the latest event is authoritative, and no prior event is mutated —
the ``review`` verdict pattern, on an append-only ledger.

Exit codes (mirroring ``harness review``):

* 0 — a design was produced, commented, and recorded.
* 1 — the design was produced but its ticket comment could not be posted: an
      expected failure that deliberately records **no** design event, so the
      run's next ``review`` refuses with ``no_design`` until ``harness design``
      is re-run against a reachable tracker; or an unexpected error (git
      failure, DB error).
* 2 — invocation error: no open run resolved for the worktree.
* 3 — no design was produced; the failed attempt is recorded and the carried
      ``reason`` names which failure it was (:data:`EXIT_DESIGN_FAILED`).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
from pathlib import Path
from tempfile import mkdtemp

import typer
from pydantic import BaseModel

from harness._git import rev_parse_head
from harness._time import elapsed_ms, iso_z, parse_iso_z
from harness.cli._engine import EngineTimeoutError, Runner, RunResult, run_engine_subprocess
from harness.cli._repo import REPO_OPTION_HELP, resolve_repo_argument, resolve_verb_db_path
from harness.cli._runs import resolve_open_run
from harness.cli._verb import VerbError, run_verb
from harness.cli.design_adopt import AdoptedDesign, resolve_adoption
from harness.cli.design_protocol import (
    DESIGN_MODEL_DEFAULT,
    DESIGN_OUT_FILENAME,
    DESIGN_TMP_PREFIX,
    DesignChannel,
    build_design_cmd,
    build_design_prompt,
    build_stdout_excerpt,
    design_content_hash,
    normalize_design,
    parse_design_fallback,
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
from harness.state import store

__all__ = [
    "DESIGN_ENGINE",
    "DesignOutput",
    "EXIT_DESIGN_FAILED",
    "EngineTimeoutError",
    "RunResult",
    "design_command",
]

# size: the design verb — one cohesive orchestration (adopt-or-engine → comment
# → event → output) on a single asyncio event loop, the same shape as
# ``review.py``; splitting it would scatter one verb's control flow across files.
# The two concerns that *are* separable already are: tracker I/O
# (``design_tracker.py``, #211) and the adopt decision (``design_adopt.py``,
# #258). What remains is flow plus the ledger write the flow's two branches
# share, which is why ``_record_adopted_design`` stays here rather than moving
# into ``design_adopt`` — it needs ``DesignOutput`` and ``_record_design_event``,
# and importing them back would make the seam circular.

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
NO_TICKET_SPEC_REASON = "no_ticket_spec"

# Neither channel delivered a design (#294). One tag covers both, because with a
# file as the channel there is no longer a distinction to draw: the two tags this
# replaced — ``no_submit`` and ``malformed_submit``, still used by ``review``,
# whose SUBMIT contract fits its small payload and is untouched — split "never
# reached the contract" from "reached it and emitted garbage", a distinction the
# JSON wire format created. A file is written or it is not.
#
# A **new** tag rather than reuse of ``no_submit`` is deliberate and is what makes
# this change measurable: ``stats_aggregate`` reads ``$.reason`` generically, so a
# distinct name is exactly what lets one ``harness stats`` table separate failures
# after the change from the 12.5% wire-format baseline before it, instead of
# summing them into a rate that can only be read as a trend.
NO_DESIGN_OUTPUT_REASON = "no_design_output"

# Which channel delivered the design, recorded on the ``ok`` event. ``file`` is
# the contract; ``stdout`` means the scoped write did not take and the fallback
# caught it — see ``_run_engine_and_collect``.
DESIGN_CHANNEL_FILE = "file"
DESIGN_CHANNEL_STDOUT = "stdout"

# The one wording of the fallback warning, so the stderr line and the ledger
# cannot drift into two phrasings of the same fact.
_FALLBACK_CHANNEL_WARNING = (
    "warning: the design for run {run_id} arrived on the stdout fallback, not "
    "the design file — the engine's scoped write capability did not take. The "
    "design is usable, but the permission configuration in build_design_cmd "
    "needs checking against the installed claude CLI"
)

# The one wording of the concurrent-invocation warning (#236), so the stderr
# line and any future reader cannot drift into two phrasings of the same fact.
_CONCURRENT_DESIGN_WARNING = (
    "another design event for run {run_id} was recorded at {ts}, after this "
    "invocation started — a second design invocation ran concurrently, and "
    "the last one to finish is the one bound to the run; confirm which design "
    "this run is bound to before implementing against it"
)


class DesignOutput(BaseModel):
    """The design the calling session implements from, plus its provenance.

    Unlike ``review`` — which prints only a bounded verdict and keeps the
    engine's output inside the verb — the design *is* the deliverable, so
    ``design_markdown`` is on the printed contract by design (ADR 0007). The
    context-economy guarantee still holds: what escapes is the design the engine
    delivered, never its reasoning, tool calls, or file reads.

    Which channel delivered it is deliberately **not** here. It is ledger
    telemetry about the engine, not something the orchestrator branches on — the
    design is the same design either way — and this key set is a locked contract
    (``test_verb_contract_locked.py``).

    ``concurrent_prior_at`` (#236) is set only when a stray overlapping
    ``design`` invocation is detected — see :func:`_record_design_event`.
    Dumped with ``exclude_none=True`` so the normal-path key set stays the six
    keys pinned since #211.
    """

    run_id: str
    design_markdown: str
    design_hash: str
    grounded_sha: str
    model: str
    status: str
    concurrent_prior_at: str | None = None


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

    def __init__(
        self,
        reason: str,
        detail: str,
        *,
        submit_excerpt: str | None = None,
        stdout_chars: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail
        # Set only at the SUBMIT-failure raise site (#277); every other failure
        # path has no engine stdout to quote and leaves both None.
        self.submit_excerpt = submit_excerpt
        self.stdout_chars = stdout_chars


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
    repo: Path | None = typer.Option(  # noqa: B008
        None,
        "--repo",
        help=REPO_OPTION_HELP,
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

    The engine is a ``claude -p`` subprocess that writes its design to one file
    outside the worktree, the only path it holds write capability for — it
    designs, it does not implement. Since #294 it holds one scoped write
    grant, so it is deliberately no longer described as read-only — that was the
    overclaim #294 was filed against. A run whose design cannot be produced records
    the failed attempt and exits 3; the build then proceeds without one rather
    than stalling (ADR 0007 D4).
    """
    repo_root = resolve_repo_argument(repo)
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
        typer.echo(output.model_dump_json(exclude_none=True))
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

    # Captured before any engine work — the concurrent-invocation detector's
    # (#236) reference point: a prior design event that finished at or after
    # this moment means a second invocation overlapped this one.
    invoked_at = iso_z()

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
            invoked_at=invoked_at,
        )
    except _DesignNotProducedError as exc:
        recorded = await _record_design_event(
            db_path,
            DesignEventData(
                run_id=resolved_run_id,
                status="failed",
                engine=DESIGN_ENGINE,
                model=resolved_model,
                designed_at=iso_z(),
                invoked_at=invoked_at,
                reason=exc.reason,
                detail=exc.detail,
                submit_excerpt=exc.submit_excerpt,
                stdout_chars=exc.stdout_chars,
            ),
        )
        extra = (
            {"concurrent_prior_at": recorded.concurrent_prior_at}
            if recorded.concurrent_prior_at is not None
            else None
        )
        raise _DesignError(
            f"no design was produced for run {resolved_run_id}: {exc.detail}. The "
            f"attempt is recorded in the ledger, so the run may proceed to "
            f"implement without a design (ADR 0007 D4).",
            EXIT_DESIGN_FAILED,
            reason=exc.reason,
            extra=extra,
        ) from exc


async def _run_engine_and_collect(
    *,
    runner: Runner,
    model: str,
    worktree_path: Path,
    title: str,
    description: str,
    timeout: float | None,
    run_id: str,
) -> tuple[str, str]:
    """Run the engine over a freshly allocated channel; return the design and how it arrived.

    The channel's directory is created here and removed in a ``finally`` on
    every path — success, timeout, unspawnable engine, or neither channel
    delivering — so no invocation leaves a design on disk. It lives outside the
    worktree, which is what keeps ``close``'s ``dirty_worktree`` gate untouched
    by anything this stage does.

    Collection order is **file, then stdout fallback**, and which one answered is
    returned so the ledger can record it. That ordering is not a preference
    between two equal channels: the file is the contract, and a design arriving
    on stdout means the scoped write did not take — a regression no test in this
    suite can catch, since none spawns a real engine. Recording it (and warning
    on stderr) is what turns that from a silent return to zero designs into a
    measurable degradation.

    Raises :class:`_DesignNotProducedError` when neither channel delivered, so
    the caller's single handler records the failed attempt (ADR 0007 D4).
    """
    tmpdir = Path(await asyncio.to_thread(mkdtemp, prefix=DESIGN_TMP_PREFIX))
    try:
        channel = DesignChannel(
            path=tmpdir / DESIGN_OUT_FILENAME,
            nonce=tmpdir.name[len(DESIGN_TMP_PREFIX) :],
        )
        try:
            result = await runner(
                cmd=build_design_cmd(model=model, channel=channel),
                stdin=build_design_prompt(title, description, channel=channel),
                env=dict(os.environ),
                cwd=worktree_path,
                timeout=timeout,
            )
        except EngineTimeoutError as exc:
            # A partial file a killed engine left behind is deliberately not
            # adopted: an engine cut off mid-write produced an arbitrary prefix,
            # and a silently truncated design becoming the run's contract is
            # worse than none. (The fallback's tolerance of a missing end marker
            # is a different case — there the engine finished and dropped a
            # marker.) The tempdir goes with it in the ``finally`` below.
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

        from_file = normalize_design(await asyncio.to_thread(_read_design_file, channel.path))
        if from_file is not None:
            return from_file, DESIGN_CHANNEL_FILE

        from_stdout = normalize_design(parse_design_fallback(result.stdout, channel.nonce))
        if from_stdout is not None:
            typer.echo(_FALLBACK_CHANNEL_WARNING.format(run_id=run_id), err=True)
            return from_stdout, DESIGN_CHANNEL_STDOUT

        # Neither channel delivered. The excerpt is the only evidence this
        # attempt leaves: a degraded run posts no comment and prints no engine
        # output, so what the engine said instead of delivering goes on the
        # ledger (#277).
        raise _DesignNotProducedError(
            NO_DESIGN_OUTPUT_REASON,
            f"the design engine wrote no design to {channel.path} and emitted no "
            f"marked fallback block on stdout",
            submit_excerpt=build_stdout_excerpt(result.stdout),
            stdout_chars=len(result.stdout),
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _read_design_file(path: Path) -> str | None:
    """Read the design the engine wrote, or ``None`` if it wrote none.

    ``errors="replace"`` rather than a raise: an engine that emitted a stray
    undecodable byte still designed, and turning that into an unexpected exit 1
    would lose a produced design to a transcoding detail. A missing file — the
    ordinary "the engine did not write" case — is likewise ``None``, not an
    error, because the fallback is still to be tried.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


async def _produce_design(
    *,
    repo_root: Path,
    db_path: Path,
    run_id: str,
    worktree_path: Path,
    model: str,
    runner: Runner,
    invoked_at: str,
) -> DesignOutput:
    """The success path: engine → comment → event → output.

    Every failure to produce a design raises :class:`_DesignNotProducedError`, which
    the caller turns into the one recorded ``failed`` attempt.
    """
    # 2. The ticket is the spec the design answers to. ``start`` persists no
    #    title/description on the run row, so they are fetched here.
    ticket = await read_run_ticket(db_path, run_id)

    # 2b. Adopt a prior design instead of designing one, when this run resumed
    #     from a preserved WIP branch and the ticket carries an authenticated
    #     design (ADR 0008 D1). Checked before the spec fetch: adoption needs no
    #     spec, so a flaky ticket read cannot cost a run a design it already has.
    adoption = await resolve_adoption(
        repo_root=repo_root,
        db_path=db_path,
        run_id=run_id,
        ticket=ticket,
        invoked_at=invoked_at,
    )
    if adoption is not None:
        return await _record_adopted_design(db_path, adoption)

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

    # 4. Run the engine under the configured ceiling and collect what it wrote.
    #    A hung engine is killed rather than hanging the verb.
    budget = load_loop_budget(repo_root)
    design_markdown, delivered_by = await _run_engine_and_collect(
        runner=runner,
        model=model,
        worktree_path=worktree_path,
        title=title,
        description=description,
        timeout=budget.engine_timeout_seconds,
        run_id=run_id,
    )
    design_hash = design_content_hash(design_markdown)

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
    recorded = await _record_design_event(
        db_path,
        DesignEventData(
            run_id=run_id,
            status="ok",
            engine=DESIGN_ENGINE,
            model=model,
            designed_at=iso_z(),
            invoked_at=invoked_at,
            design_hash=design_hash,
            grounded_sha=grounded_sha,
            channel=delivered_by,
            design_chars=len(design_markdown),
        ),
    )

    return DesignOutput(
        run_id=run_id,
        design_markdown=design_markdown,
        design_hash=design_hash,
        grounded_sha=grounded_sha,
        model=model,
        status="ok",
        concurrent_prior_at=recorded.concurrent_prior_at,
    )


async def _record_adopted_design(
    db_path: Path, adoption: AdoptedDesign
) -> DesignOutput:
    """Record an inherited design and emit it as an ordinary :class:`DesignOutput`.

    **No comment is posted.** The design is already on the ticket — that is where
    it was recovered from — and a second copy would fork the artifact ADR 0007 D2
    scopes to the change spec.

    The printed contract is unchanged, so the orchestrator's Step 1.5 handling
    (save ``design_markdown``, pass it as ``--design-file`` to ``review``) needs
    no adjustment and cannot tell an adopted design from a designed one. That
    the engine did not run is on the **ledger** (``inherited_from``) and on
    stderr, where an operator reading a tick log will see it.
    """
    event = adoption.event
    recorded = await _record_design_event(db_path, event)
    typer.echo(
        f"note: adopted the design recorded for run {event.inherited_from} "
        f"(design_hash {(event.design_hash or '')[:12]}); no design engine ran",
        err=True,
    )
    return DesignOutput(
        run_id=event.run_id,
        design_markdown=adoption.design_markdown,
        design_hash=event.design_hash or "",
        grounded_sha=event.grounded_sha or "",
        model=event.model,
        status="ok",
        concurrent_prior_at=recorded.concurrent_prior_at,
    )


# ---------------------------------------------------------------------------
# The ledger recording (the ticket comment lives in design_tracker)
# ---------------------------------------------------------------------------


async def _record_design_event(db_path: Path, data: DesignEventData) -> DesignEventData:
    """Append the ``design`` event — the run's recorded design attempt.

    Detects a concurrent invocation (#236) before writing: if the run's newest
    prior ``design`` event finished at or after this attempt's ``invoked_at``,
    a second invocation ran concurrently with this one and — since ``design``
    is idempotent-by-append (the newest event is authoritative) — this write
    is about to silently become the run's bound design, superseding one that
    someone may already be reading. That case gets ``concurrent_prior_at``
    stamped on the recorded event and a warning on stderr; a legitimate
    sequential re-run (the prior event predates ``invoked_at``) is untouched.

    Detection fails open: a DB read error or an unparseable timestamp records
    the design unchanged, with no flag — the artifact already exists, and
    wedging its recording on a diagnostic would violate ADR 0007 D4.

    ``exclude_none=True`` keeps each status's unused fields out of the JSON: an
    ``ok`` event carries no ``reason``/``detail``, a ``failed`` one no
    ``design_hash``/``grounded_sha``, rather than either reading as an explicit
    ``null``.

    Returns the (possibly flag-updated) data, so the caller can surface
    ``concurrent_prior_at`` on the printed output / error JSON too.
    """
    if data.invoked_at is not None:
        with contextlib.suppress(Exception):
            prior_timestamp = await _read_latest_design_timestamp(db_path, data.run_id)
            if prior_timestamp is not None and parse_iso_z(prior_timestamp) >= parse_iso_z(
                data.invoked_at
            ):
                data = data.model_copy(update={"concurrent_prior_at": prior_timestamp})
                typer.echo(
                    f"warning: {_CONCURRENT_DESIGN_WARNING.format(run_id=data.run_id, ts=prior_timestamp)}",  # noqa: E501
                    err=True,
                )

    # An **adopted** design records no duration (#264). Every other path measures
    # this invocation end to end, but on an adoption the two instants belong to
    # different runs: ``invoked_at`` is this run's, while ``designed_at`` is the
    # source's, carried verbatim (``design_adopt``). Subtracting them measures
    # backwards, to a design produced before this run began — a negative latency
    # no engine ever spent. Absence is the honest record, and ``inherited_from``
    # already marks the row for a reader that wants to attribute it to its source.
    #
    # The guard reads the semantic field, not the sign: negative-means-inherited
    # is an accident of the data, and a sign filter would also swallow a genuine
    # clock fault this is meant to record as-is.
    duration_ms = (
        None
        if data.inherited_from is not None
        else elapsed_ms(data.invoked_at, data.designed_at)
    )
    try:
        await EventEmitter(db_path).emit(
            run_id=data.run_id,
            event_type="design",
            data=data.model_dump(exclude_none=True),
            duration_ms=duration_ms,
        )
    except Exception as exc:  # noqa: BLE001
        raise _DesignError(f"failed to record design event: {exc}", 1) from exc
    return data


async def _read_latest_design_timestamp(db_path: Path, run_id: str) -> str | None:
    """The ``timestamp`` of the run's most recent prior ``design`` event, or ``None``.

    Ordered by ``id`` (append order), the same authority rule
    ``review._read_latest_design_event`` uses. Reading before this call's own
    insert is load-bearing — the query must not be able to see the row this
    invocation is about to write.
    """
    if not db_path.exists():
        return None
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT timestamp FROM events WHERE run_id = ? AND event_type = 'design' "
            "ORDER BY id DESC LIMIT 1",
            (run_id,),
        ) as cur,
    ):
        row = await cur.fetchone()
    return str(row[0]) if row is not None and row[0] is not None else None
