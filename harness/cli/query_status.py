"""``harness status`` — a run's terminal-state summary.

SPEC §11 names the command; ``specs/state-store.md`` documents the row shape.
Async DB access is wrapped in :func:`asyncio.run` at the command boundary
because Typer dispatches synchronously.

``harness status <id> --json`` is extended with enriched fields for Hermes
consumption (see ``specs/hermes-orchestration.md`` §Observability
requirements):

* ``failure_reason`` — ``data.reason`` from the latest ``workflow_failed``
  event; ``None`` if the run has not failed. The sole live emitter of
  ``workflow_failed`` is ``harness cancel`` (``reason='cancelled'``) — the
  engine that once emitted it was retired in CAL-574.
* ``failure_retryable`` — ``True`` for transient failures; ``False`` for
  contract violations, cancellation, and loop exhaustion; ``None`` if no
  failure.
* ``artifact_paths`` — dict of non-None artifact fields from ``state``
  (``worktree_path``, ``worktree_branch``); ``None`` when no artifacts are
  recorded.
* ``agent_session_ids`` — list of unique ``session_id`` values from
  ``tool_called`` event data; ``None`` when no session IDs are present.

Exit codes (SPEC §11):
* 0 — succeeded; produced output.
* 2 — invocation error: unknown ``run-id``, missing DB, bad flags.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import aiosqlite
import typer

from harness.cli._query_common import _resolve_db_path, _safe_json_loads

# ---------------------------------------------------------------------------
# Failure-retryable derivation
# ---------------------------------------------------------------------------

# Failure reasons that are definitively not retryable.  Contract violations
# require prompt repair; loop exhaustion means the budget was spent; cancelled
# and rejected are intentional terminations.
_NON_RETRYABLE_REASONS: frozenset[str] = frozenset(
    {"cancelled", "loop_exhausted", "rejected"}
)


def _derive_failure_retryable(failure_reason: str | None) -> bool | None:
    """Return whether a failure is worth retrying, or ``None`` if there is none.

    ``True``  — transient errors (network, timeout, generic exceptions).
    ``False`` — contract violations (need prompt repair), loop exhaustion,
                cancellation, or human rejection.
    ``None``  — the run has not failed (no ``failure_reason`` yet).
    """
    if failure_reason is None:
        return None
    if failure_reason.startswith("ContractViolation"):
        return False
    return failure_reason not in _NON_RETRYABLE_REASONS


# ---------------------------------------------------------------------------
# Artifact-path extraction
# ---------------------------------------------------------------------------

# State fields that are surfaced as artifacts for Hermes.
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
    """Fetch enriched status fields that require event-table queries.

    Uses a single connection for both queries to avoid redundant
    connection setup on every status call.

    Returns a dict with:
    ``failure_reason``    — ``str | None``: ``data.reason`` from the latest
                            ``workflow_failed`` event (emitted by
                            ``harness cancel`` with ``reason='cancelled'``).
    ``agent_session_ids`` — ``list[str] | None``: unique ``session_id`` values
                            from ``tool_called`` event data payloads.
    """
    result: dict[str, Any] = {
        "failure_reason": None,
        "agent_session_ids": None,
    }
    if not db_path.exists():
        return result

    async with aiosqlite.connect(db_path) as conn:
        # failure_reason: data.reason from the most recent workflow_failed event.
        async with conn.execute(
            "SELECT data_json FROM events "
            "WHERE run_id = ? AND event_type = 'workflow_failed' "
            "ORDER BY id DESC LIMIT 1",
            (run_id,),
        ) as cur:
            row = await cur.fetchone()
            if row is not None:
                data = _safe_json_loads(row[0])
                if isinstance(data, dict):
                    result["failure_reason"] = data.get("reason")

        # agent_session_ids: deduplicated session_id values from tool_called events.
        async with conn.execute(
            "SELECT data_json FROM events "
            "WHERE run_id = ? AND event_type = 'tool_called'",
            (run_id,),
        ) as cur:
            rows = await cur.fetchall()
        session_ids: list[str] = []
        seen: set[str] = set()
        for r in rows:
            data = _safe_json_loads(r[0])
            if isinstance(data, dict):
                sid = data.get("session_id")
                if sid is not None:
                    sid_str = str(sid)
                    if sid_str not in seen:
                        session_ids.append(sid_str)
                        seen.add(sid_str)
        if session_ids:
            result["agent_session_ids"] = session_ids

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
    run_id: str = typer.Argument(..., help="Run identifier (ULID)."),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db)."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the full row as a JSON object."
    ),
) -> None:
    """Print a run's terminal-state summary."""
    db_path = _resolve_db_path(db)
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
        # Enriched fields from the events table (Hermes observability).
        failure_reason: str | None = enriched.get("failure_reason")
        payload["failure_reason"] = failure_reason
        payload["failure_retryable"] = _derive_failure_retryable(failure_reason)
        payload["artifact_paths"] = _extract_artifact_paths(state)
        payload["agent_session_ids"] = enriched.get("agent_session_ids")
        typer.echo(json.dumps(payload, default=str))
        return

    # Human form — compact, scannable.
    typer.echo(f"run_id:           {row['run_id']}")
    typer.echo(f"workflow_name:    {row['workflow_name']}")
    typer.echo(f"workflow_version: {row['workflow_version']}")
    typer.echo(f"status:           {row['status']}")
    typer.echo(f"started_at:       {row['started_at']}")
    typer.echo(f"completed_at:     {row['completed_at'] or '-'}")
    typer.echo(f"exit_code:        {row['exit_code'] if row['exit_code'] is not None else '-'}")


__all__ = [
    "_ARTIFACT_KEYS",
    "_NON_RETRYABLE_REASONS",
    "_derive_failure_retryable",
    "_extract_artifact_paths",
    "_fetch_enriched_status",
    "_fetch_run_row",
    "_fetch_status_full",
    "status_command",
]
