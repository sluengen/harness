"""Tests for harness.workflow.tool_schema — SPEC §5 ("two artefacts").

A workflow contract compiles to two artefacts: a Pydantic model (H-006) and
a tool schema in the agent harness's native dialect (this module). The tool
schema's name is ``submit_<node_id>``, its ``input_schema`` is the Pydantic
model's ``model_json_schema()``, and its description is a stable instruction
the agent reads in-context.

The shape mirrors Anthropic's tool-definition dialect (the dict shape that
``ClaudeAgent.execute(..., submit_tool_schema=...)`` reads ``["name"]`` from
in :mod:`harness.dispatch.claude`). Other adapters re-use the same dict.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from harness.workflow.tool_schema import compile_to_tool_schema


class _SimpleContract(BaseModel):
    summary: str
    count: int = 0


class _ContractWithDescription(BaseModel):
    severity: str = Field(description="HIGH | MEDIUM | LOW")
    description: str


def test_tool_schema_name_is_submit_node_id() -> None:
    """SPEC §4.4: the tool the agent calls is ``submit_<node_id>``."""
    schema = compile_to_tool_schema(_SimpleContract, node_id="analyze")
    assert schema["name"] == "submit_analyze"


def test_tool_schema_carries_description() -> None:
    """The schema must carry a non-empty description — it's in-context guidance
    the agent reads when deciding what to submit."""
    schema = compile_to_tool_schema(_SimpleContract, node_id="analyze")
    assert isinstance(schema["description"], str)
    assert schema["description"].strip(), "description is empty"


def test_tool_schema_input_schema_matches_pydantic_json_schema() -> None:
    """The ``input_schema`` is the Pydantic model's JSON schema, verbatim.

    Single source of truth: any drift between the validation schema and what
    the agent sees would defeat the purpose of having one contract.
    """
    schema = compile_to_tool_schema(_SimpleContract, node_id="x")
    expected = _SimpleContract.model_json_schema()
    assert schema["input_schema"] == expected


def test_tool_schema_preserves_field_constraints() -> None:
    """Field-level descriptions / constraints from Pydantic must reach the
    agent via ``input_schema`` (it's the same dict, but assert the path)."""
    schema = compile_to_tool_schema(_ContractWithDescription, node_id="review")
    properties = schema["input_schema"]["properties"]
    assert properties["severity"]["description"] == "HIGH | MEDIUM | LOW"


def test_tool_schema_node_id_with_hyphens_passes_through() -> None:
    """Node ids may contain hyphens; the tool name preserves them."""
    schema = compile_to_tool_schema(_SimpleContract, node_id="root-cause")
    assert schema["name"] == "submit_root-cause"


def test_tool_schema_top_level_keys_match_anthropic_dialect() -> None:
    """The dict has exactly ``name``, ``description``, ``input_schema`` keys —
    the Anthropic tool-definition dialect ``ClaudeAgent`` consumes."""
    schema = compile_to_tool_schema(_SimpleContract, node_id="x")
    assert set(schema.keys()) == {"name", "description", "input_schema"}
