"""Shared asyncio plumbing for test modules.

One of them: :func:`run_sync`, which drives a coroutine to completion from a
synchronous test body.

The same five-line runner was defined **26 times** across the test tree under
three names (``_sync``, ``_run_sync``, ``run_sync``) — two of them inside the
shared-helper package itself, one private and one public, sitting beside each
other and doing the same thing (#279). ``code-quality`` Part B extracts on the
third strike. The concrete cost was not the duplication but the *rationale*:
only one of the 26 copies carried the docstring explaining why a fresh loop is
built instead of calling :func:`asyncio.run`, so the reasoning was invisible
from the other 25 sites and the next copy had no way to inherit it.

It lives here rather than in :mod:`tests._cliutil`: that module's subject is
Typer introspection, and asyncio plumbing is a different domain. The convention
this package follows is one shared module per domain, not one per line count —
so this takes the ``<domain>util`` spelling of :mod:`tests._gitutil` and
:mod:`tests._cliutil`, rather than the test-family spelling of
:mod:`tests._ledger` and :mod:`tests._reclaim`.

Stdlib only, by design: this module imports no ``harness`` module and no other
``tests`` module, so it cannot participate in an import cycle or pull the CLI
into collection for anything that imports it.

:mod:`tests.unit.test_async_runner_single_home` holds the invariant to one
definition, so copy 27 fails the gate rather than slipping through review.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


def run_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to completion on a fresh event loop, then close it.

    Runs ``coro`` regardless of whether pytest-asyncio left an event loop
    dangling on the current thread. ``asyncio_mode = "auto"``
    (``pyproject.toml``) means the suite's async tests run under a loop
    pytest-asyncio manages, and :func:`asyncio.run` refuses to run when any
    loop is already "running" — so a synchronous test body reaching for an
    async driver (``aiosqlite``, the ledger store) needs its own loop with
    explicit teardown rather than ``asyncio.run``.

    The ``finally: loop.close()`` is the only thing preventing a leaked loop
    and its file descriptors across a suite that calls this hundreds of times;
    several modules call it 7–10 times in a single test. Do not "simplify" this
    to :func:`asyncio.run` — that is the change this docstring exists to
    forbid.

    There is no ``except`` clause, deliberately: a failing coroutine surfaces
    as the caller's failure. A helper that caught and returned would turn a
    real ledger error into a green test.

    Typed generically over the coroutine's result, so call sites need no
    ``# type: ignore`` — the loose ``Any``/``object`` spellings of the copies
    this replaces were the reason those ignores existed. ``Coroutine`` rather
    than ``Awaitable`` because that is what
    :meth:`asyncio.AbstractEventLoop.run_until_complete` accepts.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
