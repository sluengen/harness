"""Shared plumbing for the harness verb commands (CAL-1013).

Every verb — ``start`` / ``review`` / ``close`` / ``checkpoint`` / ``reclaim``,
plus the ``cancel`` abandon path — raises one control-flow exception,
:class:`VerbError`, carrying a human ``message``, an exit ``code``, and an
optional machine-readable ``reason``. :func:`run_verb` is the single epilogue
that translates a raised ``VerbError`` into the uniform error output plus a
Typer exit, so the error-JSON shape can no longer drift between verbs.

Recorded decision — the ``reason`` field
----------------------------------------
``reason`` is a stable, machine-readable tag a caller can branch on (e.g. an
infra wall vs. an unexpected error, or ``close``'s gate-refusal kind) instead of
string-matching the human ``message``. It is **optional and emitted only when
set**: a verb that raises without a ``reason`` keeps the historical
``{"error": ...}`` JSON byte-for-byte, while ``review`` and ``close`` — which do
set one — emit ``{"error": ..., "reason": ...}``. Absent, never ``null``. This
is the uniform shape; the ``--json`` *default* stays a per-verb choice
(orchestrator-consumed verbs default it on; the human-facing ``reclaim`` /
``cancel`` default it off) and is deliberately not unified here.

Recorded decision — an unexpected exception still owes a payload (#370)
-----------------------------------------------------------------------
``VerbError`` is the *expected* failure. Everything else used to propagate, and
under ``--json`` that meant a verb could exit non-zero having written **nothing**
to stdout — the one stream the orchestrating loop parses for a reason. Measured
on the CI runner: ``start`` died on ``PermissionError: [Errno 13] Permission
denied: '/workspace/.harness'`` from inside ``store.init_db``, and the log showed
``exited 1: b''``. The verb knew what went wrong and said so, on a stream its
machine reader does not read; two people misdiagnosed the failure over two days
because of it (#369).

So an unexpected exception under ``json_output`` now emits the same uniform shape
with ``reason`` :data:`UNEXPECTED_ERROR_REASON` and exit 1, **and still prints its
traceback to stderr** — the human reader loses nothing to the machine one gaining
something. Three exceptions are re-raised untouched because Typer renders them
itself, with its own exit codes: ``Exit`` and ``Abort`` (control flow, both
``RuntimeError`` subclasses a bare ``except Exception`` would swallow) and
``BadParameter`` (argument errors, exit 2). Stated residual: a verb body raising
some *other* ``click`` exception directly would be reported as unexpected rather
than by Typer. No verb in this package does — ``BadParameter`` is the one Typer
exposes and the one they use — and covering the rest would mean importing
``click`` to name a base class no caller here reaches.

Recorded decision — the ``extra`` field
---------------------------------------
Some refusals carry *data* the caller needs to act, not just a tag: a red verify
gate carries the gate's bounded output tail, so the agent can fix what broke
without re-running the gate (CAL-1082). That data is machine-readable, so it
belongs in its own key rather than concatenated into the human ``message`` —
and composing the error JSON is exactly this epilogue's job. ``extra`` is
**optional**, merged under the reserved ``error`` / ``reason`` keys (which it
cannot override), so every verb that does not set it keeps its JSON unchanged.
"""

from __future__ import annotations

import json
import traceback
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

import typer

__all__ = ["UNEXPECTED_ERROR_REASON", "VerbError", "run_verb"]

_T = TypeVar("_T")

#: The ``reason`` tag on the payload an unexpected exception produces. Its own
#: constant because a caller branching on it must be able to name it rather than
#: match a string, exactly as the verbs' own refusal reasons are named.
UNEXPECTED_ERROR_REASON = "unexpected_error"


class VerbError(Exception):
    """Control-flow exception carrying a message, exit code, and optional reason.

    Raised inside a verb's async orchestration and translated to a Typer
    ``Exit`` by :func:`run_verb`. ``reason`` is an optional stable tag emitted
    on the error JSON, and ``extra`` optional structured data to emit alongside
    it (see the module docstring's recorded decisions).
    """

    def __init__(
        self,
        message: str,
        code: int,
        *,
        reason: str | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.reason = reason
        self.extra = extra


def run_verb(work: Callable[[], _T], *, json_output: bool) -> _T:
    """Run ``work``; on :class:`VerbError` emit the uniform error output + exit.

    Returns ``work()``'s result on success. On a raised ``VerbError`` it prints
    ``{"error": ...}`` (plus ``"reason"`` and any ``extra`` keys, only when set)
    to stdout under ``json_output``, else the human message to stderr, then
    raises ``typer.Exit(code)``.

    An **unexpected** exception under ``json_output`` is reported the same way,
    tagged :data:`UNEXPECTED_ERROR_REASON`, and its traceback still printed to
    stderr — see the recorded decision below. Without ``json_output`` it
    propagates unchanged, as does anything Typer renders itself, so a
    ``typer.BadParameter`` still exits 2 through Typer's own handler.
    """
    try:
        return work()
    except (typer.Exit, typer.Abort, typer.BadParameter):
        # Control flow and argument errors, both of which Typer already reports
        # correctly and with their own exit codes. `Exit` and `Abort` subclass
        # `RuntimeError`, so a bare `except Exception` below would swallow them
        # and rewrite a verb's deliberate exit code to 1.
        raise
    except VerbError as exc:
        if json_output:
            payload: dict[str, Any] = {"error": exc.message}
            if exc.reason is not None:
                payload["reason"] = exc.reason
            if exc.extra is not None:
                # ``error`` / ``reason`` are reserved: a stray ``extra`` key can
                # add to the contract but never redefine it.
                payload.update(
                    {k: v for k, v in exc.extra.items() if k not in ("error", "reason")}
                )
            typer.echo(json.dumps(payload))
        else:
            typer.echo(exc.message, err=True)
        raise typer.Exit(code=exc.code) from exc
    except Exception as exc:
        if not json_output:
            # Nothing consumes stdout on the human path, and Typer's own
            # renderer shows the frames better than a hand-printed traceback.
            # The defect is the machine contract, so that is the only path that
            # changes.
            raise
        # The traceback is not traded away for the payload — the two readers
        # want different things, and emitting one by discarding the other is
        # this failure pointed the other way.
        traceback.print_exc()
        typer.echo(
            json.dumps(
                {
                    "error": f"{type(exc).__name__}: {exc}",
                    "reason": UNEXPECTED_ERROR_REASON,
                }
            )
        )
        raise typer.Exit(code=1) from exc
