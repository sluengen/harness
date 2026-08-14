"""Every verb the socket *enumerates* must be one the socket can *resolve* (#311).

The retired launcher's hardcoded ``OPERATIONS`` frozenset went six verbs stale
before it was deleted, and a caller of a missing verb got ``unknown_verb`` and
went looking for absent code. #307 removed that failure mode at the root by
deriving the surface from the registered Typer app, and
``specs/features/runtime-host.md`` records the decision — which leaves this
guard "a floor rather than the mechanism".

**A floor still has to be able to fail.** Asserting that the derived surface
equals the registered leaf set is the change agreeing with itself: it is what
:func:`~harness.cli.serve_surface.operation_surface` computes, restated. The
drift vector that survives derivation is
:func:`~harness.cli.serve_surface.resolve_verb`'s depth ceiling — it tries
prefix lengths ``(2, 1)`` only. A three-level group is therefore enumerated
into the surface *and* unreachable over the socket: the caller gets
``unknown_verb`` for a verb the CLI genuinely registers, which is the original
Problem statement reached by a different route.

So the property asserted here is the pair, not either half: for every leaf the
registered app exposes, the socket's own resolution path returns *that leaf*.
It exercises ``operation_surface`` and ``resolve_verb`` together, which is what
``harness/cli/serve.py`` does on every request.

Today's tree has no three-deep group, so the real-app case is green on arrival
and proves nothing by passing. :func:`surface_problems` is therefore called by
the real-app test *and* by fixture apps built to violate it — one function, so
a fixture cannot pass a predicate the real app is not also measured by.

**What this module deliberately does not cover.** It checks that everything
*on* the surface resolves; it does not check that everything the app registers
*reaches* the surface. A ``_leaves`` regression that silently drops one
registered verb leaves every test here green — measured, not assumed. That half
is held by ``test_cli_serve.py::test_the_surface_is_derived_rather_than_listed``,
whose inline re-derivation is an independent oracle and is the only thing in the
tree that catches it. The two are complementary; retiring either leaves a hole.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
import typer

from harness.cli import serve_surface
from harness.cli.serve_surface import (
    SOCKET_EXCLUSIONS,
    registered_leaves,
    resolve_verb,
    surface_for,
)


def surface_problems(command: Any, exclusions: Mapping[str, str]) -> list[str]:
    """Every way ``command``'s socket surface would mislead a caller.

    Returned as messages rather than raised, so a fixture app can assert *what*
    was found and the real-app case can assert the list is empty. One function
    for both: a control that re-implements the predicate is not a control.

    Two families, and the exclusion family is why the declaration is checked
    here rather than trusted: a waiver naming a verb the app no longer
    registers is the same rot the derived surface exists to prevent, and a
    waiver with no reason is a silent narrowing of what the socket accepts.
    """
    problems = []
    registered = registered_leaves(command)
    for verb, reason in sorted(exclusions.items()):
        if verb not in registered:
            problems.append(f"stale exclusion: {verb!r} is not a verb the app registers")
        if not reason.strip():
            problems.append(f"unreasoned exclusion: {verb!r} is withheld with no recorded reason")

    surface = surface_for(command, exclusions)
    for verb in sorted(surface):
        resolved = resolve_verb(verb.split(), surface)
        if resolved != verb:
            problems.append(
                f"{verb!r} is on the socket surface but resolve_verb returns {resolved!r}"
            )
    return problems


def _noop() -> None:
    """A command body — Typer needs a callable, the guard needs only its name."""


def _flat_fixture() -> typer.Typer:
    """``start`` and ``worktrees cleanup`` — the shapes the tree has today."""
    app = typer.Typer()
    app.command("start")(_noop)
    worktrees = typer.Typer()
    worktrees.command("cleanup")(_noop)
    app.add_typer(worktrees, name="worktrees")
    return app


def _three_deep_fixture() -> typer.Typer:
    """``worktrees cache cleanup`` — one level deeper than ``resolve_verb`` tries."""
    app = typer.Typer()
    app.command("start")(_noop)
    worktrees = typer.Typer()
    cache = typer.Typer()
    cache.command("cleanup")(_noop)
    worktrees.add_typer(cache, name="cache")
    app.add_typer(worktrees, name="worktrees")
    return app


def _command(app: typer.Typer) -> Any:
    return typer.main.get_command(app)


# ---------------------------------------------------------------------------
# The guard is falsifiable — proven on fixtures, not by the real app passing
# ---------------------------------------------------------------------------


def test_a_three_deep_verb_is_reported_unreachable() -> None:
    """The drift vector derivation does not close: enumerated, still refused."""
    command = _command(_three_deep_fixture())

    assert "worktrees cache cleanup" in registered_leaves(command)
    assert surface_problems(command, {}) == [
        "'worktrees cache cleanup' is on the socket surface but resolve_verb returns None"
    ]


def test_the_shapes_the_tree_has_today_are_reported_clean() -> None:
    """The control. Without it, a guard that reported every verb would pass the
    case above and be indistinguishable from one that works."""
    assert surface_problems(_command(_flat_fixture()), {}) == []


# ---------------------------------------------------------------------------
# AC-2 — an exclusion is a real narrowing, honoured only with a reason
# ---------------------------------------------------------------------------


def test_an_exclusion_removes_the_verb_from_the_socket_surface() -> None:
    """Both directions, because only the pair separates a working subtraction
    from one that was never applied: the verb is on the surface unexcluded and
    off it excluded, and its sibling is untouched either way."""
    command = _command(_flat_fixture())

    assert "start" in surface_for(command, {})
    assert "start" not in surface_for(command, {"start": "reserved by the host process"})
    assert "worktrees cleanup" in surface_for(command, {"start": "reserved by the host process"})


def test_operation_surface_honours_the_declared_exclusions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wiring, not the pure function. ``operation_surface`` is what
    ``serve.py`` calls; a ``surface_for`` that subtracts correctly proves
    nothing if the production caller passes the declaration nowhere."""
    monkeypatch.setattr(serve_surface, "SOCKET_EXCLUSIONS", {"status": "withheld for this test"})

    surface = serve_surface.operation_surface()

    assert "status" not in surface
    assert "start" in surface


