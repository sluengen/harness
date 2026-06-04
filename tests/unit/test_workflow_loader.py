"""Tests for harness.workflow.loader — end-to-end workflow loader (H-008).

The loader parses a workflow YAML file, validates it against the Workflow
Pydantic model (H-005), resolves `$contracts/<name>` references (H-007),
compiles inline contracts (H-006), and runs load-time validations:

* every name in `writes:` exists on the step's compiled contract
* multiple writers of the same field declare identical types
* any `writes_files: true` step has a `worktree.create` ancestor
* a step without a `contract:` may only have `writes: []`

Note: ``decision`` steps with ``actor: human`` are now loaded without error
(H-2-002). The runner raises ``HumanDecisionRequested`` at execute time
instead.

All failures surface as `WorkflowLoadError` with the original cause in
`__cause__`. The tests check the exception type AND that the cause is
preserved, since the brief calls that out as a deliberate design choice.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from harness.workflow.contract import ContractCompileError
from harness.workflow.loader import (
    LoadedWorkflow,
    WorkflowLoadError,
    load_workflow,
)
from harness.workflow.resolver import ContractRefError
from harness.workflow.schema import Workflow

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """A scratch project layout: <root>/workflows/, <root>/contracts/."""
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


def _write_contract(contracts_root: Path, name: str, body: str) -> Path:
    path = contracts_root / f"{name}.yaml"
    path.write_text(body)
    return path


# A complete bugfix-style workflow that exercises mix of step types,
# inline + $contracts/<name>, depends_on chain, loop block, worktree
# create/cleanup. Used by the happy-path tests.
BUGFIX_WORKFLOW_YAML = """\
name: bugfix
version: 1
description: Fix a bug end-to-end
inputs:
  linear_id:
    type: string
    pattern: "^[A-Z]+-[0-9]+$"
    flag: --linear
    required: true
steps:
  - id: setup-worktree
    type: worktree
    action: create
    base: staging
    writes: []

  - id: fetch-issue
    type: script
    runtime: python
    script: scripts/fetch.py
    contract:
      issue_id: string
      title: string
    writes: [issue_id, title]

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

  - id: implement-and-test
    type: loop
    loop:
      max_iterations: 3
      until: state.tests_pass
      steps:
        - id: implement
          type: ai
          agent: claude
          prompt: prompts/implement.j2
          writes_files: true
          writes: []
        - id: run-tests
          type: script
          command: pytest -x
          contract:
            tests_pass: boolean
            failing_tests:
              type: list
              of: string
          writes: [tests_pass, failing_tests]

  - id: review
    type: ai
    agent: claude
    prompt: prompts/review.j2
    contract: $contracts/review-verdict
    writes: [status, issues]

  - id: gate
    type: check
    expr: state.status == "PASS"
    on_fail: cancel

  - id: teardown
    type: worktree
    action: cleanup
    policy: merge_to_base
    writes: []
"""

REVIEW_VERDICT_CONTRACT_YAML = """\
status:
  type: string
  enum: [PASS, FAIL]
issues:
  type: list
  of:
    severity: string
    description: string
