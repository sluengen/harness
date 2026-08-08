"""The event-loop runner has exactly one home in the test tree (#279).

The same five-line wrapper — ``new_event_loop`` / ``run_until_complete`` /
``close`` — was defined **26 times** across ``tests/``, under three names
(``_sync``, ``_run_sync``, ``run_sync``), two of them side by side inside the
shared-helper package itself. ``code-quality`` Part B extracts on the third
strike; this was the 26th. The rationale for *why* a fresh loop is used lived
at exactly one of the 26 sites, invisible from the other 25.

This guard is the structural half of that fix: it derives the test tree from
``tracked_py_sources`` and asserts that only ``tests/_asyncutil.py`` drives an
event loop, so copy 27 fails the gate instead of slipping through review.

**Scope limit, stated rather than left implicit.** ``asyncio.run`` is
deliberately *not* a flagged construct. It is a different call with different
semantics, no site uses it, and converting the suite to it (or to
pytest-asyncio) is out of scope on #279 — this guard pins the single-home
invariant, not the async strategy.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._gitutil import tracked_py_sources

# ``tests/unit/test_async_runner_single_home.py`` → ``parents[2]`` is the root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

_CANONICAL = _REPO_ROOT / "tests" / "_asyncutil.py"

# Both halves of the copied body. A copy is caught if *either* survives, and
# attribute-name matching covers every prefixed, aliased and renamed form
# (``loop.run_until_complete``, ``asyncio.new_event_loop()``, a differently
# named loop variable, a 27th wrapper name).
_LOOP_CONSTRUCTS = ("run_until_complete", "new_event_loop")


def loop_driving_calls(path: Path) -> list[str]:
    """``<relpath>:<lineno>: <attr>`` for every event-loop call in ``path``.

    An AST predicate, not a text match: a construct named in a docstring or
    held in a string literal is not an ``ast.Call`` and is correctly ignored.
    That is why this guard — itself a tracked file under ``tests/`` naming both
    constructs in prose and embedding the wrapper as a literal in its own
    anti-vacuity case — needs no self-exemption.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    try:
        relpath = path.relative_to(_REPO_ROOT)
    except ValueError:  # a synthetic source outside the repo (tmp_path)
        relpath = path
    return [
        f"{relpath}:{node.lineno}: {node.func.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _LOOP_CONSTRUCTS
    ]


def test_only_the_shared_module_drives_a_loop() -> None:
    """No test module outside ``tests/_asyncutil.py`` constructs or drives a loop."""
    sources = tracked_py_sources("tests", repo_root=_REPO_ROOT)
    # Positive control: a typo'd base would yield zero files and zero
    # offenders, which is a vacuous pass rather than a clean tree.
    assert len(sources) > 50, f"scan basis collapsed: {len(sources)} files"

    offenders = sorted(
        call
        for source in sources
        if source != _CANONICAL
        for call in loop_driving_calls(source)
    )

    assert not offenders, (
        "the event-loop runner has one home, tests/_asyncutil.py; "
        "import run_sync from it instead of re-declaring a wrapper:\n"
        + "\n".join(offenders)
    )


def test_the_shared_module_defines_exactly_one_runner() -> None:
    """The canonical module holds one loop construction and one drive.

    Without this the guard could go quietly vacuous: delete ``run_sync`` and
    "no module outside the canonical one drives a loop" becomes trivially true.
    It also refuses a *second* runner added inside the canonical file — being
    the single home is not a blanket exemption.
    """
    assert _CANONICAL.is_file(), f"missing canonical module: {_CANONICAL}"

    calls = loop_driving_calls(_CANONICAL)
    constructs = sorted(call.rsplit(": ", 1)[1] for call in calls)

    assert constructs == ["new_event_loop", "run_until_complete"], calls


def test_detector_flags_a_copy(tmp_path: Path) -> None:
    """The detector reports a re-declared wrapper, with its line numbers.

    The wrapper is embedded here as a string literal — the anti-vacuity case
    that proves the guard would catch copy 27 rather than passing because it
    scanned nothing.
    """
    copy = tmp_path / "test_copy.py"
    copy.write_text(
        "import asyncio\n"
        "\n"
        "\n"
        "def _run_sync(coro):\n"
        "    loop = asyncio.new_event_loop()\n"
        "    try:\n"
        "        return loop.run_until_complete(coro)\n"
        "    finally:\n"
        "        loop.close()\n",
        encoding="utf-8",
    )

    offenders = loop_driving_calls(copy)

    assert [call.rsplit(": ", 1)[1] for call in offenders] == [
        "new_event_loop",
        "run_until_complete",
    ], offenders
    assert [call.split(":")[1] for call in offenders] == ["5", "7"], offenders
