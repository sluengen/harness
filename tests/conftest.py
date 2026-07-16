"""Top-level pytest configuration.

Registers custom markers used by integration tests, and keeps the suite
hermetic against a real ``LINEAR_API_KEY`` in the environment.
"""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers so `--strict-markers` accepts them."""
    config.addinivalue_line(
        "markers",
        "docker: integration tests that build and run a docker image "
        "(skip if docker is unavailable).",
    )


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
