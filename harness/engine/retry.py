"""Three-layer retry policies (non-configurable in v1) — see SPEC §10.

This module is a pure async wrapper around an awaitable. The runner / executor
(H-021 / H-007 — separate tickets) will use ``run_with_retry`` to wrap each
node call. Nothing in this module mutates run state; the only side effect is
an optional ``retry_attempted`` event emitted via the supplied sink.

Three layers per SPEC §10:

- **Transient** — provider 5xx, network timeout — 3 attempts, exponential backoff.
- **Contract violation** — LLM output failed Pydantic validation — 2 attempts
  with stricter system message.
- **Logic failure** — test/check returned fail — none; handled by ``loop`` block.

Layers never compound silently — each tracks its own attempt counter. A
transient retry that then hits a ``ContractViolation`` does not get the
contract-violation budget on top, and vice versa. SPEC §10's stall section
is wired here too: ``AgentStalled`` shares the contract-violation budget
(stricter prompting) but emits its own event reason ``"stalled"`` so log
queries can distinguish stall-driven retries from payload-driven ones.

The ``transient_*`` defaults are baked in. Per SPEC: "Non-configurable in v1.
… This keeps the schema lean and forces real failure data before we add
tuning surface." The dataclass exposes constructor args so tests can
exercise the cap-clamping branch — production code uses ``v1_default()``.

Lazy SDK detection: ``anthropic`` and ``httpx`` are imported eagerly inside
``_collect_transient_classes`` but each guarded with try/except ImportError
so the module loads cleanly without the optional deps (the corresponding
exception types simply won't match at dispatch time).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from harness.dispatch.claude import AgentStalled, ContractViolation
from harness.events.schema import EventType

# --------------------------------------------------------------------------- #
# Public types
# --------------------------------------------------------------------------- #

RetryReason = Literal["transient", "contract_violation", "stalled"]
"""Discriminator emitted in ``retry_attempted`` event payloads."""


@dataclass(frozen=True)
class RetryPolicy:
    """v1 fixed retry policy — see SPEC §10. Non-configurable on purpose.

    Attributes:
        transient_attempts: Total attempts (including the first call) for the
            transient layer. Default 3 per SPEC §10.
        transient_base_delay_s: Base seconds for exponential backoff. Delay
            before attempt N is ``min(base * 2**(N-2), max_delay_s)``.
        transient_max_delay_s: Cap for backoff so a 3rd attempt isn't 60s on
            a misconfigured base.
        contract_violation_attempts: Total attempts for the contract-violation
            layer (which also covers ``AgentStalled``). Default 2 per SPEC §10.
    """

    transient_attempts: int = 3
    transient_base_delay_s: float = 1.0
    transient_max_delay_s: float = 30.0
    contract_violation_attempts: int = 2

    @classmethod
    def v1_default(cls) -> RetryPolicy:
        """Return the SPEC §10 defaults frozen as the v1 policy."""
        return cls()


@dataclass(frozen=True)
class RetryContext:
    """Per-attempt context passed to the wrapped operation.

    Lets the operation adapt its dispatch — e.g. a contract-violation retry
    can prepend a stricter system message based on
    ``contract_violation_reason``. Pass-through, not magical: the retry
    module never reads the operation's prompt.

    Attributes:
        attempt: 1-indexed attempt number. ``1`` on the first call,
            ``2`` after the first retry, etc.
        reason: ``None`` on the first call. On retries, the layer label of
            the *previous* failure: ``"transient"`` | ``"contract_violation"``
            | ``"stalled"``.
        contract_violation_reason: Carried only on contract-violation-layer
            retries. For ``ContractViolation``, the SPEC §4.4 ``reason``
            discriminator (``not_called`` | ``placeholder`` |
            ``validation_failed``). For ``AgentStalled``, the literal string
            ``"stalled"``. ``None`` on the first call and on transient retries.
    """

    attempt: int
    reason: RetryReason | None
    contract_violation_reason: str | None = None


T = TypeVar("T")
Operation = Callable[[RetryContext], Awaitable[T]]
"""Signature of the operation passed to ``run_with_retry``.

