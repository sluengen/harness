"""Tests for harness.dispatch.base + harness.dispatch.mock — see SPEC §4.7.

The Agent protocol is the dialect-agnostic surface every adapter (Claude,
codex, opencode) implements. MockAgent is the in-process double used by
engine/executor tests so they don't need a live agent harness.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from harness.dispatch.base import Agent
from harness.dispatch.mock import MockAgent
from harness.nodes.base import Attestation, NodeResult

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _SampleContract(BaseModel):
    summary: str = "ok"


def _result(summary: str = "ok") -> NodeResult[BaseModel]:
    return NodeResult[BaseModel](
        contract=_SampleContract(summary=summary),
        attestation=Attestation(status="complete"),
    )


_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


# ---------------------------------------------------------------------------
# Protocol structural typing
# ---------------------------------------------------------------------------


def test_mock_agent_is_structurally_an_agent() -> None:
    mock = MockAgent()
    assert isinstance(mock, Agent)


def test_object_without_execute_is_not_an_agent() -> None:
    class NotAnAgent:
        pass

    assert not isinstance(NotAnAgent(), Agent)


def test_external_class_satisfying_protocol_is_an_agent() -> None:
    """A class that doesn't inherit Agent but matches its shape passes isinstance."""

    class Adapter:
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
            return _result()

    assert isinstance(Adapter(), Agent)


def test_agent_protocol_cannot_be_instantiated_as_concrete_class() -> None:
    """Calling Agent() and using it as a working agent must not succeed.

    Protocol classes are not designed for direct instantiation. Either
    instantiation raises, or the produced object has no working `execute`.
    Either way, callers must implement the protocol; they cannot rent it.
    """
    try:
        instance = Agent()  # type: ignore[abstract]
    except TypeError:
        return  # Acceptable: instantiation refused outright.

    # If instantiation didn't raise, calling execute must not yield a NodeResult.
    with pytest.raises((TypeError, NotImplementedError, AttributeError)):
        # Synchronous call; we never even await it, because it shouldn't be callable.
        coro = instance.execute(  # type: ignore[call-arg]
            "p",
            _SampleContract,
            _SCHEMA,
            allowed_tools=[],
            cwd=None,
        )
        # If by chance a coroutine was produced, close it to avoid RuntimeWarning.
        if hasattr(coro, "close"):
            coro.close()
        raise TypeError("Agent() produced a usable instance — it should not.")


# ---------------------------------------------------------------------------
# MockAgent.execute — default behaviour
# ---------------------------------------------------------------------------


async def test_execute_returns_default_result_when_supplied() -> None:
    expected = _result("from-default")
    mock = MockAgent(default_result=expected)

    actual = await mock.execute(
        "the prompt",
        _SampleContract,
        _SCHEMA,
        allowed_tools=["Read"],
        cwd=None,
    )

    assert actual is expected


async def test_execute_synthesises_default_when_none_provided() -> None:
    """A MockAgent created with no arguments must still return a usable NodeResult."""
    mock = MockAgent()

    result = await mock.execute(
        "p",
        _SampleContract,
        _SCHEMA,
        allowed_tools=[],
        cwd=None,
    )

    assert isinstance(result, NodeResult)
    assert result.attestation.status == "complete"


# ---------------------------------------------------------------------------
# MockAgent.execute — call recording
# ---------------------------------------------------------------------------


async def test_execute_records_every_call_argument() -> None:
    mock = MockAgent(default_result=_result())
    cwd = Path("/tmp/work")

    await mock.execute(
        "the prompt",
        _SampleContract,
        _SCHEMA,
        allowed_tools=["Read", "Write"],
        cwd=cwd,
        timeout_s=120,
        stall_timeout_s=60,
    )

    assert len(mock.calls) == 1
    call = mock.calls[0]
    assert call.prompt == "the prompt"
    assert call.contract is _SampleContract
    assert call.submit_tool_schema == _SCHEMA
    assert call.allowed_tools == ["Read", "Write"]
    assert call.cwd == cwd
    assert call.timeout_s == 120
    assert call.stall_timeout_s == 60


async def test_execute_uses_protocol_defaults_for_timeouts() -> None:
    mock = MockAgent(default_result=_result())

    await mock.execute(
        "p",
        _SampleContract,
        _SCHEMA,
        allowed_tools=[],
        cwd=None,
    )

    call = mock.calls[0]
    assert call.timeout_s == 600
    assert call.stall_timeout_s == 300


async def test_execute_records_multiple_calls_in_order() -> None:
    mock = MockAgent(default_result=_result())

    await mock.execute("first", _SampleContract, _SCHEMA, allowed_tools=[], cwd=None)
    await mock.execute("second", _SampleContract, _SCHEMA, allowed_tools=[], cwd=None)
    await mock.execute("third", _SampleContract, _SCHEMA, allowed_tools=[], cwd=None)

    assert [c.prompt for c in mock.calls] == ["first", "second", "third"]


# ---------------------------------------------------------------------------
# MockAgent.set_next — queued return values
# ---------------------------------------------------------------------------


async def test_set_next_overrides_default_for_next_call() -> None:
    default = _result("default")
    queued = _result("queued")
    mock = MockAgent(default_result=default)
    mock.set_next(queued)

    first = await mock.execute("a", _SampleContract, _SCHEMA, allowed_tools=[], cwd=None)
    second = await mock.execute("b", _SampleContract, _SCHEMA, allowed_tools=[], cwd=None)

    assert first is queued
    assert second is default


async def test_set_next_supports_multiple_queued_results() -> None:
    default = _result("default")
    one = _result("one")
    two = _result("two")
    mock = MockAgent(default_result=default)
    mock.set_next(one)
    mock.set_next(two)

    a = await mock.execute("a", _SampleContract, _SCHEMA, allowed_tools=[], cwd=None)
    b = await mock.execute("b", _SampleContract, _SCHEMA, allowed_tools=[], cwd=None)
    c = await mock.execute("c", _SampleContract, _SCHEMA, allowed_tools=[], cwd=None)

    assert a is one
    assert b is two
    assert c is default


# ---------------------------------------------------------------------------
# MockAgent — error injection
# ---------------------------------------------------------------------------


async def test_error_argument_causes_execute_to_raise() -> None:
    boom = RuntimeError("simulated harness failure")
    mock = MockAgent(error=boom)

    with pytest.raises(RuntimeError, match="simulated harness failure"):
        await mock.execute("p", _SampleContract, _SCHEMA, allowed_tools=[], cwd=None)


async def test_error_is_recorded_before_raising() -> None:
    """Tests can assert the agent was invoked with the expected args even when it failed."""
    mock = MockAgent(error=ValueError("nope"))

    with pytest.raises(ValueError):
        await mock.execute(
            "the prompt",
            _SampleContract,
            _SCHEMA,
            allowed_tools=["Read"],
            cwd=Path("/tmp/x"),
        )

    assert len(mock.calls) == 1
    assert mock.calls[0].prompt == "the prompt"
    assert mock.calls[0].allowed_tools == ["Read"]
