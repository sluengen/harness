"""Top-level pytest configuration.

Registers custom markers used by integration tests.
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
