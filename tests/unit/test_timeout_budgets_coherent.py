"""CAL-1110 — nested timeout budgets must be coherent.

A timeout only means something if the budget enclosing it is larger. Three
nest here, outermost first:

1. the CI job's ``timeout-minutes`` (``.github/workflows/ci.yml``),
2. pytest-timeout's per-test cap (``pyproject.toml`` ``timeout``, plus any
   per-module ``pytest.mark.timeout`` override),
3. a subprocess budget inside a test or fixture (``subprocess.run(timeout=…)``).

**This inverted and nobody saw it for weeks.** ``tests/integration/test_docker.py``
builds the image with ``subprocess.run(..., timeout=600)`` — a deliberate 10
minute budget for a cold, uncached build that source-builds git (CAL-935 /
CAL-1008). But the global pytest-timeout cap is 120s and applies to the whole
test *including fixture setup*, so the fixture's 600s could never be reached:
pytest killed it at 120s first. The declared intent was dead on arrival.

It stayed invisible because the failure needs a **cold cache**. A developer's
Docker layer cache makes the build near-instant, and CI — the one place with no
cache — only runs on ``main`` pushes and PRs targeting ``main``, i.e. once per
release. It surfaced on release PR #161, the first CI run in 670 commits, as
four ``Timeout (>120.0s)`` errors.

Measured 2026-07-16: a cold ``docker build --no-cache`` takes **165s** on the
author's machine — already past the 120s cap, with a CI runner slower still. The
fixture's existing 600s is kept as the bound (it is a declared intent, not a
number invented to make a test pass) and the enclosing budgets are made to
respect it.

These tests pin the *ordering*, not the specific numbers, so any of the three can
be retuned as long as the nesting still holds.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_DOCKER_TEST = _REPO_ROOT / "tests" / "integration" / "test_docker.py"
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _global_pytest_timeout() -> int:
    """pytest-timeout's default per-test cap."""
    cfg = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    timeout = cfg["tool"]["pytest"]["ini_options"]["timeout"]
    return int(timeout)


def _docker_module_timeout() -> int:
    """The docker module's per-test cap — its ``pytest.mark.timeout`` override,
    falling back to the global cap when it declares none."""
    m = re.search(r"pytest\.mark\.timeout\(\s*(\d+)\s*\)", _DOCKER_TEST.read_text())
    return int(m.group(1)) if m else _global_pytest_timeout()


def _build_subprocess_timeout() -> int:
    """The ``docker build`` subprocess budget inside the ``built_image`` fixture.

    Scoped to that fixture deliberately. The module has a second, unrelated
    ``subprocess.run(..., timeout=15)`` — the cheap ``docker info`` availability
    probe — and a file-wide search finds *it* first, which made an earlier draft
    of this guard compare the wrong pair of numbers and pass while the defect it
    exists to catch was still present.
    """
    text = _DOCKER_TEST.read_text()
    start = text.index("def built_image")
    body = text[start:]
    # End at the next top-level def, so we read only this fixture.
    end = re.search(r"\n(?:@|def )", body)
    if end:
        body = body[: end.start()]
    m = re.search(r"timeout=(\d+)", body)
    assert m, (
        "expected the built_image fixture's docker-build subprocess to declare a "
        "timeout — if it no longer does, this guard needs rethinking, not "
        "deleting (CAL-1110)."
    )
    return int(m.group(1))


def _ci_job_budget_seconds() -> int:
    """The CI job's wall-clock budget, in seconds."""
    m = re.search(r"timeout-minutes:\s*(\d+)", _CI.read_text())
    assert m, ".github/workflows/ci.yml must declare timeout-minutes (CAL-1110)."
    return int(m.group(1)) * 60


def test_docker_module_timeout_covers_its_build_subprocess() -> None:
    """The docker tests' per-test cap must not strangle their own build budget.

    This is the defect CAL-1110 fixes: a 600s build under a 120s cap is not a
    long build, it is a guaranteed failure the moment the cache is cold.
    """
    module_cap = _docker_module_timeout()
    build_budget = _build_subprocess_timeout()
    assert module_cap >= build_budget, (
        f"tests/integration/test_docker.py allows its docker build {build_budget}s "
        f"but pytest-timeout kills the test at {module_cap}s, so the build budget "
        f"can never be reached. Raise the module's pytest.mark.timeout to at least "
        f"{build_budget}s, or lower the build's own timeout — but do not leave them "
        f"contradicting each other (CAL-1110)."
    )


def test_ci_job_budget_exceeds_the_longest_test_timeout() -> None:
    """The job's wall clock must exceed the longest single test it runs.

    Otherwise the "secondary backstop" (pyproject's words) fires *first* and the
    per-test timeout becomes decoration — the job dies before the test it was
    meant to bound ever times out.
    """
    job = _ci_job_budget_seconds()
    longest = max(_global_pytest_timeout(), _docker_module_timeout())
    assert job > longest, (
        f"the CI job budget ({job}s) does not exceed the longest per-test timeout "
        f"({longest}s), so a single slow test consumes the whole job and the "
        f"job-level limit stops being a backstop. Raise timeout-minutes in "
        f".github/workflows/ci.yml (CAL-1110)."
    )


def test_global_cap_still_bounds_ordinary_tests() -> None:
    """The docker override must not become a blanket licence to hang.

    The global cap exists to stop a hung test consuming the job budget
    (pyproject's comment). Raising it globally to accommodate one slow build
    would blunt that for all ~1500 tests, which is why the fix is a per-module
    override rather than a new global default.
    """
    assert _global_pytest_timeout() <= 120, (
        "the global pytest-timeout cap grew beyond 120s. A slow integration "
        "build needs a per-module pytest.mark.timeout, not a looser default for "
        "every test in the suite (CAL-1110)."
    )
