"""CLI surface for ``decisions`` / ``decision`` — H-2-003.

``decisions list``      — query paused runs; render run_id, workflow, started_at
                          and the question extracted from the most recent
                          ``decision_requested`` event.

``decision show``       — look up a single paused run and render its question
                          plus the display_state field values for the human
                          decider.

``decision approve``    — v2-reserved stub; exits 2 with "deferred to v2".
``decision reject``     — v2-reserved stub; exits 2 with "deferred to v2".

Exit codes (per SPEC §11):
* 0  — succeeded; produced output (or produced empty output for an empty list).
* 2  — invocation error: unknown run-id, run not paused, bad flags.

JSON output uses ``json.dumps(..., default=str)`` for non-serialisable values,
consistent with the rest of the CLI read surface.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any

import aiosqlite
import typer

from harness.state import store

__all__ = ["decisions_app", "decision_app"]


# ---------------------------------------------------------------------------
# Shared "deferred to v2" responder — approve / reject only.
# ---------------------------------------------------------------------------

_DEFERRED_MESSAGE = "deferred to v2"
_RESERVED_HELP = "v2-reserved — not yet implemented (see SPEC §11)."


def _reserved_v2(json_output: bool) -> None:
    """Emit the canonical ``deferred to v2`` response and raise ``typer.Exit(2)``."""
    if json_output:
        typer.echo(json.dumps({"error": _DEFERRED_MESSAGE}))
    else:
        typer.echo(_DEFERRED_MESSAGE, err=True)
    raise typer.Exit(code=2)


def _resolve_db_path(db: Path | None) -> Path:
    """``--db`` override or the default ``.harness/harness.db``."""
    if db is not None:
        return db
    return Path.cwd() / store.DEFAULT_DB_PATH


# ---------------------------------------------------------------------------
# Async DB helpers
# ---------------------------------------------------------------------------


async def _fetch_paused_runs(db_path: Path) -> list[dict[str, Any]]:
    """Return all runs with ``status = 'paused'``, newest first."""
    if not db_path.exists():
        return []
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT run_id, workflow_name, workflow_version, status, "
            "state_json, started_at "
            "FROM runs WHERE status = 'paused' "
            "ORDER BY started_at DESC",
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def _fetch_run_row(db_path: Path, run_id: str) -> dict[str, Any] | None:
    """Return a single run row, or ``None`` if not found."""
    if not db_path.exists():
        return None
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT run_id, workflow_name, workflow_version, status, "
            "state_json, started_at "
            "FROM runs WHERE run_id = ?",
            (run_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _fetch_decision_requested_event(
    db_path: Path, run_id: str
) -> dict[str, Any] | None:
    """Return the data payload of the most recent ``decision_requested`` event,
    or ``None`` if no such event exists for this run."""
    async with aiosqlite.connect(db_path) as conn, conn.execute(
        "SELECT data_json FROM events "
        "WHERE run_id = ? AND event_type = 'decision_requested' "
        "ORDER BY id DESC LIMIT 1",
        (run_id,),
    ) as cur:
        row = await cur.fetchone()
        if row is None:
            return None
        raw = row[0]
        try:
            return json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            return {}


async def _fetch_decision_requested_events_bulk(
    db_path: Path, run_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """Return ``{run_id: event_data}`` for the most recent ``decision_requested``
    event for each supplied *run_id* — one query for any number of runs.

    Run IDs with no matching event are absent from the returned dict.
    """
    if not run_ids:
        return {}
    placeholders = ",".join("?" * len(run_ids))
    # placeholders contains only literal '?' tokens — no injection risk.
    query = (
        "SELECT run_id, data_json FROM events e "  # noqa: S608
        "WHERE event_type = 'decision_requested' "
        f"AND run_id IN ({placeholders}) "
        "AND id = (SELECT MAX(id) FROM events "
        "          WHERE run_id = e.run_id "
        "          AND event_type = 'decision_requested')"
    )
    async with (
        aiosqlite.connect(db_path) as conn,
        conn.execute(query, run_ids) as cur,
    ):
        result: dict[str, dict[str, Any]] = {}
        async for row in cur:
            rid, raw = row[0], row[1]
            try:
                result[rid] = json.loads(raw) if raw else {}
            except (TypeError, ValueError):
                result[rid] = {}
        return result


async def _fetch_list_data(
    db_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Fetch paused runs and their decision events in a single async session.

    Returns ``(rows, events_by_run_id)`` where *events_by_run_id* maps each
    run_id to its most recent ``decision_requested`` event payload (absent
    when no such event exists).
    """
    rows = await _fetch_paused_runs(db_path)
    if not rows:
        return rows, {}
    run_ids = [r["run_id"] for r in rows]
    events = await _fetch_decision_requested_events_bulk(db_path, run_ids)
    return rows, events


