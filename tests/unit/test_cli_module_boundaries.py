"""Module-boundary guards for the CLI package (CAL-1013).

Two structural invariants the consolidation establishes:

1. The short-duration parser lives in a shared home (:mod:`harness.cli._duration`),
   not inside a sibling *command* module — so importing it is not a
   cross-command private import.
2. No verb command imports another command module's private helper. ``reclaim``
   used to reach into ``worktrees`` for ``_parse_duration``; that coupling is
   gone. These are text-parse guards in the style of the repo's other
   source-scan tests.

The guarded set is **derived** from the CLI's own registrations rather than
listed (#219). A hand-written enumeration of eight stems had fallen four command
surfaces behind the package — ``defer`` / ``release`` (tracker-protocol work),
``promote`` (ADR 0003) and ``design`` (#211) — and because the offender scan
iterates the set for both the importing module *and* the import target, every
omission was a blind spot in both directions. The guard was green because
nothing violated it, not because it had checked.

Derivation parses ``harness/cli/__init__.py`` with :mod:`ast`, resolving each
registered command name to the module its callable is imported from. Two
addressed source files are read, never a tree walk, which is why this guard has
no business with ``tests._gitutil.tracked_py_sources``: the #215 hazard is a
*walk* picking up an untracked stray worktree as living source, and a
path-addressed read of one known file cannot pick one up.

A filesystem heuristic ("every non-underscore module") would be wrong, not
merely coarse: ``review.py`` imports ``_build_cmd`` from ``review_protocol``,
which registers no command, and the heuristic would call that a violation.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from datetime import timedelta
from pathlib import Path

import pytest

from tests._cliutil import registered_command_surface
from tests._gitutil import tracked_py_sources

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_DIR = REPO_ROOT / "harness" / "cli"
CLI_INIT = CLI_DIR / "__init__.py"


def _cli_import_map(tree: ast.Module) -> dict[str, str]:
    """Map each name imported from a CLI module to that module's stem.

    Keyed by the bound name (``asname`` when aliased), so an aliased import
    still resolves to its defining module. Both the absolute
    (``from harness.cli.start import ...``) and the level-1 relative
    (``from .start import ...``) forms are recognised.
    """
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if node.level == 1:
            stem = node.module.split(".", 1)[0]
        elif node.module.startswith("harness.cli."):
            stem = node.module.rsplit(".", 1)[-1]
        else:
            continue
        for alias in node.names:
            bound[alias.asname or alias.name] = stem
    return bound


def _string_keyword(call: ast.Call, keyword: str) -> str | None:
    """Return ``call``'s ``keyword=`` argument when it is a string literal."""
    for kw in call.keywords:
        if (
            kw.arg == keyword
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        ):
            return kw.value.value
    return None


def _attribute_call(node: ast.AST, attr: str) -> ast.Call | None:
    """Return ``node`` when it is a call of the attribute ``attr`` (``x.attr(...)``)."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attr
    ):
        return node
    return None


def _first_positional_name(call: ast.Call) -> str | None:
    """Return the identifier of ``call``'s first positional argument, if it is a name."""
    if call.args and isinstance(call.args[0], ast.Name):
        return call.args[0].id
    return None


