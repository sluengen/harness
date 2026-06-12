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
import importlib.util
import re
from pathlib import Path

import pytest

from tests._gitutil import tracked_files_under

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


def test_cancel_docstring_cites_current_verb_contract_section() -> None:
    """``cancel.py`` cites the *current* §1 for the public verb contract.

    CAL-638 (CODE-2). The ``harness.cli.cancel`` module docstring summarised the
    verb's purpose as keeping "the public verb contract (SPEC §5)". §5 is part of
    the retired deterministic-engine block (superseded per SPEC.md's status
    banner); the public-verb-contract principle lives in the *current* §1 Core
    principles (#5, "The verb surface is a public contract"). This is a cite-only
    drift, distinct from the parked retired-§ docstring cluster (CAL-633/636):
    §1 is the unambiguous, uncontested home for *this* phrase. The companion
    ``SPEC §11`` exit-codes cite is correct (§11 CLI Design is current) and is
    intentionally left untouched.
    """
    src = (_REPO_ROOT / "harness" / "cli" / "cancel.py").read_text()
    # The retired §5 cite for the verb contract is gone.
    assert "public verb contract (SPEC §5)" not in src
    # It now cites the current §1 home.
    assert "public verb contract (SPEC §1)" in src


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
    """The deterministic build workflows no longer exist in the tracked tree."""
    assert tracked_files_under(f"workflows/{yaml_name}") == set()
    assert tracked_files_under(f"harness/workflows/{yaml_name}") == set()


def test_workflow_package_dir_removed() -> None:
    """The bundled-workflow package directory is gone from the tracked tree."""
    assert tracked_files_under("harness/workflows") == set()


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
# CAL-613 — the engine-era per-node state/snapshot surface is removed.
# ---------------------------------------------------------------------------
#
# ``harness.state.store`` was re-homed as a verb helper (it survives in
# VERB_MODULES above as an import-clean re-home). But its *public functions* —
# ``read_state`` / ``update_state`` / ``restore_state`` / ``write_snapshot`` /
# ``read_latest_snapshot`` plus the ``run_snapshots`` table — were the retired
# engine's per-node state machine and the never-shipped v2-resume snapshot
# layer (SPEC §6/§7, superseded). They had no production caller after CAL-574;
# the verb model holds context in the agent session, not a rehydrated state row
# (CAL-585 AC-2). A module surviving "imports cleanly" is not the same as its
# whole API surviving — a function exercised only by its own unit test is dead
# surface, not a helper. This guard asserts the dead surface is gone (the
# connection + schema + migration surface stays).


def test_dead_state_surface_removed() -> None:
    """The engine-era state read/write + snapshot functions are gone from store."""
    from harness.state import store

    removed = [
        "read_state",
        "update_state",
        "restore_state",
        "write_snapshot",
        "read_latest_snapshot",
        "StateStoreError",
        "store_connection",
        "NOTES_MAX_ENTRIES",
        "NOTES_MAX_CHARS",
    ]
    present = [name for name in removed if hasattr(store, name)]
    assert not present, (
        f"harness.state.store still exposes retired engine-era state surface: {present}. "
        "These functions had no production caller after CAL-574 — delete them with their tests."
    )

    # The connection + schema + migration surface is what survives.
    for name in ("connect", "init_db", "DEFAULT_DB_PATH"):
        assert hasattr(store, name), f"store.{name} must survive — it is the live ledger surface"


async def test_run_snapshots_table_not_created(tmp_path: Path) -> None:
    """init_db no longer creates the never-shipped run_snapshots snapshot table."""
    from harness.state import store

    db_path = tmp_path / "harness.db"
    await store.init_db(db_path)
    async with store.connect(db_path) as conn, conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ) as cur:
        tables = {row[0] async for row in cur}
    assert "run_snapshots" not in tables, (
        "run_snapshots is the retired v2-resume snapshot table with no production writer; "
        f"init_db must not create it. Found tables: {sorted(tables)}"
    )
    assert {"runs", "events"} <= tables, "the runs + events ledger tables must survive"


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
    """No real intake module is importable — robust to a stale ``__pycache__``.

    A bare leftover ``intake/__pycache__`` (bytecode for the deleted source)
    makes ``intake`` resolvable as a PEP 420 *namespace* package — no
    ``__init__.py`` required — which fails a plain ``import intake`` guard on an
    otherwise-clean checkout (the second half of CODE-3, alongside
    ``test_intake_files_removed``). The retirement contract is narrower: no
    importable intake *source*. So we assert the module either does not resolve
    at all, or resolves only as an empty namespace package (``origin`` is
    ``None`` — no code to run). A surviving ``intake/__init__.py`` or
    ``intake/*.py`` has a concrete ``origin`` and still fails here.
    """
    try:
        spec = importlib.util.find_spec(module)
    except ModuleNotFoundError:
        spec = None  # a parent package is itself gone — nothing importable
    assert spec is None or spec.origin in (None, "namespace"), (
        f"{module} resolves to importable source at {spec.origin!r}; "
        "the intake package source must be gone from the import path."
    )


def test_intake_files_removed() -> None:
    """The intake module and its (false-green) test file are gone from the tracked tree.

    Asserting over the *tracked* set, not ``Path.exists()``, is deliberate: a
    stale ``intake/__pycache__`` left over from the deleted source kept the
    working-tree directory alive and turned this guard red on a clean checkout
    (CODE-3). ``git ls-files`` reports only the committed tree, so leftover
    bytecode no longer fools the check.
    """
    assert tracked_files_under("intake") == set()
    assert tracked_files_under("tests/unit/test_linear_webhook.py") == set()


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