"""


# ---------------------------------------------------------------------------
# AC3: missing file
# ---------------------------------------------------------------------------


def test_load_missing_file_raises_workflow_load_error(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    with pytest.raises(WorkflowLoadError) as exc:
        load_workflow(missing, contracts_root=tmp_path)
    # The error should mention the offending path so the user can find it.
    assert str(missing) in str(exc.value)
    # Cause should be an OSError (FileNotFoundError) for inspection.
    assert isinstance(exc.value.__cause__, OSError)


# ---------------------------------------------------------------------------
# AC4: invalid YAML
# ---------------------------------------------------------------------------


def test_load_invalid_yaml_raises_workflow_load_error(
    project_root: Path, contracts_root: Path
) -> None:
    # YAML with a tab in indentation + unmatched bracket → parse error.
    path = _write_workflow(project_root, "name: bad\nsteps:\n  - [unbalanced\n")
    with pytest.raises(WorkflowLoadError) as exc:
        load_workflow(path, contracts_root=contracts_root)
    assert isinstance(exc.value.__cause__, yaml.YAMLError)


# ---------------------------------------------------------------------------
# AC5: pydantic schema validation failure
# ---------------------------------------------------------------------------


def test_load_pydantic_validation_failure_wraps_with_workflow_load_error(
    project_root: Path, contracts_root: Path
) -> None:
    # Missing `name`, missing `version`. Workflow model requires both.
    path = _write_workflow(
        project_root,
        "steps:\n  - id: only-step\n    type: check\n    expr: 'True'\n",
    )
    with pytest.raises(WorkflowLoadError) as exc:
        load_workflow(path, contracts_root=contracts_root)
    assert isinstance(exc.value.__cause__, ValidationError)


def test_load_unknown_step_type_wraps_with_workflow_load_error(
    project_root: Path, contracts_root: Path
) -> None:
    body = """\
name: bad
version: 1
steps:
  - id: x
    type: not-a-real-type
"""
    path = _write_workflow(project_root, body)
    with pytest.raises(WorkflowLoadError) as exc:
        load_workflow(path, contracts_root=contracts_root)
    assert isinstance(exc.value.__cause__, ValidationError)


# ---------------------------------------------------------------------------
# AC1: happy path — full bugfix workflow
# AC2: round-trip integrity for one inline + one $contracts/<name> step
# ---------------------------------------------------------------------------


def test_load_bugfix_workflow_succeeds(
    project_root: Path, contracts_root: Path
) -> None:
    _write_contract(contracts_root, "review-verdict", REVIEW_VERDICT_CONTRACT_YAML)
    path = _write_workflow(project_root, BUGFIX_WORKFLOW_YAML, name="bugfix.yaml")

    loaded = load_workflow(path, contracts_root=contracts_root)

    assert isinstance(loaded, LoadedWorkflow)
    assert isinstance(loaded.workflow, Workflow)
    assert loaded.path == path
    assert loaded.workflow.name == "bugfix"
    # The contracts dict should have entries for every step that declared a
    # contract: fetch-issue, investigate, run-tests (inside loop), review.
    # Steps without contracts (worktree, check, the implement-loop step)
    # are absent.
    assert set(loaded.contracts) == {"fetch-issue", "investigate", "run-tests", "review"}
    # All values are Pydantic model classes.
    for cls in loaded.contracts.values():
        assert isinstance(cls, type)
        assert issubclass(cls, BaseModel)


def test_load_bugfix_workflow_inline_contract_round_trip(
    project_root: Path, contracts_root: Path
) -> None:
    _write_contract(contracts_root, "review-verdict", REVIEW_VERDICT_CONTRACT_YAML)
    path = _write_workflow(project_root, BUGFIX_WORKFLOW_YAML, name="bugfix.yaml")
    loaded = load_workflow(path, contracts_root=contracts_root)

    # Inline contract: fetch-issue declared `issue_id: string, title: string`.
    cls = loaded.contracts["fetch-issue"]
    instance = cls(issue_id="PROJ-1", title="hello")
    assert instance.issue_id == "PROJ-1"  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        cls(issue_id=123, title="hello")  # wrong type


def test_load_bugfix_workflow_shared_contract_round_trip(
    project_root: Path, contracts_root: Path
) -> None:
    _write_contract(contracts_root, "review-verdict", REVIEW_VERDICT_CONTRACT_YAML)
    path = _write_workflow(project_root, BUGFIX_WORKFLOW_YAML, name="bugfix.yaml")
    loaded = load_workflow(path, contracts_root=contracts_root)

    # Shared contract: review uses $contracts/review-verdict.
    cls = loaded.contracts["review"]
    instance = cls(status="PASS", issues=[])
    assert instance.status == "PASS"  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        cls(status="MAYBE", issues=[])  # not in enum


# ---------------------------------------------------------------------------
# AC6: $contracts/<name> reference whose file is missing
# ---------------------------------------------------------------------------


def test_load_unresolvable_contract_ref_raises_workflow_load_error(
    project_root: Path, contracts_root: Path
) -> None:
    body = """\
