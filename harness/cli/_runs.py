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

:func:`read_run_resumed_from` sits here for the same reason as the resolver: two
inherit paths now gate on it — ``design``'s adopt (#258) and ``review``'s
inherited pass (#259) — and "did this run resume?" is a shared run-row rule, not
either verb's private one. It arrived with the design verb and moved here when the
second reader appeared; a review-path module reaching into ``design_tracker`` for
it would read as coupling that is not there, and a second copy is how two paths
start disagreeing about what *resumed* means.

:func:`attendance_inputs_json` / :func:`resolve_attended` sit here for that same
reason, one step earlier (#295, ADR 0011). "Is this run attended?" is a shared
run-row rule with two readers already specified — ``review``'s wall-clock
breaker (#296) and ``reclaim --stale``'s threshold selection (#297) — and the
writer (``start``'s insert) lives with them so the key's spelling cannot drift
between the side that records the mode and the sides that act on it. They are a
*pure* pair over the column's value rather than a DB reader, because both
consumers already project run rows for their own reasons and need the rule, not
another query.

:func:`read_run_assurance` is the third of the same kind (#352). "What assurance
level is this run under?" has two readers — ``design`` (is the stage required at
all?) and ``review`` (may it proceed without one?) — and the answer must be the
snapshot ``start`` wrote, never a re-read of the issue's labels, or a label
edited mid-run would change the stages a run is required to pay for after it
opened. The *policy* it reads through lives in :mod:`harness.assurance`, which is
pure; this is the one query that fetches its input.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.assurance import DEFAULT_ASSURANCE, Assurance, coerce_assurance
from harness.cli._verb import VerbError
from harness.state import store

#: The stable ``reason`` tag for :class:`LedgerNotFoundError` — the ``no open run
#: found`` case keeps its own per-verb reason (or none), so this tag can never
#: collide with it (#244 AC-3).
LEDGER_NOT_FOUND_REASON = "no_ledger"

#: The one key ``inputs_json`` carries under the verb model (#295, ADR 0011).
#: Spelled once, next to both the writer and the reader, so the two cannot drift.
ATTENDED_KEY = "attended"

#: What ``start`` has always inserted, and still inserts for an undeclared run.
#: Byte-identical is the point: every row written before #295 already means
#: *unattended*, so there is no backfill and ``"{}"`` gains no second meaning.
UNATTENDED_INPUTS_JSON = "{}"


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


def attendance_inputs_json(attended: bool) -> str:
    """The ``inputs_json`` value for a declared attendance mode (#295).

    ``start``'s only writer. Pairs with :func:`resolve_attended` — keeping the
    two together is why they live here rather than in ``start``: the readers
    (#296 ``review``, #297 ``reclaim --stale``) must agree with the writer about
    the key's spelling, and a second copy is how that agreement breaks.
    """
    return json.dumps({ATTENDED_KEY: True}) if attended else UNATTENDED_INPUTS_JSON


def resolve_attended(inputs_json: str | None) -> bool:
    """Whether a run row declared itself attended (#295, ADR 0011).

    Total by construction — it never raises, and *unattended* is both the
    default and the failure default. Only the literal JSON ``true`` declares
    attendance: a string ``"true"``, a ``1``, a non-object document, unparseable
    text and an absent column all resolve unattended.

    That strictness is deliberate rather than defensive. Declaring attendance
    opts a run out of the wall clock, which is the only ceiling on autonomous
    spend, so every ambiguous value must fail *toward* the bound. A corrupted or
    hand-edited ledger can then only ever make a run more bounded, never less.

    The parse failure is swallowed on purpose, and this is the honest trade: the
    alternative is ``review`` and the ``--stale`` sweep raising over a column
    that carried no meaning until #295, wedging a verb (and, in the sweep, a
    whole tick) on a value nothing has ever validated. It is not hidden either —
    ``harness status --json`` already parses this column and surfaces it as
    ``inputs``, so a malformed value is visible where a human would look.
    """
    try:
        data = json.loads(inputs_json) if inputs_json else None
    except (TypeError, ValueError):
        return False
    return isinstance(data, dict) and data.get(ATTENDED_KEY) is True


async def read_run_resumed_from(db_path: Path, run_id: str) -> str | None:
    """The preserved WIP branch this run resumed from, or ``None`` (#258).

    ADR 0008's F2 gate, read off the run row ``start`` wrote. ``None`` covers
    both a clean start and a ``--resume`` that fell back — in either case the
    tree a prior design described is not what this worktree holds, so there is
    nothing to inherit.
    """
    if not db_path.exists():
        return None
    async with (
        store.connect(db_path) as conn,
        conn.execute("SELECT resumed_from FROM runs WHERE run_id = ?", (run_id,)) as cur,
    ):
        row = await cur.fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0])


async def read_run_assurance(db_path: Path, run_id: str) -> Assurance:
    """The assurance level this run was opened under (#352).

    ``start`` resolves the issue's labels once and snapshots the answer on the
    row; every later verb reads it from here rather than re-reading labels, so a
    label edited mid-run cannot retroactively change the stages the run is
    required to pay for.

    Total, and falls back to :data:`~harness.assurance.DEFAULT_ASSURANCE` in one
    direction: a ledger that does not exist, a run row that is not there, a
    ``NULL`` column on a row written before the migration, or a value outside the
    vocabulary all read as ``simple`` — the level that still requires a review.
    A damaged or absent snapshot can therefore only make a run *more* verified,
    never less, which is the same posture :func:`resolve_attended` takes. The
    ``no_ledger`` refusal is not restated here: every caller resolves its run
    through :func:`resolve_open_run` first, which owns it.
    """
    if not db_path.exists():
        return DEFAULT_ASSURANCE
    async with (
        store.connect(db_path) as conn,
        conn.execute("SELECT assurance FROM runs WHERE run_id = ?", (run_id,)) as cur,
    ):
        row = await cur.fetchone()
    if row is None:
        return DEFAULT_ASSURANCE
    return coerce_assurance(row[0])
