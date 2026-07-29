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

Recorded decision — ``LedgerNotFoundError`` vs. ``None`` (#244)
------------------------------------------------------------
A missing ``db_path`` used to resolve to the same ``None`` as "the ledger was
read and holds no matching open row" — so every caller rendered both as
``no open run found for worktree ...``, hiding the real cause when the
resolved root has no ledger at all (most often working-directory drift: a verb
invoked outside the repo that opened the run). :class:`LedgerNotFoundError` gives
that case its own, distinct representation, raised in place of the old
``return None`` — every caller inherits the fix through the shared
:class:`~harness.cli._verb.VerbError` handling in :func:`harness.cli._verb.run_verb`,
with no per-verb edit needed.
"""

from __future__ import annotations

from pathlib import Path

from harness.cli._verb import VerbError
from harness.state import store

#: The stable ``reason`` tag for :class:`LedgerNotFoundError` — the ``no open run
#: found`` case keeps its own per-verb reason (or none), so this tag can never
#: collide with it (#244 AC-3).
LEDGER_NOT_FOUND_REASON = "no_ledger"


class LedgerNotFoundError(VerbError):
    """No ledger file at the resolved path — the lookup never happened."""

    def __init__(self, db_path: Path, repo_root: Path) -> None:
        super().__init__(
            f"no harness ledger at {db_path} (resolved from repo root {repo_root}) "
            f"— no run could be looked up; run the verb from the repo that owns "
            f"the run, or pass --repo / --db",
            2,
            reason=LEDGER_NOT_FOUND_REASON,
            extra={"ledger_path": str(db_path)},
        )

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
    open run is matched by ``worktree_path`` equal to ``repo_root``.

    Raises :class:`LedgerNotFoundError` when ``db_path`` does not exist — distinct
    from a ``None`` return, which means the ledger was read but held no
    matching open row (#244).
    """
    if not db_path.exists():
        raise LedgerNotFoundError(db_path, repo_root)

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
