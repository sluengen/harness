"""The tier classifier, its runtime denial, and the selection they buy (#336).

CODE-4 in ``assessments/2026-08-04-code.md`` found that the tier labels did not
describe what the suite proves: one module carried ``integration`` while ~89
modules under ``tests/unit/`` spawn processes, open the SQLite ledger or drive
whole verbs through ``CliRunner``. :mod:`tests._tiers` answers that by
**deriving** each module's tier from the dependency boundary its module-level
imports cross; this module is the guard over that helper.

**This module is deliberately ``unit``-tier.** It takes no module-level
``subprocess`` / ``sqlite3`` / ``CliRunner`` / ``harness.state`` import and
never touches ``__file__``, so the classifier it tests puts it in ``unit`` and
``tests/conftest.py`` installs :func:`tests._tiers.deny_boundaries` around every
test below. That is what makes :func:`test_a_unit_test_may_not_spawn_a_process`
a demonstration rather than an assertion about a function: the denial under test
is the one production installs, and it is installed *on this test*.

The whole-suite invariants — every tracked module classifies, every override
names live code, every helper is entered — read the committed tree and are
therefore ``guard``-tier by this module's own classifier. They live next door in
``test_tiers_corpus.py``. Splitting them is a departure from the design's single
module, and the reason is that one module cannot hold both halves honestly: a
module that imports the tracked-set reader is no longer ``unit``, so the denial
fixture would not be installed on it and the self-demonstration above would
silently become a hand-rolled call to :func:`~tests._tiers.deny_boundaries` —
proving the function while leaving the *wiring* untested.

Every classifier case below runs against a **synthetic source** written under
``tmp_path``, never against a real module of the suite. A guard whose oracle is
the corpus it guards agrees with itself by construction; writing the source
means the expected tier is stated independently of what the tree happens to
contain today.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._tiers import (
    HELPER_BOUNDARIES,
    OVERRIDES,
    TIERS,
    TierViolationError,
    apply_tier_markers,
    boundaries,
    classify,
    tier_for,
)


def _write(tmp_path: Path, body: str, name: str = "test_sample.py") -> Path:
    module = tmp_path / name
    module.write_text(body, encoding="utf-8")
    return module


# ---------------------------------------------------------------------------
# The classifier, on synthetic sources
# ---------------------------------------------------------------------------


def test_a_clirunner_module_is_integration(tmp_path: Path) -> None:
    """The headline case: driving a whole verb is a boundary crossing."""
    module = _write(tmp_path, "from typer.testing import CliRunner\n")
    assert classify(module) == "integration"


@pytest.mark.parametrize(
    ("body", "flag"),
    [
        ("import subprocess\n", "proc"),
        ("from subprocess import run\n", "proc"),
        ("import sqlite3\n", "db"),
        ("import aiosqlite\n", "db"),
        ("from harness.state.store import StateStore\n", "db"),
        ("from typer.testing import CliRunner\n", "cli"),
    ],
)
def test_an_out_of_process_import_is_integration(
    tmp_path: Path, body: str, flag: str
) -> None:
    """Each out-of-process boundary is detected, and names itself in the flags."""
    module = _write(tmp_path, body)
    assert boundaries(module) == frozenset({flag})
    assert classify(module) == "integration"


def test_a_module_that_locates_itself_in_the_checkout_is_a_guard(
    tmp_path: Path,
) -> None:
    """``__file__`` is the repo-root anchor every tree-reading guard uses."""
    module = _write(tmp_path, "from pathlib import Path\nROOT = Path(__file__)\n")
    assert boundaries(module) == frozenset({"tree"})
    assert classify(module) == "guard"


def test_the_anchor_is_read_anywhere_not_only_at_module_level(
    tmp_path: Path,
) -> None:
    """A repo root computed inside a function still reads the tree.

    Restricting this to module level is the difference between 24 ``unit``
    modules and 56: ``tests/unit/test_layers.py`` spells its root
    ``Path(__file__).resolve().parents[2]`` inside the one function that needs
    it, and a module-level-only scan calls that hermetic. The measurement is in
    :mod:`tests._tiers`; this pins the behaviour it produced.
    """
    module = _write(
        tmp_path,
        "from pathlib import Path\n\n\ndef test_x():\n    Path(__file__).parents[2]\n",
    )
    assert classify(module) == "guard"


def test_a_module_with_no_boundary_is_unit(tmp_path: Path) -> None:
    """The residue: nothing imported, nothing anchored, nothing crossed."""
    module = _write(tmp_path, "def test_x() -> None:\n    assert 1 + 1 == 2\n")
    assert boundaries(module) == frozenset()
    assert classify(module) == "unit"


def test_out_of_process_beats_tree(tmp_path: Path) -> None:
    """A guard that also shells out is ``integration``, not ``guard``.

    Precedence, stated as the widest boundary wins. Without it a module
    carrying both flags could resolve either way depending on set iteration
    order, and the cheap answer (``guard``) is the wrong one.
    """
    module = _write(tmp_path, "import subprocess\nfrom pathlib import Path\nP=Path(__file__)\n")
    assert boundaries(module) == frozenset({"proc", "tree"})
    assert classify(module) == "integration"


def test_tier_for_is_ordered_by_width() -> None:
    """The precedence rule itself, independent of any source text."""
    assert tier_for([]) == "unit"
    assert tier_for(["tree"]) == "guard"
    assert tier_for(["tree", "proc"]) == "integration"
    assert tier_for(["proc", "tree"]) == "integration"


# ---------------------------------------------------------------------------
# Shared helpers, at symbol granularity
# ---------------------------------------------------------------------------


def test_the_gitutil_split_is_by_symbol_not_by_module(tmp_path: Path) -> None:
    """``init_repo`` builds a repository; the tracked-set readers only read one.

    ``tests/_gitutil.py`` genuinely spans two boundaries, so a module-granular
    answer would push all ~140 tree-reading guards into ``integration`` and
    leave the tier meaning nothing — the exact failure this ticket exists to
    end.
    """
    creates = _write(tmp_path, "from tests._gitutil import init_repo\n", "test_a.py")
    reads = _write(
        tmp_path, "from tests._gitutil import tracked_files_under\n", "test_b.py"
    )
    assert classify(creates) == "integration"
    assert classify(reads) == "guard"


def test_a_module_importing_both_gitutil_halves_takes_the_wider_answer(
    tmp_path: Path,
) -> None:
    module = _write(
        tmp_path, "from tests._gitutil import init_repo, tracked_files_under\n"
    )
    assert boundaries(module) == frozenset({"proc", "tree"})
    assert classify(module) == "integration"


def test_a_whole_module_helper_import_takes_the_union(tmp_path: Path) -> None:
    """``from tests import _gitutil`` gets the coarser answer, and that is recorded.

    Tracking which attributes the module then reaches for would be a second
    resolver to keep honest. The imprecision is pessimistic — it can only widen
    a tier, never narrow one — so it is pinned here rather than left to be
    discovered as a surprise.
    """
    module = _write(tmp_path, "from tests import _gitutil\n")
    assert boundaries(module) == frozenset({"proc", "tree"})
    assert classify(module) == "integration"


def test_importing_the_classifier_crosses_nothing(tmp_path: Path) -> None:
    """:mod:`tests._tiers` patches ``subprocess``; it never spawns.

    Load-bearing rather than trivia: if importing the classifier implied
    ``proc``, this module would be ``integration``, the denial fixture would not
    be installed on it, and the self-demonstration below would test nothing.
    """
    module = _write(tmp_path, "from tests._tiers import classify\n")
    assert boundaries(module) == frozenset()
    assert classify(module) == "unit"


# ---------------------------------------------------------------------------
# The module-level-only contract, and the runtime half that backstops it
# ---------------------------------------------------------------------------


def test_a_function_body_import_does_not_flip_the_tier(tmp_path: Path) -> None:
    """Module level only — the contract :func:`deny_boundaries` exists to catch.

    ``tests/_cliutil.py`` documents an in-function import as the sanctioned way
    to keep a heavy import out of collection, so a function-body import must not
    be read as a declared dependency. What the structural scan gives up here is
    recovered at runtime, one test below.
    """
    module = _write(
        tmp_path,
        "def test_x() -> None:\n    import subprocess\n    subprocess.run(['true'])\n",
    )
    assert boundaries(module) == frozenset()
    assert classify(module) == "unit"


def test_this_module_is_marked_unit_by_the_production_hook(
    request: pytest.FixtureRequest,
) -> None:
    """The precondition every denial test below silently depends on.

    ``deny_boundaries`` is installed by ``tests/conftest.py`` only for a
    ``unit``-tier item. If this module drifted into ``guard`` or
    ``integration`` — one module-level ``__file__`` or ``subprocess`` import
    would do it — the three ``pytest.raises(TierViolationError)`` tests would fail
    outright rather than pass vacuously, but they would fail *confusingly*.
    This names the cause.
    """
    carried = [tier for tier in TIERS if request.node.get_closest_marker(tier)]
    assert carried == ["unit"], (
        f"this item carries tiers {carried} — expected exactly ['unit'], so "
        f"that the runtime denial under test is installed on it"
    )


def test_a_unit_test_may_not_spawn_a_process() -> None:
    """The runtime denial, demonstrated on a test the denial is installed on.

    ``subprocess`` is imported in the body precisely because a module-level
    import would classify this module ``integration`` and remove the fixture
    under test — the same contract the previous test pins, seen from the other
    side.
    """
    import subprocess

    with pytest.raises(TierViolationError, match="spawned a process"):
        subprocess.Popen(["git", "status"])


def test_a_unit_test_may_not_open_a_database() -> None:
    """The other chokepoint. ``aiosqlite`` reaches ``sqlite3.connect`` too."""
    import sqlite3

    with pytest.raises(TierViolationError, match="opened a database"):
        sqlite3.connect(":memory:")


def test_the_denial_message_says_how_to_resolve_it() -> None:
    """A refusal that does not name the remedy costs the reader a code read."""
    import sqlite3

    with pytest.raises(TierViolationError) as excinfo:
        sqlite3.connect(":memory:")
    assert "tests/_tiers.py OVERRIDES" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Marker application, and the selection it buys
# ---------------------------------------------------------------------------


class _RecordingItem:
    """The two-member slice of ``pytest.Item`` that :func:`apply_tier_markers` uses."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.markers: list[str] = []

    def add_marker(self, marker: object) -> None:
        self.markers.append(marker.name)  # type: ignore[attr-defined]


