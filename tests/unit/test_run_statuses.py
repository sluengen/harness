"""Tests for the ``RunStatus`` literal / ``RUN_STATUSES`` frozenset — CAL-583.

The verb model writes ``runs.status = "open"`` (``harness start``) and
``runs.status = "closed"`` (``harness close``). These tests pin that the
type-safe seam (:data:`RUN_STATUSES`) admits those lifecycle values, and that
a status round-tripped through a ``runs`` row written exactly as the verbs
write it validates against the frozenset.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

from harness.state import store
from harness.state.schema import RUN_STATUSES, RunStatus


def test_run_statuses_includes_verb_lifecycle() -> None:
    """``open`` and ``closed`` (verb model) are members of the frozenset."""
    assert "open" in RUN_STATUSES
    assert "closed" in RUN_STATUSES


def test_run_statuses_retains_legacy_engine_statuses() -> None:
    """Reconciling the verb statuses must not drop the legacy engine ones
    (removing them is explicitly out of scope for CAL-583)."""
    for legacy in (
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
        "stalled",
        "paused",
    ):
        assert legacy in RUN_STATUSES


def test_run_statuses_derived_from_literal() -> None:
    """The frozenset stays the runtime view of the Literal — no drift."""
    assert frozenset(get_args(RunStatus)) == RUN_STATUSES


async def test_status_written_by_start_and_close_validates(tmp_path: Path) -> None:
    """A status read back from a row written exactly as ``start``/``close``
    write it is a member of ``RUN_STATUSES``."""
    db_path = tmp_path / "harness.db"
    await store.init_db(db_path)

    async with store.connect(db_path) as conn:
        # mirror harness/cli/start.py: insert a status='open' row
        await conn.execute(
            "INSERT INTO runs ("
            "run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, started_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("01RUN", "", 0, "open", "{}", "{}", "2026-06-11T00:00:00Z"),
        )
        # mirror harness/cli/close.py: flip the row to status='closed'
        await conn.execute(
            "UPDATE runs SET status = ? WHERE run_id = ?",
            ("closed", "01RUN"),
        )
        await conn.commit()

        async with conn.execute(
            "SELECT status FROM runs WHERE run_id = ?", ("01RUN",)
        ) as cursor:
            row = await cursor.fetchone()

    assert row is not None
    status = row[0]
    assert status == "closed"
    assert status in RUN_STATUSES
