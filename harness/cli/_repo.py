"""Shared ``--repo`` / ``--db`` resolution for the verbs (CAL-584).

Each verb (``start`` / ``review`` / ``close``) resolves ``--repo`` through this
single adapter so the ``HARNESS_WORKSPACE_ROOTS`` allowlist check is identical
across them. The adapter wraps :func:`harness.workspace.resolve_repo_root` and
translates a rejection into the CLI's invocation-refusal contract: a stderr
message naming the rejected path and the configured roots, and exit code 2.

:func:`resolve_verb_db_path` is the matching one-home for the verbs' ``--db``
default — the write-side analogue of ``_query_common._resolve_db_path``. It
resolves through :func:`resolve_ledger_root` so a ``--repo`` pointing at a
linked worktree still finds the ledger ``start`` wrote under the main checkout
(#179) — a worktree created by ``harness start`` never gets its own
``.harness/``.
"""

from __future__ import annotations

from pathlib import Path

import typer

from harness.cli._git import git_common_dir
from harness.state import store
from harness.workspace import NotAGitTopLevel, WorkspaceNotAllowed, resolve_repo_root


def resolve_repo_root_or_exit(repo: Path) -> Path:
    """Resolve, allowlist-check, and repo-root-check ``repo``.

    Exits 2 with the refusal on stderr for either rejection: outside the
    workspace allowlist (:class:`WorkspaceNotAllowed`) or inside it but not a
    git top-level (:class:`NotAGitTopLevel`, #214). Both are invocation
    refusals with the same contract, so they share one exit path — but they
    stay distinct types so each keeps its own accurate message.
    """
    try:
        return resolve_repo_root(repo)
    except (WorkspaceNotAllowed, NotAGitTopLevel) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc


def resolve_ledger_root(repo_root: Path) -> Path:
    """The repo root that owns the run ledger for ``repo_root`` (#179).

    ``harness start`` writes the ``runs`` row under the *main checkout's*
    ``.harness/`` — a worktree it creates (``.worktrees/harness/<run_id>/``)
    never gets its own. Walks up via :func:`harness.cli._git.git_common_dir` —
    the same shared state git itself resolves a worktree against — so a later
    verb invoked with ``--repo`` pointing at that worktree (or run with CWD
    inside one, per ``commands/harness.md`` Step 1) still finds the ledger the
    run was opened against.

    Returns ``repo_root`` unchanged when it is not inside a git worktree —
    the main checkout (``git-common-dir`` is its own ``.git``) and any
    non-git path (test fixtures, an unresolvable ``--repo``) both fall
    through to the pre-existing behaviour.
    """
    common_dir = git_common_dir(repo_root)
    if common_dir is None:
        return repo_root
    return common_dir.parent


def resolve_verb_db_path(db: Path | None, repo_root: Path) -> Path:
    """Either the explicit ``--db`` or the default
    ``$(resolve_ledger_root(repo_root))/.harness/harness.db``.

    The verbs' write-side analogue of the read-side
    ``_query_common._resolve_db_path``: same one-flag-overrides-default shape, but
    the verb default is anchored under the resolved ledger root rather than the
    current working directory. One home so ``start`` / ``review`` / ``close`` cannot
    drift apart.
    """
    if db is not None:
        return db
    return resolve_ledger_root(repo_root) / store.DEFAULT_DB_PATH