def test_every_item_is_marked_with_its_modules_tier(tmp_path: Path) -> None:
    integration = _RecordingItem(
        _write(tmp_path, "import subprocess\n", "test_i.py")
    )
    guard = _RecordingItem(
        _write(tmp_path, "from pathlib import Path\nP=Path(__file__)\n", "test_g.py")
    )
    unit = _RecordingItem(_write(tmp_path, "x = 1\n", "test_u.py"))

    apply_tier_markers([integration, guard, unit])

    assert integration.markers == ["integration"]
    assert guard.markers == ["guard"]
    assert unit.markers == ["unit"]


def test_the_directory_is_never_consulted(tmp_path: Path) -> None:
    """A module under a directory named ``integration`` is still classified.

    ``tests/unit/`` outlives its meaning under this change — no files move —
    so the path carrying no authority is a property to pin, not a footnote.
    """
    nested = tmp_path / "integration"
    nested.mkdir()
    module = _write(nested, "x = 1\n")
    assert classify(module) == "unit"


def test_a_derived_tier_marker_is_selectable_by_dash_m(pytester: pytest.Pytester) -> None:
    """End to end: ``-m "unit or guard"`` really does deselect the integration tier.

    The affordance the finding asks for is *selection*, and no assertion about
    ``add_marker`` reaches it — pytest applies ``-m`` in its own
    ``pytest_collection_modifyitems``, so whether a marker added from a conftest
    arrives in time is a fact about hook ordering, not about our code. A nested
    in-process run answers it against the real
    :func:`~tests._tiers.apply_tier_markers`, not a restatement of it.
    """
    pytester.makeconftest(
        "from tests._tiers import apply_tier_markers\n"
        "def pytest_collection_modifyitems(items):\n"
        "    apply_tier_markers(items)\n"
    )
    pytester.makeini(
        "[pytest]\n"
        "addopts = --strict-markers\n"
        # The nested run inherits pytest-asyncio, which warns when this is
        # unset. Pinned so the proof does not add noise to the gate log.
        "asyncio_default_fixture_loop_scope = function\n"
        "markers =\n" + "".join(f"    {tier}: tier\n" for tier in TIERS)
    )
    pytester.makepyfile(
        test_crosses="from typer.testing import CliRunner\ndef test_x(): pass\n",
        test_pure="def test_y(): pass\n",
    )

    fast = pytester.runpytest("-m", "unit or guard")
    fast.assert_outcomes(passed=1, deselected=1)

    slow = pytester.runpytest("-m", "integration")
    slow.assert_outcomes(passed=1, deselected=1)


# ---------------------------------------------------------------------------
# Floors — the constants this module reads must not derive to nothing
# ---------------------------------------------------------------------------


def test_the_tier_vocabulary_is_the_three_named_tiers() -> None:
    """Widening order is load-bearing for :func:`tier_for`, so pin the sequence."""
    assert TIERS == ("unit", "guard", "integration")


def test_the_helper_and_override_tables_are_populated() -> None:
    """A table that derives to empty would make every check above vacuous.

    Named anchors rather than counts: a count is the drift these tables exist to
    absorb, while a name that disappears says so.
    """
    assert "tests._gitutil::init_repo" in HELPER_BOUNDARIES
    assert "tests._ledger" in HELPER_BOUNDARIES
    assert OVERRIDES, "the override table is empty — the escape hatch proves nothing"
    assert set(OVERRIDES.values()) <= set(TIERS)
