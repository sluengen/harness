"""Load + derive tests for the shipped ``workflows/steward.yaml``.

The steward workflow (SPEC §14) is the smallest end-to-end exercise of
the harness — three nodes, pure YAML, inline contracts, derived state.
This module covers AC1 (load) and AC2 (derive) of H-027:

* AC1 — :func:`harness.workflow.loader.load_workflow` returns a
  :class:`LoadedWorkflow` with no schema errors and three compiled
  contracts (one per step).
* AC2 — :func:`harness.workflow.derive.derive_state_schema` yields a
  ``StewardState`` class carrying ``BaseState``'s seven fields plus the
  six workflow-declared writes (summary, key_files, open_questions,
  findings, systemic_insights, report_path) with the documented defaults
  (``None`` for scalars / models, ``[]`` for lists).

The shipped YAML is the canonical SPEC §14 shape — these tests are
therefore both regression guards for the loader/derive path AND a
load-time smoke test for the steward workflow itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from harness.state.schema import BaseState
from harness.workflow.derive import derive_state_schema
from harness.workflow.loader import LoadedWorkflow, load_workflow

# Resolve the workflow path from the repo root the worktree shares with
# the test runner. ``Path(__file__).parents[2]`` walks from
# tests/unit/test_*.py up to the worktree root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_STEWARD_WORKFLOW = _REPO_ROOT / "workflows" / "steward.yaml"


@pytest.fixture(scope="module")
def loaded_steward() -> LoadedWorkflow:
    """Load the shipped steward workflow once per test module."""
    assert _STEWARD_WORKFLOW.is_file(), (
        f"workflows/steward.yaml missing at {_STEWARD_WORKFLOW}"
    )
    return load_workflow(_STEWARD_WORKFLOW)


# ---------------------------------------------------------------------------
# AC1 — load
# ---------------------------------------------------------------------------


def test_ac1_steward_workflow_loads_without_error(
    loaded_steward: LoadedWorkflow,
) -> None:
    """The shipped YAML parses, validates structurally, and the loader's
    cross-step checks (writes-against-contract, writer-type consistency,
    no human decisions, no orphan ``writes:``) all pass."""
    assert loaded_steward.workflow.name == "steward"
    assert loaded_steward.workflow.version == 1
    # SPEC §14: three steps in declaration order.
    step_ids = [s.id for s in loaded_steward.workflow.steps]
    assert step_ids == ["read-context", "assess", "write-report"]


def test_ac1_steward_workflow_has_three_compiled_contracts(
    loaded_steward: LoadedWorkflow,
) -> None:
    """Every step declares a ``contract:`` block — all three compile."""
    assert set(loaded_steward.contracts) == {
        "read-context",
        "assess",
        "write-report",
    }
    for step_id, contract_cls in loaded_steward.contracts.items():
        assert issubclass(contract_cls, BaseModel), (
            f"{step_id!r} contract is not a BaseModel subclass: "
            f"{contract_cls!r}"
        )


def test_ac1_read_context_contract_shape(
    loaded_steward: LoadedWorkflow,
) -> None:
    """``read-context`` declares ``summary: string``,
    ``key_files: list[string]``, ``open_questions: list[string]``."""
    contract = loaded_steward.contracts["read-context"]
    fields = contract.model_fields
    assert set(fields) == {"summary", "key_files", "open_questions"}


def test_ac1_assess_contract_shape(loaded_steward: LoadedWorkflow) -> None:
    """``assess`` declares ``findings: list[<finding>]`` and
    ``systemic_insights: list[string]``."""
    contract = loaded_steward.contracts["assess"]
    fields = contract.model_fields
    assert set(fields) == {"findings", "systemic_insights"}


def test_ac1_write_report_contract_shape(
    loaded_steward: LoadedWorkflow,
) -> None:
    """``write-report`` declares ``report_path: string``."""
    contract = loaded_steward.contracts["write-report"]
    assert set(contract.model_fields) == {"report_path"}


def test_ac1_steward_declares_domain_input(
    loaded_steward: LoadedWorkflow,
) -> None:
    """SPEC §14: ``inputs.domain`` is a required string enum."""
    inputs = loaded_steward.workflow.inputs
    assert "domain" in inputs
    spec = inputs["domain"]
    assert spec.type == "string"
    assert spec.required is True
    assert spec.enum is not None
    assert set(spec.enum) == {"architecture", "harness", "test", "code", "design"}


# ---------------------------------------------------------------------------
# AC2 — derive
# ---------------------------------------------------------------------------


def test_ac2_derived_state_has_base_fields_plus_six_writes(
    loaded_steward: LoadedWorkflow,
) -> None:
    """The derived state class carries BaseState's seven fields plus the
    six workflow-declared writes — no more, no less."""
    state_cls = derive_state_schema(loaded_steward)
    assert issubclass(state_cls, BaseState)

    fields = set(state_cls.model_fields)
    # BaseState fields.
    base_fields = {
        "run_id",
        "workflow_name",
        "base_branch",
        "worktree_path",
        "worktree_branch",
        "artifacts_dir",
        "started_at",
        "notes",
    }
    # Workflow-declared writes per SPEC §14.
    workflow_fields = {
        "summary",
        "key_files",
        "open_questions",
        "findings",
        "systemic_insights",
        "report_path",
    }
    assert fields == base_fields | workflow_fields


def test_ac2_derived_state_class_name_is_steward_state(
    loaded_steward: LoadedWorkflow,
) -> None:
    """The class-name convention is ``{Camel(name)}State`` — the steward
    workflow's name is ``steward``, so the derived class is
    ``StewardState``."""
    state_cls = derive_state_schema(loaded_steward)
    assert state_cls.__name__ == "StewardState"


def test_ac2_derived_state_defaults(loaded_steward: LoadedWorkflow) -> None:
    """SPEC §6 defaults: scalars default to None, list[T] defaults to [].

    The derived class must be instantiable supplying only the BaseState
    framework fields — every workflow-declared field has a default.
    """
    from datetime import UTC, datetime

    state_cls = derive_state_schema(loaded_steward)
    instance = state_cls.model_validate(
        {
            "run_id": "01HXXXXXXXXXXXXXXXXXXXXXX0",
            "workflow_name": "steward",
            "base_branch": "main",
            "artifacts_dir": "/tmp/x",
            "started_at": datetime.now(UTC),
            "notes": [],
        }
    )
    # Scalar / model defaults are None.
    assert instance.summary is None  # type: ignore[attr-defined]
    assert instance.report_path is None  # type: ignore[attr-defined]
    # list[T] defaults are [].
    assert instance.key_files == []  # type: ignore[attr-defined]
    assert instance.open_questions == []  # type: ignore[attr-defined]
    assert instance.findings == []  # type: ignore[attr-defined]
    assert instance.systemic_insights == []  # type: ignore[attr-defined]
