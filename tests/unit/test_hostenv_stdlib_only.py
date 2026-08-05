"""``harness.hostenv`` must import under a bare host interpreter (#305).

The wrapper runs this package on the **host**, before any container exists, under
an interpreter that is frequently not the project venv — the third rung of the
interpreter ladder is a bare ``python3`` with ``PYTHONPATH`` pointed at the
checkout. A pydantic/typer/aiosqlite/ulid import anywhere in the package would make
the wrapper depend on the very environment it is being run to set up, and the
failure would appear as a credential-less container 401 rather than as an import
error anyone reads.

The dependency set is **derived from ``pyproject.toml``**, not listed here. A
hardcoded list is self-satisfiable: it would keep passing on the day a fifth
dependency is added, which is exactly when it needs to fail.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
HOSTENV = PROJECT_ROOT / "harness" / "hostenv"
PYPROJECT = PROJECT_ROOT / "pyproject.toml"


def third_party_dependencies() -> set[str]:
    """The distribution's runtime dependencies, as importable top-level names.

    Derived from ``pyproject.toml``'s ``[project] dependencies`` so a newly added
    dependency is covered the moment it lands.
    """
    text = PYPROJECT.read_text()
    block = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M)
    assert block, "could not locate [project] dependencies in pyproject.toml"

    names = set()
    for raw in re.findall(r'"([^"]+)"', block.group(1)):
        name = re.split(r"[<>=!~\[ ]", raw, maxsplit=1)[0].strip()
        if name:
            names.add(name.replace("-", "_").lower())
    return names


def imported_top_level_modules(path: Path) -> set[str]:
    """Every top-level module name imported by a source file."""
    tree = ast.parse(path.read_text())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
    return modules


def hostenv_sources() -> list[Path]:
    return sorted(HOSTENV.glob("*.py"))


# ---------------------------------------------------------------------------
# Non-vacuity floors. Both derived sets must be proven non-empty and proven to
# read the tree, or the ban below passes for lack of anything to check.
# ---------------------------------------------------------------------------


def test_the_dependency_set_is_non_empty_and_read_from_the_tree() -> None:
    dependencies = third_party_dependencies()

    assert dependencies, "no dependencies parsed — the ban below would be vacuous"
    assert "pydantic" in dependencies, (
        "pydantic is a declared runtime dependency; if it is not in the derived set "
        "the parser is not reading pyproject.toml"
    )


def test_the_source_set_is_non_empty_and_covers_the_package() -> None:
    sources = hostenv_sources()
    names = {p.name for p in sources}

    assert names >= {"__init__.py", "__main__.py", "host.py", "credentials.py"}, (
        f"the scan is missing package modules; found {sorted(names)}"
    )


def test_the_import_scanner_sees_a_banned_import_in_synthetic_source(tmp_path: Path) -> None:
    """The floor that matters: run the real scanner over source that *does* import a
    dependency, and prove it is caught.

    A floor that re-implements the scanner's own walk is not a floor — this exercises
    :func:`imported_top_level_modules` itself against a value nothing in the tree
    declares.
    """
    offender = tmp_path / "offender.py"
    offender.write_text("import pydantic\nfrom typer import Typer\nimport json\n")

    found = imported_top_level_modules(offender)

    assert "pydantic" in found
    assert "typer" in found
    assert found & third_party_dependencies(), "the scanner failed to catch a real import"


# ---------------------------------------------------------------------------
# The ban itself
# ---------------------------------------------------------------------------


def test_no_hostenv_module_imports_a_third_party_dependency() -> None:
    dependencies = third_party_dependencies()

    offenders = {
        source.name: sorted(imported_top_level_modules(source) & dependencies)
        for source in hostenv_sources()
    }
    offenders = {name: found for name, found in offenders.items() if found}

    assert not offenders, (
        f"harness.hostenv must be stdlib-only, but these modules import declared "
        f"dependencies: {offenders}. The wrapper runs this package under a bare host "
        f"interpreter before any container exists."
    )


def test_the_package_imports_under_a_bare_interpreter(tmp_path: Path) -> None:
    """The claim, measured end-to-end rather than inferred from the import graph.

    Run the real interpreter with an empty ``sys.path`` addition of the checkout only
    and **no** installed dependencies visible, then import the package. This is the
    third rung of the wrapper's interpreter ladder, exercised for real.
    """
    probe = (
        "import sys;"
        # Drop anything that could be supplying the project's dependencies.
        "sys.path=[p for p in sys.path if 'site-packages' not in p and 'dist-packages' not in p];"
        f"sys.path.insert(0, {str(PROJECT_ROOT)!r});"
        "import harness.hostenv.host, harness.hostenv.credentials, harness.hostenv.__main__;"
        "print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, cwd=tmp_path
    )

    assert result.returncode == 0, (
        f"harness.hostenv failed to import without site-packages:\n{result.stderr}"
    )
    assert "ok" in result.stdout


def test_the_bare_interpreter_probe_would_fail_on_a_dependency_import(tmp_path: Path) -> None:
    """Non-vacuity for the probe above: the same isolation must reject a real import.

    Without this, a probe that silently kept site-packages on the path would report
    success for every possible package content.
    """
    probe = (
        "import sys;"
        "sys.path=[p for p in sys.path if 'site-packages' not in p and 'dist-packages' not in p];"
        f"sys.path.insert(0, {str(PROJECT_ROOT)!r});"
        "import pydantic"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, cwd=tmp_path
    )

    assert result.returncode != 0, (
        "the isolation is not isolating — site-packages is still reachable, so the "
        "stdlib-only probe above proves nothing"
    )