def _registered_command_modules(source_path: Path = CLI_INIT) -> dict[str, str]:
    """Map every registered CLI command name to the module stem defining it.

    Reads the two registration forms the CLI actually uses:

    * ``app.command(name="start", ...)(start_command)`` — a call *of a call*;
      the name comes from the inner call's ``name=`` literal, the module from
      the outer call's positional callable.
    * ``app.add_typer(worktrees_app, name="worktrees", ...)`` — the name from
      ``name=``, the module from the first positional argument.

    The relation is many-to-one: ``status`` / ``logs`` / ``events`` / ``runs``
    all resolve to ``query``. A registration this cannot resolve yields no entry
    and is caught by ``test_derivation_covers_every_registered_command``, so the
    guarded set can never shrink silently.

    ``source_path`` is injectable so the parser can be exercised against
    synthetic sources, following ``tracked_py_sources(repo_root=...)``.
    """
    tree = ast.parse(source_path.read_text())
    bound = _cli_import_map(tree)
    registered: dict[str, str] = {}

    for node in ast.walk(tree):
        if (add_typer := _attribute_call(node, "add_typer")) is not None:
            name = _string_keyword(add_typer, "name")
            symbol = _first_positional_name(add_typer)
        elif isinstance(node, ast.Call) and (
            (command := _attribute_call(node.func, "command")) is not None
        ):
            name = _string_keyword(command, "name")
            symbol = _first_positional_name(node)
        else:
            continue

        if name is not None and symbol is not None and symbol in bound:
            registered[name] = bound[symbol]

    return registered


#: Registered CLI command name -> the module stem that defines it, derived from
#: the CLI's own registrations (#219).
_COMMAND_MODULES_BY_NAME = _registered_command_modules()

#: Command modules (a verb / subcommand surface), as opposed to the shared
#: ``_``-prefixed helper modules and the protocol/query modules that register
#: nothing. A command must not import another command's private (``_``-prefixed)
#: name.
_COMMAND_MODULES = frozenset(_COMMAND_MODULES_BY_NAME.values())


def test_parse_duration_has_a_shared_home() -> None:
    """``_parse_duration`` is importable from the shared duration module and
    behaves (``30m`` / ``12h`` / ``7d``)."""
    from harness.cli._duration import _parse_duration

    assert _parse_duration("30m") == timedelta(minutes=30)
    assert _parse_duration("12h") == timedelta(hours=12)
    assert _parse_duration("7d") == timedelta(days=7)


def test_parse_duration_rejects_bad_input() -> None:
    """A bad duration raises ``typer.BadParameter`` (CLI exits 2)."""
    import typer

    from harness.cli._duration import _parse_duration

    with pytest.raises(typer.BadParameter):
        _parse_duration("nope")


def _imports_of(module_stem: str, *, cli_dir: Path = CLI_DIR) -> list[tuple[str, str]]:
    """Return ``(module, name)`` pairs for every ``from X import Y`` in a CLI
    module — resolving the imported *name* so a private helper is visible."""
    source = (cli_dir / f"{module_stem}.py").read_text()
    tree = ast.parse(source)
    pairs: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                pairs.append((node.module, alias.name))
    return pairs


def _cross_command_private_imports(
    stems: Iterable[str], *, cli_dir: Path = CLI_DIR
) -> list[str]:
    """Return one message per command module importing a sibling command's private name."""
    guarded = set(stems)
    offenders: list[str] = []
    for stem in guarded:
        for module, name in _imports_of(stem, cli_dir=cli_dir):
            if not module.startswith("harness.cli."):
                continue
            target = module.rsplit(".", 1)[-1]
            if target in guarded and name.startswith("_"):
                offenders.append(f"{stem}.py imports private {name!r} from {target}.py")
    return sorted(offenders)


def test_no_command_imports_a_sibling_commands_private_helper() -> None:
    """No command module imports a private name from another *command* module.

    (Importing a public name, or anything from a shared ``_``-helper module such
    as ``_verb`` / ``_duration`` / ``_git``, is fine.)
    """
    offenders = _cross_command_private_imports(_COMMAND_MODULES)
    assert not offenders, "cross-command private imports found: " + "; ".join(offenders)


def test_derived_command_modules_include_the_late_arrivals() -> None:
    """The guarded set covers every command surface, including the late arrivals.

    ``defer`` / ``release`` (tracker-protocol work), ``promote`` (ADR 0003) and
    ``design`` (#211) each registered a command without the hand-written set
    being extended, so each was invisible to the boundary guard in *both*
    directions — as an importer and as an import target.
    """
    assert {"design", "defer", "release", "promote"} <= _COMMAND_MODULES


