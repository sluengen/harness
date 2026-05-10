"""Contract → tool-schema compilation — SPEC §4.4, §5 ("two artefacts").

A workflow contract compiles to two artefacts at workflow load time:

1. A Pydantic model — final validation of the agent's submitted payload.
   Lives in :mod:`harness.workflow.contract` (H-006).
2. A tool schema in the agent harness's native dialect, called
   ``submit_<node_id>``, with one parameter per contract field. Lives here.

Both artefacts come from the same source so they cannot drift. The author
writes one schema and gets both behaviours: native tool-call structured
output for the agent, Pydantic validation for the engine.

The ``input_schema`` is the Pydantic model's :meth:`model_json_schema`
output verbatim — the JSON Schema dialect Pydantic emits matches what the
Anthropic tool-definition dialect (and codex / opencode) accept. Single
source of truth means no translation layer that could subtly diverge.

The dict shape — ``{"name": ..., "description": ..., "input_schema": ...}``
— is the dialect :class:`harness.dispatch.claude.ClaudeAgent` reads
``["name"]`` from. Other adapters consume the same dict.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

__all__ = ["compile_to_tool_schema"]


# Stable in-context instruction. Kept short — the prompt template carries
# task-specific guidance; this description only explains the tool's role.
_DEFAULT_DESCRIPTION = (
    "Submit the typed payload for this node. Call exactly once when the "
    "task is complete. The payload must match the input_schema."
)


def compile_to_tool_schema(
    contract: type[BaseModel], node_id: str
) -> dict[str, Any]:
    """Compile a Pydantic contract into a ``submit_<node_id>`` tool definition.

    Args:
        contract: The Pydantic model produced by
            :func:`harness.workflow.contract.compile_inline_contract` (or any
            other ``BaseModel`` subclass). Defines the typed shape the agent
            must submit.
        node_id: The workflow step's ``id``. Becomes the suffix on the tool
            name so different nodes in the same workflow expose distinct
            submit tools.

    Returns:
        A tool-definition dict with three keys: ``name`` (the
        ``submit_<node_id>`` string), ``description`` (stable in-context
        guidance), and ``input_schema`` (the Pydantic JSON schema).
    """
    return {
        "name": f"submit_{node_id}",
        "description": _DEFAULT_DESCRIPTION,
        "input_schema": contract.model_json_schema(),
    }
