"""``harness runs`` — list recent runs (optionally grouped by failure).

SPEC §11 names the command; ``specs/state-store.md`` documents the row shape.
Async DB access is wrapped in :func:`asyncio.run` at the command boundary
because Typer dispatches synchronously.

Exit codes (SPEC §11):
* 0 — succeeded; produced output.
* 2 — invocation error: missing DB, bad flags.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import aiosqlite
import typer

from harness.cli._query_common import _resolve_db_path


async def _fetch_recent_runs(
    db_path: Path,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return the N most recent runs ordered by started_at DESC."""
    if not db_path.exists():
        return []
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT run_id, workflow_name, status, started_at, duration_ms "
            "FROM runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def _fetch_failed_runs_grouped(
    db_path: Path,
) -> dict[str, list[dict[str, Any]]]:
    """Return failed runs grouped by workflow_failed event reason.

    Joins runs with events on event_type='workflow_failed' and extracts
    data_json.reason. Runs without a workflow_failed event land under the
    empty-string key.
    """
    if not db_path.exists():
        return {}
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        # Left-join so failed runs without a workflow_failed event still appear.
        async with conn.execute(
            "SELECT r.run_id, r.workflow_name, r.started_at, "
            "e.data_json AS event_data_json "
            "FROM runs r "
            "LEFT JOIN events e ON e.run_id = r.run_id "
            "  AND e.event_type = 'workflow_failed' "
            "WHERE r.status = 'failed' "
            "ORDER BY r.started_at DESC",
        ) as cur:
            rows = await cur.fetchall()

    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        d = dict(row)
        reason = ""
        raw = d.get("event_data_json")
        if raw:
            try:
                parsed = json.loads(raw)
                reason = str(parsed.get("reason", "")) if isinstance(parsed, dict) else ""
            except (TypeError, ValueError):
                reason = ""
        entry = {
            "run_id": d["run_id"],
            "workflow_name": d["workflow_name"],
            "started_at": d["started_at"],
        }
        groups.setdefault(reason, []).append(entry)
    return groups


def runs_command(
    failed: bool = typer.Option(
        False, "--failed", help="Group failed runs by failure reason."
    ),
    limit: int = typer.Option(
        20, "--limit", help="Maximum number of runs to list (default 20)."
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db)."
    ),
) -> None:
    """List recent runs."""
    db_path = _resolve_db_path(db)

    if failed:
        groups = asyncio.run(_fetch_failed_runs_grouped(db_path))
        if not groups:
            typer.echo("(no failures)")
            return
        for reason, entries in groups.items():
            header = reason if reason else "(unknown reason)"
            typer.echo(header)
            for entry in entries:
                typer.echo(
                    f"  {entry['run_id']}  {entry['workflow_name']}  "
                    f"{entry['started_at']}"
                )
        return

    rows = asyncio.run(_fetch_recent_runs(db_path, limit=limit))
    if not rows:
        return
    for row in rows:
        duration = row.get("duration_ms")
        dur_str = f"  {duration}ms" if duration is not None else ""
        typer.echo(
            f"{row['run_id']}  {row['workflow_name']:<20}  "
            f"{row['status']:<12}  {row['started_at']}{dur_str}"
        )


__all__ = [
    "_fetch_failed_runs_grouped",
    "_fetch_recent_runs",
    "runs_command",
]
