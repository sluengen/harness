"""Fixtures that create evidence only through the shipped marker runner."""

from __future__ import annotations

from pathlib import Path


def install_internal_gate(repo: Path, *, exit_code: int = 0) -> None:
    """Install the smallest fixed gate accepted by ``gate-marker.js run``.

    The environment assertion proves that a fixture took the runner's internal
    branch.  Test suites deliberately keep this gate synthetic: their subject is
    the marker contract, not Harness's full verification suite.
    """
    scripts = repo / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "verify.sh").write_text(
        "#!/usr/bin/env sh\n"
        'test "${HARNESS_GATE_MARKER_RUNNER:-}" = "1"\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
