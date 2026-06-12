"""Package-tree hygiene — the importable ``harness/`` package ships only source.

The wheel target bundles everything under ``harness/`` (``[tool.hatch.build.targets.wheel]
packages = ["harness"]``), so any non-source file placed there leaks into the
distributed artifact as package data and pollutes the import tree. Agent-process
artifacts (code-review writeups, lessons, retros) belong in the top-level
``lessons/`` / ``process/`` dirs, never inside the package.

This guard is deliberately structural: dropping a ``.md`` (or other non-source)
file under ``harness/`` fails here. If a future change genuinely needs to bundle
package data, widen ``_ALLOWED_SUFFIXES`` / ``_ALLOWED_NAMES`` as a conscious,
reviewed decision rather than by accident.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE = _REPO_ROOT / "harness"

# Source and typing markers are the only things allowed inside the import package.
_ALLOWED_SUFFIXES = {".py", ".pyi"}
_ALLOWED_NAMES = {"py.typed"}


def _is_placeholder_module(path: Path) -> bool:
    """True if a ``.py`` file carries no code — empty, or only a module docstring.

    Such a module exports nothing; once nothing imports it, it is dead surface.
    """
    body = ast.parse(path.read_text()).body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]  # strip a leading module docstring
    return not body


def test_package_tree_contains_only_source() -> None:
    """No process artifacts or other non-source files live under ``harness/``."""
    strays = [
        path.relative_to(_REPO_ROOT)
        for path in _PACKAGE.rglob("*")
        if path.is_file()
        and not path.name.startswith(".")  # skip OS/editor dotfile cruft (e.g. .DS_Store)
        and "__pycache__" not in path.parts
        and path.suffix not in _ALLOWED_SUFFIXES
        and path.name not in _ALLOWED_NAMES
    ]
    assert not strays, (
        "Non-source files leaked into the importable harness/ package "
        f"(move them to top-level lessons/ or process/): {sorted(map(str, strays))}"
    )


def test_package_tree_has_no_placeholder_modules() -> None:
    """No content-free ``.py`` module lingers under ``harness/`` as dead surface.

    The structural ``only source`` guard above passes a docstring-only or 0-byte
    module — it is still a ``.py`` file. But such a module exports nothing; left
    behind after a subsystem retirement it reads as a live API while being dead
    weight (e.g. the engine-era ``log.py`` / ``tools/`` placeholders CAL-574 left).
    An empty ``__init__.py`` is exempt *only* while it marks a package that holds a
    real module — a package whose sole content is an empty ``__init__.py`` is itself
    vestigial and is flagged.
    """
    placeholders = []
    for path in _PACKAGE.rglob("*.py"):
        if "__pycache__" in path.parts or not _is_placeholder_module(path):
            continue
        if path.name == "__init__.py":
            has_real_module = any(
                sibling.name != "__init__.py" and "__pycache__" not in sibling.parts
                for sibling in path.parent.rglob("*.py")
            )
            if has_real_module:
                continue  # legitimate package marker
        placeholders.append(path.relative_to(_REPO_ROOT))
    assert not placeholders, (
        "Content-free placeholder modules linger under harness/ "
        "(delete them — a docstring-only or empty module exports nothing): "
        f"{sorted(map(str, placeholders))}"
    )
