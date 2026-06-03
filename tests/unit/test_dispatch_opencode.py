"""Tests for harness.dispatch.opencode — see SPEC §4.4, §4.7, §10.

OpencodeAgent is the subprocess adapter wrapping the ``opencode`` CLI. It
shares the same five failure-mode detectors as ClaudeAgent (SPEC §4.4) and the
stall detector (SPEC §10). None of these tests launch a real subprocess: every
test injects a fake ``proc_fn`` via the ``OpencodeAgent(proc_fn=...)`` hook so
we exercise the wiring without the opencode binary.

Test layout mirrors test_dispatch_claude.py:

- AC1  — Agent protocol conformance
- AC2  — Happy path: submit once with valid payload -> NodeResult
- AC3  — F1: narrate-instead-of-submit -> ContractViolation(reason="not_called")
- AC4  — F2: placeholder values -> ContractViolation(reason="placeholder")
- AC5  — F3: double submit -> first wins, sink records decision_violation
- AC6  — F4: submit then text -> notes accumulate, no error
- AC7  — F5: stop without submit -> ContractViolation(reason="not_called")
- AC8  — Stall detection -> AgentStalled with elapsed populated
- AC9  — Notes from text deltas in arrival order
- AC10 — Event sink gets tool_called / tool_completed
- AC11 — NDJSON line parsing (_classify_real_line unit tests)
- AC12 — _build_cmd flag assembly
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from pydantic import BaseModel

from harness.dispatch.base import Agent, ResettableAgent
from harness.dispatch.claude import AgentStalled, ContractViolation
from harness.dispatch.opencode import OpencodeAgent, _build_cmd, _classify_real_line
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


def _make_proc_fn(events: list[dict[str, Any]]) -> Callable[..., AsyncIterator[dict[str, Any]]]:
    """Build a fake proc_fn that yields the given adapter-dialect events.

    The real proc_fn yields raw NDJSON strings. The test seam yields plain
    dicts shaped like ``{"kind": ..., ...}`` — the same adapter-dialect the
    _iter_with_stall_guard passes through when items already have ``"kind"``.
    """

    async def _proc(
        *, cmd: list[str], stdin: str, env: dict[str, str] | None, cwd: Any
    ) -> AsyncIterator[dict[str, Any]]:
        for event in events:
            yield event

    return _proc


def _make_stalled_proc_fn(
    delay_s: float, events_after: list[dict[str, Any]] | None = None
) -> Callable[..., AsyncIterator[dict[str, Any]]]:
    """Build a fake proc_fn that sleeps ``delay_s`` before yielding anything."""
    events_after = events_after or []

    async def _proc(
        *, cmd: list[str], stdin: str, env: dict[str, str] | None, cwd: Any
    ) -> AsyncIterator[dict[str, Any]]:
        await asyncio.sleep(delay_s)
        for event in events_after:
            yield event

    return _proc


def _text_event(text: str) -> dict[str, Any]:
    return {"kind": "text", "text": text}


def _tool_call_event(
    name: str, input_: dict[str, Any], tool_use_id: str = "tu_1"
) -> dict[str, Any]:
    return {"kind": "tool_call", "name": name, "input": input_, "tool_use_id": tool_use_id}


def _tool_result_event(
    tool_use_id: str = "tu_1", content: str = "ok", is_error: bool = False
) -> dict[str, Any]:
    return {
        "kind": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }


def _stop_event() -> dict[str, Any]:
    return {"kind": "stop"}


# ---------------------------------------------------------------------------
# AC1 — Agent protocol conformance
# ---------------------------------------------------------------------------


def test_opencode_agent_satisfies_agent_protocol() -> None:
    """OpencodeAgent is structurally an Agent."""
    agent = OpencodeAgent(proc_fn=_make_proc_fn([]))
    assert isinstance(agent, Agent)


def test_opencode_agent_satisfies_resettable_agent_protocol() -> None:
    """OpencodeAgent also satisfies ResettableAgent (implements reset())."""
    agent = OpencodeAgent(proc_fn=_make_proc_fn([]))
    assert isinstance(agent, ResettableAgent)


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
    agent = OpencodeAgent(proc_fn=_make_proc_fn(events))

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
        _tool_call_event("submit_node_id", {"unrelated": 1}),
        _tool_result_event(),
        _stop_event(),
    ]
    agent = OpencodeAgent(proc_fn=_make_proc_fn(events))

    with pytest.raises(ContractViolation) as exc_info:
        await agent.execute(
            "p",
            _SampleContract,
            SUBMIT_SCHEMA,
            allowed_tools=[],
            cwd=None,
        )
    assert exc_info.value.reason == "validation_failed"


# ---------------------------------------------------------------------------
# AC3 — F1: narrate-instead-of-submit
# ---------------------------------------------------------------------------


async def test_f1_no_submit_call_raises_contract_violation_not_called() -> None:
    """SPEC §4.4 row 1: model narrates instead of calling submit."""
    events = [
        _text_event("The answer is 42, here it is in prose."),
        _stop_event(),
    ]
    agent = OpencodeAgent(proc_fn=_make_proc_fn(events))

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
    agent = OpencodeAgent(proc_fn=_make_proc_fn(events))

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
    agent = OpencodeAgent(proc_fn=_make_proc_fn(events))

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
    agent = OpencodeAgent(
        proc_fn=_make_proc_fn(events),
        event_sink=lambda kind, payload: sink_events.append((kind, payload)),
    )

    result = await agent.execute(
        "p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=[], cwd=None
    )

    assert result.contract.summary == "first"  # type: ignore[attr-defined]

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
    agent = OpencodeAgent(proc_fn=_make_proc_fn(events))

    result = await agent.execute(
        "p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=[], cwd=None
    )

    assert result.contract.summary == "the answer"  # type: ignore[attr-defined]
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
    agent = OpencodeAgent(proc_fn=_make_proc_fn(events))

    with pytest.raises(ContractViolation) as exc_info:
        await agent.execute(
            "p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=[], cwd=None
        )
    assert exc_info.value.reason == "not_called"


# ---------------------------------------------------------------------------
# AC8 — Stall detection
# ---------------------------------------------------------------------------


async def test_stall_detection_raises_agent_stalled_with_elapsed() -> None:
    """SPEC §10: no subprocess event for stall_timeout_s -> AgentStalled."""
    agent = OpencodeAgent(proc_fn=_make_stalled_proc_fn(delay_s=2.0))

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
    """An event train with gaps < stall_timeout_s must NOT trigger AgentStalled."""

    async def _proc(
        *, cmd: list[str], stdin: str, env: dict[str, str] | None, cwd: Any
    ) -> AsyncIterator[dict[str, Any]]:
        for chunk in ("a", "b", "c", "d"):
            await asyncio.sleep(0.3)
            yield _text_event(chunk)
        await asyncio.sleep(0.3)
        yield _tool_call_event("submit_node_id", {"summary": "done"})
        yield _tool_result_event()
        yield _stop_event()

    agent = OpencodeAgent(proc_fn=_proc)
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
    """SPEC §7 notes channel: text deltas accumulate on agent.notes."""
    events = [
        _text_event("first thought"),
        _text_event("second thought"),
        _tool_call_event("submit_node_id", {"summary": "done"}),
        _tool_result_event(),
        _text_event("a closing remark"),
        _stop_event(),
    ]
    agent = OpencodeAgent(proc_fn=_make_proc_fn(events))

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
    queries = [_make_proc_fn(first_events), _make_proc_fn(second_events)]
    call_count = {"n": 0}

    def proc_fn(**kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        q = queries[call_count["n"]]
        call_count["n"] += 1
        return q(**kwargs)

    agent = OpencodeAgent(proc_fn=proc_fn)

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
    agent = OpencodeAgent(
        proc_fn=_make_proc_fn(events),
        event_sink=lambda kind, payload: sink_events.append((kind, payload)),
    )

    await agent.execute("p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=[], cwd=None)

    kinds = [k for k, _ in sink_events]
    assert kinds.count("tool_called") == 2
    assert kinds.count("tool_completed") == 2

    called_payloads = [p for k, p in sink_events if k == "tool_called"]
    assert called_payloads[0]["name"] == "Read"
    assert called_payloads[0]["input"] == {"path": "x.py"}
    assert called_payloads[1]["name"] == "submit_node_id"
    assert called_payloads[1]["input"] == {"summary": "ok"}


async def test_event_sink_optional_no_error_when_absent() -> None:
    """An agent constructed without event_sink must not crash on tool calls."""
    events = [
        _tool_call_event("Read", {"path": "x.py"}),
        _tool_result_event(),
        _tool_call_event("submit_node_id", {"summary": "ok"}, tool_use_id="tu_2"),
        _tool_result_event(tool_use_id="tu_2"),
        _stop_event(),
    ]
    agent = OpencodeAgent(proc_fn=_make_proc_fn(events))

    result = await agent.execute(
        "p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=[], cwd=None
    )
    assert result.contract.summary == "ok"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC11 — NDJSON line parsing (_classify_real_line unit tests)
# ---------------------------------------------------------------------------


def _ndjson_tool_use_completed(
    tool: str,
    call_id: str,
    input_: dict[str, Any],
    output: str = "OK",
) -> str:
    """Build a completed tool_use NDJSON line."""
    return json.dumps(
        {
            "type": "tool_use",
            "timestamp": 1234,
            "sessionID": "sess1",
            "part": {
                "id": "part1",
                "type": "tool",
                "callID": call_id,
                "tool": tool,
                "state": {
                    "status": "completed",
                    "input": input_,
                    "output": output,
                },
            },
        }
    )


def _ndjson_tool_use_error(
    tool: str,
    call_id: str,
    input_: dict[str, Any],
    error: str = "failed",
) -> str:
    """Build an error tool_use NDJSON line."""
    return json.dumps(
        {
            "type": "tool_use",
            "timestamp": 1234,
            "sessionID": "sess1",
            "part": {
                "id": "part1",
                "type": "tool",
                "callID": call_id,
                "tool": tool,
                "state": {
                    "status": "error",
                    "input": input_,
                    "error": error,
                },
            },
        }
    )


def _ndjson_text(text: str) -> str:
    """Build a text NDJSON line."""
    return json.dumps(
        {
            "type": "text",
            "timestamp": 1234,
            "sessionID": "sess1",
            "part": {"type": "text", "text": text},
        }
    )


def test_classify_tool_use_completed_emits_tool_call_and_tool_result() -> None:
    """A completed tool_use line -> [tool_call, tool_result]."""
    line = _ndjson_tool_use_completed(
        tool="submit_node_id",
        call_id="call_123",
        input_={"summary": "done"},
        output="OK",
    )
    events = _classify_real_line(line)
    assert len(events) == 2

    tc, tr = events
    assert tc["kind"] == "tool_call"
    assert tc["name"] == "submit_node_id"
    assert tc["tool_use_id"] == "call_123"
    assert tc["input"] == {"summary": "done"}

    assert tr["kind"] == "tool_result"
    assert tr["tool_use_id"] == "call_123"
    assert tr["is_error"] is False
    assert tr["content"] == "OK"


def test_classify_tool_use_error_emits_tool_call_and_tool_result_is_error() -> None:
    """An error tool_use line -> [tool_call, tool_result(is_error=True)]."""
    line = _ndjson_tool_use_error(
        tool="some_tool",
        call_id="call_err",
        input_={},
        error="something broke",
    )
    events = _classify_real_line(line)
    assert len(events) == 2

    tc, tr = events
    assert tc["kind"] == "tool_call"
    assert tc["name"] == "some_tool"
    assert tc["tool_use_id"] == "call_err"

    assert tr["kind"] == "tool_result"
    assert tr["is_error"] is True
    assert tr["content"] == "something broke"


def test_classify_text_event() -> None:
    """A text NDJSON line -> [{"kind": "text", "text": ...}]."""
    line = _ndjson_text("I will now do the thing.")
    events = _classify_real_line(line)
    assert events == [{"kind": "text", "text": "I will now do the thing."}]


def test_classify_step_start_is_ignored() -> None:
    """step_start events are ignored."""
    line = json.dumps({"type": "step_start", "timestamp": 1, "sessionID": "s", "part": {}})
    events = _classify_real_line(line)
    assert events == [{"kind": "ignored"}]


def test_classify_step_finish_is_ignored() -> None:
    """step_finish events are ignored."""
    line = json.dumps({"type": "step_finish", "timestamp": 1, "sessionID": "s", "part": {}})
    events = _classify_real_line(line)
    assert events == [{"kind": "ignored"}]


def test_classify_error_event_is_ignored() -> None:
    """Top-level error events are ignored (subprocess exit handles fatal errors)."""
    line = json.dumps({"type": "error", "timestamp": 1, "sessionID": "s", "error": {}})
    events = _classify_real_line(line)
    assert events == [{"kind": "ignored"}]


def test_classify_unknown_type_is_ignored() -> None:
    """Unknown event types are silently ignored."""
    line = json.dumps({"type": "some_future_event", "data": "whatever"})
    events = _classify_real_line(line)
    assert events == [{"kind": "ignored"}]


def test_classify_malformed_json_is_ignored() -> None:
    """Malformed JSON lines must not crash — return ignored."""
    events = _classify_real_line("not valid json {{{")
    assert events == [{"kind": "ignored"}]


def test_classify_empty_line_is_ignored() -> None:
    """Empty lines (common in NDJSON) must be silently ignored."""
    events = _classify_real_line("")
    assert events == [{"kind": "ignored"}]


# ---------------------------------------------------------------------------
# AC12 — _build_cmd flag assembly
# ---------------------------------------------------------------------------


def test_build_cmd_with_both_provider_and_model() -> None:
    """Both provider and model -> --model provider/model."""
    cmd = _build_cmd(provider="ollama", model="llama3", submit_tool_schema=SUBMIT_SCHEMA)
    assert "opencode" in cmd
    assert "--format" in cmd
    assert "json" in cmd
    assert "--model" in cmd
    model_idx = cmd.index("--model")
    assert cmd[model_idx + 1] == "ollama/llama3"


def test_build_cmd_with_model_only() -> None:
    """Model only (no provider) -> --model model."""
    cmd = _build_cmd(provider=None, model="llama3", submit_tool_schema=SUBMIT_SCHEMA)
    assert "--model" in cmd
    model_idx = cmd.index("--model")
    assert cmd[model_idx + 1] == "llama3"


def test_build_cmd_with_provider_only() -> None:
    """Provider only (no model) -> --model provider/default."""
    cmd = _build_cmd(provider="ollama", model=None, submit_tool_schema=SUBMIT_SCHEMA)
    assert "--model" in cmd
    model_idx = cmd.index("--model")
    assert cmd[model_idx + 1] == "ollama/default"


def test_build_cmd_with_neither_provider_nor_model() -> None:
    """Neither provider nor model -> no --model flag."""
    cmd = _build_cmd(provider=None, model=None, submit_tool_schema=SUBMIT_SCHEMA)
    assert "--model" not in cmd


def test_build_cmd_always_includes_format_json() -> None:
    """All variants must include --format json."""
    for provider, model in [(None, None), ("p", None), (None, "m"), ("p", "m")]:
        cmd = _build_cmd(provider=provider, model=model, submit_tool_schema=SUBMIT_SCHEMA)
        assert "--format" in cmd
        fmt_idx = cmd.index("--format")
        assert cmd[fmt_idx + 1] == "json"


def test_build_cmd_starts_with_opencode_run() -> None:
    """Command must start with ``opencode run``."""
    cmd = _build_cmd(provider=None, model=None, submit_tool_schema=SUBMIT_SCHEMA)
    assert cmd[0] == "opencode"
    assert cmd[1] == "run"


# ---------------------------------------------------------------------------
# Submit name extracted from schema, not hard-coded
# ---------------------------------------------------------------------------


async def test_submit_tool_name_taken_from_schema() -> None:
    """Different node ids -> different submit_<id> names — adapter must follow."""
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
    agent = OpencodeAgent(proc_fn=_make_proc_fn(events))

    result = await agent.execute(
        "p", _SampleContract, schema, allowed_tools=[], cwd=None
    )
    assert result.contract.summary == "looks fine"  # type: ignore[attr-defined]


async def test_call_to_unrelated_tool_name_does_not_count_as_submit() -> None:
    """A tool call whose name doesn't match the schema must not satisfy submit."""
    events = [
        _tool_call_event("Read", {"path": "x.py"}),
        _tool_result_event(),
        _stop_event(),
    ]
    agent = OpencodeAgent(proc_fn=_make_proc_fn(events))

    with pytest.raises(ContractViolation) as exc_info:
        await agent.execute(
            "p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=["Read"], cwd=None
        )
    assert exc_info.value.reason == "not_called"


# ---------------------------------------------------------------------------
# Unsupported adapter guard (v1 restriction)
# ---------------------------------------------------------------------------


def test_opencode_agent_without_proc_fn_raises_runtime_error() -> None:
    """OpencodeAgent without proc_fn (real subprocess path) is not supported in v1."""
    with pytest.raises(RuntimeError, match="not supported"):
        OpencodeAgent()


def test_opencode_agent_with_proc_fn_is_constructable() -> None:
    """Providing proc_fn bypasses the unsupported-guard (test seam)."""
    agent = OpencodeAgent(proc_fn=_make_proc_fn([]))
    assert agent is not None
