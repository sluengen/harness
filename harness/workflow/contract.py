"""Inline contract compilation — SPEC §5 (H-006).

A workflow YAML can carry a `contract:` block that declares the typed shape of
the state a node writes. This module compiles that YAML dict into a Pydantic
v2 model via :func:`pydantic.create_model`. Downstream nodes that reference
``$state.<field>`` then get a load-time guarantee, not a runtime hope.

The compile step is strict on purpose:

* Unknown leaf types, unknown constraint keys, and ill-formed combinations
  raise :class:`ContractCompileError` at compile time, never at validate time.
* Produced models declare ``extra="forbid"`` so an agent that hallucinates an
  extra field is rejected.
* Every field is required by default. Optionality is not part of v1 — the
  spec calls implicit shapes the foot-gun.

Scope (H-006): the Pydantic model artefact. The matching tool-schema artefact
called out in SPEC §5 ("Contract compiles to two artefacts") lands in a later
issue. This module exposes only :func:`compile_inline_contract`.
"""

from __future__ import annotations

import copy
import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

__all__ = ["ContractCompileError", "compile_inline_contract"]


# Leaf-type names accepted in the YAML form. `list` is handled separately
# because it always carries an `of:` sibling.
_LEAF_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "boolean": bool,
    "number": float,
}

_NUMERIC_TYPES: frozenset[str] = frozenset({"integer", "number"})

# Constraint keys accepted alongside `type:` in a sub-mapping.
_CONSTRAINT_KEYS: frozenset[str] = frozenset(
    {"type", "of", "enum", "pattern", "min", "max", "format"}
)


class ContractCompileError(ValueError):
    """Raised when a contract YAML dict is malformed at compile time."""


def compile_inline_contract(
    spec: dict[str, Any], name: str = "Contract"
) -> type[BaseModel]:
    """Compile an inline contract dict into a Pydantic model.

    Args:
        spec: The YAML contract dict. Each key is a field name; each value is
            either a bare leaf-type string (``"string"``, ``"integer"``,
            ``"boolean"``, ``"number"``), or a sub-mapping. A sub-mapping with
            a ``type:`` key is a constrained leaf or a typed list. A
            sub-mapping without a ``type:`` key is treated as a nested object
            schema and recursively compiled.
        name: ``__name__`` of the produced model. Defaults to ``"Contract"``.

    Returns:
        A :class:`pydantic.BaseModel` subclass with ``extra="forbid"`` and
        every field required.

    Raises:
        ContractCompileError: if the spec is malformed (unknown type,
            constraint applied to the wrong type, missing `of:` on a list,
            unsupported `format`, etc.).
    """
    if not isinstance(spec, dict):  # pragma: no cover — type-checked by callers
        raise ContractCompileError(
            f"contract spec must be a mapping, got {type(spec).__name__}"
        )
    if not spec:
        raise ContractCompileError("contract spec is empty — declare at least one field")

    # Deep-copy so we never mutate caller state.
    working = copy.deepcopy(spec)

    fields: dict[str, tuple[Any, Any]] = {}
    for field_name, raw in working.items():
        field_type, field_info = _compile_field(field_name, raw, parent_name=name)
        fields[field_name] = (field_type, field_info)

    model: type[BaseModel] = create_model(  # type: ignore[call-overload]
        name,
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )
    return model


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _compile_field(
    field_name: str, raw: Any, *, parent_name: str
) -> tuple[Any, Any]:
    """Compile a single contract field. Returns ``(type, FieldInfo)`` for
    :func:`pydantic.create_model`."""
    # Bare leaf form: `name: string`
    if isinstance(raw, str):
        if raw not in _LEAF_TYPES:
            raise ContractCompileError(
                f"field {field_name!r}: unknown type {raw!r} "
                f"(expected one of {sorted(_LEAF_TYPES)} or 'list')"
            )
        return _LEAF_TYPES[raw], Field(...)

    if not isinstance(raw, dict):
        raise ContractCompileError(
            f"field {field_name!r}: expected a type name or a mapping, "
            f"got {type(raw).__name__}"
        )

    # Sub-mapping form. Two flavors:
    #   1. has `type:` -> constrained leaf, or a typed list
    #   2. no `type:`  -> nested object schema (recursive compile)
    if "type" not in raw:
        return _compile_nested_object(field_name, raw, parent_name=parent_name)

    declared_type = raw["type"]
    if not isinstance(declared_type, str):
        raise ContractCompileError(
            f"field {field_name!r}: `type:` must be a string, "
            f"got {type(declared_type).__name__}"
        )

    if declared_type == "list":
        return _compile_list(field_name, raw, parent_name=parent_name)

    if declared_type not in _LEAF_TYPES:
        raise ContractCompileError(
            f"field {field_name!r}: unknown type {declared_type!r} "
            f"(expected one of {sorted(_LEAF_TYPES)} or 'list')"
        )

    return _compile_constrained_leaf(field_name, raw, declared_type)


