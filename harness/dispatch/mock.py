"""In-process MockAgent for engine/executor tests — see SPEC §4.7.

Provides a deterministic stand-in for a real agent harness. Tests can:

- queue per-call return values via `set_next(...)`,
- inspect every recorded invocation via `mock.calls`,
- inject errors via the `error=` constructor argument.

A bare `MockAgent()` (no constructor arguments) returns a successful
``NodeResult`` whose contract is an empty ``BaseModel`` and whose attestation
is ``status="complete"`` — the smallest valid result the engine can route.
This lets executor tests construct a usable agent in a single line.

Pure Python — no SDK imports. The Claude / codex / opencode adapters live in
sibling modules and land in later issues.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel

from harness.dispatch.base import AgentCapability
from harness.nodes.base import Attestation, NodeResult


class _EmptyContract(BaseModel):
    """Concrete zero-field contract used by the synthetic default result."""


@dataclass(frozen=True)
class RecordedCall:
    """A single captured `MockAgent.execute(...)` invocation."""

    prompt: str
    contract: type[BaseModel]
    submit_tool_schema: dict[str, Any]
    allowed_tools: list[str]
    cwd: Path | None
    timeout_s: int
    stall_timeout_s: int
    max_turns: int | None = None
    session_key: str | None = None


def _empty_default_result() -> NodeResult[BaseModel]:
    """The fallback NodeResult returned when no `default_result` was supplied.

    Uses an empty `BaseModel` instance for the contract slot — no fields, valid
    by Pydantic — paired with a ``complete`` attestation. Enough for any caller
    that only needs *some* well-formed result to flow through the engine.
    """
    return NodeResult[BaseModel](
        contract=_EmptyContract(),
        attestation=Attestation(status="complete"),
    )


@dataclass
class MockAgent:
    """A deterministic, recording stand-in for the `Agent` protocol.

    Constructor arguments:

    - ``default_result``: returned when no per-call value is queued. If left as
      ``None``, a synthetic empty-but-complete ``NodeResult`` is used.
    - ``error``: if set, every ``execute()`` call raises this exception *after*
      recording the invocation in ``calls``. Useful for verifying the executor
      passes the right arguments even on failure paths.
    """

    capability: ClassVar[AgentCapability] = AgentCapability(
        supports_submit_tool=True,
        supports_cwd=True,
        supports_max_turns=True,
        supports_tool_allowlist=True,
    )

    default_result: NodeResult[BaseModel] | None = None
    error: BaseException | None = None
    calls: list[RecordedCall] = field(default_factory=list)
    _queue: deque[NodeResult[BaseModel]] = field(default_factory=deque)

    def set_next(self, result: NodeResult[BaseModel]) -> None:
        """Queue ``result`` as the return value for the next ``execute()`` call.

        Multiple calls queue in FIFO order. Once the queue is exhausted,
        subsequent calls fall back to ``default_result`` (or the synthetic
        default if none was supplied at construction time).
        """
        self._queue.append(result)

    def reset(self) -> None:
        """No-op for the in-process MockAgent.

        SPEC §10 fresh_context: the loop evaluator calls ``reset()``
        between iterations. MockAgent doesn't retain SDK / conversation
        state across calls, so there's nothing to clear.
        """

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
        session_key: str | None = None,
    ) -> NodeResult[BaseModel]:
        self.calls.append(
            RecordedCall(
                prompt=prompt,
                contract=contract,
                submit_tool_schema=submit_tool_schema,
                allowed_tools=list(allowed_tools),
                cwd=cwd,
                timeout_s=timeout_s,
                stall_timeout_s=stall_timeout_s,
                max_turns=max_turns,
                session_key=session_key,
            )
        )

        if self.error is not None:
            raise self.error

        if self._queue:
            return self._queue.popleft()

        if self.default_result is not None:
            return self.default_result

        return _empty_default_result()
