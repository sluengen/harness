"""Append-only event log writer — see SPEC §4.9.

One row per ``emit()`` call into the ``events`` table created by
``harness.state.store``. No buffering, no batching, no listeners — just an
append-only writer the engine calls at every workflow/node/tool/state
transition.

Schema (SPEC §12)::

    events(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      run_id      TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
      node_id     TEXT,
      event_type  TEXT NOT NULL,
      timestamp   TEXT NOT NULL,
      duration_ms INTEGER,
      data_json   TEXT NOT NULL DEFAULT '{}'
    )

Timestamps are ISO-8601 UTC with a trailing ``Z`` (e.g.
``2026-05-08T17:23:45.123456Z``) — readable by humans and ``datetime.fromisoformat``
in Python 3.11+ once the ``Z`` is replaced with ``+00:00``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harness.events.schema import EVENT_TYPES, EventType
from harness.state import store


class EventEmitter:
    """Append-only writer for the ``events`` table.

    Each ``emit()`` opens a fresh aiosqlite connection via ``store.connect`` so
    every write picks up the WAL + foreign-keys PRAGMAs. That is intentional —
    the emitter does not own a long-lived connection because the engine may be
    invoked from contexts (e.g. CLI subcommands) where pooling would outlive
    the work.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def emit(
        self,
        run_id: str,
        event_type: EventType,
        node_id: str | None = None,
        data: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Append one event row.

        Args:
            run_id: The owning run's ULID. Must reference an existing
                ``runs.run_id`` — the foreign key raises
                ``sqlite3.IntegrityError`` otherwise.
            event_type: One of the canonical SPEC §4.9 event types. Unknown
                values raise ``ValueError`` before any DB write.
            node_id: Optional step/node identifier. ``None`` is stored as SQL
                NULL.
            data: Optional JSON-serializable payload. ``None`` becomes ``{}``.
            duration_ms: Optional integer duration. ``None`` is stored as SQL
                NULL.

        Raises:
            ValueError: ``event_type`` is not in the canonical SPEC §4.9 set.
            sqlite3.IntegrityError: ``run_id`` does not exist in ``runs``.
        """
        if event_type not in EVENT_TYPES:
            raise ValueError(
                f"unknown event_type {event_type!r}; expected one of {sorted(EVENT_TYPES)}"
            )

        timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        data_json = json.dumps(data if data is not None else {})

        async with store.connect(self._db_path) as conn:
            await conn.execute(
                "INSERT INTO events (run_id, node_id, event_type, timestamp, "
                "duration_ms, data_json) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, node_id, event_type, timestamp, duration_ms, data_json),
            )
            await conn.commit()
