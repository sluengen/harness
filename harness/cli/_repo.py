"""Shared ``--repo`` acceptance for the verbs (CAL-584).

Each verb (``start`` / ``review`` / ``close``) resolves ``--repo`` through this
single adapter so the ``HARNESS_WORKSPACE_ROOTS`` allowlist check is identical
across them. The adapter wraps :func:`harness.workspace.resolve_repo_root` and
translates a rejection into the CLI's invocation-refusal contract: a stderr
message naming the rejected path and the configured roots, and exit code 2.
"""

from __future__ import annotations

from pathlib import Path

import typer

from harness.workspace import WorkspaceNotAllowed, resolve_repo_root


def resolve_repo_root_or_exit(repo: Path) -> Path:
    """Resolve and allowlist-check ``repo``; exit 2 with a stderr message on refusal."""
    try:
        return resolve_repo_root(repo)
    except WorkspaceNotAllowed as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