def test_an_exclusion_without_a_recorded_reason_is_refused() -> None:
    command = _command(_flat_fixture())

    assert surface_problems(command, {"start": "   "}) == [
        "unreasoned exclusion: 'start' is withheld with no recorded reason"
    ]


def test_an_exclusion_with_a_recorded_reason_is_accepted() -> None:
    """The other direction. Without it, a guard that rejected every exclusion
    would pass the case above while making the declaration unusable."""
    command = _command(_flat_fixture())

    assert surface_problems(command, {"start": "reserved by the host process"}) == []


def test_an_excluded_verb_is_no_longer_measured_for_reachability() -> None:
    """The guard measures the surface the socket actually offers, not the raw
    leaf set. Without this the checker could read ``registered_leaves`` and
    still pass every case above, and a verb the declaration withholds would be
    reported unreachable — a complaint about a route nobody claims exists."""
    command = _command(_three_deep_fixture())

    assert surface_problems(command, {"worktrees cache cleanup": "no socket route"}) == []


def test_an_exclusion_naming_an_unregistered_verb_is_refused() -> None:
    """A waiver outliving its verb is the drift this ticket exists to stop,
    reappearing inside the escape hatch."""
    command = _command(_flat_fixture())

    assert surface_problems(command, {"nonesuch": "a real-sounding reason"}) == [
        "stale exclusion: 'nonesuch' is not a verb the app registers"
    ]


# ---------------------------------------------------------------------------
# AC-1 — the real registered app, measured against the real declaration
# ---------------------------------------------------------------------------


def test_every_registered_verb_is_reachable_over_the_socket() -> None:
    from harness.cli import app

    command = _command(app)
    surface = surface_for(command, SOCKET_EXCLUSIONS)

    # Floor: an empty or tiny surface makes the assertion below vacuously true.
    assert len(surface) > 10, f"implausibly small socket surface: {sorted(surface)}"
    assert {"start", "review", "promote start", "worktrees cleanup"} <= surface

    assert surface_problems(command, SOCKET_EXCLUSIONS) == []
