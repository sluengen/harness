"""``harness version`` — print the harness version string.

Two output forms: human (``slate-harness <v>``) and machine (``--json``
emits ``{"version": "<v>"}``). Per SPEC §11 JSON keys are part of the public
contract — don't rename without a major bump.
"""

from __future__ import annotations

import json

import typer

from harness import __version__


def version_command(
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Print harness version."""
    if json_output:
        typer.echo(json.dumps({"version": __version__}))
    else:
        typer.echo(f"slate-harness {__version__}")
