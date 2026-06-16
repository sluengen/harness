"""CAL-712 — the Hermes/launcher scaffolding subsystem is retired.

The host-launcher control socket and the autonomous-dispatch *trigger* (~990
LOC) implemented a runtime for a "Hermes" dispatcher that does not exist and is
explicitly deferred (``specs/architecture-principles.md``: *"we are not running
deterministic autonomy"*). Inert code that reads as operational is what invites
an agent to extend a world the repo does not inhabit (SYSTEM-1 / INSIGHT-1).
Owner decision 2026-06-15: **quarantine + defer** — delete the scaffolding,
preserve the *design* as a retired spec, defer building the dispatcher itself.

These tests are the executable form of the ticket's acceptance criteria:

* **AC-1** — the launcher / trigger / serve modules are unimportable and their
  source + dedicated test files are gone from the tracked tree.
* **AC-2** — ``hermes-orchestration.md`` no longer presents as live: it is
  relocated under ``specs/retired/``, its title is not ``(live)``, and it carries
  a dated supersede banner.
* **AC-3** — ``query_status`` drops the Hermes-only observability synthesis
  (``agent_session_ids`` / ``failure_retryable``) and ``runs`` drops ``--failed``.
* **AC-4** — the ``--repo`` workspace allowlist is preserved (it is load-bearing
  on every verb via ``cli/_repo.py``), not collateral of the deletion.
* **AC-5** — the scaffolding-labeling convention is encoded as a guard: a spec
  titled ``(live)`` must describe a subsystem with at least one **non-test**
  caller, and a spec under ``specs/retired/`` may not be titled ``(live)``. This
  is the INSIGHT-1 deliverable: not-yet-built capability lives under a
  clearly-deferred path, and its code has no live (non-test) caller.
"""

from __future__ import annotations

import importlib
import inspect
import re
from pathlib import Path

import pytest

from tests._gitutil import tracked_files_under

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# AC-1 — the launcher / trigger / serve subsystem is gone.
# ---------------------------------------------------------------------------

#: The retired scaffolding modules — the host-launcher control socket
#: (``launcher`` / ``launcher_client`` / the ``serve`` command) and the
#: autonomous-dispatch ``trigger`` stand-in. None may be importable.
_RETIRED_MODULES = [
    "harness.launcher",
    "harness.launcher_client",
    "harness.trigger",
    "harness.cli.serve",
]

#: Source + dedicated test files removed with the subsystem. Asserted over the
#: *tracked* tree (``git ls-files``) per the CAL-619 git-aware-guard principle:
#: a file gone from the index must read as gone even if stale bytecode lingers.
_REMOVED_PATHS = [
    "harness/launcher.py",
    "harness/launcher_client.py",
    "harness/trigger.py",
    "harness/cli/serve.py",
    "tests/unit/test_launcher.py",
    "tests/unit/test_launcher_client.py",
    "tests/unit/test_cli_serve.py",
    "tests/unit/test_trigger.py",
    "tests/integration/test_launcher_socket.py",
    "tests/integration/test_launcher_client.py",
    "tests/integration/test_hermes_demo.py",
]


@pytest.mark.parametrize("module", _RETIRED_MODULES)
def test_launcher_subsystem_is_unimportable(module: str) -> None:
    """The launcher / trigger / serve modules are no longer importable."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


@pytest.mark.parametrize("relpath", _REMOVED_PATHS)
def test_launcher_subsystem_files_removed(relpath: str) -> None:
    """The launcher / trigger / serve source + test files are gone from the tree."""
    assert tracked_files_under(relpath) == set(), (
        f"{relpath} must be removed — it is the retired Hermes scaffolding (CAL-712)."
    )


def test_serve_command_not_registered() -> None:
    """The ``serve`` command (the launcher control socket) is unregistered."""
    from harness.cli import app

    names = {c.name for c in app.registered_commands if c.name is not None}
    assert "serve" not in names, (
        "harness serve runs the retired launcher control socket — unregister it (CAL-712)."
    )


# ---------------------------------------------------------------------------
# AC-2 — the spec no longer presents as live.
# ---------------------------------------------------------------------------

#: A dated supersede banner near the top of a file — the same recognition
#: ``test_docs_consistency.py`` uses to mark a spec as retained history.
_BANNER_RE = re.compile(r"^>\s*\*\*Superseded\s+\d{4}-\d{2}-\d{2}")
_LIVE_MARKER = "(live)"


def _spec_h1(text: str) -> str:
    """The first ``# `` markdown heading in ``text`` (empty if none)."""
    for line in text.splitlines():
        if line.startswith("# "):
            return line
    return ""


