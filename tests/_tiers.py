"""The test-suite tier boundary: what each test is allowed to depend on (#336).

Three tiers, assigned per module by the dependency boundary its **module-level
imports** cross. The names mean what they say, which is the whole point of
CODE-4 (``assessments/2026-08-04-code.md``): before this, one module carried
``integration`` while ~85 modules under ``tests/unit/`` spawned processes,
opened the SQLite ledger or drove whole verbs through ``CliRunner``.

===============  ==========================================================
Tier             May cross
===============  ==========================================================
``unit``         nothing outside the process — parsers, models, protocol
                 shapes, argv builders against stubs
``guard``        the checked-out tree, read-only: docs, skills, sources, CI
                 YAML, and the ``git ls-files`` tracked set behind
                 :mod:`tests._gitutil`
``integration``  a real repository or worktree, the SQLite ledger, a spawned
                 process, or a whole verb through ``CliRunner``
===============  ==========================================================

Three tiers rather than the two the finding names. A two-way split has to put
the ~140 tree-reading guards somewhere and both homes re-create the dishonesty:
in ``unit`` they make "unit" mean "needs a full checkout with unshallowed
history" (CI already sets ``fetch-depth: 0`` for exactly that), and in
``integration`` they make "integration" mean nothing in particular. Reading the
committed tree is a real, distinct boundary, and this repo already calls those
tests guards.

Selection
---------

=====================================  ===================================
``pytest -m unit``                     in-process package signal
``pytest -m "unit or guard"``          needs no repo, ledger or process
``pytest -m integration``              boundary-crossing tests
``pytest -m "integration and not      the above without a docker daemon
docker"``
=====================================  ===================================

A tier selector is a **feedback affordance, never a gate run**.
``scripts/verify.sh`` passes no ``-m`` and keeps ``--cov-fail-under=90``; the
tiers select, they never deselect, and ``test_tiers.py`` pins that.

Two halves, one guarantee
-------------------------

:func:`classify` is *structural*: it reads the AST and answers before any test
runs, which is what makes ``-m`` selection possible at all. It can be fooled by
a boundary a test reaches through **production** code rather than through its
own imports — ``tests/unit/test_cli_serve.py`` drives a real socket server that
spawns a (stubbed) ``docker``, and imports neither ``subprocess`` nor
``CliRunner`` to do it.

:func:`deny_boundaries` is *runtime*: for a ``unit``-tier test it patches the
process and database chokepoints, so a structural miss fails by name instead of
quietly making the fast tier not fast. It is a lint enforced at runtime, not a
sandbox — a unit test could still open a socket. The claim it supports is
narrower and is the one that matters here: the fast tier cannot silently
acquire a git, ledger or process dependency.

Neither half is asked to do the other's job. That is why module-level imports
are a deliberate contract rather than a limitation: :mod:`tests._cliutil`
already documents an in-function import as the sanctioned way to keep a heavy
import out of collection, so a function-body import must not flip a tier.

No files move
-------------

Deriving the tier is what makes that possible. Relocating ~85 modules into
``tests/integration/`` would break the self-referential path literals in the
retirement and capability guards, and re-point the ``tests/unit/...`` citations
in ``SPEC.md``, ``RUNBOOK.md`` and ``specs/**`` while leaving the historical
ones in ``assessments/`` and ``CHANGELOG-archive/`` stale either way. The cost
is that the ``tests/unit/`` directory name outlives its meaning; the answer is
that the path carries **no** authority — :func:`classify` never consults the
directory — and this docstring is where that is said.
"""

from __future__ import annotations

import ast
import functools
import sqlite3
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

import pytest

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable

Tier = Literal["unit", "guard", "integration"]
BoundaryFlag = Literal["cli", "db", "proc", "tree"]

#: Every tier, in widening order. The single home for the tier vocabulary —
#: ``pyproject.toml``'s ``markers`` list is checked against this, not the
#: reverse, so adding a tier here is what forces its registration.
TIERS: tuple[Tier, ...] = ("unit", "guard", "integration")

#: Which tier a boundary flag forces. ``cli``/``db``/``proc`` are the
#: out-of-process boundaries; ``tree`` is the read-only checkout.
_BOUNDARY_TIER: dict[str, Tier] = {
    "cli": "integration",
    "db": "integration",
    "proc": "integration",
    "tree": "guard",
}

