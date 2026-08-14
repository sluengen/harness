"""The verb surface ``harness serve`` accepts — derived, never listed (#307).

The retired launcher's hardcoded ``OPERATIONS`` frozenset went stale as soon as
a verb was added, and six had been added by the time it was removed. Deriving
the surface from the registered Typer app makes that drift structurally
impossible; #311's guard is then a floor rather than the mechanism.

Extracted from :mod:`harness.cli.serve` in #310 so the socket server's own
module has room for the maintenance scheduler's wiring. It is one idea with one
recorded decision (``specs/features/runtime-host.md``, *Operation surface:
derived, not an allowlist*), on the same seam convention the ``review_*`` /
``close_*`` / ``reclaim_*`` modules follow.

**The layering rule is load-bearing here.** :func:`operation_surface` imports
``harness.cli`` *inside the function body*: the host runs this code before any
container exists, and a module-scope import would pull the whole CLI package —
and everything it imports — into the host process at startup.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

__all__ = [
    "SOCKET_EXCLUSIONS",
    "operation_surface",
    "registered_leaves",
    "resolve_verb",
    "surface_for",
]

#: Verbs the socket deliberately does not accept, each mapped to why (#311).
#:
#: The escape hatch for the one case derivation cannot express: a verb the CLI
#: registers that must not be reachable over the socket. It is a **declaration
#: with an effect** — :func:`surface_for` subtracts its keys, so an entry here
#: narrows what the server accepts rather than documenting an intention.
#:
#: ``tests/unit/test_serve_verb_reachability.py`` refuses an entry with a blank
#: reason and an entry naming a verb the app does not register: a waiver
#: outliving its verb is the same rot the derived surface exists to prevent.
#:
#: **Empty, deliberately.** #311 makes an unreachable verb fail loudly; it
#: routes nothing and withholds nothing, and its Out of scope reserves adding
#: or removing socket routes for the host-process work. ``serve`` is the one
#: plausible candidate — a ``serve`` reached over the socket of a running
#: ``serve`` — and excluding it is a behaviour change this ticket does not
#: authorise. An empty mapping here is the recorded answer, not an omission.
SOCKET_EXCLUSIONS: dict[str, str] = {}


def _leaves(command: Any, prefix: str = "") -> Iterator[str]:
    """Every leaf invocation reachable from ``command``, space-joined.

    Recurses through groups, so ``promote start`` and ``worktrees cleanup`` are
    enumerated as leaves rather than collapsed into their group name. A
    recursion that stopped at the top level would refuse every subcommand at
    runtime while looking correct in a smoke test.
    """
    commands = getattr(command, "commands", None)
    if commands:
        for name, child in commands.items():
            yield from _leaves(child, prefix=f"{prefix}{name} ")
    else:
        name = prefix.strip()
        if name:
            yield name


def registered_leaves(command: Any) -> set[str]:
    """Every leaf invocation ``command`` registers, before any exclusion.

    Takes the command tree as a parameter so the surface of an arbitrary app is
    answerable — #311's guard needs a fixture app to be measured by the same
    derivation the real one is, and a derivation reachable only through the
    hardcoded app can only ever be restated, never falsified.
    """
    return set(_leaves(command))


def surface_for(command: Any, exclusions: Mapping[str, str]) -> set[str]:
    """``command``'s leaf invocations, less the ones ``exclusions`` withholds.

    The exclusions are a parameter rather than a module read so the guard can
    measure the real declaration and a fixture one through this same
    subtraction.
    """
    return registered_leaves(command) - set(exclusions)


def operation_surface() -> set[str]:
    """The set of verb invocations this socket will accept.

    Derived from the registered Typer app on every call rather than cached: the
    app is fixed at import, and re-deriving costs a tree walk over a few dozen
    commands while removing any question of a stale snapshot.

    Imported inside the function body per the layering rule — ``harness.cli``
    must not be imported at module scope by anything the host runs early.
    """
    import typer as _typer

    from harness.cli import app

    return surface_for(_typer.main.get_command(app), SOCKET_EXCLUSIONS)


def resolve_verb(argv: list[str], surface: set[str]) -> str | None:
    """The registered invocation ``argv`` names, by longest prefix, or ``None``.

    Longest-prefix first so ``worktrees cleanup`` resolves as itself rather than
    as the group ``worktrees`` with a stray argument.
    """
    for length in (2, 1):
        candidate = " ".join(argv[:length])
        if candidate in surface:
            return candidate
    return None
