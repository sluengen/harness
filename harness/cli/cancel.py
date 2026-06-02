"""CLI surface for ``harness cancel <run-id>`` — H-2-006.

Sends SIGTERM to the harness run process identified by ``run-id``.  The
runner installs a SIGTERM → ``KeyboardInterrupt`` handler so the signal
propagates through the executor's normal cancellation path:

1. ``harness cancel <run-id>`` reads ``runs.pid`` from the DB.
2. It validates the run is currently ``running`` and the process is alive.
3. It delivers ``signal.SIGTERM`` to the recorded PID.
4. The running ``harness run`` process catches the signal, emits
   ``workflow_failed`` with ``reason='cancelled'``, sets
   ``status='cancelled'``, and exits 130.

Exit codes (SPEC §11):
* 0  — SIGTERM successfully delivered.
* 2  — Invocation error: unknown run-id, run not running, PID absent or
        stale, no permission to signal the process.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from typing import Any

import aiosqlite
import typer

from harness.state import store

__all__ = ["cancel_command"]


def _resolve_db_path(db: Path | None) -> Path:
    """``--db`` override or the default ``.harness/harness.db``."""
    if db is not None:
        return db
    return Path.cwd() / store.DEFAULT_DB_PATH


async def _fetch_run_row(db_path: Path, run_id: str) -> dict[str, Any] | None:
    """Return the run row, or ``None`` if the DB or row does not exist."""
    if not db_path.exists():
        return None
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT run_id, status, pid FROM runs WHERE run_id = ?",
            (run_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


def cancel_command(
    run_id: str = typer.Argument(..., help="Run identifier (ULID)."),
    db: Path | None = typer.Option(
        None,
        "--db",
        help="Path to harness.db (defaults to .harness/harness.db).",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Cancel a running workflow by sending SIGTERM to its process."""
    db_path = _resolve_db_path(db)
    row = asyncio.run(_fetch_run_row(db_path, run_id))

    def _err(msg: str) -> None:
        if json_output:
            typer.echo(json.dumps({"error": msg}))
        else:
            typer.echo(msg, err=True)
        raise typer.Exit(code=2)

    if row is None:
        _err(f"no run with run_id={run_id!r}")

    assert row is not None  # narrowing for type checker

    if row["status"] != "running":
        _err(
            f"run {run_id!r} is not running (status={row['status']!r}); "
            "only running workflows can be cancelled"
        )

    pid: int | None = row.get("pid")
    if pid is None:
        _err(
            f"run {run_id!r} has no recorded PID — it may have been started "
            "before H-2-006 or outside the harness CLI"
        )

    assert pid is not None  # narrowing for type checker

    # Probe whether the process is still alive before delivering the signal.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        _err(
            f"process {pid} for run {run_id!r} no longer exists "
            "(stale PID — the run may have already exited)"
        )
    except PermissionError:
        _err(
            f"no permission to signal process {pid} for run {run_id!r}"
        )

    # Deliver SIGTERM — the runner converts it to KeyboardInterrupt.
    # Guard the TOCTOU window: the process may exit between the liveness probe
    # above and the actual signal delivery here.  Without this guard a
    # ProcessLookupError (or PermissionError) would propagate as an unhandled
    # exception and print a Python traceback rather than a clean error message.
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _err(
            f"process {pid} for run {run_id!r} exited before the signal could be "
            "delivered (TOCTOU race — the run may have already completed)"
        )
    except PermissionError:
        _err(
            f"no permission to signal process {pid} for run {run_id!r}"
        )

    if json_output:
        typer.echo(json.dumps({"run_id": run_id, "outcome": "cancelled"}))
    else:
        typer.echo(f"Cancelled: sent SIGTERM to process {pid} for run {run_id}")
