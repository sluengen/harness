"""CAL-574 acceptance checks — the deterministic workflow engine is retired.

These tests are the executable form of the ticket's acceptance criteria:

* **AC-1** — the verbs operate with no dependency on the YAML-walking engine
  (``engine.runner|executor|loop|retry``) or the node protocol (``harness.nodes``
  / ``harness.workflow``). Expressed as an import-graph check: the verb modules
  import cleanly, and the retired modules are no longer importable.
* **AC-2** — ``build*.yaml`` and the workflow-walking modules are gone.
* **AC-3** — release and steward behaviour survives via the agent-task path
  (the converted task docs exist and carry their load-bearing steps).

The check is deliberately structural: a regression that re-introduces a verb's
dependency on the engine, or that resurrects a deleted module, fails here.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# AC-1 — the verbs import clean and carry no engine / node-protocol dependency.
# ---------------------------------------------------------------------------

# Every verb module the orchestrating agent shells out to, plus the CLI app
# that wires them together. Importing the app transitively imports every
# registered command, so a lingering engine import would surface here.
VERB_MODULES = [
    "harness.cli",
    "harness.cli.start",
    "harness.cli.review",
    "harness.cli.close",
    "harness.cli.cancel",
    "harness.cli.query",
    "harness.cli.doctor",
    "harness.cli.worktrees",
    "harness.cli.version",
    "harness.worktree",  # re-homed worktree lifecycle
    "harness.state.store",
    "harness.events.emitter",
    "harness.identity",
    "harness.linear",
]

# The retired surface — the YAML-walking engine, the node-type protocol, the
# workflow schema/loader/contract/derive, agent dispatch, and the decision
# pause/resume machinery. None may be importable after retirement.
RETIRED_MODULES = [
    "harness.engine",
    "harness.engine.runner",
    "harness.engine.executor",
    "harness.engine.loop",
    "harness.engine.retry",
    "harness.engine.progress",
    "harness.nodes",
    "harness.nodes.base",
    "harness.nodes.ai",
    "harness.nodes.check",
    "harness.nodes.decision",
    "harness.nodes.script",
    "harness.nodes.worktree",
    "harness.workflow",
    "harness.workflow.loader",
    "harness.workflow.schema",
    "harness.workflow.contract",
    "harness.workflow.derive",
    "harness.workflow.resolver",
    "harness.workflows",
    "harness.dispatch",
    "harness.decisions",
    "harness.cli.run",
    "harness.cli.decisions",
    "harness.cli.validate",
]


@pytest.mark.parametrize("module", VERB_MODULES)
def test_verb_modules_import_clean(module: str) -> None:
    """Each verb (and the CLI app) imports without dragging in the engine."""
    assert importlib.import_module(module) is not None


@pytest.mark.parametrize("module", RETIRED_MODULES)
def test_retired_modules_are_gone(module: str) -> None:
    """The YAML-walking engine and node protocol are no longer importable."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


def test_cli_app_exposes_verbs_not_run() -> None:
    """The CLI app keeps the verb surface and drops the YAML ``run`` command."""
    from harness.cli import app

    names = {
        cmd.name
        for cmd in app.registered_commands
        if cmd.name is not None
    }
    # Verbs survive.
    assert {"start", "review", "close"}.issubset(names)
    # The YAML walker entry and its static validator are gone.
    assert "run" not in names
    assert "validate" not in names


# ---------------------------------------------------------------------------
# AC-2 — build*.yaml and the workflow-walking modules are removed.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("yaml_name", ["build.yaml", "build-codex.yaml"])
def test_build_yaml_removed(yaml_name: str) -> None:
    """The deterministic build workflows no longer exist on disk."""
    assert not (_REPO_ROOT / "workflows" / yaml_name).exists()
    assert not (_REPO_ROOT / "harness" / "workflows" / yaml_name).exists()


def test_workflow_package_dir_removed() -> None:
    """The bundled-workflow package directory is gone."""
    assert not (_REPO_ROOT / "harness" / "workflows").exists()


# ---------------------------------------------------------------------------
# AC-3 — release & steward behaviour is available via the agent-task path.
# ---------------------------------------------------------------------------


def test_release_agent_task_present() -> None:
    """The release procedure survives as an agent-task doc with its key steps."""
    doc = _REPO_ROOT / "agents" / "tasks" / "release.md"
    assert doc.exists()
    text = doc.read_text()
    # Load-bearing mechanics from the old release.yaml.
    assert "api.linear.app/graphql" in text  # fetch closed tickets
    assert "gh pr create" in text  # raise the dev -> main PR


def test_steward_agent_task_present() -> None:
    """The steward review survives as an agent-task doc with its key steps."""
    doc = _REPO_ROOT / "agents" / "tasks" / "steward.md"
    assert doc.exists()
    text = doc.read_text()
    # The three-phase shape of the old steward.yaml: read -> assess -> report.
    lowered = text.lower()
    assert "summary" in lowered
    assert "findings" in lowered
    assert "report" in lowered


# ---------------------------------------------------------------------------
# AC-4 — status --json surfaces only artifact fields the state schema declares.
#
# ``_ARTIFACT_KEYS`` drives the ``artifact_paths`` enrichment in
# ``status --json``. Because ``BaseState`` sets ``extra="forbid"``, a validated
# state can only ever carry keys that ``BaseState`` declares — any other key is
# dead enrichment that no live run can populate, kept green only by a test that
# fabricates the field. This guard turns the CAL-600 "no synthetic data masking
# dead surface" principle into a failing test (would have caught CAL-607).
# ---------------------------------------------------------------------------


def test_artifact_keys_are_declared_state_fields() -> None:
    """Every ``_ARTIFACT_KEYS`` entry is a field the state schema declares."""
    from harness.cli.query import _ARTIFACT_KEYS
    from harness.state.schema import BaseState

    declared = set(BaseState.model_fields)
    undeclared = [k for k in _ARTIFACT_KEYS if k not in declared]
    assert not undeclared, (
        f"_ARTIFACT_KEYS contains keys no state class declares: {undeclared}. "
        "BaseState forbids extra fields, so these can never populate from a real "
        "run — they are dead enrichment. Add the field to BaseState (and a verb "
        "that writes it) before surfacing it, or drop it from _ARTIFACT_KEYS."
    )
