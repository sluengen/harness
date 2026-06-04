"""CodexAgent — subprocess adapter wrapping the ``codex`` CLI (SPEC §4.7).

Implements the ``Agent`` protocol by running ``codex --full-auto -q``
as a managed subprocess and parsing its NDJSON output stream. Primary use is
OpenAI's agentic coding tool (github.com/openai/codex) — codex is OpenAI-native
so there is no ``provider`` concept; pass ``model`` to select a specific
OpenAI model.

Responsibilities:

1. Build and launch ``codex --full-auto -q [--model <model_id>]`` with the
   prompt delivered via stdin (augmented with SUBMIT instructions for agents
   that don't support native tool injection).
2. Parse the NDJSON stream line-by-line using ``_classify_real_line``, which
   maps codex's event format to the same adapter-dialect dicts used by
   ``ClaudeAgent`` and ``OpencodeAgent``.
3. Detect all five SPEC §4.4 failure modes and raise ``ContractViolation`` /
   ``AgentStalled`` with the same structured shape as the other adapters so the
   executor's retry layer is unchanged.
4. Accumulate ``text`` events into ``self.notes`` per SPEC §7.

# Shared vocabulary

``ContractViolation``, ``AgentStalled``, ``ViolationReason``,
``_looks_placeholder``, and ``_payload_has_placeholder`` are imported from
``harness.dispatch.claude`` — they are spec-level concepts, not SDK concepts,
and should not be redefined here.

# Test seam

``__init__`` accepts an optional ``proc_fn``. When omitted, ``_default_proc_fn``
is wired in as the real subprocess path. For tests, supply a fake proc_fn that
yields adapter-dialect dicts directly.

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

from harness.dispatch.base import AgentCapability
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
# Default subprocess proc_fn
# --------------------------------------------------------------------------- #


async def _default_proc_fn(
    *,
    cmd: list[str],
    stdin: str,
    env: dict[str, str],
    cwd: Path | None,
) -> AsyncIterator[str]:
    """Run cmd as a subprocess, feed stdin, yield stdout lines as NDJSON strings."""
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=env,
        cwd=cwd,
    )
    if process.stdin is None:  # pragma: no cover
        raise RuntimeError("subprocess stdin pipe was not created")
    if process.stdout is None:  # pragma: no cover
        raise RuntimeError("subprocess stdout pipe was not created")
    process.stdin.write(stdin.encode())
    await process.stdin.drain()
    process.stdin.close()
    async for line in process.stdout:
        yield line.decode()
    await process.wait()


# --------------------------------------------------------------------------- #
# NDJSON event classification
# --------------------------------------------------------------------------- #


def _classify_real_line(line: str) -> list[dict[str, Any]]:
    """Parse one NDJSON line from ``codex --full-auto -q`` into
    zero or more adapter-dialect dicts.

    Mapping:
    - ``function_call`` with well-formed ``arguments`` JSON string ->
      ``[tool_call]``
    - ``function_call`` with malformed ``arguments`` -> ``[ignored]``
    - ``function_call_output`` -> ``[tool_result]``; ``is_error`` is True when
      ``metadata.exit_code != 0``; absent ``metadata`` defaults to not an error
    - ``message`` with ``role == "assistant"`` and non-empty string ``content`` ->
      ``[{"kind": "text", "text": ...}]``
    - ``message`` with non-assistant role, list content, or empty content ->
      ``[ignored]``
    - ``session_created``, ``session_stopped``, unknown types -> ``[ignored]``
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

    if event_type == "function_call":
        call_id: str = obj.get("id", "")
        function: dict[str, Any] = obj.get("function", {})
        name: str = function.get("name", "")
        raw_args: str = function.get("arguments", "{}")
        try:
            input_args: dict[str, Any] = json.loads(raw_args)
        except json.JSONDecodeError:
            return [{"kind": "ignored"}]

        tool_call: dict[str, Any] = {
            "kind": "tool_call",
            "name": name,
            "tool_use_id": call_id,
            "input": input_args,
        }
        return [tool_call]

    if event_type == "function_call_output":
        call_id_out: str = obj.get("call_id", "")
        output: str = obj.get("output", "")
        metadata: dict[str, Any] = obj.get("metadata") or {}
        exit_code = metadata.get("exit_code")
        is_error: bool = exit_code is not None and exit_code != 0

        tool_result: dict[str, Any] = {
            "kind": "tool_result",
            "tool_use_id": call_id_out,
            "content": output,
            "is_error": is_error,
        }
        return [tool_result]

    if event_type == "message":
        role: str = obj.get("role", "")
        content = obj.get("content", "")
        if role == "assistant" and isinstance(content, str) and content:
            return [{"kind": "text", "text": content}]
        return [{"kind": "ignored"}]

    # session_created, session_stopped, and all unknown types.
    return [{"kind": "ignored"}]


