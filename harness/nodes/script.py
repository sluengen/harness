"""Script node — subprocess wrapper, output capture, contract validation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from harness.nodes.base import NodeResult
from harness.state.schema import BaseState
from harness.workflow.schema import ScriptStep

__all__ = [
    "ScriptNode",
    "ScriptNodeError",
    "ScriptOutput",
]


class ScriptNodeError(RuntimeError):  # noqa: N818 — spec vocabulary, not PEP-8 N818
    """Raised when a script subprocess fails, times out, or is misconfigured."""


class ScriptOutput(BaseModel):
    """Stub — see real implementation below (H-015 GREEN)."""

    model_config = ConfigDict(extra="forbid")

    stdout: str
    stderr: str
    exit_code: int


class ScriptNode:
    """Stub — see real implementation below (H-015 GREEN)."""

    type: Literal["script"] = "script"

    def __init__(
        self,
        *,
        max_output_bytes: int = 1024 * 1024,
        timeout_s: float = 300.0,
    ) -> None:
        self._max_output_bytes = max_output_bytes
        self._timeout_s = timeout_s

    async def execute(
        self,
        *,
        step: ScriptStep,
        state: BaseState,
        inputs: dict[str, Any] | None = None,
    ) -> NodeResult[ScriptOutput]:
        raise NotImplementedError("H-015 GREEN")
