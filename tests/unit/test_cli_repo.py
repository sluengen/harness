"""Tests for the verbs' shared ``--repo`` / ``--db`` helpers (``harness.cli._repo``).

The lifecycle verbs (``start`` / ``review`` / ``close``) share one repo-root db
default: a ``--db`` flag overriding ``$repo_root/.harness/harness.db``. This
default is the verb (write-side) analogue of the read-side
``_query_common._resolve_db_path`` de-duped in CAL-668; it lives in ``_repo``
because the verb default is repo-root-relative, not cwd-relative.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from harness.cli._repo import resolve_verb_db_path
from harness.state import store


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_resolve_verb_db_path_defaults_under_repo_root() -> None:
    """With no ``--db``, the path is ``repo_root / DEFAULT_DB_PATH``."""
    repo_root = Path("/tmp/some-repo")

    assert resolve_verb_db_path(None, repo_root) == repo_root / store.DEFAULT_DB_PATH


def test_resolve_verb_db_path_walks_up_from_a_worktree_to_the_main_checkout(
    tmp_path: Path,
) -> None:
    """A ``--repo`` pointing at a linked worktree resolves the ledger under the
    *main checkout*, not the worktree (#179).

    ``harness start`` always writes the ``runs`` row under the main checkout's
    ``.harness/`` — a worktree it creates never gets its own. A later verb
    invoked with ``--repo <worktree>`` (or run with CWD inside one, per
    ``commands/harness.md`` Step 1) must resolve the same ledger path the run
    was opened against, or it reports a false "no open run found".
    """
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "dev")
    _git(main, "commit", "-q", "--allow-empty", "-m", "init")
    worktree = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", str(worktree), "-b", "feature")

    assert (
        resolve_verb_db_path(None, worktree)
        == main.resolve() / store.DEFAULT_DB_PATH
    )


def test_resolve_verb_db_path_unaffected_for_a_non_worktree_path(
    tmp_path: Path,
) -> None:
    """A plain (non-git, or main-checkout) ``repo_root`` behaves exactly as
    before — the worktree walk-up is a no-op outside a linked worktree."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()

    assert resolve_verb_db_path(None, plain) == plain / store.DEFAULT_DB_PATH


def test_resolve_verb_db_path_honours_explicit_db() -> None:
    """An explicit ``--db`` is returned unchanged, ignoring ``repo_root``."""
    explicit = Path("/var/data/custom.db")
    repo_root = Path("/tmp/some-repo")

    assert resolve_verb_db_path(explicit, repo_root) is explicit


def test_verbs_share_one_resolve_verb_db_path() -> None:
    """``start`` / ``review`` / ``close`` bind the one shared helper, not copies.

    Mirrors the CAL-668 single-source guard for the read-side resolver: each
    verb imports ``resolve_verb_db_path`` from ``_repo`` so the resolution logic
    cannot drift per verb.
    """
    from harness.cli import _repo, close, review, start

    assert start.resolve_verb_db_path is _repo.resolve_verb_db_path
    assert review.resolve_verb_db_path is _repo.resolve_verb_db_path
    assert close.resolve_verb_db_path is _repo.resolve_verb_db_path