#: Top-level module names whose module-level import *is* the boundary.
_IMPORT_BOUNDARIES: dict[str, frozenset[str]] = {
    "subprocess": frozenset({"proc"}),
    "sqlite3": frozenset({"db"}),
    "aiosqlite": frozenset({"db"}),
    "harness.state": frozenset({"db"}),
    "harness.state.store": frozenset({"db"}),
}

#: ``from typer.testing import CliRunner`` — the whole-verb boundary. Keyed on
#: the symbol, not the module, because ``typer.testing`` also exposes
#: ``Result``, which is a type and crosses nothing.
_CLI_SYMBOL = ("typer.testing", "CliRunner")

#: What importing a shared ``tests/_*.py`` helper costs you, resolved **one hop
#: only**. A helper that itself imports another boundary helper must state the
#: union here; ``test_tiers.py`` fails if any tracked helper is missing, so a
#: second hop cannot appear unnoticed.
#:
#: ``tests._gitutil`` is keyed at *symbol* granularity because it genuinely
#: spans two boundaries: :func:`~tests._gitutil.init_repo` builds a throwaway
#: repository, while the tracked-set readers only read the committed tree. The
#: bare module key is the union, which is the coarser answer a whole-module
#: import (``from tests import _gitutil``) has to settle for.
HELPER_BOUNDARIES: dict[str, frozenset[str]] = {
    # Stdlib-only asyncio plumbing; imports no harness and no tests module.
    "tests._asyncutil": frozenset(),
    # Typer app introspection. Imports ``typer`` only, and its call sites
    # import ``harness.cli`` inside their own function bodies.
    "tests._cliutil": frozenset(),
    "tests._gitutil": frozenset({"proc", "tree"}),
    "tests._gitutil::init_repo": frozenset({"proc"}),
    "tests._gitutil::tracked_files_under": frozenset({"tree"}),
    "tests._gitutil::tracked_py_sources": frozenset({"tree"}),
    "tests._gitutil::last_commit_date": frozenset({"tree"}),
    # Seeds ledger events straight into the SQLite store.
    "tests._ledger": frozenset({"db"}),
    # Reclaim fixtures: a seeded ledger plus real git worktrees.
    "tests._reclaim": frozenset({"db", "proc"}),
    # This module. It *patches* subprocess and sqlite3 rather than using them,
    # so importing the classifier crosses nothing — which is what lets
    # ``test_tiers.py`` stay ``unit`` and prove the denial on itself.
    "tests._tiers": frozenset(),
}

#: The escape hatch, deliberately centralized rather than spread as 250
#: per-module ``pytestmark`` lines that rot the first time one is forgotten.
#:
#: Every entry is a boundary the structural scan cannot see because the test
#: reaches it through *production* code. Each was found by running the suite
#: with :func:`deny_boundaries` active, not by inspection. ``test_tiers.py``
#: fails an entry that names a module the tree no longer tracks, or one whose
#: derived tier already equals the declared one — an exemption must name live
#: code and must actually exempt something.
OVERRIDES: dict[str, Tier] = {
    # Runs a real ``harness serve`` socket server in a thread; every verb it
    # answers spawns the stub ``docker`` binary the fixture puts on PATH.
    "tests/unit/test_cli_serve.py": "integration",
    # Drive the host-environment client, which spawns ``docker`` (stubbed) to
    # reach the verb container.
    "tests/unit/test_hostenv_client.py": "integration",
    "tests/unit/test_hostenv_credentials.py": "integration",
    "tests/unit/test_hostenv_per_request_credentials.py": "integration",
}

_REPO_ROOT = Path(__file__).resolve().parents[1]


class TierViolation(RuntimeError):
    """A ``unit``-tier test crossed a boundary its tier forbids."""


class _Markable(Protocol):
    """The slice of ``pytest.Item`` :func:`apply_tier_markers` needs.

    Narrowed to a protocol so the hook can be tested against recording stubs
    rather than a nested pytest run.
    """

    @property
    def path(self) -> Path: ...

    def add_marker(self, marker: object) -> None: ...


