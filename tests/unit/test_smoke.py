"""Smoke test — exists so pytest has at least one test to collect.

When real test suites land per H-002 onwards, this can be deleted.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

import harness


def test_version_is_set() -> None:
    assert harness.__version__
    assert isinstance(harness.__version__, str)


def test_cli_version_runs() -> None:
    """The harness CLI entrypoint can be invoked and reports a version."""
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "harness" in result.stdout


def test_cli_help_runs() -> None:
    """harness --help exits 0 and prints usage information."""
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "harness" in result.stdout.lower() or "usage" in result.stdout.lower()


def test_cli_validate_release() -> None:
    """harness validate workflows/release.yaml exits 0 for the bundled workflow."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent.parent
    workflow_file = repo_root / "workflows" / "release.yaml"
    if not workflow_file.exists():
        pytest.skip("release.yaml not present in this checkout")

    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "validate", "workflows/release.yaml"],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(repo_root),
    )
    assert result.returncode == 0, (
        f"harness validate failed (rc={result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