# --------------------------------------------------------------------------- #
# Submit-via-text helpers (supports_submit_tool=False path)
# --------------------------------------------------------------------------- #


def _augment_prompt_for_submit(prompt: str, submit_tool_schema: dict[str, Any]) -> str:
    """Append submit-tool instructions for agents that don't support native tool injection.

    Instructs the agent to output a SUBMIT: <json> line when done, which the
    execute loop recognises and treats as the structured output submit call.
    """
    name = submit_tool_schema.get("name", "submit")
    input_schema = submit_tool_schema.get("input_schema", {})
    properties = input_schema.get("properties", {})
    required: list[str] = input_schema.get("required", [])

    fields_desc = "\n".join(
        f"  - {k}: {v.get('type', 'string')}"
        + (f" (one of: {v['enum']})" if "enum" in v else "")
        for k, v in properties.items()
    )

    schema_json = json.dumps(dict.fromkeys(required, "...") if required else {})

    instruction = (
        f"\n\n---\n"
        f"## Completion Signal\n\n"
        f"When you have finished the task, you MUST signal completion by including "
        f"the following single line anywhere in your final response:\n\n"
        f"SUBMIT: <json>\n\n"
        f"Where <json> is a JSON object with these required fields:\n"
        f"{fields_desc}\n\n"
        f"Example:\n"
        f"SUBMIT: {schema_json}\n\n"
        f"The submit call name is: {name}\n"
    )
    return prompt + instruction


def _extract_submit_from_text(text: str) -> dict[str, Any] | None:
    """Scan a text event for a SUBMIT: <json> line and return the payload, or None.

    Accepts the first well-formed ``SUBMIT: <json>`` line found in *text*,
    regardless of which submit tool the workflow expects (the augmented prompt
    already constrains the model to emit the correct JSON shape for that tool).
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("SUBMIT:"):
            json_part = stripped[len("SUBMIT:"):].strip()
            try:
                payload = json.loads(json_part)
                if isinstance(payload, dict):
                    return payload
            except json.JSONDecodeError:
                pass
    return None


# --------------------------------------------------------------------------- #
# Command builder
# --------------------------------------------------------------------------- #


def _build_cmd(model: str | None) -> list[str]:
    """Build the ``codex`` invocation.

    Model flag logic:
    - ``model`` set: ``--model <model_id>``
    - ``model`` not set: no ``--model`` flag
    """
    cmd: list[str] = ["codex", "--full-auto", "-q"]

    if model is not None:
        cmd.extend(["--model", model])

    return cmd


# --------------------------------------------------------------------------- #
# CodexAgent
# --------------------------------------------------------------------------- #


class CodexAgent:
    """``Agent`` adapter for the ``codex`` CLI.

    See module docstring for design notes (notes channel, event sink,
    test seam, NDJSON parsing).
    """

    capability: AgentCapability = AgentCapability(
        supports_submit_tool=False,
        supports_cwd=True,
        supports_max_turns=False,
        supports_tool_allowlist=False,
    )

    def __init__(
        self,
        *,
        model: str | None = None,
        event_sink: Callable[[EventType, dict[str, Any]], None] | None = None,
        proc_fn: ProcFn | None = None,
    ) -> None:
        self._model = model
        self._event_sink = event_sink
        self._proc_fn: ProcFn = proc_fn if proc_fn is not None else _default_proc_fn
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
        max_turns: int | None = None,  # noqa: ARG002 — codex CLI has no max_turns flag
    ) -> NodeResult[BaseModel]:
        """Run codex and return ``NodeResult[contract]``.

        Raises:
            ContractViolation: F1/F2/F5 from SPEC §4.4 (and Pydantic failures).
            AgentStalled: SPEC §10 — no subprocess event for ``stall_timeout_s``
                seconds.
        """
        self.notes = []  # per-call reset

        submit_name = submit_tool_schema["name"]
        first_call: dict[str, Any] | None = None

        proc_fn = self._proc_fn
        cmd = _build_cmd(self._model)
        augmented_prompt = _augment_prompt_for_submit(prompt, submit_tool_schema)

        async for event in self._iter_with_stall_guard(
            proc_fn(
                cmd=cmd,
                stdin=augmented_prompt,
                env=dict(os.environ),
                cwd=cwd,
            ),
            stall_timeout_s=stall_timeout_s,
        ):
            kind = event.get("kind")

            if kind == "text":
                self.notes.append(event["text"])
                # Check for text-based submit (for agents with supports_submit_tool=False)
                submit_payload = _extract_submit_from_text(event["text"])
                if submit_payload is not None:
                    if first_call is None:
                        first_call = submit_payload
                    else:
                        self._emit("decision_violation", {"payload": submit_payload})

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
