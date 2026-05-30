"""Agent protocol — see SPEC §4.7.

The `Agent` protocol wraps an *agent harness* (Claude Code's loop, codex, or
opencode) — not a raw model API. Implementations live alongside this module
(`claude.py`, `ollama.py`, `pi.py` placeholders) and adapt the harness-specific
shape to this single dialect-agnostic surface.

The protocol is intentionally minimal: a single `execute` coroutine that takes
a prompt + the contract metadata the executor needs to enforce structured
output, and returns a `NodeResult`. Anything else (events, streaming, sandbox
semantics) is the executor's concern, not the agent's.

A second, optional protocol :class:`ResettableAgent` exposes ``reset()`` — the
loop block evaluator (H-021) invokes it between iterations of a
``fresh_context: true`` loop to clear conversational / session state. Adapters
that hold no state across calls don't need to implement it; the loop uses
:func:`isinstance` to probe at runtime and silently no-ops on agents that don't
expose the method. Keeping ``reset()`` off the core ``Agent`` protocol means
existing structural-typing tests (a bare class with only ``execute`` still
counts as an Agent) keep passing.

Marked `runtime_checkable` so callers / tests can `isinstance(x, Agent)` to
verify structural conformance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from harness.nodes.base import NodeResult


@runtime_checkable
class Agent(Protocol):
    """Dialect-agnostic agent harness wrapper. SPEC §4.7."""

    async def execute(
        self,
        prompt: str,
        contract: type[BaseModel],
        submit_tool_schema: dict[str, Any],
        *,
        allowed_tools: list[str],
        cwd: Path | None,
        timeout_s: int = 600,
        stall_timeout_s: int = 300,
        max_turns: int | None = None,
    ) -> NodeResult[BaseModel]: ...


@runtime_checkable
class ResettableAgent(Protocol):
    """Optional protocol: an :class:`Agent` that can drop session state.

    The loop evaluator (:mod:`harness.engine.loop`) calls ``reset()``
    between iterations of a ``fresh_context: true`` loop block (SPEC §10).
    Adapters that don't carry conversational state across calls don't
    need to implement this — the loop probes with :func:`isinstance` and
    is a no-op when the agent doesn't conform.
    """

    def reset(self) -> None: ...
