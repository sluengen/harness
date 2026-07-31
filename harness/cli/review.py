"""``harness review`` — engine review of HEAD, verdict bound to the reviewed SHA.

The review verb makes review a callable, audited step.  It runs the selected
review engine (``--engine claude|codex``, default ``claude``; CAL-701) against
the worktree's current HEAD, parses the structured verdict, and appends a
``review`` event to the ledger that records the exact git SHA reviewed and the
engine that produced the verdict.  Each engine is a **read-only CLI subprocess**
emitting the same ``SUBMIT: <json>`` contract — never the Agent SDK (the diff and
ticket are untrusted prompt content).  Binding the verdict to HEAD is the
load-bearing correctness
detail (proposal ``harness-as-tool.md`` decision **D2**): the future ``close``
gate refuses to merge unless the ledger holds a ``verdict='pass'`` whose
``reviewed_sha`` equals HEAD, so a stale pass cannot be reused against a changed
tree.  If ``review`` does not record the SHA it actually reviewed, the gate is
theatre.

Flow (one ``asyncio.run`` event loop for all I/O):

1. Resolve "the current run" — the ``status='open'`` runs row whose
   ``worktree_path`` matches the resolved ``--repo`` (or ``--run-id`` override).
2. Capture ``git rev-parse HEAD`` in that worktree as ``reviewed_sha``.
3. Run the selected engine's read-only CLI (``claude -p --permission-mode plan``
   or ``codex exec --sandbox read-only --ephemeral -``) with the review prompt on
   stdin; capture stdout, stderr, and the exit code.  On an explicit
   ``--engine codex`` whose tier is exhausted (the usage-limit signal on stderr +
   a non-zero exit, CAL-702) fall back **once** to the Claude engine; an ordinary
   Codex failure does *not* fall back.  Scan the resulting stdout for the first
   ``SUBMIT:`` JSON line.
4. Parse the verdict ('pass'|'fail'|'defer') + issues.  No valid SUBMIT line
   means the reviewer delivered no verdict, so it exits ``EXIT_INFRA_FAILURE``
   with ``reason`` ``no_submit`` / ``malformed_submit`` rather than recording a
   ``fail`` (#270) — the same classification the timeout and sandbox walls carry.
   It therefore costs no review cycle and leaves the ticket In Review.
5. Append a ``review`` event carrying ``run_id``, ``reviewed_sha``, ``verdict``,
   ``issues``, ``engine`` (the engine that produced the verdict — ``claude``
   after a fallback), optional ``fallback_from`` (the engine a usage-limit
   fallback replaced), optional ``commit_message`` / ``deferred_brief``,
   ``created_at``, and (#262) ``outcome='ok'`` plus the ``invoked_at`` /
   ``duration_ms`` latency pair.

Every **other** way the verb can end also appends a ``review`` event now (#262,
ADR 0009) — a refusal shape carrying ``outcome='failed'``, the path's own
``reason``, and no ``verdict``. Before, only a parsed verdict was recorded, so
the ledger held verdicts and no denominator: "how often does review succeed?"
and "how often does the engine time out?" were unanswerable rather than slow.
The refusal row cannot widen the close gate, which filters ``$.verdict = 'pass'``
and reads a missing key as NULL, and it does not consume a review cycle, which
:func:`_count_review_events` excludes it from — a refusal runs no engine, so
charging it would shrink the budget as the telemetry was collected. The writer is
:func:`~harness.cli.review_telemetry.record_terminal_refusal`, called from one
place, and it never raises: observation is subordinate to what it observes.
6. Print only the bounded verdict (``verdict`` + ``issues`` + ``reviewed_sha`` +
   ``run_id`` + ``engine``).  The engine's full stdout / reasoning stays inside
   the verb and never
   enters the returned/printed JSON — the context-economy guarantee that keeps
   the orchestrating agent's context budget bounded.

Tracker transition (CAL-1103): ``review`` owns the In-Review state.  It moves the
ticket In Progress → **In Review** just before the engine runs (step 2b, after the
breaker and gate-evidence checks, so the queue shows "reviewing" while the engine
works), and hands it back to **In Progress** on a ``fail`` (it is being built
again) — ``pass``/``defer`` leave it In Review for ``close`` (→ Done) or a
follow-up.  The move is best-effort bookkeeping, never the record: a tracker-less
run or a transition failure warns (or silently no-ops) but never loses the
verdict, and a breaker (exit 4) / gate-evidence (exit 5) refusal fires *before*
the move, so an escalating run's ticket stays where it stopped.

Exit codes (mirroring ``harness start``):
* 0 — success; the verdict JSON is printed (a recorded ``fail`` is still a
      successful *review*, exit 0 — deciding what to do with a fail is the
      agent's job, not this verb's).
* 1 — unexpected error (git failure, DB error).
* 2 — invocation error: no open run resolved for the worktree.
* 3 — infra failure: the review engine could not run at all (e.g. a
      sandbox/namespace-init wall — ``codex``/bwrap cannot create a user
      namespace in a non-privileged container).  Surfaced distinctly with a
      machine-readable ``reason`` so the orchestrator can tell "the environment
      couldn't run the review" apart from "the diff was rejected" (CAL-866).
      This is NOT a code-review ``fail`` and NOT shippable, so it does not reuse
      ``defer`` or record a **verdict** — since #262 it records a refusal event,
      which carries no ``verdict`` key and so can never satisfy the close gate.
      Two shapes hit this exit: ``codex`` exiting non-zero with the bwrap marker on stderr
      (CAL-866), *and* ``codex`` exiting 0 but emitting a well-formed ``defer``
      whose reasoning is the same bwrap wall — every read-only command it ran was
      blocked, so it reviewed nothing (CAL-924).  Both mean the diff was never
      reviewed, so both are infra, not a verdict.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import typer
from pydantic import BaseModel

from harness._git import rev_parse_head
from harness._time import elapsed_ms, iso_z
from harness.cli._engine import EngineTimeoutError, run_engine_subprocess
from harness.cli._repo import resolve_repo_root_or_exit, resolve_verb_db_path
from harness.cli._runs import resolve_open_run
from harness.cli._verb import VerbError, run_verb
from harness.cli.review_inherit import InheritedReview, resolve_inheritance
from harness.cli.review_protocol import (
    DEFAULT_ENGINE,
    MALFORMED_SUBMIT_SENTINEL,
    NO_DESIGN_REASON,
    NO_SUBMIT_SENTINEL,
    Engine,
    Runner,
    RunResult,
    Verdict,
    _build_cmd,
    build_review_prompt,
    is_codex_usage_limit,
    is_sandbox_blocked_defer,
    is_sandbox_init_failure,
    resolve_design_gate,
    resolve_model_tier,
    scan_submit_line,
)
from harness.cli.review_telemetry import record_terminal_refusal
from harness.events.emitter import EventEmitter
from harness.events.payloads import (
    MALFORMED_SUBMIT_REASON,
    NO_SUBMIT_REASON,
    REVIEW_INHERITED_FROM_PATH,
    REVIEW_OUTCOME_OK,
    REVIEW_OUTCOME_PATH,
    ReviewEventData,
)
from harness.gate import GATE_NOT_CONFIGURED_REASON, load_gate_command, read_gate_log_tail
from harness.loop_budget import (
    convergence_check_required,
    evaluate_breakers,
    load_loop_budget,
)
from harness.state import store
from harness.tracker import tracker_client
from harness.tracker_errors import (
    TrackerConfigError,
    TrackerNotFound,
    TrackerRequestError,
)
from harness.workspace import WorkspaceNotAllowed, allowed_roots, resolve_within_allowlist

# The dimension resolve_model_tier reads for this verb (#177) — the review-tier
# label family (``review:<tier>``), independent of the build-tier family the
# ticket also carries as recorded judgement, which no verb consumes.
_REVIEW_TIER_DIMENSION = "review"

# size: the review verb — one cohesive orchestration on a single asyncio event
# loop: run resolution, the ledger-backed spend breakers (cycle ceiling +
# wall-clock; CAL-906), the verify-gate evidence check (CAL-1082), HEAD-bound SHA
# capture, the usage-limit → Claude fallback (CAL-702), event emission, and the
# best-effort In-Review / In-Progress tracker transitions (CAL-1103).  The pure
# engine-protocol layer — the prompt, the SUBMIT scanner, the per-engine command
# builder, and the three engine-failure detectors — was split out to
# harness.cli.review_protocol (CAL-1107); this verb imports and re-exports it.
# The bounded engine *subprocess driver* was split out to harness.cli._engine
# (#211), shared with the ``design`` verb; ``_default_runner`` is now only the
# review-specific translation of a timeout into this verb's infra failure.
# The inherit *decision* — may a resumed run carry a predecessor's pass forward?
# — was split out to harness.cli.review_inherit (#259) on the design_adopt.py
# precedent; what stays here is the guarded early return and the recording, which
# need ReviewOutput and EventEmitter and so have nowhere else to live.
# The terminal-observation *writer* — the event every non-verdict exit path now
# appends (#262) — was split out to harness.cli.review_telemetry on the same
# precedent, and for a reason the line count understates: inlining an emit at ten
# raise sites means the eleventh is eventually forgotten, and a denominator that
# is quietly wrong is worse than one that is loudly missing.  What stays here is
# the single ``except`` that calls it, which needs _ReviewError.
# What remains is verb glue with a single caller (`_run_review`): the breaker
# *decision* is already in harness.loop_budget (pure) and the gate in
# harness.gate, so this holds only their call sites — splitting them further
# would fragment the verb, not clarify it.
__all__ = [
    "review_command",
    "ReviewOutput",
    "scan_submit_line",
    "Engine",
    "RunResult",
    "is_codex_usage_limit",
    "is_sandbox_init_failure",
    "is_sandbox_blocked_defer",
    "EXIT_INFRA_FAILURE",
    "EXIT_BREAKER_TRIPPED",
    "EXIT_GATE_FAILED",
    "SANDBOX_INIT_REASON",
    "GATE_FAILED_REASON",
    "NO_GATE_EVIDENCE_REASON",
    "NO_DESIGN_REASON",
    "DESIGN_FILE_OUTSIDE_WORKSPACE_REASON",
]

# The engine-protocol surface (prompt, SUBMIT scanner, engine identity, command
# builder, failure detectors) lives in :mod:`harness.cli.review_protocol` and is
# imported above; the names are re-exported here so ``from harness.cli.review
# import scan_submit_line`` (and the tests' ``review_mod.<name>``) keep resolving.


# ---------------------------------------------------------------------------
# Output model — the bounded verdict the verb returns / prints.
# ---------------------------------------------------------------------------


class ReviewOutput(BaseModel):
    """Bounded review verdict.

    This is the ONLY thing printed: codex's full stdout / reasoning never
    appears here (context-economy AC).  ``commit_message`` / ``deferred_brief``
    are persisted to the ledger event but deliberately kept off the printed
    surface to hold the printed JSON to the minimal verdict the agent needs.

    ``convergence_check_required`` is a bounded advisory (CAL-906): ``True`` when
    this fail lands past the unconditional review→fix cycles and below the
    ceiling, so the build agent must assess whether the fixes are converging
    before spending another cycle. It is a single bool — no engine reasoning —
    so it does not breach the context-economy guarantee.
    """

    verdict: Verdict
    issues: list[str]
    reviewed_sha: str
    run_id: str
    engine: Engine
    convergence_check_required: bool = False


class _ReviewError(VerbError):
    """``review``'s control-flow exception — a :class:`VerbError` (CAL-1013).

    ``review`` *sets* ``reason`` (an optional stable, machine-readable tag
    emitted on the error JSON, mirroring ``close``'s ``{"error", "reason"}``
    refusal shape) so a caller can branch on the *kind* of failure — e.g. an
    infra wall vs an unexpected error — rather than string-matching the human
    message (CAL-866). The ``(message, code, reason)`` carrier is inherited from
    the base.
    """


# ---------------------------------------------------------------------------
# Default runner (real subprocess) — production path. The prompt, the SUBMIT
# scanner, and the per-engine ``_build_cmd`` builder are imported from
# harness.cli.review_protocol.
# ---------------------------------------------------------------------------


async def _default_runner(
    *,
    cmd: list[str],
    stdin: str,
    env: dict[str, str],
    cwd: Path | None,
    timeout: float | None = None,
) -> RunResult:
    """Run the review engine on the shared driver; translate a timeout to infra.

    The subprocess mechanics — spawn, feed ``stdin``, capture stdout/stderr/exit,
    kill and reap on expiry — live in :func:`~harness.cli._engine.run_engine_subprocess`,
    shared with the ``design`` verb (#211). stderr and the exit code come back
    captured so the Codex usage-limit fallback (CAL-702) can detect an exhausted
    tier: the limit signal lands on stderr with a non-zero exit, never on stdout.

    This wrapper adds the one review-specific part: a killed engine is failed as
    **infra** — a hung engine never reviewed the diff, so it is not a verdict —
    via ``_ReviewError`` (``EXIT_INFRA_FAILURE`` + :data:`ENGINE_TIMEOUT_REASON`).
    """
    try:
        return await run_engine_subprocess(cmd=cmd, stdin=stdin, env=env, cwd=cwd, timeout=timeout)
    except EngineTimeoutError as exc:
        raise _ReviewError(
            f"review engine exceeded its {exc.timeout:.0f}s timeout and was killed; "
            "this is an environment/infra failure (a hung engine never reviewed "
            "the diff), not a code-review verdict. Raise engine_timeout_seconds "
            "in CONTEXT.md's loop: block if the engine legitimately needs longer.",
            EXIT_INFRA_FAILURE,
            reason=ENGINE_TIMEOUT_REASON,
        ) from None


# ---------------------------------------------------------------------------
# Verb exit codes + machine-readable refusal reasons.  The engine-failure
# detectors that classify a subprocess result (usage-limit, the two sandbox
# walls) live in harness.cli.review_protocol; the exit codes and reasons below
# are the verb's own contract — they name the breaker / gate / infra outcomes the
# orchestrator branches on — so they stay here.
# ---------------------------------------------------------------------------

# Exit code for an infra failure (the review engine could not run at all).
# Distinct from a code-review ``fail`` (exit 0), an unexpected error (1), and an
# invocation error (2) so the orchestrator can tell an environment wall from a
# rejected diff (CAL-866).
EXIT_INFRA_FAILURE = 3

# Exit code for a tripped spend breaker (the run hit the review-cycle ceiling or
# the wall-clock budget; CAL-906). Distinct from every other code so the
# orchestrator can tell "stop and escalate, the loop is bounded out" from a
# rejected diff or an infra wall. Like the infra failure, no review event is
# recorded and the engine never runs — the carried ``reason`` names which breaker
# tripped (``review_cycle_ceiling`` / ``wall_clock_budget``).
EXIT_BREAKER_TRIPPED = 4

# Exit code for a run that cannot be certified as reviewable — the verify gate
# went red or supplied no evidence (CAL-1082), the run recorded no design
# attempt (#212, ADR 0007 D3), or ``--design-file`` names a path outside the
# workspace allowlist (AC-2, #247). All four mean there is nothing worth
# reviewing, or the request cannot be honoured as given: the verb refuses
# BEFORE the engine, records no review event, and spends no tokens. One code,
# because the response is the same shape in each case (supply the missing
# evidence, or fix the input, and review again); the machine-readable
# ``reason`` names which. Distinct from every other code — 2 is already the
# invocation error — so the orchestrator can tell an uncertifiable run from a
# rejected diff, an infra wall, or a bounded-out loop.
EXIT_GATE_FAILED = 5

# Stable, machine-readable ``reason`` carried on the infra-failure error JSON.
SANDBOX_INIT_REASON = "sandbox_init_failure"

# Machine-readable ``reason`` for a red verify gate (CAL-1082).
GATE_FAILED_REASON = "gate_failed"

# Machine-readable ``reason`` for a configured gate whose evidence was never
# supplied (CAL-1082). The orchestrator must run the gate and pass the result;
# silence is not a pass.
NO_GATE_EVIDENCE_REASON = "no_gate_evidence"

# Machine-readable ``reason`` for a ``--design-file`` that resolves outside the
# workspace allowlist (AC-2, #247). Distinct from the ADR 0007 design-context
# drop: an unreachable path is the wrong flag value, not an unusable design to
# degrade past, so it is refused as a caller error BEFORE the engine runs and
# BEFORE ``_read_design_file`` would otherwise map it to the same "unreadable"
# outcome as a legitimately stale in-workspace file. Shares
# ``EXIT_GATE_FAILED`` — same response shape (fix the input, review again).
DESIGN_FILE_OUTSIDE_WORKSPACE_REASON = "design_file_outside_workspace"

# Machine-readable ``reason`` for a review engine killed by the subprocess
# timeout (CAL-1004). Like the sandbox-init wall, a killed engine never reviewed
# the diff, so this is infra (``EXIT_INFRA_FAILURE``), not a code-review verdict:
# no review event is recorded and the run stops with a distinct, greppable tag
# rather than hanging until an external kill (exit 143).
ENGINE_TIMEOUT_REASON = "engine_timeout"

# Maps the review protocol's two failure sentinels onto their reason tags (#270),
# exactly as ``design`` maps its own pair. The protocol layer reports failures as
# human sentinels — it is pure and knows nothing of exit codes — and the verb owns
# the machine-readable contract. The tags themselves are shared with ``design``
# (harness.events.payloads) so one protocol failure has one name across both
# engine verbs.
_SUBMIT_FAILURE_REASONS = {
    NO_SUBMIT_SENTINEL: NO_SUBMIT_REASON,
    MALFORMED_SUBMIT_SENTINEL: MALFORMED_SUBMIT_REASON,
}


async def _invoke_engine(
    runner: Runner,
    engine: Engine,
    cwd: Path,
    *,
    prompt: str,
    timeout: float | None,
    model: str | None = None,
) -> RunResult:
    """Run one engine subprocess via ``runner``; wrap failures as ``_ReviewError``.

    ``timeout`` is forwarded to the runner as the per-subprocess ceiling
    (CAL-1004). A ``_ReviewError`` the runner already raised — the timeout
    infra-failure carries its own exit code and ``reason`` — passes through
    unchanged; only *other* exceptions are wrapped as the generic exit-1 error.
    ``model`` (#177) is forwarded to ``_build_cmd``, which appends it as
    ``--model`` on the claude engine only; codex ignores it.

    ``prompt`` is built once by the caller and passed in (#212), so a
    usage-limit fallback re-runs the *same* prompt — including its design
    context — rather than rebuilding one that could differ from the first.
    """
    try:
        return await runner(
            cmd=_build_cmd(engine, model=model),
            stdin=prompt,
            env=dict(os.environ),
            cwd=cwd,
            timeout=timeout,
        )
    except _ReviewError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _ReviewError(f"reviewer invocation failed: {exc}", 1) from exc


async def _resolve_review_model(
    repo_root: Path, ticket: str | None, explicit_model: str | None
) -> str:
    """Resolve the claude-engine ``--model`` alias for this review (#177).

    An explicit ``--model`` wins outright. Otherwise, resolve the ticket's
    ``review:<tier>`` label via :func:`resolve_model_tier` (default
    ``sonnet``). Best-effort: a tracker-less run, an unresolvable tracker
    config, or a fetch failure all degrade to the default rather than blocking
    the review — the tier is an optimization the review can run without, not
    part of the recorded verdict (mirroring ``_park_ticket``'s tolerance for
    tracker hiccups).
    """
    if explicit_model is not None:
        return explicit_model
    if ticket is None:
        return resolve_model_tier([], _REVIEW_TIER_DIMENSION)
    try:
        client = tracker_client(repo_root)
    except TrackerConfigError:
        return resolve_model_tier([], _REVIEW_TIER_DIMENSION)
    if client is None:
        return resolve_model_tier([], _REVIEW_TIER_DIMENSION)
    try:
        issue = await client.fetch_issue(ticket)
    except (TrackerNotFound, TrackerRequestError):
        return resolve_model_tier([], _REVIEW_TIER_DIMENSION)
    labels = issue.get("labels") or []
    return resolve_model_tier(labels, _REVIEW_TIER_DIMENSION)


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


def review_command(
    repo: Path = typer.Option(  # noqa: B008
        Path("."),
        "--repo",
        help="Worktree root to review (resolves the open run by worktree_path). Defaults to CWD.",
    ),
    run_id: str | None = typer.Option(
        None,
        "--run-id",
        help="Explicit run to review. Defaults to the open run whose worktree is --repo.",
    ),
    db: Path | None = typer.Option(  # noqa: B008
        None,
        "--db",
        help="Path to harness.db (defaults to .harness/harness.db under --repo).",
    ),
    engine: Engine = typer.Option(  # noqa: B008
        DEFAULT_ENGINE,
        "--engine",
        help="Review engine: claude (default) or codex. Both run read-only.",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help=(
            "Explicit model alias for the claude engine (host/testing). Takes "
            "precedence over the ticket's resolved review:<tier> label "
            "(#177); ignored on the codex engine."
        ),
    ),
    gate_exit: int | None = typer.Option(
        None,
        "--gate-exit",
        help=(
            "Exit code of the repo's verify gate (CONTEXT.md → verify:), which "
            "you run in the worktree before review. Required when a gate is "
            "configured; non-zero refuses."
        ),
    ),
    gate_log: Path | None = typer.Option(  # noqa: B008
        None,
        "--gate-log",
        help="File holding the gate's output; its tail is recorded as evidence.",
    ),
    design_file: Path | None = typer.Option(  # noqa: B008
        None,
        "--design-file",
        help=(
            "File holding this run's recorded design (the design_markdown "
            "`harness design` printed). Verified against the design event's "
            "hash, then given to the engine as review context."
        ),
    ),
    json_output: bool = typer.Option(  # noqa: B008
        True,
        "--json/--no-json",
        help="Emit machine-readable JSON (default: on).",
    ),
) -> None:
    """Review the worktree HEAD; record the verdict bound to that SHA.

    The engine is a read-only CLI subprocess (``--engine claude|codex``,
    default claude) emitting the ``SUBMIT:`` contract — never the Agent SDK.

    You run the repo's verify gate; this verb enforces and records the evidence
    (``--gate-exit``/``--gate-log``). It refuses to invoke any engine without
    fresh green evidence — see :mod:`harness.gate` for why the gate runs on your
    side and not in here.
    """
    repo_root = resolve_repo_root_or_exit(repo)
    db_path = resolve_verb_db_path(db, repo_root)

    output = run_verb(
        lambda: asyncio.run(
            _run_review(
                repo_root=repo_root,
                run_id=run_id,
                db_path=db_path,
                engine=engine,
                model=model,
                gate_exit=gate_exit,
                gate_log=gate_log,
                design_file=design_file,
                runner=_default_runner,
            )
        ),
        json_output=json_output,
    )

    if json_output:
        typer.echo(output.model_dump_json())
    else:
        typer.echo(f"{output.verdict} ({output.reviewed_sha}) — {len(output.issues)} issue(s)")


# ---------------------------------------------------------------------------
# Async orchestration — one event loop for all I/O.
# ---------------------------------------------------------------------------


async def _run_review(
    *,
    repo_root: Path,
    run_id: str | None,
    db_path: Path,
    engine: Engine,
    model: str | None = None,
    gate_exit: int | None = None,
    gate_log: Path | None = None,
    design_file: Path | None = None,
    runner: Runner,
) -> ReviewOutput:
    """Resolve the run, then drive the review, recording **every** terminal path.

    The split between this and :func:`_review_resolved_run` is the whole of #262:
    once a run is resolved, every way the verb can end is observable, so the body
    runs inside one ``except`` that appends the terminal event and re-raises the
    refusal untouched. Ten raise sites therefore need no emit of their own, and a
    raise site added later is recorded whether or not its author remembers to.

    Run resolution stays *outside* that handler on purpose: a ``review`` event is
    keyed to a run, and the two failures above — no ledger, or no open run — have
    no run to key it to. ADR 0009 records the same for ``close``'s ``no_run``.
    """
    # 1. Resolve the open run (by explicit id, else by worktree_path == repo).
    resolved = await resolve_open_run(db_path, repo_root, run_id)
    if resolved is None:
        raise _ReviewError(
            f"no open run found for worktree {repo_root} (run_id={run_id!r})"
            if run_id
            else f"no open run found for worktree {repo_root}",
            2,
        )
    resolved_run_id, worktree_path = resolved[0], resolved[1]

    # Captured before any breaker, gate or engine work — one end of the duration
    # every terminal event now carries, and the reference point that makes a slow
    # refusal distinguishable from a fast one.
    invoked_at = iso_z()
    try:
        return await _review_resolved_run(
            repo_root=repo_root,
            db_path=db_path,
            resolved_run_id=resolved_run_id,
            worktree_path=worktree_path,
            engine=engine,
            model=model,
            gate_exit=gate_exit,
            gate_log=gate_log,
            design_file=design_file,
            runner=runner,
            invoked_at=invoked_at,
        )
    except _ReviewError as exc:
        await record_terminal_refusal(
            db_path,
            run_id=resolved_run_id,
            reason=exc.reason,
            detail=str(exc),
            invoked_at=invoked_at,
        )
        raise


async def _review_resolved_run(
    *,
    repo_root: Path,
    db_path: Path,
    resolved_run_id: str,
    worktree_path: str,
    engine: Engine,
    model: str | None,
    gate_exit: int | None,
    gate_log: Path | None,
    design_file: Path | None,
    runner: Runner,
    invoked_at: str,
) -> ReviewOutput:
    """Drive the review flow for an already-resolved run; raise on failure.

    Every step below is unchanged from before #262 — the function boundary is
    where the terminal-event recording attaches, not a re-ordering of any
    refusal. The order of the checks is load-bearing and documented step by step.
    """
    # Two pure ledger reads hoisted above the short-circuit below, and reused by
    # the steps that already made them (2b and 1b) so nothing is read twice.
    # Moving a read is behaviour-preserving: every refusal keeps its position.
    ticket = await _read_ticket(db_path, resolved_run_id)
    design_event = await _read_latest_design_event(db_path, resolved_run_id)

    # 1a-0. Inherit a prior pass instead of re-earning one, when this run resumed
    #       from a preserved WIP branch and its HEAD is the exact commit a
    #       predecessor already passed behind a green gate (#259, ADR 0008 D3).
    #       Whether that is warranted lives in harness.cli.review_inherit; this is
    #       the verb recording it.
    #
    #       Deliberately FIRST — before the spend breakers and the verify-gate
    #       evidence check. Both exist to bound or certify the cost of running an
    #       engine over an unreviewed tree, and this path runs no engine over a
    #       tree already reviewed: charging it a review cycle would spend budget
    #       nothing consumed, and demanding fresh gate evidence would re-run the
    #       gate over a byte-identical tree, which is the second cost this path
    #       removes.
    #
    #       What it must NOT skip is a refusal about *this run's own state*, so
    #       the resolver takes the design event and the supplied gate exit as
    #       inputs and declines on either: a run with no recorded design still
    #       meets ``no_design``, and a caller reporting a red gate still meets
    #       ``gate_failed``, both from the normal path below. The safety the
    #       ordering rests on is otherwise entirely in the conditions — resume
    #       provenance, a clean worktree, an exact SHA match against another run
    #       for the same ticket, and that source pass's own gate evidence, the
    #       same predicate ``close`` will apply to the event this writes.
    inherited = await resolve_inheritance(
        db_path=db_path,
        run_id=resolved_run_id,
        ticket=ticket,
        worktree_path=Path(worktree_path),
        design_recorded=design_event is not None,
        gate_exit=gate_exit,
        created_at=iso_z(),
    )
    if inherited is not None:
        return await _record_inherited_review(repo_root, db_path, ticket, inherited)

    # 1a. Enforce the ledger-backed spend breakers BEFORE running an engine
    #     (CAL-906). This verb is the loop boundary, so the cycle ceiling and the
    #     per-run wall-clock are checked here against state already in the ledger:
    #     the count of prior ``review`` events and the run's ``started_at``. A
    #     trip records NO review event and never invokes an engine — it raises the
    #     refusal contract (a dedicated exit + machine-readable ``reason``) so the
    #     orchestrator stops and escalates rather than spinning the fix loop.
    budget = load_loop_budget(repo_root)
    prior_review_count = await _count_review_events(db_path, resolved_run_id)
    started_at = await _read_started_at(db_path, resolved_run_id)
    if started_at is not None:
        trip = evaluate_breakers(
            prior_review_count=prior_review_count,
            started_at=started_at,
            now=datetime.now(UTC),
            budget=budget,
        )
        if trip is not None:
            raise _ReviewError(trip.message, EXIT_BREAKER_TRIPPED, reason=trip.reason)

    # 1b. Enforce the design stage before invoking any engine (#212, ADR 0007
    #     D3), and resolve the design the engine will review against.
    #
    #     Deliberately BEFORE the gate-evidence check: a run that never recorded
    #     a design is malformed regardless of its gate colour, so refusing on the
    #     gate first would report a transient tree state while masking a missing
    #     lifecycle stage. Root cause first — and it is a single ledger read,
    #     cheaper than the gate log's file read. It stays AFTER the spend
    #     breakers, which stop a bounded-out run before any further work, and
    #     before the tracker park, so a refused run leaves its ticket where it
    #     stopped.
    #
    #     Enforcement keys on the LEDGER alone — the presence of a design event,
    #     which a failed attempt satisfies (D4) — so ``--design-file`` can
    #     neither satisfy nor bypass it. The flag only supplies the design text
    #     for context, and only a hash that matches the recorded event's lets it
    #     reach the prompt.
    #
    #     Before reading it at all, ``--design-file`` is checked against the
    #     workspace allowlist (AC-2, #247): a path that cannot resolve under it
    #     is a caller error — most often a host-only path like ``/tmp`` the
    #     harness wrapper never mounts into the container — not an unusable
    #     design to degrade past. Refusing it here, distinctly from the
    #     ADR 0007 drop below, keeps "wrong flag value" from silently reading
    #     identically to "a design that went stale" (the gap AC-1 also closes).
    #     Reuses :func:`harness.workspace.resolve_within_allowlist`, the same
    #     ``HARNESS_WORKSPACE_ROOTS`` boundary every verb's ``--repo`` is
    #     already checked against, so "the resolved workspace root" names one
    #     boundary, not a second ad hoc one.
    if design_file is not None:
        try:
            resolve_within_allowlist(design_file, allowed_roots())
        except WorkspaceNotAllowed as exc:
            roots_desc = ", ".join(str(r) for r in exc.roots) if exc.roots else "none configured"
            raise _ReviewError(
                f"--design-file {design_file} resolves to {exc.path}, which is "
                f"not reachable under the workspace root(s) this container can "
                f"read ({roots_desc}). The harness wrapper mounts only the repo "
                f"root into the container — stage the design file inside the "
                f"repo tree (e.g. under the worktree), not a host-only path "
                f"like /tmp.",
                EXIT_GATE_FAILED,
                reason=DESIGN_FILE_OUTSIDE_WORKSPACE_REASON,
            ) from exc

    design_gate = resolve_design_gate(
        design_event, await asyncio.to_thread(_read_design_file, design_file)
    )
    if design_gate.refusal_reason is not None:
        raise _ReviewError(
            design_gate.refusal_message or design_gate.refusal_reason,
            EXIT_GATE_FAILED,
            reason=design_gate.refusal_reason,
        )
    if design_gate.warning is not None:
        typer.echo(f"warning: {design_gate.warning}", err=True)

    # 1c. Enforce the repo's verify-gate EVIDENCE before invoking any engine
    #     (CAL-1082) — what makes a recorded ``pass`` mean "the gate ran green"
    #     rather than "a reviewer read the diff". The verb does not *run* the
    #     gate: the toolchain lives host-side, with the orchestrator (see
    #     ``harness.gate``). Deliberately AFTER the spend breakers above: a run
    #     that is already bounded out is refused on that, not on its gate.
    #
    #     Missing or red evidence refuses here — no engine, no review event, no
    #     tokens spent on a tree that cannot certify itself. An unconfigured gate
    #     is recorded as such and proceeds: the harness cannot gate what a repo
    #     does not define, and the ledger says so plainly instead of implying a
    #     gate ran.
    gate_command = load_gate_command(repo_root)
    gate_ran = False
    gate_reason: str | None = GATE_NOT_CONFIGURED_REASON
    gate_exit_code: int | None = None
    gate_output_tail: str | None = None
    if gate_command is not None:
        if gate_exit is None:
            raise _ReviewError(
                f"no verify-gate evidence supplied. This repo configures a gate "
                f"({gate_command!r}); run it in the worktree and pass the result "
                f"(--gate-exit <code> [--gate-log <path>]). No engine was invoked "
                f"and no verdict was recorded — the harness does not certify what "
                f"it cannot show was verified.",
                EXIT_GATE_FAILED,
                reason=NO_GATE_EVIDENCE_REASON,
            )
        gate_output_tail = await asyncio.to_thread(read_gate_log_tail, gate_log)
        if gate_exit != 0:
            raise _ReviewError(
                f"verify gate failed (exit {gate_exit}): {gate_command!r}. No "
                f"engine was invoked and no verdict was recorded — the harness "
                f"does not review a red tree. Fix the failure in "
                f"gate_output_tail and re-run review.",
                EXIT_GATE_FAILED,
                reason=GATE_FAILED_REASON,
                extra={"gate_output_tail": gate_output_tail},
            )
        gate_ran = True
        gate_reason = None
        gate_exit_code = gate_exit

    # 2. Capture HEAD at review time — the load-bearing SHA binding (D2).
    try:
        reviewed_sha = await asyncio.to_thread(rev_parse_head, Path(worktree_path))
    except Exception as exc:  # noqa: BLE001
        raise _ReviewError(f"failed to read HEAD for worktree {worktree_path}: {exc}", 1) from exc

    # 2b. Park the ticket In Review before the engine runs (CAL-1103) — the queue
    #     shows "reviewing" while the (possibly long) engine works. Deliberately
    #     AFTER the breaker (exit 4) and gate-evidence (exit 5) refusals above, so
    #     an escalating or red-gated run leaves the ticket where it stopped. The
    #     move is best-effort: a tracker-less run or a Linear hiccup never loses
    #     the review (the verdict is the record; the transition is bookkeeping).
    await _park_ticket(repo_root, ticket, to="in_review")

    # 2c. Resolve the claude-engine model tier (#177): an explicit --model
    #     wins, else the ticket's review:<tier> label, default sonnet. Codex
    #     ignores it — see _invoke_engine / _build_cmd.
    resolved_model = await _resolve_review_model(repo_root, ticket, model)

    # 3. Run the reviewer. On an explicit ``--engine codex`` whose tier is
    #    exhausted, fall back ONCE to the Claude engine (CAL-702): a depleted
    #    Codex tier degrades the gate to a false ``fail`` exactly when relied
    #    upon, so the verb substitutes Claude and records the substitution.
    #    Single hop only — Claude does not fall back to anything.
    engine_used: Engine = engine
    fallback_from: Engine | None = None

    # The configured per-subprocess ceiling (CAL-1004): a hung engine is killed
    # and surfaced as infra rather than hanging this verb until an external kill.
    engine_timeout = budget.engine_timeout_seconds
    # Built once (#212) so the usage-limit fallback below re-runs the identical
    # prompt, design context included.
    prompt = build_review_prompt(design_gate.design_markdown)
    result = await _invoke_engine(
        runner,
        engine,
        Path(worktree_path),
        prompt=prompt,
        timeout=engine_timeout,
        model=resolved_model,
    )

    # A review-engine sandbox/init failure (e.g. codex/bwrap cannot create a user
    # namespace in a non-privileged container) is INFRA, not a verdict — the
    # engine never reviewed the diff.  Surface it distinctly (a dedicated exit +
    # machine-readable ``reason``) so the orchestrator can tell an environment
    # wall from a rejected diff (CAL-866).  It is NOT shippable, so — unlike a
    # usage-limit, which degrades to a Claude verdict — it does NOT fall back,
    # does NOT reuse ``defer``, and records no review event: a non-zero exit
    # keeps it from ever reading as a pass or being swallowed.
    if is_sandbox_init_failure(result.stderr, result.returncode):
        raise _ReviewError(
            "review engine could not initialize its sandbox (bwrap: no "
            "permissions to create a new namespace); this is an environment/infra "
            "failure, not a code-review verdict — the engine never reviewed the "
            "diff. Run review where the engine can create a user namespace, or "
            "use a different --engine.",
            EXIT_INFRA_FAILURE,
            reason=SANDBOX_INIT_REASON,
        )

    if engine == "codex" and is_codex_usage_limit(result.stderr, result.returncode):
        fallback_from = "codex"
        engine_used = "claude"
        result = await _invoke_engine(
            runner,
            "claude",
            Path(worktree_path),
            prompt=prompt,
            timeout=engine_timeout,
            model=resolved_model,
        )

    # 4. Parse the SUBMIT line.  The engine's full stdout/stderr stays local to
    #    the verb — only the verdict escapes.
    parsed = scan_submit_line(result.stdout)

    # 4a. A reviewer that emitted no parseable SUBMIT line delivered no verdict,
    #     so this is INFRA, not a rejected diff (#270) — the same classification
    #     the timeout and both sandbox walls already carry, on the same stated
    #     principle. Recorded as a ``fail`` it was three things at once: one of
    #     six review cycles spent on nothing, a spurious bounce of the ticket back
    #     to In Progress, and 33% of the ``fail`` rate #262 made queryable being
    #     protocol noise indistinguishable from a real finding.
    #
    #     Raising here gets all three from machinery that already exists: the
    #     ``except _ReviewError`` in :func:`_review` writes #262's refusal shape
    #     (``outcome='failed'`` + ``reason``, no ``verdict`` key), which
    #     :func:`_count_review_events` excludes and the close gate cannot match;
    #     and the In-Progress bounce at step 5b is simply never reached, leaving
    #     the ticket In Review exactly where the other infra walls leave it.
    #
    #     Branching on ``submit_failure`` rather than on ``issues[0]`` is
    #     deliberate: a reviewer whose genuine finding happened to be worded like
    #     the sentinel must stay a ``fail``.
    if parsed.submit_failure is not None:
        raise _ReviewError(
            f"review engine produced no verdict: {parsed.submit_failure}. This is "
            f"an engine protocol failure, not a code-review verdict — the "
            f"reviewer never delivered one, so there is nothing to fix. No review "
            f"cycle was consumed; re-run review again.",
            EXIT_INFRA_FAILURE,
            reason=_SUBMIT_FAILURE_REASONS[parsed.submit_failure],
        )

    # 4b. A Codex ``defer`` whose reasoning is the bwrap namespace wall is a
    #     sandbox-blocked non-review, not a shippable defer (CAL-924): ``codex
    #     exec`` exited 0, but every read-only command it ran to inspect the diff
    #     was killed by bwrap, so it reviewed nothing.  The stderr/non-zero
    #     detector above misses this (exit 0, marker on stdout not stderr), so
    #     surface it as the SAME infra failure (CAL-866 contract) — dedicated exit
    #     + ``reason``, NO review event — rather than recording a ``defer`` for a
    #     review that never happened.  ``engine_used`` (not the requested engine)
    #     is what ran: a usage-limit fallback would already have flipped it to
    #     claude, and a claude ``defer`` is never treated this way.
    if is_sandbox_blocked_defer(parsed.verdict, parsed.issues, engine_used):
        raise _ReviewError(
            "review engine could not initialize its sandbox (bwrap: no "
            "permissions to create a new namespace); codex exec exited 0 but "
            "every command it ran to inspect the diff was blocked, so it "
            "reviewed nothing and emitted an empty 'defer'. This is an "
            "environment/infra failure, not a code-review verdict. Run review "
            "where the engine can create a user namespace, or use a different "
            "--engine.",
            EXIT_INFRA_FAILURE,
            reason=SANDBOX_INIT_REASON,
        )

    # 4c. The convergence advisory (CAL-906): this review is cycle
    #     ``prior_review_count + 1``. A fail past the unconditional window and
    #     below the ceiling tells the build agent to assess whether the fixes are
    #     converging before spending another cycle. A bounded bool — no engine
    #     reasoning — surfaced on both the printed verdict and the ledger event.
    needs_convergence_check = convergence_check_required(
        cycles_completed=prior_review_count + 1,
        verdict=parsed.verdict,
        budget=budget,
    )

    # 5. Append the review event — the full audited record (includes optional
    #    commit_message / deferred_brief which the printed verdict omits).
    created_at = iso_z()
    # The typed contract for this payload (CAL-1012): the close gate reads
    # ``reviewed_sha`` + ``verdict`` back out of it.  ``exclude_none=True``
    # reproduces the verb's old ``if x is not None`` optional keys — the fallback
    # marker (never silent, CAL-702 AC-4) and the commit_message / deferred_brief
    # stay absent from the JSON when unset.
    event_data = ReviewEventData(
        run_id=resolved_run_id,
        reviewed_sha=reviewed_sha,
        verdict=parsed.verdict,
        issues=parsed.issues,
        engine=engine_used,
        convergence_check_required=needs_convergence_check,
        created_at=created_at,
        gate_ran=gate_ran,
        design_context=design_gate.design_markdown is not None,
        design_context_reason=design_gate.context_reason,
        gate_command=gate_command,
        gate_exit_code=gate_exit_code,
        gate_reason=gate_reason,
        gate_output_tail=gate_output_tail,
        fallback_from=fallback_from,
        commit_message=parsed.commit_message,
        deferred_brief=parsed.deferred_brief,
        # #262: the latency pair. ``outcome`` is deliberately NOT passed — it is
        # the model's default, which is the single source of "a verdict was
        # produced" for both a new event and a pre-#262 row read back. Passing it
        # here would be a second copy of the literal that no test could tell from
        # the default. (A verdict is an ``ok`` outcome whichever way it went: a
        # ``fail`` is the review working, not the verb failing, which is why the
        # field is ``outcome`` rather than ``design``'s ``status``.)
        invoked_at=invoked_at,
        duration_ms=elapsed_ms(invoked_at, created_at),
    ).model_dump(exclude_none=True)

    emitter = EventEmitter(db_path)
    try:
        await emitter.emit(
            run_id=resolved_run_id,
            event_type="review",
            data=event_data,
        )
    except Exception as exc:  # noqa: BLE001
        raise _ReviewError(f"failed to record review event: {exc}", 1) from exc

    # 5b. A ``fail`` means the ticket is being built again — hand it back to In
    #     Progress (CAL-1103). AFTER the review event is recorded, so a transition
    #     failure can never lose the verdict (AC-4). ``pass``/``defer`` leave it In
    #     Review for ``close`` or a follow-up.
    if parsed.verdict == "fail":
        await _park_ticket(repo_root, ticket, to="in_progress")

    # 6. Return ONLY the bounded verdict — the engine's stdout stays inside the
    #    verb.  ``engine`` reflects the engine that actually produced the
    #    verdict (``claude`` after a fallback); ``fallback_from`` lives on the
    #    ledger event, off the printed contract (CAL-702).
    return ReviewOutput(
        verdict=parsed.verdict,
        issues=parsed.issues,
        reviewed_sha=reviewed_sha,
        run_id=resolved_run_id,
        engine=engine_used,
        convergence_check_required=needs_convergence_check,
    )


async def _record_inherited_review(
    repo_root: Path,
    db_path: Path,
    ticket: str | None,
    inherited: InheritedReview,
) -> ReviewOutput:
    """Record an inherited pass and emit it as an ordinary :class:`ReviewOutput`.

    **No engine runs.** The ticket is still parked In Review, best-effort: CAL-1103's
    invariant is that ``review`` owns the In-Review state, and a ``pass`` leaves it
    there for ``close`` — an inherited pass is not an exception to where the ticket
    ends up, only to how it got there.

    The printed contract is unchanged, so the orchestrator's Step 3 handling needs
    no adjustment and cannot tell an inherited pass from an earned one. The printed
    ``engine`` is the source's — the rule the usage-limit fallback already sets
    (CAL-702): ``engine`` names the engine that produced the verdict. That no engine
    ran *here* is on the **ledger** (``inherited_from``) and on stderr, where an
    operator reading a tick log will see it.
    """
    event = inherited.event
    emitter = EventEmitter(db_path)
    try:
        await emitter.emit(
            run_id=event.run_id,
            event_type="review",
            data=event.model_dump(exclude_none=True),
        )
    except Exception as exc:  # noqa: BLE001
        raise _ReviewError(f"failed to record review event: {exc}", 1) from exc

    await _park_ticket(repo_root, ticket, to="in_review")
    typer.echo(
        f"note: inherited the passing review recorded for run "
        f"{inherited.source_run_id} against this exact HEAD "
        f"({event.reviewed_sha[:12]}); no review engine ran",
        err=True,
    )
    return ReviewOutput(
        verdict="pass",
        issues=event.issues,
        reviewed_sha=event.reviewed_sha,
        run_id=event.run_id,
        # Narrowed by review_inherit, which declines a source whose engine is
        # outside the literal — so this cast asserts a checked fact.
        engine=cast("Engine", event.engine),
        convergence_check_required=False,
    )


# ---------------------------------------------------------------------------
# Ledger reads for the spend breakers (CAL-906)
# ---------------------------------------------------------------------------


async def _count_review_events(db_path: Path, run_id: str) -> int:
    """Count the engine-run ``review`` events already recorded for ``run_id``.

    This is the prior review→fix cycle count the cycle ceiling is measured
    against. A missing DB (no run yet) counts as zero.

    Events carrying ``inherited_from`` are **excluded** (#259): an inherited pass
    invokes no engine, so counting it would charge a run for spend it never
    incurred — and would let a resumed run's very first action, which costs
    nothing, eat a cycle of the budget it needs for real fixes.

    Non-``ok`` outcomes are excluded for the identical reason (#262). Recording
    the terminal paths put refusals into this very query's ``event_type =
    'review'`` population, and a refusal runs no engine either: without this
    clause, five ``no_gate_evidence`` refusals — which spend nothing and are the
    orchestrator's *own* mistake to fix — would leave the run one cycle from the
    ceiling, and adding telemetry would have silently shrunk the review budget.
    It would also contradict the contract this repo relies on elsewhere, that an
    ``engine_timeout`` is infra and consumes no cycle. ``COALESCE`` is what keeps
    the pre-#262 rows counted: they carry no ``outcome`` key, ``json_extract``
    answers NULL, and every one of them was in fact a verdict.
    """
    if not db_path.exists():
        return 0
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT COUNT(*) FROM events WHERE run_id = ? AND event_type = 'review' "
            "AND json_extract(data_json, ?) IS NULL "
            "AND COALESCE(json_extract(data_json, ?), ?) = ?",
            (
                run_id,
                REVIEW_INHERITED_FROM_PATH,
                REVIEW_OUTCOME_PATH,
                REVIEW_OUTCOME_OK,
                REVIEW_OUTCOME_OK,
            ),
        ) as cur,
    ):
        row = await cur.fetchone()
    return int(row[0]) if row is not None else 0


async def _read_latest_design_event(db_path: Path, run_id: str) -> dict[str, Any] | None:
    """The payload of the run's most recent ``design`` event, or ``None``.

    ``design`` is idempotent by append (#211): a re-run adds an event and mutates
    none, so the **newest** row is authoritative in both directions — a redesign
    that failed supersedes an earlier success exactly as a success supersedes an
    earlier failure. Ordered by ``id`` (the append order) rather than by
    ``timestamp``, so two events written inside the same second still order
    deterministically.

    A missing DB, no event, or an unparseable payload all yield ``None``, which
    the gate reads as "no design attempt" and refuses on — fail-safe, the same
    posture the close gate takes toward a payload it cannot read.
    """
    if not db_path.exists():
        return None
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT data_json FROM events WHERE run_id = ? AND event_type = 'design' "
            "ORDER BY id DESC LIMIT 1",
            (run_id,),
        ) as cur,
    ):
        row = await cur.fetchone()
    if row is None or row[0] is None:
        return None
    try:
        payload = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _read_design_file(design_file: Path | None) -> str | None:
    """The design text supplied by the orchestrator, or ``None`` if none was.

    ``None`` means *no path was given* — a normal state the gate passes over
    quietly. A path that was given but could not be read comes back as the empty
    string instead, so the gate sees a supplied design and fails to match it,
    warning as it does for any other unusable one. The distinction matters: an
    OS error is a caller mistake worth surfacing, whereas silently mapping it to
    "none supplied" would hide a broken orchestration behind a normal-looking
    review. The empty string can never match a recorded design — the design
    protocol rejects whitespace-only output — so this cannot pass by accident.
    """
    if design_file is None:
        return None
    try:
        return design_file.read_text(encoding="utf-8")
    except OSError:
        return ""


async def _read_started_at(db_path: Path, run_id: str) -> datetime | None:
    """Read the run's ``started_at`` as an aware datetime, or ``None``.

    ``runs.started_at`` is written with a plain ``.isoformat()`` (offset form, no
    trailing ``Z``); ``datetime.fromisoformat`` round-trips it (and also accepts
    the trailing-``Z`` form historical/seeded rows may carry, on Python 3.11+).
    A missing row or an unparseable value yields ``None`` so the wall-clock
    breaker degrades to "do not trip" rather than erroring the verb.
    """
    if not db_path.exists():
        return None
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT started_at FROM runs WHERE run_id = ?",
            (run_id,),
        ) as cur,
    ):
        row = await cur.fetchone()
    if row is None or row[0] is None:
        return None
    try:
        return datetime.fromisoformat(str(row[0]))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Tracker transition — review owns the In-Review state (CAL-1103)
# ---------------------------------------------------------------------------


async def _read_ticket(db_path: Path, run_id: str) -> str | None:
    """The Linear ticket identifier recorded on the run row, or ``None``.

    ``review`` moves this ticket In Review / back to In Progress (CAL-1103). A
    missing DB or a row with no ``ticket`` yields ``None`` so the caller skips the
    transition (there is nothing to move).
    """
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


async def _park_ticket(
    repo_root: Path, ticket: str | None, *, to: Literal["in_review", "in_progress"]
) -> None:
    """Best-effort Linear state move for the reviewed ticket (CAL-1103).

    ``review`` parks the ticket In Review before the engine runs, and hands it
    back to In Progress on a ``fail``. The move is **bookkeeping**; the verdict is
    the record — so this never refuses the review:

    * no ticket, tracker-less (``tracker: none``), or a misconfigured tracker (no
      credential / an incomplete config block — a ``TrackerConfigError``) → a
      silent no-op (there is no tracker to move a ticket in — the same posture
      ``close`` takes for a tracker-less run; and a misconfigured tracker is
      already rejected loudly at ``start``, so a real run never reaches review
      with it);
    * an actual transition-call failure (``TrackerNotFound`` / ``TrackerRequestError``)
      → a stderr warning, and the review proceeds — a tracker hiccup must never
      lose a recorded verdict (AC-4).
    """
    if ticket is None:
        return
    try:
        client = tracker_client(repo_root)
    except TrackerConfigError:
        # A tracker that cannot be resolved — no credential in this environment,
        # or a missing/incomplete config block (a LinearConfigError or a
        # GitHubConfigError) — is swallowed here, uniquely among the verbs: this
        # transition is non-essential bookkeeping, and review's contract is that a
        # tracker problem must never cost a recorded verdict (AC-4). A misconfigured
        # tracker is already rejected loudly at ``start``, so a real run never
        # reaches review with it; this is the belt-and-braces no-op, not a bypass.
        return
    if client is None:
        # tracker: none — nothing to transition, the same tracker-less no-op.
        return
    try:
        if to == "in_review":
            await client.transition_to_in_review(ticket)
        else:
            await client.transition_to_in_progress(ticket)
    except (TrackerNotFound, TrackerRequestError) as exc:
        typer.echo(
            f"warning: failed to move {ticket} to {to.replace('_', ' ')}: {exc}; "
            f"the review verdict is recorded regardless (the transition is "
            f"bookkeeping, not the record).",
            err=True,
        )
