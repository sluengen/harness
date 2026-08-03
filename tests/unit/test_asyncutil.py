"""Unit tests for the shared asyncio runner (#279).

``run_sync`` is the single home for driving a coroutine to completion from a
synchronous test body. These tests pin the three properties its 26 consumers
depend on: it returns the coroutine's value, it propagates the coroutine's
exception rather than swallowing it, and it leaves the thread clean enough for
the next call — several modules call it 7–10 times in one test.

They mirror the ``tests/unit/test_cliutil.py`` / ``test_gitutil.py`` precedent:
a shared helper carries its own behaviour tests rather than being covered only
incidentally by its consumers.
"""

from __future__ import annotations

import pytest

from tests._asyncutil import run_sync


async def _answer() -> int:
    return 42


async def _raises() -> int:
    raise ValueError("boom")


def test_returns_the_coroutine_result() -> None:
    """The coroutine's value comes back to the synchronous caller."""
    assert run_sync(_answer()) == 42


def test_propagates_the_coroutine_exception() -> None:
    """A failing coroutine surfaces as the caller's failure, not a swallowed error.

    This is also the loop-closed-on-the-error-path case: the ``finally`` runs
    whether the coroutine returned or raised.
    """
    with pytest.raises(ValueError, match="boom"):
        run_sync(_raises())


def test_sequential_calls_both_succeed() -> None:
    """Teardown does not wedge the thread for the next call.

    The observable proof that ``loop.close()`` leaves the thread usable: a
    leaked or unclosed loop manifests exactly as the second call failing.
    """
    assert run_sync(_answer()) == 42
    assert run_sync(_answer()) == 42
