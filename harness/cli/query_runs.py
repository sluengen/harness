"""``harness runs`` — list recent runs.

SPEC §11 names the command; ``specs/features/run-ledger.md`` documents the row shape.
Async DB access is wrapped in :func:`asyncio.run` at the command boundary
because Typer dispatches synchronously.

Exit codes (SPEC §11):
* 0 — succeeded. A missing or empty DB is the empty case, not an error:
  ``runs`` lists rows by query (no run-id), so it prints nothing and exits 0.
* 2 — invocation error: bad flags. (Unlike the run-id read commands
  ``status``/``events``, a missing DB is not an error here.)
"""

from __future__ import annotations

import asyncio
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


def runs_command(
    limit: int = typer.Option(
        20, "--limit", help="Maximum number of runs to list (default 20)."
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db)."
    ),
) -> None:
    """List recent runs."""
    db_path = _resolve_db_path(db)

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
    "_fetch_recent_runs",
    "runs_command",
]
