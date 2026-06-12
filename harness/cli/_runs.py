"""Shared open-run resolution for the verbs (CAL-631).

``review`` and ``close`` both answer the same question — "which ``runs`` row is
the active run for this invocation?" — with the identical dispatch rule: an
explicit ``run_id`` matches ``WHERE run_id = ? AND status = 'open'``, otherwise
the run is the one whose ``worktree_path`` equals the resolved repo. The
``status = 'open'`` filter is the load-bearing part: it is the close gate's
contract that a verb only ever acts on a live run, and it must stay identical
across verbs. This module is the one home for that rule — it previously lived as
near-identical copies in ``review.py`` and ``close.py`` that could drift apart.

The resolver projects the four-column superset both verbs need (``close`` uses
all four, ``review`` the first two) so the query column list stays a fixed
literal — no per-caller column interpolation, hence no string-built SQL.
"""

from __future__ import annotations

from pathlib import Path

from harness.state import store

# The columns both verbs need: close consumes all four, review the first two.
# Kept as plain string literals (no interpolation) so there is no string-built
# SQL — the only per-call variation is the bound ``?`` parameter.
_SELECT_BY_RUN_ID = (
    "SELECT run_id, worktree_path, base_branch, worktree_branch "
    "FROM runs WHERE run_id = ? AND status = 'open'"
)
_SELECT_BY_WORKTREE = (
    "SELECT run_id, worktree_path, base_branch, worktree_branch "
    "FROM runs WHERE worktree_path = ? AND status = 'open'"
)


async def resolve_open_run(
    db_path: Path,
    repo_root: Path,
    run_id: str | None,
) -> tuple[str, str, str, str] | None:
    """Return ``(run_id, worktree_path, base_branch, worktree_branch)`` for the
    open run, or ``None``.

    With an explicit ``run_id`` the row must be ``status='open'``.  Otherwise the
    open run is matched by ``worktree_path`` equal to ``repo_root``.  A missing
    ``db_path`` (no run ever started here) resolves to ``None``.
    """
    if not db_path.exists():
        return None

    if run_id is not None:
        query = _SELECT_BY_RUN_ID
        params: tuple[str, ...] = (run_id,)
    else:
        query = _SELECT_BY_WORKTREE
        params = (str(repo_root),)

    async with store.connect(db_path) as conn, conn.execute(query, params) as cur:
        row = await cur.fetchone()

    if row is None:
        return None
    return str(row[0]), str(row[1]), str(row[2]), str(row[3])
