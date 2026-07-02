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
import json
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple

import typer
from pydantic import BaseModel

from harness._time import iso_z
from harness.cli._git import rev_parse_head
from harness.cli._repo import resolve_repo_root_or_exit, resolve_verb_db_path
from harness.cli._runs import resolve_open_run
from harness.events.emitter import EventEmitter
from harness.loop_budget import (
    convergence_check_required,
    evaluate_breakers,
    load_loop_budget,
)
from harness.state import store

# size: one cohesive verb — the review prompt, bounded output model, SUBMIT-line
# scanner, the engine-failure detectors (usage-limit → Claude fallback, and two
# sandbox walls → infra exit: codex's non-zero-exit/stderr case and its exit-0
# masquerading-defer case; CAL-702/CAL-866/CAL-924), the ledger-backed spend
# breakers (cycle ceiling + wall-clock; CAL-906), and the single-event-loop
# orchestration.  The detectors + breaker glue have one caller (`_run_review`);
# splitting them off to chase the 500-line limit would fragment the verb, not
# clarify it. The breaker *decision* is already factored out to
# harness.loop_budget (pure).
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
    "SANDBOX_INIT_REASON",
]

# Sentinel issue recorded when the reviewer emits no parseable SUBMIT line.
NO_SUBMIT_SENTINEL = "reviewer emitted no valid SUBMIT line"

# The verdicts the SUBMIT line may carry.  Anything else is treated as garbled.
_VALID_VERDICTS: frozenset[str] = frozenset({"pass", "fail", "defer"})

Verdict = Literal["pass", "fail", "defer"]

# The review engines.  Both are CLI subprocesses emitting the same ``SUBMIT:``
# contract — never the Agent SDK (CAL-701; architecture-principles "a review
# engine is a CLI subprocess").  ``claude`` is the default: it is available on
# the standard tier and auto-compacts, so the gate does not degrade to a false
# ``fail`` when the Codex tier is depleted.  ``codex`` stays opt-in for a
# cross-model second opinion.
Engine = Literal["claude", "codex"]
DEFAULT_ENGINE: Engine = "claude"

class RunResult(NamedTuple):
    """The full result of one engine subprocess: stdout, stderr, exit code.

    The CAL-702 usage-limit fallback needs stderr **and** the exit code to tell
    an exhausted Codex tier from an ordinary failure — the limit signal lands on
    stderr with a non-zero exit, never on stdout (captured empirically). The
    runner therefore returns all three rather than streaming stdout alone.
    """

    stdout: str
    stderr: str
    returncode: int


# A runner takes keyword args (cmd, stdin, env, cwd) and returns a RunResult.
# Default = the real engine subprocess; tests inject a fake.
Runner = Callable[..., Awaitable[RunResult]]


# ---------------------------------------------------------------------------
# Review prompt
# ---------------------------------------------------------------------------

_REVIEW_PROMPT = """\
You are the reviewer. Review the implementation at the current git HEAD of this
worktree against the ticket's acceptance criteria and the repository's
engineering standards.

When you have finished, you MUST signal your verdict by emitting a single line
of the exact form:

SUBMIT: <json>

where <json> is a JSON object with these fields:
  - verdict: one of "pass", "fail", "defer"
  - issues: array of strings (empty on a clean pass; the blocking findings on a
    fail; the reason to defer on a defer)
  - commit_message: string (optional) — a suggested commit message on a pass
  - deferred_brief: string (optional) — a brief for the deferred follow-up

Emit exactly one SUBMIT line. Example:

SUBMIT: {"verdict": "pass", "issues": []}
"""


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


