"""Tests for bin/harness shell wrapper.

The wrapper must:
- Exist at ``bin/harness`` relative to the project root.
- Be executable (mode includes x bit).
- Unset ``VIRTUAL_ENV`` before invoking the harness CLI so a foreign venv
  (e.g. a Homebrew-managed path) does not pollute the invocation.
- Pass all positional arguments through to ``harness.cli`` unchanged.
- Produce no ``uv`` VIRTUAL_ENV warning even when ``VIRTUAL_ENV`` is set.

See SPEC §11 for context.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Project root — two levels above tests/unit/
PROJECT_ROOT = Path(__file__).parent.parent.parent
BIN_HARNESS = PROJECT_ROOT / "bin" / "harness"


# ---------------------------------------------------------------------------
# AC1 — wrapper exists and is executable
# ---------------------------------------------------------------------------


def test_wrapper_exists() -> None:
    """bin/harness must exist as a file."""
    assert BIN_HARNESS.exists(), f"Expected wrapper at {BIN_HARNESS}"
    assert BIN_HARNESS.is_file(), f"{BIN_HARNESS} is not a regular file"


def test_wrapper_is_executable() -> None:
    """bin/harness must be executable by the current user."""
    assert os.access(BIN_HARNESS, os.X_OK), f"{BIN_HARNESS} is not executable"


# ---------------------------------------------------------------------------
# AC2 — basic delegation
# ---------------------------------------------------------------------------


def test_wrapper_runs_version() -> None:
    """``bin/harness version`` must exit 0 and print 'harness'."""
    result = subprocess.run(
        [str(BIN_HARNESS), "version"],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "harness" in result.stdout


def test_wrapper_passes_help_flag() -> None:
    """``bin/harness --help`` must exit 0 and print usage information."""
    result = subprocess.run(
        [str(BIN_HARNESS), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    # Typer renders help with "Usage:" or the app description
    combined = result.stdout + result.stderr
    assert "harness" in combined.lower() or "Usage" in combined


# ---------------------------------------------------------------------------
# AC3 — foreign VIRTUAL_ENV is silently ignored
# ---------------------------------------------------------------------------


def test_wrapper_succeeds_with_foreign_virtual_env() -> None:
    """Running with VIRTUAL_ENV pointing at a non-project path must succeed.

    This is the core regression test.  Without the wrapper, uv
    either silently uses the wrong interpreter (``ModuleNotFoundError``) or
    emits a warning and exits.  The wrapper bypasses uv entirely, so
    VIRTUAL_ENV is irrelevant.
    """
    env = {**os.environ, "VIRTUAL_ENV": "/tmp/nonexistent-foreign-venv"}
    result = subprocess.run(
        [str(BIN_HARNESS), "version"],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=PROJECT_ROOT,
        env=env,
    )
    assert result.returncode == 0, (
        f"Expected exit 0 with foreign VIRTUAL_ENV.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "harness" in result.stdout


def test_wrapper_emits_no_virtual_env_warning() -> None:
    """No uv VIRTUAL_ENV warning must appear in stderr.

    uv emits "VIRTUAL_ENV=... does not match the project environment path"
    when a foreign venv is active.  The wrapper must suppress this by
    unsetting VIRTUAL_ENV before any uv call.
    """
    env = {**os.environ, "VIRTUAL_ENV": "/opt/homebrew/Cellar/python@3.11/fake"}
    result = subprocess.run(
        [str(BIN_HARNESS), "version"],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=PROJECT_ROOT,
        env=env,
    )
    # uv prints its warnings to stderr; none should reference VIRTUAL_ENV
    assert "VIRTUAL_ENV" not in result.stderr, (
        f"Unexpected uv warning in stderr:\n{result.stderr}"
    )
    assert "ModuleNotFoundError" not in result.stderr
