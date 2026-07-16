"""The review engine protocol — pure engine-bug knowledge, no verb orchestration.

The ``review`` verb talks to a read-only CLI review engine (``claude`` or
``codex``) over one narrow contract: feed it :data:`_REVIEW_PROMPT` on stdin and
scan its stdout for a single ``SUBMIT: <json>`` line. Around that contract sits a
layer of *engine quirks* — knowledge of how a specific engine misbehaves — that
is empirically derived, pure, and separately tested, and that has nothing to do
with the verb's run resolution, ledger writes, spend breakers, gate evidence, or
tracker transitions.

This module is that layer, split out of ``harness.cli.review`` (CAL-1107) so the
engine-bug knowledge lives apart from the verb orchestration:

* the review **prompt** and the **SUBMIT** contract (:func:`scan_submit_line`);
* the **engine identity** (:data:`Engine`) and per-engine **command builder**
  (:func:`_build_cmd`);
* the three empirically-derived **failure detectors** — a Codex usage-limit that
  should fall back to Claude (:func:`is_codex_usage_limit`, CAL-702), and the two
  sandbox walls that mean the engine reviewed *nothing* and must surface as infra
  rather than a verdict (:func:`is_sandbox_init_failure`, CAL-866, and its exit-0
  masquerading-defer sibling :func:`is_sandbox_blocked_defer`, CAL-924).

Everything here is a pure function or a data/type definition: no I/O, no ledger,
no Typer. The verb (:mod:`harness.cli.review`) imports and re-exports these names,
so an engine quirk is a change *here*, not in the verb.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Literal, NamedTuple

from pydantic import BaseModel

__all__ = [
    "DEFAULT_ENGINE",
    "Engine",
    "RunResult",
    "Runner",
    "Verdict",
    "NO_SUBMIT_SENTINEL",
    "scan_submit_line",
    "is_codex_usage_limit",
    "is_sandbox_init_failure",
    "is_sandbox_blocked_defer",
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


# A runner takes keyword args (cmd, stdin, env, cwd, timeout) and returns a
# RunResult. Default = the real engine subprocess; tests inject a fake. The
# ``timeout`` (seconds, or None) is the per-subprocess ceiling (CAL-1004); a
# fake may accept and ignore it.
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
# Engine command builder — the per-engine read-only CLI invocation.
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
