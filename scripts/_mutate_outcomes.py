"""Records each test's outcome by its exact pytest node id, for `mutate.py` (#360).

Loaded into the *child* interpreter with ``-p _mutate_outcomes``, and writes one
JSON file at the path named by ``MUTATE_OUTCOME_PATH``.

Why a plugin rather than parsing output. ``mutate.py``'s whole rule is set
equality on node ids, so a node id that was *reconstructed* rather than
*observed* would put the reconstruction inside the predicate. ``--junitxml``
offers ``classname`` + ``name``, from which a node id has to be rebuilt — lossy
for tests in classes and for parametrized ids — and rebuilding-instead-of-reading
is exactly the step that lied in #207. ``report.nodeid`` is pytest's own answer.
Parsing ``N passed`` *is* #207.

Deliberately imports nothing from :mod:`mutate`: only ``scripts/`` is on the
child's ``PYTHONPATH``, and a shared import would work in this repo while
failing under any other invocation. :mod:`tests.unit.test_mutate_end_to_end`
pins that in both directions.

Collection failures are recorded under the collector's own node id (a module
path, not a test), which is what makes a collection-breaking mutation read as
``mispredicted``: its observed set can never equal a prediction naming tests.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_PASSED: set[str] = set()
_FAILED: set[str] = set()
_ERRORED: set[str] = set()
_COLLECTED = 0


def pytest_runtest_logreport(report: Any) -> None:
    """Call-phase outcomes are the verdict; setup/teardown failures are errors."""
    if report.when == "call":
        if report.passed:
            _PASSED.add(report.nodeid)
        elif report.failed:
            _FAILED.add(report.nodeid)
    elif report.failed:
        _ERRORED.add(report.nodeid)


def pytest_collectreport(report: Any) -> None:
    """A module that cannot be imported errors under its own node id."""
    if report.failed and report.nodeid:
        _ERRORED.add(report.nodeid)


def pytest_collection_finish(session: Any) -> None:
    """The count *after* ``-m`` deselection — the number the selection runs."""
    global _COLLECTED
    _COLLECTED = len(session.items)


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    destination = os.environ.get("MUTATE_OUTCOME_PATH")
    if not destination:
        return
    Path(destination).write_text(
        json.dumps(
            {
                "passed": sorted(_PASSED),
                "failed": sorted(_FAILED),
                "errored": sorted(_ERRORED),
                "collected": _COLLECTED,
                "exitstatus": int(exitstatus),
            }
        ),
        encoding="utf-8",
    )
