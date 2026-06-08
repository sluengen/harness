"""AI node — Jinja prompt + agent dispatch + contract enforcement.

Implements the v1 :class:`AINode` per SPEC §4.4. Responsibilities:

1. **Render** the step's Jinja2 prompt template (resolved relative to the
   ``prompts_dir`` injected at construction time) with ``state``,
   ``inputs``, and ``template_vars`` in scope. ``StrictUndefined`` mirrors
   the convention asserted in :mod:`tests.unit.test_standard_prompts`: a
   missing variable is a render-time error, never a silent empty string.
2. **Compile** the step's contract to (a) the Pydantic model that will
   validate the agent's submitted payload, and (b) the matching
   ``submit_<node_id>`` tool-schema dict (SPEC §5 "two artefacts"). Inline
   YAML dicts are compiled on demand via
   :func:`harness.workflow.contract.compile_inline_contract`; pre-compiled
   ``BaseModel`` subclasses are passed through; ``$contracts/<name>``
   string references are deferred to the H-008 wiring.
3. **Dispatch** to the supplied :class:`harness.dispatch.base.Agent` via
   ``execute(prompt, contract, submit_tool_schema, allowed_tools=…,
   cwd=…, timeout_s=…, stall_timeout_s=…, max_turns=…)``. The agent is
   injected at construction — AINode never discovers an agent globally.
   ``step.max_turns`` (None → SDK default) is forwarded as-is so the
   adapter can cap the number of model turns per SPEC §H-1.5-006.
4. **Return** the agent's :class:`NodeResult` unchanged. A defensive
   ``isinstance(result.contract, contract)`` check guards against a
   misbehaving agent that bypassed the protocol's validation.

Out of scope (executor / H-007):

* Routing ``agent.notes`` into ``state.notes`` (SPEC §7).
* Retry on :class:`ContractViolation` / :class:`AgentStalled` (SPEC §10).
* ``writes:`` extraction onto state (SPEC §6).
* Diff / commit_sha snapshotting for ``writes_files: True`` steps.
* Event emission — the agent already emits via its own ``event_sink``.

Scope decision: ``step.contract is None`` is rejected here. The
``writes: []`` exception SPEC §5 carves out for contract-less nodes will
be gated by the executor (H-007), not the AINode.

Reserved Jinja-scope keys: ``state`` and ``inputs`` are bound by the
framework. ``template_vars`` may add any other top-level variable, but
declaring ``state`` or ``inputs`` in ``template_vars`` is rejected at
render time — silent shadowing of framework scope is a workflow
authoring bug we want to surface immediately, not at the agent's
prompt-comprehension layer.

Cwd resolution: ``step.cwd`` (string, treated as a Path) wins; else
``state.worktree_path``; else ``None``.

See SPEC §4.3 (Node protocol), §4.4 (AI node mechanics), §4.7 (Agent
protocol), §5 ("Contract compiles to two artefacts").
"""

from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any, Literal

from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    TemplateError,
    TemplateNotFound,
)
from pydantic import BaseModel

from harness.dispatch.base import Agent
from harness.nodes.base import NodeResult
from harness.state.schema import BaseState
from harness.workflow.contract import ContractCompileError, compile_inline_contract
from harness.workflow.schema import AIStep
from harness.workflow.tool_schema import compile_to_tool_schema

__all__ = ["AINode"]

# Scope keys the framework owns. template_vars cannot shadow these.
_RESERVED_SCOPE_KEYS = frozenset({"state", "inputs"})


class _EmptyContract(BaseModel):
    """Zero-field contract for AI steps that declare ``writes: []``.

    Gives the agent a ``submit_<step_id>`` tool with no required fields,
    letting it signal completion after file mutations without writing
    anything to state.
    """


