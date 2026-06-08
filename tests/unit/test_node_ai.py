"""Tests for harness.nodes.ai — see SPEC §4.3, §4.4, §4.7, §5.

AINode renders a Jinja prompt with state/inputs/template_vars in scope,
compiles the contract to a ``submit_<id>`` tool schema, dispatches to an
injected ``Agent``, and returns the agent's :class:`NodeResult` for the
contract slot. State mutation, retries, ``writes:`` extraction, and event
emission are out of scope (executor / H-007).

The agent is faked via :class:`harness.dispatch.mock.MockAgent` — every
test asserts on what the AINode passed to the agent (recorded calls), not
on a real agent's behaviour. The Jinja env mirrors the runtime convention
asserted in :mod:`tests.unit.test_standard_prompts`: ``StrictUndefined``,
``keep_trailing_newline=True``, ``autoescape=False``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from jinja2 import UndefinedError
from pydantic import BaseModel

from harness.dispatch.claude import AgentStalled, ContractViolation
from harness.dispatch.mock import MockAgent, RecordedCall
from harness.nodes.ai import AINode
from harness.nodes.base import Attestation, NodeResult
from harness.state.schema import BaseState
from harness.workflow.schema import AIStep

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _Summary(BaseModel):
    summary: str


_SUMMARY_CONTRACT_DICT = {"summary": "string"}


class _CompliantMockAgent(MockAgent):
    """A MockAgent that returns a result satisfying whatever contract it
    was passed. Used by tests that want to exercise the AINode's happy
    path without caring about the agent's payload — they just need the
    isinstance guard not to fire on the AINode-compiled class.

    Pass ``payload`` to override the field values, otherwise minimal
    defaults are filled per Pydantic field type.
    """

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
        # Build minimal valid payload for the contract.
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
    """A BaseState with sensible defaults for tests; override per test."""
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
    id: str = "n1",
    prompt: str = "p.j2",
    template_vars: dict[str, object] | None = None,
    allowed_tools: list[str] | None = None,
    contract: object | None = None,
    writes: list[str] | None = None,
    cwd: str | None = None,
    writes_files: bool = False,
    stall_timeout_s: int = 300,
    timeout_s: int = 600,
    max_turns: int | None = None,
    persist_session: bool = False,
) -> AIStep:
    """Build an AIStep with reasonable defaults."""
    return AIStep(
        id=id,
        type="ai",
        prompt=prompt,
        template_vars=template_vars or {},
        allowed_tools=allowed_tools or ["Read"],
        contract=contract if contract is not None else _SUMMARY_CONTRACT_DICT,
        writes=writes if writes is not None else [],
        cwd=cwd,
        writes_files=writes_files,
        stall_timeout_s=stall_timeout_s,
        timeout_s=timeout_s,
        max_turns=max_turns,
        persist_session=persist_session,
    )


def _write_prompt(prompts_dir: Path, name: str, body: str) -> None:
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / name).write_text(body)


# ---------------------------------------------------------------------------
# AC1 — Node protocol conformance
# ---------------------------------------------------------------------------


def test_ai_node_type_attribute() -> None:
    """SPEC §4.3 Node Protocol: ``type`` is one of the five literals."""
    agent = MockAgent()
    node = AINode(agent=agent, prompts_dir=Path("/tmp/prompts"))
    assert node.type == "ai"


def test_ai_node_has_async_execute() -> None:
    import inspect

    agent = MockAgent()
    node = AINode(agent=agent, prompts_dir=Path("/tmp/prompts"))
    assert inspect.iscoroutinefunction(node.execute)


# ---------------------------------------------------------------------------
# AC2 — Renders the Jinja prompt
# AC3 — Render scope: state / inputs / template_vars
# ---------------------------------------------------------------------------


async def test_renders_prompt_with_state_inputs_and_template_vars(
    tmp_path: Path,
) -> None:
    prompts = tmp_path / "prompts"
    _write_prompt(
        prompts,
        "p.j2",
        "run={{ state.run_id }} inp={{ inputs.task }} tv={{ goal }}\n",
    )
    agent = _CompliantMockAgent()
    node = AINode(agent=agent, prompts_dir=prompts)
    state = _state(tmp_path)
    step = _step(template_vars={"goal": "find-bug"})

    await node.execute(step=step, state=state, inputs={"task": "the-thing"})

    assert agent.calls, "agent was never invoked"
    rendered = agent.calls[0].prompt
    assert "run=run_test" in rendered
    assert "inp=the-thing" in rendered
    assert "tv=find-bug" in rendered


async def test_template_vars_override_inputs_on_collision(tmp_path: Path) -> None:
    """template_vars wins over inputs on a non-reserved key collision."""
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "x={{ x }}\n")
    agent = _CompliantMockAgent()
    node = AINode(agent=agent, prompts_dir=prompts)
    step = _step(template_vars={"x": "from-tv"})

    await node.execute(step=step, state=_state(tmp_path), inputs={"x": "from-inputs"})

    assert "x=from-tv" in agent.calls[0].prompt


@pytest.mark.parametrize("reserved_key", ["state", "inputs"])
async def test_template_vars_cannot_shadow_reserved_scope_keys(
    tmp_path: Path, reserved_key: str
) -> None:
    """Reserved scope keys (state, inputs) are framework-owned — shadowing raises."""
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "anything\n")
    agent = _CompliantMockAgent()
    node = AINode(agent=agent, prompts_dir=prompts)
    step = _step(template_vars={reserved_key: "shadowed"})

    with pytest.raises(RuntimeError) as exc_info:
        await node.execute(step=step, state=_state(tmp_path), inputs={})
    msg = str(exc_info.value)
    # AC11: error names the step + the reserved key so debugging is one grep.
    assert "n1" in msg
    assert reserved_key in msg
    assert not agent.calls, "agent must not be invoked when render is rejected"


async def test_strict_undefined_raises_on_missing_var(tmp_path: Path) -> None:
    """StrictUndefined: a referenced-but-unsupplied var is a render-time error."""
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "{{ missing_var }}\n")
    agent = MockAgent()
    node = AINode(agent=agent, prompts_dir=prompts)

    with pytest.raises((UndefinedError, RuntimeError)) as exc_info:
        await node.execute(step=_step(), state=_state(tmp_path), inputs={})
    # AC11: error mentions the step id so debugging is one grep.
    assert "n1" in str(exc_info.value)


async def test_missing_prompt_file_raises_with_step_id(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    # No template file at p.j2.
    agent = MockAgent()
    node = AINode(agent=agent, prompts_dir=prompts)

    with pytest.raises(RuntimeError) as exc_info:
        await node.execute(step=_step(), state=_state(tmp_path), inputs={})
    assert "n1" in str(exc_info.value)
    assert "p.j2" in str(exc_info.value)


# ---------------------------------------------------------------------------
# AC4 (consumed) — submit_<id> schema is what the agent receives
# ---------------------------------------------------------------------------


async def test_dispatches_with_compiled_submit_tool_schema(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = _CompliantMockAgent()
    node = AINode(agent=agent, prompts_dir=prompts)

    await node.execute(step=_step(id="analyze"), state=_state(tmp_path), inputs={})

    schema = agent.calls[0].submit_tool_schema
    assert schema["name"] == "submit_analyze"
    # input_schema is a Pydantic JSON schema; spot-check the field name.
    assert "summary" in schema["input_schema"]["properties"]


# ---------------------------------------------------------------------------
# AC5 — Dispatches to injected Agent with allowed_tools / cwd / timeouts
# ---------------------------------------------------------------------------


async def test_dispatches_with_allowed_tools_and_timeouts(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = _CompliantMockAgent()
    node = AINode(agent=agent, prompts_dir=prompts)
    step = _step(allowed_tools=["Read", "Grep"], stall_timeout_s=42, timeout_s=99)

    await node.execute(step=step, state=_state(tmp_path), inputs={})

    call = agent.calls[0]
    assert call.allowed_tools == ["Read", "Grep"]
    assert call.stall_timeout_s == 42
    assert call.timeout_s == 99


async def test_cwd_resolution_step_cwd_wins(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = _CompliantMockAgent()
    node = AINode(agent=agent, prompts_dir=prompts)
    step = _step(cwd="/abs/from-step")
    state = _state(tmp_path, worktree_path=Path("/abs/from-state"))

    await node.execute(step=step, state=state, inputs={})

    assert agent.calls[0].cwd == Path("/abs/from-step")


async def test_cwd_resolution_falls_back_to_worktree_path(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = _CompliantMockAgent()
    node = AINode(agent=agent, prompts_dir=prompts)
    state = _state(tmp_path, worktree_path=Path("/abs/from-state"))

    await node.execute(step=_step(cwd=None), state=state, inputs={})

    assert agent.calls[0].cwd == Path("/abs/from-state")


async def test_cwd_resolution_none_when_neither_set(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = _CompliantMockAgent()
    node = AINode(agent=agent, prompts_dir=prompts)

    await node.execute(step=_step(cwd=None), state=_state(tmp_path), inputs={})

    assert agent.calls[0].cwd is None


# ---------------------------------------------------------------------------
# AC6 — Returns the agent's NodeResult; guards against misbehaving agents
# ---------------------------------------------------------------------------


async def test_returns_agent_node_result_unchanged(tmp_path: Path) -> None:
    """The contract instance the agent built is what the AINode hands back."""
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = _CompliantMockAgent(payload={"summary": "from-agent"})
    node = AINode(agent=agent, prompts_dir=prompts)

    result = await node.execute(step=_step(), state=_state(tmp_path), inputs={})

    # The compiled type is keyed off the step id — assert via the field
    # name on the dynamically-compiled instance.
    assert result.contract.summary == "from-agent"  # type: ignore[attr-defined]
    assert result.attestation.status == "complete"
    # Type matches what the agent received.
    assert isinstance(result.contract, agent.calls[0].contract)


async def test_misbehaving_agent_returns_wrong_contract_type_raises(
    tmp_path: Path,
) -> None:
    """Defensive isinstance check: if the agent bypasses validation and hands
    back a contract that isn't an instance of the declared contract class,
    AINode raises a clear RuntimeError naming the step.

    The guard only fires when the step declares writes — writes:[] steps are
    signal-only and the engine never extracts fields from their contract.
    """
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")

    # MockAgent's default result has contract=_EmptyContract() — which is
    # not an instance of the AINode-compiled summary contract.
    agent = MockAgent()  # default synthetic empty result
    node = AINode(agent=agent, prompts_dir=prompts)

    # writes=["summary"] ensures the guard fires (guard skips writes:[] steps).
    with pytest.raises(RuntimeError) as exc_info:
        await node.execute(
            step=_step(writes=["summary"]), state=_state(tmp_path), inputs={}
        )
    assert "n1" in str(exc_info.value)


# ---------------------------------------------------------------------------
# AC7 — Null contract (writes:[] exception) uses _EmptyContract
# ---------------------------------------------------------------------------


async def test_no_contract_step_uses_empty_contract(tmp_path: Path) -> None:
    """A step with contract=None (writes:[] exception per SPEC §5) does not
    raise at the AINode layer. Instead, AINode supplies a zero-field
    _EmptyContract so the agent still has a submit tool to call on completion.
    The loader / executor gate the "no-contract + non-empty writes" case.
    """
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = MockAgent()
    node = AINode(agent=agent, prompts_dir=prompts)
    # Build AIStep directly — _step() substitutes _SUMMARY_CONTRACT_DICT for None.
    step = AIStep(id="n1", type="ai", prompt="p.j2", contract=None, writes=[])

    result = await node.execute(step=step, state=_state(tmp_path), inputs={})

    assert result is not None
    # Agent receives the zero-field contract, not None.
    assert len(agent.calls[0].contract.model_fields) == 0


# ---------------------------------------------------------------------------
# AC8 — Inline dict compiled; pre-compiled type passed through; $contracts
#       reference deferred to H-008.
# ---------------------------------------------------------------------------


async def test_inline_dict_contract_compiled_on_demand(tmp_path: Path) -> None:
    """An inline dict contract compiles to a Pydantic model whose class name
    derives from the step id. The agent receives that compiled type."""
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = MockAgent()
    node = AINode(agent=agent, prompts_dir=prompts)
    # writes must be non-empty so the misbehaving-agent guard fires after compile.
    step = _step(
        id="analyze",
        contract={"summary": "string", "score": "integer"},
        writes=["summary", "score"],
    )

    # MockAgent default returns an empty contract — we expect the misbehaving
    # guard to fire *after* the compile step. We just assert on what was
    # passed to the agent, which is recorded *before* the guard runs.
    with pytest.raises(RuntimeError):
        await node.execute(step=step, state=_state(tmp_path), inputs={})

    contract_cls = agent.calls[0].contract
    # Title-cased step id + "Contract" suffix.
    assert contract_cls.__name__ == "AnalyzeContract"
    # Compiled fields match.
    assert set(contract_cls.model_fields) == {"summary", "score"}


async def test_precompiled_type_contract_passed_through(tmp_path: Path) -> None:
    """If the step's contract is already a BaseModel subclass, AINode uses
    it as-is (no recompile)."""
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = MockAgent()
    node = AINode(agent=agent, prompts_dir=prompts)

    # writes=["summary"] so the misbehaving-agent guard fires after dispatch
    # (MockAgent returns _EmptyContract(), not _Summary()).
    step = AIStep(
        id="x",
        type="ai",
        prompt="p.j2",
        contract=None,  # bypassed via contract_override
        writes=["summary"],
    )
    # Override the field directly via model_copy to inject a pre-compiled type.
    # The supported public path is via constructor `contract_override` — see
    # AINode docstring. Tests use a public knob.
    with pytest.raises(RuntimeError):
        await node.execute(
            step=step,
            state=_state(tmp_path),
            inputs={},
            contract_override=_Summary,
        )

    assert agent.calls[0].contract is _Summary


async def test_contract_string_reference_raises_not_implemented(
    tmp_path: Path,
) -> None:
    """``$contracts/<name>`` resolution lands in H-008 — AINode rejects it
    with a clear NotImplementedError naming the dependency ticket."""
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = MockAgent()
    node = AINode(agent=agent, prompts_dir=prompts)
    step = _step(contract="$contracts/review-verdict")

    with pytest.raises(NotImplementedError) as exc_info:
        await node.execute(step=step, state=_state(tmp_path), inputs={})
    assert "H-008" in str(exc_info.value)


# ---------------------------------------------------------------------------
# AC9 — Agent exceptions propagate
# ---------------------------------------------------------------------------


async def test_contract_violation_propagates(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = MockAgent(error=ContractViolation("not_called"))
    node = AINode(agent=agent, prompts_dir=prompts)

    with pytest.raises(ContractViolation):
        await node.execute(step=_step(), state=_state(tmp_path), inputs={})


async def test_agent_stalled_propagates(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = MockAgent(error=AgentStalled(elapsed=42.0))
    node = AINode(agent=agent, prompts_dir=prompts)

    with pytest.raises(AgentStalled):
        await node.execute(step=_step(), state=_state(tmp_path), inputs={})


# ---------------------------------------------------------------------------
# AC10 — max_turns forwarded to agent (H-1.5-006)
# ---------------------------------------------------------------------------


async def test_max_turns_passed_to_agent(tmp_path: Path) -> None:
    """AINode forwards step.max_turns to agent.execute so the SDK can cap
    the number of model turns in a single node invocation."""
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = _CompliantMockAgent()
    node = AINode(agent=agent, prompts_dir=prompts)

    await node.execute(step=_step(max_turns=5), state=_state(tmp_path), inputs={})

    assert agent.calls[0].max_turns == 5


async def test_max_turns_none_by_default_passes_through(tmp_path: Path) -> None:
    """When max_turns is absent (None), AINode passes None to the agent so
    the SDK uses its own default behaviour."""
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = _CompliantMockAgent()
    node = AINode(agent=agent, prompts_dir=prompts)

    await node.execute(step=_step(), state=_state(tmp_path), inputs={})

    assert agent.calls[0].max_turns is None


# ---------------------------------------------------------------------------
# session_key forwarded to agent based on step.persist_session
# ---------------------------------------------------------------------------


async def test_persist_session_forwards_step_id_as_session_key(tmp_path: Path) -> None:
    """A step with persist_session=True makes AINode pass step.id as the
    agent's session_key so the conversation resumes across re-executions."""
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = _CompliantMockAgent()
    node = AINode(agent=agent, prompts_dir=prompts)

    await node.execute(
        step=_step(id="implement", persist_session=True),
        state=_state(tmp_path),
        inputs={},
    )

    assert agent.calls[0].session_key == "implement"


async def test_no_persist_session_passes_none_session_key(tmp_path: Path) -> None:
    """Without persist_session (the default, e.g. the review step) AINode passes
    session_key=None so the agent runs fresh each call."""
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, "p.j2", "go\n")
    agent = _CompliantMockAgent()
    node = AINode(agent=agent, prompts_dir=prompts)

    await node.execute(
        step=_step(id="review", persist_session=False),
        state=_state(tmp_path),
        inputs={},
    )

    assert agent.calls[0].session_key is None
