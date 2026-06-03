"""OpencodeAgent — subprocess adapter wrapping the ``opencode`` CLI (SPEC §4.7).

Implements the ``Agent`` protocol by running ``opencode run --format json``
as a managed subprocess and parsing its NDJSON output stream. Primary use is
local models via Ollama or llama-swap+llama.cpp through an OpenAI-compatible
endpoint — set ``provider`` and ``model`` accordingly.

Responsibilities:

1. Build and launch ``opencode run --format json [--model <spec>]`` with the
   prompt delivered via stdin.
2. Parse the NDJSON stream line-by-line using ``_classify_real_line``, which
   maps opencode's event format to the same adapter-dialect dicts used by
   ``ClaudeAgent``.
3. Detect all five SPEC §4.4 failure modes and raise ``ContractViolation`` /
   ``AgentStalled`` with the same structured shape as the Claude adapter so the
   executor's retry layer is unchanged.
4. Accumulate ``text`` events into ``self.notes`` per SPEC §7.

# Shared vocabulary

``ContractViolation``, ``AgentStalled``, ``ViolationReason``,
``_looks_placeholder``, and ``_payload_has_placeholder`` are imported from
``harness.dispatch.claude`` — they are spec-level concepts, not SDK concepts,
and should not be redefined here.

# Test seam

``__init__`` requires ``proc_fn`` (raises ``RuntimeError`` if omitted — OpenCode
dispatch is not supported in v1). The fake proc_fn receives keyword args
``(cmd, stdin, env, cwd)`` and yields adapter-dialect dicts. A real proc_fn
would yield raw NDJSON strings; ``_iter_with_stall_guard`` classifies them
via ``_classify_real_line``.

See SPEC §4.4 (failure-mode catalogue), §4.7 (Agent protocol), §7 (notes
channel), §10 (stall detection).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from harness.dispatch.claude import (
    AgentStalled,
    ContractViolation,
    _payload_has_placeholder,
)
from harness.events.schema import EventType
from harness.nodes.base import Attestation, NodeResult

# --------------------------------------------------------------------------- #
# Type aliases
# --------------------------------------------------------------------------- #

# A proc function takes keyword args (cmd, stdin, env, cwd) and yields a stream
# of *something* — adapter-dialect dicts in tests, raw NDJSON strings in prod.
ProcFn = Callable[..., AsyncIterator[Any]]


# --------------------------------------------------------------------------- #
# NDJSON event classification
# --------------------------------------------------------------------------- #


def _classify_real_line(line: str) -> list[dict[str, Any]]:
    """Parse one NDJSON line from ``opencode run --format json`` into
    zero or more adapter-dialect dicts.

    Mapping:
    - ``tool_use`` with ``part.state.status == "completed"`` ->
      ``[tool_call, tool_result]``
    - ``tool_use`` with ``part.state.status == "error"`` ->
      ``[tool_call, tool_result(is_error=True)]``
    - ``text`` -> ``[{"kind": "text", "text": ...}]``
    - ``step_start``, ``step_finish``, ``error``, unknown -> ``[ignored]``
    - Malformed or empty JSON -> ``[ignored]``
    """
    stripped = line.strip()
    if not stripped:
        return [{"kind": "ignored"}]

    try:
        obj: dict[str, Any] = json.loads(stripped)
    except json.JSONDecodeError:
        return [{"kind": "ignored"}]

    event_type = obj.get("type")

    if event_type == "tool_use":
        part: dict[str, Any] = obj.get("part", {})
        state: dict[str, Any] = part.get("state", {})
        status = state.get("status")
        tool_name: str = part.get("tool", "")
        call_id: str = part.get("callID", "")
        input_args: dict[str, Any] = state.get("input") or {}

        tool_call: dict[str, Any] = {
            "kind": "tool_call",
            "name": tool_name,
            "tool_use_id": call_id,
            "input": input_args,
        }

        if status == "completed":
            output: str = state.get("output", "")
            tool_result: dict[str, Any] = {
                "kind": "tool_result",
                "tool_use_id": call_id,
                "content": output,
                "is_error": False,
            }
            return [tool_call, tool_result]

        if status == "error":
            error_msg: str = state.get("error", "")
            error_result: dict[str, Any] = {
                "kind": "tool_result",
                "tool_use_id": call_id,
                "content": error_msg,
                "is_error": True,
            }
            return [tool_call, error_result]

        # Unknown status — treat as ignored.
        return [{"kind": "ignored"}]

    if event_type == "text":
        part_text: dict[str, Any] = obj.get("part", {})
        text_value: str = part_text.get("text", "")
        return [{"kind": "text", "text": text_value}]

    # step_start, step_finish, error, and all unknown types.
    return [{"kind": "ignored"}]


# --------------------------------------------------------------------------- #
# Command builder
# --------------------------------------------------------------------------- #


def _build_cmd(
    provider: str | None,
    model: str | None,
    submit_tool_schema: dict[str, Any],  # noqa: ARG001 — reserved for future MCP injection
) -> list[str]:
    """Build the ``opencode run`` invocation.

    Model flag logic:
    - Both ``provider`` and ``model`` set: ``--model provider/model``
    - Only ``model`` set: ``--model model``
    - Only ``provider`` set: ``--model provider/default``
    - Neither set: no ``--model`` flag

    # TODO: inject submit tool via MCP
    The submit tool schema is accepted here for future use when opencode gains
    MCP server support so the agent can call submit directly. For now, tool
    capture happens via NDJSON parsing.
    """
    cmd: list[str] = ["opencode", "run", "--format", "json"]

    if provider is not None and model is not None:
        cmd.extend(["--model", f"{provider}/{model}"])
    elif model is not None:
        cmd.extend(["--model", model])
    elif provider is not None:
        cmd.extend(["--model", f"{provider}/default"])

    return cmd


# --------------------------------------------------------------------------- #
# OpencodeAgent
# --------------------------------------------------------------------------- #


class OpencodeAgent:
    """``Agent`` adapter for the ``opencode`` CLI.

    See module docstring for design notes (notes channel, event sink,
    test seam, NDJSON parsing).
    """

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        event_sink: Callable[[EventType, dict[str, Any]], None] | None = None,
        proc_fn: ProcFn | None = None,
    ) -> None:
        if proc_fn is None:
            raise RuntimeError(
                "OpenCode dispatch is not supported in v1 of this release. "
                "Use ClaudeAgent instead, or pass proc_fn= for testing."
            )
        self._provider = provider
        self._model = model
        self._event_sink = event_sink
        self._proc_fn: ProcFn = proc_fn
        self.notes: list[str] = []

    # ---- public API ------------------------------------------------------- #

    def reset(self) -> None:
        """Drop the carried-over notes buffer.

        SPEC §10 fresh_context: the loop evaluator calls ``reset()`` between
        iterations of a ``fresh_context: true`` loop block.
        """
        self.notes = []

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
        max_turns: int | None = None,  # noqa: ARG002 — opencode CLI has no max_turns flag
    ) -> NodeResult[BaseModel]:
        """Run opencode and return ``NodeResult[contract]``.

        Raises:
            ContractViolation: F1/F2/F5 from SPEC §4.4 (and Pydantic failures).
            AgentStalled: SPEC §10 — no subprocess event for ``stall_timeout_s``
                seconds.
        """
        self.notes = []  # per-call reset

        submit_name = submit_tool_schema["name"]
        first_call: dict[str, Any] | None = None

        proc_fn = self._proc_fn
        cmd = _build_cmd(self._provider, self._model, submit_tool_schema)

        async for event in self._iter_with_stall_guard(
            proc_fn(
                cmd=cmd,
                stdin=prompt,
                env=dict(os.environ),
                cwd=cwd,
            ),
            stall_timeout_s=stall_timeout_s,
        ):
            kind = event.get("kind")

            if kind == "text":
                self.notes.append(event["text"])

            elif kind == "tool_call":
                self._emit("tool_called", {"name": event["name"], "input": event["input"]})
                if event["name"] == submit_name:
                    payload: dict[str, Any] = event["input"]
                    if first_call is None:
                        first_call = payload
                    else:
                        # F3: double submit. First wins; record the violation.
                        self._emit("decision_violation", {"payload": payload})

            elif kind == "tool_result":
                self._emit(
                    "tool_completed",
                    {
                        "tool_use_id": event["tool_use_id"],
                        "is_error": event.get("is_error", False),
                    },
                )

            elif kind == "stop":
                break

            # 'ignored' (and any future kinds) silently passes through.

        if first_call is None:
            # F1 / F5: agent ended without submitting.
            raise ContractViolation("not_called")

        if _payload_has_placeholder(first_call):
            # F2: payload looks like placeholder values.
            raise ContractViolation("placeholder", payload=first_call)

        try:
            validated = contract.model_validate(first_call)
        except ValidationError as e:
            raise ContractViolation(
                "validation_failed",
                message=f"submit payload failed Pydantic validation: {e}",
                payload=first_call,
            ) from e

        return NodeResult[BaseModel](
            contract=validated,
            attestation=Attestation(status="complete"),
        )

    # ---- internals -------------------------------------------------------- #

    def _emit(self, kind: EventType, payload: dict[str, Any]) -> None:
        """Forward an event to the sink if one was supplied; no-op otherwise."""
        if self._event_sink is not None:
            self._event_sink(kind, payload)

    @staticmethod
    async def _iter_with_stall_guard(
        source: AsyncIterator[Any],
        *,
        stall_timeout_s: int,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield from ``source``, raising ``AgentStalled`` on inactivity.

        Each ``__anext__`` is wrapped in ``asyncio.wait_for(stall_timeout_s)``.
        If a single gap between events exceeds the budget, the underlying
        coroutine is cancelled and ``AgentStalled`` is raised. The clock
        resets on every event — total elapsed time is the executor's
        ``timeout_s`` concern.

        Adapter-dialect dicts (``{"kind": ...}``) pass through. Raw NDJSON
        strings are classified via ``_classify_real_line``.
        """
        iterator = source.__aiter__()
        while True:
            t0 = time.monotonic()
            try:
                item = await asyncio.wait_for(iterator.__anext__(), timeout=stall_timeout_s)
            except StopAsyncIteration:
                return
            except TimeoutError as e:
                elapsed = time.monotonic() - t0
                raise AgentStalled(elapsed=elapsed) from e

            # Adapter-dialect dicts pass through; raw NDJSON strings get classified.
            if isinstance(item, dict) and "kind" in item:
                yield item
            else:
                for classified in _classify_real_line(str(item)):
                    yield classified


