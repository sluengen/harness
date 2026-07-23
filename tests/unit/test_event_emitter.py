"""Tests for harness.events.emitter — append-only event log writer.

See SPEC §4.7 (event types) and ``specs/features/run-ledger.md`` (events table).

CAL-713 pruned the canonical event set to the live-verb-emitter types
(``workflow_failed`` via ``harness cancel``, ``review``, ``close``); CAL-738
added ``checkpoint`` (``harness checkpoint`` — the run-branch push). The
retired deterministic-engine types (CAL-574) are no longer writable — the
emitter validates them out — but historical rows that still carry them read
back unchanged, because readers never re-validate ``event_type``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import aiosqlite
import pytest

from harness.events.emitter import EventEmitter
from harness.events.schema import EVENT_TYPES, EventType
from harness.state import store

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

#: The canonical set — every type a live verb emits. CAL-713 pruned this to the
#: post-engine live set; CAL-738 added ``checkpoint`` (the run-branch push);
#: CAL-1143 added ``defer`` (the audited triage write); #193 added ``release``
#: (the ``/decision`` return write — the ``defer`` shape in reverse).
LIVE_EVENT_TYPES: list[EventType] = [
    "workflow_failed",
    "review",
    "close",
    "checkpoint",
    "defer",
    "release",
]

#: Retired deterministic-engine types (CAL-574). No live code emits these; the
#: emitter now rejects them on write. Kept here as a test fixture so the
#: write-rejection and historical-row-read-back guarantees stay pinned.
_RETIRED_ENGINE_EVENT_TYPES: list[str] = [
    "workflow_started",
    "workflow_completed",
    "workflow_paused",
    "node_started",
    "node_completed",
    "node_failed",
    "tool_called",
    "tool_completed",
    "state_changed",
    "loop_iteration",
    "retry_attempted",
    "decision_requested",
    "decision_made",
    "decision_received",
    "decision_timeout",
    "decision_violation",
]

_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


async def _init_db_with_run(db_path: Path, run_id: str = "R1") -> None:
    """Initialise schema and insert a placeholder ``runs`` row.

    Events have a foreign key to ``runs(run_id)``, so every event-emitter test
    needs a parent run row in place.
    """
    await store.init_db(db_path)
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, "test", 1, "running", "{}", "{}", "2026-05-08T00:00:00Z"),
        )
        await conn.commit()


async def _fetch_all_events(db_path: Path) -> list[dict[str, object]]:
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT id, run_id, node_id, event_type, timestamp, duration_ms, "
            "data_json FROM events ORDER BY id"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Round-trip — every live event type writes and reads back
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event_type", LIVE_EVENT_TYPES)
async def test_emit_round_trips_every_live_event_type(
    tmp_path: Path, event_type: EventType
) -> None:
    db_path = tmp_path / "harness.db"
    await _init_db_with_run(db_path)
    emitter = EventEmitter(db_path)

    await emitter.emit(
        run_id="R1",
        event_type=event_type,
        node_id="step-1",
        data={"k": "v"},
        duration_ms=42,
    )

    rows = await _fetch_all_events(db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"] == "R1"
    assert row["event_type"] == event_type
    assert row["node_id"] == "step-1"
    assert row["duration_ms"] == 42
    assert json.loads(str(row["data_json"])) == {"k": "v"}


def test_canonical_set_is_exactly_the_live_types() -> None:
    """``EVENT_TYPES`` enumerates only types a live verb emits (CAL-713)."""
    assert frozenset(LIVE_EVENT_TYPES) == EVENT_TYPES


# ---------------------------------------------------------------------------
# Defaults — None args persist as expected
# ---------------------------------------------------------------------------


async def test_emit_defaults_data_to_empty_json_object(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    await _init_db_with_run(db_path)
    emitter = EventEmitter(db_path)

    await emitter.emit(run_id="R1", event_type="review")

    rows = await _fetch_all_events(db_path)
    assert len(rows) == 1
    assert json.loads(str(rows[0]["data_json"])) == {}


async def test_emit_stores_node_id_and_duration_as_null_when_missing(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "harness.db"
    await _init_db_with_run(db_path)
    emitter = EventEmitter(db_path)

    await emitter.emit(run_id="R1", event_type="review")

    rows = await _fetch_all_events(db_path)
    assert rows[0]["node_id"] is None
    assert rows[0]["duration_ms"] is None


# ---------------------------------------------------------------------------
# Timestamp format — ISO-8601 UTC with trailing Z
# ---------------------------------------------------------------------------


async def test_emit_writes_iso8601_utc_timestamp_with_z_suffix(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    await _init_db_with_run(db_path)
    emitter = EventEmitter(db_path)

    await emitter.emit(run_id="R1", event_type="review")

    rows = await _fetch_all_events(db_path)
    timestamp = str(rows[0]["timestamp"])
    assert _TIMESTAMP_RE.match(timestamp), (
        f"timestamp {timestamp!r} does not match ISO-8601 UTC with Z suffix"
    )


# ---------------------------------------------------------------------------
# Append order — multiple emits append in monotonic id order
# ---------------------------------------------------------------------------


async def test_emit_appends_in_monotonic_id_order(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    await _init_db_with_run(db_path)
    emitter = EventEmitter(db_path)

    await emitter.emit(run_id="R1", event_type="review", node_id="s1")
    await emitter.emit(run_id="R1", event_type="review", node_id="s2")
    await emitter.emit(run_id="R1", event_type="workflow_failed")
    await emitter.emit(run_id="R1", event_type="close")

    rows = await _fetch_all_events(db_path)
    ids = [int(r["id"]) for r in rows]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))
    assert [r["event_type"] for r in rows] == [
        "review",
        "review",
        "workflow_failed",
        "close",
    ]


# ---------------------------------------------------------------------------
# Validation — non-live event types rejected on write
# ---------------------------------------------------------------------------


async def test_emit_rejects_unknown_event_type(tmp_path: Path) -> None:
    """Unknown event types are rejected before they reach the database.

    Decision: raise ``ValueError`` with the offending value in the message.
    The canonical set is enforced at the emitter boundary so the events table
    never gains a non-canonical type from a live write.
    """
    db_path = tmp_path / "harness.db"
    await _init_db_with_run(db_path)
    emitter = EventEmitter(db_path)

    with pytest.raises(ValueError, match="not_a_real_event"):
        await emitter.emit(run_id="R1", event_type="not_a_real_event")  # type: ignore[arg-type]

    rows = await _fetch_all_events(db_path)
    assert rows == []


@pytest.mark.parametrize("event_type", _RETIRED_ENGINE_EVENT_TYPES)
async def test_emit_rejects_retired_engine_event_type(
    tmp_path: Path, event_type: str
) -> None:
    """Retired deterministic-engine types (CAL-574) are no longer writable.

    They were dropped from the canonical set in CAL-713; a live write of one
    is rejected exactly like any unknown type, so no fresh row can resurrect
    the retired surface.
    """
    db_path = tmp_path / "harness.db"
    await _init_db_with_run(db_path)
    emitter = EventEmitter(db_path)

    with pytest.raises(ValueError, match=re.escape(event_type)):
        await emitter.emit(run_id="R1", event_type=event_type)  # type: ignore[arg-type]

    assert await _fetch_all_events(db_path) == []


async def test_historical_legacy_event_row_reads_back(tmp_path: Path) -> None:
    """The legacy-rows allowance: a retired-engine event already in the table
    reads back unchanged.

    Readers never re-validate ``event_type`` (only the emitter does, on write),
    so pruning the canonical set does not break historical rows. This is the
    executable form of AC #1's "historical-row validation still passes": the
    row is inserted directly (mirroring an engine-era write) and round-trips.
    """
    db_path = tmp_path / "harness.db"
    await _init_db_with_run(db_path)

    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO events (run_id, node_id, event_type, timestamp, "
            "duration_ms, data_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("R1", "node-7", "workflow_started", "2026-05-08T00:00:00Z", 5, "{}"),
        )
        await conn.commit()

    rows = await _fetch_all_events(db_path)
    assert len(rows) == 1
    assert rows[0]["event_type"] == "workflow_started"
    assert rows[0]["node_id"] == "node-7"


# ---------------------------------------------------------------------------
# Foreign key — emitting against a non-existent run raises
# ---------------------------------------------------------------------------


async def test_emit_rejects_event_for_non_existent_run(tmp_path: Path) -> None:
    """Foreign-key enforcement: events.run_id REFERENCES runs(run_id).

    aiosqlite raises ``IntegrityError`` (subclass of ``sqlite3.IntegrityError``)
    when the parent row is missing.
    """
    import sqlite3

    db_path = tmp_path / "harness.db"
    await store.init_db(db_path)  # No runs row inserted.
    emitter = EventEmitter(db_path)

    with pytest.raises(sqlite3.IntegrityError):
        await emitter.emit(run_id="ghost", event_type="review")


# ---------------------------------------------------------------------------
# Data — JSON-serializable payloads round-trip intact
# ---------------------------------------------------------------------------


async def test_emit_serializes_nested_data_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    await _init_db_with_run(db_path)
    emitter = EventEmitter(db_path)

    payload: dict[str, object] = {
        "tool": "Read",
        "args": {"path": "/x"},
        "results": [1, 2, 3],
        "ok": True,
        "missing": None,
    }
    await emitter.emit(
        run_id="R1",
        event_type="review",
        node_id="n1",
        data=payload,
    )

    rows = await _fetch_all_events(db_path)
    assert json.loads(str(rows[0]["data_json"])) == payload
