"""CLI entrypoint — see SPEC §11.

The CLI is the public contract. Stable flags, stable exit codes, stable JSON
output. The harness exposes verbs the orchestrating agent shells out to
(``start`` / ``review`` / ``close``) plus read/inspection commands. Subcommands
are split across modules for readability:

* :mod:`harness.cli.version`  — ``harness version``
* :mod:`harness.cli.query`    — ``harness status / logs / events / runs``
* :mod:`harness.cli.worktrees` — ``harness worktrees list / cleanup``
* :mod:`harness.cli.start`    — ``harness start <ticket>``
* :mod:`harness.cli.review`   — ``harness review --run-id <id>``
* :mod:`harness.cli.close`    — ``harness close <ticket> --run-id <id>``

Exit codes:
- 0   command succeeded
- 1   unexpected error (git failure, DB error, Linear error)
- 2   invocation / gate refusal (bad flags, unknown run-id, gate not satisfied)
- 130 SIGINT
"""

from __future__ import annotations

import typer

from harness.cli.cancel import cancel_command
from harness.cli.checkpoint import checkpoint_command
from harness.cli.close import close_command
from harness.cli.doctor import doctor_command
from harness.cli.query import (
    events_command,
    logs_command,
    runs_command,
    status_command,
)
from harness.cli.reclaim import reclaim_command
from harness.cli.review import review_command
from harness.cli.start import start_command
from harness.cli.version import version_command
from harness.cli.worktrees import worktrees_app

app = typer.Typer(
    help="Deterministic, audited verbs an agent calls to drive a ticket — see SPEC.md",
    no_args_is_help=True,
)


@app.callback()
def _root() -> None:
    """Harness root callback.

    Forces Typer into multi-subcommand mode so subcommands like ``version`` are
    invoked as ``harness version`` (not promoted to the root).
    """


# Top-level read commands.
app.command(name="version", help="Print harness version.")(version_command)
app.command(name="status", help="Print a run's terminal-state summary.")(
    status_command
)
app.command(name="logs", help="Print a run's event timeline.")(logs_command)
app.command(name="events", help="Print a run's events (JSON or compact).")(
    events_command
)
app.command(name="cancel", help="Abandon an in-flight run (close without merge).")(
    cancel_command
)
app.command(name="reclaim", help="Reclaim a stranded run: revert its ticket to Todo and reconcile the ledger.")(  # noqa: E501
    reclaim_command
)
app.command(name="doctor", help="Run system health checks.")(doctor_command)
app.command(name="runs", help="List recent runs.")(runs_command)
app.command(name="start", help="Open a run: fetch ticket, transition to In Progress, create worktree.")(  # noqa: E501
    start_command
)
app.command(name="review", help="Review the worktree HEAD with codex; record the verdict bound to that SHA.")(  # noqa: E501
    review_command
)
app.command(name="close", help="Close a run: enforce the review gate, merge/push, transition ticket to Done.")(  # noqa: E501
    close_command
)
app.command(name="checkpoint", help="Push the run branch to origin so committed WIP survives the container dying.")(  # noqa: E501
    checkpoint_command
)

# Nested worktrees app.
app.add_typer(worktrees_app, name="worktrees", help="Inspect or clean up run worktrees.")


__all__ = ["app"]


if __name__ == "__main__":
    app()
