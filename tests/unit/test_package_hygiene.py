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

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE = _REPO_ROOT / "harness"

# Source and typing markers are the only things allowed inside the import package.
_ALLOWED_SUFFIXES = {".py", ".pyi"}
_ALLOWED_NAMES = {"py.typed"}


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