def test_hermes_spec_relocated_to_retired() -> None:
    """``hermes-orchestration.md`` is retired: relocated, not ``(live)``, bannered."""
    assert tracked_files_under("specs/hermes-orchestration.md") == set(), (
        "hermes-orchestration.md must move out of specs/ root into specs/retired/."
    )
    moved = tracked_files_under("specs/retired/hermes-orchestration.md")
    assert moved, "hermes-orchestration.md must be relocated under specs/retired/ (AC-2)."

    text = next(iter(moved)).read_text(encoding="utf-8")
    assert _LIVE_MARKER not in _spec_h1(text).lower(), (
        "the relocated hermes-orchestration.md must not still be titled '(live)'."
    )
    head = text.splitlines()[:12]
    assert any(_BANNER_RE.match(line) for line in head), (
        "the relocated hermes-orchestration.md needs a dated supersede banner."
    )


# ---------------------------------------------------------------------------
# AC-3 — the Hermes-only observability synthesis is gone.
# ---------------------------------------------------------------------------


def test_query_status_drops_hermes_only_derivation() -> None:
    """``query_status`` no longer carries the ``failure_retryable`` derivation."""
    from harness.cli import query_status

    for name in ("_derive_failure_retryable", "_NON_RETRYABLE_REASONS"):
        assert not hasattr(query_status, name), (
            f"query_status.{name} drove the Hermes-only failure_retryable field; "
            "it has no live emitter — delete it (CAL-712, AC-3)."
        )


