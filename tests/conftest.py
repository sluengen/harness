"""Top-level pytest configuration.

Registers custom markers used by integration tests, assigns every collected
test its dependency tier, and keeps the suite hermetic against a real
``LINEAR_API_KEY`` in the environment.
"""

from __future__ import annotations

import pytest

from tests._tiers import apply_tier_markers, deny_boundaries


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers so `--strict-markers` accepts them."""
    config.addinivalue_line(
        "markers",
        "docker: integration tests that build and run a docker image "
        "(skip if docker is unavailable).",
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Assign each collected test the tier its module's dependencies imply.

    Derived rather than declared, so ``-m unit`` / ``-m "unit or guard"`` /
    ``-m integration`` select honestly without a marker line in 250 modules —
    the rationale, the boundary definitions and the escape hatch all live in
    :mod:`tests._tiers`. This hook runs before pytest's own ``-m`` deselection,
    which is what makes a derived marker selectable at all.
    """
    apply_tier_markers(items)


@pytest.fixture(autouse=True)
def _deny_out_of_process_boundaries(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail a ``unit``-tier test that spawns a process or opens a database.

    The runtime half of the tier guarantee. :func:`tests._tiers.classify` is
    structural and cannot see a boundary a test reaches through *production*
    code; this makes that miss loud instead of letting the fast tier quietly
    acquire a git, ledger or process dependency. ``guard`` and ``integration``
    tests are untouched — a guard reaching the tracked set through
    ``git ls-files`` is exactly what its tier permits.
    """
    if request.node.get_closest_marker("unit") is not None:
        deny_boundaries(monkeypatch)


@pytest.fixture(autouse=True)
def _hermetic_linear_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset ``LINEAR_API_KEY`` for every test so none reaches the real tracker.

    Verbs now touch Linear on more paths — ``review`` parks the ticket In Review
    (CAL-1103), on top of ``start``/``close``/``reclaim`` — and ``linear_enabled``
    defaults **on** for a repo with no ``CONTEXT.md`` (the throw-away tmp repos
    these tests use). Without this, a dev or CI shell that happens to export
    ``LINEAR_API_KEY`` would let a green-path verb test build a real ``LinearClient``
    and attempt a live network transition. Deleting the key makes ``linear_api_key``
    raise deterministically, so a verb that does not patch Linear degrades to the
    tracker-less no-op instead. A test that needs a key patches
    ``linear_api_key`` / ``LinearClient`` directly (bypassing the env), so this
    is transparent to them.
    """
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)


# ``pytester`` is enabled here because a root conftest is the only place pytest
# accepts ``pytest_plugins``. It exists for one test — the end-to-end proof in
# ``tests/unit/test_tiers.py`` that a derived tier marker is actually selectable
# by ``-m``, which is the affordance #336 delivers and which no assertion about
# ``add_marker`` alone can demonstrate. The nested runs are in-process.
pytest_plugins = ["pytester"]
