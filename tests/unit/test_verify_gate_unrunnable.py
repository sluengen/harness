"""CAL-1160 — the verify gate signals a toolchain failure as *blocked*, not red.

``scripts/verify.sh`` reserves an exit code for "the gate could not run at all":
a missing tool or a broken venv is infrastructure, not a red tree, and a caller
reading only the exit code cannot otherwise tell the two apart. This module pins
that the preflight exists and that a **real** run of the script against a broken
toolchain actually produces the reserved code — the property a line-match on the
script would not prove.

**#435 inlined the reserved code.** It was single-sourced in
``harness.gate.GATE_UNRUNNABLE_EXIT`` and cross-checked against the bash literal,
because the promotion classifier read the Python constant to key ``blocked``
apart from ``needs_ticket``. ADR 0015 retires that classifier with the package,
so there is no second home to drift from and the two-place-literal test went with
it. The script is now the only home, and 97 is written here as the expected
value: the executing test below is what binds it, and it fails if the preflight
is dropped, reordered after a check, or made to exit anything else.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY = REPO_ROOT / "scripts" / "verify.sh"

#: The reserved "gate could not run" exit code. Distinct from 1 (a red tree) and
#: from pytest's 4 (usage error), which is the whole point of reserving it.
GATE_UNRUNNABLE_EXIT = 97


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
    assert _reserved_exit_literal() == GATE_UNRUNNABLE_EXIT, (
        "the script's reserved literal must be the code this module expects — "
        "otherwise the executing assertion above would silently start pinning a "
        "different contract than the one documented here (CAL-1160)."
    )


def test_verify_preflights_the_parallel_plugin() -> None:
    """The xdist probe is part of the preflight, not a bare ``-n`` on the stage (#358).

    ``-n`` is pytest-xdist's flag: without the plugin, pytest exits **4** (usage
    error), which a caller cannot tell from a red tree — so a developer venv
    predating the parallel gate would read as a code failure. Probing it alongside
    ruff/mypy/pytest routes that case to the same reserved code.

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
        "stale venv reads as a toolchain failure, not a red tree (#358, CAL-1160)."
    )