# ---------------------------------------------------------------------------
# ``harness decisions`` (plural) — ``list``
# ---------------------------------------------------------------------------


decisions_app = typer.Typer(
    help="Enumerate paused runs awaiting human decision.",
    no_args_is_help=True,
)


@decisions_app.command("list")
def decisions_list_command(
    db: Path | None = typer.Option(
        None,
        "--db",
        help="Path to harness.db (defaults to .harness/harness.db).",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON array."
    ),
) -> None:
    """List paused runs awaiting a human decision."""
    db_path = _resolve_db_path(db)
    rows, events_by_run = asyncio.run(_fetch_list_data(db_path))

    if json_output:
        results: list[dict[str, Any]] = []
        for row in rows:
            evt = events_by_run.get(row["run_id"])
            results.append(
                {
                    "run_id": row["run_id"],
                    "workflow_name": row["workflow_name"],
                    "started_at": row["started_at"],
                    "question": evt.get("message") if evt else None,
                }
            )
        typer.echo(json.dumps(results, default=str))
        return

    if not rows:
        return  # empty list → silent exit 0

    for row in rows:
        evt = events_by_run.get(row["run_id"])
        question = (evt.get("message") if evt else None) or "-"
        typer.echo(f"run_id:   {row['run_id']}")
        typer.echo(f"workflow: {row['workflow_name']}")
        typer.echo(f"started:  {row['started_at']}")
        typer.echo(f"question: {question}")
        typer.echo("")  # blank separator between entries


# ---------------------------------------------------------------------------
# ``harness decision`` (singular) — ``show`` / ``approve`` / ``reject``
# ---------------------------------------------------------------------------


decision_app = typer.Typer(
    help="Inspect or resolve a paused decision node.",
    no_args_is_help=True,
)


@decision_app.command("show")
def decision_show_command(
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
    """Show a paused decision's question and display_state for the decider."""
    db_path = _resolve_db_path(db)
    row = asyncio.run(_fetch_run_row(db_path, run_id))

    if row is None:
        typer.echo(f"no run with run_id={run_id!r}", err=True)
        raise typer.Exit(code=2)

    if row["status"] != "paused":
        typer.echo(
            f"run {run_id!r} is not paused (status={row['status']!r})",
            err=True,
        )
        raise typer.Exit(code=2)

    evt = asyncio.run(_fetch_decision_requested_event(db_path, run_id))
    question: str | None = evt.get("message") if evt else None
    display_state_fields: list[str] = (evt.get("display_state") or []) if evt else []

    # Resolve field values from the run's persisted state blob.
    state: dict[str, Any] = {}
    with contextlib.suppress(TypeError, ValueError):
        state = json.loads(row.get("state_json") or "{}") or {}
    display_state_values: dict[str, Any] = {
        field: state.get(field) for field in display_state_fields
    }

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "run_id": run_id,
                    "workflow_name": row["workflow_name"],
                    "started_at": row["started_at"],
                    "question": question,
                    "display_state": display_state_values,
                },
                default=str,
            )
        )
        return

    # Human form.
    typer.echo(f"run_id:   {run_id}")
    typer.echo(f"workflow: {row['workflow_name']}")
    typer.echo(f"started:  {row['started_at']}")
    typer.echo(f"question: {question or '-'}")
    if display_state_values:
        typer.echo("")
        typer.echo("state:")
        for field, value in display_state_values.items():
            typer.echo(f"  {field}: {value}")


@decision_app.command("approve", help=_RESERVED_HELP)
def decision_approve_command(
    run_id: str = typer.Argument(..., help="Run identifier (ULID)."),
    comment: str | None = typer.Option(
        None, "--comment", help="Optional decision comment (captured to event log)."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Approve a paused decision — v2-reserved, not yet implemented."""
    _reserved_v2(json_output)


@decision_app.command("reject", help=_RESERVED_HELP)
def decision_reject_command(
    run_id: str = typer.Argument(..., help="Run identifier (ULID)."),
    comment: str | None = typer.Option(
        None, "--comment", help="Optional decision comment (captured to event log)."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Reject a paused decision — v2-reserved, not yet implemented."""
    _reserved_v2(json_output)
