"""Shared Typer introspection for test modules.

One of them: :func:`registered_command_surface`, the set of names the
top-level app exposes as ``harness <name>``.

Five guards derived that set for themselves — the CLI-surface lock, the
feature-spec/CLI agreement check, #219's anti-vacuity oracle, and the Hermes
and YAML-engine retirement guards — three of them with the same two lines
copied verbatim, two reading only the ``registered_commands`` half. Five
readers of one concept means a Typer API change, or the latent bug of dropping
the ``registered_groups`` half, has to be found and fixed five times (#222,
``code-quality`` Part B).

It lives here rather than in :mod:`tests._gitutil`: that module's subject is
the git-tracked file set, and Typer introspection is a different domain. The
convention is one shared module per domain, not one per line count.

The app is a **parameter**, never imported here. Every call site imports
``harness.cli`` inside its own function body deliberately; a module-level
import would pull the CLI into collection for anything importing this helper.
"""

from __future__ import annotations

import typer


def registered_command_surface(app: typer.Typer) -> set[str]:
    """Every top-level command and sub-app name the Typer app registers.

    Both halves, always — direct commands *and* sub-app groups. A registration
    with no explicit ``name=`` is excluded: Typer would render it under its
    callable's function name, so the result is a subset of the rendered surface
    in general, though ``harness/cli/__init__.py`` names every registration and
    the two coincide today.

    Top level only. The ``promote`` group contributes ``"promote"``, never
    ``promote start``.
    """
    names = {c.name for c in app.registered_commands if c.name is not None}
    names |= {g.name for g in app.registered_groups if g.name is not None}
    return names