def test_derivation_covers_every_registered_command() -> None:
    """The derivation resolves *every* name the live Typer app registers.

    The anti-vacuity check, and the reason the derivation can be trusted: the
    offender scan passes trivially when the guarded set is empty or short, which
    is precisely the failure #219 was filed for. Runtime introspection is the
    independent oracle — two derivations of the same surface that must agree, so
    a registration style the parser does not understand fails *here*, naming the
    command, rather than quietly shrinking what gets guarded.
    """
    from harness.cli import app

    registered = registered_command_surface(app)

    assert set(_COMMAND_MODULES_BY_NAME) == registered


def test_every_derived_module_has_a_source_file() -> None:
    """Every derived stem addresses a real module file.

    A command surface that becomes a package (``promote/``) fails here with an
    actionable message, rather than as a ``FileNotFoundError`` surfacing inside
    the offender scan.
    """
    missing = sorted(
        stem for stem in _COMMAND_MODULES if not (CLI_DIR / f"{stem}.py").is_file()
    )
    assert not missing, (
        "derived command modules with no source file (the derivation in "
        f"_registered_command_modules needs updating): {missing}"
    )


def test_many_names_from_one_module_collapse_to_one_stem() -> None:
    """The read commands are many names behind one import surface.

    ``harness.cli.query`` re-exports from focused ``query_*`` siblings, so the
    derivation must collapse them to the one stem rather than reporting five
    modules that could then import each other's privates unnoticed.
    """
    query_names = {
        name for name, stem in _COMMAND_MODULES_BY_NAME.items() if stem == "query"
    }
    assert query_names == {"status", "logs", "events", "runs", "stats"}


def test_parser_reads_both_registration_forms(tmp_path: Path) -> None:
    """``app.command(name=...)(callable)`` and ``app.add_typer(app_obj, name=...)``."""
    source = tmp_path / "__init__.py"
    source.write_text(
        "from harness.cli.alpha import alpha_command\n"
        "from harness.cli.bravo import bravo_app\n"
        "app.command(name='alpha', help='x')(alpha_command)\n"
        "app.add_typer(bravo_app, name='bravo', help='y')\n"
    )

    assert _registered_command_modules(source) == {"alpha": "alpha", "bravo": "bravo"}


def test_parser_resolves_an_aliased_import(tmp_path: Path) -> None:
    """A registration whose callable was imported under an alias still resolves."""
    source = tmp_path / "__init__.py"
    source.write_text(
        "from harness.cli.charlie import charlie_command as run_charlie\n"
        "app.command(name='charlie')(run_charlie)\n"
    )

    assert _registered_command_modules(source) == {"charlie": "charlie"}


def test_parser_excludes_a_registration_from_outside_the_cli_package(
    tmp_path: Path,
) -> None:
    """A callable that is not a CLI import yields no entry — excluded by rule.

    Without this the exclusion of ``query_status`` / ``review_protocol`` and
    friends could be an accident of the current tree rather than the contract.
    """
    source = tmp_path / "__init__.py"
    source.write_text(
        "from harness.cli.delta import delta_command\n"
        "from somewhere.other import stray_command\n"
        "app.command(name='delta')(delta_command)\n"
        "app.command(name='stray')(stray_command)\n"
    )

    assert _registered_command_modules(source) == {"delta": "delta"}


def test_the_guard_detects_a_cross_command_private_import(tmp_path: Path) -> None:
    """The positive control: the offender scan actually fires.

    The live tree is clean, so every other assertion here proves only that
    nothing currently violates the rule — never that the check works.
    """
    (tmp_path / "a.py").write_text("from harness.cli.b import _helper\n")
    (tmp_path / "b.py").write_text("")

    offenders = _cross_command_private_imports({"a", "b"}, cli_dir=tmp_path)

    assert offenders == ["a.py imports private '_helper' from b.py"]


