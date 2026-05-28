"""ClaudeAgent — v1 adapter wrapping ``claude_agent_sdk`` for SPEC §4.7.

Implements the ``Agent`` protocol on top of Anthropic's ``claude_agent_sdk``
Python SDK, which embeds the Claude Code loop in-process. Responsibilities:

1. Run the SDK ``query`` loop with the executor-supplied prompt + allowed tools.
2. Inject a ``submit_<node_id>`` tool via an in-process MCP server
   (``_SUBMIT_MCP_SERVER``) so the agent session has a callable tool to
   signal completion.  The executor compiles the schema — see SPEC §4.4.
   The MCP server name is ``harness``; the full tool name seen by the agent
   is ``mcp__harness__submit_<node_id>``.
3. Detect the five SPEC §4.4 failure modes and raise ``ContractViolation``
   with a structured ``reason`` so the executor's retry layer can branch on
   it. Submit-twice does not raise; it emits a ``decision_violation`` event
   on the sink and the first call wins.
4. Detect stalls per SPEC §10 and raise ``AgentStalled`` with elapsed seconds.

# Notes channel — SPEC §4.4, §7

The protocol returns ``NodeResult`` with ``extra="forbid"``, so notes can't
ride on the return value. Instead, every ``execute()`` call accumulates the
SDK's text-delta stream into ``self.notes`` (reset at the top of each call).
The downstream ``AINode`` (H-014, separate ticket) is responsible for routing
``agent.notes`` into ``state.notes`` — this adapter is just the source.

# Event sink — interim wiring until H-014's executor adds an EventEmitter

``__init__`` accepts an optional ``event_sink: Callable[[EventType, dict], None]``.
The adapter calls it for every ``tool_called`` / ``tool_completed`` pair, plus
the canonical ``decision_violation`` event when submit is called more than once.
All event-type strings are members of ``harness.events.schema.EVENT_TYPES`` so
the executor's real EventEmitter (H-014) can forward them without translation.

# Auth surface

The SDK reads ``ANTHROPIC_API_KEY`` from the environment for API-rate calls,
and uses the ``claude /login`` cookie for subscription pricing. We do not
configure auth in this adapter — the SDK handles it via env / login state at
the underlying ``query()`` call.

# Test seam

``__init__`` accepts ``query_fn`` to swap in a fake SDK iterator for unit
tests; defaults to ``claude_agent_sdk.query``. The fake takes the same
keyword-only ``(prompt, options, transport)`` shape as the real ``query``.
Tests yield plain dicts shaped like
``{"kind": "text" | "tool_call" | "tool_result" | "stop", ...}``;
the adapter's classification logic dispatches on ``"kind"`` so the wiring is
exercised without depending on the SDK's specific message types. The real
``query`` yields SDK ``Message`` objects — adapt them to the same dialect via
``_classify_real_message`` (the only place SDK-specific code lives).

See SPEC §4.4 (failure-mode catalogue), §4.7 (Agent protocol), §7 (notes
channel), §10 (stall detection).
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from harness.events.schema import EventType
from harness.nodes.base import Attestation, NodeResult

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #

ViolationReason = Literal["not_called", "placeholder", "validation_failed"]


class ContractViolation(Exception):  # noqa: N818 — SPEC §4.4 names "contract violation"
    """The agent failed to deliver a valid structured payload via submit.

    Raised in three SPEC §4.4 cases (``reason`` distinguishes which):

    - ``"not_called"`` — agent ended its turn without calling submit (F1, F5).
    - ``"placeholder"`` — submit was called and Pydantic accepted it, but the
      values match the placeholder regex.
    - ``"validation_failed"`` — submit was called but the payload failed the
      Pydantic contract.

    The executor (out of scope here) catches this and applies the
    contract-violation retry layer per SPEC §10.
    """

    def __init__(
        self,
        reason: ViolationReason,
        *,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.reason: ViolationReason = reason
        self.payload = payload
        super().__init__(message or f"contract violation: {reason}")


class AgentStalled(Exception):  # noqa: N818 — SPEC §10 names the state "stalled"
    """The SDK stream went silent for longer than ``stall_timeout_s``.

    SPEC §10: a stall is distinct from the hard wall-clock timeout — it
    measures inactivity, not total elapsed time. ``elapsed`` records seconds
    waited since the last SDK event before the kill.
    """

    def __init__(self, elapsed: float, *, message: str | None = None) -> None:
        self.elapsed = elapsed
        super().__init__(message or f"agent stalled for {elapsed:.1f}s with no SDK events")


# --------------------------------------------------------------------------- #
# Placeholder detection
# --------------------------------------------------------------------------- #

# SPEC §4.4 row 2: reject submit payloads whose values look like obvious
# placeholders. Match the *whole* string only — substrings of real prose are
# allowed (e.g. "Refactored the loader; left a TODO for X" passes).
_PLACEHOLDER_RE = re.compile(r"^(TODO|<.*>|example|placeholder)$", re.IGNORECASE)


def _looks_placeholder(value: Any) -> bool:
    """True iff ``value`` is a string matching the placeholder regex.

    Non-string values (numbers, bools, nested dicts) never match — the
    failure mode SPEC §4.4 documents is specifically string-typed values like
    ``"summary": "TODO"``.
    """
    return isinstance(value, str) and bool(_PLACEHOLDER_RE.match(value.strip()))


def _payload_has_placeholder(payload: dict[str, Any]) -> bool:
    """True iff any top-level string field in ``payload`` matches the regex.

    Top-level only in v1 — nested-dict scanning isn't worth the complexity
    until a real workflow needs it.
    """
    return any(_looks_placeholder(v) for v in payload.values())


# Name of the in-process MCP server that exposes the submit tool to the agent.
# The agent sees the tool as ``mcp__<server>__submit_<node_id>``.
_SUBMIT_MCP_SERVER = "harness"


# --------------------------------------------------------------------------- #
# Event classification — interim dialect
# --------------------------------------------------------------------------- #

# Tests yield plain dicts shaped like {"kind": <literal>, ...}.  When the
# executor wires up the real ``claude_agent_sdk.query``, classification
# happens in ``_classify_real_message`` (below) which yields the same dicts.
# Keeping a single normalised dialect lets the rest of the adapter stay
# SDK-agnostic, which is the whole point of having an Agent protocol.

ClassifiedKind = Literal["text", "tool_call", "tool_result", "stop", "ignored"]


def _classify_real_message(message: Any) -> list[dict[str, Any]]:
    """Convert one SDK ``Message`` into zero or more adapter-dialect dicts.

    A single ``AssistantMessage`` may carry multiple content blocks
    (``TextBlock`` + ``ToolUseBlock`` + ``ToolResultBlock``). Each block
    becomes one classified event in arrival order.

    Imported lazily so the module loads without the SDK installed (tests use
    the ``query_fn`` test seam and never hit this path).
    """
    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ResultMessage,
            TextBlock,
            ToolResultBlock,
            ToolUseBlock,
            UserMessage,
        )
    except ImportError:  # pragma: no cover - covered by lazy import test seam
        return [{"kind": "ignored"}]

    out: list[dict[str, Any]] = []
    if isinstance(message, AssistantMessage | UserMessage):
        # ``UserMessage.content`` may be a plain string when a user prompt is
        # echoed back rather than a list of blocks. We only care about the
        # block form (tool results land here).
        content = message.content
        if isinstance(content, str):
            return [{"kind": "ignored"}]
        for block in content:
            if isinstance(block, TextBlock):
                out.append({"kind": "text", "text": block.text})
            elif isinstance(block, ToolUseBlock):
                out.append(
                    {
                        "kind": "tool_call",
                        "name": block.name,
                        "input": block.input,
                        "tool_use_id": block.id,
                    }
                )
            elif isinstance(block, ToolResultBlock):
                out.append(
                    {
                        "kind": "tool_result",
                        "tool_use_id": block.tool_use_id,
                        "content": block.content,
                        "is_error": bool(block.is_error),
                    }
                )
    elif isinstance(message, ResultMessage):
        out.append({"kind": "stop"})
    if not out:
        out.append({"kind": "ignored"})
    return out


# --------------------------------------------------------------------------- #
# ClaudeAgent
# --------------------------------------------------------------------------- #

# A query function takes the SDK ``query()`` keyword args and yields a stream
# of *something* — adapter-dialect dicts in tests, SDK Messages in production.
QueryFn = Callable[..., AsyncIterator[Any]]


class ClaudeAgent:
    """v1 ``Agent`` adapter for Anthropic's ``claude_agent_sdk``.

    See module docstring for the design notes (notes channel, event sink,
    auth, test seam).
    """

    def __init__(
        self,
        *,
        event_sink: Callable[[EventType, dict[str, Any]], None] | None = None,
        query_fn: QueryFn | None = None,
        model: str | None = None,
    ) -> None:
        self._event_sink = event_sink
        self._model = model
        self._query_fn = query_fn  # None -> resolved lazily inside execute()
        self.notes: list[str] = []

    # ---- public API ------------------------------------------------------- #

    def reset(self) -> None:
        """Drop the carried-over notes buffer.

        SPEC §10 fresh_context: the loop evaluator calls ``reset()``
        between iterations of a ``fresh_context: true`` loop. The
        per-call ``execute()`` already clears ``notes`` at its top, so
        this is belt-and-braces for callers that read ``self.notes``
        between iterations.
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
    ) -> NodeResult[BaseModel]:
        """Run the SDK loop and return ``NodeResult[contract]``.

        Raises:
            ContractViolation: F1/F2/F5 from SPEC §4.4 (and validation
                failures on the submit payload).
            AgentStalled: SPEC §10 — no SDK event for ``stall_timeout_s``
                seconds.
        """
        self.notes = []  # per-call reset; tests assert this contract.

        bare_submit_name = submit_tool_schema["name"]
        # The submit tool is exposed via an in-process MCP server so the agent
        # session has a callable tool. The real SDK emits the full MCP-namespaced
        # name in ToolUseBlock; the test seam uses the bare name directly.
        mcp_submit_name = f"mcp__{_SUBMIT_MCP_SERVER}__{bare_submit_name}"
        first_call: dict[str, Any] | None = None
        query_fn = self._query_fn or _resolve_real_query_fn()

        # Wall-clock cap. The executor wraps in its own ``asyncio.wait_for``
        # for total timeout enforcement; this is the per-stream stall guard.
        async for event in self._iter_with_stall_guard(
            query_fn(
                prompt=prompt,
                options=self._build_options(allowed_tools, cwd, submit_tool_schema),
            ),
            stall_timeout_s=stall_timeout_s,
        ):
            kind = event.get("kind")

            if kind == "text":
                self.notes.append(event["text"])

            elif kind == "tool_call":
                self._emit("tool_called", {"name": event["name"], "input": event["input"]})
                if event["name"] in (bare_submit_name, mcp_submit_name):
                    payload = event["input"]
                    if first_call is None:
                        first_call = payload
                    else:
                        # F3: double submit. First wins; record the violation
                        # on the sink. Workflow continues so post-submit text
                        # can still flow into notes.
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

            # 'ignored' (and any future event kinds) silently passes through.

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

    def _build_options(
        self,
        allowed_tools: list[str],
        cwd: Path | None,
        submit_tool_schema: dict[str, Any] | None = None,
    ) -> Any:
        """Build the ``ClaudeAgentOptions`` for the underlying ``query`` call.

        When ``submit_tool_schema`` is supplied, registers the submit tool as
        an in-process MCP server (``_SUBMIT_MCP_SERVER``) so the agent session
        has a callable ``mcp__harness__submit_<node_id>`` tool. The handler is
        a no-op — the dispatch loop captures the payload via the ``ToolUseBlock``
        event before the MCP handler runs.

        Imported lazily so this module loads without the SDK installed (tests
        provide ``query_fn`` and never call this).
        """
        try:
            from claude_agent_sdk import ClaudeAgentOptions, SdkMcpTool, create_sdk_mcp_server
        except ImportError:  # pragma: no cover - tests bypass via query_fn
            return None

        effective_allowed = list(allowed_tools)
        kwargs: dict[str, Any] = {}

        if submit_tool_schema is not None:
            bare_name: str = submit_tool_schema["name"]
            full_name = f"mcp__{_SUBMIT_MCP_SERVER}__{bare_name}"

            async def _noop_handler(args: dict[str, Any]) -> dict[str, Any]:
                return {"content": [{"type": "text", "text": "OK"}]}

            submit_tool = SdkMcpTool(
                name=bare_name,
                description=submit_tool_schema.get(
                    "description", "Submit the typed payload for this node."
                ),
                input_schema=submit_tool_schema["input_schema"],
                handler=_noop_handler,
            )
            server_cfg = create_sdk_mcp_server(_SUBMIT_MCP_SERVER, tools=[submit_tool])
            kwargs["mcp_servers"] = {_SUBMIT_MCP_SERVER: server_cfg}
            effective_allowed.append(full_name)

        kwargs["allowed_tools"] = effective_allowed
        if cwd is not None:
            kwargs["cwd"] = cwd
        if self._model is not None:
            kwargs["model"] = self._model
        return ClaudeAgentOptions(**kwargs)

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
        ``timeout_s`` concern, not ours.

        Real SDK messages get classified into adapter dialect on the fly.
        """
        iterator = source.__aiter__()
        while True:
            t0 = time.monotonic()
            try:
                msg = await asyncio.wait_for(iterator.__anext__(), timeout=stall_timeout_s)
            except StopAsyncIteration:
                return
            except TimeoutError as e:
                elapsed = time.monotonic() - t0
                raise AgentStalled(elapsed=elapsed) from e

            # Adapter-dialect dicts pass through; SDK Messages get classified.
            if isinstance(msg, dict) and "kind" in msg:
                yield msg
            else:
                for classified in _classify_real_message(msg):
                    yield classified


# --------------------------------------------------------------------------- #
# Real-SDK lazy import
# --------------------------------------------------------------------------- #


def _resolve_real_query_fn() -> QueryFn:
    """Return the real ``claude_agent_sdk.query`` or raise a clear error.

    Lazy so the module imports without the SDK installed (tests inject
    ``query_fn`` and never reach this).
    """
    try:
        from claude_agent_sdk import query
    except ImportError as e:  # pragma: no cover - executor concern
        raise RuntimeError(
            "claude_agent_sdk is not installed; install the dispatch[claude] extra "
            "or pass query_fn= for testing."
        ) from e
    return query
