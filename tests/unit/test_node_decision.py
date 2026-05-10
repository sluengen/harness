"""Tests for harness.nodes.decision — see SPEC §4.5.

DecisionNode is a thin gate over the AI dispatch path:

* ``actor: llm`` (v1) — same execution shape as ``AINode``, but the contract
  is required to declare ``decision: bool`` and a ``decision_made`` event is
  emitted on success.
* ``actor: human`` (v2) — schema-reserved; running such a workflow errors
  ("actor: human is reserved for v2") until the resume machinery ships.

Routing on ``on_reject:`` is the executor's job (H-007). The DecisionNode
itself only validates the contract, dispatches, and records the
``decision_made`` event with the ``on_reject`` value echoed verbatim for
audit / executor consumption.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from harness.dispatch.claude import ContractViolation
from harness.dispatch.mock import MockAgent, RecordedCall
from harness.events.schema import EventType
from harness.nodes.base import Attestation, NodeResult
from harness.nodes.decision import DecisionNode
from harness.state.schema import BaseState
from harness.workflow.schema import DecisionStep

# ---------------------------------------------------------------------------
# Fixtures / helpers (mirrors test_node_ai.py — duplicated by convention,
# tests don't import helpers across modules).
# ---------------------------------------------------------------------------


_DECISION_CONTRACT_DICT: dict[str, Any] = {"decision": "boolean"}


class _DecisionOnly(BaseModel):
    decision: bool


class _DecisionWithReasoning(BaseModel):
    decision: bool
    reasoning: str


class _NoDecision(BaseModel):
    summary: str


class _DecisionWrongType(BaseModel):
    decision: str


class _CompliantMockAgent(MockAgent):
    """A MockAgent that returns a result satisfying whatever contract it
    was passed. Builds a minimal valid payload by Pydantic field type.
    Pass ``payload`` to override per-field values."""

    def __init__(self, *, payload: dict[str, object] | None = None) -> None:
        super().__init__()
        self._payload_override = payload or {}

    async def execute(  # type: ignore[override]
        self,
        prompt: str,
        contract: type[BaseModel],
        submit_tool_schema: dict[str, object],
        *,
        allowed_tools: list[str],
        cwd: Path | None,
        timeout_s: int = 600,
        stall_timeout_s: int = 300,
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
            )
        )
        if self.error is not None:
            raise self.error
        payload: dict[str, object] = {}
        for field_name, info in contract.model_fields.items():
            if field_name in self._payload_override:
                payload[field_name] = self._payload_override[field_name]
                continue
            ann = info.annotation
            if ann is str or ann is type(None):
                payload[field_name] = "x"
            elif ann is int:
                payload[field_name] = 0
            elif ann is bool:
                payload[field_name] = False
            elif ann is float:
                payload[field_name] = 0.0
            else:
                payload[field_name] = "x"
        return NodeResult[BaseModel](
            contract=contract.model_validate(payload),
            attestation=Attestation(status="complete"),
        )


def _state(tmp_path: Path, **overrides: object) -> BaseState:
    defaults: dict[str, object] = {
        "run_id": "run_test",
        "workflow_name": "test_wf",
        "base_branch": "main",
        "worktree_path": None,
        "worktree_branch": None,
        "artifacts_dir": tmp_path / "artifacts",
        "started_at": datetime(2026, 5, 10, 12, 0, 0),
        "notes": [],
    }
    defaults.update(overrides)
    return BaseState(**defaults)  # type: ignore[arg-type]


def _step(
    *,
    id: str = "gate",
    actor: str = "llm",
    prompt: str | None = "p.j2",
    template_vars: dict[str, object] | None = None,
    allowed_tools: list[str] | None = None,
    contract: object | None = None,
    cwd: str | None = None,
    on_reject: str = "cancel",
    message: str | None = None,
) -> DecisionStep:
    """Build a DecisionStep with reasonable defaults."""
    kwargs: dict[str, Any] = {
        "id": id,
        "type": "decision",
        "actor": actor,
        "on_reject": on_reject,
        "template_vars": template_vars or {},
        "allowed_tools": allowed_tools or ["Read"],
        "contract": contract if contract is not None else _DECISION_CONTRACT_DICT,
        "cwd": cwd,
    }
    if actor == "llm":
        kwargs["prompt"] = prompt
    if actor == "human":
        kwargs["message"] = message or "approve?"
    return DecisionStep(**kwargs)


def _write_prompt(prompts_dir: Path, name: str, body: str) -> None:
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / name).write_text(body)


def _make_sink() -> tuple[
    list[tuple[EventType, dict[str, Any]]],
    Any,
]:
    """Return (recorder, sink-callable) — sink appends to recorder."""
    recorded: list[tuple[EventType, dict[str, Any]]] = []

    def sink(event_type: EventType, payload: dict[str, Any]) -> None:
        recorded.append((event_type, payload))

    return recorded, sink


# ---------------------------------------------------------------------------
# AC1, AC2 — Node protocol conformance
# ---------------------------------------------------------------------------


def test_decision_node_type_attribute() -> None:
    """SPEC §4.3 Node Protocol: ``type`` is one of the five literals."""
    node = DecisionNode(agent=MockAgent(), prompts_dir=Path("/tmp/prompts"))
    assert node.type == "decision"


def test_decision_node_has_async_execute() -> None:
    import inspect

    node = DecisionNode(agent=MockAgent(), prompts_dir=Path("/tmp/prompts"))
    assert inspect.iscoroutinefunction(node.execute)


# ---------------------------------------------------------------------------
# AC3 — actor: human reserved for v2
# ---------------------------------------------------------------------------


async def test_actor_human_raises_v2_reserved(tmp_path: Path) -> None:
    """SPEC §4.5: workflows using actor: human error until v2 ships."""
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    agent = MockAgent()
    node = DecisionNode(agent=agent, prompts_dir=prompts)
    step = _step(actor="human", prompt=None, message="approve?")

    with pytest.raises(RuntimeError) as exc_info:
        await node.execute(step=step, state=_state(tmp_path), inputs={})
    assert "actor: human is reserved for v2" in str(exc_info.value)
    assert not agent.calls, "agent must not be invoked for human-actor steps"


# ---------------------------------------------------------------------------
# AC4 — Contract missing `decision` field is rejected (inline + pre-compiled)
# ---------------------------------------------------------------------------


async def test_inline_dict_contract_missing_decision_raises(tmp_path: Path) -> None:
    """Decision contracts MUST declare a `decision` field."""
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = MockAgent()
    node = DecisionNode(agent=agent, prompts_dir=prompts)
    step = _step(id="gate", contract={"summary": "string"})

    with pytest.raises(RuntimeError) as exc_info:
        await node.execute(step=step, state=_state(tmp_path), inputs={})
    msg = str(exc_info.value)
    assert "gate" in msg
    assert "decision: bool" in msg
    assert not agent.calls, "agent must not be dispatched when contract is invalid"


async def test_precompiled_contract_missing_decision_raises(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = MockAgent()
    node = DecisionNode(agent=agent, prompts_dir=prompts)
    step = _step(id="gate", contract=None)

    with pytest.raises(RuntimeError) as exc_info:
        await node.execute(
            step=step,
            state=_state(tmp_path),
            inputs={},
            contract_override=_NoDecision,
        )
    msg = str(exc_info.value)
    assert "gate" in msg
    assert "decision: bool" in msg
    assert not agent.calls


# ---------------------------------------------------------------------------
# AC5 — Contract has decision but wrong type
# ---------------------------------------------------------------------------


async def test_inline_dict_contract_decision_wrong_type_raises(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = MockAgent()
    node = DecisionNode(agent=agent, prompts_dir=prompts)
    step = _step(id="gate", contract={"decision": "string"})

    with pytest.raises(RuntimeError) as exc_info:
        await node.execute(step=step, state=_state(tmp_path), inputs={})
    msg = str(exc_info.value)
    assert "gate" in msg
    assert "decision: bool" in msg
    assert not agent.calls


async def test_precompiled_contract_decision_wrong_type_raises(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = MockAgent()
    node = DecisionNode(agent=agent, prompts_dir=prompts)
    step = _step(id="gate", contract=None)

    with pytest.raises(RuntimeError) as exc_info:
        await node.execute(
            step=step,
            state=_state(tmp_path),
            inputs={},
            contract_override=_DecisionWrongType,
        )
    msg = str(exc_info.value)
    assert "gate" in msg
    assert "decision: bool" in msg
    assert not agent.calls


# ---------------------------------------------------------------------------
# AC6 — Happy path dispatches via underlying AI shape
# ---------------------------------------------------------------------------


async def test_dispatches_with_rendered_prompt_schema_and_tools(tmp_path: Path) -> None:
    """The agent receives the rendered prompt, the compiled submit_<id>
    schema, and the configured allowed_tools — same as the AINode shape."""
    prompts = tmp_path / "prompts"
    _write_prompt(
        prompts,
        "p.j2",
        "decide on run={{ state.run_id }} task={{ inputs.task }}\n",
    )
    agent = _CompliantMockAgent()
    node = DecisionNode(agent=agent, prompts_dir=prompts)
    step = _step(id="approve", allowed_tools=["Read", "Grep"])

    await node.execute(
        step=step, state=_state(tmp_path), inputs={"task": "the-thing"}
    )

    assert len(agent.calls) == 1
    call = agent.calls[0]
    assert "decide on run=run_test" in call.prompt
    assert "task=the-thing" in call.prompt
    assert call.submit_tool_schema["name"] == "submit_approve"
    assert "decision" in call.submit_tool_schema["input_schema"]["properties"]
    assert call.allowed_tools == ["Read", "Grep"]


# ---------------------------------------------------------------------------
# AC7 — decision_made event emitted exactly once on success
# ---------------------------------------------------------------------------


async def test_decision_made_event_emitted_on_success(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = _CompliantMockAgent(payload={"decision": True})
    recorded, sink = _make_sink()
    node = DecisionNode(agent=agent, prompts_dir=prompts, event_sink=sink)
    step = _step(id="approve", on_reject="cancel")

    await node.execute(step=step, state=_state(tmp_path), inputs={})

    assert len(recorded) == 1
    event_type, payload = recorded[0]
    assert event_type == "decision_made"
    assert payload == {
        "step_id": "approve",
        "decision": True,
        "on_reject": "cancel",
    }


async def test_decision_made_event_carries_false_decision(tmp_path: Path) -> None:
    """A False decision is recorded faithfully (not coerced)."""
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = _CompliantMockAgent(payload={"decision": False})
    recorded, sink = _make_sink()
    node = DecisionNode(agent=agent, prompts_dir=prompts, event_sink=sink)
    step = _step(id="gate", on_reject="cancel")

    await node.execute(step=step, state=_state(tmp_path), inputs={})

    assert len(recorded) == 1
    assert recorded[0][1]["decision"] is False


# ---------------------------------------------------------------------------
# AC8 — Agent exception: no decision_made event
# ---------------------------------------------------------------------------


async def test_no_event_when_agent_raises(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = MockAgent(error=ContractViolation("not_called"))
    recorded, sink = _make_sink()
    node = DecisionNode(agent=agent, prompts_dir=prompts, event_sink=sink)
    step = _step()

    with pytest.raises(ContractViolation):
        await node.execute(step=step, state=_state(tmp_path), inputs={})

    assert recorded == [], "decision_made must not fire when dispatch fails"


async def test_no_event_when_contract_invalid(tmp_path: Path) -> None:
    """Contract validation failure aborts before dispatch — no event."""
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = MockAgent()
    recorded, sink = _make_sink()
    node = DecisionNode(agent=agent, prompts_dir=prompts, event_sink=sink)
    step = _step(contract={"summary": "string"})  # missing `decision`

    with pytest.raises(RuntimeError):
        await node.execute(step=step, state=_state(tmp_path), inputs={})

    assert recorded == []


# ---------------------------------------------------------------------------
# AC9 — event_sink is None → dispatch still works, no error
# ---------------------------------------------------------------------------


async def test_event_sink_none_is_noop(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = _CompliantMockAgent(payload={"decision": True})
    node = DecisionNode(agent=agent, prompts_dir=prompts, event_sink=None)

    result = await node.execute(step=_step(), state=_state(tmp_path), inputs={})

    assert result.contract.decision is True  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC10 — contract_override path
# ---------------------------------------------------------------------------


async def test_contract_override_with_decision_bool_accepted(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = _CompliantMockAgent(payload={"decision": True})
    node = DecisionNode(agent=agent, prompts_dir=prompts)
    step = _step(contract=None)

    result = await node.execute(
        step=step,
        state=_state(tmp_path),
        inputs={},
        contract_override=_DecisionOnly,
    )

    assert agent.calls[0].contract is _DecisionOnly
    assert result.contract.decision is True  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC11 — $contracts/<name> reference defers to H-008
# ---------------------------------------------------------------------------


async def test_contract_string_reference_raises_not_implemented(
    tmp_path: Path,
) -> None:
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = MockAgent()
    node = DecisionNode(agent=agent, prompts_dir=prompts)
    step = _step(contract="$contracts/approve-verdict")

    with pytest.raises(NotImplementedError) as exc_info:
        await node.execute(step=step, state=_state(tmp_path), inputs={})
    assert "H-008" in str(exc_info.value)


# ---------------------------------------------------------------------------
# AC12 — Extra contract fields pass through unchanged
# ---------------------------------------------------------------------------


async def test_extra_contract_fields_preserved(tmp_path: Path) -> None:
    """Decision contracts may declare extra fields (e.g. `reasoning`) — they
    must round-trip through the dispatch and arrive in the result."""
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = _CompliantMockAgent(
        payload={"decision": True, "reasoning": "looks good"}
    )
    node = DecisionNode(agent=agent, prompts_dir=prompts)
    step = _step(
        id="review",
        contract={"decision": "boolean", "reasoning": "string"},
    )

    result = await node.execute(step=step, state=_state(tmp_path), inputs={})

    assert result.contract.decision is True  # type: ignore[attr-defined]
    assert result.contract.reasoning == "looks good"  # type: ignore[attr-defined]


async def test_extra_contract_fields_precompiled_preserved(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = _CompliantMockAgent(
        payload={"decision": False, "reasoning": "missing data"}
    )
    node = DecisionNode(agent=agent, prompts_dir=prompts)

    result = await node.execute(
        step=_step(contract=None),
        state=_state(tmp_path),
        inputs={},
        contract_override=_DecisionWithReasoning,
    )

    assert result.contract.decision is False  # type: ignore[attr-defined]
    assert result.contract.reasoning == "missing data"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC13 — on_reject echoed verbatim into the event payload
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "on_reject", ["cancel", "continue", "retry_loop:foo", "pause_for_human"]
)
async def test_on_reject_echoed_into_event(tmp_path: Path, on_reject: str) -> None:
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = _CompliantMockAgent(payload={"decision": True})
    recorded, sink = _make_sink()
    node = DecisionNode(agent=agent, prompts_dir=prompts, event_sink=sink)
    step = _step(on_reject=on_reject)

    await node.execute(step=step, state=_state(tmp_path), inputs={})

    assert recorded[0][1]["on_reject"] == on_reject
