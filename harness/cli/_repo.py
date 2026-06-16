"""Shared ``--repo`` / ``--db`` resolution for the verbs (CAL-584).

Each verb (``start`` / ``review`` / ``close``) resolves ``--repo`` through this
single adapter so the ``HARNESS_WORKSPACE_ROOTS`` allowlist check is identical
across them. The adapter wraps :func:`harness.workspace.resolve_repo_root` and
translates a rejection into the CLI's invocation-refusal contract: a stderr
message naming the rejected path and the configured roots, and exit code 2.

:func:`resolve_verb_db_path` is the matching one-home for the verbs' ``--db``
default — the write-side analogue of ``_query_common._resolve_db_path``.
"""

from __future__ import annotations

from pathlib import Path

import typer

from harness.state import store
from harness.workspace import WorkspaceNotAllowed, resolve_repo_root


def resolve_repo_root_or_exit(repo: Path) -> Path:
    """Resolve and allowlist-check ``repo``; exit 2 with a stderr message on refusal."""
    try:
        return resolve_repo_root(repo)
    except WorkspaceNotAllowed as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc


def resolve_verb_db_path(db: Path | None, repo_root: Path) -> Path:
    """Either the explicit ``--db`` or the default ``$repo_root/.harness/harness.db``.

    The verbs' write-side analogue of the read-side
    ``_query_common._resolve_db_path``: same one-flag-overrides-default shape, but
    the verb default is anchored under the resolved ``repo_root`` rather than the
    current working directory. One home so ``start`` / ``review`` / ``close`` cannot
    drift apart.
    """
    if db is not None:
        return db
    return repo_root / store.DEFAULT_DB_PATH
