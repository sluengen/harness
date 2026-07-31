"""Import-layering guards for the ``harness`` package (#269).

Two modules could not be imported first in a fresh interpreter. ``harness/cli/_git.py``
was a pure leaf — it imports only ``harness.branch_config`` and ``harness.identity``
— but it *lived inside* the ``harness.cli`` package, whose ``__init__.py`` eagerly
imports every verb module. Three modules **below** the CLI layer imported it
(``close_merge``, ``promotion``, ``promotion_pr``), so entering the graph through
any of them ran the whole CLI, and the CLI imported them straight back::

    harness.close_merge
      -> harness.cli._git            (forces the harness.cli package __init__)
        -> harness.cli.review
          -> harness.cli.review_inherit
            -> from harness.close_merge import worktree_porcelain   # still partial

``harness.promotion`` survived on ordering luck alone. Both live failures were
**latent**: in a full-suite run something else imports ``harness.cli`` first, so
the package is already initialized by the time these modules are reached and
``scripts/verify.sh`` stayed green. The bug only fired when one of them was the
*first* harness import in the process — which is exactly what running a single
test file does (``pytest tests/unit/test_close_merge.py`` died at collection).

The fix re-homed the helpers to :mod:`harness._git`, a top-level leaf beside
:mod:`harness._time`. These guards keep the class from coming back.

Two guards, deliberately not one, because neither subsumes the other:

* :func:`test_no_module_below_the_cli_imports_into_it` — the **cause**. No module
  under ``harness/`` outside ``harness/cli/`` may import from ``harness.cli``.
  It fires on the layering violation even when no runtime cycle results, and it
  names the offending file and import.
* :func:`test_every_harness_module_imports_first` — the **symptom**. Every module
  in the package imports cleanly when it is the first harness module imported. It
  catches a cycle formed entirely *inside* the CLI package, which the layering
  rule permits and cannot see.

Both **derive** their subject rather than enumerating it (the #219 lesson — a
hand-written list of guarded modules silently fell four command surfaces behind
the package, and the guard was green because it had not checked, not because
nothing violated it). The layering scan reads the *tracked* source set via
``tests._gitutil.tracked_py_sources`` rather than an ``rglob``, so an abandoned
worktree left under ``harness/`` cannot read as living source (#215).

The layering scan reads **AST imports only**, never text. A grep would fire on
the dozen-plus legitimate docstring cross-references to CLI internals across
``harness/events/``, ``harness/state/`` and ``harness/close_merge.py`` — a
``:mod:`harness.cli.close``` cite is documentation, not an edge in the import
graph.

Acceptance criteria (#269):

* **AC-1** — ``harness.close_merge`` and ``harness.promotion_pr`` import in a
  fresh interpreter. :func:`test_close_merge_imports_first`,
  :func:`test_promotion_pr_imports_first`.
* **AC-3** — every module in the package imports first-cleanly.
  :func:`test_every_harness_module_imports_first`.
* **AC-4** — the layering rule itself.
  :func:`test_no_module_below_the_cli_imports_into_it`.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest

from tests._gitutil import tracked_py_sources

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The package whose internals are off-limits to everything beneath it, and the
#: directory that holds it. A module is "below the CLI" iff it is tracked source
#: under ``harness/`` that does not live in this directory.
_CLI_PACKAGE = "harness.cli"
_CLI_DIR_PART = "harness/cli/"


# ---------------------------------------------------------------------------
# AC-4 — the layering rule: nothing below the CLI imports into it
# ---------------------------------------------------------------------------


def _module_package(path: Path, *, repo_root: Path) -> str:
    """The dotted package a source file's relative imports resolve against.

    ``harness/events/payloads.py`` → ``harness.events``. A relative import's
    ``level`` counts *up* from here, which is why the package — not the module —
    is the anchor.
    """
    parts = path.resolve().relative_to(repo_root.resolve()).parts
    return ".".join(parts[:-1])


def _absolute_target(node: ast.ImportFrom, *, package: str) -> str | None:
    """The absolute module an ``ImportFrom`` names, resolving the relative forms.

    ``level=0`` is already absolute. Otherwise ``level`` strips that many
    trailing components off ``package`` (``level=1`` → the package itself), and
    ``node.module`` — absent in ``from . import x`` — is appended. Returns
    ``None`` when the climb walks off the top, which is a syntax error Python
    would have rejected long before this scan.
    """
    if node.level == 0:
        return node.module
    base_parts = package.split(".")
    if node.level > len(base_parts):
        return None
    base = ".".join(base_parts[: len(base_parts) - node.level + 1])
    return f"{base}.{node.module}" if node.module else base


def _targets_the_cli(dotted: str | None) -> bool:
    """True iff ``dotted`` is the CLI package or something inside it.

    The prefix test is on ``harness.cli.`` with the trailing dot, so a
    hypothetical sibling named ``harness.client`` is not swept up.
    """
    return dotted is not None and (
        dotted == _CLI_PACKAGE or dotted.startswith(f"{_CLI_PACKAGE}.")
    )


def _up_imports(paths: Iterable[Path], *, repo_root: Path = REPO_ROOT) -> list[str]:
    """One message per import that reaches from below the CLI up into it.

    Covers every form that creates the edge: ``import harness.cli.x``,
    ``from harness.cli.x import y``, ``from harness import cli`` (the package
    bound by name), and the relative equivalents.

    There is deliberately no ``TYPE_CHECKING`` exemption. No module needs one
    today, and adding one now would be designing for a case that does not exist
    — and a type-only up-import is still an edge the next reader has to reason
    about.
    """
    offenders: list[str] = []
    for path in sorted(paths):
        package = _module_package(path, repo_root=repo_root)
        tree = ast.parse(path.read_text())
        rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _targets_the_cli(alias.name):
                        offenders.append(f"{rel}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                target = _absolute_target(node, package=package)
                if _targets_the_cli(target):
                    names = ", ".join(alias.name for alias in node.names)
                    offenders.append(f"{rel}: from {target} import {names}")
                elif target == "harness":
                    # ``from harness import cli`` binds the package itself.
                    for alias in node.names:
                        if alias.name == "cli":
                            offenders.append(f"{rel}: from harness import cli")
    return sorted(offenders)


def _modules_below_the_cli(*, repo_root: Path = REPO_ROOT) -> list[Path]:
    """Tracked ``harness/`` sources that are not part of the CLI package."""
    return [
        path
        for path in tracked_py_sources("harness", repo_root=repo_root)
        if _CLI_DIR_PART not in path.as_posix()
    ]


def test_no_module_below_the_cli_imports_into_it() -> None:
    """No module under ``harness/`` outside ``harness/cli/`` imports from ``harness.cli``.

    The rule whose violation produced both cycles. It fires on the *edge*, not on
    the crash, so a future up-import that happens not to close a loop is still
    caught — with the file and the import named.
    """
    offenders = _up_imports(_modules_below_the_cli())

    assert not offenders, (
        "modules below the CLI layer must not import from harness.cli "
        "(move the shared helper down to a leaf instead):\n  "
        + "\n  ".join(offenders)
    )


def test_the_layering_scan_covers_the_modules_that_broke() -> None:
    """Anti-vacuity: the scanned set is real and contains the three offenders.

    The offender scan passes trivially on an empty set, so a mis-built exclusion
    filter would turn the guard above into a no-op that reports success. These
    three modules are the ones that carried the up-import, so their presence is
    the proof the filter keeps what it must.
    """
    scanned = {
        path.resolve().relative_to(REPO_ROOT).as_posix()
        for path in _modules_below_the_cli()
    }

    assert len(scanned) > 10, f"suspiciously small scanned set: {sorted(scanned)}"
    assert {
        "harness/close_merge.py",
        "harness/promotion.py",
        "harness/promotion_pr.py",
    } <= scanned


def test_the_layering_scan_excludes_the_cli_package_itself() -> None:
    """The CLI's own modules are outside the scan — the rule is about the boundary.

    Intra-CLI imports are not merely tolerated, they are the package's normal
    structure (``review.py`` imports ``review_protocol``). Guarding them here
    would flag the whole package; the intra-CLI rule lives in
    ``test_cli_module_boundaries.py`` and is a different contract.
    """
    scanned = {path.as_posix() for path in _modules_below_the_cli()}

    assert not any(_CLI_DIR_PART in name for name in scanned)


@pytest.mark.parametrize(
    "source, expected",
    [
        ("from harness.cli._repo import resolve_repo_root_or_exit\n", True),
        ("import harness.cli.close\n", True),
        ("from harness import cli\n", True),
        ("from harness._git import run_git\n", False),
        ("from harness import close_merge\n", False),
        # A sibling whose name merely starts with the same letters.
        ("from harness.client import thing\n", False),
    ],
)
def test_the_layering_guard_classifies_each_import_form(
    tmp_path: Path, source: str, expected: bool
) -> None:
    """The positive controls: the scan actually fires, on every up-import form.

    The live tree is clean once #269 lands, so every assertion against it proves
    only that nothing currently violates the rule — never that the check works.
    """
    module = tmp_path / "harness" / "sample.py"
    module.parent.mkdir(parents=True)
    module.write_text(source)

    assert bool(_up_imports([module], repo_root=tmp_path)) is expected


def test_the_layering_guard_ignores_a_docstring_cite(tmp_path: Path) -> None:
    """A docstring cross-reference to CLI internals is documentation, not an edge.

    The negative control that rules out a text/grep implementation:
    ``harness/events/payloads.py`` alone carries six such cites, and
    ``harness/state/`` and ``harness/close_merge.py`` carry more.
    """
    module = tmp_path / "harness" / "sample.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        '"""Read by :func:`harness.cli.close._evaluate_gate`.\n\n'
        'See :mod:`harness.cli.review` for the caller.\n"""\n'
        "from harness._git import run_git\n"
    )

    assert _up_imports([module], repo_root=tmp_path) == []


