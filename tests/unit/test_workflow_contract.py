"""Tests for harness.workflow.contract — inline contract → Pydantic model (H-006)."""

from __future__ import annotations

import copy
import datetime as dt
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from harness.workflow.contract import (
    ContractCompileError,
    compile_inline_contract,
)

# ---------------------------------------------------------------------------
# Bare leaf forms
# ---------------------------------------------------------------------------


def test_bare_string_field() -> None:
    model_cls = compile_inline_contract({"name": "string"})
    instance = model_cls.model_validate({"name": "hello"})
    assert instance.model_dump() == {"name": "hello"}


def test_bare_integer_field() -> None:
    model_cls = compile_inline_contract({"count": "integer"})
    assert model_cls.model_validate({"count": 5}).model_dump() == {"count": 5}


def test_bare_boolean_field() -> None:
    model_cls = compile_inline_contract({"flag": "boolean"})
    assert model_cls.model_validate({"flag": True}).model_dump() == {"flag": True}


def test_bare_number_field_accepts_float() -> None:
    model_cls = compile_inline_contract({"score": "number"})
    assert model_cls.model_validate({"score": 1.25}).model_dump() == {"score": 1.25}


def test_bare_number_field_accepts_int() -> None:
    # number is a float in Pydantic; ints coerce.
    model_cls = compile_inline_contract({"score": "number"})
    assert model_cls.model_validate({"score": 3}).score == 3.0


def test_string_field_rejects_int() -> None:
    model_cls = compile_inline_contract({"name": "string"})
    with pytest.raises(ValidationError):
        model_cls.model_validate({"name": 42})


def test_integer_field_rejects_non_numeric_string() -> None:
    model_cls = compile_inline_contract({"count": "integer"})
    with pytest.raises(ValidationError):
        model_cls.model_validate({"count": "not-a-number"})


# ---------------------------------------------------------------------------
# Sub-mapping leaf form
# ---------------------------------------------------------------------------


def test_sub_mapping_leaf_form_string() -> None:
    model_cls = compile_inline_contract({"name": {"type": "string"}})
    assert model_cls.model_validate({"name": "x"}).name == "x"


def test_sub_mapping_leaf_form_integer() -> None:
    model_cls = compile_inline_contract({"count": {"type": "integer"}})
    assert model_cls.model_validate({"count": 7}).count == 7


# ---------------------------------------------------------------------------
# list of <leaf type>
# ---------------------------------------------------------------------------


def test_list_of_string() -> None:
    model_cls = compile_inline_contract(
        {"items": {"type": "list", "of": "string"}}
    )
    instance = model_cls.model_validate({"items": ["a", "b", "c"]})
    assert instance.items == ["a", "b", "c"]


def test_list_of_integer() -> None:
    model_cls = compile_inline_contract(
        {"counts": {"type": "list", "of": "integer"}}
    )
    assert model_cls.model_validate({"counts": [1, 2, 3]}).counts == [1, 2, 3]


def test_list_of_string_rejects_wrong_element_type() -> None:
    model_cls = compile_inline_contract(
        {"items": {"type": "list", "of": "string"}}
    )
    with pytest.raises(ValidationError):
        model_cls.model_validate({"items": ["a", 5]})


def test_list_without_of_is_compile_error() -> None:
    with pytest.raises(ContractCompileError, match="`list` requires `of`"):
        compile_inline_contract({"items": {"type": "list"}})


# ---------------------------------------------------------------------------
# list of sub-objects
# ---------------------------------------------------------------------------


def test_list_of_subobject() -> None:
    model_cls = compile_inline_contract(
        {
            "results": {
                "type": "list",
                "of": {"status": "string", "score": "number"},
            }
        }
    )
    instance = model_cls.model_validate(
        {"results": [{"status": "ok", "score": 1.0}, {"status": "fail", "score": 0.0}]}
    )
    assert len(instance.results) == 2
    assert instance.results[0].status == "ok"


def test_list_of_subobject_rejects_missing_field() -> None:
    model_cls = compile_inline_contract(
        {"results": {"type": "list", "of": {"status": "string"}}}
    )
    with pytest.raises(ValidationError):
        model_cls.model_validate({"results": [{}]})


# ---------------------------------------------------------------------------
# Nested object as a value
# ---------------------------------------------------------------------------


def test_nested_object_field() -> None:
    model_cls = compile_inline_contract(
        {"metadata": {"author": "string", "count": "integer"}}
    )
    instance = model_cls.model_validate(
        {"metadata": {"author": "scott", "count": 3}}
    )
    assert instance.metadata.author == "scott"
    assert instance.metadata.count == 3