name: wf
version: 1
steps:
  - id: setup
    type: worktree
    action: create
    base: staging
    writes: []
  - id: s1
    type: script
    command: echo hi
    contract: $contracts/does-not-exist
    writes: [x]
"""
    path = _write_workflow(project_root, body)
    with pytest.raises(WorkflowLoadError) as exc:
        load_workflow(path, contracts_root=contracts_root)
    assert isinstance(exc.value.__cause__, ContractRefError)


# ---------------------------------------------------------------------------
# AC7: malformed inline contract surfaces ContractCompileError as cause
# ---------------------------------------------------------------------------


def test_load_malformed_inline_contract_raises_workflow_load_error(
    project_root: Path, contracts_root: Path
) -> None:
    body = """\
name: wf
version: 1
steps:
  - id: setup
    type: worktree
    action: create
    base: staging
    writes: []
  - id: s1
    type: script
    command: echo hi
    contract:
      bad: not-a-real-type
    writes: [bad]
"""
    path = _write_workflow(project_root, body)
    with pytest.raises(WorkflowLoadError) as exc:
        load_workflow(path, contracts_root=contracts_root)
    assert isinstance(exc.value.__cause__, ContractCompileError)


# ---------------------------------------------------------------------------
# AC8: writes references a field not declared in the contract
# ---------------------------------------------------------------------------


def test_load_writes_field_missing_from_contract_raises(
    project_root: Path, contracts_root: Path
) -> None:
    body = """\
name: wf
version: 1
steps:
  - id: setup
    type: worktree
    action: create
    base: staging
    writes: []
  - id: s1
    type: script
    command: echo hi
    contract:
      a: string
    writes: [a, ghost]
"""
    path = _write_workflow(project_root, body)
    with pytest.raises(WorkflowLoadError) as exc:
        load_workflow(path, contracts_root=contracts_root)
    msg = str(exc.value)
    assert "s1" in msg
    assert "ghost" in msg


# ---------------------------------------------------------------------------
# AC9: two steps writing the same field with conflicting types
# AC10: identical types load cleanly
# ---------------------------------------------------------------------------


def test_load_conflicting_writer_types_raises(
    project_root: Path, contracts_root: Path
) -> None:
    body = """\
name: wf
version: 1
steps:
  - id: setup
    type: worktree
    action: create
    base: staging
    writes: []
  - id: a
    type: script
    command: echo a
    contract:
      count: integer
    writes: [count]
  - id: b
    type: script
    command: echo b
    contract:
      count: string
    writes: [count]
"""
    path = _write_workflow(project_root, body)
    with pytest.raises(WorkflowLoadError) as exc:
        load_workflow(path, contracts_root=contracts_root)
    msg = str(exc.value)
    assert "count" in msg


def test_load_identical_writer_types_succeeds(
    project_root: Path, contracts_root: Path
) -> None:
    body = """\
name: wf
version: 1
steps:
  - id: setup
    type: worktree
    action: create
    base: staging
    writes: []
  - id: a
    type: script
    command: echo a
    contract:
      count: integer
    writes: [count]
  - id: b
    type: script
    command: echo b
    contract:
      count: integer
    writes: [count]
"""
    path = _write_workflow(project_root, body)
    loaded = load_workflow(path, contracts_root=contracts_root)
    assert "a" in loaded.contracts
    assert "b" in loaded.contracts


def test_load_conflicting_enum_types_raises(
    project_root: Path, contracts_root: Path
) -> None:
    """Strings with different `enum` lists count as different types — keep
    this strict. (Per the brief.)
    """
    body = """\