def test_the_layering_guard_resolves_a_relative_up_import(tmp_path: Path) -> None:
    """``from ..cli import x`` in ``harness/events/`` is the same offence.

    Relative imports resolve against the file's package, so the scan must climb
    rather than pattern-match the written text.
    """
    module = tmp_path / "harness" / "events" / "sample.py"
    module.parent.mkdir(parents=True)
    module.write_text("from ..cli import _git\n")

    assert _up_imports([module], repo_root=tmp_path) == [
        "harness/events/sample.py: from harness.cli import _git"
    ]


# ---------------------------------------------------------------------------
# AC-1 / AC-3 — every module imports cleanly as the first harness import
# ---------------------------------------------------------------------------

#: Run in a child interpreter: walk ``package``, and import each module with the
#: package's own entries purged from ``sys.modules`` first, so every import is
#: the *first* one in a graph that starts empty. Emits ``{module: last traceback
#: line}`` for the failures as JSON on stdout.
#:
#: One child for the whole sweep, not one per module: the isolation that matters
#: is a clean ``harness`` graph, and the purge gives that at ~70 imports in well
#: under a second, where a subprocess each would add ~18s to every gate run.
#: Purging inside the *pytest* process is not an option — later tests hold
#: references to the old module objects while ``sys.modules`` hands out new ones,
#: so a monkeypatch would land on an object the live Typer app no longer uses.
_SWEEP_SCRIPT = """
import importlib, json, pkgutil, sys, traceback

package = sys.argv[1]
root = importlib.import_module(package)
names = [package] + [m.name for m in pkgutil.walk_packages(root.__path__, package + ".")]

failures = {}
for name in sorted(names):
    prefix = package + "."
    for key in [k for k in sys.modules if k == package or k.startswith(prefix)]:
        del sys.modules[key]
    try:
        importlib.import_module(name)
    except BaseException:
        failures[name] = traceback.format_exc().strip().splitlines()[-1]

json.dump({"checked": len(names), "failures": failures}, sys.stdout)
"""


