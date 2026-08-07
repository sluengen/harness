"""#358 AC-4 — splitting the gate does not move the coverage total.

``scripts/verify.sh`` used to make one coverage claim from one pytest run. It now
makes it from two: ``-m docker`` serially writes ``.coverage``, then
``-m "not docker"`` runs across N xdist workers with ``--cov-append`` and
``--cov-fail-under=90`` evaluated on the union.

Every part of that is a place a total can silently go **down**: a worker whose
arcs never reach the controller, an append that overwrites instead of unions, a
combine that drops a file. A lower total behind a floor that still reads
``--cov-fail-under=90`` is the failure this module exists to catch, because it
lowers the bar the gate exists to hold while looking exactly like a pass.

``test_verify_coverage_gate.py`` pins that the *flags* are wired correctly. This
pins the thing the flags are for: that the arrangement **measures the same
population**. The wiring can be right and the number still wrong.

Method: build a throwaway package with a known mix of covered and uncovered
lines, then measure it twice — once the old way, once the gate's way — and require
the totals to be equal. Real subprocesses running real ``pytest-cov`` and real
``pytest-xdist``, because an in-process reimplementation of the combine would be
this test agreeing with itself about the one mechanism under test.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

#: The marker standing in for ``docker`` — the capability the real gate serializes.
#: Named differently on purpose: this measures the *combine*, and borrowing the
#: real marker would drag the docker skipif and a daemon requirement in with it.
SERIAL_MARKER = "tagged"

#: Workers for the parallel leg. Two is enough to prove the combine unions across
#: processes; more only lengthens the test.
WORKERS = 2

_PACKAGE = {
    "__init__.py": "",
    # A module where some branches run and some do not, so the total is neither
    # 0% nor 100% — see the non-vacuity floor below.
    "covered.py": (
        "def always(value):\n"
        "    return value * 2\n"
        "\n"
        "\n"
        "def branchy(value):\n"
        "    if value > 0:\n"
        "        return 'positive'\n"
        "    if value < 0:\n"
        "        return 'negative'\n"
        "    return 'zero'\n"
    ),
    "partly.py": (
        "def reached(value):\n"
        "    return value + 1\n"
        "\n"
        "\n"
        "def never_called(value):\n"
        "    total = 0\n"
        "    for item in range(value):\n"
        "        total += item\n"
        "    return total\n"
    ),
    # Reached *only* by the serialized leg, which is what makes the union claim
    # non-trivial: if the serial stage's arcs were discarded, this module's lines
    # would go missing from the combined total and the equality would fail.
    "serial_only.py": (
        "def tagged_path(value):\n"
        "    doubled = value * 2\n"
        "    return doubled + 1\n"
    ),
}

#: Every synthetic test opens with this: it records the pid it ran under, which is
#: how :func:`test_the_parallel_leg_really_ran_in_more_than_one_process` proves the
#: parallel leg genuinely distributed. Recording the pid beats scraping xdist's
#: banner — under ``-q`` the ``gw0``/``gw1`` listing is suppressed entirely, so a
#: banner check fails against a run that *is* parallel, and would equally pass
#: against a future xdist that printed the banner without distributing.
_RECORD_PID = (
    "import os\n"
    "\n"
    "\n"
    "def _record_pid():\n"
    "    directory = os.environ.get('PID_DIR')\n"
    "    if directory:\n"
    "        open(os.path.join(directory, str(os.getpid())), 'a').close()\n"
)

#: Several non-marked tests rather than one, so both workers reliably receive
#: work under xdist's dynamic ``--dist load`` scheduling.
_TESTS = {
    "test_a.py": (
        _RECORD_PID + "\n"
        "from pkg.covered import always, branchy\n"
        "\n"
        "\n"
        "def test_always():\n"
        "    _record_pid()\n"
        "    assert always(2) == 4\n"
        "\n"
        "\n"
        "def test_positive():\n"
        "    _record_pid()\n"
        "    assert branchy(1) == 'positive'\n"
    ),
    "test_b.py": (
        _RECORD_PID + "\n"
        "from pkg.covered import branchy\n"
        "\n"
        "\n"
        "def test_negative():\n"
        "    _record_pid()\n"
        "    assert branchy(-1) == 'negative'\n"
        "\n"
        "\n"
        "def test_negative_again():\n"
        "    _record_pid()\n"
        "    assert branchy(-5) == 'negative'\n"
    ),
    "test_c.py": (
        _RECORD_PID + "\n"
        "from pkg.partly import reached\n"
        "\n"
        "\n"
        "def test_reached():\n"
        "    _record_pid()\n"
        "    assert reached(1) == 2\n"
        "\n"
        "\n"
        "def test_reached_again():\n"
        "    _record_pid()\n"
        "    assert reached(4) == 5\n"
    ),
    "test_tagged.py": (
        _RECORD_PID + "\n"
        "import pytest\n"
        "\n"
        "from pkg.serial_only import tagged_path\n"
        "\n"
        f"pytestmark = [pytest.mark.{SERIAL_MARKER}]\n"
        "\n"
        "\n"
        "def test_tagged_path():\n"
        "    _record_pid()\n"
        "    assert tagged_path(2) == 5\n"
    ),
}


def _build_project(root: Path) -> None:
    """Write the synthetic package, its tests and an ini registering the marker."""
    package = root / "pkg"
    package.mkdir()
    for name, source in _PACKAGE.items():
        (package / name).write_text(source, encoding="utf-8")
    tests = root / "tests"
    tests.mkdir()
    for name, source in _TESTS.items():
        (tests / name).write_text(source, encoding="utf-8")
    (root / "pytest.ini").write_text(
        "[pytest]\n"
        "addopts = --strict-markers\n"
        f"markers =\n    {SERIAL_MARKER}: the serialized capability\n",
        encoding="utf-8",
    )


def _run(
    root: Path, *args: str, pid_dir: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Run pytest in *root* with the repo's plugins disabled.

    ``-p no:cacheprovider`` and a cleared ``PYTEST_ADDOPTS`` keep the nested run
    from inheriting this suite's configuration; ``PYTHONPATH`` is *root* so the
    synthetic ``pkg`` imports without an install step. *pid_dir*, when given, is
    where each synthetic test records the process it ran under.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    env.pop("PYTEST_ADDOPTS", None)
    if pid_dir is not None:
        env["PID_DIR"] = str(pid_dir)
    else:
        env.pop("PID_DIR", None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


def _as_totals(value: object) -> dict[str, float]:
    """Narrow a fixture entry back to the totals mapping (mypy strict)."""
    assert isinstance(value, dict)
    return value


def _totals(report: Path) -> dict[str, float]:
    """``covered_lines``/``missing_lines``/``percent_covered`` from a JSON report."""
    data = json.loads(report.read_text(encoding="utf-8"))
    return data["totals"]


@pytest.fixture
def measured(tmp_path: Path) -> dict[str, object]:
    """Measure the synthetic package the old way and the gate's way.

    Returns both totals plus the set of processes the parallel leg's tests ran
    under, so the assertions below can check the numbers *and* that the leg
    genuinely distributed.
    """
    serial_root = tmp_path / "serial"
    split_root = tmp_path / "split"
    pid_dir = tmp_path / "pids"
    for directory in (serial_root, split_root, pid_dir):
        directory.mkdir()
    _build_project(serial_root)
    _build_project(split_root)

    # (A) The old shape: one invocation over everything.
    one = _run(
        serial_root,
        "--cov=pkg",
        "--cov-report=json:serial.json",
        "-q",
    )
    assert one.returncode == 0, f"serial leg failed:\n{one.stdout}\n{one.stderr}"

    # (B) The gate's shape: the marked leg resets the data file, then the parallel
    #     leg appends and the report is written from the union.
    first = _run(
        split_root,
        "-m",
        SERIAL_MARKER,
        "--cov=pkg",
        "-q",
    )
    assert first.returncode == 0, f"split leg 1 failed:\n{first.stdout}\n{first.stderr}"
    second = _run(
        split_root,
        "-m",
        f"not {SERIAL_MARKER}",
        "-n",
        str(WORKERS),
        "--cov=pkg",
        "--cov-append",
        "--cov-report=json:split.json",
        "-q",
        pid_dir=pid_dir,
    )
    assert second.returncode == 0, (
        f"split leg 2 failed:\n{second.stdout}\n{second.stderr}"
    )

    return {
        "serial": _totals(serial_root / "serial.json"),
        "split": _totals(split_root / "split.json"),
        "parallel_pids": {path.name for path in pid_dir.iterdir()},
    }


def test_the_split_gate_measures_the_same_population(
    measured: dict[str, object],
) -> None:
    """AC-4: the combined total equals the serial total, line for line.

    Equality on ``covered_lines`` is the load-bearing assertion — a percentage
    can coincide while the underlying counts differ.
    """
    serial = _as_totals(measured["serial"])
    split = _as_totals(measured["split"])
    assert split["covered_lines"] == serial["covered_lines"], (
        f"splitting the gate changed the covered-line count: serial "
        f"{serial['covered_lines']} vs split {split['covered_lines']}. The floor "
        f"would be enforced on a different population than before (#358 AC-4)."
    )
    assert split["percent_covered"] == serial["percent_covered"], (
        f"splitting the gate changed the coverage percentage: serial "
        f"{serial['percent_covered']} vs split {split['percent_covered']} "
        f"(#358 AC-4)."
    )
    assert split["missing_lines"] == serial["missing_lines"], (
        f"splitting the gate changed the missing-line count: serial "
        f"{serial['missing_lines']} vs split {split['missing_lines']} (#358 AC-4)."
    )


def test_the_measurement_is_not_trivially_equal(
    measured: dict[str, object],
) -> None:
    """Non-vacuity floor: the fixture measures a package that is partly covered.

    A package with **no** covered lines, or with **nothing** missing, makes the
    equality above true for reasons that have nothing to do with the combine —
    the shape where a guard reads green while measuring nothing (#168). Both
    counts must be non-zero for the comparison to carry information.
    """
    serial = _as_totals(measured["serial"])
    assert serial["covered_lines"] > 0, (
        "the synthetic package must have covered lines, or equality is trivial"
    )
    assert serial["missing_lines"] > 0, (
        "the synthetic package must have missing lines, or equality is trivial — "
        "a fully covered package compares equal however badly the combine works"
    )


def test_the_serial_legs_arcs_survive_into_the_union(
    measured: dict[str, object],
) -> None:
    """The union really is a union, not just the parallel leg's own total.

    ``pkg/serial_only.py`` is reached *only* by the marked leg. If ``--cov-append``
    overwrote rather than unioned — the "subtly wrong combine" AC-4 names — those
    lines would be missing from the split total, which is what makes this the
    sharpest single check here. Asserted as a count so it cannot be satisfied by
    the file merely appearing in the report with zero arcs.
    """
    serial_only_lines = sum(
        1
        for line in _PACKAGE["serial_only.py"].splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
    assert serial_only_lines >= 3
    split = _as_totals(measured["split"])
    assert split["covered_lines"] >= serial_only_lines, (
        f"the combined total ({split['covered_lines']}) is smaller than the "
        f"serial-only module alone ({serial_only_lines}), so the marked leg's "
        f"arcs did not survive --cov-append (#358 AC-4)."
    )


def test_the_parallel_leg_really_ran_in_more_than_one_process(
    measured: dict[str, object],
) -> None:
    """Guards the whole module against a silently-absent xdist.

    If ``-n`` were ignored, every assertion above would still pass — they would
    just be comparing two serial runs, proving nothing about combining arcs
    *across processes*, which is the mechanism the gate now depends on.

    Measured from the pids the tests themselves recorded rather than from xdist's
    banner. The banner is not usable evidence here: under ``-q`` the ``gw0``/``gw1``
    listing is suppressed, so scraping it fails against a run that really is
    parallel — and it would equally pass against a future xdist that printed the
    banner while distributing to one worker. The pid set answers the question
    directly.
    """
    pids = measured["parallel_pids"]
    assert isinstance(pids, set)
    assert len(pids) >= 2, (
        f"the parallel leg's tests ran in {len(pids)} process(es) ({sorted(pids)}); "
        f"with -n {WORKERS} they must span at least two, or the equivalence above "
        f"compared two serial runs and proves nothing about combining arcs across "
        f"processes (#358 AC-4)."
    )
