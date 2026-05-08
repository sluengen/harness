"""Tests for H-009 — state-schema derivation.

Two units under test:

* :class:`harness.state.schema.BaseState` — the framework-defined fields
  every workflow's derived state class subclasses (SPEC §6).
* :func:`harness.workflow.derive.derive_state_schema` — walks a
  :class:`LoadedWorkflow`, takes the union of every step's
  ``writes:`` declarations, and produces a Pydantic class subclassing
  ``BaseState`` with one field per declared writes name.

Defaults rule (SPEC §6, "Defaults are None for scalars, [] for lists,
{} for dicts, applied automatically").

The H-008 loader already enforces "every writes name has a matching
contract field" and "type consistency across writers", so these tests
build their fixtures via :func:`load_workflow` and assume those
invariants hold by the time we reach derive.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, get_args, get_origin

import pytest
from pydantic import BaseModel, Field, ValidationError

from harness.state.schema import BaseState
from harness.workflow.derive import derive_state_schema
from harness.workflow.loader import load_workflow

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    (tmp_path / "workflows").mkdir()
    (tmp_path / "contracts").mkdir()
    return tmp_path


@pytest.fixture
def contracts_root(project_root: Path) -> Path:
    return project_root / "contracts"


def _write_workflow(project_root: Path, body: str, name: str = "wf.yaml") -> Path:
    path = project_root / "workflows" / name
    path.write_text(body)
    return path


def _base_kwargs() -> dict[str, object]:
    """Minimal valid kwargs to construct a BaseState (or any subclass)."""
    return {
        "run_id": "r1",
        "workflow_name": "wf",
        "base_branch": "staging",
        "artifacts_dir": Path("/tmp/x"),
        "started_at": datetime(2026, 5, 8, 12, 0, 0),
    }


# ---------------------------------------------------------------------------
# AC1, AC2 — BaseState
# ---------------------------------------------------------------------------


def test_base_state_instantiates_with_required_and_optional_defaults() -> None:
    """AC1: BaseState requires the documented fields and accepts the
    documented optional defaults."""
    s = BaseState(**_base_kwargs())  # type: ignore[arg-type]
    assert s.run_id == "r1"
    assert s.workflow_name == "wf"
    assert s.base_branch == "staging"
    assert s.worktree_path is None
    assert s.worktree_branch is None
    assert s.artifacts_dir == Path("/tmp/x")
    assert s.started_at == datetime(2026, 5, 8, 12, 0, 0)
    assert s.notes == []


def test_base_state_rejects_unknown_fields() -> None:
    """AC2: BaseState forbids extras."""
    with pytest.raises(ValidationError):
        BaseState(**_base_kwargs(), bogus=1)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC3, AC4 — happy-path derivation (SPEC §6 worked example)
# ---------------------------------------------------------------------------


WORKED_EXAMPLE_WORKFLOW = """\
name: bugfix
version: 1
steps:
  - id: investigate
    type: ai
    agent: claude
    prompt: prompts/investigate.j2
    contract:
      root_cause: string
      plan:
        type: list
        of: string
    writes: [root_cause, plan]

  - id: run-tests
    type: script
    command: pytest -x
    contract:
      tests_pass: boolean
      failing_tests:
        type: list
        of: string
    writes: [tests_pass, failing_tests]
"""


def test_derive_worked_example_field_shape(
    project_root: Path, contracts_root: Path
) -> None:
    """AC3: §6 worked example produces the exact derived shape."""
    path = _write_workflow(project_root, WORKED_EXAMPLE_WORKFLOW)
    loaded = load_workflow(path, contracts_root=contracts_root)

    derived_cls = derive_state_schema(loaded)

    fields = derived_cls.model_fields
    # The four workflow-specific fields.
    assert "root_cause" in fields
    assert "plan" in fields
    assert "tests_pass" in fields
    assert "failing_tests" in fields

    # Scalars become Optional with default None.
    rc_ann = fields["root_cause"].annotation
    assert rc_ann is not None
    assert type(None) in get_args(rc_ann)
    assert str in get_args(rc_ann)
    assert fields["root_cause"].default is None

    tp_ann = fields["tests_pass"].annotation
    assert tp_ann is not None
    assert type(None) in get_args(tp_ann)
    assert bool in get_args(tp_ann)
    assert fields["tests_pass"].default is None

    # Lists keep their list[T] annotation, default empty-list.
    plan_ann = fields["plan"].annotation
    assert get_origin(plan_ann) is list
    assert get_args(plan_ann) == (str,)
    instance = derived_cls(**_base_kwargs())  # type: ignore[arg-type]
    assert instance.plan == []  # type: ignore[attr-defined]
    assert instance.failing_tests == []  # type: ignore[attr-defined]


def test_derive_returns_basestate_subclass(
    project_root: Path, contracts_root: Path
) -> None:
    """AC4: derived class is a BaseState subclass."""
    path = _write_workflow(project_root, WORKED_EXAMPLE_WORKFLOW)
    loaded = load_workflow(path, contracts_root=contracts_root)
    derived_cls = derive_state_schema(loaded)
    assert issubclass(derived_cls, BaseState)


# ---------------------------------------------------------------------------
# AC5 — empty-writes workflow
# ---------------------------------------------------------------------------


EMPTY_WRITES_WORKFLOW = """\
name: pure-side-effect
version: 1
steps:
  - id: setup
    type: worktree
    action: create
    base: staging
    writes: []
  - id: noop
    type: check
    expr: 'True'
    writes: []
