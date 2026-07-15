"""The repo's verify gate, as the harness runs it — CAL-1082.

The close gate enforced three things — a run exists, the worktree is clean, and a
``verdict='pass'`` is bound to HEAD — and **none of them was evidence that a test
ever executed**. The only instruction to run the gate lived in prose addressed to
a model (``commands/harness.md``: "Run the repo's verify gate locally as you
go"), enforced by nothing. So a ``pass`` from a reviewer that merely *read* the
diff was byte-identical in the ledger to one backed by a green test suite —
against this repo's own iron law ("no completion claim without fresh evidence")
and against ``CONTEXT.md``'s claim that the harness owns "the durable record
**and the gate**".

This module is the missing half: it reads the repo's configured gate command and
runs it. ``harness review`` calls it before invoking any engine, records the
result on the ``review`` event, and refuses a red tree outright — so the ledger's
``pass`` now *means* something a reader can check.

It deliberately mirrors :mod:`harness.loop_budget`, the standing precedent for
this shape: config read out of ``CONTEXT.md`` in its own module, with a
documented fallback when the key is absent, called from a verb rather than
inlined into it. ``review.py`` is on the architecture watchlist — it already
carries verb orchestration, the prompt, the SUBMIT parser, the per-engine
builders, the failure detectors, and the fallback — so the gate lands here, as a
seam by construction, and ``review.py`` grows only a call site.

**The gate is run, not sandboxed further.** The container that runs it is
already the unprivileged one that reviews untrusted diffs (ADR 0002); running a
repo's own test suite executes repo-controlled code by definition, so the gate
grants no privilege the review did not already have. Loosening the container to
accommodate an exotic toolchain was weighed and rejected there; a repo whose
toolchain the container lacks gets an honest ``gate_failed`` instead of a
diff-only ``pass`` (CAL-1084 closes that gap).
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import NamedTuple

__all__ = [
    "DEFAULT_GATE_TIMEOUT_SECONDS",
    "GATE_NOT_CONFIGURED_REASON",
    "GATE_OUTPUT_TAIL_LIMIT",
    "GateResult",
    "load_gate_command",
    "run_gate",
]

#: Recorded as the ``review`` event's ``gate_reason`` when the repo configures no
#: ``verify:`` command. The harness cannot gate what a repo does not define; the
#: ledger says so plainly rather than implying a gate ran. ``close`` reads this
#: value to tell an honest "no gate configured" from missing evidence.
GATE_NOT_CONFIGURED_REASON = "not_configured"

#: How much of a failed gate's output rides on the refusal JSON. The tail — not
#: the head — because the diagnostic lines (the failing assertion, the summary)
#: come last. A deliberate, bounded exception to the verb's context-economy rule:
#: this is the *reason for the refusal*, not engine reasoning, and without it the
#: agent must re-run the whole gate just to learn what broke.
GATE_OUTPUT_TAIL_LIMIT = 2048

#: The per-gate subprocess ceiling. A hung gate must not hang the verb forever —
#: the same gap ``engine_timeout_seconds`` closes for the review engine
#: (CAL-1004). Fixed, not a ``CONTEXT.md`` key: a repo needing a different bound
#: is its own change (CAL-1082 "out of scope"). 15 minutes clears a full
#: lint → typecheck → test suite with room to spare.
DEFAULT_GATE_TIMEOUT_SECONDS = 900


class GateResult(NamedTuple):
    """The outcome of one gate run.

    ``exit_code`` is ``None`` when the gate started but never reported one — it
    was killed by the timeout. The caller treats any non-zero-or-``None`` code as
    a failure, so a killed gate refuses rather than passing silently.
    """

    ran: bool
    exit_code: int | None
    output_tail: str
    duration_ms: int


# ---------------------------------------------------------------------------
# Config — read the gate command from CONTEXT.md (not hardcoded)
# ---------------------------------------------------------------------------

# ``verify:`` is a distinctly-named string key in CONTEXT.md, optionally quoted
# and optionally trailed by a comment. A direct per-key match is robust here and
# avoids pulling in a YAML parser for one string — the same trade
# ``loop_budget._read_int_key`` makes for its integers. Two alternatives: the
# quoted form (group 1) takes the value verbatim, so a ``#`` inside it survives;
# the bare form (group 2) stops at a trailing comment.
_VERIFY_KEY_PATTERN = (
    r'^\s*verify:\s*"([^"]+)"\s*(?:#.*)?$'
    r'|^\s*verify:\s*([^"#\s][^#]*?)\s*(?:#.*)?$'
)


def load_gate_command(repo_root: Path) -> str | None:
    """The repo's ``verify:`` command from ``repo_root/CONTEXT.md``, else ``None``.

    ``None`` means *this repo defines no gate* — both when ``CONTEXT.md`` is
    absent entirely and when it configures no ``verify:`` key. The caller records
    that absence as :data:`GATE_NOT_CONFIGURED_REASON` rather than inventing a
    default command: guessing a gate would be worse than admitting there is none.
    """
    context = repo_root / "CONTEXT.md"
    try:
        text = context.read_text()
    except OSError:
        return None
    match = re.search(_VERIFY_KEY_PATTERN, text, re.MULTILINE)
    if match is None:
        return None
    command = match.group(1) or match.group(2)
    return command.strip() or None


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def run_gate(
    worktree: Path, command: str, timeout_s: int = DEFAULT_GATE_TIMEOUT_SECONDS
) -> GateResult:
    """Run ``command`` in ``worktree``; capture its exit code and output tail.

    Run through a shell because ``CONTEXT.md``'s ``verify:`` **is** a shell
    command line — the retired workflow engine's ``verify`` node ran it the same
    way, and real values (``bash scripts/verify.sh``, ``npm run verify && npm
    test``) need shell semantics. This grants nothing: the command is repo-owned
    config at the same trust level as the test suite it invokes, and running that
    suite already executes repo-controlled code.

    stdout and stderr are merged — a failing gate scatters its diagnosis across
    both, and the tail is only useful if it is the *whole* tail.
    """
    started = time.monotonic()
    try:
        completed = subprocess.run(  # noqa: S602 — repo-owned config; see docstring
            command,
            shell=True,
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        return GateResult(
            ran=True,
            exit_code=None,
            output_tail=_tail(
                f"{_decode(exc.stdout)}{_decode(exc.stderr)}\n"
                f"[gate killed after {timeout_s}s — exceeded the gate timeout]"
            ),
            duration_ms=_elapsed_ms(started),
        )
    return GateResult(
        ran=True,
        exit_code=completed.returncode,
        output_tail=_tail(f"{completed.stdout}{completed.stderr}"),
        duration_ms=_elapsed_ms(started),
    )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _decode(stream: str | bytes | None) -> str:
    """A ``TimeoutExpired``'s partial output, which may be bytes or absent."""
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode(errors="replace")
    return stream


def _tail(output: str) -> str:
    """The last :data:`GATE_OUTPUT_TAIL_LIMIT` characters of ``output``."""
    return output[-GATE_OUTPUT_TAIL_LIMIT:]
