"""Module-boundary guards for the CLI package (CAL-1013).

Two structural invariants the consolidation establishes:

1. The short-duration parser lives in a shared home (:mod:`harness.cli._duration`),
   not inside a sibling *command* module — so importing it is not a
   cross-command private import.
2. No verb command imports another command module's private helper. ``reclaim``
   used to reach into ``worktrees`` for ``_parse_duration``; that coupling is
   gone. These are text-parse guards in the style of the repo's other
   source-scan tests.
"""

from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path

import pytest

CLI_DIR = Path(__file__).resolve().parents[2] / "harness" / "cli"

#: Command modules (a verb / subcommand surface), as opposed to the shared
#: ``_``-prefixed helper modules. A command must not import another command's
#: private (``_``-prefixed) name.
_COMMAND_MODULES = {
    "start",
    "review",
    "close",
    "checkpoint",
    "reclaim",
    "cancel",
    "worktrees",
    "doctor",
}


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


def _imports_of(module_stem: str) -> list[tuple[str, str]]:
    """Return ``(module, name)`` pairs for every ``from X import Y`` in a CLI
    module — resolving the imported *name* so a private helper is visible."""
    source = (CLI_DIR / f"{module_stem}.py").read_text()
    tree = ast.parse(source)
    pairs: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                pairs.append((node.module, alias.name))
    return pairs


def test_no_command_imports_a_sibling_commands_private_helper() -> None:
    """No command module imports a private name from another *command* module.

    (Importing a public name, or anything from a shared ``_``-helper module such
    as ``_verb`` / ``_duration`` / ``_git``, is fine.)
    """
    offenders: list[str] = []
    for stem in _COMMAND_MODULES:
        for module, name in _imports_of(stem):
            if not module.startswith("harness.cli."):
                continue
            target = module.rsplit(".", 1)[-1]
            if target in _COMMAND_MODULES and name.startswith("_"):
                offenders.append(f"{stem}.py imports private {name!r} from {target}.py")
    assert not offenders, "cross-command private imports found: " + "; ".join(offenders)


def test_reclaim_does_not_import_from_worktrees() -> None:
    """Explicit regression: the specific coupling CAL-1013 removed stays gone."""
    imports = _imports_of("reclaim")
    assert not any(
        module == "harness.cli.worktrees" for module, _ in imports
    ), "reclaim.py must not import from the worktrees command module"
