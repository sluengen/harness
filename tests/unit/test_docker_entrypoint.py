"""Tests for ``docker/entrypoint.sh`` — the one-image / two-entrypoint switch.

Decision #3 (``specs/hermes-orchestration.md`` §Runtime topology, settled by
human call 2026-06-11): the per-session agent runtime (claude) and the per-call
verb container (codex) ship as a **single image with two entrypoints** — an
``agent`` mode and a ``verb`` mode. The entrypoint script selects the role
(CAL-585).

These tests drive the real script with stub ``claude`` / ``uv`` binaries on
``PATH`` (no docker, no real CLIs) and assert the dispatched command:

* ``agent <TICKET>`` → ``claude -p "/harness run <TICKET>"`` (decision #2:
  headless agent runtime drives the full verb loop non-interactively).
* ``verb <args…>`` → ``uv run harness <args…>`` (a single one-shot verb).
* a bare verb (no mode selector) stays backward compatible with the launcher /
  ``~/bin/harness`` wrapper, which invoke ``<image> start …`` directly.
* ``agent`` with no ticket is an invocation error (exit 2).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[2] / "docker" / "entrypoint.sh"

_STUB = """\
#!/usr/bin/env bash
# Stub binary: print a recognisable marker plus each argv token, then exit 0.
printf '%s' "$STUB_NAME"
for a in "$@"; do printf ' [%s]' "$a"; done
printf '\\n'
"""


def _make_stub(bin_dir: Path, name: str) -> None:
    stub = bin_dir / name
    stub.write_text(_STUB)
    stub.chmod(0o755)


def _run(args: list[str], bin_dir: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    # Put the stub dir first so the script's `claude` / `uv` resolve to stubs.
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["STUB_NAME"] = "STUB"
    return subprocess.run(
        ["bash", str(ENTRYPOINT), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.fixture
def bin_dir(tmp_path: Path) -> Path:
    d = tmp_path / "bin"
    d.mkdir()
    for name in ("claude", "uv"):
        _make_stub(d, name)
    return d


def test_entrypoint_script_exists_and_is_executable() -> None:
    assert ENTRYPOINT.exists(), f"missing {ENTRYPOINT}"
    assert os.access(ENTRYPOINT, os.X_OK), "entrypoint.sh must be executable"


def test_agent_mode_drives_harness_run_headless(bin_dir: Path) -> None:
    # `agent CAL-585` → `claude -p "/harness run CAL-585"`.
    proc = _run(["agent", "CAL-585"], bin_dir)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "STUB [-p] [/harness run CAL-585]"


def test_agent_mode_requires_a_ticket(bin_dir: Path) -> None:
    proc = _run(["agent"], bin_dir)
    assert proc.returncode == 2
    # Nothing was dispatched — no stub marker in stdout.
    assert "STUB" not in proc.stdout


def test_verb_mode_runs_a_single_one_shot_verb(bin_dir: Path) -> None:
    # `verb start CAL-1 --repo /x` → `uv run harness start CAL-1 --repo /x`.
    proc = _run(["verb", "start", "CAL-1", "--repo", "/x"], bin_dir)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "STUB [run] [harness] [start] [CAL-1] [--repo] [/x]"


def test_bare_verb_is_backward_compatible(bin_dir: Path) -> None:
    # The launcher and ~/bin/harness wrapper invoke `<image> start CAL-1 …`
    # directly (no mode selector). That must keep working as a verb invocation.
    proc = _run(["start", "CAL-1", "--repo", "/x"], bin_dir)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "STUB [run] [harness] [start] [CAL-1] [--repo] [/x]"