def test_nested_object_rejects_extra_inner_field() -> None:
    model_cls = compile_inline_contract(
        {"metadata": {"author": "string"}}
    )
    with pytest.raises(ValidationError, match="extra"):
        model_cls.model_validate({"metadata": {"author": "x", "rogue": 1}})


def test_nested_object_three_deep() -> None:
    model_cls = compile_inline_contract(
        {"a": {"b": {"c": "string"}}}
    )
    instance = model_cls.model_validate({"a": {"b": {"c": "deep"}}})
    assert instance.a.b.c == "deep"


# ---------------------------------------------------------------------------
# enum
# ---------------------------------------------------------------------------


def test_enum_string_accepts_value_in_set() -> None:
    model_cls = compile_inline_contract(
        {"status": {"type": "string", "enum": ["PASS", "FAIL"]}}
    )
    assert model_cls.model_validate({"status": "PASS"}).status == "PASS"


def test_enum_string_rejects_value_outside_set() -> None:
    model_cls = compile_inline_contract(
        {"status": {"type": "string", "enum": ["PASS", "FAIL"]}}
    )
    with pytest.raises(ValidationError):
        model_cls.model_validate({"status": "MAYBE"})


def test_enum_integer() -> None:
    model_cls = compile_inline_contract(
        {"level": {"type": "integer", "enum": [1, 2, 3]}}
    )
    assert model_cls.model_validate({"level": 2}).level == 2
    with pytest.raises(ValidationError):
        model_cls.model_validate({"level": 4})


# ---------------------------------------------------------------------------
# pattern
# ---------------------------------------------------------------------------


def test_pattern_matching() -> None:
    model_cls = compile_inline_contract(
        {"id": {"type": "string", "pattern": r"^PROJ-\d+$"}}
    )
    assert model_cls.model_validate({"id": "PROJ-270"}).id == "PROJ-270"


def test_pattern_not_matching() -> None:
    model_cls = compile_inline_contract(
        {"id": {"type": "string", "pattern": r"^PROJ-\d+$"}}
    )
    with pytest.raises(ValidationError):
        model_cls.model_validate({"id": "nope"})


def test_pattern_on_non_string_is_compile_error() -> None:
    with pytest.raises(ContractCompileError, match="`pattern` only valid"):
        compile_inline_contract(
            {"x": {"type": "integer", "pattern": "^foo$"}}
        )


# ---------------------------------------------------------------------------
# min / max on integer + number
# ---------------------------------------------------------------------------


def test_integer_min_max() -> None:
    model_cls = compile_inline_contract(
        {"priority": {"type": "integer", "min": 1, "max": 5}}
    )
    assert model_cls.model_validate({"priority": 3}).priority == 3
    with pytest.raises(ValidationError):
        model_cls.model_validate({"priority": 0})
    with pytest.raises(ValidationError):
        model_cls.model_validate({"priority": 6})


def test_number_min_max() -> None:
    model_cls = compile_inline_contract(
        {"ratio": {"type": "number", "min": 0.0, "max": 1.0}}
    )
    assert model_cls.model_validate({"ratio": 0.5}).ratio == 0.5
    with pytest.raises(ValidationError):
        model_cls.model_validate({"ratio": -0.1})
    with pytest.raises(ValidationError):
        model_cls.model_validate({"ratio": 1.1})


def test_min_only() -> None:
    model_cls = compile_inline_contract({"n": {"type": "integer", "min": 0}})
    assert model_cls.model_validate({"n": 0}).n == 0
    with pytest.raises(ValidationError):
        model_cls.model_validate({"n": -1})


def test_max_only() -> None:
    model_cls = compile_inline_contract({"n": {"type": "integer", "max": 10}})
    assert model_cls.model_validate({"n": 10}).n == 10
    with pytest.raises(ValidationError):
        model_cls.model_validate({"n": 11})


def test_min_on_string_is_compile_error() -> None:
    with pytest.raises(ContractCompileError, match="`min`/`max` only valid"):
        compile_inline_contract({"x": {"type": "string", "min": 1}})


def test_max_on_boolean_is_compile_error() -> None:
    with pytest.raises(ContractCompileError, match="`min`/`max` only valid"):
        compile_inline_contract({"x": {"type": "boolean", "max": 1}})


# ---------------------------------------------------------------------------
# format: datetime
# ---------------------------------------------------------------------------


def test_format_datetime_accepts_iso_string() -> None:
    model_cls = compile_inline_contract(
        {"created_at": {"type": "string", "format": "datetime"}}
    )
    instance = model_cls.model_validate({"created_at": "2026-05-08T12:34:56"})
    assert isinstance(instance.created_at, dt.datetime)


