"""The tier boundary held against the corpus it classifies (#336).

The classifier's own cases live in ``test_tiers.py`` and run against synthetic
sources under ``tmp_path``. This module asks the questions that only the real
tree can answer: does every tracked test module classify, is every shared helper
entered in the boundary table, and does every override still name live code.

*"Is the gate still the whole suite" was answered here too until #358 split the
gate into two selected stages; it is now answered by measurement in
``test_verify_parallel_tiers.py`` — see the note where it stood.*

**This module is deliberately ``guard``-tier.** It reads the committed tree
through :mod:`tests._gitutil`, which is exactly the boundary ``guard`` names, so
the classifier under test puts it there — and
:func:`test_this_module_carries_the_tier_the_classifier_assigns_it` checks that
the production hook in ``tests/conftest.py`` actually said so. That
split from ``test_tiers.py`` is what keeps the runtime-denial demonstration
honest; the reason is written out in that module's docstring.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

from tests._gitutil import tracked_files_under, tracked_py_sources
from tests._tiers import HELPER_BOUNDARIES, OVERRIDES, TIERS, Tier, boundaries, classify

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: This module, excluded from the retirement scan below — it has to carry the
#: literal it bans in order to look for it. The repo's existing retirement
#: guards use the same ``_SELF`` exclusion.
_SELF = "tests/unit/test_tiers_corpus.py"

#: The retired marker, named once so the scan and its positive control cannot
#: drift into testing different needles.
_RETIRED_MARKER = "pytest.mark.slow"

#: One named module per tier. Anchors rather than counts: a count is the drift
#: these floors exist to absorb, while a renamed or deleted anchor says so by
#: name. Each was chosen because its tier follows from what it plainly does.
_ANCHORS: dict[str, Tier] = {
    # Drives `harness start` through CliRunner against a real repo and ledger.
    "tests/unit/test_cli_start.py": "integration",
    # Reads the process doc and its three entry-file mirrors out of the checkout.
    "tests/unit/test_process_doc_mirrors.py": "guard",
    # Parses a CONTEXT.md loop block held in the test's own strings.
    "tests/unit/test_loop_budget.py": "unit",
}


def _test_modules() -> list[Path]:
    return [
        path
        for path in tracked_py_sources("tests")
        if path.name.startswith("test_")
    ]


def _shared_helpers() -> list[Path]:
    return [
        path
        for path in tracked_py_sources("tests")
        if path.parent.name == "tests"
        and path.name.startswith("_")
        and path.name != "__init__.py"
    ]


def _relpath(path: Path) -> str:
    return path.relative_to(_REPO_ROOT).as_posix()


def _derived_tier(path: Path) -> Tier:
    """*path*'s tier ignoring :data:`OVERRIDES` — what the scan alone concludes."""
    from tests._tiers import tier_for

    return tier_for(boundaries(path))


# ---------------------------------------------------------------------------
# Floors — every derived set below must reach real modules
# ---------------------------------------------------------------------------


def test_the_corpus_reaches_the_named_anchors() -> None:
    """The subject set is non-empty and contains modules we can name.

    A parametrized guard over a derived set goes *vacuous*, not red, when the
    derivation dies: pytest parametrizes over nothing and the run stays green.
    This is the floor for the two derivations below, and it asserts membership
    rather than re-running the derivation.
    """
    modules = {_relpath(path) for path in _test_modules()}
    assert modules, "no tracked test modules — the corpus derivation collapsed"
    missing = set(_ANCHORS) - modules
    assert not missing, f"anchor modules are no longer tracked: {sorted(missing)}"


def test_every_tier_is_populated_by_a_module_we_can_name() -> None:
    """Each of the three tiers holds real modules, one of which is named.

    A classifier that answered ``"integration"`` for everything would satisfy
    "every module classifies" while destroying the affordance. This is what
    fails then.
    """
    tiers = {path: classify(path) for path in _test_modules()}
    populated = set(tiers.values())
    assert populated == set(TIERS), f"tiers with no modules: {set(TIERS) - populated}"
    for relpath, expected in _ANCHORS.items():
        assert tiers[_REPO_ROOT / relpath] == expected, (
            f"{relpath} classified {tiers[_REPO_ROOT / relpath]!r}, expected "
            f"{expected!r} — the boundary it crosses has changed, or the "
            f"detector for that boundary has"
        )


