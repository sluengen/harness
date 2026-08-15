"""The two timeout budgets that bound a CI run stay coherent (CAL-1110, #357, #435).

Two numbers decide how long anything in this repo may take: pytest-timeout's
per-test cap (``pyproject.toml`` → ``tool.pytest.ini_options.timeout``) and the CI
job's wall clock (``.github/workflows/ci.yml`` → ``timeout-minutes``). They are
declared in different files by different people, and each is only meaningful
relative to the other — a per-test cap above the job budget makes the cap
decoration, because the job dies first and the test it was meant to bound never
times out.

**This module used to be much larger, and #435 is why it is not.** CAL-1110 and
#357 were both about the same inversion in a *third* kind of budget: a
module-scoped fixture running ``docker build`` for hundreds of seconds under a
120s cap that covered fixture setup. Everything here that parsed a module's
``pytest.mark.timeout``, read a fixture's ``subprocess.run(..., timeout=…)``, and
replayed the ``func_only`` phase semantics against a generated module existed to
bound ``tests/integration/test_docker.py`` and ``tests/integration/test_serve_socket.py``.

ADR 0015 retires the container, and both of those modules go with it — so no
module declares a timeout override any more, and there is no build budget left to
be inverted. Those guards are deleted rather than re-pointed: a guard kept alive
by finding it a new subject asserts something nobody decided. What is left is the
pair of budgets that still exist, and the relationship between them that still
has to hold.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: The ceiling the global per-test cap may not exceed. A slow test needs a
#: per-module override, not a looser default for every test in the suite.
_GLOBAL_CAP_CEILING = 120


def _global_pytest_timeout() -> int:
    """pytest-timeout's default per-test cap."""
    cfg = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    timeout = cfg["tool"]["pytest"]["ini_options"]["timeout"]
    return int(timeout)


def _ci_job_budget_seconds() -> int:
    """The CI job's wall-clock budget, in seconds."""
    text = _CI.read_text(encoding="utf-8")
    budgets = [int(m) * 60 for m in re.findall(r"timeout-minutes:\s*(\d+)", text)]
    assert budgets, ".github/workflows/ci.yml must declare timeout-minutes (CAL-1110)."
    # The smallest, not the first: every job in the file runs the same suite
    # under the same per-test cap, so the binding constraint is the tightest
    # job budget, and reading whichever happens to be written first would let a
    # new, shorter job slip under this guard.
    return min(budgets)


def test_ci_job_budget_exceeds_the_longest_test_timeout() -> None:
    """The job's wall clock must exceed the longest single test it runs.

    Otherwise the "secondary backstop" (pyproject's words) fires *first* and the
    per-test timeout becomes decoration — the job dies before the test it was
    meant to bound ever times out.
    """
    job = _ci_job_budget_seconds()
    longest = _global_pytest_timeout()
    assert job > longest, (
        f"the CI job budget ({job}s) does not exceed the longest per-test timeout "
        f"({longest}s), so a single slow test consumes the whole job and the "
        f"job-level limit stops being a backstop. Raise timeout-minutes in "
        f".github/workflows/ci.yml (CAL-1110)."
    )


def test_global_cap_still_bounds_ordinary_tests() -> None:
    """The cap must not drift upward into a blanket licence to hang.

    The global cap exists to stop a hung test consuming the job budget
    (pyproject's comment). Raising it globally to accommodate one slow test would
    blunt that for the whole suite, which is why a genuinely slow module takes a
    per-module ``pytest.mark.timeout`` instead.
    """
    assert _global_pytest_timeout() <= _GLOBAL_CAP_CEILING, (
        f"the global pytest-timeout cap grew beyond {_GLOBAL_CAP_CEILING}s. A slow "
        "test needs a per-module pytest.mark.timeout, not a looser default for "
        "every test in the suite (CAL-1110)."
    )


def test_both_budgets_are_actually_read() -> None:
    """The floor: both numbers were parsed out of real declarations.

    Each test above is a comparison, and a comparison between two values that a
    silently-failing parser defaulted to zero is satisfiable without either file
    saying anything. Reading them is asserted separately from relating them.
    """
    assert _global_pytest_timeout() > 0, (
        "no per-test cap was parsed out of pyproject.toml, so the comparisons "
        "above are relating a default to a default"
    )
    assert _ci_job_budget_seconds() > 0, (
        "no job budget was parsed out of ci.yml, so the comparison above is "
        "relating a default to a default"
    )