def test_the_guard_ignores_a_public_cross_command_import(tmp_path: Path) -> None:
    """The negative control: a *public* sibling import is not an offence."""
    (tmp_path / "a.py").write_text("from harness.cli.b import helper\n")
    (tmp_path / "b.py").write_text("")

    assert _cross_command_private_imports({"a", "b"}, cli_dir=tmp_path) == []


def test_reclaim_does_not_import_from_worktrees() -> None:
    """Explicit regression: the specific coupling CAL-1013 removed stays gone."""
    imports = _imports_of("reclaim")
    assert not any(
        module == "harness.cli.worktrees" for module, _ in imports
    ), "reclaim.py must not import from the worktrees command module"


#: The backend client modules a tracker-neutral CLI module may not reach into.
#: A **denylist of backends**, deliberately not an allowlist of seam modules:
#: ``harness.tracker``, ``harness.tracker_errors`` and ``harness.tracker_queue``
#: are unmentioned and therefore always allowed, so a future seam-side module
#: cannot be forbidden by omission. Pinned against the factory by
#: :func:`test_backend_modules_match_the_seam_factory`.
_BACKEND_MODULES = frozenset({"harness.linear", "harness.github"})

#: Repo-relative POSIX path -> the documented reason that module may name a
#: backend. **Empty today**, and the entry bar is narrow: a module whose
#: *purpose* is one backend (a hypothetical ``harness linear migrate``), never a
#: verb that finds the seam inconvenient. It exists so the escape from the rule
#: is a reviewed four-line edit that leaves a record, rather than deleting the
#: guard, which leaves none. Entries are checked by
#: :func:`test_every_exemption_is_documented_and_resolves`; the path the
#: exemption actually takes is proven by :func:`test_an_exempt_module_is_skipped`,
#: since an empty mapping exercises nothing.
_BACKEND_EXEMPT: dict[str, str] = {}

#: The factory that wires every backend — the oracle for ``_BACKEND_MODULES``.
SEAM_SOURCE = REPO_ROOT / "harness" / "tracker.py"


def _absolute_target(node: ast.ImportFrom, *, package: str) -> str | None:
    """The absolute module an ``ImportFrom`` names, resolving the relative forms.

    Same rule as ``test_import_layering._absolute_target``: ``level`` strips that
    many trailing components off ``package`` (``level=1`` → the package itself),
    and ``node.module`` — absent in ``from . import x`` — is appended.
    """
    if node.level == 0:
        return node.module
    base_parts = package.split(".")
    if node.level > len(base_parts):
        return None
    base = ".".join(base_parts[: len(base_parts) - node.level + 1])
    return f"{base}.{node.module}" if node.module else base