def _module_imports(tree: ast.Module) -> list[tuple[str, str | None]]:
    """Every module-level import as ``(module, imported name or None)`` pairs.

    Module level only, and by walking ``tree.body`` rather than ``ast.walk``,
    so a function-body import cannot reach this list. That is the contract
    :func:`deny_boundaries` exists to backstop.
    """
    pairs: list[tuple[str, str | None]] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            pairs.extend((alias.name, None) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            pairs.extend((module, alias.name) for alias in node.names)
    return pairs


def _reads_the_tree(tree: ast.Module) -> bool:
    """Whether the module locates itself inside the checkout.

    ``__file__`` is the tell, and it is read **anywhere** in the module rather
    than only at module level: the repo-root anchor is spelled
    ``Path(__file__).parent.parent.parent`` in most guards and
    ``Path(__file__).resolve().parents[2]`` in others, and a handful compute it
    inside the function that needs it. Restricting this to module level put 32
    tree-reading guards in ``unit`` when it was measured (56 unit modules
    against 24), which is the mislabelling this ticket exists to end. There is
    no hermetic use of ``__file__`` in a test module, so widening the scan
    costs nothing.
    """
    return any(
        isinstance(node, ast.Name) and node.id == "__file__" for node in ast.walk(tree)
    )


@functools.lru_cache(maxsize=None)
def _boundaries_of_source(source: str) -> frozenset[str]:
    tree = ast.parse(source)
    flags: set[str] = set()
    for module, name in _module_imports(tree):
        if name is not None:
            symbol = HELPER_BOUNDARIES.get(f"{module}::{name}")
            if symbol is not None:
                flags |= symbol
                continue
            if (module, name) == _CLI_SYMBOL:
                flags.add("cli")
            # ``from tests import _gitutil`` — the imported *name* is the helper.
            helper = HELPER_BOUNDARIES.get(f"{module}.{name}")
            if helper is not None:
                flags |= helper
        helper = HELPER_BOUNDARIES.get(module)
        if helper is not None:
            flags |= helper
            continue
        for prefix, boundary in _IMPORT_BOUNDARIES.items():
            if module == prefix or module.startswith(f"{prefix}."):
                flags |= boundary
    if _reads_the_tree(tree):
        flags.add("tree")
    return frozenset(flags)


def boundaries(path: Path) -> frozenset[str]:
    """The boundary flags *path*'s module-level imports and body declare.

    Memoized on the source text rather than the path, so the same synthetic
    body classifies identically wherever a test writes it, and a file edited
    in place is re-read rather than served stale.
    """
    return _boundaries_of_source(Path(path).read_text(encoding="utf-8"))


def _override_key(path: Path) -> str | None:
    """*path* as a repo-relative POSIX string, or None if it is outside the repo.

    Returning None rather than raising is what lets :func:`classify` run over
    synthetic modules under ``tmp_path``: the classifier's oracle is proven on
    sources written by the test, and a temp file can never collide with an
    override entry.
    """
    try:
        return Path(path).resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return None


def classify(path: Path) -> Tier:
    """*path*'s tier — an :data:`OVERRIDES` entry if it has one, else derived.

    The directory is never consulted. ``tests/unit/`` is a historical location,
    not a claim.
    """
    key = _override_key(path)
    if key is not None and key in OVERRIDES:
        return OVERRIDES[key]
    return tier_for(boundaries(path))


def tier_for(flags: Iterable[str]) -> Tier:
    """The widest tier a set of boundary flags forces."""
    tiers = {_BOUNDARY_TIER[flag] for flag in flags if flag in _BOUNDARY_TIER}
    for tier in reversed(TIERS):
        if tier in tiers:
            return tier
    return "unit"


def apply_tier_markers(items: Iterable[_Markable]) -> None:
    """Mark every collected item with its module's tier.

    Applied from ``tests/conftest.py``'s ``pytest_collection_modifyitems``,
    which runs before ``-m`` deselection — so the derived tier is selectable
    without a single marker line in a test module.
    """
    for item in items:
        item.add_marker(getattr(pytest.mark, classify(item.path)))


def deny_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make a process spawn or a database connection raise :class:`TierViolation`.

    Patched at the chokepoints rather than at each caller's alias:
    ``subprocess.Popen`` is what every ``run``/``check_output``/``call`` funnels
    through, and ``aiosqlite`` reaches ``sqlite3.connect`` on its worker thread.
    A test that has *already* replaced these with its own fakes is unaffected —
    it is not crossing the boundary either.
    """

    def _refuse(kind: str) -> Callable[..., object]:
        def deny(*args: object, **kwargs: object) -> object:
            raise TierViolation(
                f"a unit-tier test {kind}. Either keep it in-process, or record "
                f"its tier in tests/_tiers.py OVERRIDES with the reason. "
                f"(called with {args!r})"
            )

        return deny

    monkeypatch.setattr(subprocess, "Popen", _refuse("spawned a process"))
    monkeypatch.setattr(sqlite3, "connect", _refuse("opened a database"))