Receives a fresh ``RetryContext`` per attempt, returns an awaitable of any
type. The retry module is generic in ``T`` and re-raises whatever exception
the operation raised once budget is exhausted.
"""


# --------------------------------------------------------------------------- #
# Transient-class detection (lazy)
# --------------------------------------------------------------------------- #


def _collect_transient_classes() -> tuple[type[BaseException], ...]:
    """Build the tuple of transient-by-isinstance exception classes.

    ``OSError`` covers ``ConnectionError`` and (Python 3.11+) ``TimeoutError``
    and ``asyncio.TimeoutError`` (which is an alias for ``TimeoutError``).
    The optional SDK classes are added only if importable so this module
    loads cleanly without ``anthropic`` / ``httpx`` installed.

    ``anthropic.APIStatusError`` is intentionally NOT placed here — not all
    instances are transient (4xx isn't). It's handled by ``_is_transient``
    via a runtime ``status_code`` check.
    """
    classes: list[type[BaseException]] = [OSError]
    try:
        import anthropic

        classes.append(anthropic.APIConnectionError)
    except ImportError:  # pragma: no cover - exercised only without anthropic
        pass
    try:
        import httpx

        classes.append(httpx.TimeoutException)
    except ImportError:  # pragma: no cover - exercised only without httpx
        pass
    return tuple(classes)


_TRANSIENT_CLASSES: tuple[type[BaseException], ...] = _collect_transient_classes()


def _is_transient(exc: BaseException) -> bool:
    """Return True iff ``exc`` belongs to the transient retry layer.

    Checks the cheap isinstance tuple first, then falls back to a runtime
    ``status_code >= 500`` check for ``anthropic.APIStatusError`` (since 4xx
    is not transient and we can't pre-bake that distinction into a tuple).
    """
    if isinstance(exc, _TRANSIENT_CLASSES):
        return True
    try:
        from anthropic import APIStatusError
    except ImportError:  # pragma: no cover - exercised only without anthropic
        return False
    if isinstance(exc, APIStatusError):
        # ``status_code`` is set by the base APIStatusError __init__.
        status = getattr(exc, "status_code", None)
        return isinstance(status, int) and status >= 500
    return False


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


def _transient_delay_s(policy: RetryPolicy, next_attempt: int) -> float:
    """Backoff before ``next_attempt`` (1-indexed). Attempt 1 → 0 (no sleep)."""
    if next_attempt <= 1:
        return 0.0
    raw: float = policy.transient_base_delay_s * (2 ** (next_attempt - 2))
    return float(min(raw, policy.transient_max_delay_s))


async def run_with_retry(
    operation: Operation[T],
    *,
    policy: RetryPolicy | None = None,
    event_sink: Callable[[EventType, dict[str, Any]], None] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Run ``operation`` with the SPEC §10 three-layer retry policy.

    Layers in precedence order on a single attempt:

    - **Transient** (``OSError`` + family, ``anthropic.APIStatusError`` 5xx,
      ``anthropic.APIConnectionError``, ``httpx.TimeoutException``):
      up to ``policy.transient_attempts`` attempts with exponential backoff
      (``base_delay_s * 2**(attempt-2)`` capped at ``max_delay_s``).
    - **Contract violation** (``ContractViolation`` and ``AgentStalled``):
      up to ``policy.contract_violation_attempts`` attempts with the SPEC's
      "stricter system message" hint passed via
      ``RetryContext.contract_violation_reason``. No backoff — retried
      immediately.
    - **Anything else** is re-raised unchanged on first failure. No silent
      compounding.

    Layers do **not** compound: a transient retry that then hits a
    ``ContractViolation`` does not get the contract-violation budget on top.
    Each layer counts its attempts independently.

    Each retry emits a ``retry_attempted`` event to ``event_sink`` (if
    provided) BEFORE the next attempt: ``{"attempt": next_attempt,
    "reason": <RetryReason>, "delay_s": <float>}``. The first attempt does
    not emit (it's the original try, not a retry). For ``AgentStalled``,
    ``reason`` is ``"stalled"`` (distinct from ``"contract_violation"``)
    so log queries can tell them apart.

    Args:
        operation: An async callable taking a :class:`RetryContext` and
            returning ``T``.
        policy: The retry policy. Defaults to :meth:`RetryPolicy.v1_default`.
        event_sink: Optional ``(EventType, dict) -> None`` sink.
        sleep: Async sleep function. Defaults to :func:`asyncio.sleep`.
            Tests can pass a recorder to assert on the schedule without
            actually waiting.

    Returns:
        The first successful result from ``operation``.

    Raises:
        Whatever ``operation`` raises after the relevant budget is
        exhausted, re-raised unchanged so the caller sees the original type.
    """
    pol = policy if policy is not None else RetryPolicy.v1_default()

    transient_used = 0
    contract_used = 0
    last_reason: RetryReason | None = None
    last_hint: str | None = None
    attempt = 1

    while True:
        ctx = RetryContext(
            attempt=attempt,
            reason=last_reason,
            contract_violation_reason=last_hint,
        )
        try:
            return await operation(ctx)
        except ContractViolation as e:
            contract_used += 1
            if contract_used >= pol.contract_violation_attempts:
                raise
            next_reason: RetryReason = "contract_violation"
            next_hint: str | None = e.reason
            delay = 0.0
        except AgentStalled:
            contract_used += 1
            if contract_used >= pol.contract_violation_attempts:
                raise
            next_reason = "stalled"
            next_hint = "stalled"
            delay = 0.0
        except BaseException as e:
            if not _is_transient(e):
                raise
            transient_used += 1
            if transient_used >= pol.transient_attempts:
                raise
            attempt += 1
            delay = _transient_delay_s(pol, attempt)
            if event_sink is not None:
                event_sink(
                    "retry_attempted",
                    {"attempt": attempt, "reason": "transient", "delay_s": delay},
                )
            await sleep(delay)
            last_reason = "transient"
            last_hint = None
            continue

        # Contract-violation / stalled path: emit, advance attempt, no sleep.
        attempt += 1
        if event_sink is not None:
            event_sink(
                "retry_attempted",
                {"attempt": attempt, "reason": next_reason, "delay_s": delay},
            )
        last_reason = next_reason
        last_hint = next_hint
