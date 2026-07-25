"""The bounded engine subprocess — the one driver both engine verbs run on.

Two verbs shell out to a read-only CLI engine over a ``SUBMIT:`` contract:
``review`` (the diff, ``harness.cli.review_protocol``) and ``design`` (the
ticket, ``harness.cli.design_protocol``, #211). Both need the *identical*
mechanics — spawn the process, feed the prompt on stdin, capture stdout/stderr
and the exit code, and on expiry of the configured ceiling kill **and reap** the
child so no zombie survives (CAL-1004).

They differ in exactly one thing: which :class:`~harness.cli._verb.VerbError`
a timeout becomes. ``review`` reports its own exit code and ``reason``; ``design``
reports its own and additionally *records* the failed attempt in the ledger
(ADR 0007's degrade-and-record). So the driver raises a **neutral**
:class:`EngineTimeoutError` and each verb translates it — the verb-specific part
stays with the verb, the mechanics live here once.

This module owns :class:`RunResult` and :data:`Runner` for the same reason: they
describe the driver's contract, and both protocol layers depend on them.
:mod:`harness.cli.review_protocol` re-exports them so every existing
``review_protocol``/``review`` import keeps resolving.

Extracted from ``review``'s ``_default_runner`` in #211 as that change's
architecture-watchlist outcome (a small behaviour-preserving seam extraction):
copying a driver whose only difference is its exception type is the duplication
``code-quality`` Part A forbids. ``review``'s pre-existing timeout tests — which
spawn a genuinely hanging child — are the behaviour-preservation proof.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import NamedTuple

__all__ = [
    "EngineTimeoutError",
    "RunResult",
    "Runner",
    "run_engine_subprocess",
]

# Engines can emit very large single lines (a file read, a whole diff), well past
# asyncio's 64 KiB stream default — which would abort the read with a
# LimitOverrunError mid-review.
_STREAM_LIMIT = 8 * 1024 * 1024


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


class EngineTimeoutError(Exception):
    """The engine subprocess hit its ceiling and was killed.

    Deliberately **neutral** — it names the mechanical fact and nothing about
    what the calling verb does with it. Each verb catches this and raises its own
    ``VerbError`` with its own exit code, ``reason``, and remediation text, so the
    driver stays shared without either verb's contract leaking into the other's.
    """

    def __init__(self, timeout: float) -> None:
        super().__init__(f"engine subprocess exceeded its {timeout:.0f}s timeout")
        self.timeout = timeout


async def run_engine_subprocess(
    *,
    cmd: list[str],
    stdin: str,
    env: dict[str, str],
    cwd: Path | None,
    timeout: float | None = None,
) -> RunResult:
    """Run ``cmd`` as a subprocess, feed ``stdin``, capture stdout/stderr/exit.

    ``timeout`` (seconds) caps the subprocess. On expiry the child is killed
    **and reaped** — ``asyncio.wait_for`` cancels ``communicate()`` but leaves the
    process alive, so skipping the reap would orphan it — and
    :class:`EngineTimeoutError` is raised. ``None`` runs unbounded, for a caller
    that opts out.
    """
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=cwd,
        limit=_STREAM_LIMIT,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(stdin.encode()), timeout=timeout
        )
    except TimeoutError:
        # asyncio.wait_for raises the builtin TimeoutError (3.11+) after
        # cancelling communicate(); the child is still alive. Kill and reap it so
        # no zombie/orphan survives, then surface the neutral timeout.
        process.kill()
        await process.wait()
        assert timeout is not None  # only a set ceiling can expire
        raise EngineTimeoutError(timeout) from None
    return RunResult(
        stdout=stdout_bytes.decode(errors="replace"),
        stderr=stderr_bytes.decode(errors="replace"),
        returncode=process.returncode if process.returncode is not None else -1,
    )