def _compile_nested_object(
    field_name: str, raw: dict[str, Any], *, parent_name: str
) -> tuple[Any, Any]:
    """A sub-mapping with no ``type:`` becomes a recursive sub-model."""
    sub_name = f"{parent_name}_{field_name}"
    sub_model = compile_inline_contract(raw, name=sub_name)
    return sub_model, Field(...)


def _compile_list(
    field_name: str, raw: dict[str, Any], *, parent_name: str
) -> tuple[Any, Any]:
    """`type: list` with `of: <leaf-or-subschema>` becomes ``list[T]``."""
    _reject_unknown_keys(field_name, raw, allowed={"type", "of"})
    if "of" not in raw:
        raise ContractCompileError(
            f"field {field_name!r}: `list` requires `of` (element type)"
        )
    element_spec = raw["of"]
    element_type: Any
    if isinstance(element_spec, str):
        if element_spec not in _LEAF_TYPES:
            raise ContractCompileError(
                f"field {field_name!r}: unknown type {element_spec!r} in `of:`"
            )
        element_type = _LEAF_TYPES[element_spec]
    elif isinstance(element_spec, dict):
        # Element schema may itself be a leaf-with-constraints, a nested object,
        # or another list. Re-use _compile_field's branching. We give it a
        # synthetic field name "item" because errors should still be readable.
        element_type, _ = _compile_field(
            f"{field_name}[item]", element_spec, parent_name=f"{parent_name}_{field_name}"
        )
    else:
        raise ContractCompileError(
            f"field {field_name!r}: `of:` must be a type name or mapping, "
            f"got {type(element_spec).__name__}"
        )
    return list[element_type], Field(...)


def _compile_constrained_leaf(
    field_name: str, raw: dict[str, Any], declared_type: str
) -> tuple[Any, Any]:
    """A leaf type with optional constraints (`enum`, `pattern`, `min`, `max`,
    `format`)."""
    _reject_unknown_keys(field_name, raw, allowed=_CONSTRAINT_KEYS)

    enum_values = raw.get("enum")
    pattern = raw.get("pattern")
    min_value = raw.get("min")
    max_value = raw.get("max")
    fmt = raw.get("format")

    # `pattern` only makes sense on strings.
    if pattern is not None and declared_type != "string":
        raise ContractCompileError(
            f"field {field_name!r}: `pattern` only valid on `string` "
            f"(got {declared_type!r})"
        )

    # `min`/`max` only make sense on numerics.
    if (min_value is not None or max_value is not None) and declared_type not in _NUMERIC_TYPES:
        raise ContractCompileError(
            f"field {field_name!r}: `min`/`max` only valid on `integer` or "
            f"`number` (got {declared_type!r})"
        )

    # `format` only makes sense on strings (only `datetime` supported in v1).
    if fmt is not None and declared_type != "string":
        raise ContractCompileError(
            f"field {field_name!r}: `format` only valid on `string` "
            f"(got {declared_type!r})"
        )

    # Resolve base type, with `format: datetime` overriding str -> datetime.
    base_type: type
    if fmt is not None:
        if fmt == "datetime":
            base_type = dt.datetime
        else:
            raise ContractCompileError(
                f"field {field_name!r}: unsupported `format` {fmt!r} "
                f"(supported: 'datetime')"
            )
    else:
        base_type = _LEAF_TYPES[declared_type]

    # Build a Field(...) carrying the supported constraints.
    field_kwargs: dict[str, Any] = {}
    if pattern is not None:
        field_kwargs["pattern"] = pattern
    if min_value is not None:
        field_kwargs["ge"] = min_value
    if max_value is not None:
        field_kwargs["le"] = max_value

    # `enum` is enforced via Literal[...] rather than a Field constraint, so
    # bad values fail with a clear "literal_error" rather than a custom check.
    if enum_values is not None:
        if not isinstance(enum_values, list) or not enum_values:
            raise ContractCompileError(
                f"field {field_name!r}: `enum` must be a non-empty list"
            )
        # Build Literal[v1, v2, ...] dynamically. Pydantic + Python typing
        # accept Literal with a tuple of args via Union/Literal indexing.
        literal_type = _literal_from_values(enum_values)
        # `pattern` on a Literal is meaningless once values are constrained,
        # but if both are declared we still apply pattern via Annotated so the
        # author's intent is preserved.
        annotated_type = Annotated[literal_type, Field(..., **field_kwargs)]  # type: ignore[valid-type]
        return annotated_type, Field(...)

    return Annotated[base_type, Field(..., **field_kwargs)], Field(...)


def _literal_from_values(values: list[Any]) -> Any:
    """Construct a ``Literal[v1, v2, ...]`` type from a runtime list."""
    # Literal[*values] isn't legal at runtime; subscript with a tuple instead.
    return Literal[tuple(values)]


def _reject_unknown_keys(
    field_name: str, raw: dict[str, Any], *, allowed: frozenset[str] | set[str]
) -> None:
    extras = set(raw) - set(allowed)
    if extras:
        raise ContractCompileError(
            f"field {field_name!r}: unknown constraint(s) {sorted(extras)} "
            f"(allowed: {sorted(allowed)})"
        )