"""


def test_derive_empty_writes_workflow_has_only_basestate_fields(
    project_root: Path, contracts_root: Path
) -> None:
    """AC5: a workflow with no writes anywhere → derived class adds
    nothing on top of BaseState, but still works."""
    path = _write_workflow(project_root, EMPTY_WRITES_WORKFLOW)
    loaded = load_workflow(path, contracts_root=contracts_root)
    derived_cls = derive_state_schema(loaded)

    assert issubclass(derived_cls, BaseState)
    # No fields beyond BaseState's.
    extra_fields = set(derived_cls.model_fields) - set(BaseState.model_fields)
    assert extra_fields == set()
    # And it instantiates.
    derived_cls(**_base_kwargs())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC6 — scalar default rule
# ---------------------------------------------------------------------------


SCALAR_WORKFLOW = """\
name: scalar
version: 1
steps:
  - id: s1
    type: script
    command: echo
    contract:
      summary: string
    writes: [summary]
"""


def test_derive_scalar_field_becomes_optional_with_none_default(
    project_root: Path, contracts_root: Path
) -> None:
    """AC6: a `string` writes field → `str | None`, default None."""
    path = _write_workflow(project_root, SCALAR_WORKFLOW)
    loaded = load_workflow(path, contracts_root=contracts_root)
    derived_cls = derive_state_schema(loaded)

    fi = derived_cls.model_fields["summary"]
    args = get_args(fi.annotation)
    assert str in args
    assert type(None) in args
    assert fi.default is None


# ---------------------------------------------------------------------------
# AC7 — list default rule
# ---------------------------------------------------------------------------


LIST_WORKFLOW = """\
name: lists
version: 1
steps:
  - id: s1
    type: script
    command: echo
    contract:
      tags:
        type: list
        of: string
    writes: [tags]
"""


def test_derive_list_field_keeps_list_annotation_and_empty_default(
    project_root: Path, contracts_root: Path
) -> None:
    """AC7: a list writes-field → `list[T]`, default `[]` (NOT None)."""
    path = _write_workflow(project_root, LIST_WORKFLOW)
    loaded = load_workflow(path, contracts_root=contracts_root)
    derived_cls = derive_state_schema(loaded)

    fi = derived_cls.model_fields["tags"]
    assert get_origin(fi.annotation) is list
    assert get_args(fi.annotation) == (str,)

    instance = derived_cls(**_base_kwargs())  # type: ignore[arg-type]
    assert instance.tags == []  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC8 — nested-object field
# ---------------------------------------------------------------------------


NESTED_WORKFLOW = """\
name: nested
version: 1
steps:
  - id: s1
    type: script
    command: echo
    contract:
      issue:
        id: string
        title: string
    writes: [issue]
"""


def test_derive_nested_object_field_stays_optional_model(
    project_root: Path, contracts_root: Path
) -> None:
    """AC8: nested object → derived has `<NestedModel> | None = None`."""
    path = _write_workflow(project_root, NESTED_WORKFLOW)
    loaded = load_workflow(path, contracts_root=contracts_root)
    derived_cls = derive_state_schema(loaded)

    fi = derived_cls.model_fields["issue"]
    args = get_args(fi.annotation)
    # One of the union arms must be a BaseModel subclass.
    nested_models = [
        a for a in args if isinstance(a, type) and issubclass(a, BaseModel)
    ]
    assert len(nested_models) == 1
    assert type(None) in args
    assert fi.default is None

    nested_model_cls = nested_models[0]
    # Round-trip — the nested model still validates its inputs.
    n = nested_model_cls(id="X-1", title="hi")
    assert n.id == "X-1"  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        nested_model_cls(id=123, title="hi")


# ---------------------------------------------------------------------------
# AC9 — constrained leaf
# ---------------------------------------------------------------------------


CONSTRAINED_WORKFLOW = """\
name: constrained
version: 1
steps:
  - id: s1
    type: script
    command: echo
    contract:
      priority:
        type: integer
        min: 1
        max: 5
    writes: [priority]