class _ReviewError(Exception):
    """Internal control-flow exception carrying a message and an exit code.

    ``reason`` is an optional stable, machine-readable tag emitted on the error
    JSON (mirroring ``close``'s ``{"error", "reason"}`` refusal shape) so a
    caller can branch on the *kind* of failure — e.g. an infra wall vs an
    unexpected error — rather than string-matching the human message (CAL-866).
    """

    def __init__(self, message: str, code: int, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.reason = reason


# ---------------------------------------------------------------------------
# SUBMIT-line scanner
# ---------------------------------------------------------------------------


class _Parsed(BaseModel):
    """Internal parse result of the SUBMIT line."""

    verdict: Verdict
    issues: list[str]
    commit_message: str | None = None
    deferred_brief: str | None = None


def scan_submit_line(stdout: str) -> _Parsed:
    """Scan codex stdout for the first valid ``SUBMIT: <json>`` line.

    A line is valid when it starts with ``SUBMIT:`` (after stripping), the JSON
    after the prefix parses to an object, and ``verdict`` is one of
    ``pass``/``fail``/``defer``.  Missing, malformed, or unknown-verdict SUBMIT
    lines yield a recorded ``fail`` carrying the :data:`NO_SUBMIT_SENTINEL`
    issue — the verb never raises on a bad reviewer, it records the failure.
    """
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("SUBMIT:"):
            continue
        json_part = stripped[len("SUBMIT:"):].strip()
        try:
            payload = json.loads(json_part)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        verdict = payload.get("verdict")
        if verdict not in _VALID_VERDICTS:
            continue
        raw_issues = payload.get("issues", [])
        issues = [str(i) for i in raw_issues] if isinstance(raw_issues, list) else []
        commit_message = payload.get("commit_message")
        deferred_brief = payload.get("deferred_brief")
        return _Parsed(
            verdict=verdict,
            issues=issues,
            commit_message=commit_message if isinstance(commit_message, str) else None,
            deferred_brief=deferred_brief if isinstance(deferred_brief, str) else None,
        )

    # No parseable SUBMIT line — record a fail with the sentinel issue.
    return _Parsed(verdict="fail", issues=[NO_SUBMIT_SENTINEL])


# ---------------------------------------------------------------------------
# Engine command builders + default runner (real subprocess) — production path.
# ---------------------------------------------------------------------------


def _build_cmd(engine: Engine) -> list[str]:
    """Build the review invocation for ``engine`` — a CLI subprocess (CAL-701).

    Both engines are headless CLIs fed the review prompt on **stdin** and scanned
    for a single ``SUBMIT: <json>`` line; neither uses the Agent SDK.  Both run
    **read-only**: the diff under review and the ticket are untrusted prompt
    content, so a read-only posture stops prompt-injection from mutating the host.

    * ``claude`` — ``claude -p`` headless in **plan** permission mode (read-only:
      it may read files / run read-only git, but carries no edit/write/bypass
      capability).
    * ``codex`` — ``codex exec`` under the ``--sandbox read-only`` sandbox
      (matching the published ``commands/build.md`` Codex-engine guidance), reading
      the prompt from ``-`` (stdin).  This replaces the earlier
      ``--dangerously-bypass-approvals-and-sandbox`` full-access invocation.
    """
    if engine == "claude":
        return ["claude", "-p", "--permission-mode", "plan"]
    return [
        "codex",
        "exec",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "-",
    ]


async def _default_runner(
    *,
    cmd: list[str],
    stdin: str,
    env: dict[str, str],
    cwd: Path | None,
) -> RunResult:
    """Run ``cmd`` as a subprocess, feed ``stdin``, capture stdout/stderr/exit.

    stderr and the exit code are captured (no longer discarded) so the Codex
    usage-limit fallback (CAL-702) can detect an exhausted tier: the limit
    signal lands on stderr with a non-zero exit, never on stdout.
    """
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=cwd,
        limit=8 * 1024 * 1024,  # engines can emit large lines (file reads, diffs)
    )
    stdout_bytes, stderr_bytes = await process.communicate(stdin.encode())
    return RunResult(
        stdout=stdout_bytes.decode(errors="replace"),
        stderr=stderr_bytes.decode(errors="replace"),
        returncode=process.returncode if process.returncode is not None else -1,
    )


# ---------------------------------------------------------------------------
# Codex usage-limit detection (CAL-702)
# ---------------------------------------------------------------------------

