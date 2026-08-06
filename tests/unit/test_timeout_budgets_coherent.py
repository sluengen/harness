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

**#357 — the same defect, in a second module, and a different fix.**
``tests/integration/test_serve_socket.py`` arrived later (#307) with the identical
shape: a module-scoped fixture running ``docker build`` under a cap that covers
setup. Cold, all six of its tests ERROR at setup; warm, they pass — so the gate
reds on a file the diff never touched, and the weekly Docker prune on this host
plus every fresh CI runner guarantee the cold case recurs.

It is not fixed the CAL-1110 way. That fix raised the whole module cap to 600s,
which ``test_docker.py`` can afford because its tests *are* the build. The socket
module's build is incidental to six ~25s tests, so a blanket 600s cap would let a
genuinely hung socket test burn ten minutes before the gate noticed. Instead the
cap stays 120 and only the **phase it is measured over** changes: the module
declares ``pytest.mark.timeout(func_only=True)``, which moves pytest-timeout's
timer from ``pytest_runtest_protocol`` (setup + call + teardown) to
``pytest_runtest_call`` (the body alone), and the build carries its own
``subprocess.run(timeout=600)``.

So the nesting above gains a fourth attribute — *which phase* a per-test cap is
measured over — and the guards below cover both modules. The accepted cost is
that fixture setup and teardown in that one module are no longer bounded by
pytest; the build's own budget and the CI job's wall clock bound them instead,
which is what ``test_ci_job_budget_exceeds_the_longest_test_timeout`` now folds
``build + cap`` into.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_DOCKER_TEST = _REPO_ROOT / "tests" / "integration" / "test_docker.py"
_SERVE_SOCKET_TEST = _REPO_ROOT / "tests" / "integration" / "test_serve_socket.py"
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _global_pytest_timeout() -> int:
    """pytest-timeout's default per-test cap."""
    cfg = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    timeout = cfg["tool"]["pytest"]["ini_options"]["timeout"]
    return int(timeout)


# --- reading a module's declared budgets ------------------------------------
#
# These helpers parse the target file with ``ast`` rather than searching its
# text, and they never import it: importing either integration module evaluates
# its ``pytestmark``, which shells out to ``docker info`` — a unit test would
# then need a daemon to run.
#
# The AST is what makes the scoping honest. Both modules declare a cheap
# ``subprocess.run(..., timeout=15)`` ``docker info`` probe *above* the build
# fixture, and a file-wide text search finds *that* one first — the mis-parse an
# earlier draft of this guard shipped, which made it compare the wrong pair of
# numbers and pass while the defect it exists to catch was still present. Walking
# only the named fixture's own node cannot reach the probe at all, so the hazard
# is removed rather than worked around. For the same reason the marker below is
# read from the ``pytestmark`` assignment rather than matched anywhere in the
# file, so a mention in a comment or a docstring can never be mistaken for a
# declaration.


def _timeout_marker(path: Path) -> ast.Call | None:
    """The module's ``pytest.mark.timeout`` marker node, or None if it has none."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "pytestmark"
            for target in node.targets
        ):
            continue
        elements = node.value.elts if isinstance(node.value, ast.List) else [node.value]
        for element in elements:
            if (
                isinstance(element, ast.Call)
                and ast.unparse(element.func) == "pytest.mark.timeout"
            ):
                return element
    return None


def _module_timeout(path: Path) -> int:
    """The per-test cap that applies to a module's tests.

    A ``pytest.mark.timeout(N)`` override when the module states one, else the
    global cap — which is also what a marker carrying only keyword arguments
    resolves to, since pytest-timeout falls back to the ini value when the
    marker names no number of its own.
    """
    call = _timeout_marker(path)
    if call is None or not call.args:
        return _global_pytest_timeout()
    return int(ast.literal_eval(call.args[0]))


def _module_defers_timeout_to_the_test_body(path: Path) -> bool:
    """Whether the module's marker sets ``func_only=True``.

    That is the flag deciding *which phase* the cap is measured over:
    pytest-timeout installs its timer in ``pytest_runtest_protocol`` (setup +
    call + teardown) when it is false, and in ``pytest_runtest_call`` (the test
    body alone) when it is true.
    """
    call = _timeout_marker(path)
    if call is None:
        return False
    return any(
        keyword.arg == "func_only" and ast.literal_eval(keyword.value) is True
        for keyword in call.keywords
    )


def _fixture_subprocess_timeout(path: Path, fixture: str) -> int:
    """The ``subprocess.run(timeout=…)`` budget declared inside one named fixture."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != fixture:
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            if ast.unparse(call.func) != "subprocess.run":
                continue
            for keyword in call.keywords:
                if keyword.arg == "timeout":
                    return int(ast.literal_eval(keyword.value))
        raise AssertionError(
            f"expected the {fixture} fixture in {path.name} to declare a timeout on "
            f"its docker-build subprocess — if it no longer does, this guard needs "
            f"rethinking, not deleting (CAL-1110). With the pytest cap deferred to "
            f"the test body, that subprocess budget is the only thing bounding the "
            f"build short of the CI job's own wall clock."
        )
    raise AssertionError(f"no fixture named {fixture!r} in {path.name}")


def _build_subprocess_timeout() -> int:
    """The ``docker build`` subprocess budget inside the ``built_image`` fixture."""
    return _fixture_subprocess_timeout(_DOCKER_TEST, "built_image")


def _docker_module_timeout() -> int:
    """The docker module's per-test cap."""
    return _module_timeout(_DOCKER_TEST)


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
    # The serve-socket module defers its cap to the test body, so the worst case
    # for a single item there is not the cap alone: an uncached build runs first,
    # bounded by its own subprocess budget, and only then does the body's cap
    # start. Fold the sum in, so a later rise in the build budget cannot quietly
    # outgrow the job that is supposed to contain it.
    serve_socket_worst_case = _fixture_subprocess_timeout(
        _SERVE_SOCKET_TEST, "image"
    ) + _module_timeout(_SERVE_SOCKET_TEST)
    longest = max(
        _global_pytest_timeout(), _docker_module_timeout(), serve_socket_worst_case
    )
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


# ---------------------------------------------------------------------------
# #357 — the same inversion, in the serve-socket module.
#
# `tests/integration/test_serve_socket.py` arrived after CAL-1110 (#307) and
# reproduced its defect exactly: a module-scoped fixture that runs `docker build`
# under the global 120s cap, which covers fixture setup. Cold, the build alone
# exceeds the cap, so all six tests ERROR at setup and the gate reds on a file
# the diff never touched.
#
# The fix is deliberately *not* the CAL-1110 one. That module raised its whole
# per-test cap to 600s, which it can afford because its tests **are** the build.
# Here the build is incidental to six ~25s socket tests, and a blanket 600s cap
# would let a genuinely hung socket test burn ten minutes before the gate noticed.
# So the cap stays at 120 and only the *phase* it is measured over changes.
# ---------------------------------------------------------------------------


def test_the_serve_socket_build_budget_is_distinct_from_and_above_its_per_test_cap() -> (
    None
):
    """#357 AC-2 — the two budgets are two numbers, and the build's is the larger.

    Both halves are load-bearing. Without the second, the first is satisfiable by
    a pair of numbers that never both apply: a 600s build budget under a 120s cap
    that still covers setup is not a long build, it is CAL-1110's dead letter
    again, wearing a bigger number.
    """
    per_test = _module_timeout(_SERVE_SOCKET_TEST)
    build = _fixture_subprocess_timeout(_SERVE_SOCKET_TEST, "image")

    assert build > per_test, (
        f"the serve-socket image build is allowed {build}s but the module's "
        f"per-test cap is {per_test}s. A cold build measured 165s (CAL-1110), so "
        f"a build budget at or below the cap is one the cold path cannot fit in."
    )
    assert _module_defers_timeout_to_the_test_body(_SERVE_SOCKET_TEST), (
        f"the build is allowed {build}s, but the module's {per_test}s cap still "
        f"covers fixture setup, so {build}s can never be reached — pytest-timeout "
        f"kills the item at {per_test}s first. This is CAL-1110's inversion "
        f"returning by a different route (#357)."
    )


def test_the_declared_timeout_policy_exempts_setup_but_not_the_test_body(
    tmp_path: Path,
) -> None:
    """#357 AC-1 + AC-3 — measured, on the marker the module actually declares.

    The claim is about pytest-timeout's *behaviour*, and the assertion above only
    reads a flag's name. So this replays the module's own marker — unparsed from
    its `pytestmark`, not retyped here — against a generated module at 1/120
    scale: a fixture that sleeps past the cap must survive, and a test body that
    sleeps past it must still be killed.

    Scaling is what makes it affordable. Proving AC-1 at full size needs a cold
    16-minute build; a 1s cap and 3s sleeps prove the identical phase semantics
    in about five seconds, and would catch a pytest-timeout upgrade that changed
    what `func_only` means — which no amount of reading the marker can.
    """
    marker = _timeout_marker(_SERVE_SOCKET_TEST)
    assert marker is not None, (
        "the serve-socket module declares no pytest.mark.timeout marker, so its "
        "build runs under the global cap that covers fixture setup (#357)."
    )
    assert not marker.args, (
        f"the serve-socket module restates a per-test number "
        f"({ast.unparse(marker)}). It must inherit the global cap and change only "
        f"the phase it is measured over — the scaled replay below drives the cap "
        f"from the command line, so it cannot speak for a hardcoded one, and "
        f"AC-3 wants the ordinary cap on these test bodies anyway."
    )

    (tmp_path / "test_generated.py").write_text(
        "import time\n"
        "import pytest\n"
        f"pytestmark = [{ast.unparse(marker)}]\n"
        "\n"
        "@pytest.fixture(scope='module')\n"
        "def slow_setup():\n"
        "    time.sleep(3)\n"
        "    return 'built'\n"
        "\n"
        "def test_a_setup_is_exempt(slow_setup):\n"
        "    assert slow_setup == 'built'\n"
        "\n"
        "def test_b_body_is_still_bounded(slow_setup):\n"
        "    time.sleep(3)\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "test_generated.py",
            "-p",
            "no:cacheprovider",
            "--timeout=1",
            "-q",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        # tmp_path sits outside the repo so no ini is discovered and --timeout=1
        # governs; clearing PYTEST_ADDOPTS stops the parent run's own flags
        # (coverage, --strict-markers) leaking into the child.
        env={**os.environ, "PYTEST_ADDOPTS": ""},
    )
    report = f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"

    assert "1 passed" in result.stdout, (
        "a 3s module-scoped fixture was killed under a 1s cap, so the cap still "
        "covers fixture setup and a cold docker build cannot fit under it — AC-1 "
        f"(#357).\n{report}"
    )
    assert "1 failed" in result.stdout and "Timeout (>1.0s)" in result.stdout, (
        "a test body that slept 3s under a 1s cap was NOT killed, so the marker "
        "exempts more than the build and a genuinely hung socket test would no "
        f"longer fail fast — AC-3 (#357).\n{report}"
    )