def _dotted_attribute_chain(node: ast.Attribute) -> str | None:
    """``harness.github.GitHubClient`` for that attribute chain, else ``None``.

    Only a chain rooted at a plain ``ast.Name`` resolves; anything rooted at a
    call or subscript is not a module path.
    """
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _backend_references(source: str, *, package: str = "harness.cli") -> list[str]:
    """Sorted dotted backend references in ``source``, read from the AST.

    AST rather than text, for the reason ``test_import_layering.py`` gives and
    this tree demonstrates: ``promote.py``, ``close.py``, ``reclaim.py`` and
    ``start.py`` all name ``LinearClient`` / ``GitHubClient`` in docstrings and
    comments legitimately, so a grep-shaped guard is red on a clean tree.

    Matching is on **exact dotted segments**, never ``str.startswith``, so a
    hypothetical ``harness.linear_notes`` is not a backend. A
    ``TYPE_CHECKING``-guarded import counts: ``ast.walk`` sees it, and backend
    vocabulary in a neutral verb's type signatures is the same coupling the rule
    exists to prevent.

    Non-goals, stated so nobody reads more assurance into a green run than is
    there: ``importlib.import_module("harness.linear")``, ``getattr``, and
    string-built dynamic access are not detected. This converts prose and review
    memory into a structural invariant against drift and accident; it is not an
    adversarial sandbox.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(
                alias.name for alias in node.names if alias.name in _BACKEND_MODULES
            )
        elif isinstance(node, ast.ImportFrom):
            target = _absolute_target(node, package=package)
            if target in _BACKEND_MODULES:
                found.update(f"{target}.{alias.name}" for alias in node.names)
            elif target is not None:
                # ``from harness import linear`` binds the backend module itself.
                found.update(
                    f"{target}.{alias.name}"
                    for alias in node.names
                    if f"{target}.{alias.name}" in _BACKEND_MODULES
                )
        elif isinstance(node, ast.Attribute):
            dotted = _dotted_attribute_chain(node)
            if dotted is not None and dotted.rsplit(".", 1)[0] in _BACKEND_MODULES:
                found.add(dotted)
    return sorted(found)


def _backend_modules_from_seam(source_path: Path = SEAM_SOURCE) -> frozenset[str]:
    """The ``harness.*`` modules the tracker factory imports a ``*Client`` from.

    ``harness/tracker.py`` also imports ``layers``, ``repo_config`` and
    ``tracker_queue``, so the ``*Client`` shape — not "everything the factory
    imports" — is what separates a backend from the seam's own dependencies. A
    third backend has to be wired here to be reachable at all, which is what
    makes this an oracle for ``_BACKEND_MODULES`` rather than a second copy of
    it.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source_path.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("harness.")
            and any(alias.name.endswith("Client") for alias in node.names)
        ):
            found.add(node.module)
    return frozenset(found)


#: Every tracked ``*.py`` under ``harness/cli/``, recursively — ``__init__.py``,
#: the ``_``-prefixed shared helpers, the non-registering ``*_protocol`` /
#: ``query_*`` modules, and any future subpackage. The tracked set rather than an
#: ``rglob`` so an abandoned worktree parked under the package cannot read as
#: living source (#215), and the tracked set rather than the registration-derived
#: ``_COMMAND_MODULES`` because this rule's subject is every module in the
#: package, not only the ones that register a command: a lazy backend import is
#: most tempting exactly in a helper that registers nothing.
_CLI_SOURCES = tracked_py_sources("harness/cli", repo_root=REPO_ROOT)


