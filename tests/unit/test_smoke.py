"""Smoke test — exists so pytest has at least one test to collect.

When real test suites land per H-002 onwards, this can be deleted.
"""

from __future__ import annotations

import subprocess
import sys

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