def test_status_json_has_no_hermes_only_fields(tmp_path: Path) -> None:
    """``status --json`` no longer emits ``agent_session_ids`` / ``failure_retryable``."""
    import asyncio
    import json

    from typer.testing import CliRunner

    from harness.cli import app
    from harness.state import store

    db_path = tmp_path / "harness.db"

    async def _seed() -> None:
        await store.init_db(db_path)
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
                "state_json, inputs_json, base_branch, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("R1", "", 0, "open", "{}", "{}", "dev", "2026-06-15T00:00:00Z"),
            )
            await conn.commit()

    asyncio.run(_seed())
    result = CliRunner().invoke(app, ["status", "R1", "--db", str(db_path), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    for key in ("agent_session_ids", "failure_retryable"):
        assert key not in payload, (
            f"status --json still emits the Hermes-only field {key!r} (CAL-712, AC-3)."
        )


def test_runs_command_drops_failed_grouping() -> None:
    """The ``runs`` command no longer exposes the Hermes-only ``--failed`` grouping."""
    from harness.cli import query_runs

    params = inspect.signature(query_runs.runs_command).parameters
    assert "failed" not in params, (
        "runs --failed grouped by workflow_failed reason for Hermes; no live "
        "verb emits those reasons — drop the flag (CAL-712, AC-3)."
    )
    assert not hasattr(query_runs, "_fetch_failed_runs_grouped"), (
        "the --failed grouping helper must be removed with the flag (CAL-712, AC-3)."
    )


# ---------------------------------------------------------------------------
# AC-4 — the workspace allowlist survives the deletion.
# ---------------------------------------------------------------------------


def test_workspace_allowlist_preserved() -> None:
    """``harness.workspace`` and its verb wiring survive — it is load-bearing.

    The ticket keeps the ``--repo`` allowlist: every verb resolves ``--repo``
    through ``cli/_repo.py`` → ``harness.workspace.resolve_repo_root``, failing
    closed when ``HARNESS_WORKSPACE_ROOTS`` is unset. Deleting the launcher must
    not take the allowlist with it.
    """
    from harness import workspace

    for name in ("resolve_repo_root", "WorkspaceNotAllowed"):
        assert hasattr(workspace, name), f"harness.workspace.{name} must survive (AC-4)."

    repo_src = (_REPO_ROOT / "harness" / "cli" / "_repo.py").read_text(encoding="utf-8")
    assert "from harness.workspace import" in repo_src and "resolve_repo_root" in repo_src, (
        "cli/_repo.py must keep wiring the verbs to the workspace allowlist (AC-4)."
    )


# ---------------------------------------------------------------------------
# AC-5 — the scaffolding-labeling convention (INSIGHT-1).
#
# The defect: a spec titled "(live)" describing a subsystem whose only callers
# are tests — inert code that reads as operational. The convention: not-yet-built
# capability lives under a clearly-deferred path (``specs/retired/``) or carries
# a "design, not built" banner, and its code has no live (non-test) caller. The
# guard fails if a "(live)" spec names harness modules but none has a non-test
# caller, and if a retired spec still wears the "(live)" badge.
# ---------------------------------------------------------------------------

_MODULE_TOKEN_RE = re.compile(r"harness\.[A-Za-z_][\w.]*")


def _module_source_exists(module: str) -> bool:
    """True iff ``module`` resolves to a tracked ``harness/`` source file."""
    rel = module.replace(".", "/")
    return bool(
        tracked_files_under(f"{rel}.py") or tracked_files_under(f"{rel}/__init__.py")
    )


def _imports_module(text: str, module: str) -> bool:
    """True iff ``text`` imports or references ``module`` (any dotted use, or a
    ``from <parent> import <leaf>`` of it)."""
    if re.search(rf"\b{re.escape(module)}\b", text):
        return True
    parent, _, leaf = module.rpartition(".")
    return bool(
        parent
        and re.search(rf"from {re.escape(parent)} import [^\n]*\b{re.escape(leaf)}\b", text)
    )


def _has_nontest_caller(module: str) -> bool:
    """True iff some ``harness/`` source other than ``module``'s own file uses it."""
    own = {
        (_REPO_ROOT / f"{module.replace('.', '/')}.py").resolve(),
        (_REPO_ROOT / f"{module.replace('.', '/')}/__init__.py").resolve(),
    }
    for path in tracked_files_under("harness"):
        if path.suffix != ".py" or path in own:
            continue
        if _imports_module(path.read_text(encoding="utf-8"), module):
            return True
    return False


def _live_spec_is_violating(
    title: str, named_modules: set[str], live_modules: set[str]
) -> bool:
    """A spec violates the convention iff it is titled ``(live)``, names at least
    one harness module, and **none** of them is live (exists + non-test caller)."""
    if _LIVE_MARKER not in title.lower():
        return False
    if not named_modules:
        return False
    return named_modules.isdisjoint(live_modules)


# The convention rule, pinned by example: (title, named, live) -> violating?
_RULE_CASES = [
    # not titled (live) — never evaluated
    ("# A subsystem", {"harness.launcher"}, set(), False),
    # (live) + a module with a non-test caller — OK
    ("# Foo (live)", {"harness.workspace"}, {"harness.workspace"}, False),
    # (live) + named module is test-only / nonexistent — violation
    ("# Foo (live)", {"harness.launcher"}, set(), True),
    # (live) but names no harness module — not this defect class
    ("# Foo (live)", set(), set(), False),
    # (live) + at least one named module is live — OK (a genuine live reference)
    ("# Foo (live)", {"harness.launcher", "harness.workspace"}, {"harness.workspace"}, False),
]


@pytest.mark.parametrize("title, named, live, expected", _RULE_CASES)
def test_live_spec_rule(
    title: str, named: set[str], live: set[str], expected: bool
) -> None:
    assert _live_spec_is_violating(title, named, live) is expected


def _live_specs() -> list[Path]:
    """Tracked ``specs/**/*.md`` outside ``specs/retired/`` titled ``(live)``."""
    retired = tracked_files_under("specs/retired")
    out: list[Path] = []
    for path in sorted(tracked_files_under("specs")):
        if path.suffix != ".md" or path in retired:
            continue
        if _LIVE_MARKER in _spec_h1(path.read_text(encoding="utf-8")).lower():
            out.append(path)
    return out


def test_no_live_spec_describes_a_test_only_subsystem() -> None:
    """No ``(live)`` spec names a subsystem whose only callers are tests (INSIGHT-1)."""
    violations: list[str] = []
    for spec in _live_specs():
        text = spec.read_text(encoding="utf-8")
        named = set(_MODULE_TOKEN_RE.findall(text))
        live = {m for m in named if _module_source_exists(m) and _has_nontest_caller(m)}
        if _live_spec_is_violating(_spec_h1(text), named, live):
            violations.append(
                f"{spec.relative_to(_REPO_ROOT)}: titled '(live)' but names only "
                f"test-only/absent modules {sorted(named)}"
            )
    assert not violations, (
        "a spec titled '(live)' describes a subsystem with no live (non-test) "
        "caller — move it under specs/retired/ or banner it 'design, not built', "
        "and delete the inert code (INSIGHT-1):\n  " + "\n  ".join(violations)
    )


def test_retired_specs_are_not_titled_live() -> None:
    """A spec under ``specs/retired/`` may not still be titled ``(live)``."""
    offenders = [
        str(p.relative_to(_REPO_ROOT))
        for p in sorted(tracked_files_under("specs/retired"))
        if p.suffix == ".md"
        and _LIVE_MARKER in _spec_h1(p.read_text(encoding="utf-8")).lower()
    ]
    assert not offenders, (
        f"retired specs still wear the '(live)' badge: {offenders}. A retired "
        "subsystem's spec is design history, not a live reference."
    )
