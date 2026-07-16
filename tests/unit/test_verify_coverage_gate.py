"""CAL-1015 — the verification gate enforces a coverage floor.

``pytest-cov`` is a dev dependency but the gate ran plain ``pytest``, so line
coverage could silently erode change over change. This wires the floor into the
one gate every merge and release runs (``scripts/verify.sh``): the pytest step
measures the ``harness`` package and fails below ``--cov-fail-under=90`` (90
leaves headroom below the 91% baseline measured 2026-07-06).

The behavioural half of the acceptance criterion — *the current suite passes the
gate* — is proven by running ``scripts/verify.sh`` itself, which now measures
coverage on every invocation; this guard pins the *wiring* so the floor cannot
be silently dropped back to plain pytest (both flags must survive on the pytest
command, and the floor value is asserted exactly, so a stray ``--cov-fail-under``
with no number would not satisfy it).

*Source:* CAL-1015 (review-finding, 2026-07-06 5-dimension assessment).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY = REPO_ROOT / "scripts" / "verify.sh"

#: The floor the gate enforces. Chosen below the 91% baseline to leave headroom.
COVERAGE_FLOOR = 90


def _pytest_command() -> str:
    """The gate's pytest invocation line (non-comment) from ``scripts/verify.sh``.

    The gate runs pytest through a single ``uv run … pytest …`` command; return
    that line so assertions bind to the real invocation rather than to a comment
    that merely mentions pytest. Fails loudly if no such line exists.
    """
    lines = [
        ln
        for ln in VERIFY.read_text().splitlines()
        if "pytest" in ln and not ln.lstrip().startswith("#")
    ]
    assert lines, "scripts/verify.sh must invoke pytest"
    # The command line is the one that actually runs pytest (has `uv run`).
    cmd = [ln for ln in lines if "uv run" in ln and "pytest" in ln]
    assert cmd, "scripts/verify.sh must run pytest via `uv run … pytest`"
    return cmd[0]


def test_gate_measures_the_harness_package() -> None:
    """The pytest step scopes coverage to the ``harness`` package."""
    assert "--cov=harness" in _pytest_command(), (
        "scripts/verify.sh's pytest step must pass --cov=harness so the coverage "
        "floor measures the harness package (CAL-1015)."
    )


def test_gate_enforces_the_coverage_floor() -> None:
    """The pytest step fails the gate below the coverage floor."""
    cmd = _pytest_command()
    match = re.search(r"--cov-fail-under=(\d+)", cmd)
    assert match is not None, (
        "scripts/verify.sh's pytest step must pass --cov-fail-under=<N> so the "
        "gate fails when coverage drops below the floor (CAL-1015)."
    )
    assert int(match.group(1)) == COVERAGE_FLOOR, (
        f"the coverage floor must be {COVERAGE_FLOOR} (90 leaves headroom below "
        f"the 91% baseline); found --cov-fail-under={match.group(1)} (CAL-1015)."
    )
