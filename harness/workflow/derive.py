"""Derive a workflow's state schema — see SPEC §6 (H-009).

Pure transformation: ``LoadedWorkflow → type[BaseState]``. We walk every
step (including the body of any ``loop:`` block), collect each name
listed in ``writes:`` together with its compiled-contract field type,
and produce a Pydantic class subclassing :class:`BaseState` that carries
one field per write declaration.

Defaults (SPEC §6 "Defaults are None for scalars, [] for lists, {} for
dicts, applied automatically"):

* scalar / model annotations  → ``T | None`` with default ``None``
* ``list[T]`` annotations     → ``list[T]`` with default ``[]``
* ``dict[K, V]`` annotations  → ``dict[K, V]`` with default ``{}``

The H-008 loader already verified that every name in ``writes:`` exists
on the step's contract and that multiple writers of the same field
declare identical types. This module trusts those invariants and does
not re-validate them.

Class name convention
---------------------

The derived class is named ``f"{Camel(workflow.name)}State"``. The
``Camel`` step splits on ``-`` and ``_``, capitalises each chunk, and
joins. Example:

* ``"bugfix"``      → ``"BugfixState"``
* ``"hot-fix"``     → ``"HotFixState"``
* ``"my_workflow"`` → ``"MyWorkflowState"``
"""

from __future__ import annotations

from typing import Annotated, Any, get_origin

from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

from harness.state.schema import BaseState
from harness.workflow.loader import LoadedWorkflow
from harness.workflow.schema import LoopStep, Step

__all__ = ["derive_state_schema"]


def derive_state_schema(loaded: LoadedWorkflow) -> type[BaseState]:
    """Walk ``loaded.workflow.steps``, take the union of every step's
    ``writes:`` declarations + matching contract field types, and
    return a Pydantic class subclassing :class:`BaseState`.

    See module docstring for the defaults rule and class-name
    convention.
    """
    workflow = loaded.workflow
    contracts = loaded.contracts

    # field_name → (annotation, default) for create_model. Insertion
    # order is preserved by the dict (Python 3.7+); since we walk the
    # workflow in declaration order, downstream introspection is
    # deterministic.
    derived_fields: dict[str, tuple[Any, Any]] = {}

    for step in _iter_all_steps(workflow.steps):
        contract = contracts.get(step.id)
        if contract is None:
            # Steps without a contract are guaranteed by the loader to
            # have writes: []; nothing to contribute.
            continue
        for name in step.writes:
            if name in derived_fields:
                # Loader guarantees identical types across writers, so
                # the first occurrence wins. Skip silently.
                continue
            field_info = contract.model_fields[name]
            derived_fields[name] = _to_state_field(field_info)

    class_name = f"{_camelize(workflow.name)}State"

    derived: type[BaseState] = create_model(  # type: ignore[call-overload]
        class_name,
        __base__=BaseState,
        **derived_fields,
    )
    return derived


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _to_state_field(field_info: FieldInfo) -> tuple[Any, Any]:
    """Translate a contract :class:`FieldInfo` into ``(annotation,
    default)`` for the derived state.

    Per SPEC §6:
      * list  → ``list[T]``      default ``[]``
      * dict  → ``dict[K, V]``   default ``{}``
      * other → ``T | None``     default ``None``

    The contract annotation is preserved as-is for the non-Optional
    arm, so :class:`Annotated` metadata (``Field(ge=…, le=…)``) and
    :data:`typing.Literal` enums survive untouched.
    """
    annotation = field_info.annotation
    if annotation is None:
        # create_model can't accept a bare None annotation; treat it
        # as "Any | None" so the derived field is at least valid.
        # (No contract field reaches here in practice — Pydantic v2
        # always sets annotation when create_model was used.)
        return (Any | None, None)  # pragma: no cover

    # Determine the default rule from the *bare* annotation before we
    # fold metadata back in: list[T] keeps its origin as `list`, but
    # Annotated[list[T], ...] does not — check first.
    origin = get_origin(annotation)

    # Re-attach any metadata Pydantic stripped onto FieldInfo.metadata
    # (Ge/Le/Pattern/etc.). The contract compiler builds fields via
    # Annotated[T, Field(...constraints...)] then create_model — Pydantic
    # v2 stores the resulting constraints on FieldInfo.metadata, not on
    # the bare annotation. Fold them back so they survive the
    # state-schema round-trip.
    if field_info.metadata:
        # mypy can't follow runtime-built Annotated subscriptions; the
        # contract compiler does the same trick for the same reason.
        annotation = Annotated[(annotation, *field_info.metadata)]  # type: ignore[assignment]

    if origin is list:
        return (annotation, _empty_list_default())
    if origin is dict:
        return (annotation, _empty_dict_default())

    # Scalar / model / constrained / Literal — all get Optional[T] = None.
    return (annotation | None, None)


def _iter_all_steps(steps: list[Step]) -> list[Step]:
    """Flatten the workflow's steps in declaration order, descending
    into ``loop:`` bodies. Mirrors the loader's ``_iter_steps`` helper
    so derive sees exactly the same set of steps the loader validated.
    """
    out: list[Step] = []
    for step in steps:
        out.append(step)
        if isinstance(step, LoopStep):
            out.extend(_iter_all_steps(list(step.loop.steps)))
    return out


def _camelize(name: str) -> str:
    """Split on ``-`` and ``_`` and CamelCase. ``"hot-fix"`` →
    ``"HotFix"``. Idempotent on already-camel input (``"BugFix"`` →
    ``"BugFix"``)."""
    chunks = name.replace("-", "_").split("_")
    return "".join(c[:1].upper() + c[1:] for c in chunks if c)


# Default factories for list[]/dict{} fields. We allocate fresh
# instances per model instantiation by handing pydantic a Field with
# ``default_factory=…`` so two instances never alias the same list/dict.
def _empty_list_default() -> Any:
    from pydantic import Field

    return Field(default_factory=list)


def _empty_dict_default() -> Any:
    from pydantic import Field

    return Field(default_factory=dict)


# Touch the BaseModel import so static analyzers don't drop it — the
# return type annotation references BaseState (a BaseModel subclass).
_ = BaseModel