# The stable phrase ``codex exec`` prints to **stderr** when the tier is
# exhausted, captured empirically (CAL-702, 2026-06-15). The full real line was:
#
#   ERROR: You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/
#   explore/pro), visit https://chatgpt.com/codex/settings/usage to purchase
#   more credits or try again at Jun 18th, 2026 8:18 PM.
#
# The URLs and the reset date vary run-to-run; the lowercased phrase below is the
# invariant core. On a usage limit stdout is empty and the process exits 1.
_CODEX_USAGE_LIMIT_MARKER = "you've hit your usage limit"


def is_codex_usage_limit(stderr: str, returncode: int) -> bool:
    """True iff a Codex run failed *specifically* because the tier is exhausted.

    Matches narrowly — the stable usage-limit phrase (case-insensitive) on a
    non-zero exit — so an ordinary Codex failure does NOT trigger fallback.
    Errors are never swallowed: a real review failure stays a visible ``fail``;
    only a verified quota wall degrades gracefully to the Claude engine.
    """
    if returncode == 0:
        return False
    return _CODEX_USAGE_LIMIT_MARKER in stderr.lower()


# ---------------------------------------------------------------------------
# Review-engine sandbox/init-failure detection (CAL-866)
# ---------------------------------------------------------------------------

# The stable phrase **bwrap** prints to stderr when it cannot create a user
# namespace — e.g. ``codex exec --sandbox read-only`` running inside a
# non-privileged Docker container whose seccomp profile blocks ``CLONE_NEWUSER``.
# The real captured line was:
#
#   bwrap: No permissions to create a new namespace
#
# This is an *environment* failure: the engine never got far enough to review
# anything.  Lowercased invariant core below; the ``bwrap:`` prefix is dropped so
# the match survives a differently-prefixed wrapper, while staying specific
# enough that an ordinary failure mentioning "namespace" does not match.
_SANDBOX_INIT_MARKER = "no permissions to create a new namespace"

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

# Stable, machine-readable ``reason`` carried on the infra-failure error JSON.
SANDBOX_INIT_REASON = "sandbox_init_failure"


def is_sandbox_init_failure(stderr: str, returncode: int) -> bool:
    """True iff a review engine failed because its sandbox could not initialize.

    Mirrors :func:`is_codex_usage_limit`: a narrow stderr match (the stable
    bwrap namespace phrase, case-insensitive) on a non-zero exit.  Such a failure
    is *infra*, not a code-review verdict — the engine never reviewed the diff —
    so the verb surfaces it distinctly (a dedicated exit + ``reason``) instead of
    letting it fall through to a recorded ``fail``.  The narrowness keeps an
    ordinary review failure a visible ``fail``: a clean exit, or a failure
    without the marker, returns ``False``.
    """
    if returncode == 0:
        return False
    return _SANDBOX_INIT_MARKER in stderr.lower()


def is_sandbox_blocked_defer(verdict: str, issues: list[str], engine: Engine) -> bool:
    """True iff a Codex ``defer`` is really a sandbox-blocked non-review (CAL-924).

    :func:`is_sandbox_init_failure` catches the case where ``codex exec`` itself
    exits non-zero with the bwrap marker on **stderr**.  It MISSES the subtler
    case seen in the CAL-906 dogfood: ``codex exec`` exits **0**, but every
    read-only command it shells out to inspect the diff is killed by bwrap, so
    Codex reviews nothing yet emits a well-formed
    ``SUBMIT: {"verdict": "defer", ...}`` whose reasoning is "I could not run any
    command (bwrap: no permissions to create a new namespace)".  That reads as a
    normal, shippable ``defer`` though no review happened.

    This detector reads the OTHER channel: the same bwrap marker
    (:data:`_SANDBOX_INIT_MARKER`, case-insensitive) inside the reviewer's own
    reasoning — the parsed ``issues``.  It is deliberately narrow:

    * only a ``defer`` — a blocked review cannot ``pass`` or ``fail`` without
      inspecting the diff, so pass/fail are left untouched;
    * only the ``codex`` engine — ``claude`` runs in plan mode, never bwrap, so a
      Claude ``defer`` that merely quotes the phrase is never swallowed.

    A genuine, well-founded defer (a real out-of-scope finding, no marker) stays
    a recorded ``defer``.  (Honest limit: a codex review that genuinely inspects
    the diff yet quotes the exact bwrap phrase in its finding would be caught —
    an acceptably rare shape, weighed against a review that never ran silently
    shipping.)
    """
    if engine != "codex" or verdict != "defer":
        return False
    return _SANDBOX_INIT_MARKER in " ".join(issues).lower()


