"""CAL-574 acceptance checks — the deterministic workflow engine is retired.

These tests are the executable form of the ticket's acceptance criteria:

* **AC-1** — the verbs operate with no dependency on the YAML-walking engine
  (``engine.runner|executor|loop|retry``) or the node protocol (``harness.nodes``
  / ``harness.workflow``). Expressed as an import-graph check: the verb modules
  import cleanly, and the retired modules are no longer importable.
* **AC-2** — ``build*.yaml`` and the workflow-walking modules are gone.
* **AC-3** — release and steward behaviour survives the engine retirement and
  carries its load-bearing steps. CAL-574 first parked both as agent-task docs
  under ``agents/tasks/``; CAL-716 eliminated that redundant layer, so the
  behaviour now lives in its durable home — the steward procedure folded into
  ``agents/steward.md``, the release procedure folded into ``RELEASING.md`` (a
  task = command + role + skill + template, never a ``tasks/`` file; see
  ``specs/architecture-principles.md``).

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


def test_package_docstring_describes_verb_model_not_engine() -> None:
    """The package's own docstring names the current verb model, not the retired engine.

    CAL-574 retired the deterministic workflow engine; SPEC §1–2 and CONTEXT.md
    now describe the harness as "deterministic, audited verbs an agent calls — not
    an engine that drives agents." A live docstring that still calls the package a
    "workflow execution engine" re-asserts the retired model as the package's
    *current* identity (CODE-1, 2026-06-13 assessment). Other live modules frame the
    engine correctly in the past tense ("the engine was retired in CAL-574"); only the
    top-level package self-description regressed. This guard is scoped to that single
    package docstring — the broader retired-§ docstring-cite class is CAL-633/CAL-636.
    """
    import harness

    doc = harness.__doc__ or ""
    assert "execution engine" not in doc.lower(), (
        "harness/__init__.py still calls the package a 'workflow execution engine' — "
        "the model retired in CAL-574. Describe the current verb model instead."
    )
    assert "verb" in doc.lower(), (
        "the package docstring should name the current verb model "
        "(SPEC §1–2: deterministic, audited verbs an agent calls)."
    )


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


# A live-source *citation* of a retired build workflow by name — ``build.yaml``
# or ``build-codex.yaml``. ``test_build_yaml_removed`` guards that the *files* are
# gone; this guards that no docstring/comment still *points a reader at* them.
# A cite into a deleted artifact is worse than no cite — it sends a reader to
# prose that no longer exists (the same class ``test_retired_spec_cites.py``
# eliminated for retired SPEC sections, CAL-633). One pattern covers both names:
# ``build`` + optional ``-codex`` + ``.yaml``.
_RETIRED_BUILD_YAML_CITE = re.compile(r"\bbuild(?:-codex)?\.yaml\b")

# The boundary contract, pinned by example (mirrors test_retired_spec_cites.py).
_BUILD_YAML_MATCH = [
    "matching the build-codex.yaml logic",  # the linear.py docstring cite
    "Mirrors ``build-codex.yaml``.",        # the linear.py _transition cite
    "see workflows/build.yaml",             # path-qualified bare form
    "build.yaml",                           # bare filename
]
_BUILD_YAML_NO_MATCH = [
    "build a yaml document",     # prose that is not a filename cite
    "buildable.yamlish config",  # not the retired filename
    "rebuild.yaml is unrelated", # different filename (no word boundary before build)
]


@pytest.mark.parametrize("sample", _BUILD_YAML_MATCH)
def test_retired_build_yaml_cite_regex_matches(sample: str) -> None:
    assert _RETIRED_BUILD_YAML_CITE.search(sample), (
        f"{sample!r} should be flagged as a retired build-workflow cite"
    )


@pytest.mark.parametrize("sample", _BUILD_YAML_NO_MATCH)
def test_retired_build_yaml_cite_regex_ignores_non_cites(sample: str) -> None:
    assert not _RETIRED_BUILD_YAML_CITE.search(sample), f"{sample!r} must not be flagged"


def test_no_live_harness_source_cites_a_retired_build_yaml() -> None:
    """No git-tracked ``harness/**/*.py`` names the retired ``build*.yaml`` workflows.

    The deterministic build workflows (``build.yaml`` / ``build-codex.yaml``) were
    deleted with the engine (CAL-574); the verb model that replaced them is
    self-contained. A docstring or comment that still says the code "mirrors
    build-codex.yaml" cross-refers a reader to a file that no longer exists —
    ``test_build_yaml_removed`` only proves the file is gone, not that nothing
    points at it. This sweep closes that gap, the same way
    ``test_retired_spec_cites.py`` did for retired SPEC sections.
    """
    violations: list[str] = []
    for path in sorted(tracked_files_under("harness")):
        if path.suffix != ".py":
            continue
        for line_no, line in enumerate(path.read_text().splitlines(), start=1):
            if _RETIRED_BUILD_YAML_CITE.search(line):
                violations.append(f"{path.name}:{line_no}: {line.strip()}")

    assert not violations, (
        "live harness/ source cites a retired build workflow (build.yaml / "
        "build-codex.yaml were deleted with the engine in CAL-574; the verb "
        "model is self-contained):\n  " + "\n  ".join(violations)
    )


# ---------------------------------------------------------------------------
# AC-3 — release & steward behaviour survives the engine retirement in its
# durable home (CAL-574 parked it under agents/tasks/; CAL-716 folded it in).
# ---------------------------------------------------------------------------


def test_release_procedure_survives_in_releasing_doc() -> None:
    """The release procedure survives in ``RELEASING.md`` with its key steps.

    CAL-574 converted ``release.yaml`` to ``agents/tasks/release.md``; CAL-716
    folded it into ``RELEASING.md`` (the durable home) and deleted the task file.
    The load-bearing mechanics — summarise completed Linear tickets into release
    notes, then raise the ``dev → main`` PR — must survive the move.
    """
    text = (_REPO_ROOT / "RELEASING.md").read_text()
    lowered = text.lower()
    assert "release notes" in lowered  # summarise the shipped tickets
    assert "linear" in lowered  # fetch the completed tickets (via the linear skill)
    assert "gh pr create" in text  # raise the dev -> main PR
    # The eliminated task file must be gone (CAL-716).
    assert not (_REPO_ROOT / "agents" / "tasks" / "release.md").exists()


def test_steward_procedure_survives_in_steward_agent() -> None:
    """The steward review survives in ``agents/steward.md`` with its key steps.

    CAL-574 converted ``steward.yaml`` to ``agents/tasks/steward.md``; CAL-716
    folded the procedure into ``agents/steward.md`` (dropping the dangling
    pointer) and deleted the task file. The three-phase shape — read/summarise →
    assess → report — must survive the move.
    """
    text = (_REPO_ROOT / "agents" / "steward.md").read_text()
    lowered = text.lower()
    assert "summar" in lowered  # read & summarise the scope
    assert "assess" in lowered  # assess against the domain standards
    assert "report" in lowered  # write the dated report
    # The eliminated task file must be gone (CAL-716).
    assert not (_REPO_ROOT / "agents" / "tasks" / "steward.md").exists()


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


# ---------------------------------------------------------------------------
# CAL-693 — the dormant engine-era worktree-cleanup surface is removed.
# ---------------------------------------------------------------------------
#
# ``harness.worktree`` was re-homed as a verb helper (``WorktreeNode.create``
# survives — ``harness start`` calls it). But the ``cleanup`` half — the
# ``CleanupPolicy`` Literal, the three policy implementations
# (``merge_to_base`` / ``leave_for_inspection`` / ``delete_unconditionally``),
# and the ``WorktreeCleanupOutput`` model — was the retired engine's
# ``worktree.cleanup`` *node*. It has had no production caller after CAL-574:
# ``harness start``'s rollback (``_cleanup_worktree_sync``), ``harness close``'s
# merge, and ``harness worktrees cleanup`` all run direct git, not the policy
# machinery, which was exercised only by its own unit tests. Same dead-surface
# class as ``test_dead_state_surface_removed`` (CAL-613): a module surviving
# "imports cleanly" is not the same as its whole API surviving. AC-4 retires it.


def test_dead_worktree_cleanup_surface_removed() -> None:
    """The engine-era ``cleanup`` policy machinery is gone from ``harness.worktree``."""
    from harness import worktree

    removed = ["CleanupPolicy", "WorktreeCleanupOutput"]
    present = [name for name in removed if hasattr(worktree, name)]
    assert not present, (
        f"harness.worktree still exposes the retired cleanup surface: {present}. "
        "The CleanupPolicy machinery had no production caller after CAL-574 "
        "(start/close/worktrees use direct git) — delete it with its tests (AC-4)."
    )

    assert not hasattr(worktree.WorktreeNode, "cleanup"), (
        "WorktreeNode.cleanup is the retired engine's worktree.cleanup node with no "
        "live caller — delete it (CAL-693, AC-4)."
    )

    # The create half is the live verb helper — it must survive.
    assert hasattr(worktree.WorktreeNode, "create"), (
        "WorktreeNode.create must survive — harness start calls it"
    )
    for name in ("WorktreeCreateOutput", "WorktreeNodeError", "worktree_path"):
        assert hasattr(worktree, name), (
            f"worktree.{name} must survive — it is the live create surface"
        )


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
# ``assessments/`` (dated code assessments), ``lessons/`` (captured run logs),
# and ``CHANGELOG-archive/`` (released CHANGELOG entries rotated out of the root
# file, CAL-1011). Hidden / generated trees (``.venv``, ``.git``,
# ``.pytest_cache`` …) and vendored ``node_modules`` are excluded too.
_HISTORY_SEGMENTS = {"assessments", "lessons", "CHANGELOG-archive"}
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


# ---------------------------------------------------------------------------
# CAL-632 — live module docstrings cite their as-built §4.x home, not a
# retired SPEC section.
#
# The SPEC.md currency map (header + the §3 banner) declares §1–2, §4 and §11
# current, and §3, §5–§10, §12–§14 the retired deterministic engine. Two live
# modules opened their docstring with a cross-ref into the retired range
# (``worktree.py`` → §9, ``identity.py`` → §8) when each has a verbatim as-built
# home in §4 (§4.5 ``harness.worktree``, §4.8 ``harness.identity``). A reader
# following the stale cite lands in retired engine prose. Same defect class as
# the shipped CAL-629 (``_time.py`` → §12). This guard locks the two clean
# fixes; the wider cluster (§6/§7/§12 cites with no clean §4.x home) is CAL-633.
# ---------------------------------------------------------------------------

# (module import path, as-built §4.x home it must cite, retired § it must not).
_DOCSTRING_SECTION_CASES = [
    ("harness.worktree", "4.5", "9"),
    ("harness.identity", "4.8", "8"),
]


@pytest.mark.parametrize("module, current, retired", _DOCSTRING_SECTION_CASES)
def test_module_docstring_cites_asbuilt_section(
    module: str, current: str, retired: str
) -> None:
    """Each module docstring cross-refs its current §4.x home, not a retired §."""
    doc = importlib.import_module(module).__doc__ or ""
    assert f"SPEC §{current}" in doc, (
        f"{module} docstring should cite its as-built home SPEC §{current}; got: {doc!r}"
    )
    assert not re.search(rf"SPEC §{retired}\b", doc), (
        f"{module} docstring still cites retired SPEC §{retired} — point it at "
        f"§{current} (the as-built home; §{retired} describes the retired engine)."
    )
