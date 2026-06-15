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
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal, NamedTuple

import typer
from pydantic import BaseModel

from harness._time import iso_z
from harness.cli._git import rev_parse_head
from harness.cli._repo import resolve_repo_root_or_exit, resolve_verb_db_path
from harness.cli._runs import resolve_open_run
from harness.events.emitter import EventEmitter

__all__ = [
    "review_command",
    "ReviewOutput",
    "scan_submit_line",
    "Engine",
    "RunResult",
    "is_codex_usage_limit",
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
    """

    verdict: Verdict
    issues: list[str]
    reviewed_sha: str
    run_id: str
    engine: Engine


class _ReviewError(Exception):
    """Internal control-flow exception carrying a message and an exit code."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


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
            typer.echo(json.dumps({"error": exc.message}))
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
    if engine == "codex" and is_codex_usage_limit(result.stderr, result.returncode):
        fallback_from = "codex"
        engine_used = "claude"
        result = await _invoke_engine(runner, "claude", Path(worktree_path))

    # 4. Parse the SUBMIT line (bad/missing → fail + sentinel).  The engine's
    #    full stdout/stderr stays local to the verb — only the verdict escapes.
    parsed = scan_submit_line(result.stdout)

    # 5. Append the review event — the full audited record (includes optional
    #    commit_message / deferred_brief which the printed verdict omits).
    created_at = iso_z()
    event_data: dict[str, Any] = {
        "run_id": resolved_run_id,
        "reviewed_sha": reviewed_sha,
        "verdict": parsed.verdict,
        "issues": parsed.issues,
        "engine": engine_used,
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
    )