async def _invoke_engine(runner: Runner, engine: Engine, cwd: Path) -> RunResult:
    """Run one engine subprocess via ``runner``; wrap failures as ``_ReviewError``."""
    try:
        return await runner(
            cmd=_build_cmd(engine),
            stdin=_REVIEW_PROMPT,
            env=dict(os.environ),
            cwd=cwd,
        )
    except Exception as exc:  # noqa: BLE001
        raise _ReviewError(f"reviewer invocation failed: {exc}", 1) from exc


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
    json_output: bool = typer.Option(  # noqa: B008
        True,
        "--json/--no-json",
        help="Emit machine-readable JSON (default: on).",
    ),
) -> None:
    """Review the worktree HEAD; record the verdict bound to that SHA.

    The engine is a read-only CLI subprocess (``--engine claude|codex``,
    default claude) emitting the ``SUBMIT:`` contract — never the Agent SDK.
    """
    repo_root = resolve_repo_root_or_exit(repo)
    db_path = resolve_verb_db_path(db, repo_root)

    try:
        output = asyncio.run(
            _run_review(
                repo_root=repo_root,
                run_id=run_id,
                db_path=db_path,
                engine=engine,
                runner=_default_runner,
            )
        )
    except _ReviewError as exc:
        if json_output:
            payload: dict[str, str] = {"error": exc.message}
            # A stable ``reason`` lets the orchestrator branch on the failure
            # kind (e.g. an infra wall) without parsing the human message.
            if exc.reason is not None:
                payload["reason"] = exc.reason
            typer.echo(json.dumps(payload))
        else:
            typer.echo(exc.message, err=True)
        raise typer.Exit(code=exc.code) from exc

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

    # 2. Capture HEAD at review time — the load-bearing SHA binding (D2).
    try:
        reviewed_sha = await asyncio.to_thread(rev_parse_head, Path(worktree_path))
    except Exception as exc:  # noqa: BLE001
        raise _ReviewError(f"failed to read HEAD for worktree {worktree_path}: {exc}", 1) from exc

    # 3. Run the reviewer. On an explicit ``--engine codex`` whose tier is
    #    exhausted, fall back ONCE to the Claude engine (CAL-702): a depleted
    #    Codex tier degrades the gate to a false ``fail`` exactly when relied
    #    upon, so the verb substitutes Claude and records the substitution.
    #    Single hop only — Claude does not fall back to anything.
    engine_used: Engine = engine
    fallback_from: Engine | None = None

    result = await _invoke_engine(runner, engine, Path(worktree_path))

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
        result = await _invoke_engine(runner, "claude", Path(worktree_path))

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
    event_data: dict[str, Any] = {
        "run_id": resolved_run_id,
        "reviewed_sha": reviewed_sha,
        "verdict": parsed.verdict,
        "issues": parsed.issues,
        "engine": engine_used,
        "convergence_check_required": needs_convergence_check,
        "created_at": created_at,
    }
    # Record the fallback in the ledger — never silent (CAL-702 AC-4).  Present
    # only when a Codex usage-limit forced the hop to Claude.
    if fallback_from is not None:
        event_data["fallback_from"] = fallback_from
    if parsed.commit_message is not None:
        event_data["commit_message"] = parsed.commit_message
    if parsed.deferred_brief is not None:
        event_data["deferred_brief"] = parsed.deferred_brief

    emitter = EventEmitter(db_path)
    try:
        await emitter.emit(
            run_id=resolved_run_id,
            event_type="review",
            data=event_data,
        )
    except Exception as exc:  # noqa: BLE001
        raise _ReviewError(f"failed to record review event: {exc}", 1) from exc

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
