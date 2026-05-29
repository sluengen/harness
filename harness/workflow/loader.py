"""Workflow loader — SPEC §5, §6, §9 (H-008).

End-to-end loader for a workflow YAML file. Responsibilities:

1. Read + parse YAML from disk.
2. Validate the structural shape via the H-005 :class:`Workflow` model.
3. Resolve every step's ``contract:`` —

   * inline dict → :func:`harness.workflow.contract.compile_inline_contract`
   * ``$contracts/<name>`` reference → :func:`harness.workflow.resolver.resolve_contract_ref`

4. Run **load-time validations** that the schema layer can't express on
   its own:

   * every name in a step's ``writes:`` exists as a field on that step's
     compiled contract
   * if multiple steps write the same field, their contract field types
     must be identical
   * any node with ``writes_files: true`` has a ``worktree.create``
     ancestor in the dependency graph
   * a ``decision`` step with ``actor: human`` is rejected (v2 feature)
   * a step with non-empty ``writes:`` and no ``contract:`` is rejected

The loader stops at "contracts compiled, validations pass". Per-workflow
state-model derivation (the ``BaseState + workflow-specific fields``
class) is H-009's job.

Errors
------

All load-time failures surface as :class:`WorkflowLoadError`. The original
exception is preserved on ``__cause__`` so callers can still inspect the
underlying :class:`pydantic.ValidationError`,
:class:`harness.workflow.resolver.ContractRefError`,
:class:`harness.workflow.contract.ContractCompileError`,
:class:`yaml.YAMLError`, or :class:`OSError` if needed. One catchable type
for the common case; full fidelity for the rare case.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ValidationError

from harness.workflow.contract import (
    ContractCompileError,
    compile_inline_contract,
)
from harness.workflow.resolver import (
    ContractRefError,
    is_contract_ref,
    resolve_contract_ref,
)
from harness.workflow.schema import (
    DecisionStep,
    LoopStep,
    Step,
    Workflow,
    WorktreeStep,
)

__all__ = ["LoadedWorkflow", "WorkflowLoadError", "load_workflow"]


class WorkflowLoadError(ValueError):
    """Raised when a workflow fails load-time validation.

    Distinct from the underlying error classes (Pydantic
    :class:`ValidationError`, :class:`ContractRefError`,
    :class:`ContractCompileError`, :class:`yaml.YAMLError`,
    :class:`OSError`) so callers can catch all load-time failures with
    one type. The original cause is preserved via ``__cause__``.
    """


@dataclass(frozen=True)
class LoadedWorkflow:
    """A workflow + its compiled contracts, ready for the engine.

    Attributes:
        workflow: the parsed :class:`Workflow` Pydantic model.
        contracts: mapping ``step_id`` -> compiled Pydantic model class.
            Only populated for steps that declared a ``contract:``. Steps
            without a contract (allowed only when ``writes: []``) are
            absent from the dict.
        path: source YAML path (for error messages).
    """

    workflow: Workflow
    contracts: dict[str, type[BaseModel]] = field(default_factory=dict)
    path: Path = field(default_factory=lambda: Path())


def load_workflow(
    path: Path, *, contracts_root: Path | None = None
) -> LoadedWorkflow:
    """Load and validate a workflow YAML.

    Args:
        path: workflow YAML path.
        contracts_root: directory of shared contracts. Defaults to
            ``path.parent.parent / "contracts"`` when ``None`` — i.e. for
            ``workflows/bugfix.yaml``, contracts are in ``contracts/``.

    Returns:
        :class:`LoadedWorkflow` with all contracts compiled.

    Raises:
        WorkflowLoadError: on any load-time failure. The original
            exception is preserved on ``__cause__``.
    """
    if contracts_root is None:
        contracts_root = path.parent.parent / "contracts"

    raw_text = _read_file(path)
    parsed = _parse_yaml(path, raw_text)
    workflow = _validate_workflow(path, parsed)

    contracts = _compile_all_contracts(path, workflow, contracts_root)
    _validate_writes_against_contracts(workflow, contracts)
    _validate_writer_type_consistency(workflow, contracts)
    _validate_worktree_ancestry(workflow)
    _validate_decision_actor(workflow)
    _validate_writes_without_contract(workflow)

    return LoadedWorkflow(workflow=workflow, contracts=contracts, path=path)


# ---------------------------------------------------------------------------
# Stage 1 — read + parse + structural validate
# ---------------------------------------------------------------------------


def _read_file(path: Path) -> str:
    try:
        return path.read_text()
    except OSError as exc:
        raise WorkflowLoadError(
            f"could not read workflow file {path}: {exc}"
        ) from exc


def _parse_yaml(path: Path, raw_text: str) -> Any:
    try:
        return yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise WorkflowLoadError(
            f"workflow {path}: invalid YAML: {exc}"
        ) from exc


def _validate_workflow(path: Path, parsed: Any) -> Workflow:
    if not isinstance(parsed, dict):
        raise WorkflowLoadError(
            f"workflow {path}: top-level YAML must be a mapping, got "
            f"{type(parsed).__name__}"
        )
    try:
        return Workflow.model_validate(parsed)
    except ValidationError as exc:
        raise WorkflowLoadError(
            f"workflow {path}: schema validation failed: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Stage 2 — compile contracts (inline or $contracts/<name>)
# ---------------------------------------------------------------------------


def _compile_all_contracts(
    path: Path, workflow: Workflow, contracts_root: Path
) -> dict[str, type[BaseModel]]:
    contracts: dict[str, type[BaseModel]] = {}
    for step in _iter_steps(workflow.steps):
        spec = _step_contract_spec(step)
        if spec is None:
            continue
        contracts[step.id] = _compile_step_contract(path, step.id, spec, contracts_root)
    return contracts


def _compile_step_contract(
    path: Path,
    step_id: str,
    spec: str | dict[str, Any],
    contracts_root: Path,
) -> type[BaseModel]:
    """Dispatch on inline-vs-reference and surface failures as
    :class:`WorkflowLoadError`."""
    if is_contract_ref(spec):
        assert isinstance(spec, str)  # narrowed by is_contract_ref  # noqa: S101
        try:
            return resolve_contract_ref(spec, contracts_root)
        except ContractRefError as exc:
            raise WorkflowLoadError(
                f"workflow {path}: step {step_id!r} contract reference "
                f"{spec!r} could not be resolved: {exc}"
            ) from exc
        except ContractCompileError as exc:
            raise WorkflowLoadError(
                f"workflow {path}: step {step_id!r} shared contract "
                f"{spec!r} is malformed: {exc}"
            ) from exc

    if isinstance(spec, dict):
        try:
            return compile_inline_contract(spec, name=f"Contract_{_safe_id(step_id)}")
        except ContractCompileError as exc:
            raise WorkflowLoadError(
                f"workflow {path}: step {step_id!r} inline contract is "
                f"malformed: {exc}"
            ) from exc

    raise WorkflowLoadError(
        f"workflow {path}: step {step_id!r} contract must be a string "
        f"reference or a mapping, got {type(spec).__name__}"
    )


# ---------------------------------------------------------------------------
# Stage 3 — load-time validation rules
# ---------------------------------------------------------------------------


def _validate_writes_against_contracts(
    workflow: Workflow, contracts: dict[str, type[BaseModel]]
) -> None:
    """AC8: every name in ``writes:`` must exist on the compiled
    contract."""
    for step in _iter_steps(workflow.steps):
        if not step.writes:
            continue
        contract = contracts.get(step.id)
        if contract is None:
            # AC14 covers "writes without contract"; not our concern here.
            continue
        contract_fields = set(contract.model_fields)
        for spec in step.writes:
            name = spec.field
            if name not in contract_fields:
                raise WorkflowLoadError(
                    f"step {step.id!r} writes field {name!r} not declared "
                    f"in its contract (contract fields: "
                    f"{sorted(contract_fields)})"
                )


def _validate_writer_type_consistency(
    workflow: Workflow, contracts: dict[str, type[BaseModel]]
) -> None:
    """AC9/AC10: if multiple steps write the same field, their contract
    field types must be identical (compared via Pydantic v2 annotation).
    """
    # Map field-name → list of (step_id, annotation)
    seen: dict[str, list[tuple[str, Any]]] = {}
    for step in _iter_steps(workflow.steps):
        contract = contracts.get(step.id)
        if contract is None:
            continue
        for spec in step.writes:
            name = spec.field
            if name not in contract.model_fields:
                # AC8 will catch this — don't double-fire.
                continue
            annotation = contract.model_fields[name].annotation
            seen.setdefault(name, []).append((step.id, annotation))

    for name, writers in seen.items():
        if len(writers) <= 1:
            continue
        first_step, first_ann = writers[0]
        for other_step, other_ann in writers[1:]:
            if other_ann != first_ann:
                raise WorkflowLoadError(
                    f"field {name!r} has conflicting types across writers: "
                    f"step {first_step!r} declares {first_ann!r}, step "
                    f"{other_step!r} declares {other_ann!r}"
                )


def _validate_worktree_ancestry(workflow: Workflow) -> None:
    """AC11/AC12: any node with ``writes_files: true`` must have a
    ``worktree.create`` ancestor in the dependency graph.

    The graph edges are the union of explicit ``depends_on:`` and the
    implicit predecessor edge — SPEC §5 says "default: previous step". A
    step's predecessor is the step that came before it in declaration
    order at the same nesting level.

    Loop steps inherit the loop's predecessors: a ``writes_files: true``
    step inside a ``loop:`` block sees the loop's ancestors as its own.
    """
    # Build an "ancestor producers" map: step_id → True if any ancestor
    # is a worktree.create. We compute this in a single forward pass since
    # steps are already in declaration order.
    has_worktree_ancestor: dict[str, bool] = {}

    def visit_block(steps: list[Step], inherited: bool) -> None:
        """Walk a block of sibling steps. ``inherited`` is True if the
        enclosing context already has a worktree ancestor (e.g. a loop
        whose predecessors include a worktree.create)."""
        prev_has_worktree = inherited
        # Track each step's own ancestor flag so depends_on can look them up.
        local_flag: dict[str, bool] = {}

        for step in steps:
            # Compute this step's ancestor flag from:
            # (a) the implicit predecessor edge (prev_has_worktree),
            # (b) explicit depends_on edges (other steps in this block).
            ancestor_flag = prev_has_worktree
            for dep in step.depends_on:
                # depends_on may name siblings in this block, or any
                # already-visited step at a higher level. We honour both.
                if dep in local_flag:
                    ancestor_flag = ancestor_flag or local_flag[dep]
                elif dep in has_worktree_ancestor:
                    ancestor_flag = ancestor_flag or has_worktree_ancestor[dep]

            # Self check: a worktree.create step is itself the ancestor.
            is_worktree_create = (
                isinstance(step, WorktreeStep) and step.action == "create"
            )

            local_flag[step.id] = ancestor_flag or is_worktree_create
            has_worktree_ancestor[step.id] = local_flag[step.id]

            # writes_files check applies to leaf steps. Loop blocks
            # don't carry writes_files themselves; their child steps do.
            writes_files = getattr(step, "writes_files", False)
            if writes_files and not local_flag[step.id]:
                raise WorkflowLoadError(
                    f"step {step.id!r} writes files but no "
                    f"worktree.create ancestor exists in its dependency "
                    f"graph"
                )

            # Recurse into loop bodies, inheriting the loop's own flag.
            if isinstance(step, LoopStep):
                visit_block(list(step.loop.steps), inherited=local_flag[step.id])

            # Update the implicit-predecessor flag for the *next* sibling.
            prev_has_worktree = local_flag[step.id]

    visit_block(list(workflow.steps), inherited=False)


def _validate_decision_actor(workflow: Workflow) -> None:
    """AC13: ``decision`` with ``actor: human`` is reserved for v2."""
    for step in _iter_steps(workflow.steps):
        if isinstance(step, DecisionStep) and step.actor == "human":
            raise WorkflowLoadError(
                f"step {step.id!r}: decision actor 'human' not supported "
                f"in v1; use actor: llm"
            )


def _validate_writes_without_contract(workflow: Workflow) -> None:
    """AC14: a step with ``writes: [...]`` (non-empty) but no
    ``contract:`` is a load-time error. ``writes: []`` and no contract
    is the documented sidecar pattern (e.g. the ``implement`` node in
    the SPEC §5 example).

    ``WorktreeStep`` is explicitly excluded: ``worktree.create`` writes
    ``worktree_path`` and ``worktree_branch`` directly into
    ``BaseState`` via framework-managed paths, not via the normal
    ``contract:`` → ``writes:`` pathway.
    """
    for step in _iter_steps(workflow.steps):
        if not step.writes:
            continue
        if isinstance(step, WorktreeStep):
            continue
        if _step_contract_spec(step) is None:
            raise WorkflowLoadError(
                f"step {step.id!r} declares writes={step.writes!r} but "
                f"has no contract — every node that writes state must "
                f"declare a contract"
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iter_steps(steps: list[Step]) -> list[Step]:
    """Flatten the workflow's steps, descending into loop blocks. Used
    by validators that don't care about nesting structure (writes,
    contracts, decision actor)."""
    out: list[Step] = []
    for step in steps:
        out.append(step)
        if isinstance(step, LoopStep):
            out.extend(_iter_steps(list(step.loop.steps)))
    return out


def _step_contract_spec(step: Step) -> str | dict[str, Any] | None:
    """Return the step's ``contract:`` spec or ``None`` if the step type
    doesn't carry one. ``check``, ``worktree``, and ``loop`` steps don't
    have a contract."""
    return getattr(step, "contract", None)


def _safe_id(step_id: str) -> str:
    """Make a step id usable as a Python identifier suffix."""
    return step_id.replace("-", "_").replace(".", "_")
