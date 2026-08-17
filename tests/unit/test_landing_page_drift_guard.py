"""Gate-level drift guard for the repo-guide landing page (#169 / CAL-1202).

The landing page ``docs/index.html`` is hand-authored and duplicates the
guidance catalog that lives canonically in ``registry.yaml`` — so it rots. The
accepted proposal (``specs/proposals/repo-guide-landing-page.md``) chose a
*lean gate guard, not a generator*: a ``scripts/`` check, wired into
``scripts/verify.sh``, that fails the gate when the page names a piece of
guidance the registry no longer has (a renamed or removed command / skill /
agent the page still references — the highest-likelihood drift).

Every named piece of guidance on the page carries a ``data-guidance="<id>"``
attribute (the machine-readable reference convention established by CAL-1200),
so "every named ``/command``, skill, and agent" is exactly the set of those
attributes. The guard resolves each against ``registry.yaml`` and fails on a
ghost.

These tests pin the three acceptance criteria:

  AC-1  the check FAILS the gate when a ghost reference is injected (regression);
  AC-2  the check PASSES on the real, current page;
  AC-3  it runs as part of ``bash scripts/verify.sh``.

The guard is exercised both as a pure function (``find_ghost_references``) and
as the actual script a subprocess runs — so a green here means the real gate
command behaves.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from tests.unit._prose import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "check_landing_page_guidance.py"
PAGE = REPO_ROOT / "docs" / "index.html"
REGISTRY = REPO_ROOT / "registry.yaml"
VERIFY = REPO_ROOT / "scripts" / "verify.sh"


def _guard():
    """Import the standalone script as a module (``scripts/`` is not a package)."""
    spec = importlib.util.spec_from_file_location("check_landing_page_guidance", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# AC-2 — the check PASSES on the real, current page
# --------------------------------------------------------------------------- #


def test_real_page_has_no_ghost_references() -> None:
    """Every guidance id the real page names resolves in registry.yaml."""
    guard = _guard()
    ghosts = guard.find_ghost_references(
        PAGE.read_text(encoding="utf-8"),
        REGISTRY.read_text(encoding="utf-8"),
    )
    assert ghosts == [], f"real page names guidance absent from registry.yaml: {ghosts}"


def test_script_exits_zero_on_real_page() -> None:
    """Running the actual script against the real page succeeds (gate passes)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"guard failed on the real page (exit {result.returncode}):\n"
        f"{result.stdout}\n{result.stderr}"
    )


# --------------------------------------------------------------------------- #
# AC-1 — the check FAILS when a ghost reference is injected
# --------------------------------------------------------------------------- #


def test_injected_ghost_is_detected() -> None:
    """A guidance reference that does not resolve is reported as a ghost."""
    guard = _guard()
    tampered = PAGE.read_text(encoding="utf-8") + (
        '\n<span data-guidance="ghost-command-xyz">/ghost</span>\n'
    )
    ghosts = guard.find_ghost_references(tampered, REGISTRY.read_text(encoding="utf-8"))
    assert ghosts == ["ghost-command-xyz"], f"expected the injected ghost, got {ghosts}"


def test_script_exits_nonzero_on_injected_ghost(tmp_path: Path) -> None:
    """The script FAILS (non-zero) when pointed at a page carrying a ghost.

    This is the regression the acceptance criterion asks for: a renamed/removed
    piece of guidance the page still names must fail the gate.
    """
    tampered = tmp_path / "index.html"
    tampered.write_text(
        PAGE.read_text(encoding="utf-8")
        + '\n<span data-guidance="ghost-command-xyz">/ghost</span>\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--page", str(tampered)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "guard must fail the gate when a ghost is present"
    assert "ghost-command-xyz" in (result.stdout + result.stderr), (
        "the failure must name the offending ghost reference"
    )


def test_empty_page_fails_rather_than_passing_vacuously(tmp_path: Path) -> None:
    """A page with zero guidance references is a failure, not a vacuous pass.

    The page always names guidance; zero references means the structure changed
    (or the page is broken) — exactly the silent-rot case the guard exists to
    catch, so it must not pass quietly.
    """
    empty = tmp_path / "index.html"
    empty.write_text("<html><body>no guidance here</body></html>", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--page", str(empty)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "a page with no guidance references must fail the guard"


# --------------------------------------------------------------------------- #
# AC-3 — the guard runs as part of scripts/verify.sh
# --------------------------------------------------------------------------- #


def test_guard_is_wired_into_verify_sh() -> None:
    """``scripts/verify.sh`` invokes the drift guard, so the gate runs it."""
    verify = VERIFY.read_text(encoding="utf-8")
    assert "check_landing_page_guidance.py" in verify, (
        "scripts/verify.sh must invoke the landing-page drift guard"
    )
