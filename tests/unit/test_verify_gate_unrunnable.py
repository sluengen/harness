"""CAL-1160 — the verify gate signals a toolchain failure as *blocked*, not red.

``promote``'s classifier keys ``blocked`` (infrastructure) apart from
``needs_ticket`` (a red tree) off a **reserved exit code** the gate emits when its
toolchain cannot even launch. That reserved code is single-sourced in
:data:`harness.gate.GATE_UNRUNNABLE_EXIT`; ``scripts/verify.sh`` carries the same
literal in a preflight. This module pins both halves:

* the two-place literal cannot drift (the bash value must equal the Python
  constant);
* a **real** run of ``scripts/verify.sh`` with the toolchain made unavailable
  exits that reserved code — the proof a real gate can *produce* the ``blocked``
  signal, which the old ``exit_code=None`` monkeypatch faked. Together with the
  CLI test that maps the code to ``blocked``, this closes the reachability gap.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from harness.gate import GATE_UNRUNNABLE_EXIT

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY = REPO_ROOT / "scripts" / "verify.sh"


def _reserved_exit_literal() -> int:
    """The reserved exit code assigned in ``scripts/verify.sh`` (``GATE_UNRUNNABLE_EXIT=<N>``).

    Fails loudly if the assignment is absent so the preflight cannot be silently
    dropped."""
    match = re.search(
        r"^\s*GATE_UNRUNNABLE_EXIT=(\d+)\s*$", VERIFY.read_text(), re.MULTILINE
    )
    assert match is not None, (
        "scripts/verify.sh must assign GATE_UNRUNNABLE_EXIT=<N> in its toolchain "
        "preflight (CAL-1160)."
    )
    return int(match.group(1))


def test_verify_reserved_code_matches_python_constant() -> None:
    """The bash literal equals :data:`harness.gate.GATE_UNRUNNABLE_EXIT` — the two
    homes of the reserved code cannot drift, or an infra failure would classify as a
    red tree again."""
    assert _reserved_exit_literal() == GATE_UNRUNNABLE_EXIT, (
        "scripts/verify.sh's reserved exit code must equal "
        "harness.gate.GATE_UNRUNNABLE_EXIT (CAL-1160)."
    )


def test_verify_exits_reserved_code_when_toolchain_unavailable(tmp_path: Path) -> None:
    """A real ``scripts/verify.sh`` run whose ``uv`` cannot launch its tools exits
    the reserved ``GATE_UNRUNNABLE_EXIT`` — before any check runs.

    A stub ``uv`` that always fails models the observed live infrastructure failure
    (``error: Failed to spawn: ruff``): the preflight probe ``uv run --extra dev
    <tool> --version`` fails, so the gate exits the reserved code deterministically
    rather than a generic non-zero indistinguishable from a red tree. No monkeypatch
    — this is the gate script itself."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text("#!/bin/sh\nexit 3\n")  # uv present but its run cannot spawn the tool
    fake_uv.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

    result = subprocess.run(
        ["bash", str(VERIFY)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == GATE_UNRUNNABLE_EXIT, (
        f"expected verify.sh to exit {GATE_UNRUNNABLE_EXIT} on an unrunnable "
        f"toolchain; got {result.returncode}\nstdout={result.stdout}\n"
        f"stderr={result.stderr}"
    )


def test_verify_preflights_the_parallel_plugin() -> None:
    """The xdist probe is part of the preflight, not a bare ``-n`` on the stage (#358).

    ``-n`` is pytest-xdist's flag: without the plugin, pytest exits **4** (usage
    error), which the promotion classifier cannot tell from a red tree — so a
    developer venv predating the parallel gate would file a ticket blaming the
    code. Probing it alongside ruff/mypy/pytest routes that case to the same
    reserved ``blocked`` code.

    Pinned as *probe implies reserved exit* rather than as a line match, so the
    check cannot be satisfied by a probe that fails the gate red instead.
    """
    text = VERIFY.read_text()
    probe = re.search(r"^.*import xdist.*$", text, re.MULTILINE)
    assert probe is not None, (
        "scripts/verify.sh must preflight `import xdist`: the parallel stage "
        "passes -n, and a venv without the plugin is a toolchain failure, not a "
        "red tree (#358)."
    )
    tail = text[probe.end() :]
    guarded = tail[: tail.find("\nfi")] if "\nfi" in tail else tail
    assert 'exit "$GATE_UNRUNNABLE_EXIT"' in guarded, (
        "the xdist preflight must exit the reserved GATE_UNRUNNABLE_EXIT so a "
        "stale venv classifies as `blocked`, not `needs_ticket` (#358, CAL-1160)."
    )
