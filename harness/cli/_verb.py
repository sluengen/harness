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
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, TypeVar

import typer

__all__ = ["VerbError", "run_verb"]

_T = TypeVar("_T")


class VerbError(Exception):
    """Control-flow exception carrying a message, exit code, and optional reason.

    Raised inside a verb's async orchestration and translated to a Typer
    ``Exit`` by :func:`run_verb`. ``reason`` is an optional stable tag emitted
    on the error JSON (see the module docstring's recorded decision).
    """

    def __init__(self, message: str, code: int, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.reason = reason


def run_verb(work: Callable[[], _T], *, json_output: bool) -> _T:
    """Run ``work``; on :class:`VerbError` emit the uniform error output + exit.

    Returns ``work()``'s result on success. On a raised ``VerbError`` it prints
    ``{"error": ...}`` (plus ``"reason"`` only when set) to stdout under
    ``json_output``, else the human message to stderr, then raises
    ``typer.Exit(code)``. Any non-``VerbError`` propagates unchanged — so a
    ``typer.BadParameter`` still exits 2 through Typer's own handler.
    """
    try:
        return work()
    except VerbError as exc:
        if json_output:
            payload: dict[str, Any] = {"error": exc.message}
            if exc.reason is not None:
                payload["reason"] = exc.reason
            typer.echo(json.dumps(payload))
        else:
            typer.echo(exc.message, err=True)
        raise typer.Exit(code=exc.code) from exc
