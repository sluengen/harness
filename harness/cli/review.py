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
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple, cast

import typer
from pydantic import BaseModel

from harness._git import rev_parse_head
from harness._time import elapsed_ms, iso_z
from harness.cli._engine import EngineTimeoutError, run_engine_subprocess
from harness.cli._repo import REPO_OPTION, resolve_repo_argument, resolve_verb_db_path
from harness.cli._runs import read_run_assurance, resolve_attended, resolve_open_run
from harness.cli._verb import VerbError, run_verb
from harness.cli.review_inherit import InheritedReview, resolve_inheritance
from harness.cli.review_pollution import (
    measure_worktree_pollution,
    pollution_refusal_message,
)
from harness.cli.review_probe import (
    SENTINEL_FILENAME,
    ProbeOutcome,
    build_probe_feedback,
    combine_issues,
    combine_verdict,
    demonstrated_ids,
    read_probe_report,
    render_probe_table,
    screen_proposals,
    survivors,
)
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
    REVIEW_REFUSAL_REASON_PATH,
    REVIEW_REVIEWED_SHA_PATH,
    ProbeEntryRecord,
    ReviewEventData,
)
from harness.gate import GATE_NOT_CONFIGURED_REASON, load_gate_command, read_gate_log_tail
from harness.loop_budget import (
    REPEAT_ENGINE_TIMEOUT_REASON,
    LoopBudget,
    convergence_check_required,
    cycles_exhausted,
    evaluate_breakers,
    evaluate_repeat_timeout,
    load_loop_budget,
)
from harness.probe_tree import ProbeTreeError, create_probe_tree, snapshot_tree, teardown_probe_tree
from harness.state import store
from harness.tracker import tracker_client
from harness.tracker_errors import (
    TrackerConfigError,
    TrackerNotFound,
    TrackerRequestError,
)
from harness.workspace import WorkspaceNotAllowed, allowed_roots, resolve_within_allowlist

