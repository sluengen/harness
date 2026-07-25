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

CLI_DIR = Path(__file__).resolve().parents[2] / "harness" / "cli"
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
    """``status`` / ``logs`` / ``events`` / ``runs`` are four names, one module."""
    query_names = {
        name for name, stem in _COMMAND_MODULES_BY_NAME.items() if stem == "query"
    }
    assert query_names == {"status", "logs", "events", "runs"}


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
