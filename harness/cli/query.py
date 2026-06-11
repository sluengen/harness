"""Read-side query commands — ``status``, ``logs``, ``events``.

SPEC §11 names the commands; SPEC §12 documents the row shapes. All three
share the same DB resolution path: a ``--db`` flag overriding the default
``$cwd/.harness/harness.db``. Async DB access is wrapped in
:func:`asyncio.run` at each command boundary because Typer dispatches synchronously.

Exit codes (SPEC §11):
* 0 — succeeded; produced output.
* 2 — invocation error: unknown ``run-id``, missing DB, bad flags.

JSON output is line-stable (one event per line for ``events --json``,
single object for ``status --json``) so callers can pipe into ``jq``.

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
  (``worktree_path``, ``worktree_branch``, ``pr_url``, ``report_path``);
  ``None`` when no artifacts are recorded.
* ``agent_session_ids`` — list of unique ``session_id`` values from
  ``tool_called`` event data; ``None`` when no session IDs are present.
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

from harness.state import store

# A run is "in progress" while its status sits in this set. Anything else is
# terminal and ``logs --follow`` should exit on the next poll. SPEC §12 lists
# the canonical statuses.
_IN_PROGRESS_STATUSES: frozenset[str] = frozenset({"pending", "running"})

# How often ``--follow`` polls for new events. 500ms per the task brief —
# kept as a module constant so tests can monkey-patch if needed.
_FOLLOW_POLL_INTERVAL_SECONDS = 0.5


# ---------------------------------------------------------------------------
# Shared options
# ---------------------------------------------------------------------------


def _resolve_db_path(db: Path | None) -> Path:
    """Either the explicit ``--db`` or the default
    ``$cwd/.harness/harness.db``."""
    if db is not None:
        return db
    return Path.cwd() / store.DEFAULT_DB_PATH


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
    "pr_url",
    "report_path",
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


def _safe_json_loads(raw: Any) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        # Surface as a string rather than crashing the CLI — the row is
        # authoritative, even if its embedded JSON is malformed.
        return raw


# ---------------------------------------------------------------------------
# events / logs — share a single fetcher
# ---------------------------------------------------------------------------


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
    db: Path | None = typer.Option(None, "--db", help="Path to harness.db."),
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
    db: Path | None = typer.Option(None, "--db", help="Path to harness.db."),
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
                node_info = ""
                typer.echo(
                    f"  {entry['run_id']}  {entry['workflow_name']}  "
                    f"{entry['started_at']}{node_info}"
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
    "status_command",
    "logs_command",
    "events_command",
    "runs_command",
]
