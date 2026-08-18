"""#478 — the gate preflight probes node with the same reserved-exit-code pattern.

Admission (ADR 0017 D5): class (a) — ``scripts/verify.sh`` executed against a
stubbed toolchain, asserting the exit code and diagnostic the preflight
produces.

The preflight (CAL-1160) probes ruff, mypy, pytest and pytest-xdist so a broken
venv reads as *the gate could not run* (the reserved exit 97), never as a red
tree. Node was the hole: the gate itself runs no node, but the suite the gate
runs executes the enforcement and advisory hooks (``hooks/*.js``) under node —
and **skips** those tests when node is missing (every hook module's ``_node()``
helper is a ``pytest.skip``). So a broken or absent node produced a green gate
whose marker claimed a tree verified, while the hook guards the marker exists
to serve were never run. That is an infrastructure failure wearing a green
gate, which is exactly the misreading the reserved code exists to prevent.

The gate is executed with a stub ``PATH``: a ``uv`` that answers every probe
with success, and node either absent, broken, or runnable. The stub is what
makes the probe's own behaviour observable in isolation — with the real
toolchain the earlier probes dominate the outcome.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.unit._prose import REPO_ROOT

VERIFY = REPO_ROOT / "scripts" / "verify.sh"

#: The reserved code: *the gate could not run* — distinct from a red tree (1).
GATE_UNRUNNABLE_EXIT = 97


def _stub(bindir: Path, name: str, *, exit_code: int = 0) -> None:
    stub = bindir / name
    stub.write_text(f"#!/bin/sh\nexit {exit_code}\n")
    stub.chmod(0o755)


def _run_gate(bindir: Path) -> subprocess.CompletedProcess[str]:
    """Run the real gate script with ``bindir`` as the entire ``PATH``."""
    return subprocess.run(
        ["/bin/bash", str(VERIFY)],
        cwd=REPO_ROOT,
        env={"PATH": str(bindir)},
        capture_output=True,
        text=True,
        timeout=100,
    )


def test_a_missing_node_exits_the_reserved_infrastructure_code(tmp_path: Path) -> None:
    """No node on PATH is 'the gate could not run', never a green (or red) tree.

    The stub ``uv`` answers every earlier probe and every later stage with
    success, so without the node probe this run exits 0 — a green gate over a
    tree whose hook guards were silently skipped, which is the #478 defect.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub(bindir, "uv")

    proc = _run_gate(bindir)

    assert proc.returncode == GATE_UNRUNNABLE_EXIT, (
        f"expected the reserved exit {GATE_UNRUNNABLE_EXIT} for a missing node; "
        f"got {proc.returncode} (stdout: {proc.stdout!r})"
    )
    assert "gate precondition failed" in proc.stderr
    assert "node" in proc.stderr, (
        f"the diagnostic must name the missing tool: {proc.stderr!r}"
    )


def test_a_broken_node_is_the_same_infrastructure_failure(tmp_path: Path) -> None:
    """A node that cannot even answer ``--version`` is as absent as no node."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub(bindir, "uv")
    _stub(bindir, "node", exit_code=1)

    proc = _run_gate(bindir)

    assert proc.returncode == GATE_UNRUNNABLE_EXIT
    assert "node" in proc.stderr


def test_a_runnable_node_passes_the_probe(tmp_path: Path) -> None:
    """With node answering, the preflight moves on — the probe adds no false
    refusal. Everything downstream is the success stub, so the only way this
    run could exit {GATE_UNRUNNABLE_EXIT} is the probe misfiring."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub(bindir, "uv")
    _stub(bindir, "node")

    proc = _run_gate(bindir)

    assert proc.returncode != GATE_UNRUNNABLE_EXIT, (
        f"the node probe refused a runnable node: {proc.stderr!r}"
    )