def test_format_datetime_rejects_garbage() -> None:
    model_cls = compile_inline_contract(
        {"created_at": {"type": "string", "format": "datetime"}}
    )
    with pytest.raises(ValidationError):
        model_cls.model_validate({"created_at": "not-a-date"})


def test_unsupported_format_is_compile_error() -> None:
    with pytest.raises(ContractCompileError, match="unsupported `format`"):
        compile_inline_contract(
            {"x": {"type": "string", "format": "uuid-flavor-of-the-month"}}
        )


# ---------------------------------------------------------------------------
# extra="forbid", required-by-default
# ---------------------------------------------------------------------------


def test_extra_fields_forbidden() -> None:
    model_cls = compile_inline_contract({"name": "string"})
    with pytest.raises(ValidationError, match="extra"):
        model_cls.model_validate({"name": "x", "rogue": True})


def test_missing_field_raises() -> None:
    model_cls = compile_inline_contract({"name": "string", "count": "integer"})
    with pytest.raises(ValidationError):
        model_cls.model_validate({"name": "x"})


# ---------------------------------------------------------------------------
# Compile errors
# ---------------------------------------------------------------------------


def test_unknown_leaf_type_is_compile_error() -> None:
    with pytest.raises(ContractCompileError, match="unknown type"):
        compile_inline_contract({"x": "float"})


def test_unknown_leaf_type_in_sub_mapping_is_compile_error() -> None:
    with pytest.raises(ContractCompileError, match="unknown type"):
        compile_inline_contract({"x": {"type": "float"}})


def test_unknown_constraint_key_is_compile_error() -> None:
    with pytest.raises(ContractCompileError, match="unknown constraint"):
        compile_inline_contract(
            {"x": {"type": "string", "wat": "is this"}}
        )


def test_empty_top_level_is_compile_error() -> None:
    # An empty schema buys nothing — flag it as a probable author bug.
    with pytest.raises(ContractCompileError, match="empty"):
        compile_inline_contract({})


# ---------------------------------------------------------------------------
# Input dict not mutated
# ---------------------------------------------------------------------------


def test_input_spec_dict_not_mutated() -> None:
    spec: dict[str, Any] = {
        "summary": "string",
        "items": {"type": "list", "of": "string"},
        "status": {"type": "string", "enum": ["PASS", "FAIL"]},
        "nested": {"author": "string"},
    }
    snapshot = copy.deepcopy(spec)
    compile_inline_contract(spec)
    assert spec == snapshot


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_round_trip_dump_revalidates() -> None:
    model_cls = compile_inline_contract(
        {
            "summary": "string",
            "items": {"type": "list", "of": "string"},
            "status": {"type": "string", "enum": ["PASS", "FAIL"]},
            "priority": {"type": "integer", "min": 1, "max": 5},
            "metadata": {"author": "string"},
        }
    )
    payload: dict[str, Any] = {
        "summary": "all done",
        "items": ["a", "b"],
        "status": "PASS",
        "priority": 3,
        "metadata": {"author": "scott"},
    }
    first = model_cls.model_validate(payload)
    dumped = first.model_dump()
    second = model_cls.model_validate(dumped)
    assert second.model_dump() == dumped


# ---------------------------------------------------------------------------
# Generated model name
# ---------------------------------------------------------------------------


def test_generated_model_name_default() -> None:
    model_cls = compile_inline_contract({"x": "string"})
    assert model_cls.__name__ == "Contract"


def test_generated_model_name_custom() -> None:
    model_cls = compile_inline_contract({"x": "string"}, name="ReviewVerdict")
    assert model_cls.__name__ == "ReviewVerdict"


def test_returned_model_is_basemodel_subclass() -> None:
    model_cls = compile_inline_contract({"x": "string"})
    assert issubclass(model_cls, BaseModel)


# ---------------------------------------------------------------------------
# Spec-section example end-to-end
# ---------------------------------------------------------------------------


def test_spec_example_compiles_and_validates() -> None:
    """The exact example from SPEC §5."""
    spec: dict[str, Any] = {
        "summary": "string",
        "items": {"type": "list", "of": "string"},
        "count": "integer",
        "status": {"type": "string", "enum": ["PASS", "FAIL"]},
        "priority": {"type": "integer", "min": 1, "max": 5},
    }
    model_cls = compile_inline_contract(spec, name="SpecExample")
    instance = model_cls.model_validate(
        {
            "summary": "ran",
            "items": ["a"],
            "count": 1,
            "status": "PASS",
            "priority": 3,
        }
    )
    assert instance.model_dump() == {
        "summary": "ran",
        "items": ["a"],
        "count": 1,
        "status": "PASS",
        "priority": 3,
    }
