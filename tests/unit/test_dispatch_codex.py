"""Tests for harness.dispatch.codex — see SPEC §4.4, §4.7, §10.

CodexAgent is the subprocess adapter wrapping the ``codex`` CLI. It shares the
same five failure-mode detectors as ClaudeAgent (SPEC §4.4) and the stall
detector (SPEC §10). None of these tests launch a real subprocess: every test
injects a fake ``proc_fn`` via the ``CodexAgent(proc_fn=...)`` hook so we
exercise the wiring without the codex binary.

Test layout mirrors test_dispatch_opencode.py:

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
from harness.dispatch.codex import CodexAgent, _build_cmd, _classify_real_line
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


def test_codex_agent_satisfies_agent_protocol() -> None:
    """CodexAgent is structurally an Agent."""
    agent = CodexAgent(proc_fn=_make_proc_fn([]))
    assert isinstance(agent, Agent)


def test_codex_agent_satisfies_resettable_agent_protocol() -> None:
    """CodexAgent also satisfies ResettableAgent (implements reset())."""
    agent = CodexAgent(proc_fn=_make_proc_fn([]))
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
    agent = CodexAgent(proc_fn=_make_proc_fn(events))

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
    agent = CodexAgent(proc_fn=_make_proc_fn(events))

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
    agent = CodexAgent(proc_fn=_make_proc_fn(events))

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
    agent = CodexAgent(proc_fn=_make_proc_fn(events))

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
    agent = CodexAgent(proc_fn=_make_proc_fn(events))

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
    agent = CodexAgent(
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
    agent = CodexAgent(proc_fn=_make_proc_fn(events))

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
    agent = CodexAgent(proc_fn=_make_proc_fn(events))

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
    agent = CodexAgent(proc_fn=_make_stalled_proc_fn(delay_s=2.0))

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

    agent = CodexAgent(proc_fn=_proc)
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
    agent = CodexAgent(proc_fn=_make_proc_fn(events))

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

    agent = CodexAgent(proc_fn=proc_fn)

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
    agent = CodexAgent(
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
    agent = CodexAgent(proc_fn=_make_proc_fn(events))

    result = await agent.execute(
        "p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=[], cwd=None
    )
    assert result.contract.summary == "ok"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC11 — NDJSON line parsing (_classify_real_line unit tests)
# ---------------------------------------------------------------------------


def _ndjson_function_call(
    name: str,
    call_id: str,
    arguments: dict[str, Any],
) -> str:
    """Build a function_call NDJSON line (codex format)."""
    return json.dumps(
        {
            "type": "function_call",
            "id": call_id,
            "function": {
                "name": name,
                "arguments": json.dumps(arguments),
            },
        }
    )


def _ndjson_function_call_output(
    call_id: str,
    output: str = "OK",
    exit_code: int | None = 0,
) -> str:
    """Build a function_call_output NDJSON line (codex format)."""
    obj: dict[str, Any] = {
        "type": "function_call_output",
        "call_id": call_id,
        "output": output,
    }
    if exit_code is not None:
        obj["metadata"] = {"exit_code": exit_code}
    return json.dumps(obj)


def _ndjson_message(role: str, content: Any) -> str:
    """Build a message NDJSON line (codex format)."""
    return json.dumps(
        {
            "type": "message",
            "role": role,
            "content": content,
        }
    )


def test_classify_function_call_emits_tool_call() -> None:
    """A function_call line with well-formed arguments JSON -> [tool_call]."""
    line = _ndjson_function_call(
        name="submit_node_id",
        call_id="fc_abc",
        arguments={"summary": "done"},
    )
    events = _classify_real_line(line)
    assert len(events) == 1

    tc = events[0]
    assert tc["kind"] == "tool_call"
    assert tc["name"] == "submit_node_id"
    assert tc["tool_use_id"] == "fc_abc"
    assert tc["input"] == {"summary": "done"}


def test_classify_function_call_output_exit_code_0_not_error() -> None:
    """A function_call_output with exit_code 0 -> [tool_result(is_error=False)]."""
    line = _ndjson_function_call_output(call_id="fc_abc", output="result text", exit_code=0)
    events = _classify_real_line(line)
    assert len(events) == 1

    tr = events[0]
    assert tr["kind"] == "tool_result"
    assert tr["tool_use_id"] == "fc_abc"
    assert tr["content"] == "result text"
    assert tr["is_error"] is False


def test_classify_function_call_output_exit_code_nonzero_is_error() -> None:
    """A function_call_output with exit_code != 0 -> [tool_result(is_error=True)]."""
    line = _ndjson_function_call_output(call_id="fc_err", output="err msg", exit_code=1)
    events = _classify_real_line(line)
    assert len(events) == 1

    tr = events[0]
    assert tr["kind"] == "tool_result"
    assert tr["tool_use_id"] == "fc_err"
    assert tr["content"] == "err msg"
    assert tr["is_error"] is True


def test_classify_message_assistant_string_content_emits_text() -> None:
    """A message event with role==assistant and string content -> [text]."""
    line = _ndjson_message(role="assistant", content="I will now do the thing.")
    events = _classify_real_line(line)
    assert events == [{"kind": "text", "text": "I will now do the thing."}]


def test_classify_message_non_assistant_role_is_ignored() -> None:
    """A message event with a non-assistant role -> ignored."""
    line = _ndjson_message(role="user", content="some user text")
    events = _classify_real_line(line)
    assert events == [{"kind": "ignored"}]


def test_classify_function_call_malformed_arguments_is_ignored() -> None:
    """A function_call with malformed arguments JSON string -> ignored."""
    line = json.dumps(
        {
            "type": "function_call",
            "id": "fc_bad",
            "function": {
                "name": "some_tool",
                "arguments": "{not valid json",
            },
        }
    )
    events = _classify_real_line(line)
    assert events == [{"kind": "ignored"}]


def test_classify_session_created_is_ignored() -> None:
    """session_created events are ignored."""
    line = json.dumps({"type": "session_created", "session_id": "sess_xyz"})
    events = _classify_real_line(line)
    assert events == [{"kind": "ignored"}]


def test_classify_session_stopped_is_ignored() -> None:
    """session_stopped events are ignored."""
    line = json.dumps({"type": "session_stopped", "session_id": "sess_xyz", "reason": "done"})
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


def test_classify_function_call_output_absent_metadata_defaults_not_error() -> None:
    """A function_call_output with absent metadata -> [tool_result(is_error=False)]."""
    line = json.dumps(
        {
            "type": "function_call_output",
            "call_id": "fc_nometa",
            "output": "some output",
        }
    )
    events = _classify_real_line(line)
    assert len(events) == 1

    tr = events[0]
    assert tr["kind"] == "tool_result"
    assert tr["tool_use_id"] == "fc_nometa"
    assert tr["content"] == "some output"
    assert tr["is_error"] is False


def test_classify_message_assistant_empty_string_is_ignored() -> None:
    """A message event with assistant role and empty string content -> ignored."""
    line = _ndjson_message(role="assistant", content="")
    events = _classify_real_line(line)
    assert events == [{"kind": "ignored"}]


def test_classify_message_assistant_list_content_is_ignored() -> None:
    """A message event with assistant role and list content -> ignored."""
    line = _ndjson_message(role="assistant", content=[{"type": "text", "text": "hi"}])
    events = _classify_real_line(line)
    assert events == [{"kind": "ignored"}]


# ---------------------------------------------------------------------------
# AC12 — _build_cmd flag assembly
# ---------------------------------------------------------------------------


def test_build_cmd_no_model_produces_base_flags() -> None:
    """No model -> [\"codex\", \"--full-auto\", \"-q\"] with no --model flag."""
    cmd = _build_cmd(model=None)
    assert cmd == ["codex", "--full-auto", "-q"]
    assert "--model" not in cmd


def test_build_cmd_with_model_appends_model_flag() -> None:
    """With model -> appends [\"--model\", <model_id>]."""
    cmd = _build_cmd(model="gpt-4o")
    assert "--model" in cmd
    model_idx = cmd.index("--model")
    assert cmd[model_idx + 1] == "gpt-4o"


def test_build_cmd_always_starts_with_codex() -> None:
    """Command must always start with ``codex``."""
    cmd = _build_cmd(model=None)
    assert cmd[0] == "codex"


def test_build_cmd_always_includes_full_auto_and_quiet() -> None:
    """``--full-auto`` and ``-q`` must always be present."""
    for model in (None, "gpt-4o"):
        cmd = _build_cmd(model=model)
        assert "--full-auto" in cmd
        assert "-q" in cmd


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
    agent = CodexAgent(proc_fn=_make_proc_fn(events))

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
    agent = CodexAgent(proc_fn=_make_proc_fn(events))

    with pytest.raises(ContractViolation) as exc_info:
        await agent.execute(
            "p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=["Read"], cwd=None
        )
    assert exc_info.value.reason == "not_called"


# ---------------------------------------------------------------------------
# AC-new1/2 — Default construction (v1 guard removed)
# ---------------------------------------------------------------------------


def test_codex_agent_default_construction_succeeds() -> None:
    """CodexAgent() without proc_fn constructs without error."""
    agent = CodexAgent()
    assert agent is not None


def test_codex_agent_default_proc_fn_is_set() -> None:
    """CodexAgent() with no proc_fn gets _default_proc_fn wired in."""
    from harness.dispatch.codex import _default_proc_fn

    agent = CodexAgent()
    assert agent._proc_fn is _default_proc_fn


def test_codex_agent_with_proc_fn_is_constructable() -> None:
    """Providing proc_fn sets that proc_fn (test seam still works)."""
    agent = CodexAgent(proc_fn=_make_proc_fn([]))
    assert agent is not None


# ---------------------------------------------------------------------------
# AC-new3/4 — _augment_prompt_for_submit
# ---------------------------------------------------------------------------


def test_augment_prompt_appends_submit_header() -> None:
    """_augment_prompt_for_submit appends SUBMIT instructions containing field names."""
    from harness.dispatch.codex import _augment_prompt_for_submit

    result = _augment_prompt_for_submit("Do the thing.", SUBMIT_SCHEMA)
    assert "Do the thing." in result
    assert "SUBMIT:" in result
    assert "summary" in result


def test_augment_prompt_preserves_original() -> None:
    """_augment_prompt_for_submit result starts with original prompt text."""
    from harness.dispatch.codex import _augment_prompt_for_submit

    original = "Review the code changes."
    result = _augment_prompt_for_submit(original, SUBMIT_SCHEMA)
    assert result.startswith(original)


def test_augment_prompt_example_is_single_line_submit() -> None:
    """The prompt example must match the single-line SUBMIT parser."""
    from harness.dispatch.codex import (
        _augment_prompt_for_submit,
        _extract_submit_from_text,
    )

    result = _augment_prompt_for_submit("Do the thing.", SUBMIT_SCHEMA)
    submit_lines = [line for line in result.splitlines() if line.startswith("SUBMIT: {")]
    assert submit_lines == ['SUBMIT: {"summary": "..."}']
    assert _extract_submit_from_text(submit_lines[0]) == {"summary": "..."}


# ---------------------------------------------------------------------------
# AC-new5/6/7 — _extract_submit_from_text
# ---------------------------------------------------------------------------


def test_extract_submit_from_text_detects_submit_line() -> None:
    """_extract_submit_from_text returns parsed dict when SUBMIT: line present."""
    from harness.dispatch.codex import _extract_submit_from_text

    text = 'Here is my analysis.\nSUBMIT: {"summary": "all good"}\nDone.'
    result = _extract_submit_from_text(text)
    assert result == {"summary": "all good"}


def test_extract_submit_from_text_returns_none_when_absent() -> None:
    """_extract_submit_from_text returns None when no SUBMIT: line present."""
    from harness.dispatch.codex import _extract_submit_from_text

    text = "I reviewed everything and it looks good."
    result = _extract_submit_from_text(text)
    assert result is None


def test_extract_submit_from_text_ignores_malformed_json() -> None:
    """_extract_submit_from_text returns None when SUBMIT: payload is not valid JSON."""
    from harness.dispatch.codex import _extract_submit_from_text

    text = "SUBMIT: not valid json {"
    result = _extract_submit_from_text(text)
    assert result is None


# ---------------------------------------------------------------------------
# AC-new8 — execute handles text-based submit (SUBMIT: line in text event)
# ---------------------------------------------------------------------------


async def test_execute_handles_text_based_submit() -> None:
    """When a text event contains 'SUBMIT: <json>', execute treats it as submit."""
    events = [
        _text_event('Analysis complete.\nSUBMIT: {"summary": "all done"}\n'),
        _stop_event(),
    ]
    agent = CodexAgent(proc_fn=_make_proc_fn(events))
    result = await agent.execute(
        "do the thing",
        _SampleContract,
        SUBMIT_SCHEMA,
        allowed_tools=[],
        cwd=None,
    )
    assert result.contract.summary == "all done"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC-new10 — double text-based submit → first wins + decision_violation
# ---------------------------------------------------------------------------


async def test_execute_double_text_submit_first_wins() -> None:
    """Two SUBMIT: lines in text events → first wins, second emits decision_violation."""
    sink_events: list[tuple[str, dict[str, Any]]] = []
    events = [
        _text_event('SUBMIT: {"summary": "first"}'),
        _text_event('SUBMIT: {"summary": "second"}'),
        _stop_event(),
    ]
    agent = CodexAgent(
        proc_fn=_make_proc_fn(events),
        event_sink=lambda kind, payload: sink_events.append((kind, payload)),
    )
    result = await agent.execute(
        "p", _SampleContract, SUBMIT_SCHEMA, allowed_tools=[], cwd=None
    )
    assert result.contract.summary == "first"  # type: ignore[attr-defined]
    violations = [(k, p) for k, p in sink_events if k == "decision_violation"]
    assert len(violations) == 1


# ---------------------------------------------------------------------------
# AC-new11 — prompt is augmented with schema instructions before proc_fn call
# ---------------------------------------------------------------------------


async def test_execute_augments_prompt_before_sending() -> None:
    """The proc_fn receives an augmented prompt containing submit instructions."""
    received_stdin: list[str] = []

    async def capturing_proc_fn(
        *, cmd: list[str], stdin: str, env: dict[str, str], cwd: Any
    ) -> AsyncIterator[dict[str, Any]]:
        received_stdin.append(stdin)
        yield _tool_call_event("submit_node_id", {"summary": "done"})
        yield _tool_result_event()
        yield _stop_event()

    agent = CodexAgent(proc_fn=capturing_proc_fn)
    await agent.execute(
        "Original prompt.",
        _SampleContract,
        SUBMIT_SCHEMA,
        allowed_tools=[],
        cwd=None,
    )
    assert len(received_stdin) == 1
    assert "Original prompt." in received_stdin[0]
    assert "SUBMIT:" in received_stdin[0]


# ---------------------------------------------------------------------------
# AC-new12 — _build_cmd: no submit_tool_schema parameter
# ---------------------------------------------------------------------------


def test_build_cmd_no_model_produces_base_flags_no_schema_param() -> None:
    """_build_cmd takes only model; SUBMIT_SCHEMA is no longer a parameter."""
    cmd = _build_cmd(model=None)
    assert cmd == ["codex", "--full-auto", "-q"]
    assert "--model" not in cmd


def test_build_cmd_with_model_appends_model_flag_no_schema_param() -> None:
    """_build_cmd(model=...) appends --model flag; no submit_tool_schema arg."""
    cmd = _build_cmd(model="gpt-4o")
    assert "--model" in cmd
    model_idx = cmd.index("--model")
    assert cmd[model_idx + 1] == "gpt-4o"


# ---------------------------------------------------------------------------
# Integration — _default_proc_fn is an async generator function
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_codex_agent_real_proc_fn_is_callable() -> None:
    """The default proc_fn is an async generator callable (doesn't need codex binary)."""
    import inspect

    from harness.dispatch.codex import _default_proc_fn

    assert callable(_default_proc_fn)
    assert inspect.isasyncgenfunction(_default_proc_fn)
