"""CLI entrypoint — see SPEC §11.

The CLI is the public contract. Stable flags, stable exit codes, stable JSON
output. Subcommands are split across modules for readability:

* :mod:`harness.cli.version`  — ``harness version``
* :mod:`harness.cli.validate` — ``harness validate <workflow.yaml>``
* :mod:`harness.cli.query`    — ``harness status / logs / events``
* :mod:`harness.cli.worktrees` — ``harness worktrees list / cleanup``

Per-workflow ``harness run <workflow>`` dynamic generation is reserved for a
later task; this package only assembles the read-side surface.

Exit codes:
- 0   workflow completed successfully / read command succeeded
- 1   workflow failed (caught error during execution)
- 2   invocation error (bad flags, unknown run-id, workflow YAML invalid)
- 3   contract violation (LLM output failed validation after exhausting retries)
- 4   paused awaiting decision (v2)
- 130 SIGINT
"""

from __future__ import annotations

import typer

from harness.cli.decisions import decision_app, decisions_app
from harness.cli.query import (
    events_command,
    logs_command,
    status_command,
)
from harness.cli.validate import validate_command
from harness.cli.version import version_command
from harness.cli.worktrees import worktrees_app

app = typer.Typer(
    help="Deterministic workflow execution harness — see SPEC.md",
    no_args_is_help=True,
)


@app.callback()
def _root() -> None:
    """Calibrate Harness root callback.

    Forces Typer into multi-subcommand mode so subcommands like ``version`` are
    invoked as ``harness version`` (not promoted to the root).
    """


# Top-level read commands.
app.command(name="version", help="Print harness version.")(version_command)
app.command(name="validate", help="Validate a workflow YAML file (static).")(
    validate_command
)
app.command(name="status", help="Print a run's terminal-state summary.")(
    status_command
)
app.command(name="logs", help="Print a run's event timeline.")(logs_command)
app.command(name="events", help="Print a run's events (JSON or compact).")(
    events_command
)

# Nested worktrees app.
app.add_typer(worktrees_app, name="worktrees", help="Inspect or clean up run worktrees.")

# v2-reserved decision surface — see SPEC §11 and harness/cli/decisions.py.
app.add_typer(
    decisions_app,
    name="decisions",
    help="v2-reserved — enumerate paused runs awaiting human decision.",
)
app.add_typer(
    decision_app,
    name="decision",
    help="v2-reserved — inspect or resolve a paused decision node.",
)


__all__ = ["app"]


if __name__ == "__main__":
    app()
