"""Tests for harness.dispatch.claude — see SPEC §4.4, §4.7, §10.

ClaudeAgent is the v1 adapter. It wraps ``claude_agent_sdk.query`` with the
five failure-mode detectors required by SPEC §4.4 (narrate-instead-of-submit,
placeholder values, double-submit, submit-then-text, never-submitted) and the
stall detector required by SPEC §10. None of these tests touch the real SDK or
network: every test injects a fake ``query`` coroutine via the
``ClaudeAgent(query_fn=...)`` constructor hook so we exercise the wiring, not
the harness.

Test layout follows the AC groups in the H-012 brief:

- AC1 — Agent protocol conformance
- AC2 — Happy path: submit called once with valid payload returns NodeResult
- AC3 — F1: narrate-instead-of-submit -> ContractViolation(reason="not_called")
- AC4 — F2: placeholder values -> ContractViolation(reason="placeholder")
- AC5 — F3: double submit -> first wins, sink records decision_violation
- AC6 — F4: submit then more text -> notes accumulate, no error
- AC7 — F5: agent stops without ever submitting -> ContractViolation
- AC8 — Stall detection -> AgentStalled with elapsed populated
- AC9 — Notes captured from text deltas in arrival order
- AC10 — Event sink receives tool_called / tool_completed for each tool call
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from pydantic import BaseModel

from harness.dispatch.base import Agent
from harness.dispatch.claude import AgentStalled, ClaudeAgent, ContractViolation
from harness.nodes.base import NodeResult

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _SampleContract(BaseModel):
    summary: str


SUBMIT_SCHEMA: dict[str, Any] = {
    "name": "submit_node_id",
    "description": "Submit the typed payload for this node.",
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    },
}


def _text_event(text: str) -> dict[str, Any]:
    """A canned 'text delta' event for the fake SDK stream."""
    return {"kind": "text", "text": text}


def _tool_call_event(
    name: str, input_: dict[str, Any], tool_use_id: str = "tu_1"
) -> dict[str, Any]:
    """A canned 'tool call' event for the fake SDK stream."""
    return {"kind": "tool_call", "name": name, "input": input_, "tool_use_id": tool_use_id}


def _tool_result_event(
    tool_use_id: str = "tu_1", content: str = "ok", is_error: bool = False
) -> dict[str, Any]:
    """A canned 'tool result' event for the fake SDK stream."""
    return {
        "kind": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }


def _stop_event() -> dict[str, Any]:
    """A canned 'stop' event signalling the SDK turn ended."""
    return {"kind": "stop"}


def _make_query_fn(events: list[dict[str, Any]]) -> Callable[..., AsyncIterator[dict[str, Any]]]:
    """Build a fake ``query`` callable that yields the given event sequence.

    The real SDK returns an ``AsyncIterator[Message]``. We model it as an
    async iterator over plain dicts shaped like ``{"kind": ..., ...}``: the
    adapter's classification logic (text vs tool-call vs tool-result vs stop)
    is what we want to exercise, not the SDK's specific ``Message`` types.
    """

    async def _query(
        *, prompt: str, options: Any = None, transport: Any = None
    ) -> AsyncIterator[dict[str, Any]]:
        for event in events:
            yield event

    return _query


def _make_stalled_query_fn(
    delay_s: float, events_after: list[dict[str, Any]] | None = None
) -> Callable[..., AsyncIterator[dict[str, Any]]]:
    """Build a fake ``query`` that sleeps ``delay_s`` before yielding anything.

    Used to exercise the stall detector — the adapter must not block on a
    silent SDK iterator for longer than ``stall_timeout_s``.
    """
    events_after = events_after or []

    async def _query(
        *, prompt: str, options: Any = None, transport: Any = None
    ) -> AsyncIterator[dict[str, Any]]:
        await asyncio.sleep(delay_s)
        for event in events_after:
            yield event

    return _query


# ---------------------------------------------------------------------------
# AC1 — Agent protocol conformance
# ---------------------------------------------------------------------------


def test_claude_agent_satisfies_agent_protocol() -> None:
    """ClaudeAgent is structurally an Agent — see harness/dispatch/base.py."""
    agent = ClaudeAgent(query_fn=_make_query_fn([]))
    assert isinstance(agent, Agent)


# ---------------------------------------------------------------------------
# AC2 — Happy path
# ---------------------------------------------------------------------------


async def test_happy_path_submit_called_once_returns_node_result() -> None:
    """A submit call with a valid payload yields NodeResult[contract]."""
    events = [
        _text_event("I'll work on this and then submit."),
        _tool_call_event("submit_node_id", {"summary": "all done"}),
        _tool_result_event(),
        _stop_event(),
    ]
    agent = ClaudeAgent(query_fn=_make_query_fn(events))

    result = await agent.execute(
        "do the thing",
        _SampleContract,
        SUBMIT_SCHEMA,
        allowed_tools=["Read"],
        cwd=None,
    )

    assert isinstance(result, NodeResult)
    assert isinstance(result.contract, _SampleContract)
    assert result.contract.summary == "all done"
    assert result.attestation.status == "complete"


async def test_happy_path_validates_payload_against_contract() -> None:
    """Submit with a payload that fails Pydantic validation must raise."""
    events = [
        # Missing required 'summary' field.
        _tool_call_event("submit_node_id", {"unrelated": 1}),
        _tool_result_event(),
        _stop_event(),
    ]
    agent = ClaudeAgent(query_fn=_make_query_fn(events))

    with pytest.raises(ContractViolation) as exc_info:
        await agent.execute(
            "p",
            _SampleContract,
            SUBMIT_SCHEMA,
            allowed_tools=[],
            cwd=None,
        )
    # validation_failed is a distinct reason from the placeholder/not_called modes.
    assert exc_info.value.reason == "validation_failed"


# ---------------------------------------------------------------------------
# AC3 — F1: narrate-instead-of-submit
# ---------------------------------------------------------------------------


async def test_f1_no_submit_call_raises_contract_violation_not_called() -> None:
    """SPEC §4.4 row 1: model narrates the answer instead of calling submit."""
    events = [
        _text_event("The answer is 42, here it is in prose."),
        _stop_event(),
    ]
    agent = ClaudeAgent(query_fn=_make_query_fn(events))

    with pytest.raises(ContractViolation) as exc_info:
        await agent.execute(
            "p",
            _SampleContract,
            SUBMIT_SCHEMA,
            allowed_tools=[],
            cwd=None,
        )
    assert exc_info.value.reason == "not_called"


# ---------------------------------------------------------------------------
# AC4 — F2: placeholder values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "TODO",
        "todo",
        "<...>",
        "<placeholder>",
        "example",
        "Example",
        "PLACEHOLDER",
        "placeholder",
    ],
)
async def test_f2_placeholder_values_raise_contract_violation_placeholder(value: str) -> None:
    """SPEC §4.4 row 2: submit passes Pydantic but values look like placeholders."""
    events = [
        _tool_call_event("submit_node_id", {"summary": value}),
        _tool_result_event(),
        _stop_event(),
    ]
    agent = ClaudeAgent(query_fn=_make_query_fn(events))

    with pytest.raises(ContractViolation) as exc_info:
        await agent.execute(
            "p",
            _SampleContract,
            SUBMIT_SCHEMA,
            allowed_tools=[],
            cwd=None,
        )
    assert exc_info.value.reason == "placeholder"


async def test_f2_real_value_does_not_trip_placeholder_detector() -> None:
    """A genuine summary that contains 'TODO' as a substring must not trip."""
    events = [
        _tool_call_event(
            "submit_node_id",
            {"summary": "Refactored the loader; left a TODO for the deferred dict-merge case."},
        ),
        _tool_result_event(),
        _stop_event(),
    ]
    agent = ClaudeAgent(query_fn=_make_query_fn(events))

    result = await agent.execute(
        "p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=[], cwd=None
    )
    assert "TODO" in result.contract.summary  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC5 — F3: double submit
# ---------------------------------------------------------------------------


async def test_f3_double_submit_first_wins_and_sink_records_violation() -> None:
    """SPEC §4.4 row 3: submit called twice -> first wins, second is a violation."""
    events = [
        _tool_call_event("submit_node_id", {"summary": "first"}),
        _tool_result_event(tool_use_id="tu_1"),
        _tool_call_event("submit_node_id", {"summary": "second"}, tool_use_id="tu_2"),
        _tool_result_event(tool_use_id="tu_2"),
        _stop_event(),
    ]
    sink_events: list[tuple[str, dict[str, Any]]] = []
    agent = ClaudeAgent(
        query_fn=_make_query_fn(events),
        event_sink=lambda kind, payload: sink_events.append((kind, payload)),
    )

    result = await agent.execute(
        "p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=[], cwd=None
    )

    # First call wins.
    assert result.contract.summary == "first"  # type: ignore[attr-defined]

    # Sink records the violation with the *second* call's payload.
    violation_events = [(k, p) for k, p in sink_events if k == "decision_violation"]
    assert len(violation_events) == 1
    _, payload = violation_events[0]
    assert payload["payload"] == {"summary": "second"}


# ---------------------------------------------------------------------------
# AC6 — F4: submit then text continues
# ---------------------------------------------------------------------------


async def test_f4_submit_then_text_continues_no_error_notes_accumulate() -> None:
    """SPEC §4.4 row 4: submit called, then more text -> first wins, text -> notes."""
    events = [
        _tool_call_event("submit_node_id", {"summary": "the answer"}),
        _tool_result_event(),
        _text_event("post-submit explanation chunk one"),
        _text_event("post-submit explanation chunk two"),
        _stop_event(),
    ]
    agent = ClaudeAgent(query_fn=_make_query_fn(events))

    result = await agent.execute(
        "p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=[], cwd=None
    )

    assert result.contract.summary == "the answer"  # type: ignore[attr-defined]
    # post-submit text deltas land in notes (alongside any pre-submit ones).
    assert "post-submit explanation chunk one" in agent.notes
    assert "post-submit explanation chunk two" in agent.notes


# ---------------------------------------------------------------------------
# AC7 — F5: never submit + stop
# ---------------------------------------------------------------------------


async def test_f5_stop_without_submit_raises_not_called() -> None:
    """SPEC §4.4 row 5: agent stops without ever calling submit."""
    events = [
        _text_event("Looked at the code."),
        _text_event("It's complicated. I'll think more next time."),
        _stop_event(),
    ]
    agent = ClaudeAgent(query_fn=_make_query_fn(events))

    with pytest.raises(ContractViolation) as exc_info:
        await agent.execute(
            "p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=[], cwd=None
        )
    assert exc_info.value.reason == "not_called"


# ---------------------------------------------------------------------------
# AC8 — Stall detection
# ---------------------------------------------------------------------------


async def test_stall_detection_raises_agent_stalled_with_elapsed() -> None:
    """SPEC §10: no SDK event for stall_timeout_s -> AgentStalled."""
    # Fake query that sleeps far longer than the stall budget.
    agent = ClaudeAgent(query_fn=_make_stalled_query_fn(delay_s=2.0))

    with pytest.raises(AgentStalled) as exc_info:
        await agent.execute(
            "p",
            _SampleContract,
            SUBMIT_SCHEMA,
            allowed_tools=[],
            cwd=None,
            stall_timeout_s=1,
        )
    assert exc_info.value.elapsed >= 1.0


async def test_stall_resets_on_each_event() -> None:
    """A fast event train that takes longer than stall_timeout_s in total but
    never has a single gap that long must NOT trigger AgentStalled."""

    async def _query(
        *, prompt: str, options: Any = None, transport: Any = None
    ) -> AsyncIterator[dict[str, Any]]:
        # Each event arrives well within the stall window, total elapsed
        # exceeds it. Stall must reset on each event.
        for chunk in ("a", "b", "c", "d"):
            await asyncio.sleep(0.3)
            yield _text_event(chunk)
        await asyncio.sleep(0.3)
        yield _tool_call_event("submit_node_id", {"summary": "done"})
        yield _tool_result_event()
        yield _stop_event()

    agent = ClaudeAgent(query_fn=_query)
    result = await agent.execute(
        "p",
        _SampleContract,
        SUBMIT_SCHEMA,
        allowed_tools=[],
        cwd=None,
        stall_timeout_s=1,
    )
    assert result.contract.summary == "done"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC9 — Notes captured from text deltas
# ---------------------------------------------------------------------------


async def test_text_deltas_populate_notes_in_arrival_order() -> None:
    """SPEC §4.4 notes channel: text deltas accumulate on agent.notes."""
    events = [
        _text_event("first thought"),
        _text_event("second thought"),
        _tool_call_event("submit_node_id", {"summary": "done"}),
        _tool_result_event(),
        _text_event("a closing remark"),
        _stop_event(),
    ]
    agent = ClaudeAgent(query_fn=_make_query_fn(events))

    await agent.execute("p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=[], cwd=None)

    assert agent.notes == [
        "first thought",
        "second thought",
        "a closing remark",
    ]


async def test_notes_reset_between_executes() -> None:
    """`self.notes` is a per-call buffer — second execute must not see first's."""
    first_events = [
        _text_event("call-one note"),
        _tool_call_event("submit_node_id", {"summary": "one"}),
        _tool_result_event(),
        _stop_event(),
    ]
    second_events = [
        _text_event("call-two note"),
        _tool_call_event("submit_node_id", {"summary": "two"}),
        _tool_result_event(),
        _stop_event(),
    ]
    # The query_fn is called fresh each execute, so we wrap them.
    queries = [_make_query_fn(first_events), _make_query_fn(second_events)]
    call_count = {"n": 0}

    def query_fn(**kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        q = queries[call_count["n"]]
        call_count["n"] += 1
        return q(**kwargs)

    agent = ClaudeAgent(query_fn=query_fn)

    await agent.execute("p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=[], cwd=None)
    assert agent.notes == ["call-one note"]

    await agent.execute("p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=[], cwd=None)
    assert agent.notes == ["call-two note"]


# ---------------------------------------------------------------------------
# AC10 — Event sink receives tool_called / tool_completed
# ---------------------------------------------------------------------------


async def test_event_sink_receives_tool_called_and_tool_completed() -> None:
    """Each tool-call/tool-result pair fires sink('tool_called', ...) and
    sink('tool_completed', ...). Submit calls included."""
    events = [
        _tool_call_event("Read", {"path": "x.py"}, tool_use_id="tu_a"),
        _tool_result_event(tool_use_id="tu_a", content="file contents"),
        _tool_call_event("submit_node_id", {"summary": "ok"}, tool_use_id="tu_b"),
        _tool_result_event(tool_use_id="tu_b"),
        _stop_event(),
    ]
    sink_events: list[tuple[str, dict[str, Any]]] = []
    agent = ClaudeAgent(
        query_fn=_make_query_fn(events),
        event_sink=lambda kind, payload: sink_events.append((kind, payload)),
    )

    await agent.execute("p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=[], cwd=None)

    kinds = [k for k, _ in sink_events]
    # Read tool: called + completed. Submit tool: called + completed.
    assert kinds.count("tool_called") == 2
    assert kinds.count("tool_completed") == 2

    # Each tool_called payload carries the name and input.
    called_payloads = [p for k, p in sink_events if k == "tool_called"]
    assert called_payloads[0]["name"] == "Read"
    assert called_payloads[0]["input"] == {"path": "x.py"}
    assert called_payloads[1]["name"] == "submit_node_id"
    assert called_payloads[1]["input"] == {"summary": "ok"}


async def test_event_sink_optional_no_error_when_absent() -> None:
    """An agent constructed without an event_sink must not crash on tool calls."""
    events = [
        _tool_call_event("Read", {"path": "x.py"}),
        _tool_result_event(),
        _tool_call_event("submit_node_id", {"summary": "ok"}, tool_use_id="tu_2"),
        _tool_result_event(tool_use_id="tu_2"),
        _stop_event(),
    ]
    # event_sink omitted entirely.
    agent = ClaudeAgent(query_fn=_make_query_fn(events))

    result = await agent.execute(
        "p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=[], cwd=None
    )
    assert result.contract.summary == "ok"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Submit name extracted from the schema, not hard-coded
# ---------------------------------------------------------------------------


async def test_submit_tool_name_taken_from_schema() -> None:
    """Different node ids -> different submit_<id> names — the adapter must
    follow what the executor compiled, not assume a fixed string."""
    schema = {
        "name": "submit_review",
        "description": "...",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    }
    events = [
        _tool_call_event("submit_review", {"summary": "looks fine"}),
        _tool_result_event(),
        _stop_event(),
    ]
    agent = ClaudeAgent(query_fn=_make_query_fn(events))

    result = await agent.execute(
        "p", _SampleContract, schema, allowed_tools=[], cwd=None
    )
    assert result.contract.summary == "looks fine"  # type: ignore[attr-defined]


async def test_call_to_unrelated_tool_name_does_not_count_as_submit() -> None:
    """A tool call whose name doesn't match the schema must not satisfy the
    submit requirement — the agent must still be flagged not_called."""
    events = [
        _tool_call_event("Read", {"path": "x.py"}),
        _tool_result_event(),
        _stop_event(),
    ]
    agent = ClaudeAgent(query_fn=_make_query_fn(events))

    with pytest.raises(ContractViolation) as exc_info:
        await agent.execute(
            "p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=["Read"], cwd=None
        )
    assert exc_info.value.reason == "not_called"


# ---------------------------------------------------------------------------
# CAL-505 — MCP-prefixed submit name is accepted by execute()
# ---------------------------------------------------------------------------


async def test_mcp_prefixed_submit_name_counts_as_submit() -> None:
    """The real SDK emits ``mcp__harness__submit_<id>`` when the agent calls
    the in-process MCP submit tool.  execute() must accept that name as a
    valid submit call, not flag it as not_called.
    """
    from harness.dispatch.claude import _SUBMIT_MCP_SERVER

    mcp_name = f"mcp__{_SUBMIT_MCP_SERVER}__submit_node_id"
    events = [
        _tool_call_event(mcp_name, {"summary": "done via mcp"}),
        _tool_result_event(),
        _stop_event(),
    ]
    agent = ClaudeAgent(query_fn=_make_query_fn(events))

    result = await agent.execute(
        "p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=[], cwd=None
    )
    assert result.contract.summary == "done via mcp"  # type: ignore[attr-defined]


async def test_mcp_prefixed_name_of_different_server_does_not_count() -> None:
    """A submit call namespaced under a *different* MCP server must not satisfy
    the submit requirement — only ``mcp__harness__*`` is the canonical server."""
    mcp_name = "mcp__other_server__submit_node_id"
    events = [
        _tool_call_event(mcp_name, {"summary": "wrong server"}),
        _tool_result_event(),
        _stop_event(),
    ]
    agent = ClaudeAgent(query_fn=_make_query_fn(events))

    with pytest.raises(ContractViolation) as exc_info:
        await agent.execute(
            "p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=[], cwd=None
        )
    assert exc_info.value.reason == "not_called"
