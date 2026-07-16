"""Promotion ledger — the promotion lifecycle's auditable state record (CAL-1114).

Promotion is a first-class, audited harness lifecycle over the universal
``dev → staging → main`` topology ([ADR 0003](../../specs/decisions/0003-promotion-lifecycle.md)).
Where the build run ledger (:mod:`harness.state.store`) records a *ticket's*
integration into ``dev``, this records a *promotion's* movement toward release:
one row per promotion, read back by promotion id so an outer orchestrator can
pause after the harness classifies a merge+gate attempt and resume by re-reading
the state it left.

The promotion state lives in the same per-project SQLite DB
(``.harness/harness.db``) as the run ledger, in a **sibling ``promotions``
table** — the run ledger's ``runs``/``events`` tables are untouched, so the two
lifecycles cannot weaken each other (ADR 0003, "distinct from the build-run
close gate"). Each row stores the whole :class:`Promotion` as a JSON blob keyed
by ``promotion_id``; the model is the single source of the shape and validates on
read. A denormalized ``status`` column is kept alongside so a future "find the
open promotion" query need not scan every blob.

This module is CAL-1114's **library** half — the model, the enum, the
persistence, and the PR gate predicate. The CLI JSON contract that surfaces them
(``harness promote status`` / ``pr``) lives in :mod:`harness.cli.promote`, and the
worktree/merge mechanics that *create* promotions land in CAL-1115.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, get_args

import aiosqlite
from pydantic import BaseModel, ConfigDict

from harness.state import store

__all__ = [
    "PROMOTION_STATUSES",
    "Promotion",
    "PromotionStatus",
    "init_promotions",
    "insert_promotion",
    "pr_gate_satisfied",
    "read_promotion",
    "update_promotion",
]


# The promotion lifecycle states (ADR 0003). ``opened`` is the initial state once
# the row/worktree/branch exist and the merge has been attempted; the middle four
# (``pr_ready`` / ``agent_may_fix`` / ``needs_ticket`` / ``blocked``) are the
# policy classifications a merge+gate attempt returns; ``pr_opened`` and
# ``escalated`` are the two terminal paths; ``cancelled`` records a withdrawn or
# superseded promotion (recorded, never deleted). The blob column is plain
# ``TEXT`` without a CHECK constraint, so this Literal is the type-safe seam.
PromotionStatus = Literal[
    "opened",
    "pr_ready",
    "agent_may_fix",
    "needs_ticket",
    "blocked",
    "pr_opened",
    "escalated",
    "cancelled",
]

PROMOTION_STATUSES: frozenset[str] = frozenset(get_args(PromotionStatus))
"""Runtime view of the canonical promotion statuses — derived from
:data:`PromotionStatus` so the two cannot drift."""


class Promotion(BaseModel):
    """One promotion's full lifecycle state — the row stored in ``promotions``.

    The fields expose enough for an outer orchestrator to branch without scraping
    text (ADR 0003): the branch endpoints and the promotion branch, the current
    ``status``, the ``merged_sha`` a clean merge records (CAL-1115) and the
    ``gated_sha`` the PR gate reads, the bounded repair ``attempts`` count, the
    terminal ``pr_url`` / ``escalation_ticket``, and a bounded ``evidence``
    reference (e.g. the captured gate-log path). ``repo`` / ``worktree_path`` name
    where to inspect the promotion.

    ``extra="forbid"`` so a writer that hallucinates an unknown field is rejected
    rather than silently persisted (the same discipline as ``BaseState``).
    """

    model_config = ConfigDict(extra="forbid")

    promotion_id: str
    repo: str
    from_branch: str
    to_branch: str
    status: PromotionStatus
    created_at: str
    updated_at: str
    worktree_path: str | None = None
    promotion_branch: str | None = None
    merged_sha: str | None = None
    gated_sha: str | None = None
    attempts: int = 0
    pr_url: str | None = None
    escalation_ticket: str | None = None
    evidence: str | None = None


def pr_gate_satisfied(promotion: Promotion) -> bool:
    """The promotion PR gate: may a PR be opened for this promotion? (AC-4)

    True only when the promotion is ``pr_ready`` **and** carries fresh gate
    evidence — a ``gated_sha`` — mirroring the ``review``/``close`` gate's
    evidence discipline (a promotion cannot reach ``pr_ready`` without a green
    gate, ADR 0003). ``harness promote pr`` refuses when this returns False, so
    PR creation is impossible from any other state or without a gated SHA.
    """
    return promotion.status == "pr_ready" and bool(promotion.gated_sha)


# ---------------------------------------------------------------------------
# Persistence — a sibling table in the run ledger's DB.
# ---------------------------------------------------------------------------

# Idempotent — ``CREATE ... IF NOT EXISTS``. Re-running is a no-op. The row is the
# ``Promotion`` JSON blob keyed by id; ``status`` is denormalized for querying.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS promotions (
  promotion_id  TEXT PRIMARY KEY,
  status        TEXT NOT NULL,
  data_json     TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_promotions_status ON promotions(status);
"""


async def init_promotions(db_path: Path) -> None:
    """Create the ``promotions`` table + index if absent. Idempotent.

    Reuses :func:`store.connect` so the promotion table lives in the same
    per-project DB with the same WAL + foreign-key PRAGMAs as the run ledger.
    """
    async with store.connect(db_path) as conn:
        await conn.executescript(_SCHEMA)
        await conn.commit()


async def insert_promotion(promotion: Promotion, *, db_path: Path) -> None:
    """Insert a new promotion row (creating the table on first write)."""
    await init_promotions(db_path)
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO promotions (promotion_id, status, data_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (
                promotion.promotion_id,
                promotion.status,
                promotion.model_dump_json(),
                promotion.updated_at,
            ),
        )
        await conn.commit()


async def read_promotion(promotion_id: str, *, db_path: Path) -> Promotion | None:
    """Return the :class:`Promotion` for ``promotion_id``, or ``None`` if absent.

    Degrades to ``None`` — never raises — for the two "nothing written yet" cases
    a later invocation legitimately hits: a DB file that does not exist, and a DB
    initialised for runs but without the promotions table (no promotion has been
    created). Every other read failure propagates.
    """
    if not db_path.exists():
        return None
    try:
        async with (
            store.connect(db_path) as conn,
            conn.execute(
                "SELECT data_json FROM promotions WHERE promotion_id = ?",
                (promotion_id,),
            ) as cur,
        ):
            row = await cur.fetchone()
    except aiosqlite.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return None
        raise
    if row is None:
        return None
    return Promotion.model_validate_json(row[0])


async def update_promotion(promotion: Promotion, *, db_path: Path) -> None:
    """Overwrite the stored row for ``promotion.promotion_id`` with new state."""
    await init_promotions(db_path)
    async with store.connect(db_path) as conn:
        await conn.execute(
            "UPDATE promotions SET status = ?, data_json = ?, updated_at = ? "
            "WHERE promotion_id = ?",
            (
                promotion.status,
                promotion.model_dump_json(),
                promotion.updated_at,
                promotion.promotion_id,
            ),
        )
        await conn.commit()
