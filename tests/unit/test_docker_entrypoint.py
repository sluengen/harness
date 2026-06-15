"""Tests for ``docker/entrypoint.sh`` — the one-shot verb container.

The image runs one audited verb per container, exactly as the ``~/bin/harness``
wrapper invokes ``<image> start CAL-1 --repo …``. (The launcher-socket ``agent``
mode for an autonomous per-session runtime was the deferred Hermes-dispatch
scaffolding, removed in CAL-712 — see ``specs/retired/hermes-orchestration.md``.)

These tests drive the real script with stub ``uv`` on ``PATH`` (no docker, no
real CLIs) and assert the dispatched command:

* ``verb <args…>`` → ``uv run harness <args…>`` (a single one-shot verb).
* a bare verb (no mode selector) stays backward compatible with the
  ``~/bin/harness`` wrapper, which invokes ``<image> start …`` directly.
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
    _make_stub(d, "uv")
    return d


def test_entrypoint_script_exists_and_is_executable() -> None:
    assert ENTRYPOINT.exists(), f"missing {ENTRYPOINT}"
    assert os.access(ENTRYPOINT, os.X_OK), "entrypoint.sh must be executable"


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