def test_the_shared_helper_set_reaches_gitutil() -> None:
    """The helper derivation is non-empty and finds the one that spans boundaries."""
    helpers = {_relpath(path) for path in _shared_helpers()}
    assert "tests/_gitutil.py" in helpers, f"helper derivation collapsed: {helpers}"


# ---------------------------------------------------------------------------
# Whole-suite invariants
# ---------------------------------------------------------------------------


def test_every_tracked_test_module_classifies() -> None:
    """No module in the tree defeats the classifier.

    The failure this closes is a parse or lookup error surfacing during
    collection, where it costs a whole run rather than one test.
    """
    for path in _test_modules():
        assert classify(path) in TIERS


def test_every_shared_helper_declares_its_boundaries() -> None:
    """A new ``tests/_*.py`` helper cannot enter the suite unclassified.

    :data:`HELPER_BOUNDARIES` resolves **one hop only**: a helper that itself
    imports another boundary helper has to state the union. This is the
    tripwire against a second hop appearing — add ``tests/_docker.py``, use it
    from three modules, and those modules stay ``unit`` until it is entered
    here.
    """
    for path in _shared_helpers():
        key = f"tests.{path.stem}"
        assert key in HELPER_BOUNDARIES, (
            f"{_relpath(path)} is a shared test helper with no entry in "
            f"tests._tiers.HELPER_BOUNDARIES — every module importing it would "
            f"be classified as if it crossed nothing"
        )


def test_every_override_names_a_tracked_module() -> None:
    """An exemption must name live code."""
    for relpath in OVERRIDES:
        assert tracked_files_under(relpath), (
            f"tests._tiers.OVERRIDES names {relpath}, which the tree no longer "
            f"tracks — a stale exemption is a hole, not a no-op"
        )


def test_every_override_actually_exempts_something() -> None:
    """An entry whose declared tier equals its derived tier proves nothing.

    The #219 lesson applied to this table: an allowlist with no still-needed
    check silently grows into a hole. Each entry here exists because the test
    reaches a boundary through *production* code that the structural scan
    cannot see, so removing the entry has to change the answer.
    """
    for relpath, declared in OVERRIDES.items():
        derived = _derived_tier(_REPO_ROOT / relpath)
        assert derived != declared, (
            f"tests._tiers.OVERRIDES[{relpath!r}] declares {declared!r}, which "
            f"the classifier already derives — delete the entry"
        )


@pytest.mark.parametrize("relpath", sorted(OVERRIDES))
def test_an_override_widens_the_tier_it_replaces(relpath: str) -> None:
    """An override may only widen. Narrowing would be a way to silence the denial.

    The escape hatch exists because the structural scan is blind to a boundary
    reached through production code — always a *missed* dependency, never an
    imagined one. An entry demoting a module to ``unit`` would be using the
    table to opt out of the guarantee rather than to correct it.
    """
    declared = OVERRIDES[relpath]
    derived = _derived_tier(_REPO_ROOT / relpath)
    assert TIERS.index(declared) > TIERS.index(derived), (
        f"{relpath} is overridden from {derived!r} down to {declared!r}"
    )


# ---------------------------------------------------------------------------
# The markers, the retirement, and the gate
# ---------------------------------------------------------------------------


def _registered_markers() -> dict[str, str]:
    config = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    entries = config["tool"]["pytest"]["ini_options"]["markers"]
    return {entry.split(":", 1)[0].strip(): entry for entry in entries}


def test_every_tier_is_registered_as_a_marker() -> None:
    """``--strict-markers`` turns a missing registration into a collection error.

    Derived from :data:`tests._tiers.TIERS` rather than listed, so adding a
    tier is what forces its registration — one edit, not two that can drift.
    """
    registered = _registered_markers()
    missing = [tier for tier in TIERS if tier not in registered]
    assert not missing, f"tiers registered nowhere in pyproject.toml: {missing}"


def test_the_marker_list_holds_no_tier_the_classifier_does_not_know() -> None:
    """The reverse direction: a registered tier name with no tier behind it.

    ``docker`` is deliberately exempt — it is a *capability* that narrows
    ``integration``, not a tier, and the two docker modules carry both.
    """
    registered = set(_registered_markers()) - {"docker"}
    assert registered == set(TIERS), (
        f"pyproject.toml registers {sorted(registered)}, tests._tiers knows "
        f"{sorted(TIERS)}"
    )


