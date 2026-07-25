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
4. Parse the verdict ('pass'|'fail'|'defer') + issues.  No valid SUBMIT line →
   ``verdict='fail'`` with the sentinel issue
   "reviewer emitted no valid SUBMIT line".
5. Append a ``review`` event carrying ``run_id``, ``reviewed_sha``, ``verdict``,
   ``issues``, ``engine`` (the engine that produced the verdict — ``claude``
   after a fallback), optional ``fallback_from`` (the engine a usage-limit
   fallback replaced), optional ``commit_message`` / ``deferred_brief``,
   ``created_at``.
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
      ``defer`` or record a verdict — no review event is written.  Two shapes hit
      this exit: ``codex`` exiting non-zero with the bwrap marker on stderr
      (CAL-866), *and* ``codex`` exiting 0 but emitting a well-formed ``defer``
      whose reasoning is the same bwrap wall — every read-only command it ran was
      blocked, so it reviewed nothing (CAL-924).  Both mean the diff was never
      reviewed, so both are infra, not a verdict.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import typer
from pydantic import BaseModel

from harness._time import iso_z
from harness.cli._engine import EngineTimeoutError, run_engine_subprocess
from harness.cli._git import rev_parse_head
from harness.cli._repo import resolve_repo_root_or_exit, resolve_verb_db_path
from harness.cli._runs import resolve_open_run
from harness.cli._verb import VerbError, run_verb
from harness.cli.review_protocol import (
    _REVIEW_PROMPT,
    DEFAULT_ENGINE,
    Engine,
    Runner,
    RunResult,
    Verdict,
    _build_cmd,
    is_codex_usage_limit,
    is_sandbox_blocked_defer,
    is_sandbox_init_failure,
    resolve_model_tier,
    scan_submit_line,
)
from harness.events.emitter import EventEmitter
from harness.events.payloads import ReviewEventData
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
        return await run_engine_subprocess(
            cmd=cmd, stdin=stdin, env=env, cwd=cwd, timeout=timeout
        )
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

# Exit code for a verify gate that cannot certify the tree (CAL-1082) — either
# the orchestrator's gate went red, or it supplied no evidence that a gate ran at
# all. Both mean there is nothing worth reviewing: the verb refuses BEFORE the
# engine, records no review event, and spends no tokens. Distinct from every
# other code — 2 is already the invocation error — so the orchestrator can tell
# "your gate is red / you never ran it" from a rejected diff, an infra wall, or a
# bounded-out loop.
EXIT_GATE_FAILED = 5

# Stable, machine-readable ``reason`` carried on the infra-failure error JSON.
SANDBOX_INIT_REASON = "sandbox_init_failure"

# Machine-readable ``reason`` for a red verify gate (CAL-1082).
GATE_FAILED_REASON = "gate_failed"

# Machine-readable ``reason`` for a configured gate whose evidence was never
# supplied (CAL-1082). The orchestrator must run the gate and pass the result;
# silence is not a pass.
NO_GATE_EVIDENCE_REASON = "no_gate_evidence"

# Machine-readable ``reason`` for a review engine killed by the subprocess
# timeout (CAL-1004). Like the sandbox-init wall, a killed engine never reviewed
# the diff, so this is infra (``EXIT_INFRA_FAILURE``), not a code-review verdict:
# no review event is recorded and the run stops with a distinct, greppable tag
# rather than hanging until an external kill (exit 143).
ENGINE_TIMEOUT_REASON = "engine_timeout"


async def _invoke_engine(
    runner: Runner, engine: Engine, cwd: Path, *, timeout: float | None, model: str | None = None
) -> RunResult:
    """Run one engine subprocess via ``runner``; wrap failures as ``_ReviewError``.

    ``timeout`` is forwarded to the runner as the per-subprocess ceiling
    (CAL-1004). A ``_ReviewError`` the runner already raised — the timeout
    infra-failure carries its own exit code and ``reason`` — passes through
    unchanged; only *other* exceptions are wrapped as the generic exit-1 error.
    ``model`` (#177) is forwarded to ``_build_cmd``, which appends it as
    ``--model`` on the claude engine only; codex ignores it.
    """
    try:
        return await runner(
            cmd=_build_cmd(engine, model=model),
            stdin=_REVIEW_PROMPT,
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
    runner: Runner,
) -> ReviewOutput:
    """Drive the review flow; raise :class:`_ReviewError` on failure."""
    # 1. Resolve the open run (by explicit id, else by worktree_path == repo).
    resolved = await resolve_open_run(db_path, repo_root, run_id)
    if resolved is None:
        raise _ReviewError(
            f"no open run found for worktree {repo_root} "
            f"(run_id={run_id!r})" if run_id else f"no open run found for worktree {repo_root}",
            2,
        )
    resolved_run_id, worktree_path = resolved[0], resolved[1]

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

    # 1b. Enforce the repo's verify-gate EVIDENCE before invoking any engine
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
    ticket = await _read_ticket(db_path, resolved_run_id)
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
    result = await _invoke_engine(
        runner, engine, Path(worktree_path), timeout=engine_timeout, model=resolved_model
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
            timeout=engine_timeout,
            model=resolved_model,
        )

    # 4. Parse the SUBMIT line (bad/missing → fail + sentinel).  The engine's
    #    full stdout/stderr stays local to the verb — only the verdict escapes.
    parsed = scan_submit_line(result.stdout)

    # 4a. A Codex ``defer`` whose reasoning is the bwrap namespace wall is a
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

    # 4b. The convergence advisory (CAL-906): this review is cycle
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
        gate_command=gate_command,
        gate_exit_code=gate_exit_code,
        gate_reason=gate_reason,
        gate_output_tail=gate_output_tail,
        fallback_from=fallback_from,
        commit_message=parsed.commit_message,
        deferred_brief=parsed.deferred_brief,
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


# ---------------------------------------------------------------------------
# Ledger reads for the spend breakers (CAL-906)
# ---------------------------------------------------------------------------


async def _count_review_events(db_path: Path, run_id: str) -> int:
    """Count the ``review`` events already recorded for ``run_id``.

    This is the prior review→fix cycle count the cycle ceiling is measured
    against. A missing DB (no run yet) counts as zero.
    """
    if not db_path.exists():
        return 0
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT COUNT(*) FROM events WHERE run_id = ? AND event_type = 'review'",
            (run_id,),
        ) as cur,
    ):
        row = await cur.fetchone()
    return int(row[0]) if row is not None else 0


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