"""


def test_derive_constrained_leaf_preserves_metadata(
    project_root: Path, contracts_root: Path
) -> None:
    """AC9: `integer` with min/max keeps its constraint metadata, plus
    Optional + None default."""
    path = _write_workflow(project_root, CONSTRAINED_WORKFLOW)
    loaded = load_workflow(path, contracts_root=contracts_root)
    derived_cls = derive_state_schema(loaded)

    fi = derived_cls.model_fields["priority"]
    # Default is None
    assert fi.default is None
    # Out-of-range still rejected.
    with pytest.raises(ValidationError):
        derived_cls(**_base_kwargs(), priority=99)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        derived_cls(**_base_kwargs(), priority=0)  # type: ignore[arg-type]
    # In-range accepted.
    ok = derived_cls(**_base_kwargs(), priority=3)  # type: ignore[arg-type]
    assert ok.priority == 3  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC10 — enum / Literal
# ---------------------------------------------------------------------------


ENUM_WORKFLOW = """\
name: enums
version: 1
steps:
  - id: s1
    type: script
    command: echo
    contract:
      status:
        type: string
        enum: [PASS, FAIL]
    writes: [status]
"""


def test_derive_enum_field_preserves_literal_and_optional(
    project_root: Path, contracts_root: Path
) -> None:
    """AC10: a string with enum: [PASS, FAIL] → derived has
    `Literal[...] | None` with None default."""
    path = _write_workflow(project_root, ENUM_WORKFLOW)
    loaded = load_workflow(path, contracts_root=contracts_root)
    derived_cls = derive_state_schema(loaded)

    fi = derived_cls.model_fields["status"]
    assert fi.default is None

    # Bad values rejected; good values accepted.
    with pytest.raises(ValidationError):
        derived_cls(**_base_kwargs(), status="MAYBE")  # type: ignore[arg-type]

    ok = derived_cls(**_base_kwargs(), status="PASS")  # type: ignore[arg-type]
    assert ok.status == "PASS"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC11 — cross-step union of identically-typed writes
# ---------------------------------------------------------------------------


CROSS_STEP_WORKFLOW = """\
name: cross
version: 1
steps:
  - id: s1
    type: script
    command: echo
    contract:
      verdict:
        type: string
        enum: [PASS, FAIL]
    writes: [verdict]
  - id: s2
    type: script
    command: echo
    contract:
      verdict:
        type: string
        enum: [PASS, FAIL]
    writes: [verdict]
"""


def test_derive_two_steps_same_field_collapses_to_one(
    project_root: Path, contracts_root: Path
) -> None:
    """AC11: two writers, identical types → one field on derived."""
    path = _write_workflow(project_root, CROSS_STEP_WORKFLOW)
    loaded = load_workflow(path, contracts_root=contracts_root)
    derived_cls = derive_state_schema(loaded)

    # Just one extra field beyond BaseState.
    extra = set(derived_cls.model_fields) - set(BaseState.model_fields)
    assert extra == {"verdict"}
    fi = derived_cls.model_fields["verdict"]
    assert fi.default is None


# ---------------------------------------------------------------------------
# AC12 — loop-body writes are included
# ---------------------------------------------------------------------------


LOOP_WORKFLOW = """\
name: loopwf
version: 1
steps:
  - id: outer
    type: loop
    loop:
      max_iterations: 3
      until: state.tests_pass
      steps:
        - id: run-tests
          type: script
          command: pytest -x
          contract:
            tests_pass: boolean
          writes: [tests_pass]
"""


def test_derive_includes_loop_body_writes(
    project_root: Path, contracts_root: Path
) -> None:
    """AC12: writes inside a loop body show up on the derived state."""
    path = _write_workflow(project_root, LOOP_WORKFLOW)
    loaded = load_workflow(path, contracts_root=contracts_root)
    derived_cls = derive_state_schema(loaded)

    assert "tests_pass" in derived_cls.model_fields
    fi = derived_cls.model_fields["tests_pass"]
    assert type(None) in get_args(fi.annotation)
    assert bool in get_args(fi.annotation)
    assert fi.default is None


# ---------------------------------------------------------------------------
# AC13 — top-level state_schema rejected by H-005 schema, confirmed via loader
# ---------------------------------------------------------------------------


def test_top_level_state_schema_field_rejected_at_load_time(
    project_root: Path, contracts_root: Path
) -> None:
    """AC13: declaring `state_schema:` at the top of a workflow is a
    load-time error. Already enforced by the H-005 Workflow model
    (`extra="forbid"`); this test just pins the user-visible behaviour."""
    body = """\
name: rogue
version: 1
state_schema:
  bogus: string
steps:
  - id: only
    type: check
    expr: 'True'
"""
    path = _write_workflow(project_root, body)
    from harness.workflow.loader import WorkflowLoadError

    with pytest.raises(WorkflowLoadError):
        load_workflow(path, contracts_root=contracts_root)


# ---------------------------------------------------------------------------
# Sanity — derived class name is deterministic and includes "State"
# ---------------------------------------------------------------------------


def test_derived_class_name_ends_with_state(
    project_root: Path, contracts_root: Path
) -> None:
    """Sanity: the derived class has a readable, deterministic name."""
    path = _write_workflow(project_root, WORKED_EXAMPLE_WORKFLOW)
    loaded = load_workflow(path, contracts_root=contracts_root)
    derived_cls = derive_state_schema(loaded)
    assert derived_cls.__name__.endswith("State")


# Touch the imports the test module relies on — placate F401 in tooling
# that may not understand fixture-scoped use.
_ = (Annotated, Literal, BaseModel, Field)
