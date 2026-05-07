"""Agent protocol — see SPEC §4.7.

The `Agent` protocol wraps an *agent harness* (Claude Code's loop, codex, or
opencode) — not a raw model API. Implementations live alongside this module
(`claude.py`, `ollama.py`, `pi.py` placeholders) and adapt the harness-specific
shape to this single dialect-agnostic surface.

The protocol is intentionally minimal: a single `execute` coroutine that takes
a prompt + the contract metadata the executor needs to enforce structured
output, and returns a `NodeResult`. Anything else (events, streaming, sandbox
semantics) is the executor's concern, not the agent's.

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
    ) -> NodeResult[BaseModel]: ...