def _cli_backend_offenders(
    sources: Iterable[Path],
    *,
    repo_root: Path = REPO_ROOT,
    exempt: dict[str, str] | None = None,
) -> list[str]:
    """One message per non-exempt source naming a backend, sorted.

    Reads source text and parses it; it never imports a scanned module, so no
    import-time side effect runs, no credential is read and no socket opens. A
    source that does not parse raises rather than being skipped — a syntax error
    in living source is a real defect, never a silently unscanned module.
    """
    exemptions = _BACKEND_EXEMPT if exempt is None else exempt
    offenders: list[str] = []
    for path in sources:
        rel = path.relative_to(repo_root).as_posix()
        if rel in exemptions:
            continue
        for reference in _backend_references(path.read_text(encoding="utf-8")):
            offenders.append(
                f"{rel} names {reference} — a CLI module reaches its tracker "
                "through harness.tracker.tracker_client(repo_root) and catches "
                "harness.tracker_errors, never a backend client (#339; the leak "
                "this prevents is #328)"
            )
    return sorted(offenders)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "import harness.linear\n", ["harness.linear"], id="import-absolute"
        ),
        pytest.param(
            "import harness.linear as lin\n", ["harness.linear"], id="import-aliased"
        ),
        pytest.param(
            "from harness.github import GitHubClient, github_token\n",
            ["harness.github.GitHubClient", "harness.github.github_token"],
            id="from-backend-two-names",
        ),
        pytest.param(
            "from harness import linear\n", ["harness.linear"], id="from-package"
        ),
        pytest.param(
            "from ..linear import LinearClient\n",
            ["harness.linear.LinearClient"],
            id="relative-level-2",
        ),
        pytest.param("from .. import github\n", ["harness.github"], id="relative-bare"),
        pytest.param(
            "import harness\nharness.github.GitHubClient(cfg)\n",
            ["harness.github.GitHubClient"],
            id="attribute-chain",
        ),
        pytest.param(
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from harness.linear import LinearClient\n",
            ["harness.linear.LinearClient"],
            id="type-checking-guarded",
        ),
        pytest.param(
            "from harness.tracker import tracker_client\n", [], id="seam-is-allowed"
        ),
        pytest.param(
            "from harness.tracker_errors import TrackerConfigError\n",
            [],
            id="error-vocabulary-is-allowed",
        ),
        pytest.param(
            "from harness.tracker_queue import QueueMembership\n",
            [],
            id="queue-module-is-allowed",
        ),
        pytest.param(
            '"""Prose naming harness.linear.LinearClient only."""\n',
            [],
            id="docstring-mention-is-not-a-reference",
        ),
        pytest.param(
            "from harness.cli.linear_notes import x\n", [], id="prefix-non-collision"
        ),
        pytest.param("from . import _verb\n", [], id="relative-level-1-bare"),
    ],
)
def test_the_backend_reference_detector_discriminates(
    source: str, expected: list[str]
) -> None:
    """Control for the tree-wide rule below, exercising **the same** predicate.

    The rule itself passes on today's clean tree, so it proves only that nothing
    currently violates it — never that the scanner can fire. This is the test
    that proves it can, and it routes through the one ``_backend_references``
    rather than an inline copy, so a detector degraded to a no-op fails here
    instead of going quietly green.

    The negative cases are the ones that make it a *discriminator*: the seam and
    the error vocabulary are what a verb is supposed to import, prose is why this
    reads the AST and not the text, and ``harness.cli.linear_notes`` is why
    matching is on exact dotted segments rather than a prefix.
    """
    assert _backend_references(source) == expected


def test_no_cli_module_imports_a_backend_client() -> None:
    """The rule: no module under ``harness/cli/`` names a backend client (#339).

    A CLI verb reaches its tracker through ``harness.tracker.tracker_client`` and
    catches ``harness.tracker_errors``; constructing a ``LinearClient`` or a
    ``GitHubClient`` directly gives backend selection a second source of truth.
    That is not hypothetical — ``promote escalate`` did exactly this until #328,
    which is why the escalation terminal was unreachable on the backend this repo
    actually dogfoods. This converts the contract from prose and review memory
    into a source-tree invariant.
    """
    offenders = _cli_backend_offenders(_CLI_SOURCES)
    assert not offenders, "backend-coupled CLI modules found:\n" + "\n".join(offenders)


def test_the_guard_fires_on_a_seeded_offender(tmp_path: Path) -> None:
    """The collection-level positive control: the scan reaches files and reports.

    Distinct from the detector control above, which proves only that the
    predicate discriminates on a string. This proves the layer around it — that
    sources are read, paths are made repo-relative, and the message names the
    remedy — so a scan wired to an empty file set cannot pass as a clean tree.
    """
    offender = tmp_path / "harness" / "cli" / "escalate.py"
    offender.parent.mkdir(parents=True)
    offender.write_text("from harness.linear import LinearClient\n")

    messages = _cli_backend_offenders([offender], repo_root=tmp_path)

    assert len(messages) == 1
    assert messages[0].startswith(
        "harness/cli/escalate.py names harness.linear.LinearClient"
    )
    assert "harness.tracker.tracker_client" in messages[0]