def _import_each_first(package: str, *, cwd: Path) -> dict[str, object]:
    """Import every module of ``package`` as the first import of a clean graph.

    Returns ``{"checked": int, "failures": {module: last traceback line}}``. A
    child that dies or prints unparseable stdout raises through
    :func:`pytest.fail` with its stderr attached, so a broken sweep is never a
    vacuous pass.
    """
    proc = subprocess.run(
        [sys.executable, "-c", _SWEEP_SCRIPT, package],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.fail(f"import sweep child failed ({proc.returncode}):\n{proc.stderr}")
    try:
        result: dict[str, object] = json.loads(proc.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"import sweep produced no result:\n{proc.stdout!r}\n{proc.stderr}")
    return result


@pytest.mark.parametrize("module", ["harness.close_merge", "harness.promotion_pr"])
def test_the_reported_modules_import_first(module: str) -> None:
    """AC-1, literally as reported: each module imports in a fresh interpreter.

    Kept as its own spawn per module, separate from the sweep, because this is
    the reproduction from the bug report — it must be readable as such and must
    fail with the reported ``ImportError`` on the unfixed tree.
    """
    proc = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, f"import {module} failed:\n{proc.stderr}"


def test_every_harness_module_imports_first() -> None:
    """AC-3: no module in the package fails when imported into a clean graph.

    Broader than a cycle check by design: a module that fails to import for any
    reason — a syntax error, a missing dependency, import-time I/O that raises —
    is reported the same way, because the contract is "imports cleanly first".
    """
    result = _import_each_first("harness", cwd=REPO_ROOT)

    assert result["failures"] == {}, f"modules that fail as a first import: {result}"


def test_the_sweep_checks_the_whole_package() -> None:
    """Anti-vacuity: the sweep really walked the package, not a handful of modules."""
    result = _import_each_first("harness", cwd=REPO_ROOT)

    assert isinstance(result["checked"], int)
    assert result["checked"] > 50, f"sweep walked too few modules: {result['checked']}"


def test_the_sweep_detects_a_latent_cycle(tmp_path: Path) -> None:
    """The positive control: a synthetic cycle is reported, naming the module.

    The package is a miniature of #269, *including its latency*, which is what
    makes it worth building rather than asserting on a trivial two-module loop:

    * ``zvictim`` is a leaf-ish module that reaches into the ``sub`` package;
    * ``sub``'s ``__init__`` eagerly imports ``sub.v``, which name-imports back
      from ``zvictim``;
    * ``awarmer`` imports ``sub`` and sorts *first*, so in a shared interpreter
      the package is already initialized by the time ``zvictim`` is reached and
      the cycle never fires — exactly why ``verify.sh`` stayed green while
      ``pytest tests/unit/test_close_merge.py`` died at collection.

    That last property is what pins the ``sys.modules`` purge: drop it and
    ``zvictim`` hits the import cache warmed by ``awarmer``, the sweep reports
    nothing, and this test fails. The purge is load-bearing, not tidy.
    """
    package = tmp_path / "cyc"
    (package / "sub").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "awarmer.py").write_text("import cyc.sub\n")
    (package / "zvictim.py").write_text("from cyc.sub.leaf import H\n\nNAME = 'z'\n")
    (package / "sub" / "__init__.py").write_text("from cyc.sub.v import V\n")
    (package / "sub" / "leaf.py").write_text("H = 1\n")
    (package / "sub" / "v.py").write_text("from cyc.zvictim import NAME\n\nV = NAME\n")

    result = _import_each_first("cyc", cwd=tmp_path)

    failures = result["failures"]
    assert isinstance(failures, dict)
    assert set(failures) == {"cyc.zvictim"}, f"cycle not detected as expected: {result}"
    assert "partially initialized" in failures["cyc.zvictim"]


def test_the_sweep_reports_a_clean_package(tmp_path: Path) -> None:
    """The negative control: an acyclic package sweeps clean.

    Without it, :func:`test_the_sweep_detects_a_cycle` could pass because the
    sweep reports *everything* as broken.
    """
    package = tmp_path / "fine"
    package.mkdir()
    (package / "__init__.py").write_text("from fine.a import NAME\n")
    (package / "a.py").write_text("NAME = 'a'\n")
    (package / "b.py").write_text("from fine.a import NAME\n")

    result = _import_each_first("fine", cwd=tmp_path)

    assert result["failures"] == {}
    assert result["checked"] == 3
