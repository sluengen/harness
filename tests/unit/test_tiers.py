"""The test-suite tier boundary — its classifier, its markers, its denial (#336).

CODE-4 in ``assessments/2026-08-04-code.md`` found that the tier labels do not
describe what the suite proves: one module was marked ``integration`` while
~85 modules under ``tests/unit/`` spawn processes, open the SQLite ledger or
drive whole verbs through ``CliRunner``. ``pytest tests/unit`` *was* the broad
gate, so a contributor had no fast isolated signal to select and the word
"integration" understated the tree by two orders of magnitude.

:mod:`tests._tiers` answers that by **deriving** each module's tier from the
dependency boundary its module-level imports cross, rather than by hand-marking
250 modules with a line that rots. This module is the guard over that helper.

Two halves, and neither is asked to do the other's job:

* **Structural** — :func:`tests._tiers.classify` reads the module's AST and
  answers before any test runs, which is what makes ``-m`` *selection* possible
  at all. It can be fooled by a boundary a test reaches through production code
  rather than through its own imports.
* **Runtime** — :func:`tests._tiers.deny_boundaries` patches the process and
  database chokepoints for a ``unit``-tier test, so a structural miss fails
  loudly instead of quietly making the fast tier not fast.

This module must itself classify ``unit`` — it takes no module-level
``subprocess`` / ``CliRunner`` / ``harness.state`` import and never touches
``__file__`` — which is what lets it prove the runtime denial on itself.

The whole-suite invariants below (:func:`test_every_tracked_test_module_classifies`
and its siblings) read the tracked tree through :mod:`tests._gitutil`, so they
are ``guard``-tier by the classifier they verify. That is correct rather than
awkward: a guard over the tree lives in the tier it defines.
"""

from __future__ import annotations

from pathlib import Path

from tests._tiers import classify


def _write(tmp_path: Path, body: str, name: str = "test_sample.py") -> Path:
    module = tmp_path / name
    module.write_text(body, encoding="utf-8")
    return module


def test_a_clirunner_module_is_integration(tmp_path: Path) -> None:
    """The headline case: driving a whole verb is a boundary crossing."""
    module = _write(tmp_path, "from typer.testing import CliRunner\n")
    assert classify(module) == "integration"
