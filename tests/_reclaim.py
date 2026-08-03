"""Shared fixtures for the ``harness reclaim`` test family (#274).

``reclaim`` is decomposed across four production modules — ``reclaim.py``,
``reclaim_liveness.py``, ``reclaim_closable.py`` and ``reclaim_undo.py`` — and
#274 splits their single 2,774-line test home into one module per production
module. Every arm seeds the same ledger shapes and drives the verb through the
same patched tracker seam, so those fixtures land in **four** test modules at
once. That is the ``tests/_ledger.py`` / ``tests/_gitutil.py`` pattern: a need
shared by several modules lives in one place rather than being pasted into each.

Membership follows one rule, so the boundary is decidable rather than a matter
of taste: **a helper used by more than one test module lives here with a public
name; a helper with a single consumer stays private in that module.** So
``make_linear_stub``'s single-target counterpart stays in
``test_cli_reclaim.py``, the undo arm's ledger-mutation helpers stay in
``test_reclaim_undo.py``, and the closable arm's review seeders stay in
``test_reclaim_closable.py``.

The names are public (no leading underscore) because these are imported across
modules; underscore-prefixed cross-module imports are the private-import smell
``test_cli_module_boundaries.py`` polices in production, and the two existing
shared modules both export public names.

``invoke`` is the load-bearing one. ``reclaim`` has no ``--repo`` and resolves
its tracker from ``Path.cwd()``, which in this repo is ``tracker: github`` — so
a test that reaches the verb through a bare ``cli_runner.invoke`` would resolve
ambient config instead of the stub. Every arm goes through ``invoke`` (or the
undo arm's own wrapper) for that reason.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from harness._time import iso_z
from harness.cli import app
from harness.state import store
from tests._asyncutil import run_sync
from tests._gitutil import init_repo

cli_runner = CliRunner()


def iso_minutes_ago(minutes: int) -> str:
    """A trailing-``Z`` UTC timestamp ``minutes`` in the past — the Linear
    ``updatedAt`` shape the sweep parses (proposal D2 staleness signal)."""
    return iso_z(datetime.now(UTC) - timedelta(minutes=minutes))


# ---------------------------------------------------------------------------
# DB seeding / inspection helpers
# ---------------------------------------------------------------------------


def seed_run(
    db_path: Path,
    *,
    run_id: str,
    status: str,
    ticket: str | None = "CAL-735",
    worktree_branch: str | None = "harness/cal-735",
    worktree_path: str | None = None,
    started_at: str = "2026-01-01T00:00:00+00:00",
) -> None:
    """Seed a run row with the ticket + branch fields reclaim reads.

    ``started_at`` defaults to a long-past stamp so an existing test's seeded run
    reads as dead — which is what those tests mean. Since #216 the sweep treats
    ``started_at`` as a liveness signal (``start`` emits no event, so it is the
    only one a pre-``design`` run has), so a test about a *live* run sets it.
    """

    async def _insert() -> None:
        await store.init_db(db_path)
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
                "state_json, inputs_json, base_branch, worktree_branch, "
                "worktree_path, ticket, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    "test",
                    1,
                    status,
                    "{}",
                    "{}",
                    "dev",
                    worktree_branch,
                    worktree_path,
                    ticket,
                    started_at,
                ),
            )
            await conn.commit()

    run_sync(_insert())


def seed_checkpoint(
    db_path: Path,
    run_id: str,
    branch: str = "harness/cal-735",
    *,
    timestamp: str | None = None,
) -> None:
    """Emit a ``checkpoint`` event for ``run_id`` — the durable-WIP signal a
    checkpoint-push leaves (CAL-738). reclaim reports a resumable branch only when
    one exists; a run with none has no pushed WIP.

    ``timestamp`` back-dates the event (#216). ``EventEmitter`` always stamps
    *now*, but since #216 the sweep reads the newest event as a liveness signal —
    so a test that wants a *dead* run must say when its last sign of life was,
    rather than inheriting "a moment ago" and accidentally asserting the run is
    alive. Left ``None`` the event keeps the emitter's own clock.
    """
    from harness.events.emitter import EventEmitter

    async def _emit() -> None:
        await EventEmitter(db_path).emit(
            run_id=run_id,
            event_type="checkpoint",
            data={"run_id": run_id, "branch": branch, "pushed_sha": "deadbeef"},
        )
        if timestamp is not None:
            async with store.connect(db_path) as conn:
                await conn.execute(
                    "UPDATE events SET timestamp = ? WHERE run_id = ?",
                    (timestamp, run_id),
                )
                await conn.commit()

    run_sync(_emit())


def seed_worktree(path: Path, *, minutes_ago: int, name: str = "impl.py") -> Path:
    """A real git worktree-shaped directory with one **tracked** file aged
    ``minutes_ago``.

    ``git init`` + ``git add`` only — no commit (which would need a user
    identity) — because ``git ls-files`` reads the **index**, not history. The
    mtime is set explicitly with ``os.utime`` rather than inherited from write
    order, so the test's own clock is the only clock involved.
    """
    init_repo(path)
    target = path / name
    target.write_text("# work in progress\n")
    subprocess.run(["git", "add", name], cwd=path, check=True, capture_output=True)
    stamp = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).timestamp()
    os.utime(target, (stamp, stamp))
    return path


def fetch_row(db_path: Path, run_id: str) -> dict[str, Any] | None:
    async def _select() -> dict[str, Any] | None:
        async with store.connect(db_path) as conn:
            cur = await conn.execute(
                "SELECT status, completed_at FROM runs WHERE run_id = ?", (run_id,)
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return {"status": row[0], "completed_at": row[1]}

    return run_sync(_select())


def fetch_events(db_path: Path, run_id: str, event_type: str) -> list[dict[str, Any]]:
    async def _select() -> list[dict[str, Any]]:
        async with store.connect(db_path) as conn:
            cur = await conn.execute(
                "SELECT data_json FROM events WHERE run_id = ? AND event_type = ?",
                (run_id, event_type),
            )
            rows = await cur.fetchall()
        return [json.loads(r[0]) for r in rows]

    return run_sync(_select())


def count_open_for_ticket(db_path: Path, ticket: str) -> int:
    async def _count() -> int:
        async with store.connect(db_path) as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM runs WHERE ticket = ? AND status = 'open'",
                (ticket,),
            )
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    return run_sync(_count())


def insert_fresh_open(db_path: Path, *, run_id: str, ticket: str) -> bool:
    """Try to insert a new open run for ``ticket``; return True on success.

    The partial unique index ``idx_runs_ticket_open`` rejects a second open row
    for the same ticket — so this succeeds only if reclaim cleared the prior one.
    """

    async def _insert() -> bool:
        try:
            async with store.connect(db_path) as conn:
                await conn.execute(
                    "INSERT INTO runs (run_id, workflow_name, workflow_version, "
                    "status, state_json, inputs_json, base_branch, ticket, "
                    "started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (run_id, "test", 1, "open", "{}", "{}", "dev", ticket,
                     "2026-02-02T00:00:00+00:00"),
                )
                await conn.commit()
            return True
        except Exception:
            return False

    return run_sync(_insert())


def make_sweep_stub(active: list[dict[str, str]]) -> MagicMock:
    """A LinearClient mock for ``--stale``: ``fetch_reclaimable_issues`` returns the
    given list; the revert primitives are no-op AsyncMocks (the single stub serves
    both the enumeration and the per-ticket revert, which the sweep reuses)."""
    mock = MagicMock()
    mock.fetch_reclaimable_issues = AsyncMock(return_value=active)
    mock.transition_to_unstarted = AsyncMock(return_value=None)
    mock.apply_label = AsyncMock(return_value=None)
    mock.post_comment = AsyncMock(return_value=None)
    return mock


def invoke(args: list[str], stub: MagicMock) -> Any:
    # ``reclaim`` resolves its tracker from ``Path.cwd()`` (it has no ``--repo``),
    # so these tests would otherwise pick up the *harness repo's own* CONTEXT.md —
    # now ``tracker: github`` (CAL-1204). Patch the factory + backend directly so
    # the reclaim logic is exercised against the stub regardless of ambient config
    # (the factory→backend wiring is covered by ``test_tracker_seam.py``).
    with (
        patch("harness.cli.reclaim.tracker_client", return_value=stub),
        patch("harness.cli.reclaim.tracker_backend", return_value="linear"),
    ):
        return cli_runner.invoke(app, args)