def test_an_exempt_module_is_skipped(tmp_path: Path) -> None:
    """The exemption path works — the only proof available while the live set is empty.

    Without this, ``_BACKEND_EXEMPT`` is four lines of structure nothing
    exercises: a lookup keyed on the wrong path shape would be invisible until
    the day someone needed it and the guard refused a documented exemption.
    """
    offender = tmp_path / "harness" / "cli" / "linear_migrate.py"
    offender.parent.mkdir(parents=True)
    offender.write_text("from harness.linear import LinearClient\n")

    exempt = {"harness/cli/linear_migrate.py": "backend-specific by purpose (#000)"}

    assert _cli_backend_offenders([offender], repo_root=tmp_path, exempt=exempt) == []


def test_the_scanned_set_covers_every_command_module() -> None:
    """Non-vacuity: the scanned set is non-empty and holds every command module.

    A scan over an empty or short file list passes trivially — the #219 failure
    this module already carries a lesson about. The two derivations in this file
    answer different questions (registrations vs. tracked sources), so checking
    one against the other is a real cross-check rather than a restatement.
    """
    assert _CLI_SOURCES, "the tracked CLI source set is empty — the scan is vacuous"

    scanned = {path.name for path in _CLI_SOURCES}
    missing = sorted(
        stem for stem in _COMMAND_MODULES if f"{stem}.py" not in scanned
    )
    assert not missing, f"command modules absent from the scanned set: {missing}"
    assert "__init__.py" in scanned


def test_backend_modules_match_the_seam_factory() -> None:
    """The denylist is pinned by an independent derivation of the same fact.

    ``tracker_client`` is the one place a backend is wired, so a third backend
    lands in ``harness/tracker.py`` first. Deriving the vocabulary from there
    means the denylist cannot silently fall behind the factory — the #219 lesson
    applied to a literal rather than to a file set.
    """
    assert _backend_modules_from_seam() == _BACKEND_MODULES


def test_the_seam_oracle_derives_rather_than_restates(tmp_path: Path) -> None:
    """The oracle reads its answer out of the source it is given.

    An oracle that returned the literal it is meant to check would agree with it
    forever. A synthetic factory wiring a third backend must therefore come back
    with three, naming the one the denylist has not heard of.
    """
    factory = tmp_path / "tracker.py"
    factory.write_text(
        "from harness.github import GitHubClient, GitHubConfigError\n"
        "from harness.linear import LinearClient, linear_api_key\n"
        "from harness.jira import JiraClient\n"
        "from harness.tracker_queue import QueueMembership\n"
        "from harness import layers, repo_config\n"
    )

    assert _backend_modules_from_seam(factory) == frozenset(
        {"harness.github", "harness.linear", "harness.jira"}
    )


def test_every_exemption_is_documented_and_resolves() -> None:
    """An exemption cannot arrive undocumented or outlive its module.

    Vacuously true today by design — the mapping is empty. It is the entry bar
    for the day it is not, which is why it checks the shape of an entry rather
    than a count.
    """
    scanned = {path.relative_to(REPO_ROOT).as_posix() for path in _CLI_SOURCES}
    for path, reason in _BACKEND_EXEMPT.items():
        assert path in scanned, f"exemption {path!r} names no tracked CLI source"
        assert reason.strip(), f"exemption {path!r} carries no reason"
        assert "#" in reason, f"exemption {path!r} cites no issue"


def test_promote_reaches_the_tracker_through_the_seam() -> None:
    """Explicit regression: the #328 leak the tree-wide rule generalises.

    Kept as a named pin beside ``test_reclaim_does_not_import_from_worktrees``
    for the same reason — the general rule would report it, but only this names
    the specific coupling and the ticket that removed it, so a future reader sees
    why ``promote.py`` is worth watching (it is on the architecture watchlist).
    """
    source = (CLI_DIR / "promote.py").read_text(encoding="utf-8")
    assert _backend_references(source) == [], (
        "harness/cli/promote.py must reach its tracker through "
        "harness.tracker.tracker_client, never a backend client directly (#328)"
    )
