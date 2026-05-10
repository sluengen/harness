"""Tests for harness.engine.retry — three-layer retry per SPEC §10.

The retry module is a pure async wrapper around an awaitable. Layers:

- Transient (3 attempts, exponential backoff capped) — OSError + family,
  ``anthropic.APIStatusError`` 5xx, ``anthropic.APIConnectionError``,
  ``httpx.TimeoutException``.
- Contract violation (2 attempts, no backoff, stricter-prompt hint via
  ``RetryContext.contract_violation_reason``) — ``ContractViolation`` and
  ``AgentStalled`` (per SPEC §10 stall section).
- Logic-failure layer is intentionally absent — handled by the ``loop``
  block in the workflow language, not by this module.

AC mapping is inline on each test.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from anthropic import APIConnectionError, APIStatusError

from harness.dispatch.claude import AgentStalled, ContractViolation
from harness.engine.retry import (
    RetryContext,
    RetryPolicy,
    run_with_retry,
)
from harness.events.schema import EventType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sleep_recorder() -> tuple[list[float], Callable[[float], Awaitable[None]]]:
    """Return ``(recorded, fake_sleep)`` — fake_sleep records args, never blocks."""
    recorded: list[float] = []

    async def fake_sleep(delay: float) -> None:
        recorded.append(delay)

    return recorded, fake_sleep


def _make_event_recorder() -> tuple[
    list[tuple[EventType, dict[str, Any]]],
    Callable[[EventType, dict[str, Any]], None],
]:
    """Return ``(recorded, sink)`` — sink appends each (type, payload) tuple."""
    recorded: list[tuple[EventType, dict[str, Any]]] = []

    def sink(event_type: EventType, data: dict[str, Any]) -> None:
        recorded.append((event_type, data))

    return recorded, sink


def _make_anthropic_status_error(status: int) -> APIStatusError:
    """Construct an ``APIStatusError`` with a synthetic ``httpx.Response``.

    The real SDK builds these from a live response; tests need a minimal
    stand-in that satisfies the constructor's ``response: httpx.Response``
    parameter and exposes ``.status_code``.
    """
    request = httpx.Request("GET", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code=status, request=request)
    # The base ``APIStatusError.__init__`` requires status_code to derive from
    # the response; assign explicitly so subclasses don't shadow it.
    err = APIStatusError(f"status {status}", response=response, body=None)
    return err


# ---------------------------------------------------------------------------
# AC1 — RetryPolicy defaults match SPEC §10
# ---------------------------------------------------------------------------


def test_ac1_v1_default_returns_spec_baked_defaults() -> None:
    """``RetryPolicy.v1_default()`` has the SPEC §10 baked-in numbers."""
    policy = RetryPolicy.v1_default()
    assert policy.transient_attempts == 3
    assert policy.contract_violation_attempts == 2


def test_ac1_retry_policy_is_frozen_dataclass() -> None:
    """RetryPolicy is immutable — defaults are non-configurable in v1."""
    policy = RetryPolicy.v1_default()
    with pytest.raises((AttributeError, Exception)):
        policy.transient_attempts = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AC2 — Happy path: success on first try
# ---------------------------------------------------------------------------


async def test_ac2_first_try_success_returns_value_no_events() -> None:
    """Operation succeeds on attempt 1 → no retries, no events."""
    sleeps, fake_sleep = _make_sleep_recorder()
    events, sink = _make_event_recorder()

    async def op(ctx: RetryContext) -> str:
        return "ok"

    result = await run_with_retry(op, event_sink=sink, sleep=fake_sleep)

    assert result == "ok"
    assert events == []
    assert sleeps == []


# ---------------------------------------------------------------------------
# AC3 — One transient failure then success
# ---------------------------------------------------------------------------


async def test_ac3_transient_then_success_emits_one_retry_event() -> None:
    """ConnectionError once → 1 retry, event reason=transient, attempt=2."""
    sleeps, fake_sleep = _make_sleep_recorder()
    events, sink = _make_event_recorder()
    calls = 0

    async def op(ctx: RetryContext) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("blip")
        return "ok"

    result = await run_with_retry(op, event_sink=sink, sleep=fake_sleep)

    assert result == "ok"
    assert calls == 2
    assert len(events) == 1
    event_type, payload = events[0]
    assert event_type == "retry_attempted"
    assert payload == {"attempt": 2, "reason": "transient", "delay_s": 1.0}
    assert sleeps == [1.0]


# ---------------------------------------------------------------------------
# AC4 — All transient exception classes are classified as transient
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        OSError("os blip"),
        TimeoutError("t/o"),
        ConnectionError("conn"),
    ],
    ids=["OSError", "TimeoutError", "ConnectionError"],
)
async def test_ac4_oserror_family_is_transient(exc: BaseException) -> None:
    """OSError + descendants (TimeoutError, ConnectionError) → transient layer."""
    sleeps, fake_sleep = _make_sleep_recorder()
    events, sink = _make_event_recorder()
    calls = 0

    async def op(ctx: RetryContext) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise exc
        return "ok"

    result = await run_with_retry(op, event_sink=sink, sleep=fake_sleep)

    assert result == "ok"
    assert calls == 2
    assert events[0][1]["reason"] == "transient"


# ---------------------------------------------------------------------------
# AC5 — Exponential backoff schedule
# ---------------------------------------------------------------------------


async def test_ac5_transient_exponential_schedule_three_attempts() -> None:
    """Three transient failures → operation called 3x, sleeps [1.0, 2.0]."""
    sleeps, fake_sleep = _make_sleep_recorder()
    events, sink = _make_event_recorder()
    calls = 0
    err = ConnectionError("persistent")

    async def op(ctx: RetryContext) -> str:
        nonlocal calls
        calls += 1
        raise err

    with pytest.raises(ConnectionError) as exc_info:
        await run_with_retry(op, event_sink=sink, sleep=fake_sleep)

    assert exc_info.value is err
    assert calls == 3
    assert sleeps == [1.0, 2.0]
    # Two retry events: attempt 2 (delay 1.0) and attempt 3 (delay 2.0).
    assert [e[1]["attempt"] for e in events] == [2, 3]
    assert [e[1]["delay_s"] for e in events] == [1.0, 2.0]


# ---------------------------------------------------------------------------
# AC6 — Backoff cap respected
# ---------------------------------------------------------------------------


async def test_ac6_transient_max_delay_caps_backoff() -> None:
    """With base=1.0 and cap=1.5, the third sleep would be 4.0 → capped to 1.5."""
    sleeps, fake_sleep = _make_sleep_recorder()
    events, sink = _make_event_recorder()
    policy = RetryPolicy(
        transient_attempts=4,
        transient_base_delay_s=1.0,
        transient_max_delay_s=1.5,
        contract_violation_attempts=2,
    )
    calls = 0

    async def op(ctx: RetryContext) -> str:
        nonlocal calls
        calls += 1
        raise ConnectionError("p")

    with pytest.raises(ConnectionError):
        await run_with_retry(op, policy=policy, event_sink=sink, sleep=fake_sleep)

    assert calls == 4
    # Schedule pre-cap would be: 1.0, 2.0, 4.0. Cap 1.5 → 1.0, 1.5, 1.5.
    assert sleeps == [1.0, 1.5, 1.5]


# ---------------------------------------------------------------------------
# AC7 — ContractViolation retry; reason hint passed through
# ---------------------------------------------------------------------------


async def test_ac7_contract_violation_then_success() -> None:
    """ContractViolation('validation_failed') once → 1 retry, hint propagated."""
    sleeps, fake_sleep = _make_sleep_recorder()
    events, sink = _make_event_recorder()
    contexts: list[RetryContext] = []

    async def op(ctx: RetryContext) -> str:
        contexts.append(ctx)
        if ctx.attempt == 1:
            raise ContractViolation("validation_failed")
        return "ok"

    result = await run_with_retry(op, event_sink=sink, sleep=fake_sleep)

    assert result == "ok"
    assert len(contexts) == 2
    assert contexts[0].attempt == 1
    assert contexts[0].reason is None
    assert contexts[0].contract_violation_reason is None
    assert contexts[1].attempt == 2
    assert contexts[1].reason == "contract_violation"
    assert contexts[1].contract_violation_reason == "validation_failed"
    assert events == [
        ("retry_attempted", {"attempt": 2, "reason": "contract_violation", "delay_s": 0.0})
    ]


# ---------------------------------------------------------------------------
# AC8 — AgentStalled uses contract-violation budget but emits reason="stalled"
# ---------------------------------------------------------------------------


async def test_ac8_agent_stalled_then_success_emits_stalled_reason() -> None:
    """AgentStalled is retried under contract-violation budget but events
    distinguish via reason="stalled". Hint passes "stalled" string.
    """
    sleeps, fake_sleep = _make_sleep_recorder()
    events, sink = _make_event_recorder()
    contexts: list[RetryContext] = []

    async def op(ctx: RetryContext) -> str:
        contexts.append(ctx)
        if ctx.attempt == 1:
            raise AgentStalled(elapsed=12.5)
        return "ok"

    result = await run_with_retry(op, event_sink=sink, sleep=fake_sleep)

    assert result == "ok"
    assert contexts[1].reason == "stalled"
    assert contexts[1].contract_violation_reason == "stalled"
    assert events == [
        ("retry_attempted", {"attempt": 2, "reason": "stalled", "delay_s": 0.0})
    ]


# ---------------------------------------------------------------------------
# AC9 — Contract-violation retries do not sleep
# ---------------------------------------------------------------------------


async def test_ac9_contract_violation_does_not_sleep() -> None:
    """ContractViolation retries call operation again immediately — no sleep."""
    sleeps, fake_sleep = _make_sleep_recorder()
    events, sink = _make_event_recorder()
    calls = 0

    async def op(ctx: RetryContext) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ContractViolation("validation_failed")
        return "ok"

    await run_with_retry(op, event_sink=sink, sleep=fake_sleep)

    assert sleeps == []  # no sleep call at all on the contract-violation path


# ---------------------------------------------------------------------------
# AC10 — Transient budget exhausted re-raises original
# ---------------------------------------------------------------------------


async def test_ac10_transient_budget_exhausted_reraises_original() -> None:
    """After 3 transient failures, the LAST exception is re-raised unchanged."""
    sleeps, fake_sleep = _make_sleep_recorder()
    events, sink = _make_event_recorder()
    last_err: ConnectionError | None = None
    counter = 0

    async def op(ctx: RetryContext) -> str:
        nonlocal last_err, counter
        counter += 1
        last_err = ConnectionError(f"call {counter}")
        raise last_err

    with pytest.raises(ConnectionError) as exc_info:
        await run_with_retry(op, event_sink=sink, sleep=fake_sleep)

    assert exc_info.value is last_err
    assert counter == 3


# ---------------------------------------------------------------------------
# AC11 — ContractViolation budget exhausted re-raises original
# ---------------------------------------------------------------------------


async def test_ac11_contract_violation_budget_exhausted_reraises_original() -> None:
    """After 2 ContractViolation failures, the LAST instance is re-raised."""
    sleeps, fake_sleep = _make_sleep_recorder()
    events, sink = _make_event_recorder()
    last_err: ContractViolation | None = None
    counter = 0

    async def op(ctx: RetryContext) -> str:
        nonlocal last_err, counter
        counter += 1
        last_err = ContractViolation("validation_failed")
        raise last_err

    with pytest.raises(ContractViolation) as exc_info:
        await run_with_retry(op, event_sink=sink, sleep=fake_sleep)

    assert exc_info.value is last_err
    assert counter == 2


# ---------------------------------------------------------------------------
# AC12 — Non-transient, non-contract-violation re-raises immediately
# ---------------------------------------------------------------------------


async def test_ac12_runtimeerror_does_not_retry() -> None:
    """Generic exceptions are re-raised on first failure: 1 call, 0 events."""
    sleeps, fake_sleep = _make_sleep_recorder()
    events, sink = _make_event_recorder()
    calls = 0

    async def op(ctx: RetryContext) -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("oops")

    with pytest.raises(RuntimeError, match="oops"):
        await run_with_retry(op, event_sink=sink, sleep=fake_sleep)

    assert calls == 1
    assert events == []
    assert sleeps == []


# ---------------------------------------------------------------------------
# AC13 — Layers do NOT compound: separate counters per layer
# ---------------------------------------------------------------------------


async def test_ac13_layers_do_not_compound() -> None:
    """ContractViolation then ConnectionError → both retried, distinct events.

    Sequence:
      1. raises ContractViolation('validation_failed') → contract budget retry
      2. raises ConnectionError → transient retry (own budget, not exhausted)
      3. succeeds.
    Two retry events: contract_violation, transient. Operation called 3 times.
    """
    sleeps, fake_sleep = _make_sleep_recorder()
    events, sink = _make_event_recorder()
    calls = 0

    async def op(ctx: RetryContext) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ContractViolation("validation_failed")
        if calls == 2:
            raise ConnectionError("blip")
        return "ok"

    result = await run_with_retry(op, event_sink=sink, sleep=fake_sleep)

    assert result == "ok"
    assert calls == 3
    assert [e[1]["reason"] for e in events] == ["contract_violation", "transient"]


# ---------------------------------------------------------------------------
# AC14 — event_sink=None still retries correctly
# ---------------------------------------------------------------------------


async def test_ac14_event_sink_none_still_retries() -> None:
    """Without an event sink, transient retries still work."""
    sleeps, fake_sleep = _make_sleep_recorder()
    calls = 0

    async def op(ctx: RetryContext) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("blip")
        return "ok"

    result = await run_with_retry(op, event_sink=None, sleep=fake_sleep)

    assert result == "ok"
    assert calls == 2
    assert sleeps == [1.0]


# ---------------------------------------------------------------------------
# AC15 — anthropic.APIStatusError 5xx is transient; 4xx is not
# ---------------------------------------------------------------------------


async def test_ac15_anthropic_status_500_is_transient() -> None:
    """APIStatusError with status_code=500 → retried under transient layer."""
    sleeps, fake_sleep = _make_sleep_recorder()
    events, sink = _make_event_recorder()
    calls = 0

    async def op(ctx: RetryContext) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _make_anthropic_status_error(500)
        return "ok"

    result = await run_with_retry(op, event_sink=sink, sleep=fake_sleep)

    assert result == "ok"
    assert calls == 2
    assert events[0][1]["reason"] == "transient"


async def test_ac15_anthropic_status_404_is_not_transient() -> None:
    """APIStatusError with status_code=404 → re-raised on first failure."""
    sleeps, fake_sleep = _make_sleep_recorder()
    events, sink = _make_event_recorder()
    calls = 0

    async def op(ctx: RetryContext) -> str:
        nonlocal calls
        calls += 1
        raise _make_anthropic_status_error(404)

    with pytest.raises(APIStatusError):
        await run_with_retry(op, event_sink=sink, sleep=fake_sleep)

    assert calls == 1
    assert events == []


async def test_ac15_anthropic_api_connection_error_is_transient() -> None:
    """APIConnectionError → retried under transient layer."""
    sleeps, fake_sleep = _make_sleep_recorder()
    events, sink = _make_event_recorder()
    calls = 0
    request = httpx.Request("GET", "https://api.anthropic.com/v1/messages")

    async def op(ctx: RetryContext) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise APIConnectionError(request=request)
        return "ok"

    result = await run_with_retry(op, event_sink=sink, sleep=fake_sleep)

    assert result == "ok"
    assert events[0][1]["reason"] == "transient"


async def test_ac15_httpx_timeout_exception_is_transient() -> None:
    """httpx.TimeoutException → retried under transient layer."""
    sleeps, fake_sleep = _make_sleep_recorder()
    events, sink = _make_event_recorder()
    calls = 0

    async def op(ctx: RetryContext) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.TimeoutException("read timeout")
        return "ok"

    result = await run_with_retry(op, event_sink=sink, sleep=fake_sleep)

    assert result == "ok"
    assert events[0][1]["reason"] == "transient"


# ---------------------------------------------------------------------------
# AC16 — RetryContext shape is what operation receives
# ---------------------------------------------------------------------------


async def test_ac16_retry_context_shape_per_attempt() -> None:
    """attempt 1 has reason=None; attempt 2 has reason matching the failure layer."""
    sleeps, fake_sleep = _make_sleep_recorder()
    contexts: list[RetryContext] = []

    async def op(ctx: RetryContext) -> str:
        contexts.append(ctx)
        if ctx.attempt == 1:
            raise ConnectionError("blip")
        return "ok"

    await run_with_retry(op, sleep=fake_sleep)

    assert len(contexts) == 2
    assert contexts[0] == RetryContext(attempt=1, reason=None, contract_violation_reason=None)
    assert contexts[1].attempt == 2
    assert contexts[1].reason == "transient"
    assert contexts[1].contract_violation_reason is None


# ---------------------------------------------------------------------------
# AC17 — event_sink callable signature is (EventType, dict)
# ---------------------------------------------------------------------------


async def test_ac17_event_sink_signature_is_eventtype_and_dict() -> None:
    """Sink is invoked with (event_type, payload_dict) — recorded as a tuple."""
    sleeps, fake_sleep = _make_sleep_recorder()
    captured: list[tuple[EventType, dict[str, Any]]] = []

    def sink(event_type: EventType, data: dict[str, Any]) -> None:
        captured.append((event_type, data))

    async def op(ctx: RetryContext) -> str:
        if ctx.attempt == 1:
            raise ConnectionError("blip")
        return "ok"

    await run_with_retry(op, event_sink=sink, sleep=fake_sleep)

    assert len(captured) == 1
    event_type, payload = captured[0]
    assert event_type == "retry_attempted"
    assert isinstance(payload, dict)
    assert set(payload.keys()) == {"attempt", "reason", "delay_s"}
