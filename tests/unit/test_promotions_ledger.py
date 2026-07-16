"""CAL-1114 — the promotion ledger (persistence) + model + PR gate.

The promotion lifecycle (ADR 0003) needs an auditable state record equivalent to
the build run ledger, so an outer orchestrator can pause/resume across command
invocations and the harness can enforce the PR/escalation gates. This module
guards the *library* half of CAL-1114 — the ``Promotion`` model, its
``PromotionStatus`` enum, the sibling ``promotions`` table, and the ``pr``
gate predicate — while ``test_promotion_contract_locked.py`` guards the CLI
JSON contract.

* **AC-1** — a promotion persists to the DB and reads back by promotion id from a
  *fresh connection* (a later invocation reads what an earlier one wrote).
* **AC-3** — ``PromotionStatus`` enumerates the lifecycle states, including the
  clean/pr-ready, agent-may-fix, needs-ticket, blocked, pr-opened, and escalated
  semantics.
* **AC-4** — ``pr_gate_satisfied`` returns True only for a ``pr_ready`` promotion
  carrying fresh gate evidence (a gated SHA).
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

from harness.state import promotions, store
from harness.state.promotions import (
    PROMOTION_STATUSES,
    Promotion,
    PromotionStatus,
    pr_gate_satisfied,
)


def _promotion(**overrides: object) -> Promotion:
    """A minimal valid ``Promotion`` with sensible defaults, overridable per-test."""
    base: dict[str, object] = {
        "promotion_id": "p1",
        "repo": "/repo",
        "from_branch": "dev",
        "to_branch": "staging",
        "status": "opened",
        "created_at": "2026-07-17T00:00:00+00:00",
        "updated_at": "2026-07-17T00:00:00+00:00",
    }
    base.update(overrides)
    return Promotion(**base)  # type: ignore[arg-type]


# --- AC-1: persistence + read-by-id -------------------------------------------


async def test_promotion_persists_and_reads_by_id(tmp_path: Path) -> None:
    """A written promotion reads back by id — across a fresh connection (AC-1)."""
    db = tmp_path / "harness.db"
    promo = _promotion(promotion_branch="promote/p1", worktree_path="/wt/p1")
    await promotions.insert_promotion(promo, db_path=db)

    # A *separate* read — the store re-opens the DB, mirroring a later invocation.
    got = await promotions.read_promotion("p1", db_path=db)
    assert got == promo


async def test_read_unknown_promotion_returns_none(tmp_path: Path) -> None:
    """An id with no row reads back as ``None`` (not an error)."""
    db = tmp_path / "harness.db"
    await promotions.init_promotions(db)
    assert await promotions.read_promotion("nope", db_path=db) is None


async def test_read_missing_db_returns_none(tmp_path: Path) -> None:
    """A read against a DB file that does not exist returns ``None``."""
    assert await promotions.read_promotion("x", db_path=tmp_path / "absent.db") is None


async def test_read_missing_promotions_table_returns_none(tmp_path: Path) -> None:
    """A DB initialised for runs but without the promotions table reads ``None``.

    The sibling table is created lazily by the writers; a read that predates any
    write must degrade to "no such promotion", not raise.
    """
    db = tmp_path / "harness.db"
    await store.init_db(db)  # creates runs/events, not promotions
    assert await promotions.read_promotion("x", db_path=db) is None


async def test_update_promotion_persists_new_state(tmp_path: Path) -> None:
    """``update_promotion`` overwrites the stored row; a re-read reflects it."""
    db = tmp_path / "harness.db"
    await promotions.insert_promotion(_promotion(), db_path=db)

    advanced = _promotion(
        status="pr_ready",
        gated_sha="abc123",
        attempts=1,
        updated_at="2026-07-17T01:00:00+00:00",
    )
    await promotions.update_promotion(advanced, db_path=db)

    got = await promotions.read_promotion("p1", db_path=db)
    assert got is not None
    assert got.status == "pr_ready"
    assert got.gated_sha == "abc123"
    assert got.attempts == 1
    assert got.updated_at == "2026-07-17T01:00:00+00:00"


async def test_init_promotions_is_idempotent(tmp_path: Path) -> None:
    """Initialising the promotions schema twice is a no-op (never raises)."""
    db = tmp_path / "harness.db"
    await promotions.init_promotions(db)
    await promotions.init_promotions(db)
    await promotions.insert_promotion(_promotion(), db_path=db)
    assert await promotions.read_promotion("p1", db_path=db) is not None


# --- AC-3: the lifecycle-status enum ------------------------------------------

#: The promotion lifecycle states (ADR 0003). ``opened`` is the initial state;
#: ``pr_opened`` / ``escalated`` are the two terminal paths; ``cancelled`` is the
#: withdrawn/superseded record. The middle four are the policy classifications a
#: merge+gate attempt returns.
_EXPECTED_STATUSES = {
    "opened",
    "pr_ready",
    "agent_may_fix",
    "needs_ticket",
    "blocked",
    "pr_opened",
    "escalated",
    "cancelled",
}


def test_promotion_status_enum_is_the_locked_set() -> None:
    """``PromotionStatus`` holds exactly the ADR-0003 lifecycle states (AC-3)."""
    assert set(get_args(PromotionStatus)) == _EXPECTED_STATUSES
    assert frozenset(_EXPECTED_STATUSES) == PROMOTION_STATUSES


def test_promotion_status_includes_ac3_semantics() -> None:
    """AC-3 names six required semantics; each is a member of the enum."""
    for semantic in (
        "pr_ready",  # clean / pr-ready
        "agent_may_fix",
        "needs_ticket",
        "blocked",
        "pr_opened",
        "escalated",
    ):
        assert semantic in PROMOTION_STATUSES


# --- AC-4: the PR gate predicate ----------------------------------------------


def test_pr_gate_satisfied_only_for_pr_ready_with_gated_sha() -> None:
    """The PR gate passes only for ``pr_ready`` + a gated SHA (AC-4)."""
    assert pr_gate_satisfied(_promotion(status="pr_ready", gated_sha="deadbeef"))


def test_pr_gate_rejects_pr_ready_without_gated_sha() -> None:
    """A ``pr_ready`` promotion with no gate evidence does not satisfy the gate."""
    assert not pr_gate_satisfied(_promotion(status="pr_ready", gated_sha=None))


def test_pr_gate_rejects_non_pr_ready_even_with_gated_sha() -> None:
    """A gated SHA alone is not enough — the status must be ``pr_ready``."""
    assert not pr_gate_satisfied(_promotion(status="opened", gated_sha="deadbeef"))
    assert not pr_gate_satisfied(_promotion(status="agent_may_fix", gated_sha="x"))