name: wf
version: 1
steps:
  - id: setup
    type: worktree
    action: create
    base: staging
    writes: []
  - id: a
    type: script
    command: echo a
    contract:
      verdict:
        type: string
        enum: [PASS, FAIL]
    writes: [verdict]
  - id: b
    type: script
    command: echo b
    contract:
      verdict:
        type: string
        enum: [GREEN, RED]
    writes: [verdict]
"""
    path = _write_workflow(project_root, body)
    with pytest.raises(WorkflowLoadError) as exc:
        load_workflow(path, contracts_root=contracts_root)
    assert "verdict" in str(exc.value)


# ---------------------------------------------------------------------------
# AC11: writes_files=true with no worktree.create ancestor → error
# AC12: worktree.create ancestor present → loads cleanly
# AC12 (loop variant): writes_files inside a loop whose ancestor is the
#   worktree at the top of the workflow.
# ---------------------------------------------------------------------------


def test_load_writes_files_without_worktree_ancestor_raises(
    project_root: Path, contracts_root: Path
) -> None:
    body = """\
name: wf
version: 1
steps:
  - id: a
    type: ai
    agent: claude
    prompt: prompts/x.j2
    writes_files: true
    writes: []
"""
    path = _write_workflow(project_root, body)
    with pytest.raises(WorkflowLoadError) as exc:
        load_workflow(path, contracts_root=contracts_root)
    msg = str(exc.value)
    assert "a" in msg
    assert "worktree" in msg


def test_load_writes_files_with_worktree_ancestor_succeeds(
    project_root: Path, contracts_root: Path
) -> None:
    body = """\
name: wf
version: 1
steps:
  - id: setup
    type: worktree
    action: create
    base: staging
    writes: []
  - id: middle
    type: script
    command: echo hi
    writes: []
  - id: writer
    type: ai
    agent: claude
    prompt: prompts/x.j2
    writes_files: true
    writes: []
"""
    path = _write_workflow(project_root, body)
    loaded = load_workflow(path, contracts_root=contracts_root)
    assert loaded.workflow.name == "wf"


def test_load_writes_files_inside_loop_with_outer_worktree_succeeds(
    project_root: Path, contracts_root: Path
) -> None:
    """A `writes_files: true` step inside a `loop:` is fine if the loop
    itself has a `worktree.create` ancestor — the worktree need not be
    inside the loop.
    """
    body = """\
name: wf
version: 1
steps:
  - id: setup
    type: worktree
    action: create
    base: staging
    writes: []
  - id: lp
    type: loop
    loop:
      max_iterations: 2
      until: state.done
      steps:
        - id: implement
          type: ai
          agent: claude
          prompt: prompts/x.j2
          writes_files: true
          writes: []
        - id: check-done
          type: script
          command: echo
          contract:
            done: boolean
          writes: [done]
"""
    path = _write_workflow(project_root, body)
    loaded = load_workflow(path, contracts_root=contracts_root)
    assert "check-done" in loaded.contracts


def test_load_writes_files_inside_loop_without_worktree_raises(
    project_root: Path, contracts_root: Path
) -> None:
    """Same loop scenario, but no worktree.create at all — must error."""
    body = """\
name: wf
version: 1
steps:
  - id: lp
    type: loop
    loop:
      max_iterations: 2
      until: state.done
      steps:
        - id: implement
          type: ai
          agent: claude
          prompt: prompts/x.j2
          writes_files: true
          writes: []
        - id: check-done
          type: script
          command: echo
          contract:
            done: boolean
          writes: [done]
"""
    path = _write_workflow(project_root, body)
    with pytest.raises(WorkflowLoadError) as exc:
        load_workflow(path, contracts_root=contracts_root)
    msg = str(exc.value)
    assert "implement" in msg
    assert "worktree" in msg


# ---------------------------------------------------------------------------
# AC13: decision actor:human → allowed at load time (H-2-002)
# Runner raises HumanDecisionRequested at execute time instead.
# ---------------------------------------------------------------------------


def test_load_decision_actor_human_succeeds(
    project_root: Path, contracts_root: Path
) -> None:
    """H-2-002: actor: human workflows now load without error.

    The runner raises HumanDecisionRequested at execute time; the loader
    no longer blocks these workflows at load time.
    """
    body = """\
