"""``harness review`` — codex review of HEAD, verdict bound to the reviewed SHA.

The review verb makes review a callable, audited step.  It runs the configured
reviewer (codex) against the worktree's current HEAD, parses the structured
verdict, and appends a ``review`` event to the ledger that records the exact git
SHA reviewed.  Binding the verdict to HEAD is the load-bearing correctness
detail (proposal ``harness-as-tool.md`` decision **D2**): the future ``close``
gate refuses to merge unless the ledger holds a ``verdict='pass'`` whose
``reviewed_sha`` equals HEAD, so a stale pass cannot be reused against a changed
tree.  If ``review`` does not record the SHA it actually reviewed, the gate is
theatre.

Flow (one ``asyncio.run`` event loop for all I/O):

1. Resolve "the current run" — the ``status='open'`` runs row whose
   ``worktree_path`` matches the resolved ``--repo`` (or ``--run-id`` override).
2. Capture ``git rev-parse HEAD`` in that worktree as ``reviewed_sha``.
3. Run ``codex exec --dangerously-bypass-approvals-and-sandbox --ephemeral -``
   with the review prompt on stdin and scan stdout for the first ``SUBMIT:``
   JSON line.
4. Parse the verdict ('pass'|'fail'|'defer') + issues.  No valid SUBMIT line →
   ``verdict='fail'`` with the sentinel issue
   "reviewer emitted no valid SUBMIT line".
5. Append a ``review`` event carrying ``run_id``, ``reviewed_sha``, ``verdict``,
   ``issues``, optional ``commit_message`` / ``deferred_brief``, ``created_at``.
6. Print only the bounded verdict (``verdict`` + ``issues`` + ``reviewed_sha`` +
   ``run_id``).  Codex's full stdout / reasoning stays inside the verb and never
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
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, Literal

import typer
from pydantic import BaseModel

from harness._time import iso_z
from harness.cli._git import rev_parse_head
from harness.cli._repo import resolve_repo_root_or_exit
from harness.cli._runs import resolve_open_run
from harness.events.emitter import EventEmitter
from harness.state import store

__all__ = ["review_command", "ReviewOutput", "scan_submit_line"]

# Sentinel issue recorded when codex emits no parseable SUBMIT line.
NO_SUBMIT_SENTINEL = "reviewer emitted no valid SUBMIT line"

# The verdicts the SUBMIT line may carry.  Anything else is treated as garbled.
_VALID_VERDICTS: frozenset[str] = frozenset({"pass", "fail", "defer"})

Verdict = Literal["pass", "fail", "defer"]

# A runner takes keyword args (cmd, stdin, env, cwd) and yields stdout text
# lines.  Default = the real codex subprocess; tests inject a fake.
Runner = Callable[..., AsyncIterator[str]]


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
# Default codex runner (real subprocess) — the production path.
# ---------------------------------------------------------------------------


def _build_cmd() -> list[str]:
    """Build the plain ``codex exec`` review invocation (no ``--json``).

    Per the ticket the review verb runs plain ``codex exec ... -`` and scans
    stdout *text* for the SUBMIT line — it does not need the NDJSON adapter.
    """
    return [
        "codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--ephemeral",
        "-",
    ]


async def _default_runner(
    *,
    cmd: list[str],
    stdin: str,
    env: dict[str, str],
    cwd: Path | None,
) -> AsyncIterator[str]:
    """Run ``cmd`` as a subprocess, feed ``stdin``, yield stdout lines."""
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=env,
        cwd=cwd,
        limit=8 * 1024 * 1024,  # codex can emit large lines (file reads, diffs)
    )
    if process.stdin is None:  # pragma: no cover
        raise RuntimeError("subprocess stdin pipe was not created")
    if process.stdout is None:  # pragma: no cover
        raise RuntimeError("subprocess stdout pipe was not created")
    process.stdin.write(stdin.encode())
    await process.stdin.drain()
    process.stdin.close()
    async for line in process.stdout:
        yield line.decode(errors="replace")
    await process.wait()


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
    json_output: bool = typer.Option(  # noqa: B008
        True,
        "--json/--no-json",
        help="Emit machine-readable JSON (default: on).",
    ),
) -> None:
    """Review the worktree HEAD with codex; record the verdict bound to that SHA."""
    repo_root = resolve_repo_root_or_exit(repo)
    db_path = db if db is not None else repo_root / store.DEFAULT_DB_PATH

    try:
        output = asyncio.run(
            _run_review(
                repo_root=repo_root,
                run_id=run_id,
                db_path=db_path,
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

    # 3. Run the reviewer and accumulate stdout (kept local to the verb).
    cmd = _build_cmd()
    stdout_buf: list[str] = []
    try:
        async for line in runner(
            cmd=cmd,
            stdin=_REVIEW_PROMPT,
            env=dict(os.environ),
            cwd=Path(worktree_path),
        ):
            stdout_buf.append(line)
    except Exception as exc:  # noqa: BLE001
        raise _ReviewError(f"reviewer invocation failed: {exc}", 1) from exc

    # 4. Parse the SUBMIT line (bad/missing → fail + sentinel).
    parsed = scan_submit_line("".join(stdout_buf))

    # 5. Append the review event — the full audited record (includes optional
    #    commit_message / deferred_brief which the printed verdict omits).
    created_at = iso_z()
    event_data: dict[str, Any] = {
        "run_id": resolved_run_id,
        "reviewed_sha": reviewed_sha,
        "verdict": parsed.verdict,
        "issues": parsed.issues,
        "created_at": created_at,
    }
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

    # 6. Return ONLY the bounded verdict — codex stdout stays inside the verb.
    return ReviewOutput(
        verdict=parsed.verdict,
        issues=parsed.issues,
        reviewed_sha=reviewed_sha,
        run_id=resolved_run_id,
    )