class AINode:
    """v1 AI node: render → dispatch → return.

    Conforms structurally to :class:`harness.nodes.base.Node`. The
    ``Agent`` is injected at construction; the executor (H-007) constructs
    the AINode once per workflow run and re-uses it across every AI step.

    The Jinja ``Environment`` is built once per AINode instance and reused
    across calls — the ``FileSystemLoader`` rooted at ``prompts_dir`` lets
    workflows reference templates by relative path (``prompts/review.j2`` or
    ``my-prompt.j2``).
    """

    type: Literal["ai"] = "ai"

    def __init__(self, *, agent: Agent, prompts_dir: Path) -> None:
        self._agent = agent
        self._prompts_dir = prompts_dir
        # Mirrors tests/unit/test_standard_prompts.py — single dialect across
        # the runtime so authors who develop with one env see the same
        # behaviour the executor sees.
        # autoescape=False is intentional: Jinja templates render LLM
        # prompts (plain text), not HTML. HTML-escaping prompt copy would
        # corrupt the agent's instructions. Mirrors the convention in
        # tests/unit/test_standard_prompts.py.
        self._env = Environment(
            loader=FileSystemLoader(str(prompts_dir)),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            autoescape=False,  # noqa: S701 — prompts are plain text, not HTML
        )

    async def execute(
        self,
        *,
        step: AIStep,
        state: BaseState,
        inputs: dict[str, Any],
        contract_override: builtins.type[BaseModel] | None = None,
        repo_root: Path | None = None,
    ) -> NodeResult[BaseModel]:
        """Render, dispatch, and return the agent's :class:`NodeResult`.

        Args:
            step: The workflow's :class:`AIStep`.
            state: Run state — passed to the prompt template under ``state``.
            inputs: Workflow inputs — passed under ``inputs``.
            contract_override: Optional pre-compiled contract type. Used by
                the executor when the contract was resolved upstream
                (e.g. via ``$contracts/<name>`` once H-008 wires that path).
                When supplied, ``step.contract`` is ignored. Transitional —
                once H-008 makes the loader pre-compile every contract into
                ``step.contract`` itself, this parameter is expected to
                disappear.
            repo_root: When set, ``cwd="."`` in the step resolves to this
                path instead of ``Path(".")``. Required for cross-repo
                execution where agent operations must run in the target repo,
                not the harness process directory.

        Raises:
            RuntimeError: prompt-template not found, render error,
                contract compile failure, missing contract, or the agent
                returned a contract instance of the wrong type.
            NotImplementedError: ``step.contract`` is a ``$contracts/<name>``
                string reference (H-008 territory).
        """
        contract_cls = self._resolve_contract(step, contract_override)
        prompt_text = self._render_prompt(step, state, inputs)
        submit_schema = compile_to_tool_schema(contract_cls, node_id=step.id)
        cwd = self._resolve_cwd(step, state, repo_root=repo_root)

        # A step that opts into session persistence resumes one conversation
        # per step.id across re-executions (e.g. fix-loop retries); otherwise
        # session_key is None and the agent runs fresh each call.
        session_key = step.id if step.persist_session else None

        result = await self._agent.execute(
            prompt_text,
            contract_cls,
            submit_schema,
            allowed_tools=list(step.allowed_tools),
            cwd=cwd,
            timeout_s=step.timeout_s,
            stall_timeout_s=step.stall_timeout_s,
            max_turns=step.max_turns,
            session_key=session_key,
        )

        # Defensive guard: a well-behaved Agent (per protocol) returns a
        # NodeResult whose contract is an instance of the type we passed.
        # ClaudeAgent enforces this; MockAgent's bare-default does not.
        # Skip the check for writes:[] steps — the empty-contract path is
        # a signal-only submit; we never extract fields from it.
        if step.writes and not isinstance(result.contract, contract_cls):
            raise RuntimeError(
                f"AI step {step.id!r}: agent returned a contract instance of "
                f"{builtins.type(result.contract).__name__}, expected "
                f"{contract_cls.__name__}. The agent bypassed contract "
                f"validation — this is an Agent-implementation bug, not a "
                f"workflow problem."
            )
        return result

    # ---- internals ------------------------------------------------------- #

    def _resolve_contract(
        self,
        step: AIStep,
        override: builtins.type[BaseModel] | None,
    ) -> builtins.type[BaseModel]:
        """Pick the contract type for this step.

        Precedence: ``override`` > ``step.contract`` (compiled / passed
        through). String references (``$contracts/<name>``) raise
        :class:`NotImplementedError` pointing at H-008.
        """
        if override is not None:
            return override

        spec = step.contract
        if spec is None:
            # writes:[] exception (SPEC §5 / AUTHORING §3): no state output,
            # only file mutations. Return the zero-field contract so the agent
            # still gets a submit tool to call to signal completion.
            return _EmptyContract

        if isinstance(spec, type) and issubclass(spec, BaseModel):
            # Already-compiled type — passthrough.
            return spec

        if isinstance(spec, dict):
            try:
                return compile_inline_contract(
                    spec, name=f"{step.id.title()}Contract"
                )
            except ContractCompileError as e:
                raise RuntimeError(
                    f"AI step {step.id!r}: contract compile failed: {e}"
                ) from e

        if isinstance(spec, str):
            # $contracts/<name> reference — H-008 wires resolution; until
            # then the executor must pre-compile and pass via override.
            raise NotImplementedError(
                f"AI step {step.id!r}: contract string reference {spec!r} — "
                f"$contracts/<name> resolution lands in H-008 wiring; "
                f"pass a pre-compiled type via contract_override for now."
            )

        raise RuntimeError(
            f"AI step {step.id!r}: unsupported contract spec type "
            f"{type(spec).__name__}"
        )

    def _render_prompt(
        self, step: AIStep, state: BaseState, inputs: dict[str, Any]
    ) -> str:
        """Render the step's Jinja template with the canonical scope.

        Scope: ``state`` (the BaseState instance), ``inputs`` (workflow
        input dict), plus every key in ``step.template_vars`` flattened
        as a top-level variable. ``state`` and ``inputs`` are reserved
        scope keys: ``template_vars`` is rejected at render time if it
        tries to shadow either, since silently clobbering a reserved
        scope key would mask a workflow-authoring bug as a render-success.
        """
        reserved = _RESERVED_SCOPE_KEYS & step.template_vars.keys()
        if reserved:
            raise RuntimeError(
                f"AI step {step.id!r}: template_vars cannot shadow reserved "
                f"scope keys {sorted(reserved)} — those names are bound to "
                f"the framework-supplied state and inputs objects."
            )

        try:
            template = self._env.get_template(step.prompt)
        except TemplateNotFound as e:
            raise RuntimeError(
                f"AI step {step.id!r}: prompt template {step.prompt!r} not "
                f"found under {self._prompts_dir}"
            ) from e

        scope: dict[str, Any] = {
            "state": state,
            "inputs": inputs,
        }
        # template_vars merge in as top-level vars; reserved keys (state,
        # inputs) are guarded above so this update can never override them.
        scope.update(step.template_vars)

        try:
            return template.render(**scope)
        except TemplateError as e:
            raise RuntimeError(
                f"AI step {step.id!r}: prompt render failed: {e}"
            ) from e

    @staticmethod
    def _resolve_cwd(
        step: AIStep,
        state: BaseState,
        *,
        repo_root: Path | None = None,
    ) -> Path | None:
        """``step.cwd`` (treated as Path) wins; else state.worktree_path; else None.

        When ``step.cwd == "."`` and ``repo_root`` is provided, returns
        ``repo_root`` so cross-repo AI steps run in the target repo
        instead of the harness process directory.
        """
        if step.cwd is not None:
            cwd = Path(step.cwd)
            if str(cwd) == "." and repo_root is not None:
                return repo_root
            return cwd
        if state.worktree_path is not None:
            return state.worktree_path
        return None
