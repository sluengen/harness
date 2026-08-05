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

The explicit repo argument (#306, ADR 0012)
-------------------------------------------
:func:`repo_arg_or_cwd` is the **one** place in ``harness/cli/`` where an
omitted ``--repo`` becomes the current working directory, and therefore the one
place the deprecation warning is emitted. Every command declares its repo
argument with a ``None`` default and passes it through here.

``None`` rather than ``Path(".")`` is load-bearing, not stylistic: with a
``Path(".")`` default a command cannot tell *omitted* from an explicit
``--repo .``, so it would have to warn a caller who did state its intent — which
makes the deprecation unactionable. ``None`` is what makes omission
representable at all.

"Exactly one warning per invocation" is a property of the call graph, not of a
suppression latch: a command enters this seam once, from its command function,
and hands the resolved path down to any helper that needs it. A latch was
rejected — it would silently under-report under an in-process ``CliRunner``, and
would mask a second ambient read rather than expose it.
"""

from __future__ import annotations

from pathlib import Path

import typer

from harness._git import git_common_dir
from harness.state import store
from harness.workspace import NotAGitTopLevel, WorkspaceNotAllowed, resolve_repo_root

#: Stable prefix of the deprecation line, so callers and guards can recognize it
#: without pinning the whole sentence.
IMPLICIT_REPO_WARNING_PREFIX = "warning: no --repo given"

#: The full deprecation warning. One constant, so retiring the implicit form
#: later is a deletion rather than an audit. It interpolates nothing — no path,
#: no token, no ticket content — so it can never leak repo layout into a log.
IMPLICIT_REPO_DEPRECATION = (
    f"{IMPLICIT_REPO_WARNING_PREFIX} — defaulting to the current working "
    "directory. The implicit form is deprecated and will be removed; pass "
    "--repo <path> explicitly (ADR 0012)."
)

#: Help text shared by every command's ``--repo`` declaration.
REPO_OPTION_HELP = (
    "Repo root to act on. Defaults to the current working directory, which is "
    "deprecated and will be removed (ADR 0012)."
)


def repo_arg_or_cwd(repo: Path | None) -> Path:
    """The explicit ``--repo``, or the CWD plus one deprecation warning.

    Written to stderr: stdout carries the JSON contract the orchestrating loop
    parses, and a warning that leaked into it would break ``json.loads`` in
    every caller.
    """
    if repo is not None:
        return repo
    typer.echo(IMPLICIT_REPO_DEPRECATION, err=True)
    return Path.cwd()


def resolve_repo_argument(repo: Path | None) -> Path:
    """:func:`repo_arg_or_cwd` then :func:`resolve_repo_root_or_exit`.

    The one call the enforcing verbs make: warn-if-omitted, then allowlist- and
    git-top-level-check. Two steps rather than one function so the commands that
    deliberately do *not* enforce the allowlist today (the read and ops
    commands) can take the first half without acquiring the second — enforcing
    it there would refuse every native invocation with no
    ``HARNESS_WORKSPACE_ROOTS`` set, a behaviour change the implicit path must
    not have.
    """
    return resolve_repo_root_or_exit(repo_arg_or_cwd(repo))


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
    never gets its own. Walks up via :func:`harness._git.git_common_dir` —
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
