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
import re
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


# ---------------------------------------------------------------------------
# CAL-601 — the engine-era Linear webhook intake (``intake/``) is retired.
# ---------------------------------------------------------------------------
#
# ``intake/linear_webhook.py`` was an HTTP server that *listened* for Linear
# webhooks and autonomously *spawned* work — the engine-era "the harness is
# autonomous" pattern the verb model rejects (SPEC §47/§52: triggers are
# external; the harness does not listen). CAL-574 retired the engine but missed
# this standalone sibling module, which has shelled out to the deleted
# ``harness run`` ever since. CAL-601 removes it. This guard is the executable
# completeness check: the module is gone, and no living doc / build-config
# re-introduces a reference to it.
#
# Scope note: this guard is deliberately *intake-specific*. The wider
# retirement-completeness guard (the engine-era ``harness run <workflow>`` /
# ``harness validate`` CLI surface and the SPEC §4/§11 prose) is CAL-603's
# deliverable, sequenced after this change — see CAL-603's 2026-06-12 decision.

INTAKE_MODULES = ["intake", "intake.linear_webhook"]


@pytest.mark.parametrize("module", INTAKE_MODULES)
def test_intake_package_not_importable(module: str) -> None:
    """The Linear webhook intake package is no longer importable."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


def test_intake_files_removed() -> None:
    """The intake module and its (false-green) test file are gone from disk."""
    assert not (_REPO_ROOT / "intake").exists()
    assert not (_REPO_ROOT / "tests" / "unit" / "test_linear_webhook.py").exists()


# Matches a reference to the *module* — its path, a dotted import of one of its
# attributes (``intake.cancel_run``), the ``python -m`` form, or the mypy scope
# that named it — not the English word "intake" (e.g. "Linear is intake",
# "Stage 1: intake / worktree"), which legitimately survives. The dot/slash is
# load-bearing: prose never writes ``intake.`` or ``intake/``.
_INTAKE_MODULE_PATTERN = re.compile(
    r"intake/|intake\.[A-Za-z_]|python -m intake|harness intake\b"
)

# Discover every living doc / spec / build-config rather than name a hand-picked
# allowlist — an incomplete six-file allowlist let ``specs/state-store.md``'s
# ``intake.cancel_run`` reference slip through review (CAL-601). Discovery scans
# all tracked Markdown plus the two build configs that named the module.
#
# Point-in-time records are history, not living guidance, and are excluded:
# ``assessments/`` (dated code assessments) and ``lessons/`` (captured run
# logs). Hidden / generated trees (``.venv``, ``.git``, ``.pytest_cache`` …)
# and vendored ``node_modules`` are excluded too.
_HISTORY_SEGMENTS = {"assessments", "lessons"}
_EXTRA_CONFIG_DOCS = ["pyproject.toml", "scripts/verify.sh"]


def _living_doc_relpaths() -> list[str]:
    """All living Markdown docs + build configs a regression would touch."""
    rels: list[str] = []
    for path in sorted(_REPO_ROOT.rglob("*.md")):
        parts = path.relative_to(_REPO_ROOT).parts
        if any(
            p in _HISTORY_SEGMENTS or p == "node_modules" or p.startswith(".")
            for p in parts
        ):
            continue
        rels.append(str(path.relative_to(_REPO_ROOT)))
    rels.extend(_EXTRA_CONFIG_DOCS)
    return rels


@pytest.mark.parametrize("relpath", _living_doc_relpaths())
def test_living_docs_have_no_intake_module_reference(relpath: str) -> None:
    """No living doc / build-config references the retired intake module."""
    text = (_REPO_ROOT / relpath).read_text()
    matches = _INTAKE_MODULE_PATTERN.findall(text)
    assert not matches, f"{relpath} still references retired intake module: {matches}"


def _living_source_relpaths() -> list[str]:
    """Tracked package source (``harness/``) — the shipped, living code.

    ``tests/`` is excluded on purpose: this guard and its fixtures legitimately
    spell the retired names (``INTAKE_MODULES``, the pattern literals), so
    scanning them would self-trip.
    """
    pkg = _REPO_ROOT / "harness"
    return [
        str(p.relative_to(_REPO_ROOT))
        for p in sorted(pkg.rglob("*.py"))
        if "__pycache__" not in p.parts
    ]


@pytest.mark.parametrize("relpath", _living_source_relpaths())
def test_living_source_has_no_intake_module_reference(relpath: str) -> None:
    """No living package source narrates the retired intake module.

    The ``ModuleNotFoundError`` import guards above cannot catch a *prose*
    reference — a docstring or comment that names ``intake.cancel_run`` is a
    dangling pointer no import check sees. This closes that gap for the shipped
    package (caught a stale ``cancel.py`` docstring in CAL-601 review).
    """
    text = (_REPO_ROOT / relpath).read_text()
    matches = _INTAKE_MODULE_PATTERN.findall(text)
    assert not matches, f"{relpath} still references retired intake module: {matches}"
