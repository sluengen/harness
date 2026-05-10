"""Per-node execution + contract validation — see SPEC §4.2.

Responsibilities (per SPEC §4.2):

1. Resolve ``depends_on`` against state (raises :class:`DependencyNotSatisfied`
   when a referenced field is unset / ``None``).
2. Dispatch to the matching node by ``step.type`` via the registry on
   :class:`Context`.
3. Wrap the node call with :func:`harness.engine.retry.run_with_retry`.
   ``retry_attempted`` events are buffered during the call and flushed to
   the event log between ``node_started`` and the terminal node event.
4. Validate the result's contract against ``ctx.contracts[step.id]``. A
   missing entry (when ``writes:`` is non-empty), a runtime-type
   mismatch, or a ``writes:`` field name that doesn't exist on the
   contract all surface as :class:`ContractMismatch`.
5. Extract only the declared ``writes:`` fields and call
   :func:`harness.state.store.update_state` — the executor is the only
   writer of state.
6. Emit ``node_started`` before dispatch, ``node_completed`` on success,
   or ``node_failed`` (carrying the exception's class name) on any
   exception, then re-raise.

The runner (H-022) constructs a :class:`Context` per workflow run and
calls :meth:`Executor.execute` once per step. Loop blocks (H-021) are the
runner's responsibility — the executor never sees them.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from harness.engine.retry import RetryContext, RetryPolicy, run_with_retry
from harness.events.emitter import EventEmitter
from harness.events.schema import EventType
from harness.nodes.base import NodeResult
from harness.state.schema import BaseState
from harness.state.store import read_state, update_state
from harness.workflow.schema import Step

__all__ = [
    "ContractMismatch",
    "Context",
    "DependencyNotSatisfied",
    "Executor",
    "NodeRunner",
]


# A node adapter: ``async def(step, state, ctx) -> NodeResult``. The runner
# (H-022) builds these by binding each Node implementation's keyword-only
# execute() to this uniform call shape; the executor itself doesn't import
# the Node classes so this module stays independent of dispatch backends.
NodeRunner = Callable[
    [Step, BaseState, "Context"], Awaitable[NodeResult[BaseModel]]
]


class DependencyNotSatisfied(Exception):  # noqa: N818 — SPEC vocabulary
    """A step's ``depends_on`` referenced a state field that was unset / None."""


class ContractMismatch(Exception):  # noqa: N818 — SPEC vocabulary
    """The runtime contract doesn't match the step's declared contract.

    Three failure modes share this type:

    * ``ctx.contracts`` has no entry for ``step.id`` but the step
      declares ``writes:``.
    * The :class:`NodeResult.contract` is not an instance of the type
      declared on ``ctx.contracts[step.id]``.
    * A name in ``step.writes`` does not exist as a field on the
      contract.

    All three are surfaced at the same boundary; the loader (H-008) catches
    the third class at load-time too, but the executor still validates
    defensively in case the runner is invoked with hand-built contexts.
    """


@dataclass(frozen=True)
class Context:
    """Per-run execution context handed to every :meth:`Executor.execute` call.

    Attributes:
        run_id: ULID of the active run; used for state reads/writes and
            event emission.
        db_path: Path to the SQLite store.
        contracts: ``step.id`` → compiled Pydantic contract type. Built by
            :func:`harness.workflow.loader.load_workflow`. Only steps that
            declared a ``contract:`` appear here.
        state_schema: The workflow-derived state class (H-009). Used by
            :func:`harness.state.store.read_state` /
            :func:`harness.state.store.update_state`.
        nodes: ``step.type`` → :data:`NodeRunner`. The runner builds these
            adapters from the concrete Node implementations
            (:mod:`harness.nodes.ai` and siblings).
    """

    run_id: str
    db_path: Path
    contracts: dict[str, type[BaseModel]]
    state_schema: type[BaseState]
    nodes: dict[str, NodeRunner]


