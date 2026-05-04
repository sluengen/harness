"""CLI entrypoint — see SPEC §11.

The CLI is the public contract. Stable flags, stable exit codes, stable JSON output.

Per-workflow subcommand generation: at invocation, the CLI loads the workflow YAML,
reads its `inputs:` block, and dynamically generates the appropriate Typer subcommand
flags and positional arguments. The workflow IS the CLI definition for its own
subcommand.

Exit codes:
- 0   workflow completed successfully
- 1   workflow failed (caught error during execution)
- 2   invocation error (bad flags, missing config, workflow YAML invalid)
- 3   contract violation (LLM output failed validation after exhausting retries)
- 4   paused awaiting decision (v2)
- 130 SIGINT
"""

from __future__ import annotations

import typer

from harness import __version__

app = typer.Typer(
    help="Deterministic workflow execution harness — see SPEC.md",
    no_args_is_help=True,
)


@app.command()
def version(json_output: bool = typer.Option(False, "--json")) -> None:
    """Print harness version."""
    if json_output:
        typer.echo(f'{{"version": "{__version__}"}}')
    else:
        typer.echo(f"calibrate-harness {__version__}")


if __name__ == "__main__":
    app()
