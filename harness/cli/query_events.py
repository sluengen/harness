"""``harness events`` / ``harness logs`` — a run's event timeline.

Both commands read the same ``events`` table through one fetcher
(:func:`_fetch_events`); ``events`` is the JSON-stable form (one object per
line for ``--json``) while ``logs`` is the human timeline (with ``--follow``
tailing until the run becomes terminal). SPEC §11 names the commands;
``specs/state-store.md`` documents the event row shape. Async DB access is
wrapped in
:func:`asyncio.run` at each command boundary because Typer dispatches
synchronously.

Exit codes (SPEC §11):
* 0 — succeeded; produced output.
* 2 — invocation error: unknown ``run-id``, missing DB, bad flags.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import aiosqlite
import typer

from harness.cli._query_common import _resolve_db_path, _safe_json_loads

# A run is "in progress" while its status sits in this set, so ``logs --follow``
# keeps tailing; any other status is terminal and the loop exits on the next
# poll. ``open`` is the live verb-model status — ``harness start`` writes it and
# ``review``/``close`` resolve a run by ``status='open'``; the retired engine's
# ``pending``/``running`` are kept so a historical run still tails. See
# :data:`harness.state.schema.RunStatus` for the canonical status split.
_IN_PROGRESS_STATUSES: frozenset[str] = frozenset({"open", "pending", "running"})

# How often ``--follow`` polls for new events. 500ms per the task brief —
# kept as a module constant so tests can monkey-patch if needed.
_FOLLOW_POLL_INTERVAL_SECONDS = 0.5


async def _run_exists(db_path: Path, run_id: str) -> bool:
    if not db_path.exists():
        return False
    async with aiosqlite.connect(db_path) as conn, conn.execute(
        "SELECT 1 FROM runs WHERE run_id = ?", (run_id,)
    ) as cur:
        return (await cur.fetchone()) is not None


async def _fetch_events(
    db_path: Path,
    run_id: str,
    *,
    event_type: str | None = None,
    node_id: str | None = None,
    after_id: int = 0,
) -> list[dict[str, Any]]:
    """Return events for ``run_id`` ordered by autoincrement id.

    ``after_id`` lets ``logs --follow`` ask for new rows only.
    ``event_type`` and ``node_id`` are independent filters (both honoured if
    set).
    """
    query = [
        "SELECT id, run_id, node_id, event_type, timestamp, duration_ms, "
        "data_json FROM events WHERE run_id = ? AND id > ?"
    ]
    params: list[Any] = [run_id, after_id]
    if event_type is not None:
        query.append("AND event_type = ?")
        params.append(event_type)
    if node_id is not None:
        query.append("AND node_id = ?")
        params.append(node_id)
    query.append("ORDER BY id ASC")

    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(" ".join(query), params) as cur:
            rows = await cur.fetchall()
            return [
                {
                    "id": int(r["id"]),
                    "run_id": r["run_id"],
                    "node_id": r["node_id"],
                    "event_type": r["event_type"],
                    "timestamp": r["timestamp"],
                    "duration_ms": r["duration_ms"],
                    "data": _safe_json_loads(r["data_json"]),
                }
                for r in rows
            ]


async def _fetch_status(db_path: Path, run_id: str) -> str | None:
    async with aiosqlite.connect(db_path) as conn, conn.execute(
        "SELECT status FROM runs WHERE run_id = ?", (run_id,)
    ) as cur:
        row = await cur.fetchone()
        if row is None:
            return None
        return str(row[0])


def _format_event_compact(evt: dict[str, Any]) -> str:
    """Single-line human form: ``<ts> <event_type> [node=<id>] <data>``."""
    parts = [str(evt["timestamp"]), str(evt["event_type"])]
    if evt.get("node_id"):
        parts.append(f"node={evt['node_id']}")
    if evt.get("data") not in (None, {}, ""):
        # Compact JSON without spaces so the line stays grep-able.
        parts.append(json.dumps(evt["data"], separators=(",", ":"), default=str))
    return " ".join(parts)


def events_command(
    run_id: str = typer.Argument(..., help="Run identifier (ULID)."),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db)."
    ),
    event_type: str | None = typer.Option(
        None, "--type", help="Filter to a single event_type."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit one JSON object per event, one per line."
    ),
    after_id: int = typer.Option(
        0,
        "--after-id",
        help=(
            "Return only events with id > this value. "
            "Enables incremental polling: store the last-seen event id, "
            "then pass it on the next call to fetch only new events."
        ),
    ),
) -> None:
    """Print events for a run."""
    db_path = _resolve_db_path(db)
    if not asyncio.run(_run_exists(db_path, run_id)):
        typer.echo(f"no run with run_id={run_id!r}", err=True)
        raise typer.Exit(code=2)

    rows = asyncio.run(
        _fetch_events(db_path, run_id, event_type=event_type, after_id=after_id)
    )

    if json_output:
        for evt in rows:
            typer.echo(json.dumps(evt, default=str))
        return

    for evt in rows:
        typer.echo(_format_event_compact(evt))


def logs_command(
    run_id: str = typer.Argument(..., help="Run identifier (ULID)."),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db)."
    ),
    node: str | None = typer.Option(
        None, "--node", help="Filter to events for a single node id."
    ),
    follow: bool = typer.Option(
        False, "--follow", help="Poll for new events; exit when the run becomes terminal."
    ),
) -> None:
    """Print a human-readable timeline of events for a run."""
    db_path = _resolve_db_path(db)
    if not asyncio.run(_run_exists(db_path, run_id)):
        typer.echo(f"no run with run_id={run_id!r}", err=True)
        raise typer.Exit(code=2)

    if not follow:
        rows = asyncio.run(_fetch_events(db_path, run_id, node_id=node))
        for evt in rows:
            typer.echo(_format_event_compact(evt))
        return

    asyncio.run(_follow_logs(db_path, run_id, node))


async def _follow_logs(db_path: Path, run_id: str, node_id: str | None) -> None:
    """``--follow`` implementation. Prints every event, then polls until the
    run's status is no longer in :data:`_IN_PROGRESS_STATUSES`.

    Ctrl-C surfaces as :class:`KeyboardInterrupt`; Typer/Click maps that to
    exit code 130 by default. We don't intercept it here.
    """
    last_id = 0
    while True:
        try:
            rows = await _fetch_events(
                db_path, run_id, node_id=node_id, after_id=last_id
            )
        except sqlite3.OperationalError:
            # Database may be momentarily locked by a concurrent writer
            # (WAL still allows reads, but readers can race a schema bump).
            # Treat as transient — try again next tick.
            await asyncio.sleep(_FOLLOW_POLL_INTERVAL_SECONDS)
            continue

        for evt in rows:
            typer.echo(_format_event_compact(evt))
            last_id = max(last_id, evt["id"])
            # Flush so callers tailing the output see lines immediately.
            sys.stdout.flush()

        status = await _fetch_status(db_path, run_id)
        if status is None or status not in _IN_PROGRESS_STATUSES:
            return

        await asyncio.sleep(_FOLLOW_POLL_INTERVAL_SECONDS)


__all__ = [
    "_FOLLOW_POLL_INTERVAL_SECONDS",
    "_IN_PROGRESS_STATUSES",
    "_fetch_events",
    "_fetch_status",
    "_follow_logs",
    "_format_event_compact",
    "_run_exists",
    "events_command",
    "logs_command",
]
