"""Shared ledger-abandon transaction — flip an in-flight run to ``cancelled``.

``harness cancel`` and ``harness reclaim`` perform the *identical* local-ledger
reconciliation: in one transaction, mark an in-flight run ``status='cancelled'``
+ stamp ``completed_at`` **and** append a ``workflow_failed`` audit event. They
differ only in the recorded ``reason`` — ``'cancelled'`` for an abandon,
``'reclaimed'`` for a reclamation revert. Housing the transaction here (rather
than duplicating it across the two verbs) keeps both writing the ledger the same
way, so a change to the consistency rule lands in one place.

The status flip and the event must land **together**: a run marked ``cancelled``
with no ``workflow_failed`` event is an inconsistent ledger that retry cannot
repair (a terminal run refuses re-abandon). So both writes share one transaction
— commit once, or roll back together.

The cancellable set is an explicit **allowlist**, not a terminal denylist: an
unknown or future status is *refused*, never silently overwritten to
``cancelled``.
"""

from __future__ import annotations

import aiosqlite

from harness.events.payloads import WorkflowFailedEventData
from harness.events.schema import EVENT_TYPES
from harness.state.schema import RUN_STATUSES

__all__ = [
    "ABANDON_EVENT_TYPE",
    "CANCELLABLE_STATUSES",
    "AbandonError",
    "abandon_run_in_ledger",
]

#: In-flight statuses a run can be abandoned *from* — an explicit allowlist. The
#: verb model only ever writes ``open``; the rest are legacy engine / intake
#: states that may still appear on historical rows. An allowlist means an unknown
#: or future status is **refused**, never silently overwritten.
CANCELLABLE_STATUSES: frozenset[str] = frozenset(
    {"open", "running", "pending", "paused", "stalled"}
)
# The allowlist must stay a subset of the canonical run-status set.
assert CANCELLABLE_STATUSES <= RUN_STATUSES

#: The abandonment event. ``workflow_failed`` (carrying ``reason``) is the
#: canonical mark (a member of :data:`EVENT_TYPES`) that ``harness status`` reads
#: to surface ``failure_reason``.
ABANDON_EVENT_TYPE = "workflow_failed"
assert ABANDON_EVENT_TYPE in EVENT_TYPES  # guard against a future rename drift


class AbandonError(Exception):
    """Internal control-flow exception carrying a message and an exit code."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


async def abandon_run_in_ledger(
    conn: aiosqlite.Connection,
    run_id: str,
    *,
    reason: str,
    completed_at: str,
    event_ts: str,
) -> None:
    """Flip the in-flight run ``run_id`` to ``cancelled`` + emit its abandon event.

    Performed in **one transaction** on the caller-owned ``conn`` (the caller owns
    the connection so a verb can sequence other side effects around it). On the
    happy path the run moves ``in-flight → cancelled``, ``completed_at`` is
    stamped, and a ``workflow_failed`` event with ``data.reason == reason`` is
    appended.

    Raises:
        AbandonError: with exit code ``2`` when the run is missing, already
            terminal, has an unrecognised status, or changed state concurrently;
            with exit code ``1`` when the event write fails (the status flip is
            rolled back, so the run stays abandonable on retry).
    """
    event_data = WorkflowFailedEventData(reason=reason).model_dump_json()

    await conn.execute("BEGIN IMMEDIATE")
    try:
        cur = await conn.execute(
            "SELECT status FROM runs WHERE run_id = ?", (run_id,)
        )
        row = await cur.fetchone()
        if row is None:
            raise AbandonError(f"no run with run_id={run_id!r}", 2)

        status = str(row[0])
        if status not in CANCELLABLE_STATUSES:
            # Refuse anything not on the allowlist. Distinguish a known terminal
            # run from an unrecognised status for a clearer message, but never
            # overwrite either.
            if status in RUN_STATUSES:
                raise AbandonError(
                    f"run {run_id!r} is already terminal (status={status!r}); "
                    "only an in-flight run can be abandoned",
                    2,
                )
            raise AbandonError(
                f"run {run_id!r} has an unrecognised status {status!r}; "
                "refusing to abandon",
                2,
            )

        # Guard the transition on the exact status we observed — optimistic
        # concurrency. If a close/cancel raced in between the read above and
        # here, the status differs and zero rows change: refuse rather than
        # overwrite a terminal state.
        update = await conn.execute(
            "UPDATE runs SET status = 'cancelled', completed_at = ? "
            "WHERE run_id = ? AND status = ?",
            (completed_at, run_id, status),
        )
        if update.rowcount == 0:
            raise AbandonError(
                f"run {run_id!r} changed state concurrently; only an in-flight "
                "run can be abandoned",
                2,
            )

        # Append the abandonment event in the same transaction (mirrors
        # EventEmitter's INSERT; inlined here so it shares the commit).
        await conn.execute(
            "INSERT INTO events (run_id, node_id, event_type, timestamp, "
            "duration_ms, data_json) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, None, ABANDON_EVENT_TYPE, event_ts, None, event_data),
        )
        await conn.commit()
    except AbandonError:
        await conn.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        await conn.rollback()
        raise AbandonError(f"failed to record abandonment: {exc}", 1) from exc