class Executor:
    """Per-step execution wrapper. One instance per workflow run.

    Stateless apart from the retry policy; the runner constructs once and
    re-uses across every step it dispatches.
    """

    def __init__(self, *, policy: RetryPolicy | None = None) -> None:
        self._policy = policy if policy is not None else RetryPolicy.v1_default()

    async def execute(self, step: Step, ctx: Context) -> NodeResult[BaseModel]:
        """Run one step end-to-end.

        Raises:
            DependencyNotSatisfied: a ``depends_on`` field is ``None`` in state.
            ContractMismatch: missing / mismatched / unknown-field contract.
            RuntimeError: no node adapter registered for ``step.type``.
            BaseException: anything the node raises after retry budget
                exhaustion, re-raised after a ``node_failed`` event lands.
        """
        emitter = EventEmitter(ctx.db_path)
        state = await read_state(ctx.run_id, ctx.state_schema, db_path=ctx.db_path)

        self._check_depends_on(step, state)
        contract_cls = self._resolve_contract(step, ctx)
        runner = self._resolve_runner(step, ctx)

        await emitter.emit(
            run_id=ctx.run_id, event_type="node_started", node_id=step.id
        )

        retry_events: list[tuple[EventType, dict[str, Any]]] = []

        def sink(event_type: EventType, data: dict[str, Any]) -> None:
            retry_events.append((event_type, data))

        started_at = time.monotonic()
        try:
            async def op(_rc: RetryContext) -> NodeResult[BaseModel]:
                return await runner(step, state, ctx)

            result = await run_with_retry(
                op, policy=self._policy, event_sink=sink
            )
        except BaseException as exc:
            await self._flush_retry_events(emitter, ctx.run_id, step.id, retry_events)
            await emitter.emit(
                run_id=ctx.run_id,
                event_type="node_failed",
                node_id=step.id,
                data={
                    "reason": type(exc).__name__,
                    "message": str(exc),
                },
            )
            raise

        await self._flush_retry_events(emitter, ctx.run_id, step.id, retry_events)

        if contract_cls is not None and not isinstance(result.contract, contract_cls):
            await self._emit_failed_for_internal(
                emitter, ctx.run_id, step.id, "ContractMismatch"
            )
            raise ContractMismatch(
                f"step {step.id!r}: node returned contract of type "
                f"{type(result.contract).__name__}, expected {contract_cls.__name__}"
            )

        if step.writes:
            self._validate_writes_against_contract(step, contract_cls)
            await self._apply_writes(ctx, step, result)

        duration_ms = int((time.monotonic() - started_at) * 1000)
        await emitter.emit(
            run_id=ctx.run_id,
            event_type="node_completed",
            node_id=step.id,
            duration_ms=duration_ms,
        )

        return result

    # ---- internals ------------------------------------------------------- #

    @staticmethod
    def _check_depends_on(step: Step, state: BaseState) -> None:
        """Raise :class:`DependencyNotSatisfied` for any unset depends_on field.

        Convention (SPEC §4.2 / §5): a derived-state field defaults to
        ``None`` until written. A non-``None`` value means the predecessor
        has produced it; ``None`` means the prerequisite never ran.
        """
        for dep in step.depends_on:
            if not hasattr(state, dep):
                raise DependencyNotSatisfied(
                    f"step {step.id!r}: depends_on field {dep!r} not declared "
                    f"on state schema {type(state).__name__!r}"
                )
            if getattr(state, dep) is None:
                raise DependencyNotSatisfied(
                    f"step {step.id!r}: depends_on field {dep!r} is unset "
                    f"(None) in state — predecessor has not produced it"
                )

    @staticmethod
    def _resolve_contract(
        step: Step, ctx: Context
    ) -> type[BaseModel] | None:
        """Pick the contract type for this step.

        Returns ``None`` only when the step has no writes AND no contract is
        registered — i.e. the SPEC §5 ``writes: []`` exception. Any step
        with a non-empty ``writes:`` MUST have a registered contract.
        """
        contract_cls = ctx.contracts.get(step.id)
        if contract_cls is None and step.writes:
            raise ContractMismatch(
                f"step {step.id!r}: declares writes={step.writes!r} but no "
                f"contract is registered in Context.contracts"
            )
        return contract_cls

    @staticmethod
    def _resolve_runner(step: Step, ctx: Context) -> NodeRunner:
        runner = ctx.nodes.get(step.type)
        if runner is None:
            raise RuntimeError(
                f"step {step.id!r}: no node registered for type {step.type!r} "
                f"(registered types: {sorted(ctx.nodes)})"
            )
        return runner

    @staticmethod
    def _validate_writes_against_contract(
        step: Step, contract_cls: type[BaseModel] | None
    ) -> None:
        """Every name in ``step.writes`` must exist on the contract."""
        # _resolve_contract already raised if contract_cls is None and writes
        # is non-empty, so the assert is defensive only.
        assert contract_cls is not None
        contract_fields = set(contract_cls.model_fields.keys())
        unknown = [name for name in step.writes if name not in contract_fields]
        if unknown:
            raise ContractMismatch(
                f"step {step.id!r}: writes={unknown!r} not declared on "
                f"contract {contract_cls.__name__} "
                f"(contract fields: {sorted(contract_fields)})"
            )

    @staticmethod
    async def _apply_writes(
        ctx: Context, step: Step, result: NodeResult[BaseModel]
    ) -> None:
        """Project the declared ``writes:`` fields onto state."""
        payload = {name: getattr(result.contract, name) for name in step.writes}
        await update_state(
            ctx.run_id,
            ctx.state_schema,
            db_path=ctx.db_path,
            **payload,
        )

    @staticmethod
    async def _flush_retry_events(
        emitter: EventEmitter,
        run_id: str,
        node_id: str,
        events: list[tuple[EventType, dict[str, Any]]],
    ) -> None:
        """Emit any buffered ``retry_attempted`` events in arrival order."""
        for event_type, data in events:
            await emitter.emit(
                run_id=run_id,
                event_type=event_type,
                node_id=node_id,
                data=data,
            )

    @staticmethod
    async def _emit_failed_for_internal(
        emitter: EventEmitter,
        run_id: str,
        node_id: str,
        reason: str,
    ) -> None:
        """Emit ``node_failed`` for an executor-internal validation failure.

        Separate from the raise-from-node path because the message text is
        controlled (no need to capture an external exception's str()).
        """
        await emitter.emit(
            run_id=run_id,
            event_type="node_failed",
            node_id=node_id,
            data={"reason": reason, "message": ""},
        )