name: wf
version: 1
steps:
  - id: ask-human
    type: decision
    actor: human
    message: "Approve?"
    on_reject: cancel
"""
    path = _write_workflow(project_root, body)
    loaded = load_workflow(path, contracts_root=contracts_root)
    assert loaded.workflow.name == "wf"


def test_load_decision_actor_llm_succeeds(
    project_root: Path, contracts_root: Path
) -> None:
    body = """\
name: wf
version: 1
steps:
  - id: setup
    type: worktree
    action: create
    base: staging
    writes: []
  - id: should-proceed
    type: decision
    actor: llm
    agent: claude
    prompt: prompts/x.j2
    contract:
      decision: boolean
      reasoning: string
    writes: [decision, reasoning]
"""
    path = _write_workflow(project_root, body)
    loaded = load_workflow(path, contracts_root=contracts_root)
    assert "should-proceed" in loaded.contracts


# ---------------------------------------------------------------------------
# AC14: a step with non-empty `writes:` but no `contract:` → error
# (writes: [] with no contract is fine — already exercised by happy path)
# ---------------------------------------------------------------------------


def test_load_writes_without_contract_raises(
    project_root: Path, contracts_root: Path
) -> None:
    body = """\
name: wf
version: 1
steps:
  - id: setup
    type: worktree
    action: create
    base: staging
    writes: []
  - id: bad
    type: script
    command: echo
    writes: [x]
"""
    path = _write_workflow(project_root, body)
    with pytest.raises(WorkflowLoadError) as exc:
        load_workflow(path, contracts_root=contracts_root)
    msg = str(exc.value)
    assert "bad" in msg


# ---------------------------------------------------------------------------
# Worktree steps may declare writes: without a contract:
# ---------------------------------------------------------------------------


def test_load_worktree_create_with_writes_succeeds(
    project_root: Path, contracts_root: Path
) -> None:
    """worktree.create may declare writes: [worktree_path, worktree_branch]
    without a contract: — the fields are framework-managed and bypass the
    normal contract → writes pathway.
    """
    body = """\
name: wf
version: 1
steps:
  - id: setup
    type: worktree
    action: create
    base: staging
    writes: [worktree_path, worktree_branch]
  - id: use-worktree
    type: script
    command: echo "$STATE_WORKTREE_PATH"
    writes: []
"""
    path = _write_workflow(project_root, body)
    loaded = load_workflow(path, contracts_root=contracts_root)
    assert loaded.workflow.name == "wf"
    # Worktree steps never appear in the contracts dict.
    assert "setup" not in loaded.contracts


def test_load_non_worktree_writes_without_contract_still_raises(
    project_root: Path, contracts_root: Path
) -> None:
    """The AC14 guard still fires for non-worktree steps.

    Worktree exemption applies only for WorktreeStep, not all step types.
    """
    body = """\
name: wf
version: 1
steps:
  - id: bad
    type: script
    command: echo
    writes: [x]