def test_the_slow_marker_is_retired() -> None:
    """``slow`` survived on 34 tests in two modules and was selected by nothing.

    It was a second, weaker name for ``integration``: both modules carrying it
    (``test_cli_start.py``, ``test_worktree.py``) drive real repositories, so
    every test it marked is now ``integration`` by dependency rather than by an
    unmeasured judgment about speed. Nothing in ``scripts/verify.sh`` or CI ever
    selected on it.
    """
    scanned = [path for path in tracked_py_sources("tests") if _relpath(path) != _SELF]
    assert scanned, "the retirement scan reaches no modules"
    offenders = [
        _relpath(path)
        for path in scanned
        if _RETIRED_MARKER in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"the retired `slow` marker is back in: {offenders}"
    assert "slow" not in _registered_markers()


def test_the_retirement_scan_would_see_the_marker_if_it_returned() -> None:
    """The positive control for an absence assertion.

    A sentence never written is absent for free, so the check above passes
    against a scan that reads nothing — or one whose needle no longer matches
    what a real marker looks like. This runs the same predicate over synthetic
    source that reinstates the retired marker and requires it to be found.

    It is also why the scan excludes ``_SELF``: this module has to carry the
    literal to look for it, and a guard that flags itself is a guard nobody can
    keep green.
    """
    reinstated = "import pytest\n\npytestmark = pytest.mark.slow\n"
    assert _RETIRED_MARKER in reinstated
    assert _RETIRED_MARKER not in "import pytest\n\npytestmark = pytest.mark.docker\n"


# ``test_the_gate_still_runs_the_whole_suite`` lived here until #358 and is not
# lost: it is superseded by
# ``test_verify_parallel_tiers.py::test_the_gate_stages_partition_the_whole_suite``.
# Its #336 form banned any ``-m`` from the gate's pytest lines, which was a proxy
# for "the gate does not narrow the suite". #358 partitions the gate into
# ``-m docker`` and ``-m "not docker"``, so the proxy would now forbid the
# arrangement rather than the abuse. The successor asserts the property itself —
# the union of the gate's selections *is* the whole suite, and the stages do not
# overlap — by collecting each selection, which also catches the narrowings a
# ``-m`` ban never could (``--ignore``, ``--deselect``). It lives beside the other
# gate-shape guards; the tier vocabulary this module owns is unchanged.


# ---------------------------------------------------------------------------
# The production wiring, checked from inside it
# ---------------------------------------------------------------------------


def test_this_module_carries_the_tier_the_classifier_assigns_it(
    request: pytest.FixtureRequest,
) -> None:
    """The conftest hook is live, checked against the running item.

    Everything above tests :mod:`tests._tiers` as a library. If
    ``tests/conftest.py`` stopped calling
    :func:`~tests._tiers.apply_tier_markers`, all of it would still pass while
    no test in the suite carried a tier at all. Reading the marker off this very
    item is the check that cannot be satisfied by the library alone — and it
    also pins that this module sits in ``guard``, which is what keeps the
    denial demonstration in ``test_tiers.py`` meaningful.
    """
    carried = [tier for tier in TIERS if request.node.get_closest_marker(tier)]
    assert carried == ["guard"], (
        f"this item carries tiers {carried} — expected exactly ['guard']. An "
        f"empty list means tests/conftest.py no longer applies tier markers."
    )


def test_the_conftest_hook_and_fixture_are_wired_to_the_classifier() -> None:
    """Both halves are reached from the root conftest, not just the marker one.

    The item-level check above proves the collection hook ran. The runtime
    denial has its own demonstration in ``test_tiers.py``, but only for the
    ``unit`` tier — nothing there would notice the fixture being narrowed to a
    tier that does not exist. This reads the conftest's own AST for the two
    call sites.
    """
    tree = ast.parse((_REPO_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8"))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert {"apply_tier_markers", "deny_boundaries"} <= called, (
        f"tests/conftest.py calls {sorted(called)} — both halves of the tier "
        f"guarantee must be wired there"
    )