# size: the review verb — one cohesive orchestration on a single asyncio event
# loop: run resolution, the ledger-backed spend breakers (cycle ceiling +
# wall-clock, the latter unattended-only since #296, whose mode input this verb
# reads off the run row alongside started_at; CAL-906), the verify-gate evidence
# check (CAL-1082), HEAD-bound SHA
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
# Extraction considered and DEFERRED at #296: that ticket threads one keyword
# argument through the existing breaker call site and adds one column to one
# private single-row read (_read_breaker_inputs) — no new concept in the file.
# The only candidate seam, "the run facts the breaker block reads", would move
# ~20 lines into a module with exactly one importer; it becomes a seam when a
# second verb needs the same projection, and `reclaim --stale` (#297) projects
# its own rows for its own reasons.
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
    "RUN_WORKTREE_MUTATED_REASON",
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
    this fail precedes a cycle outside the unconditional window and inside the
    budget, so the build agent must assess whether the fixes are converging
    before spending another cycle. It is a single bool — no engine reasoning —
    so it does not breach the context-economy guarantee.

    ``cycles_exhausted`` (#329) is its terminal counterpart: ``True`` when this
    fail consumed the last review→fix cycle the run may spend. The two partition
    the fails — one asks for a judgment, the other says there is nothing left to
    judge — so the orchestrator stops here, preserves the WIP, and puts the
    ticket on operator hold rather than spending an implement pass on a cycle the
    verb will refuse. The exit-4 refusal remains the deterministic backstop for
    an orchestrator that ignores it.
    """

    verdict: Verdict
    issues: list[str]
    reviewed_sha: str
    run_id: str
    engine: Engine
    convergence_check_required: bool = False
    cycles_exhausted: bool = False
    #: The probe stage's two numbers (#363): how many reviewer-proposed
    #: mutations actually ran, and how many the suite failed to catch. Two
    #: integers are not engine reasoning, so the context-economy guarantee is
    #: intact — and they are what an orchestrator needs to read a `fail` whose
    #: findings are prefixed `[probe:<id>]` without going to the ledger. Zero on
    #: every path where no stage ran, which `probe_status` on the event
    #: disambiguates.
    probes_run: int = 0
    probes_survived: int = 0


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
            "the diff), not a code-review verdict. The usual cause is a hung "
            "engine, and one re-run against this same HEAD is worth trying — but "
            f"a second timeout at this SHA is refused ({REPEAT_ENGINE_TIMEOUT_REASON}) "
            "instead of retried, because repeated attempts at an unchanged tree "
            "return one identical answer at full cost each. Only if the ledger "
            "shows this engine *finishing* just past the ceiling, rather than "
            "hanging at it, is engine_timeout_seconds in CONTEXT.md's loop: block "
            "the thing to change.",
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

# Machine-readable ``reason`` for a run worktree that has drifted far past its
# own git index (#359). Shares ``EXIT_GATE_FAILED`` with the three refusals above
# — same response shape, and the same thing to do about it: fix the input and
# review again. A sixth exit code would say something new to an orchestrator that
# has nothing new to do.
#
# Distinct from :data:`ENGINE_TIMEOUT_REASON` in both the exit code (5, not 3)
# and the tag, and that distinctness is the point rather than a formality: a
# polluted tree *presents* as an engine timeout, so a shared tag would leave an
# operator reading the ledger unable to tell "the engine hung" from "we refused
# to let it".
POLLUTED_WORKTREE_REASON = "polluted_worktree"

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


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


class _HeadUnderReview:
    """The SHA this invocation is about, once the verb has read it (#347).

    Mutable and single-field by design: it is written once, immediately after
    ``rev_parse_head``, and read only by the terminal-refusal handler, which sits
    outside the frame that captured it. Everything before the capture leaves it
    ``None``, which is exactly the pre-HEAD refusals whose rows must stay as they
    were.
    """

    __slots__ = ("sha",)

    def __init__(self) -> None:
        self.sha: str | None = None


def review_command(
    repo: Path | None = REPO_OPTION,
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
    repo_root = resolve_repo_argument(repo)
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
                probe_runner=_default_probe_runner,
            )
        ),
        json_output=json_output,
    )

    if json_output:
        typer.echo(output.model_dump_json())
    else:
        typer.echo(f"{output.verdict} ({output.reviewed_sha}) — {len(output.issues)} issue(s)")


# ---------------------------------------------------------------------------
# The probe stage (#363) — the reviewer's mutation budget.
#
# The *judgment* is pure and lives in harness.cli.review_probe; the throwaway
# tree and the identity check are git mechanics in harness.probe_tree. What is
# here is the impure middle: spawn the mutation harness under the configured
# ceiling, and map every way it can end onto a recorded status.
# ---------------------------------------------------------------------------

#: The engine broke the one contract granting it execute rests on: it left the
#: reviewed worktree changed. Classified as INFRA, like the sandbox wall and the
#: timeout, because the reason is the same — the engine did not do the thing it
#: was asked to do, so no verdict it produced is trustworthy. It is not a code
#: review ``fail``: the diff was never the problem.
RUN_WORKTREE_MUTATED_REASON = "run_worktree_mutated"

#: ``scripts/mutate.py``, relative to the **primary checkout** — never the probe
#: tree. Only the *tree* comes from the reviewed SHA; the instrument that judges
#: it must not be swappable by the branch under review.
_MUTATE_SCRIPT = Path("scripts") / "mutate.py"


class _ProbeStage(NamedTuple):
    """What the probe stage did, reduced to what the event records."""

    status: str
    proposed: int = 0
    dropped: int = 0
    outcomes: tuple[ProbeOutcome, ...] = ()
    duration_ms: int = 0


async def _default_probe_runner(
    *,
    cmd: list[str],
    stdin: str,
    env: dict[str, str],
    cwd: Path | None,
    timeout: float | None = None,
) -> RunResult:
    """Spawn the mutation harness on the shared bounded driver.

    The same :func:`~harness.cli._engine.run_engine_subprocess` both engine verbs
    use, for the one property that makes AC-4's budget a *bound* rather than a
    convention: the subprocess is killed at ``timeout`` and reaped. A mutation
    can induce an infinite loop, so an unbounded probe stage would be a new way
    to hang a run — which is precisely the failure the review timeout exists for.

    A separate seam from ``_default_runner`` even though the shape is identical:
    tests must be able to stub the engine and the probe independently, and
    "the engine was never spawned" is an assertion this change needs to make.
    """
    return await run_engine_subprocess(cmd=cmd, stdin=stdin, env=env, cwd=cwd, timeout=timeout)


async def _run_probe_stage(
    *,
    repo_root: Path,
    run_id: str,
    reviewed_sha: str,
    raw_probes: list[Any] | None,
    budget: LoopBudget,
    probe_runner: Runner,
) -> _ProbeStage:
    """Run the reviewer's proposed mutations against a throwaway tree.

    **Every path degrades.** The stage returns a status and the review keeps the
    first pass's verdict; nothing here can refuse a run. That is ADR 0007 D4's
    posture for the design stage applied to an instrument that is strictly more
    optional than a design: probing is evidence-gathering, and an instrument that
    can wedge the thing it observes is worse than no instrument.

    The one thing it does **not** do is touch the run worktree. The probe tree is
    a different directory at the reviewed SHA, so the tree under review is
    untouched by construction rather than by care.
    """
    started = iso_z()
    if budget.probe_max_entries <= 0:
        return _ProbeStage(status="disabled")
    script = repo_root / _MUTATE_SCRIPT
    if not script.is_file():
        # A consuming repo, or one whose checkout predates the harness. Not an
        # error: the harness cannot mutate what a repo has no instrument for,
        # exactly as it cannot run a gate it has no toolchain for.
        return _ProbeStage(status="no_instrument")

    try:
        probe_tree = await asyncio.to_thread(create_probe_tree, repo_root, run_id, reviewed_sha)
    except ProbeTreeError as exc:
        typer.echo(f"warning: probe stage skipped — {exc}", err=True)
        return _ProbeStage(status="tree_failed")

    try:
        sentinel_text = f"{run_id} {reviewed_sha}"
        (probe_tree / SENTINEL_FILENAME).write_text(sentinel_text + "\n", encoding="utf-8")
        screened = await asyncio.to_thread(
            screen_proposals, raw_probes, tree=probe_tree, cap=budget.probe_max_entries
        )
        if screened.dropped:
            typer.echo(
                "warning: probe entries dropped — "
                + "; ".join(f"{i}: {r}" for i, r in screened.dropped),
                err=True,
            )
        if not screened.kept:
            return _ProbeStage(
                status="none_proposed",
                proposed=screened.proposed,
                dropped=len(screened.dropped),
                duration_ms=elapsed_ms(started, iso_z()) or 0,
            )

        with tempfile.TemporaryDirectory(prefix="harness-probe-") as scratch:
            scratch_dir = Path(scratch)
            table_path = scratch_dir / "probe.toml"
            report_path = scratch_dir / "report.json"
            table_path.write_text(
                render_probe_table(
                    screened.kept,
                    sentinel_file=SENTINEL_FILENAME,
                    sentinel_text=sentinel_text,
                ),
                encoding="utf-8",
            )
            cmd = [
                sys.executable,
                str(script),
                "run",
                "--table",
                str(table_path),
                "--tree",
                str(probe_tree),
                "--json",
                str(report_path),
                "--work-dir",
                str(scratch_dir / "work"),
                "--timeout",
                str(budget.probe_budget_seconds),
            ]
            try:
                result = await probe_runner(
                    cmd=cmd,
                    stdin="",
                    env=dict(os.environ),
                    cwd=repo_root,
                    timeout=float(budget.probe_budget_seconds),
                )
            except EngineTimeoutError:
                return _ProbeStage(
                    status="timeout",
                    proposed=screened.proposed,
                    dropped=len(screened.dropped),
                    duration_ms=elapsed_ms(started, iso_z()) or 0,
                )
            status = _probe_status_for(result)
            outcomes: tuple[ProbeOutcome, ...] = ()
            if status == "ran":
                outcomes = _read_probe_report_file(report_path)
                if not outcomes:
                    status = "error"
            return _ProbeStage(
                status=status,
                proposed=screened.proposed,
                dropped=len(screened.dropped),
                outcomes=outcomes,
                duration_ms=elapsed_ms(started, iso_z()) or 0,
            )
    finally:
        await asyncio.to_thread(teardown_probe_tree, repo_root, probe_tree)


def _refuse_if_worktree_moved(worktree: Path, before: str | None) -> None:
    """Refuse if the run worktree changed while an untrusted actor had control.

    Honest about its reach, per the rule ``design``'s own write grant states of
    itself: this detects what **git can see** — a tracked edit, a deletion, an
    untracked addition, HEAD moving — and not a write inside a gitignored path.
    It is a detector at the boundary, not the boundary. ``close``'s two conjuncts
    stay the enforcement, which is why the worst case remains a wedged run rather
    than a laundered merge.

    Skips when either snapshot is unknown. A failed ``git status`` is not
    evidence of a write, and manufacturing a refusal out of a failed probe would
    stop runs for a reason nothing observed.
    """
    if before is None:
        return
    after = snapshot_tree(worktree)
    if after is None or after == before:
        return
    raise _ReviewError(
        f"the run worktree at {worktree} changed while the review engine had "
        f"control. The reviewer runs read-only and the probe stage works in a "
        f"separate throwaway tree, so nothing in this verb should have written "
        f"here — the tree that would merge is no longer the tree that was "
        f"reviewed. No verdict was recorded. Inspect `git status` in the "
        f"worktree, restore it to the reviewed commit, and review again.",
        EXIT_INFRA_FAILURE,
        reason=RUN_WORKTREE_MUTATED_REASON,
    )


def _refusal_reason(stderr: str) -> str:
    """The refusal tag the mutation harness printed, or ``unknown``.

    Its contract is a stable first-line ``refused (<reason>): <message>``, and
    the tag exists precisely so a caller can branch on *which* rule refused
    rather than matching prose. Reading it is not scraping a human summary — the
    thing this module refuses to do with ``render()`` — it is reading the one
    machine-readable field a non-zero exit has room for.

    Falls back to ``unknown`` rather than raising: a status is an observation,
    and an observation that can fail the thing it observes is worse than a
    coarse one.
    """
    for line in stderr.splitlines():
        stripped = line.strip()
        if stripped.startswith("refused (") and "):" in stripped:
            return stripped[len("refused (") : stripped.index("):")]
    return "unknown"


def _probe_status_for(result: RunResult) -> str:
    """Map the mutation harness's exit code onto a recorded status.

    Its contract (0 all killed / 1 not / 2 refused / 3 runner unavailable / 4 at
    least one inert) is a *table verdict*, and every one of those is a legitimate
    outcome of asking a reviewer for mutations — 0, 1 and 4 all produced a report
    to read. Only 2 and 3 did not.

    A refusal carries *which* rule refused, taken from the harness's own stable
    tag rather than invented here — ``table`` / ``containment`` / ``landing`` /
    ``baseline`` / ``prediction`` / ``observable``. The distinction is the whole
    diagnostic value of the status: ``refused:prediction`` says the reviewer
    named a node id outside the selection (a defect in its proposal, and the
    measurement that decides whether a probing reviewer is worth its cost),
    while ``refused:baseline`` says the tree was already red and says nothing
    about the reviewer at all.

    ``unavailable`` (exit 3) is the one worth naming separately rather than
    folding into ``error``, because it is the expected in-container outcome: the
    verb's image is built ``--no-dev`` and carries no pytest, the same catch-22
    :mod:`harness.gate` records for the verify gate. A host-side install runs the
    stage; the container degrades and says so, rather than reporting a failure
    that reads like a defect in the diff.
    """
    if result.returncode in (0, 1, 4):
        return "ran"
    if result.returncode == 2:
        return f"refused:{_refusal_reason(result.stderr)}"
    if result.returncode == 3:
        return "unavailable"
    return "error"


def _read_probe_report_file(path: Path) -> tuple[ProbeOutcome, ...]:
    """Read the harness's ``--json`` report; ``()`` when it is not readable."""
    try:
        return read_probe_report(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return ()


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
    probe_runner: Runner,
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
    # The one fact the handler below needs that it cannot see (#347): HEAD is
    # captured deep inside the body, and a refusal raised after that point must
    # record which tree it was about. A one-field carrier rather than
    # ``_ReviewError.extra`` — ``extra`` is merged into the *printed* error JSON,
    # so using it would widen the CLI contract at every post-HEAD raise site for
    # a ledger-only need, and would put the burden back on each site to remember,
    # which is the very failure this single-handler split exists to prevent.
    head = _HeadUnderReview()
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
            probe_runner=probe_runner,
            invoked_at=invoked_at,
            head=head,
        )
    except _ReviewError as exc:
        await record_terminal_refusal(
            db_path,
            run_id=resolved_run_id,
            reason=exc.reason,
            detail=str(exc),
            invoked_at=invoked_at,
            reviewed_sha=head.sha,
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
    probe_runner: Runner,
    invoked_at: str,
    head: _HeadUnderReview | None = None,
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
    # The run's assurance snapshot (#352) — read once, here, beside the other two
    # hoisted ledger reads. It decides whether the design stage was required at
    # all, which both the inheritance resolver below and the design gate at 1b
    # need; the *decision* is harness.assurance's, never this verb's.
    assurance = await read_run_assurance(db_path, resolved_run_id)
    design_gate = resolve_design_gate(
        assurance, design_event, await asyncio.to_thread(_read_design_file, design_file)
    )

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
        # Not "did it record a design?" but "may it review without one?" (#352).
        # A ``simple`` run legitimately has no design event, and gating on the
        # event's presence would make such a run decline inheritance forever,
        # waiting for a ``no_design`` refusal that can no longer fire.
        design_precondition_met=design_gate.refusal_reason is None,
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
    breaker_inputs = await _read_breaker_inputs(db_path, resolved_run_id)
    if breaker_inputs.started_at is not None:
        trip = evaluate_breakers(
            prior_review_count=prior_review_count,
            started_at=breaker_inputs.started_at,
            now=datetime.now(UTC),
            budget=budget,
            attended=breaker_inputs.attended,
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
    if head is not None:
        head.sha = reviewed_sha

    # 2a. The third spend breaker, and the only one keyed on the tree (#347).
    #     An engine that has already hung twice at *this* SHA is not asked a
    #     third time: run 01KZ67FRV3HZRZ8CMAHBYBP4QT spent four ~725s attempts
    #     against one pushed SHA for four identical answers, ~44% of the
    #     unattended wall-clock budget, and finished only because the tree then
    #     changed. Repetition against a byte-identical tree gathers no evidence.
    #
    #     It sits HERE, not with the two breakers in 1a, only because it needs
    #     HEAD — and before the tracker park below, so a bounded-out run leaves
    #     its ticket where it stopped, exactly like the other two. Exit 4 rather
    #     than the timeout's own exit 3 is the point of the refusal: exit 3's
    #     documented orchestrator response is "just re-run", which is the loop
    #     being closed, whereas exit 4's is "stop and escalate".
    #
    #     Fail-open by construction: the count comes from the ledger, so rows
    #     predating #347 (which carry no ``reviewed_sha``) match no HEAD and read
    #     as zero. A guard that stops a run rests only on evidence the ledger
    #     actually holds.
    repeat_trip = evaluate_repeat_timeout(
        timeouts_at_sha=await _count_engine_timeouts_at_sha(
            db_path, resolved_run_id, reviewed_sha
        ),
        reviewed_sha=reviewed_sha,
        budget=budget,
    )
    if repeat_trip is not None:
        raise _ReviewError(repeat_trip.message, EXIT_BREAKER_TRIPPED, reason=repeat_trip.reason)

    # 2a'. Refuse a run worktree that has drifted far past its own git index
    #      (#359). A worktree carrying thousands of untracked files drowns the
    #      review engine's tool use: #208 arrived here with 3,555 files against
    #      578 tracked, burned the whole engine ceiling and returned
    #      ``engine_timeout`` having reviewed nothing; the tree cleaned to 586/578
    #      and the very next review returned a real verdict. #205 identified that
    #      cause and fixed it with a rule an operator has to keep ("never gate in
    #      the run worktree"); this is the same rule as a mechanism, turning a
    #      silent 720-second burn into an instant refusal that states its remedy.
    #
    #      Placed HERE for four reasons, each of which fixes one edge of the slot:
    #      after the inherit short-circuit (that path spawns no engine, so a
    #      polluted tree is irrelevant to it and refusing would block a review
    #      that costs nothing); after every cheaper pre-engine check, since a
    #      directory walk is the most expensive of them and a bounded-out,
    #      undesigned or red-gated run should be refused on *that*; after the HEAD
    #      capture just above, so the refusal row carries ``reviewed_sha`` and an
    #      operator reading the ledger sees ``engine_timeout`` and
    #      ``polluted_worktree`` against the same tree — the #208 correlation made
    #      legible; and before the tracker park below, so a refused run leaves its
    #      ticket where it stopped, exactly like every other pre-engine refusal.
    #
    #      Fail-open by construction, like the repeat-timeout breaker above: the
    #      measurement is ``None`` for every case it cannot answer (the check
    #      disabled, a path that is not a git top-level, a wedged or failed
    #      ``ls-files``, an empty index) and review proceeds. A guard that stops a
    #      run may rest only on evidence it actually gathered — and the failure it
    #      prevents is expensive but recoverable, whereas refusing a legitimate
    #      review is not.
    pollution = await asyncio.to_thread(
        measure_worktree_pollution,
        Path(worktree_path),
        limit=budget.untracked_file_limit,
    )
    if pollution is not None and pollution.refuses:
        raise _ReviewError(
            pollution_refusal_message(pollution),
            EXIT_GATE_FAILED,
            reason=POLLUTED_WORKTREE_REASON,
            extra={"worktree_pollution": pollution.as_payload()},
        )

    # 2b. Park the ticket In Review before the engine runs (CAL-1103) — the queue
    #     shows "reviewing" while the (possibly long) engine works. Deliberately
    #     AFTER the breaker (exit 4) and gate-evidence (exit 5) refusals above, so
    #     an escalating or red-gated run leaves the ticket where it stopped. The
    #     move is best-effort: a tracker-less run or a Linear hiccup never loses
    #     the review (the verdict is the record; the transition is bookkeeping).
    await _park_ticket(repo_root, ticket, to="in_review")

    # 2b'. Snapshot the run worktree before control passes to the engine (#363).
    #      Until this change nothing the engine produced could reach the tree —
    #      it runs read-only, and that was the third defence behind `close`'s
    #      SHA-bound pass and its dirty-worktree refusal. Granting the reviewer a
    #      way to cause execution removes that third defence, so the other two
    #      become load-bearing in a way they were not, and this makes the wedge
    #      surface where it happened rather than at the end of the run.
    #
    #      ``None`` when git cannot answer, and the comparison is then skipped:
    #      the same fail-open asymmetry the pollution check above states, for the
    #      same reason — a guard that stops a run may rest only on evidence it
    #      actually gathered.
    worktree_before = await asyncio.to_thread(snapshot_tree, Path(worktree_path))

    # 2c. Resolve the claude-engine model (#321): an explicit --model wins, else
    #     CONTEXT.md's loop.review_model (default sonnet). Codex ignores it —
    #     see _invoke_engine / _build_cmd. ``budget`` is already loaded for the
    #     breakers above, so this reads no file and makes no network call; the
    #     retired per-ticket tier (ADR 0005) made a tracker round-trip here.
    resolved_model = model if model is not None else budget.review_model

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
    prompt = build_review_prompt(
        design_gate.design_markdown, probe_cap=budget.probe_max_entries
    )
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

    # 4b-i. The engine has had control of a worktree it is not allowed to write.
    #       Check that before anything else uses its output (#363). Classified as
    #       INFRA rather than as a `fail`: the engine broke the contract its
    #       execute grant rests on, so no verdict it produced is trustworthy —
    #       the same reason the sandbox wall and the timeout are infra, and the
    #       same cost (no review cycle, ticket left In Review).
    _refuse_if_worktree_moved(Path(worktree_path), worktree_before)

    # 4b-ii. The probe stage: run the mutations the reviewer proposed against a
    #        throwaway tree at the reviewed SHA. Deliberately AFTER the infra
    #        classifications above — an engine that never delivered a verdict has
    #        proposed nothing worth running — and after the identity check, so a
    #        misbehaving engine is never handed a second opportunity.
    #
    #        Every path degrades: the stage records what happened and the first
    #        pass's verdict stands. Probing gathers evidence, and an instrument
    #        that can wedge the thing it observes is worse than no instrument
    #        (ADR 0007 D4's posture for the design stage, which is strictly less
    #        optional than this one).
    probe = await _run_probe_stage(
        repo_root=repo_root,
        run_id=resolved_run_id,
        reviewed_sha=reviewed_sha,
        raw_probes=parsed.probes,
        budget=budget,
        probe_runner=probe_runner,
    )
    # The probe tree is a different directory, but an `observe` is arbitrary
    # Python running as the invoking user (mutate.py says so plainly), so the
    # tree under review is re-checked after the stage as well as after the
    # engine.
    _refuse_if_worktree_moved(Path(worktree_path), worktree_before)

    # 4b-iii. The second pass, iff something survived. A fresh engine invocation
    #         under its own ceiling, told what its proposals did and what it
    #         already concluded, and asked to revise. It cannot propose more:
    #         `build_review_prompt` takes the feedback block *instead of* the
    #         request, so one review spends the budget once.
    #
    #         The combination is computed here, never trusted to that pass — a
    #         monotone max, so an engine just told its own proposals mostly
    #         failed cannot soften into withdrawing a finding about the diff.
    survived = survivors(probe.outcomes)
    second_verdict: str | None = None
    second_issues: list[str] | None = None
    if survived:
        try:
            second = await _invoke_engine(
                runner,
                engine_used,
                Path(worktree_path),
                prompt=build_review_prompt(
                    design_gate.design_markdown,
                    probe_feedback=build_probe_feedback(
                        probe.outcomes,
                        first_verdict=parsed.verdict,
                        first_issues=tuple(parsed.issues),
                    ),
                ),
                timeout=engine_timeout,
                model=resolved_model,
            )
            second_parsed = scan_submit_line(second.stdout)
            if second_parsed.submit_failure is None:
                second_verdict, second_issues = second_parsed.verdict, second_parsed.issues
        except _ReviewError as exc:
            # A second pass that times out or walls costs the review its probe
            # findings, never its verdict. Raising here would let an optional
            # enrichment fail a review the first pass already completed.
            typer.echo(f"warning: probe second pass did not complete: {exc}", err=True)
        _refuse_if_worktree_moved(Path(worktree_path), worktree_before)

    final_verdict = cast("Verdict", combine_verdict(parsed.verdict, second_verdict))
    final_issues = combine_issues(parsed.issues, second_issues)

    # 4c. The convergence advisory (CAL-906): this review is cycle
    #     ``prior_review_count + 1``. A fail past the unconditional window and
    #     below the ceiling tells the build agent to assess whether the fixes are
    #     converging before spending another cycle. A bounded bool — no engine
    #     reasoning — surfaced on both the printed verdict and the ledger event.
    needs_convergence_check = convergence_check_required(
        cycles_completed=prior_review_count + 1,
        verdict=final_verdict,
        budget=budget,
    )
    # 4d. The terminal signal (#329): this fail spent the last cycle the run may
    #     spend. Computed from the same cycle count, so the pair cannot disagree
    #     about which cycle this is.
    budget_exhausted = cycles_exhausted(
        cycles_completed=prior_review_count + 1,
        verdict=final_verdict,
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
        verdict=final_verdict,
        issues=final_issues,
        engine=engine_used,
        convergence_check_required=needs_convergence_check,
        cycles_exhausted=budget_exhausted,
        created_at=created_at,
        gate_ran=gate_ran,
        design_context=design_gate.design_markdown is not None,
        design_context_reason=design_gate.context_reason,
        gate_command=gate_command,
        gate_exit_code=gate_exit_code,
        gate_reason=gate_reason,
        gate_output_tail=gate_output_tail,
        fallback_from=fallback_from,
        # #293: the model the engine actually ran with, so review latency is
        # readable against ``design``'s and across a tier change. Keyed off
        # ``engine_used`` rather than the requested ``engine`` — the same
        # distinction ``engine=engine_used`` + ``fallback_from`` already draws:
        # a usage-limit fallback re-invokes claude with this same alias, and
        # codex ignores --model, so recording one there would assert a model
        # was in force when none was. ``resolved_model`` is the object passed
        # to the engine above, not a re-resolution of the ticket's label.
        model=resolved_model if engine_used == "claude" else None,
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
        # #363. `probe_status` carries the degradations as well as the successes
        # — six of its eight values are ways the stage did not produce a report —
        # because none of them may change a verdict, so "did it run, and if not
        # why" has to be answerable from the ledger rather than from stderr.
        probe_status=probe.status,
        probe_proposed=probe.proposed,
        probe_dropped=probe.dropped,
        probe_entries=[ProbeEntryRecord(**o.as_payload()) for o in probe.outcomes] or None,
        probe_demonstrated=list(demonstrated_ids(probe.outcomes)) or None,
        probe_duration_ms=probe.duration_ms,
        # Absent unless a stage ran at all: `False` on a repo that disabled
        # probing would assert that a pass which was never possible did not
        # happen.
        probe_second_pass=(second_verdict is not None) if survived else None,
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
    if final_verdict == "fail":
        await _park_ticket(repo_root, ticket, to="in_progress")

    # 6. Return ONLY the bounded verdict — the engine's stdout stays inside the
    #    verb.  ``engine`` reflects the engine that actually produced the
    #    verdict (``claude`` after a fallback); ``fallback_from`` lives on the
    #    ledger event, off the printed contract (CAL-702).
    return ReviewOutput(
        verdict=final_verdict,
        issues=final_issues,
        reviewed_sha=reviewed_sha,
        run_id=resolved_run_id,
        engine=engine_used,
        convergence_check_required=needs_convergence_check,
        cycles_exhausted=budget_exhausted,
        probes_run=len(probe.outcomes),
        probes_survived=len(survived),
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


async def _count_engine_timeouts_at_sha(db_path: Path, run_id: str, sha: str) -> int:
    """Count this run's ``engine_timeout`` refusals recorded **at ``sha``** (#347).

    The input to :func:`~harness.loop_budget.evaluate_repeat_timeout`, and the
    reason ``reviewed_sha`` had to reach the refusal payload: a fresh verb
    invocation has no in-process memory of the previous one, so "has the engine
    already hung at this exact tree?" is answerable only from the ledger.

    No ``outcome`` predicate is needed. :class:`~harness.events.payloads.ReviewEventData`
    has no ``reason`` field at all, so matching on the reason path already
    excludes every verdict row — the same property that lets ``close`` key its
    failure reads on :data:`~harness.events.payloads.CLOSE_REASON_PATH` alone.
    Nor does it count the repeat *refusals* themselves: those carry
    ``repeat_engine_timeout``, so the decision is idempotent — a run that refuses
    once refuses again on the same evidence rather than on evidence it generated.

    A missing DB counts as zero, as :func:`_count_review_events` does. This guard
    protects budget, not integrity, so absent evidence must let the engine run.
    """
    if not db_path.exists():
        return 0
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT COUNT(*) FROM events WHERE run_id = ? AND event_type = 'review' "
            "AND json_extract(data_json, ?) = ? AND json_extract(data_json, ?) = ?",
            (
                run_id,
                REVIEW_REFUSAL_REASON_PATH,
                ENGINE_TIMEOUT_REASON,
                REVIEW_REVIEWED_SHA_PATH,
                sha,
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


class _BreakerInputs(NamedTuple):
    """The two run-row facts :func:`evaluate_breakers` needs from this verb."""

    started_at: datetime | None
    attended: bool


async def _read_breaker_inputs(db_path: Path, run_id: str) -> _BreakerInputs:
    """Read the run's ``started_at`` and declared attendance mode.

    ``runs.started_at`` is written with a plain ``.isoformat()`` (offset form, no
    trailing ``Z``); ``datetime.fromisoformat`` round-trips it (and also accepts
    the trailing-``Z`` form historical/seeded rows may carry, on Python 3.11+).
    A missing row or an unparseable value yields ``None`` so the wall-clock
    breaker degrades to "do not trip" rather than erroring the verb.

    ``attended`` comes from the same row's ``inputs_json`` (#296, ADR 0011),
    resolved through the shared :func:`~harness.cli._runs.resolve_attended` —
    never by testing the column's truthiness here. That helper is where the
    value is validated, and it fails closed on every ambiguity, so a corrupt or
    hand-edited ledger can only ever make a run *more* bounded. Both facts come
    off one row in one read: a second query would be a second copy of the
    row-missing degrade rule to keep in step with this one.
    """
    if not db_path.exists():
        return _BreakerInputs(None, False)
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT started_at, inputs_json FROM runs WHERE run_id = ?",
            (run_id,),
        ) as cur,
    ):
        row = await cur.fetchone()
    if row is None or row[0] is None:
        return _BreakerInputs(None, False)
    attended = resolve_attended(row[1])
    try:
        return _BreakerInputs(datetime.fromisoformat(str(row[0])), attended)
    except ValueError:
        return _BreakerInputs(None, attended)


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
