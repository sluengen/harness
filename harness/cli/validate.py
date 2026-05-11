"""``harness validate <workflow.yaml>`` — static workflow validation.

Delegates to :func:`harness.workflow.loader.load_workflow`. The loader runs
every load-time check (schema validation, contract compilation, writes-against-
contract, writer-type-consistency, worktree-ancestry, decision-actor,
writes-without-contract). On success this command prints a one-line OK with
the workflow name + version and exits 0. On failure it prints the
:class:`WorkflowLoadError` message and exits 2 (per SPEC §11 exit code 2 ==
invocation / config error).
"""

from __future__ import annotations

from pathlib import Path

import typer

from harness.workflow.loader import WorkflowLoadError, load_workflow


def validate_command(
    workflow: Path = typer.Argument(
        ..., exists=False, help="Workflow YAML file to validate."
    ),
) -> None:
    """Validate a workflow YAML file. Exits 0 on success, 2 on failure."""
    if not workflow.exists():
        typer.echo(f"workflow file not found: {workflow}", err=True)
        raise typer.Exit(code=2)

    try:
        loaded = load_workflow(workflow)
    except WorkflowLoadError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(f"OK {loaded.workflow.name} v{loaded.workflow.version}")
