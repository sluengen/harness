"""Decision node — LLM gate (v1) + human approval (v2 schema-reserved).

Implements :class:`DecisionNode` per SPEC §4.5. Two actor flavors:

**``actor: llm``** (v1) — same execution shape as :class:`harness.nodes.ai.AINode`,
with two additions:

1. The contract MUST declare a ``decision: bool`` field. Validated at
   ``execute()`` time before dispatch — across inline-dict, pre-compiled
   ``BaseModel``, and ``contract_override`` paths. The error mentions the
   step id and the literal phrase ``decision: bool`` so authoring mistakes
   are grep-friendly.
2. On successful dispatch, a single ``decision_made`` event is emitted via
   the (optional) ``event_sink``. The payload is
   ``{"step_id", "decision", "on_reject"}`` — ``on_reject`` is echoed
   verbatim from the workflow YAML so the executor (H-007) can route on it.

**``actor: human``** (v2) — schema-reserved. Running such a workflow
errors at ``execute()`` time with ``"actor: human is reserved for v2"``
until the resume machinery (``harness/decisions/``) ships.

Out of scope (executor / H-007):

* Routing on ``on_reject`` (cancel / continue / retry_loop / pause_for_human).
* ``writes:`` extraction onto state.
* ``decision_requested`` / ``decision_received`` events for the human path.

Composition: the LLM path delegates render + dispatch + isinstance-guard to
an internally-constructed :class:`AINode`. SPEC §4.5 explicitly endorses
this ("Implemented as syntactic sugar over the AI dispatch path plus
routing"). The transient :class:`AIStep` we build mirrors the
``DecisionStep`` fields one-for-one; ``writes_files``, ``stall_timeout_s``,
and ``timeout_s`` use ``AIStep``'s defaults since ``DecisionStep`` does
not declare them.

See SPEC §4.3 (Node protocol), §4.4 (AI node mechanics), §4.5 (Decision
node), §4.9 (event types).
"""

from __future__ import annotations

import builtins
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from harness.dispatch.base import Agent
from harness.events.schema import EventType
from harness.nodes.ai import AINode
from harness.nodes.base import NodeResult
from harness.state.schema import BaseState
from harness.workflow.contract import ContractCompileError, compile_inline_contract
from harness.workflow.schema import AIStep, DecisionStep

__all__ = ["DecisionNode"]

_HUMAN_ACTOR_RESERVED_MSG = "actor: human is reserved for v2"