"""
    path = _write_workflow(project_root, body)
    with pytest.raises(WorkflowLoadError) as exc:
        load_workflow(path, contracts_root=contracts_root)
    assert "bad" in str(exc.value)


# ---------------------------------------------------------------------------
# `contracts_root` defaults to <workflow>/../../contracts
# ---------------------------------------------------------------------------


def test_load_contracts_root_defaults_to_sibling_dir(project_root: Path) -> None:
    """When `contracts_root` is omitted, the loader resolves to
    `path.parent.parent / "contracts"` — the project layout."""
    _write_contract(
        project_root / "contracts", "review-verdict", REVIEW_VERDICT_CONTRACT_YAML
    )
    path = _write_workflow(project_root, BUGFIX_WORKFLOW_YAML, name="bugfix.yaml")
    loaded = load_workflow(path)  # no contracts_root kwarg
    assert "review" in loaded.contracts


# ---------------------------------------------------------------------------
# WorkflowLoadError is itself a ValueError so callers can catch broadly.
# ---------------------------------------------------------------------------


def test_workflow_load_error_is_value_error() -> None:
    assert issubclass(WorkflowLoadError, ValueError)


# ---------------------------------------------------------------------------
# Misc: explicit unused-import guard so ruff doesn't strip what we use.
# ---------------------------------------------------------------------------


def test_module_exports_present() -> None:
    """Tiny sanity check that the public API names are importable from the
    module — pins the API surface."""
    from harness.workflow import loader

    for name in ("LoadedWorkflow", "WorkflowLoadError", "load_workflow"):
        assert hasattr(loader, name), name


# Keep imports referenced even if any individual assertion path is skipped.
_ = (Any,)


# ---------------------------------------------------------------------------
# Item 2: $inputs.* in unsupported surfaces
# ---------------------------------------------------------------------------


def test_inputs_ref_in_script_command_raises_load_error(
    project_root: Path, contracts_root: Path
) -> None:
    path = _write_workflow(
        project_root,
        """\
name: bad-command
version: 1
steps:
  - id: run-test
    type: script
    command: scripts/deploy.sh $inputs.env
    writes: []
""",
    )
    with pytest.raises(WorkflowLoadError, match="run-test") as exc:
        load_workflow(path, contracts_root=contracts_root)
    msg = str(exc.value)
    assert "$inputs" in msg or "inputs" in msg
    assert "command" in msg


def test_inputs_ref_in_check_expr_raises_load_error(
    project_root: Path, contracts_root: Path
) -> None:
    path = _write_workflow(
        project_root,
        """\
name: bad-check
version: 1
steps:
  - id: gate
    type: check
    expr: "$inputs.flag == True"
    on_fail: cancel
""",
    )
    with pytest.raises(WorkflowLoadError, match="gate") as exc:
        load_workflow(path, contracts_root=contracts_root)
    msg = str(exc.value)
    assert "$inputs" in msg or "inputs" in msg
    assert "expr" in msg


def test_inputs_ref_in_loop_until_expression_raises_load_error(
    project_root: Path, contracts_root: Path
) -> None:
    path = _write_workflow(
        project_root,
        """\
name: bad-until
version: 1
steps:
  - id: my-loop
    type: loop
    loop:
      max_iterations: 5
      until: "$inputs.done == True"
      steps:
        - id: tick
          type: script
          command: echo hi
          writes: []
""",
    )
    with pytest.raises(WorkflowLoadError, match="my-loop") as exc:
        load_workflow(path, contracts_root=contracts_root)
    msg = str(exc.value)
    assert "$inputs" in msg or "inputs" in msg
    assert "until" in msg


def test_inputs_ref_in_args_does_not_raise(
    project_root: Path, contracts_root: Path
) -> None:
    """$inputs.* in args: is the correct pattern and must not raise."""
    path = _write_workflow(
        project_root,
        """\
name: ok-args
version: 1
steps:
  - id: run
    type: script
    command: scripts/deploy.sh
    args: ["$inputs.env"]
    writes: []
""",
    )
    # Must not raise.
    loaded = load_workflow(path, contracts_root=contracts_root)
    assert loaded is not None


def test_inputs_ref_in_until_bash_does_not_raise(
    project_root: Path, contracts_root: Path
) -> None:
    """$inputs.* in until_bash: is the correct pattern and must not raise."""
    path = _write_workflow(
        project_root,
        """\
name: ok-until-bash
version: 1
steps:
  - id: wait-loop
    type: loop
    loop:
      max_iterations: 10
      until_bash: "[ -f $inputs.output_path ]"
      steps:
        - id: poll
          type: script
          command: sleep 1
          writes: []
""",
    )
    loaded = load_workflow(path, contracts_root=contracts_root)
    assert loaded is not None
