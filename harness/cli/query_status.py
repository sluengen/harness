"""``harness status`` — a run's terminal-state summary.

SPEC §11 names the command; ``specs/features/run-ledger.md`` documents the row shape.
Async DB access is wrapped in :func:`asyncio.run` at the command boundary
because Typer dispatches synchronously.

``harness status <id> --json`` is extended with two enriched fields read from
the events / state tables:

* ``failure_reason`` — ``data.reason`` from the latest ``workflow_failed``
  event; ``None`` if the run has not failed. The live emitters of
  ``workflow_failed`` are ``harness cancel`` (``reason='cancelled'``) and
  ``harness reclaim`` (``reason='reclaimed'``) — the engine that once emitted it
  was retired in CAL-574.
* ``artifact_paths`` — dict of non-None artifact fields from ``state``
  (``worktree_path``, ``worktree_branch``); ``None`` when no artifacts are
  recorded.

The run id may be given positionally or as ``--run-id`` (#245) — resolved by
:func:`harness.cli._query_common._resolve_run_id`, shared with ``logs``/``events``.

Exit codes (SPEC §11):
* 0 — succeeded; produced output.
* 2 — invocation error: unknown ``run-id``, missing/conflicting run id, missing DB, bad flags.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import aiosqlite
import typer

from harness.cli._query_common import (
    _resolve_db_path,
    _resolve_run_id,
    _safe_json_loads,
)
from harness.cli._repo import REPO_OPTION_HELP
from harness.events.payloads import WORKFLOW_FAILED_REASON_KEY

# ---------------------------------------------------------------------------
# Artifact-path extraction
# ---------------------------------------------------------------------------

# State fields surfaced as artifacts under ``artifact_paths``.
_ARTIFACT_KEYS: tuple[str, ...] = (
    "worktree_path",
    "worktree_branch",
)


def _extract_artifact_paths(state: Any) -> dict[str, Any] | None:
    """Extract artifact-relevant fields from the parsed ``state`` dict.

    Returns a dict of ``{field: value}`` for every ``_ARTIFACT_KEYS`` entry
    whose value is non-``None`` in ``state``, or ``None`` when no artifacts
    are recorded.
    """
    if not isinstance(state, dict):
        return None
    paths = {k: state[k] for k in _ARTIFACT_KEYS if state.get(k) is not None}
    return paths if paths else None


# ---------------------------------------------------------------------------
# status — single row from runs
# ---------------------------------------------------------------------------


async def _fetch_run_row(db_path: Path, run_id: str) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT run_id, workflow_name, workflow_version, status, state_json, "
            "inputs_json, base_branch, worktree_branch, exit_code, started_at, "
            "completed_at, duration_ms FROM runs WHERE run_id = ?",
            (run_id,),
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            return dict(row)


async def _fetch_enriched_status(db_path: Path, run_id: str) -> dict[str, Any]:
    """Fetch the enriched ``failure_reason`` field from the events table.

    Returns a dict with:
    ``failure_reason`` — ``str | None``: ``data.reason`` from the latest
                         ``workflow_failed`` event (emitted by ``harness cancel``
                         with ``reason='cancelled'`` or ``harness reclaim`` with
                         ``reason='reclaimed'``).
    """
    result: dict[str, Any] = {"failure_reason": None}
    if not db_path.exists():
        return result

    # failure_reason: data.reason from the most recent workflow_failed event.
    async with (
        aiosqlite.connect(db_path) as conn,
        conn.execute(
            "SELECT data_json FROM events "
            "WHERE run_id = ? AND event_type = 'workflow_failed' "
            "ORDER BY id DESC LIMIT 1",
            (run_id,),
        ) as cur,
    ):
        row = await cur.fetchone()
        if row is not None:
            data = _safe_json_loads(row[0])
            if isinstance(data, dict):
                result["failure_reason"] = data.get(WORKFLOW_FAILED_REASON_KEY)

    return result


async def _fetch_status_full(
    db_path: Path, run_id: str
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Fetch the run row and enriched event fields in a single async context.

    Returns ``(row, enriched)`` — ``row`` is ``None`` when the run does not
    exist; ``enriched`` is an empty dict in that case.
    """
    row = await _fetch_run_row(db_path, run_id)
    if row is None:
        return None, {}
    enriched = await _fetch_enriched_status(db_path, run_id)
    return row, enriched


def status_command(
    run_id: str | None = typer.Argument(
        None, help="Run identifier (ULID). May also be given as --run-id."
    ),
    repo: Path | None = typer.Option(
        None, "--repo", help=REPO_OPTION_HELP
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db)."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the full row as a JSON object."
    ),
    run_id_option: str | None = typer.Option(
        None, "--run-id", help="Run identifier (ULID) — alias for the positional RUN_ID."
    ),
) -> None:
    """Print a run's terminal-state summary."""
    run_id = _resolve_run_id(run_id, run_id_option)
    db_path = _resolve_db_path(db, repo)
    row, enriched = asyncio.run(_fetch_status_full(db_path, run_id))
    if row is None:
        typer.echo(f"no run with run_id={run_id!r}", err=True)
        raise typer.Exit(code=2)

    if json_output:
        payload = dict(row)
        # Parse the embedded JSON blobs so callers don't have to. Keep the
        # original keys around as ``state`` / ``inputs`` — the raw strings
        # are dropped from the output (callers reach for the parsed form).
        state = _safe_json_loads(row.get("state_json"))
        payload["state"] = state
        payload["inputs"] = _safe_json_loads(row.get("inputs_json"))
        payload.pop("state_json", None)
        payload.pop("inputs_json", None)
        # Enriched fields from the events / state tables.
        payload["failure_reason"] = enriched.get("failure_reason")
        payload["artifact_paths"] = _extract_artifact_paths(state)
        typer.echo(json.dumps(payload, default=str))
        return

    # Human form — compact, scannable.
    typer.echo(f"run_id:           {row['run_id']}")
    typer.echo(f"status:           {row['status']}")
    typer.echo(f"started_at:       {row['started_at']}")
    typer.echo(f"completed_at:     {row['completed_at'] or '-'}")
    typer.echo(f"exit_code:        {row['exit_code'] if row['exit_code'] is not None else '-'}")


__all__ = [
    "_ARTIFACT_KEYS",
    "_extract_artifact_paths",
    "_fetch_enriched_status",
    "_fetch_run_row",
    "_fetch_status_full",
    "status_command",
]