class DecisionNode:
    """v1 Decision node: ``actor: llm`` dispatches via :class:`AINode` + emits
    a ``decision_made`` event; ``actor: human`` raises until v2 lands.

    The :class:`Agent` and ``prompts_dir`` are injected at construction; an
    inner :class:`AINode` instance is built once and reused across calls.
    The ``event_sink`` is optional — when ``None``, the node still
    dispatches, it just records nothing.
    """

    type: Literal["decision"] = "decision"

    def __init__(
        self,
        *,
        agent: Agent,
        prompts_dir: Path,
        event_sink: Callable[[EventType, dict[str, Any]], None] | None = None,
    ) -> None:
        self._agent = agent
        self._prompts_dir = prompts_dir
        self._event_sink = event_sink
        # Composition: the AINode owns prompt rendering + dispatch + the
        # isinstance guard. We layer decision-specific contract checks and
        # the decision_made event around it.
        self._ai_node = AINode(agent=agent, prompts_dir=prompts_dir)

    async def execute(
        self,
        *,
        step: DecisionStep,
        state: BaseState,
        inputs: dict[str, Any],
        contract_override: builtins.type[BaseModel] | None = None,
    ) -> NodeResult[BaseModel]:
        """Validate the contract, dispatch via the AI path, emit event.

        Raises:
            RuntimeError: ``actor: human`` (v2 reserved); contract missing
                or wrong-typed ``decision`` field; or anything the
                underlying :class:`AINode` raises.
            NotImplementedError: ``step.contract`` is a ``$contracts/<name>``
                string reference (H-008 territory) — mirrors :class:`AINode`.
        """
        if step.actor == "human":
            # v2 territory. SPEC §4.5: "running a workflow that uses
            # actor: human errors at load time with 'actor: human is
            # reserved for v2' until the resume machinery ships." We match
            # the SPEC's error message at execute() time — load-time
            # rejection lands when the workflow loader (H-008) wires up.
            raise RuntimeError(
                f"decision step {step.id!r}: {_HUMAN_ACTOR_RESERVED_MSG}"
            )

        # actor: llm path. Build a transient AIStep mirroring the
        # DecisionStep's LLM-relevant fields. DecisionStep doesn't declare
        # writes_files / stall_timeout_s / timeout_s — fall through to
        # AIStep's defaults.
        ai_step = self._build_ai_step(step)

        # Validate the contract has `decision: bool` BEFORE dispatch. We
        # resolve the contract here (mirroring AINode's resolution rules)
        # and run the decision-specific check; AINode then re-resolves the
        # same spec on its way to dispatch, but we pass the already-
        # resolved class via contract_override so the compile work is not
        # duplicated.
        contract_cls = self._resolve_contract_for_check(
            ai_step, contract_override
        )
        self._require_decision_bool(step.id, contract_cls)

        result = await self._ai_node.execute(
            step=ai_step,
            state=state,
            inputs=inputs,
            contract_override=contract_cls,
        )

        # Emit decision_made only on successful return. Any exception above
        # propagates without firing an event — the executor's audit log
        # will record `node_failed` for those paths.
        if self._event_sink is not None:
            decision_value = result.contract.decision  # type: ignore[attr-defined]
            self._event_sink(
                "decision_made",
                {
                    "step_id": step.id,
                    "decision": bool(decision_value),
                    "on_reject": step.on_reject,
                },
            )

        return result

    # ---- internals ------------------------------------------------------- #

    @staticmethod
    def _build_ai_step(step: DecisionStep) -> AIStep:
        """Translate a DecisionStep (actor=llm) into an AIStep for the
        underlying AI dispatch path.

        DecisionStep's model_validator guarantees ``prompt`` is not None
        when ``actor == 'llm'``; the assert here is a defensive guard.
        """
        assert step.prompt is not None  # noqa: S101 — guaranteed by DecisionStep validator
        return AIStep(
            id=step.id,
            type="ai",
            agent=step.agent,
            model=step.model,
            prompt=step.prompt,
            template_vars=step.template_vars,
            allowed_tools=step.allowed_tools,
            contract=step.contract,
            cwd=step.cwd,
            # AIStep defaults for fields DecisionStep doesn't declare.
            writes_files=False,
            stall_timeout_s=300,
            timeout_s=600,
        )

    def _resolve_contract_for_check(
        self,
        ai_step: AIStep,
        override: builtins.type[BaseModel] | None,
    ) -> builtins.type[BaseModel]:
        """Resolve the contract spec to a Pydantic class for the
        ``decision: bool`` check. Mirrors :class:`AINode`'s resolution
        precedence: ``override`` > ``step.contract``.

        Inline-dict specs are pre-screened for the ``decision`` key here
        so the author sees a clear "decision: bool required" error rather
        than a Pydantic compile error. Compilation is then delegated to
        the same helper :class:`AINode` uses, keeping the two paths
        consistent.
        """
        if override is not None:
            return override

        spec = ai_step.contract
        if spec is None:
            raise RuntimeError(
                f"decision step {ai_step.id!r}: no contract declared. "
                f"Decision nodes require a contract that declares "
                f"`decision: bool`."
            )

        if isinstance(spec, type) and issubclass(spec, BaseModel):
            return spec

        if isinstance(spec, dict):
            # Pre-check: the inline dict must declare a `decision` field.
            # We surface a friendly error before invoking the compiler so
            # the message names the missing field rather than "compile
            # produced an empty model" or similar.
            self._require_decision_bool_in_dict(ai_step.id, spec)
            try:
                return compile_inline_contract(
                    spec, name=f"{ai_step.id.title()}Contract"
                )
            except ContractCompileError as e:
                raise RuntimeError(
                    f"decision step {ai_step.id!r}: contract compile failed: {e}"
                ) from e

        if isinstance(spec, str):
            # $contracts/<name> — defer to H-008. Mirror AINode's wording so
            # workflow authors see the same NotImplementedError shape.
            raise NotImplementedError(
                f"decision step {ai_step.id!r}: contract string reference "
                f"{spec!r} — $contracts/<name> resolution lands in H-008 "
                f"wiring; pass a pre-compiled type via contract_override "
                f"for now."
            )

        raise RuntimeError(
            f"decision step {ai_step.id!r}: unsupported contract spec type "
            f"{type(spec).__name__}"
        )

    @staticmethod
    def _require_decision_bool_in_dict(
        step_id: str, spec: dict[str, Any]
    ) -> None:
        """Inline-dict pre-check: ``decision`` key exists and resolves to
        boolean. Bare-leaf form (``decision: boolean``) and constrained
        form (``decision: {type: boolean}``) both accepted."""
        if "decision" not in spec:
            raise RuntimeError(
                f"decision step {step_id!r}: contract must declare "
                f"`decision: bool` — required by SPEC §4.5."
            )
        raw = spec["decision"]
        # Bare leaf: "boolean" or (synonym) "bool".
        if isinstance(raw, str):
            if raw not in ("boolean", "bool"):
                raise RuntimeError(
                    f"decision step {step_id!r}: contract `decision` must "
                    f"be `decision: bool` (got type {raw!r})."
                )
            return
        if isinstance(raw, dict):
            declared = raw.get("type")
            if declared not in ("boolean", "bool"):
                raise RuntimeError(
                    f"decision step {step_id!r}: contract `decision` must "
                    f"be `decision: bool` (got type {declared!r})."
                )
            return
        raise RuntimeError(
            f"decision step {step_id!r}: contract `decision` must be "
            f"`decision: bool` (got {type(raw).__name__})."
        )

    @staticmethod
    def _require_decision_bool(
        step_id: str, contract_cls: builtins.type[BaseModel]
    ) -> None:
        """Pre-compiled check: ``decision`` field exists with annotation
        ``bool``. Runs on every contract that reaches dispatch — covers
        ``contract_override`` and pre-compiled ``step.contract`` paths,
        and revalidates the inline-dict path after compilation as a
        belt-and-braces guard."""
        field = contract_cls.model_fields.get("decision")
        if field is None:
            raise RuntimeError(
                f"decision step {step_id!r}: contract must declare "
                f"`decision: bool` — required by SPEC §4.5 (got fields "
                f"{sorted(contract_cls.model_fields)})."
            )
        if field.annotation is not bool:
            raise RuntimeError(
                f"decision step {step_id!r}: contract field `decision` must "
                f"be `decision: bool` (got annotation "
                f"{getattr(field.annotation, '__name__', field.annotation)!r})."
            )
