"""Tests for ``harness reclaim`` — reclaim a run whose orchestrator died
(CAL-735 single-target, CAL-736 ``--stale`` sweep).

Breakdown items 2 + 3 of the accepted proposal ``stale-run-reclamation``. A run
whose driving session died leaves the Linear ticket stuck *In Progress*, an
``open`` ``runs`` row, and a worktree/branch. ``harness cancel`` only flips the
local row — it never touches Linear, so the ticket stays In Progress and every
dependent stays blocked. ``reclaim`` is the one auditable verb that reverts the
ticket and reconciles the local ledger.

Contract under test:

* ``harness reclaim <run-id>`` (or ``--ticket <ID>``) reverts the Linear ticket
  to **Todo** (``transition_to_unstarted``), applies the ``reclaimed`` label, and
  posts a comment naming the reclaim time and the preserved branch ref.
* In one transaction it flips the matching ``open`` run to ``cancelled`` + stamps
  ``completed_at`` + emits ``workflow_failed`` with ``reason='reclaimed'`` (reusing
  the ``cancel`` ledger transaction), so ``idx_runs_ticket_open`` no longer blocks
  a fresh ``harness start`` on that ticket.
* It **preserves** the branch/worktree (proposal D4) — it never prunes.
* Linear is the load-bearing substrate, so the revert runs **first**; the local
  reconcile is secondary. A Linear failure therefore leaves the run in-flight
  (a retry still sees work to reclaim).
* Refuses cleanly (exit 2) for an unknown run-id, a finished-terminal run, an
  unrecognised status, or an ambiguous invocation (both / neither selector).
  Idempotent — reclaiming an already-``cancelled`` run is a safe no-op.
* ``--stale --project <name> [--older-than 90m]`` enumerates the project's active
  tickets — In Progress **and** In Review (CAL-1103) — and reclaims each idle past
  the threshold (reusing the single-target ``--ticket`` path per ticket), skipping
  any inside the threshold; an empty / already-reverted project is a clean no-op.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

from typer.testing import CliRunner

from harness._time import iso_z
from harness.cli import _review_gate, app, reclaim, reclaim_closable, reclaim_liveness, reclaim_undo
from harness.reclaim_marker import UNRECLAIM_MARKER
from harness.state import store
from harness.tracker_errors import TrackerRequestError
from tests._gitutil import init_repo

cli_runner = CliRunner()


def _iso_minutes_ago(minutes: int) -> str:
    """A trailing-``Z`` UTC timestamp ``minutes`` in the past — the Linear
    ``updatedAt`` shape the sweep parses (proposal D2 staleness signal)."""
    return iso_z(datetime.now(UTC) - timedelta(minutes=minutes))


# ---------------------------------------------------------------------------
# DB seeding / inspection helpers
# ---------------------------------------------------------------------------


def _run_sync(coro: object) -> object:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)  # type: ignore[arg-type]
    finally:
        loop.close()


def _seed_run(
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

    _run_sync(_insert())


def _seed_checkpoint(
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

    _run_sync(_emit())



async def _delete_run(db_path: Path, run_id: str) -> None:
    """Drop a probe row so a following undo is not blocked by its own fixture."""
    async with store.connect(db_path) as conn:
        await conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        await conn.commit()


async def _set_completed_at(db_path: Path, run_id: str, stamp: str) -> None:
    """Order two cancelled runs for the ``--undo --ticket`` newest-wins resolution."""
    async with store.connect(db_path) as conn:
        await conn.execute(
            "UPDATE runs SET completed_at = ? WHERE run_id = ?", (stamp, run_id)
        )
        await conn.commit()


async def _recancel(db_path: Path, run_id: str) -> None:
    """Re-reclaim a run that was previously undone (a *second*, genuine death)."""
    async with store.connect(db_path) as conn:
        await conn.execute(
            "UPDATE runs SET status = 'cancelled', completed_at = ? WHERE run_id = ?",
            ("2026-06-06T00:00:00+00:00", run_id),
        )
        await conn.execute(
            "INSERT INTO events (run_id, node_id, event_type, timestamp, "
            "duration_ms, data_json) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, None, "workflow_failed", "2026-06-06T00:00:00+00:00", None,
             json.dumps({"reason": "reclaimed"})),
        )
        await conn.commit()



async def _cancel_deliberately(db_path: Path, run_id: str) -> None:
    """The operator's own ``harness cancel`` on a run that was undone earlier."""
    async with store.connect(db_path) as conn:
        await conn.execute(
            "UPDATE runs SET status = 'cancelled', completed_at = ? WHERE run_id = ?",
            ("2026-07-07T00:00:00+00:00", run_id),
        )
        await conn.execute(
            "INSERT INTO events (run_id, node_id, event_type, timestamp, "
            "duration_ms, data_json) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, None, "workflow_failed", "2026-07-07T00:00:00+00:00", None,
             json.dumps({"reason": "cancelled"})),
        )
        await conn.commit()


async def _set_status(db_path: Path, run_id: str, status: str) -> None:
    """Force a run's status — stands in for a concurrent verb winning a race."""
    async with store.connect(db_path) as conn:
        await conn.execute(
            "UPDATE runs SET status = ? WHERE run_id = ?", (status, run_id)
        )
        await conn.commit()


def _fetch_row(db_path: Path, run_id: str) -> dict[str, Any] | None:
    async def _select() -> dict[str, Any] | None:
        async with store.connect(db_path) as conn:
            cur = await conn.execute(
                "SELECT status, completed_at FROM runs WHERE run_id = ?", (run_id,)
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return {"status": row[0], "completed_at": row[1]}

    return _run_sync(_select())  # type: ignore[return-value]


def _fetch_events(db_path: Path, run_id: str, event_type: str) -> list[dict[str, Any]]:
    async def _select() -> list[dict[str, Any]]:
        async with store.connect(db_path) as conn:
            cur = await conn.execute(
                "SELECT data_json FROM events WHERE run_id = ? AND event_type = ?",
                (run_id, event_type),
            )
            rows = await cur.fetchall()
        return [json.loads(r[0]) for r in rows]

    return _run_sync(_select())  # type: ignore[return-value]


def _count_open_for_ticket(db_path: Path, ticket: str) -> int:
    async def _count() -> int:
        async with store.connect(db_path) as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM runs WHERE ticket = ? AND status = 'open'",
                (ticket,),
            )
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    return _run_sync(_count())  # type: ignore[return-value]


def _insert_fresh_open(db_path: Path, *, run_id: str, ticket: str) -> bool:
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

    return _run_sync(_insert())  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Linear stub
# ---------------------------------------------------------------------------


def _make_linear_stub(
    *,
    raise_on_transition: Exception | None = None,
) -> MagicMock:
    """Mock LinearClient whose reclamation primitives are AsyncMocks."""
    mock = MagicMock()
    if raise_on_transition is not None:
        mock.transition_to_unstarted = AsyncMock(side_effect=raise_on_transition)
    else:
        mock.transition_to_unstarted = AsyncMock(return_value=None)
    mock.apply_label = AsyncMock(return_value=None)
    mock.post_comment = AsyncMock(return_value=None)
    return mock


def _make_sweep_stub(active: list[dict[str, str]]) -> MagicMock:
    """A LinearClient mock for ``--stale``: ``fetch_reclaimable_issues`` returns the
    given list; the revert primitives are no-op AsyncMocks (the single stub serves
    both the enumeration and the per-ticket revert, which the sweep reuses)."""
    mock = MagicMock()
    mock.fetch_reclaimable_issues = AsyncMock(return_value=active)
    mock.transition_to_unstarted = AsyncMock(return_value=None)
    mock.apply_label = AsyncMock(return_value=None)
    mock.post_comment = AsyncMock(return_value=None)
    return mock


def _invoke(args: list[str], stub: MagicMock) -> Any:
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


# ===========================================================================
# AC: revert Linear (Todo + label + comment) AND flip the local run — run-id
# ===========================================================================


def test_reclaim_reverts_linear_and_flips_run(tmp_path: Path) -> None:
    """The happy path: revert the ticket to Todo + reclaimed label + comment, and
    flip the open run to cancelled with a reclaimed event."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="open", ticket="CAL-735",
              worktree_branch="harness/cal-735")
    _seed_checkpoint(db, "R1")  # the run checkpoint-pushed → branch is durable
    stub = _make_linear_stub()

    result = _invoke(["reclaim", "R1", "--db", str(db)], stub)
    assert result.exit_code == 0, result.output

    # Linear revert.
    stub.transition_to_unstarted.assert_awaited_once_with("CAL-735")
    stub.apply_label.assert_awaited_once_with("CAL-735", "reclaimed")
    stub.post_comment.assert_awaited_once()
    # Comment names the preserved (checkpoint-pushed) branch ref.
    (_ident, body) = stub.post_comment.await_args.args
    assert "harness/cal-735" in body

    # Local ledger: open -> cancelled with a completion stamp.
    row = _fetch_row(db, "R1")
    assert row is not None
    assert row["status"] == "cancelled"
    assert row["completed_at"] is not None

    # The audit event carries reason='reclaimed' (distinct from cancel).
    events = _fetch_events(db, "R1", "workflow_failed")
    assert len(events) == 1
    assert events[0].get("reason") == "reclaimed"


def test_reclaim_frees_the_open_ticket_index(tmp_path: Path) -> None:
    """After reclaim, ``idx_runs_ticket_open`` no longer blocks a fresh open run."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="open", ticket="CAL-735")
    # Before: a second open row for the same ticket is rejected by the index.
    assert _insert_fresh_open(db, run_id="DUP", ticket="CAL-735") is False

    result = _invoke(["reclaim", "R1", "--db", str(db)], _make_linear_stub())
    assert result.exit_code == 0, result.output
    assert _count_open_for_ticket(db, "CAL-735") == 0

    # After: a fresh start (new open row) for the ticket now succeeds.
    assert _insert_fresh_open(db, run_id="R2", ticket="CAL-735") is True


def test_reclaim_preserves_the_worktree(tmp_path: Path) -> None:
    """Proposal D4: reclaim never prunes the worktree/branch."""
    db = tmp_path / "harness.db"
    wt = tmp_path / "wt-cal-735"
    wt.mkdir()
    (wt / "marker.txt").write_text("wip")
    _seed_run(db, run_id="R1", status="open", ticket="CAL-735",
              worktree_path=str(wt), worktree_branch="harness/cal-735")

    result = _invoke(["reclaim", "R1", "--db", str(db)], _make_linear_stub())
    assert result.exit_code == 0, result.output
    # The worktree dir and its WIP marker survive — nothing was pruned.
    assert wt.exists()
    assert (wt / "marker.txt").read_text() == "wip"


def test_reclaim_surfaces_failure_reason_in_status(tmp_path: Path) -> None:
    """End-to-end: ``harness status`` reports ``failure_reason='reclaimed'``."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="open", ticket="CAL-735")
    assert _invoke(["reclaim", "R1", "--db", str(db)],
                   _make_linear_stub()).exit_code == 0

    status_result = cli_runner.invoke(app, ["status", "R1", "--json", "--db", str(db)])
    assert status_result.exit_code == 0, status_result.output
    payload = json.loads(status_result.output)
    assert payload["status"] == "cancelled"
    assert payload["failure_reason"] == "reclaimed"


def test_reclaim_json_output(tmp_path: Path) -> None:
    """``--json`` emits the run, ticket, outcome, and preserved branch."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="open", ticket="CAL-735",
              worktree_branch="harness/cal-735")
    _seed_checkpoint(db, "R1")  # checkpoint-pushed → the branch is resumable
    result = _invoke(["reclaim", "R1", "--json", "--db", str(db)], _make_linear_stub())
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["run_id"] == "R1"
    assert payload["ticket"] == "CAL-735"
    assert payload["outcome"] == "reclaimed"
    assert payload["branch_preserved"] == "harness/cal-735"


def test_reclaim_without_checkpoint_reports_no_resumable_branch(tmp_path: Path) -> None:
    """CAL-738 AC3: a run that never checkpoint-pushed has no durable WIP, so
    reclaim degrades cleanly to *no resumable branch* — it does not advertise a
    local-only branch a later pick could not fetch."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="open", ticket="CAL-735",
              worktree_branch="harness/cal-735")
    # No checkpoint event seeded — nothing was pushed.
    stub = _make_linear_stub()
    result = _invoke(["reclaim", "R1", "--json", "--db", str(db)], stub)
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    assert payload["outcome"] == "reclaimed"
    assert payload["branch_preserved"] is None
    # The comment does not promise a branch a resume could not find.
    (_ident, body) = stub.post_comment.await_args.args
    assert "harness/cal-735" not in body


# ===========================================================================
# --ticket mode
# ===========================================================================


def test_reclaim_by_ticket_flips_open_run(tmp_path: Path) -> None:
    """``--ticket`` resolves the open run for the ticket and reclaims it."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="open", ticket="CAL-900",
              worktree_branch="harness/cal-900")
    stub = _make_linear_stub()
    result = _invoke(["reclaim", "--ticket", "CAL-900", "--db", str(db)], stub)
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("CAL-900")
    assert _fetch_row(db, "R1")["status"] == "cancelled"  # type: ignore[index]


def test_reclaim_by_ticket_with_no_local_run_still_reverts_linear(
    tmp_path: Path,
) -> None:
    """The load-bearing path the ``--stale`` sweep (CAL-736) builds on: a stranded
    ticket with no local open run (the cloud regime) is still reverted on Linear."""
    db = tmp_path / "harness.db"
    _run_sync(store.init_db(db))  # empty ledger — no run rows
    stub = _make_linear_stub()
    result = _invoke(["reclaim", "--ticket", "CAL-901", "--json", "--db", str(db)], stub)
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("CAL-901")
    stub.apply_label.assert_awaited_once_with("CAL-901", "reclaimed")
    payload = json.loads(result.output)
    assert payload["outcome"] == "reverted"
    assert payload["branch_preserved"] is None


# ===========================================================================
# Idempotency
# ===========================================================================


def test_reclaim_already_cancelled_is_a_safe_noop(tmp_path: Path) -> None:
    """Reclaiming an already-``cancelled`` run is a no-op: no second Linear revert,
    no duplicate event, exit 0."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="open", ticket="CAL-735")
    assert _invoke(["reclaim", "R1", "--db", str(db)],
                   _make_linear_stub()).exit_code == 0

    # Second reclaim — the run is now cancelled.
    second_stub = _make_linear_stub()
    result = _invoke(["reclaim", "R1", "--json", "--db", str(db)], second_stub)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["outcome"] == "already_reclaimed"
    # No Linear mutation on the idempotent re-run.
    second_stub.transition_to_unstarted.assert_not_awaited()
    second_stub.post_comment.assert_not_awaited()
    # No duplicate audit event.
    assert len(_fetch_events(db, "R1", "workflow_failed")) == 1


# ===========================================================================
# Refusals
# ===========================================================================


def test_reclaim_unknown_run_refused(tmp_path: Path) -> None:
    """Unknown run-id → exit 2, no Linear mutation."""
    db = tmp_path / "harness.db"
    _run_sync(store.init_db(db))
    stub = _make_linear_stub()
    result = _invoke(["reclaim", "NOPE", "--db", str(db)], stub)
    assert result.exit_code == 2
    stub.transition_to_unstarted.assert_not_awaited()


def test_reclaim_closed_run_refused(tmp_path: Path) -> None:
    """A finished-terminal run (``closed``) is refused — nothing to reclaim."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="closed", ticket="CAL-735")
    stub = _make_linear_stub()
    result = _invoke(["reclaim", "R1", "--db", str(db)], stub)
    assert result.exit_code == 2
    stub.transition_to_unstarted.assert_not_awaited()
    # Row untouched.
    assert _fetch_row(db, "R1") == {"status": "closed", "completed_at": None}


def test_reclaim_unrecognised_status_refused(tmp_path: Path) -> None:
    """A status outside the known set is refused, never silently overwritten."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="bogus", ticket="CAL-735")
    stub = _make_linear_stub()
    result = _invoke(["reclaim", "R1", "--db", str(db)], stub)
    assert result.exit_code == 2
    assert _fetch_row(db, "R1") == {"status": "bogus", "completed_at": None}
    stub.transition_to_unstarted.assert_not_awaited()


def test_reclaim_requires_a_selector(tmp_path: Path) -> None:
    """Neither run-id nor --ticket → exit 2 (ambiguous invocation)."""
    db = tmp_path / "harness.db"
    result = _invoke(["reclaim", "--db", str(db)], _make_linear_stub())
    assert result.exit_code == 2


def test_reclaim_rejects_both_selectors(tmp_path: Path) -> None:
    """Both run-id and --ticket → exit 2 (ambiguous invocation)."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="open", ticket="CAL-735")
    result = _invoke(["reclaim", "R1", "--ticket", "CAL-735", "--db", str(db)],
                     _make_linear_stub())
    assert result.exit_code == 2


def test_reclaim_run_without_ticket_refused(tmp_path: Path) -> None:
    """A run with no associated ticket cannot be reverted — exit 2."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="open", ticket=None)
    stub = _make_linear_stub()
    result = _invoke(["reclaim", "R1", "--db", str(db)], stub)
    assert result.exit_code == 2
    stub.transition_to_unstarted.assert_not_awaited()


# ===========================================================================
# Load-bearing ordering — the Linear revert gates the local reconcile
# ===========================================================================


def test_reclaim_linear_failure_leaves_run_in_flight(tmp_path: Path) -> None:
    """Linear is the load-bearing substrate, so the revert runs first: if it
    fails, the local run stays in-flight (a retry still sees work to reclaim)."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="open", ticket="CAL-735")
    stub = _make_linear_stub(raise_on_transition=RuntimeError("Linear down"))
    result = _invoke(["reclaim", "R1", "--json", "--db", str(db)], stub)
    assert result.exit_code != 0
    # The local flip never happened — the run is still abandonable on retry.
    assert _fetch_row(db, "R1")["status"] == "open"  # type: ignore[index]
    assert _fetch_events(db, "R1", "workflow_failed") == []


def test_reclaim_unconfirmed_transition_leaves_run_in_flight(tmp_path: Path) -> None:
    """``TrackerTransitionUnconfirmed`` subclasses ``TrackerRequestError`` (#233),
    so it takes the same in-flight-preserving path as any other tracker
    failure — pinned directly rather than only inferred from the subclass
    relationship."""
    from harness.tracker_errors import TrackerTransitionUnconfirmed

    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R1", status="open", ticket="CAL-735")
    stub = _make_linear_stub(
        raise_on_transition=TrackerTransitionUnconfirmed("post-write state still In Progress")
    )
    result = _invoke(["reclaim", "R1", "--json", "--db", str(db)], stub)
    assert result.exit_code != 0
    assert _fetch_row(db, "R1")["status"] == "open"  # type: ignore[index]
    assert _fetch_events(db, "R1", "workflow_failed") == []


# ===========================================================================
# Single-source-of-truth — shared helpers
# ===========================================================================


def test_reclaim_uses_shared_resolve_db_path() -> None:
    """``reclaim`` resolves ``--db`` via the one shared ``_query_common`` helper."""
    from harness.cli import _query_common, reclaim

    assert reclaim._resolve_db_path is _query_common._resolve_db_path


def test_reclaim_and_cancel_share_the_abandon_transaction() -> None:
    """``reclaim`` reuses the same ledger-abandon transaction ``cancel`` does —
    the AC's "reuse the harness cancel transaction"."""
    from harness.cli import _abandon, cancel, reclaim

    assert reclaim._abandon_in_ledger is _abandon.abandon_run_in_ledger
    assert cancel._abandon_in_ledger is _abandon.abandon_run_in_ledger


# ===========================================================================
# CAL-736: --stale sweep — enumerate active (In Progress / In Review) tickets,
# reclaim the stale ones (CAL-1103 broadened the enumeration to In Review)
# ===========================================================================


def test_stale_sweep_reclaims_past_threshold(tmp_path: Path) -> None:
    """A ticket idle past the threshold is reclaimed. With no local run (the cloud
    regime) the revert-only path runs — the load-bearing case for the routine."""
    db = tmp_path / "harness.db"
    _run_sync(store.init_db(db))  # empty ledger — cloud regime
    stub = _make_sweep_stub([{"identifier": "CAL-800", "updated_at": _iso_minutes_ago(100)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness v3", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.fetch_reclaimable_issues.assert_awaited_once_with(project="Harness v3")
    stub.transition_to_unstarted.assert_awaited_once_with("CAL-800")

    payload = json.loads(result.output)
    assert payload["mode"] == "stale-sweep"
    assert payload["scanned"] == 1
    assert [r["ticket"] for r in payload["reclaimed"]] == ["CAL-800"]
    assert payload["skipped"] == []


def test_stale_sweep_reclaims_stranded_in_review_ticket(tmp_path: Path) -> None:
    """AC-5 (CAL-1103): a ticket ``review`` parked **In Review** whose orchestrator
    then died is reclaimed to Todo just like a stranded In-Progress one.

    The sweep enumerates both transient started states (``fetch_reclaimable_issues``
    now includes In Review — pinned at the query level in
    ``test_linear_reclaim_primitives``), so an In-Review ticket idle past the
    threshold reaches the same per-ticket revert. Without this, a run that died
    between ``review pass`` and ``close`` would wedge the queue: the ticket sits In
    Review forever and the old sweep, In-Progress-only, never touched it."""
    db = tmp_path / "harness.db"
    _run_sync(store.init_db(db))  # cloud regime: revert-only, no local run
    stub = _make_sweep_stub([{"identifier": "CAL-900", "updated_at": _iso_minutes_ago(120)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness v3", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    # Reverted to Todo — the stranded In-Review ticket re-enters the queue.
    stub.transition_to_unstarted.assert_awaited_once_with("CAL-900")
    payload = json.loads(result.output)
    assert [r["ticket"] for r in payload["reclaimed"]] == ["CAL-900"]


def test_stale_sweep_skips_sub_threshold(tmp_path: Path) -> None:
    """A fresh/active ticket inside the threshold is never reclaimed."""
    db = tmp_path / "harness.db"
    _run_sync(store.init_db(db))
    stub = _make_sweep_stub([{"identifier": "CAL-801", "updated_at": _iso_minutes_ago(10)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness v3", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_not_awaited()
    payload = json.loads(result.output)
    assert payload["reclaimed"] == []
    assert payload["skipped"] == ["CAL-801"]


def test_stale_sweep_mixed_partitions_by_age(tmp_path: Path) -> None:
    """A mixed list is partitioned: only the past-threshold ticket is reclaimed."""
    db = tmp_path / "harness.db"
    _run_sync(store.init_db(db))
    stub = _make_sweep_stub(
        [
            {"identifier": "CAL-810", "updated_at": _iso_minutes_ago(200)},  # stale
            {"identifier": "CAL-811", "updated_at": _iso_minutes_ago(30)},  # fresh
        ]
    )

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness v3", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [r["ticket"] for r in payload["reclaimed"]] == ["CAL-810"]
    assert payload["skipped"] == ["CAL-811"]
    stub.transition_to_unstarted.assert_awaited_once_with("CAL-810")


def test_stale_sweep_honours_custom_older_than(tmp_path: Path) -> None:
    """``--older-than`` lowers the bar: a 30-min-idle ticket is stale under 20m."""
    db = tmp_path / "harness.db"
    _run_sync(store.init_db(db))
    stub = _make_sweep_stub([{"identifier": "CAL-820", "updated_at": _iso_minutes_ago(30)}])

    result = _invoke(
        [
            "reclaim", "--stale", "--older-than", "20m",
            "--project", "Harness v3", "--json", "--db", str(db),
        ],
        stub,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [r["ticket"] for r in payload["reclaimed"]] == ["CAL-820"]
    assert payload["older_than"] == "20m"


def test_stale_sweep_empty_project_is_noop(tmp_path: Path) -> None:
    """No In-Progress tickets → a clean no-op (exit 0, nothing reclaimed)."""
    db = tmp_path / "harness.db"
    _run_sync(store.init_db(db))
    stub = _make_sweep_stub([])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness v3", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["scanned"] == 0
    assert payload["reclaimed"] == []
    assert payload["skipped"] == []
    stub.transition_to_unstarted.assert_not_awaited()


def test_stale_sweep_idempotent_across_ticks(tmp_path: Path) -> None:
    """Safe every tick: once reclaimed a ticket is Todo, so the next sweep's
    enumeration no longer returns it — a true no-op, not a second revert."""
    db = tmp_path / "harness.db"
    _run_sync(store.init_db(db))
    # Tick 1: the ticket is stale and In Progress → reclaimed.
    tick1 = _make_sweep_stub([{"identifier": "CAL-830", "updated_at": _iso_minutes_ago(120)}])
    assert _invoke(
        ["reclaim", "--stale", "--project", "Harness v3", "--db", str(db)], tick1
    ).exit_code == 0
    tick1.transition_to_unstarted.assert_awaited_once_with("CAL-830")
    # Tick 2: it is now Todo, so it is no longer enumerated → nothing to do.
    tick2 = _make_sweep_stub([])
    assert _invoke(
        ["reclaim", "--stale", "--project", "Harness v3", "--db", str(db)], tick2
    ).exit_code == 0
    tick2.transition_to_unstarted.assert_not_awaited()


def test_stale_sweep_full_reclaim_when_local_run_exists(tmp_path: Path) -> None:
    """In the local regime the sweep does a full reclaim: the open run flips to
    cancelled and the comment names the preserved branch (reuses the single path)."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R9", status="open", ticket="CAL-840",
              worktree_branch="harness/cal-840")
    # Durable WIP pushed — back-dated past the threshold so the run reads as dead
    # on *both* signals (#216): an event stamped "now" would make this a live run.
    _seed_checkpoint(
        db, "R9", branch="harness/cal-840", timestamp=_iso_minutes_ago(100)
    )
    stub = _make_sweep_stub([{"identifier": "CAL-840", "updated_at": _iso_minutes_ago(100)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness v3", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    assert _fetch_row(db, "R9")["status"] == "cancelled"  # type: ignore[index]
    assert _fetch_events(db, "R9", "workflow_failed")[0]["reason"] == "reclaimed"
    (_ident, body) = stub.post_comment.await_args.args
    assert "harness/cal-840" in body
    payload = json.loads(result.output)
    assert payload["reclaimed"][0]["outcome"] == "reclaimed"


# ===========================================================================
# #216: liveness = newest of (tracker updatedAt, ledger last-activity)
#
# The tracker timestamp alone is not a heartbeat on the ``github`` backend: a
# Projects-v2 Status write is an *item*-level mutation, so ``start`` (and every
# later verb) leaves the underlying issue's ``updatedAt`` untouched. A live run
# therefore looks arbitrarily stale to a tracker-only sweep. The ledger already
# records the run's real activity, so it is consulted as an additive local
# override — it can only ever spare a live run, never condemn one (amends
# proposal D2, refines D3).
# ===========================================================================


def test_stale_sweep_spares_a_run_whose_ledger_is_fresh(tmp_path: Path) -> None:
    """AC-1 + AC-4, the observed case: tracker-stale but ledger-fresh → not swept.

    Reproduces the tick-#103 incident that filed this ticket. The issue's
    ``updatedAt`` sat 5h stale because nothing a run does bumps it on the GitHub
    backend, while the run itself had checkpointed 20 minutes ago. A tracker-only
    sweep reclaims it underneath a live orchestrator, and the next tick picks the
    same ticket up and duplicates the work.
    """
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="R216", status="open", ticket="216",
              worktree_branch="harness/216")
    _seed_checkpoint(db, "R216", branch="harness/216",
                     timestamp=_iso_minutes_ago(20))  # alive 20m ago
    stub = _make_sweep_stub([{"identifier": "216", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    # The live run is left strictly alone: no revert, no label, no comment.
    stub.transition_to_unstarted.assert_not_awaited()
    stub.apply_label.assert_not_awaited()
    stub.post_comment.assert_not_awaited()
    assert _fetch_row(db, "R216")["status"] == "open"  # type: ignore[index]
    payload = json.loads(result.output)
    assert payload["reclaimed"] == []
    assert payload["skipped"] == ["216"]


def test_stale_sweep_spares_a_freshly_started_run_with_no_events(
    tmp_path: Path,
) -> None:
    """``started_at`` is a liveness signal in its own right, not just events.

    ``start`` emits **no** event (the writable types are ``workflow_failed`` /
    ``review`` / ``close`` / ``checkpoint`` / ``defer`` / ``design`` / ``release``),
    so a run in its first stretch — before ``design`` or any checkpoint — has an
    empty ``events`` set. Keying on events alone would leave exactly that window
    reclaimable while the issue's ``updatedAt`` still predates the run.
    """
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="RFRESH", status="open", ticket="217",
              worktree_branch="harness/217", started_at=_iso_minutes_ago(5))
    stub = _make_sweep_stub([{"identifier": "217", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_not_awaited()
    assert _fetch_row(db, "RFRESH")["status"] == "open"  # type: ignore[index]
    assert json.loads(result.output)["skipped"] == ["217"]


def test_stale_sweep_still_reclaims_when_the_ledger_is_also_stale(
    tmp_path: Path,
) -> None:
    """AC-2: a genuinely dead run is still reclaimed — the fix narrows, not blocks.

    Both signals are past the threshold (``started_at`` old, no events), so the
    sweep reverts the ticket and reconciles the ledger exactly as before.
    """
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="RDEAD", status="open", ticket="218",
              worktree_branch="harness/218", started_at=_iso_minutes_ago(240))
    stub = _make_sweep_stub([{"identifier": "218", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("218")
    assert _fetch_row(db, "RDEAD")["status"] == "cancelled"  # type: ignore[index]
    assert _fetch_events(db, "RDEAD", "workflow_failed")[0]["reason"] == "reclaimed"
    assert json.loads(result.output)["reclaimed"][0]["ticket"] == "218"


def test_stale_sweep_reclaims_when_ledger_has_no_open_run_for_the_ticket(
    tmp_path: Path,
) -> None:
    """AC-2 tail: a reachable-but-silent ledger does not spare the ticket.

    The cloud regime's shape — the DB exists but never saw this run, so it has no
    opinion. Liveness collapses to the tracker timestamp (today's behaviour) and
    the revert-only path runs; a present-but-empty ledger must not read as
    "alive".
    """
    db = tmp_path / "harness.db"
    _run_sync(store.init_db(db))  # reachable ledger, no row for this ticket
    stub = _make_sweep_stub([{"identifier": "219", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("219")
    assert json.loads(result.output)["reclaimed"][0]["ticket"] == "219"


def test_stale_sweep_reclaims_when_no_ledger_exists(tmp_path: Path) -> None:
    """AC-2 tail: an absent DB is the pure cloud regime — tracker-only, unchanged."""
    db = tmp_path / "absent" / "harness.db"  # never created
    stub = _make_sweep_stub([{"identifier": "220", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("220")
    assert json.loads(result.output)["reclaimed"][0]["ticket"] == "220"


def test_stale_sweep_ledger_liveness_respects_a_custom_threshold(
    tmp_path: Path,
) -> None:
    """The ledger is compared against the *same* cutoff as the tracker signal.

    Two runs whose last ledger activity straddles a custom ``--older-than 30m``:
    the 10-minute one is spared, the 50-minute one is reclaimed. Pins that the
    ledger comparison uses the resolved threshold rather than a hardcoded 90m.
    """
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="RIN", status="open", ticket="221",
              worktree_branch="harness/221", started_at=_iso_minutes_ago(10))
    _seed_run(db, run_id="ROUT", status="open", ticket="222",
              worktree_branch="harness/222", started_at=_iso_minutes_ago(50))
    stub = _make_sweep_stub(
        [
            {"identifier": "221", "updated_at": _iso_minutes_ago(300)},
            {"identifier": "222", "updated_at": _iso_minutes_ago(300)},
        ]
    )

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--older-than", "30m",
         "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["skipped"] == ["221"]
    assert [r["ticket"] for r in payload["reclaimed"]] == ["222"]


def test_stale_sweep_partitions_tracker_stale_tickets_by_ledger(
    tmp_path: Path,
) -> None:
    """Each ticket is judged independently; ``scanned`` still counts them all."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="RALIVE", status="open", ticket="223",
              worktree_branch="harness/223", started_at=_iso_minutes_ago(200))
    _seed_checkpoint(db, "RALIVE", branch="harness/223",
                     timestamp=_iso_minutes_ago(15))  # alive despite an old start
    _seed_run(db, run_id="RGONE", status="open", ticket="224",
              worktree_branch="harness/224", started_at=_iso_minutes_ago(200))
    stub = _make_sweep_stub(
        [
            {"identifier": "223", "updated_at": _iso_minutes_ago(300)},
            {"identifier": "224", "updated_at": _iso_minutes_ago(300)},
        ]
    )

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["scanned"] == 2
    assert payload["skipped"] == ["223"]
    assert [r["ticket"] for r in payload["reclaimed"]] == ["224"]
    stub.transition_to_unstarted.assert_awaited_once_with("224")


def test_stale_sweep_does_not_consult_the_ledger_for_a_fresh_ticket(
    tmp_path: Path,
) -> None:
    """The ledger is a second opinion on *candidates*, not a cost on every ticket.

    A tracker-fresh ticket short-circuits before any DB read. Pinned by pointing
    ``--db`` at a path that is a *directory* — opening it as a database would
    raise — so the test fails loudly if the fast path is ever lost.
    """
    not_a_db = tmp_path / "not-a-db"
    not_a_db.mkdir()
    stub = _make_sweep_stub([{"identifier": "225", "updated_at": _iso_minutes_ago(10)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(not_a_db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["skipped"] == ["225"]


# --- --stale invocation refusals ----------------------------------------------


def test_stale_without_project_sweeps_the_whole_queue(tmp_path: Path) -> None:
    """AC-1/AC-2 (#174): ``--stale`` with no ``--project`` is no longer refused — it
    sweeps the whole tracker queue via ``fetch_reclaimable_issues(project=None)``, each
    backend interpreting "unset" as its natural full queue (Linear: the team; GitHub:
    the board). A stale ticket is reverted exactly as in the scoped sweep."""
    db = tmp_path / "harness.db"
    _run_sync(store.init_db(db))
    stub = _make_sweep_stub(
        [{"identifier": "CAL-900", "updated_at": _iso_minutes_ago(120)}]
    )
    result = _invoke(["reclaim", "--stale", "--json", "--db", str(db)], stub)
    assert result.exit_code == 0, result.output
    stub.fetch_reclaimable_issues.assert_awaited_once_with(project=None)
    stub.transition_to_unstarted.assert_awaited_once_with("CAL-900")
    payload = json.loads(result.output)
    assert payload["project"] is None
    assert [r["ticket"] for r in payload["reclaimed"]] == ["CAL-900"]


def test_stale_unscoped_human_output_names_the_whole_queue(tmp_path: Path) -> None:
    """The non-JSON summary reads naturally when unscoped — no bare ``'None'`` where
    a project name would be (exercises the ``project is None`` print branch)."""
    db = tmp_path / "harness.db"
    _run_sync(store.init_db(db))
    result = _invoke(["reclaim", "--stale", "--db", str(db)], _make_sweep_stub([]))
    assert result.exit_code == 0, result.output
    assert "whole tracker queue" in result.output
    assert "None" not in result.output


def test_stale_rejects_a_run_id_selector(tmp_path: Path) -> None:
    """``--stale`` combined with a single-target ``<run-id>`` is ambiguous → exit 2."""
    db = tmp_path / "harness.db"
    _run_sync(store.init_db(db))
    result = _invoke(
        ["reclaim", "R1", "--stale", "--project", "Harness v3", "--db", str(db)],
        _make_sweep_stub([]),
    )
    assert result.exit_code == 2


def test_stale_rejects_a_ticket_selector(tmp_path: Path) -> None:
    """``--stale`` combined with ``--ticket`` is ambiguous → exit 2."""
    db = tmp_path / "harness.db"
    _run_sync(store.init_db(db))
    result = _invoke(
        ["reclaim", "--stale", "--ticket", "CAL-1", "--project", "Harness v3",
         "--db", str(db)],
        _make_sweep_stub([]),
    )
    assert result.exit_code == 2


def test_stale_rejects_a_bad_duration(tmp_path: Path) -> None:
    """A malformed ``--older-than`` is refused (exit 2, like worktrees cleanup)."""
    db = tmp_path / "harness.db"
    _run_sync(store.init_db(db))
    result = _invoke(
        ["reclaim", "--stale", "--older-than", "soon", "--project", "Harness v3",
         "--db", str(db)],
        _make_sweep_stub([]),
    )
    assert result.exit_code == 2


# ===========================================================================
# #254 — the THIRD staleness signal: worktree tracked-file mtime
#
# The ledger signal (#216) reads the newest of ``runs.started_at`` and the
# newest event, which covers a run with no event *yet*. It does not cover a run
# whose last event has already aged past the threshold while the session keeps
# working: the observed case ran ``design``, implemented every AC, then spent
# ~3h retrying a contended gate with zero commits and zero further events, so
# both clocks agreed the ticket looked abandoned. A third signal reads what the
# session was actually touching — the newest mtime among the open run's
# worktree's *tracked* files — and, like the ledger, it can only ever *spare* a
# run, never condemn one the first two checks would have kept.
# ===========================================================================


def _seed_worktree(path: Path, *, minutes_ago: int, name: str = "impl.py") -> Path:
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


def test_stale_sweep_spares_a_run_whose_worktree_is_fresh(tmp_path: Path) -> None:
    """AC-1 + AC-5, the observed case: both clocks stale, worktree fresh → spared.

    Reproduces the 2026-07-29 incident that filed this ticket. The tracker's
    ``updatedAt`` was 5h old (nothing a run does bumps it on the GitHub backend),
    the run's last ledger event was ~2h40m old (a ``design`` that finished long
    before), and yet the session was alive and editing tracked files minutes ago.
    A two-clock sweep reclaims it underneath the live orchestrator and a second
    session then re-implements the finished work from scratch.
    """
    db = tmp_path / "harness.db"
    worktree = _seed_worktree(tmp_path / "wt-254", minutes_ago=5)
    _seed_run(db, run_id="R254", status="open", ticket="254",
              worktree_branch="harness/254", worktree_path=str(worktree),
              started_at=_iso_minutes_ago(240))
    _seed_checkpoint(db, "R254", branch="harness/254",
                     timestamp=_iso_minutes_ago(160))  # last event, already stale
    stub = _make_sweep_stub([{"identifier": "254", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    # The live run is left strictly alone: no revert, no label, no comment.
    stub.transition_to_unstarted.assert_not_awaited()
    stub.apply_label.assert_not_awaited()
    stub.post_comment.assert_not_awaited()
    assert _fetch_row(db, "R254")["status"] == "open"  # type: ignore[index]
    payload = json.loads(result.output)
    assert payload["reclaimed"] == []
    assert payload["skipped"] == ["254"]


def test_stale_sweep_reclaims_when_the_worktree_is_also_stale(tmp_path: Path) -> None:
    """AC-2: all three clocks stale → still reclaimed. The fix narrows, not blocks."""
    db = tmp_path / "harness.db"
    worktree = _seed_worktree(tmp_path / "wt-dead", minutes_ago=180)
    _seed_run(db, run_id="RWDEAD", status="open", ticket="301",
              worktree_branch="harness/301", worktree_path=str(worktree),
              started_at=_iso_minutes_ago(240))
    stub = _make_sweep_stub([{"identifier": "301", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("301")
    assert _fetch_row(db, "RWDEAD")["status"] == "cancelled"  # type: ignore[index]
    assert json.loads(result.output)["reclaimed"][0]["ticket"] == "301"


def test_stale_sweep_reclaims_when_the_run_recorded_no_worktree_path(
    tmp_path: Path,
) -> None:
    """AC-2 tail: a NULL ``worktree_path`` is no opinion, not a spare.

    Every pre-CAL-570 run row, and any row a caller wrote without the column, has
    nothing to probe. The ticket falls back to the tracker+ledger verdict.
    """
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="RNOPATH", status="open", ticket="302",
              worktree_branch="harness/302", worktree_path=None,
              started_at=_iso_minutes_ago(240))
    stub = _make_sweep_stub([{"identifier": "302", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("302")
    assert json.loads(result.output)["reclaimed"][0]["ticket"] == "302"


def test_stale_sweep_reclaims_when_the_worktree_path_is_absent(tmp_path: Path) -> None:
    """AC-2 tail, the cloud regime: a recorded path that does not resolve here.

    ``start`` records the path as the *container* saw it (``/workspace/…``), so a
    ledger read on another host — or in a fresh container — names a directory that
    is simply not there. No opinion, today's behaviour.
    """
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="RGONEPATH", status="open", ticket="303",
              worktree_branch="harness/303",
              worktree_path=str(tmp_path / "never-existed"),
              started_at=_iso_minutes_ago(240))
    stub = _make_sweep_stub([{"identifier": "303", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("303")


def test_stale_sweep_reclaims_when_the_worktree_path_is_not_a_git_toplevel(
    tmp_path: Path,
) -> None:
    """A plain, freshly-written directory that is not a git tree spares nothing."""
    db = tmp_path / "harness.db"
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "recent.txt").write_text("just written\n")  # mtime = now
    _seed_run(db, run_id="RPLAIN", status="open", ticket="304",
              worktree_branch="harness/304", worktree_path=str(plain),
              started_at=_iso_minutes_ago(240))
    stub = _make_sweep_stub([{"identifier": "304", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("304")


def test_stale_sweep_is_not_fooled_by_an_enclosing_repository(tmp_path: Path) -> None:
    """The load-bearing guard: a pruned worktree must not read the MAIN checkout.

    ``git`` walks **up** from a directory that is not itself a top-level, so
    ``ls-files`` run in a stale worktree directory would report the enclosing
    repository's index — the operator's own checkout, whose files are almost
    always freshly edited. Without the ``--show-toplevel`` guard that spares every
    stale ticket and silently switches the whole sweep off.

    The nested directory must hold a **tracked, fresh** file of the enclosing
    repository for this test to discriminate: ``git ls-files`` is prefix-scoped, so
    a nested directory with nothing tracked under it returns an empty listing and
    reads as no-opinion whether the guard is present or not. With a tracked fresh
    file under the prefix, removing the guard makes the probe report *that* file
    and spare the ticket — which is the regression being pinned.
    """
    db = tmp_path / "harness.db"
    enclosing = init_repo(tmp_path / "enclosing")
    nested = enclosing / "stale-worktree"
    nested.mkdir()
    (nested / "fresh.py").write_text("the operator's own live edits\n")
    subprocess.run(["git", "add", "stale-worktree/fresh.py"], cwd=enclosing,
                   check=True, capture_output=True)
    now = datetime.now(UTC).timestamp()
    os.utime(nested / "fresh.py", (now, now))
    _seed_run(db, run_id="RNESTED", status="open", ticket="305",
              worktree_branch="harness/305", worktree_path=str(nested),
              started_at=_iso_minutes_ago(240))
    stub = _make_sweep_stub([{"identifier": "305", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("305")
    assert json.loads(result.output)["reclaimed"][0]["ticket"] == "305"


def test_stale_sweep_reclaims_when_the_worktree_index_is_empty(tmp_path: Path) -> None:
    """A git tree with nothing tracked has no mtime to read — no opinion.

    The file exists and is fresh, but it was never ``git add``ed, so ``ls-files``
    lists nothing. This is the documented limit of the signal (the index bounds
    the scan) and the reason ``--undo`` is the backstop.
    """
    db = tmp_path / "harness.db"
    empty = init_repo(tmp_path / "wt-untracked")
    (empty / "never-added.py").write_text("live edits, never staged\n")
    _seed_run(db, run_id="REMPTY", status="open", ticket="306",
              worktree_branch="harness/306", worktree_path=str(empty),
              started_at=_iso_minutes_ago(240))
    stub = _make_sweep_stub([{"identifier": "306", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("306")


def test_stale_sweep_reclaims_when_a_tracked_file_is_missing_from_the_tree(
    tmp_path: Path,
) -> None:
    """A tracked path deleted from the working tree is skipped, not fatal.

    ``ls-files`` reads the index, so it still names a file ``rm``'d from disk.
    Its ``stat`` raises; the probe must skip that entry and keep going rather
    than abort — here every *remaining* entry is stale, so the ticket is
    reclaimed on the ordinary verdict.
    """
    db = tmp_path / "harness.db"
    worktree = _seed_worktree(tmp_path / "wt-deleted", minutes_ago=200)
    (worktree / "impl.py").unlink()
    _seed_run(db, run_id="RDELETED", status="open", ticket="307",
              worktree_branch="harness/307", worktree_path=str(worktree),
              started_at=_iso_minutes_ago(240))
    stub = _make_sweep_stub([{"identifier": "307", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("307")


def test_stale_sweep_reclaims_when_the_ls_files_probe_times_out(
    tmp_path: Path,
) -> None:
    """A wedged ``git`` degrades to no opinion — it never wedges the pre-flight.

    The Build routine runs this sweep every tick, so a probe that can raise is a
    probe that can stop the loop it exists to unblock. A fired ``TimeoutExpired``
    (and any other ``SubprocessError``/``OSError``) must read as "nothing to say".
    """
    db = tmp_path / "harness.db"
    worktree = _seed_worktree(tmp_path / "wt-wedged", minutes_ago=1)  # fresh!
    _seed_run(db, run_id="RWEDGED", status="open", ticket="308",
              worktree_branch="harness/308", worktree_path=str(worktree),
              started_at=_iso_minutes_ago(240))
    stub = _make_sweep_stub([{"identifier": "308", "updated_at": _iso_minutes_ago(300)}])

    real_run_git = reclaim_liveness.run_git

    def _wedge(cwd: Path, *args: str, **kwargs: Any) -> Any:
        if args[:1] == ("ls-files",):
            raise subprocess.TimeoutExpired(cmd="git ls-files", timeout=15)
        return real_run_git(cwd, *args, **kwargs)

    with patch.object(reclaim_liveness, "run_git", _wedge):
        result = _invoke(
            ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
            stub,
        )
    assert result.exit_code == 0, result.output
    # The worktree is genuinely fresh — only the degraded probe lets it be
    # reclaimed, which is the documented failure posture.
    stub.transition_to_unstarted.assert_awaited_once_with("308")


def test_stale_sweep_reclaims_when_the_ls_files_probe_fails(tmp_path: Path) -> None:
    """A non-zero ``ls-files`` exit is no opinion too (a corrupt index, say).

    The stub emits **partial output alongside** the failure — git can write some
    entries and then die — because that is what makes the check discriminating: an
    implementation that ignored ``returncode`` would parse ``impl.py``, find it
    fresh, and spare a ticket on the strength of a failed probe.
    """
    db = tmp_path / "harness.db"
    worktree = _seed_worktree(tmp_path / "wt-broken", minutes_ago=1)  # fresh!
    _seed_run(db, run_id="RBROKEN", status="open", ticket="309",
              worktree_branch="harness/309", worktree_path=str(worktree),
              started_at=_iso_minutes_ago(240))
    stub = _make_sweep_stub([{"identifier": "309", "updated_at": _iso_minutes_ago(300)}])

    real_run_git = reclaim_liveness.run_git

    def _fail(cwd: Path, *args: str, **kwargs: Any) -> Any:
        if args[:1] == ("ls-files",):
            return subprocess.CompletedProcess(
                args=["git"], returncode=128, stdout="impl.py\0",
                stderr="fatal: index file corrupt",
            )
        return real_run_git(cwd, *args, **kwargs)

    with patch.object(reclaim_liveness, "run_git", _fail):
        result = _invoke(
            ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
            stub,
        )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("309")


def test_stale_sweep_worktree_liveness_respects_a_custom_threshold(
    tmp_path: Path,
) -> None:
    """The worktree mtime is compared against the *resolved* cutoff, not a fixed 90m.

    Two runs whose worktree activity straddles ``--older-than 30m``: the
    10-minute one is spared, the 50-minute one reclaimed. Both have identically
    stale tracker and ledger clocks, so the worktree probe is the only thing
    separating them.
    """
    db = tmp_path / "harness.db"
    fresh = _seed_worktree(tmp_path / "wt-in", minutes_ago=10)
    stale = _seed_worktree(tmp_path / "wt-out", minutes_ago=50)
    _seed_run(db, run_id="RWIN", status="open", ticket="310",
              worktree_branch="harness/310", worktree_path=str(fresh),
              started_at=_iso_minutes_ago(200))
    _seed_run(db, run_id="RWOUT", status="open", ticket="311",
              worktree_branch="harness/311", worktree_path=str(stale),
              started_at=_iso_minutes_ago(200))
    stub = _make_sweep_stub(
        [
            {"identifier": "310", "updated_at": _iso_minutes_ago(300)},
            {"identifier": "311", "updated_at": _iso_minutes_ago(300)},
        ]
    )

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--older-than", "30m",
         "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["scanned"] == 2
    assert payload["skipped"] == ["310"]
    assert [r["ticket"] for r in payload["reclaimed"]] == ["311"]


def test_stale_sweep_does_not_probe_a_tracker_fresh_ticket(tmp_path: Path) -> None:
    """The short-circuit is preserved: a tracker-fresh ticket costs no probe.

    The sweep must not pay a subprocess plus a ``stat`` per tracked file for a
    ticket the tracker itself says is active. Asserted by making the probe raise
    if it is ever reached.
    """
    db = tmp_path / "harness.db"
    worktree = _seed_worktree(tmp_path / "wt-fresh-tracker", minutes_ago=200)
    _seed_run(db, run_id="RFRESHTRACKER", status="open", ticket="312",
              worktree_branch="harness/312", worktree_path=str(worktree),
              started_at=_iso_minutes_ago(240))
    stub = _make_sweep_stub([{"identifier": "312", "updated_at": _iso_minutes_ago(5)}])

    def _never(_worktree: Path) -> None:
        raise AssertionError("the worktree probe ran for a tracker-fresh ticket")

    with patch.object(reclaim_liveness, "worktree_last_activity", _never):
        result = _invoke(
            ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
            stub,
        )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["skipped"] == ["312"]


def test_stale_sweep_does_not_probe_when_the_ledger_is_already_fresh(
    tmp_path: Path,
) -> None:
    """Nor does a ledger-fresh ticket: the cheaper signal short-circuits first."""
    db = tmp_path / "harness.db"
    worktree = _seed_worktree(tmp_path / "wt-ledger-fresh", minutes_ago=200)
    _seed_run(db, run_id="RLEDGERFRESH", status="open", ticket="313",
              worktree_branch="harness/313", worktree_path=str(worktree),
              started_at=_iso_minutes_ago(10))
    stub = _make_sweep_stub([{"identifier": "313", "updated_at": _iso_minutes_ago(300)}])

    def _never(_worktree: Path) -> None:
        raise AssertionError("the worktree probe ran for a ledger-fresh ticket")

    with patch.object(reclaim_liveness, "worktree_last_activity", _never):
        result = _invoke(
            ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
            stub,
        )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["skipped"] == ["313"]


def test_stale_sweep_does_not_probe_when_there_is_no_open_run(tmp_path: Path) -> None:
    """No open run row → no probe at all, and the revert-only path runs unchanged."""
    db = tmp_path / "harness.db"
    _run_sync(store.init_db(db))  # reachable ledger, no row for this ticket
    stub = _make_sweep_stub([{"identifier": "314", "updated_at": _iso_minutes_ago(300)}])

    def _never(_worktree: Path) -> None:
        raise AssertionError("the worktree probe ran with no open run row")

    with patch.object(reclaim_liveness, "worktree_last_activity", _never):
        result = _invoke(
            ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
            stub,
        )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("314")


# ===========================================================================
# #255 — the THIRD sweep outcome: a stranded run that is *closable*, not stale
#
# A run that passed ``review`` and then lost its session is still ``open``, and
# ``close`` has no spend breaker — so it was closable in place the whole time
# (proposal ``resume-earned-stages`` F3). Reverting it to Todo throws away a
# passing review and forces a fresh run to re-design and re-review to reach a
# ``close`` that was one command away.
#
# The check is additive in the same one-way shape as #216/#254: it can only ever
# divert a ticket the sweep was *already about to revert*, and every uncertainty
# resolves to "not closable" — i.e. to today's behaviour.
#
# Ordering is load-bearing. ``locally_live`` is checked **first**, so a live
# session paused at a clean, previously-passed HEAD reads as ``skipped`` (spared
# because alive) rather than ``closable`` (finished, and therefore drainable by
# #256). The proposal's risk section is explicit that the two mean opposite
# things downstream.
# ===========================================================================


def _seed_closable_worktree(
    path: Path, *, minutes_ago: int, name: str = "impl.py"
) -> tuple[Path, str]:
    """A real worktree with a **commit**, aged ``minutes_ago`` → ``(path, head_sha)``.

    Distinct from :func:`_seed_worktree` in the one way that matters here:
    ``tests._gitutil.init_repo`` deliberately makes no commit (it needs no user
    identity), so ``git rev-parse HEAD`` fails there. A closable fixture needs a
    real HEAD, so this commits with an inline identity.

    ``minutes_ago`` back-dates the tracked file's mtime **past the threshold**.
    That is not cosmetic: a freshly written worktree file makes #254's mtime
    signal read *fresh*, the ticket is spared as ``locally_live``, and a closable
    test then goes green while never reaching the predicate at all.
    """
    init_repo(path)
    target = path / name
    target.write_text("# reviewed work\n")
    env_id = [
        "-c", "user.email=t@example.com",
        "-c", "user.name=T",
    ]
    subprocess.run(["git", "add", name], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", *env_id, "commit", "-q", "-m", "reviewed"],
        cwd=path, check=True, capture_output=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path, check=True, capture_output=True, text=True,
    ).stdout.strip()
    stamp = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).timestamp()
    os.utime(target, (stamp, stamp))
    return path, head


_GREEN_GATE = {"gate_ran": True, "gate_command": "bash scripts/verify.sh", "gate_exit_code": 0}


def _seed_review(
    db_path: Path,
    run_id: str,
    *,
    reviewed_sha: str,
    verdict: str = "pass",
    gate: dict[str, Any] | None = None,
    timestamp: str,
) -> None:
    """Append a ``review`` event mirroring what ``harness review`` records.

    ``gate`` defaults to the evidence a green verify gate records (CAL-1082);
    pass ``gate={}`` for the legacy shape the close gate's backstop refuses.

    ``timestamp`` is **required**, unlike :func:`_seed_checkpoint`'s optional
    back-date, because every caller here needs it: ``EventEmitter`` stamps *now*,
    and a fresh event makes the run's ledger clock read live — which sends the
    ticket to ``skipped`` before the closable predicate is ever consulted.
    """
    from harness.events.emitter import EventEmitter

    async def _emit() -> None:
        await EventEmitter(db_path).emit(
            run_id=run_id,
            event_type="review",
            data={
                "run_id": run_id,
                "reviewed_sha": reviewed_sha,
                "verdict": verdict,
                "issues": [],
                "engine": "claude",
                "created_at": timestamp,
                **(_GREEN_GATE if gate is None else gate),
            },
        )
        async with store.connect(db_path) as conn:
            await conn.execute(
                "UPDATE events SET timestamp = ? WHERE run_id = ? AND event_type = 'review'",
                (timestamp, run_id),
            )
            await conn.commit()

    _run_sync(_emit())


def _seed_closable(
    tmp_path: Path,
    *,
    ticket: str,
    run_id: str,
    verdict: str = "pass",
    gate: dict[str, Any] | None = None,
    sha_override: str | None = None,
    dirty: bool = False,
) -> Path:
    """The full closable fixture: aged committed worktree + open run + back-dated
    review. Returns the worktree path.

    Every knob is a *negative* case's single deviation, so a negative test differs
    from the positive one in exactly the fact under test.
    """
    worktree, head = _seed_closable_worktree(tmp_path / f"wt-{ticket}", minutes_ago=200)
    if dirty:
        (worktree / "uncommitted.py").write_text("# edited after the pass\n")
    db = tmp_path / "harness.db"
    _seed_run(
        db, run_id=run_id, status="open", ticket=ticket,
        worktree_branch=f"harness/{ticket}", worktree_path=str(worktree),
        started_at=_iso_minutes_ago(400),
    )
    _seed_review(
        db, run_id,
        reviewed_sha=sha_override if sha_override is not None else head,
        verdict=verdict, gate=gate, timestamp=_iso_minutes_ago(180),
    )
    return worktree


def test_stale_sweep_reports_a_closable_run_instead_of_reclaiming_it(
    tmp_path: Path,
) -> None:
    """AC-1 + AC-2, the load-bearing case: a past-threshold open run whose clean
    worktree HEAD carries a gate-evidenced ``pass`` is reported ``closable`` and
    left completely alone.

    "Left alone" is asserted against the tracker recording **zero** mutations and
    against the ledger row still reading ``open`` with no ``workflow_failed``
    event — not merely against the ticket's absence from ``reclaimed``, which a
    silent skip would also satisfy.
    """
    db = tmp_path / "harness.db"
    worktree = _seed_closable(tmp_path, ticket="400", run_id="RCLOSE")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=worktree, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    stub = _make_sweep_stub([{"identifier": "400", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    assert payload["closable"] == [
        {"ticket": "400", "run_id": "RCLOSE", "head_sha": head}
    ]
    assert payload["reclaimed"] == []
    assert payload["skipped"] == []

    # AC-1: no tracker mutation of any kind.
    stub.transition_to_unstarted.assert_not_awaited()
    stub.apply_label.assert_not_awaited()
    stub.post_comment.assert_not_awaited()
    # AC-2: the run is still open and finishable.
    assert _fetch_row(db, "RCLOSE")["status"] == "open"  # type: ignore[index]
    assert _fetch_events(db, "RCLOSE", "workflow_failed") == []


def test_stale_sweep_reports_the_same_closable_run_on_every_tick(
    tmp_path: Path,
) -> None:
    """The classification is stable and idempotent — it writes nothing, so it
    cannot consume itself.

    The sweep leaves a closable ticket ``open`` and In Review, so every later tick
    reports it again until something closes it. That repetition is intended (the
    report is the only signal #256 has), and this pins that repeating it costs no
    tracker mutation and no ledger write.
    """
    db = tmp_path / "harness.db"
    _seed_closable(tmp_path, ticket="401", run_id="RTWICE")
    issues = [{"identifier": "401", "updated_at": _iso_minutes_ago(300)}]

    for _tick in range(2):
        stub = _make_sweep_stub(issues)
        result = _invoke(
            ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
            stub,
        )
        assert result.exit_code == 0, result.output
        assert [c["ticket"] for c in json.loads(result.output)["closable"]] == ["401"]
        stub.transition_to_unstarted.assert_not_awaited()

    assert _fetch_row(db, "RTWICE")["status"] == "open"  # type: ignore[index]
    assert _fetch_events(db, "RTWICE", "workflow_failed") == []


def test_stale_sweep_reclaims_a_pass_bound_to_a_different_sha(tmp_path: Path) -> None:
    """AC-3: HEAD advanced after the review, so the pass no longer covers the tree
    that would merge — ``close`` refuses ``stale_review``, so this is not closable."""
    db = tmp_path / "harness.db"
    _seed_closable(tmp_path, ticket="402", run_id="RSTALE", sha_override="0" * 40)
    stub = _make_sweep_stub([{"identifier": "402", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["closable"] == []
    stub.transition_to_unstarted.assert_awaited_once_with("402")
    assert _fetch_row(db, "RSTALE")["status"] == "cancelled"  # type: ignore[index]


def test_stale_sweep_reclaims_a_pass_without_verify_gate_evidence(
    tmp_path: Path,
) -> None:
    """AC-3: the CAL-1082 backstop applies identically here.

    A pass written by a harness predating the verify gate carries no ``gate_ran``
    key at all. ``close`` refuses it (``no_gate_evidence``), so reporting it
    closable would strand the ticket as neither reclaimed nor closed — the one
    outcome worse than either.
    """
    db = tmp_path / "harness.db"
    _seed_closable(tmp_path, ticket="403", run_id="RNOGATE", gate={})
    stub = _make_sweep_stub([{"identifier": "403", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["closable"] == []
    stub.transition_to_unstarted.assert_awaited_once_with("403")


def test_stale_sweep_reclaims_a_run_whose_only_verdict_is_fail(tmp_path: Path) -> None:
    """AC-3: a ``fail`` at HEAD is not a pass. The query selects on the verdict, so
    a run that reviewed and lost is reclaimed exactly as before."""
    db = tmp_path / "harness.db"
    _seed_closable(tmp_path, ticket="404", run_id="RFAIL", verdict="fail")
    stub = _make_sweep_stub([{"identifier": "404", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["closable"] == []
    stub.transition_to_unstarted.assert_awaited_once_with("404")


def test_stale_sweep_reclaims_a_closable_looking_run_with_a_dirty_worktree(
    tmp_path: Path,
) -> None:
    """A HEAD-matching, gate-evidenced pass over a **dirty** tree is not closable.

    This case is not in the ticket's AC list; it comes from the ticket's own rule
    that the predicate must not report closable what ``close`` will refuse. A run
    that passed review and then died leaving an uncommitted edit has a perfect
    pass and a tree ``close`` rejects (``dirty_worktree``, its second gate
    conjunct) — so without the clean-tree check the ticket would be neither
    reclaimed nor closable, forever.
    """
    db = tmp_path / "harness.db"
    _seed_closable(tmp_path, ticket="405", run_id="RDIRTY", dirty=True)
    stub = _make_sweep_stub([{"identifier": "405", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["closable"] == []
    stub.transition_to_unstarted.assert_awaited_once_with("405")


def test_stale_sweep_does_not_call_a_closable_run_inside_an_enclosing_repo(
    tmp_path: Path,
) -> None:
    """A pruned worktree directory must not borrow the *enclosing* repo's HEAD.

    ``git`` walks up from a directory whose worktree registration is gone, so
    without the top-level guard the probe would read the main checkout's HEAD —
    and if a pass happened to be recorded for that SHA the sweep would report a
    dead ticket as closable. The fixture makes that concrete: the run's recorded
    pass names the *outer* repo's HEAD, and the inner path is not its own repo.
    """
    outer, outer_head = _seed_closable_worktree(tmp_path / "outer", minutes_ago=200)
    inner = outer / "nested"
    inner.mkdir()
    db = tmp_path / "harness.db"
    _seed_run(
        db, run_id="RNESTED", status="open", ticket="406",
        worktree_branch="harness/406", worktree_path=str(inner),
        started_at=_iso_minutes_ago(400),
    )
    _seed_review(
        db, "RNESTED", reviewed_sha=outer_head, timestamp=_iso_minutes_ago(180)
    )
    stub = _make_sweep_stub([{"identifier": "406", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["closable"] == []
    stub.transition_to_unstarted.assert_awaited_once_with("406")


def test_stale_sweep_reclaims_when_a_closable_probe_is_wedged(tmp_path: Path) -> None:
    """A wedged ``git`` degrades to *not closable* — it never wedges the pre-flight.

    Fires on ``status`` rather than ``rev-parse`` so the probe has already got a
    HEAD: that is the ordering where an implementation which let the exception
    escape, or which read a failed status as a clean tree, would differ.
    """
    db = tmp_path / "harness.db"
    _seed_closable(tmp_path, ticket="407", run_id="RPROBE")
    stub = _make_sweep_stub([{"identifier": "407", "updated_at": _iso_minutes_ago(300)}])

    # Reached through the already-imported module rather than
    # ``from harness import close_merge``: importing it top-level here would run
    # ahead of ``harness.cli`` and trip the close_merge ↔ harness.cli cycle that
    # ``close.py``'s own import comment documents.
    close_merge = reclaim_closable.close_merge
    real_run_git = close_merge.run_git

    def _wedge(cwd: Path, *args: str, **kwargs: Any) -> Any:
        if args[:1] == ("status",):
            raise subprocess.TimeoutExpired(cmd="git status", timeout=15)
        return real_run_git(cwd, *args, **kwargs)

    with patch.object(close_merge, "run_git", _wedge):
        result = _invoke(
            ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
            stub,
        )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["closable"] == []
    stub.transition_to_unstarted.assert_awaited_once_with("407")


def test_stale_sweep_prefers_alive_over_closable(tmp_path: Path) -> None:
    """The ordering that keeps #256 from merging out from under a live session.

    This run satisfies **both** rules: its worktree is fresh (a live session) and
    its clean HEAD carries a gate-evidenced pass. It must read as ``skipped``, not
    ``closable`` — *spared because alive* must not be drained, *closable because
    finished* must be, and only the check order distinguishes them.
    """
    db = tmp_path / "harness.db"
    worktree, head = _seed_closable_worktree(tmp_path / "wt-live", minutes_ago=2)
    _seed_run(
        db, run_id="RLIVE", status="open", ticket="408",
        worktree_branch="harness/408", worktree_path=str(worktree),
        started_at=_iso_minutes_ago(400),
    )
    _seed_review(db, "RLIVE", reviewed_sha=head, timestamp=_iso_minutes_ago(180))
    stub = _make_sweep_stub([{"identifier": "408", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["skipped"] == ["408"]
    assert payload["closable"] == []
    stub.transition_to_unstarted.assert_not_awaited()


def test_stale_sweep_without_a_ledger_is_byte_identical_to_the_old_behaviour(
    tmp_path: Path,
) -> None:
    """AC-4, the cloud regime: no DB on disk → the predicate is unreachable.

    Asserts the awaited **call sequence**, not just the counts, so a change that
    reordered or added a tracker call would fail here even if the totals matched.
    """
    db = tmp_path / "harness.db"  # never created
    stub = _make_sweep_stub(
        [
            {"identifier": "409", "updated_at": _iso_minutes_ago(300)},
            {"identifier": "410", "updated_at": _iso_minutes_ago(10)},
            {"identifier": "411", "updated_at": _iso_minutes_ago(400)},
        ]
    )

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["closable"] == []
    assert [r["ticket"] for r in payload["reclaimed"]] == ["409", "411"]
    assert payload["skipped"] == ["410"]
    assert stub.transition_to_unstarted.await_args_list == [call("409"), call("411")]


def test_stale_sweep_spends_nothing_on_a_within_threshold_ticket(
    tmp_path: Path,
) -> None:
    """AC-5, by instrumentation rather than inference.

    A tracker-fresh ticket short-circuits before any local work at all. Every seam
    the closable path could reach is replaced with a raising stub, so the test
    fails loudly if the predicate is ever consulted — asserting the *absence* of
    work, which reading the output alone cannot do.
    """
    db = tmp_path / "harness.db"
    _seed_closable(tmp_path, ticket="412", run_id="RFRESH")
    stub = _make_sweep_stub([{"identifier": "412", "updated_at": _iso_minutes_ago(5)}])

    async def _never_closable(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the closable predicate ran for a tracker-fresh ticket")

    def _never_git(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("a git probe ran for a tracker-fresh ticket")

    with (
        patch.object(reclaim, "closable_run", _never_closable),
        patch.object(reclaim_closable, "rev_parse_head", _never_git),
        patch.object(reclaim_liveness, "worktree_last_activity", _never_git),
    ):
        result = _invoke(
            ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
            stub,
        )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["skipped"] == ["412"]


def test_stale_sweep_outcomes_are_disjoint_and_total(tmp_path: Path) -> None:
    """AC-6: every scanned ticket lands in exactly one list.

    Four tickets, one per outcome path — tracker-fresh, locally live, closable,
    dead. Disjointness alone would be satisfied by silently dropping a ticket, so
    the totality identity is asserted alongside it.
    """
    db = tmp_path / "harness.db"
    # closable: aged worktree, HEAD-matching green pass.
    _seed_closable(tmp_path, ticket="420", run_id="RMIXCLOSE")
    # locally live: fresh worktree, no review at all.
    live_wt = _seed_worktree(tmp_path / "wt-mixlive", minutes_ago=2)
    _seed_run(
        db, run_id="RMIXLIVE", status="open", ticket="421",
        worktree_branch="harness/421", worktree_path=str(live_wt),
        started_at=_iso_minutes_ago(400),
    )
    # dead: no local run row at all (the revert-only path).
    stub = _make_sweep_stub(
        [
            {"identifier": "419", "updated_at": _iso_minutes_ago(5)},    # fresh
            {"identifier": "420", "updated_at": _iso_minutes_ago(300)},  # closable
            {"identifier": "421", "updated_at": _iso_minutes_ago(300)},  # live
            {"identifier": "422", "updated_at": _iso_minutes_ago(300)},  # dead
        ]
    )

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    reclaimed = {r["ticket"] for r in payload["reclaimed"]}
    skipped = set(payload["skipped"])
    closable = {c["ticket"] for c in payload["closable"]}
    assert reclaimed == {"422"}
    assert skipped == {"419", "421"}
    assert closable == {"420"}
    assert reclaimed & skipped == set()
    assert reclaimed & closable == set()
    assert skipped & closable == set()
    assert payload["scanned"] == len(reclaimed) + len(skipped) + len(closable) == 4


def test_stale_sweep_human_output_names_a_closable_run(tmp_path: Path) -> None:
    """The non-``--json`` summary carries the third outcome too — the operator
    reading a pre-flight must see that a ticket is waiting on ``close``, not
    silently absent from both other lists."""
    db = tmp_path / "harness.db"
    _seed_closable(tmp_path, ticket="423", run_id="RHUMAN")
    stub = _make_sweep_stub([{"identifier": "423", "updated_at": _iso_minutes_ago(300)}])

    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--db", str(db)], stub
    )
    assert result.exit_code == 0, result.output
    assert "1 closable" in result.output
    assert "closable  423" in result.output
    assert "harness close will finish it" in result.output


def test_closable_predicate_reads_the_verdict_through_the_payload_constant(
    tmp_path: Path,
) -> None:
    """AC-7, behaviourally: the payload constant is the query's real input.

    A source grep proves only that the constant is *imported*. Repointing it at a
    field that does not exist must turn a previously-closable ticket into a
    reclaimed one — which is what proves the query reads it rather than a literal
    ``$.verdict`` spelled alongside it.
    """
    db = tmp_path / "harness.db"
    _seed_closable(tmp_path, ticket="424", run_id="RCONST")
    stub = _make_sweep_stub([{"identifier": "424", "updated_at": _iso_minutes_ago(300)}])

    with patch.object(_review_gate, "REVIEW_VERDICT_PATH", "$.not_the_verdict"):
        result = _invoke(
            ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
            stub,
        )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["closable"] == []
    stub.transition_to_unstarted.assert_awaited_once_with("424")


def test_review_gate_modules_hold_no_raw_json_path_literal() -> None:
    """AC-7, structurally: neither shared module re-spells a payload key.

    ``run-ledger.md`` requires a reader to import the field-derived constant so a
    key rename breaks at the model rather than silently degrading a gate.
    """
    from harness.cli import _review_gate as gate_mod

    for module in (gate_mod, reclaim_closable):
        source = Path(module.__file__).read_text()  # type: ignore[arg-type]
        body = source.split('"""', 2)[-1]  # skip the module docstring
        assert "$.reviewed_sha" not in body, module.__name__
        assert "$.verdict" not in body, module.__name__


def test_closable_predicate_agrees_with_the_close_gate(tmp_path: Path) -> None:
    """The anti-drift pin: the sweep's prediction and ``close``'s gate are one rule.

    A sweep that reports *closable* for a run ``close`` then refuses leaves the
    ticket neither reclaimed nor closed. Rather than trusting that two
    implementations agree, both call the same module — and this asserts the
    equivalence directly across the whole ledger matrix, so a future divergence
    fails here.
    """
    from harness.cli import close as close_mod

    matrix: list[tuple[str, dict[str, Any]]] = [
        ("no pass at all", {"verdict": "fail"}),
        ("pass at another sha", {"sha_override": "0" * 40}),
        ("pass without gate evidence", {"gate": {}}),
        ("pass with gate not configured",
         {"gate": {"gate_ran": False, "gate_reason": "not_configured"}}),
        ("green pass", {}),
    ]
    for index, (label, kwargs) in enumerate(matrix):
        case_dir = tmp_path / f"case-{index}"
        case_dir.mkdir()
        db = case_dir / "harness.db"
        worktree = _seed_closable(
            case_dir, ticket=f"5{index:02d}", run_id=f"RAGREE{index}", **kwargs
        )
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=worktree, check=True,
            capture_output=True, text=True,
        ).stdout.strip()

        liveness = _run_sync(reclaim_liveness.open_run_liveness(db, f"5{index:02d}"))
        predicted = _run_sync(reclaim_closable.closable_run(db, liveness))  # type: ignore[arg-type]
        gate = _run_sync(close_mod._evaluate_gate(db, f"RAGREE{index}", head))

        assert (predicted is not None) == (gate is None), (
            f"{label}: sweep says closable={predicted is not None}, "
            f"close gate says {gate}"
        )


# ===========================================================================
# #254 — ``reclaim --undo``: reversing a confirmed false-positive reclaim
#
# The worktree signal above narrows how often a live run is reclaimed; it cannot
# eliminate it (a worktree can vanish, and an untracked-only edit is invisible to
# the index). Before this arm existed, recovery from a false positive meant a
# hand-rolled ``git push`` plus a hand-written tracker comment — bypassing the
# ledger entirely, which is the one thing the verb loop exists to prevent.
#
# Undo's authority is deliberately bounded: it re-opens only a run it can *prove*
# was reclaim-cancelled, and refuses outright when a competing open run exists
# rather than arbitrating between two sessions.
# ===========================================================================


def _make_undo_stub(*, raise_on_transition: Exception | None = None) -> MagicMock:
    """A tracker mock carrying the three seam methods undo restores a ticket with.

    Undo adds **no** backend method: ``transition_to_in_progress`` /
    ``remove_label`` / ``post_comment`` all already exist for `start` and
    `release`, so both backends are served unchanged.
    """
    mock = MagicMock()
    if raise_on_transition is not None:
        mock.transition_to_in_progress = AsyncMock(side_effect=raise_on_transition)
    else:
        mock.transition_to_in_progress = AsyncMock(return_value=None)
    mock.remove_label = AsyncMock(return_value=None)
    mock.post_comment = AsyncMock(return_value=None)
    return mock


def _invoke_undo(args: list[str], stub: MagicMock, *, backend: str = "linear") -> Any:
    """``_invoke`` for the undo arm: the client is resolved in ``reclaim_undo``."""
    with (
        patch("harness.cli.reclaim_undo.tracker_client", return_value=stub),
        patch("harness.cli.reclaim.tracker_backend", return_value=backend),
    ):
        return cli_runner.invoke(app, args)


def _seed_reclaimed(
    db_path: Path,
    *,
    run_id: str,
    ticket: str,
    reason: str = "reclaimed",
) -> None:
    """A run left exactly as ``reclaim`` leaves it: ``cancelled`` + the event.

    ``reason`` is a parameter because the *reason* is the whole gate: a run
    cancelled by ``harness cancel`` (``reason='cancelled'``) is an intentional
    abandon, not a false positive, and must not be undoable.
    """
    _seed_run(db_path, run_id=run_id, status="cancelled", ticket=ticket,
              worktree_branch=f"harness/{ticket}")

    async def _finish() -> None:
        async with store.connect(db_path) as conn:
            await conn.execute(
                "UPDATE runs SET completed_at = ? WHERE run_id = ?",
                ("2026-01-01T01:00:00+00:00", run_id),
            )
            await conn.execute(
                "INSERT INTO events (run_id, node_id, event_type, timestamp, "
                "duration_ms, data_json) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, None, "workflow_failed", "2026-01-01T01:00:00+00:00", None,
                 json.dumps({"reason": reason})),
            )
            await conn.commit()

    _run_sync(_finish())


def test_undo_restores_the_ticket_and_reopens_the_run(tmp_path: Path) -> None:
    """AC-3, the happy path — all five effects of a reversal."""
    db = tmp_path / "harness.db"
    _seed_reclaimed(db, run_id="RUNDO", ticket="401")
    stub = _make_undo_stub()

    result = _invoke_undo(
        ["reclaim", "--undo", "RUNDO", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 0, result.output
    # 1-3. the tracker is restored: In Progress, label dropped, comment posted.
    stub.transition_to_in_progress.assert_awaited_once_with("401")
    stub.remove_label.assert_awaited_once_with("401", "reclaimed")
    stub.post_comment.assert_awaited_once()
    assert UNRECLAIM_MARKER in stub.post_comment.await_args.args[1]
    # 4. the row is open again, and no longer claims to have ended.
    row = _fetch_row(db, "RUNDO")
    assert row["status"] == "open"  # type: ignore[index]
    assert row["completed_at"] is None  # type: ignore[index]
    # 5. the reversal is appended; the reclamation event SURVIVES (append-only).
    undone = _fetch_events(db, "RUNDO", "reclaim_undone")
    assert len(undone) == 1
    assert undone[0]["ticket"] == "401"
    assert _fetch_events(db, "RUNDO", "workflow_failed")[0]["reason"] == "reclaimed"
    payload = json.loads(result.output)
    assert payload["outcome"] == "undone"
    assert payload["run_id"] == "RUNDO"


def test_undo_frees_the_reopened_run_for_the_open_ticket_index(tmp_path: Path) -> None:
    """The re-opened row occupies ``idx_runs_ticket_open`` again.

    Reclaim's whole local purpose is to *clear* that slot so a fresh ``start``
    is not blocked; undo must put it back, or two sessions could both start on
    the ticket the reversal just restored.
    """
    db = tmp_path / "harness.db"
    _seed_reclaimed(db, run_id="RSLOT", ticket="402")
    assert _insert_fresh_open(db, run_id="RPROBE0", ticket="402") is True
    # Undo cannot run while that probe row holds the slot — remove it and retry.
    _run_sync(_delete_run(db, "RPROBE0"))

    result = _invoke_undo(
        ["reclaim", "--undo", "RSLOT", "--json", "--db", str(db)], _make_undo_stub()
    )
    assert result.exit_code == 0, result.output
    assert _count_open_for_ticket(db, "402") == 1
    assert _insert_fresh_open(db, run_id="RPROBE1", ticket="402") is False


def test_undo_refuses_when_the_ticket_already_has_another_open_run(
    tmp_path: Path,
) -> None:
    """The observed duplicate-session case: refuse, and touch nothing.

    A second session already ran ``harness start`` on the reverted ticket. Undo
    must not arbitrate between two sessions — the duplicate may hold real work —
    so it refuses, names the competing run, and performs **no** tracker write
    (the operator runs ``harness cancel`` on the duplicate first).
    """
    db = tmp_path / "harness.db"
    _seed_reclaimed(db, run_id="RLOSER", ticket="403")
    assert _insert_fresh_open(db, run_id="RWINNER", ticket="403") is True
    stub = _make_undo_stub()

    result = _invoke_undo(
        ["reclaim", "--undo", "RLOSER", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == "ticket_has_open_run"
    assert "RWINNER" in payload["error"]
    stub.transition_to_in_progress.assert_not_awaited()
    stub.remove_label.assert_not_awaited()
    stub.post_comment.assert_not_awaited()
    assert _fetch_row(db, "RLOSER")["status"] == "cancelled"  # type: ignore[index]


def test_undo_refuses_a_deliberately_cancelled_run(tmp_path: Path) -> None:
    """``harness cancel`` is an intentional abandon, not a false positive."""
    db = tmp_path / "harness.db"
    _seed_reclaimed(db, run_id="RCANCEL", ticket="404", reason="cancelled")
    stub = _make_undo_stub()

    result = _invoke_undo(
        ["reclaim", "--undo", "RCANCEL", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "not_reclaimed"
    stub.transition_to_in_progress.assert_not_awaited()
    assert _fetch_row(db, "RCANCEL")["status"] == "cancelled"  # type: ignore[index]


def test_undo_refuses_a_cancelled_run_with_no_abandon_event(tmp_path: Path) -> None:
    """A ``cancelled`` row with no ``workflow_failed`` at all cannot be proven
    to have been reclaimed, so it is refused rather than assumed."""
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="RNOEVENT", status="cancelled", ticket="405",
              worktree_branch="harness/405")
    stub = _make_undo_stub()

    result = _invoke_undo(
        ["reclaim", "--undo", "RNOEVENT", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "not_reclaimed"
    stub.transition_to_in_progress.assert_not_awaited()


def test_undo_refuses_an_open_run_that_was_never_reclaimed(tmp_path: Path) -> None:
    """An ``open`` run is 'not cancelled' — it must read as ``not_reclaimed``,
    NOT as an idempotent ``already_open`` no-op.

    The two outcomes overlap textually (an open run is indeed not cancelled), so
    the distinction is made on evidence: ``already_open`` requires a recorded
    ``reclaim_undone`` event proving a prior reversal. Without one, undoing a
    perfectly live run would be a silent no-op that reports success.
    """
    db = tmp_path / "harness.db"
    _seed_run(db, run_id="RLIVE", status="open", ticket="406",
              worktree_branch="harness/406")
    stub = _make_undo_stub()

    result = _invoke_undo(
        ["reclaim", "--undo", "RLIVE", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "not_reclaimed"
    stub.transition_to_in_progress.assert_not_awaited()


def test_undo_is_an_idempotent_noop_on_an_already_undone_run(tmp_path: Path) -> None:
    """Re-running undo on a completed reversal is a clean no-op, like
    ``already_reclaimed`` — exit 0, and no second tracker write."""
    db = tmp_path / "harness.db"
    _seed_reclaimed(db, run_id="RTWICE", ticket="407")
    first = _invoke_undo(
        ["reclaim", "--undo", "RTWICE", "--json", "--db", str(db)], _make_undo_stub()
    )
    assert first.exit_code == 0, first.output

    stub = _make_undo_stub()
    second = _invoke_undo(
        ["reclaim", "--undo", "RTWICE", "--json", "--db", str(db)], stub
    )
    assert second.exit_code == 0, second.output
    assert json.loads(second.output)["outcome"] == "already_undone"
    stub.transition_to_in_progress.assert_not_awaited()
    stub.post_comment.assert_not_awaited()
    assert len(_fetch_events(db, "RTWICE", "reclaim_undone")) == 1


def test_undo_works_again_on_a_run_reclaimed_after_a_prior_undo(
    tmp_path: Path,
) -> None:
    """A run undone, then *genuinely* reclaimed later, is undoable again.

    The reversal history must not disqualify a run from a later reversal: the run
    is ``cancelled`` with a ``reclaimed`` abandon event, which is the whole gate.
    Keying the gate on 'has never been undone' would strand exactly this run.
    """
    db = tmp_path / "harness.db"
    _seed_reclaimed(db, run_id="RAGAIN", ticket="408")
    assert _invoke_undo(
        ["reclaim", "--undo", "RAGAIN", "--json", "--db", str(db)], _make_undo_stub()
    ).exit_code == 0
    # ...time passes, the session really does die, and reclaim runs again.
    _run_sync(_recancel(db, "RAGAIN"))

    stub = _make_undo_stub()
    result = _invoke_undo(
        ["reclaim", "--undo", "RAGAIN", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["outcome"] == "undone"
    assert _fetch_row(db, "RAGAIN")["status"] == "open"  # type: ignore[index]
    assert len(_fetch_events(db, "RAGAIN", "reclaim_undone")) == 2


def test_undo_by_ticket_with_no_local_run_restores_the_tracker_only(
    tmp_path: Path,
) -> None:
    """The cloud regime: no reachable run row, so restore the tracker and say so."""
    db = tmp_path / "absent" / "harness.db"  # never created
    stub = _make_undo_stub()

    result = _invoke_undo(
        ["reclaim", "--undo", "--ticket", "409", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_in_progress.assert_awaited_once_with("409")
    stub.remove_label.assert_awaited_once_with("409", "reclaimed")
    payload = json.loads(result.output)
    assert payload["outcome"] == "unreverted"
    assert payload["run_id"] is None


def test_undo_by_ticket_targets_the_most_recent_reclaimed_run(tmp_path: Path) -> None:
    """``--ticket`` resolves to the newest reclaim-cancelled run for that ticket."""
    db = tmp_path / "harness.db"
    _seed_reclaimed(db, run_id="ROLD", ticket="410")
    _seed_reclaimed(db, run_id="RNEW", ticket="410")
    _run_sync(_set_completed_at(db, "ROLD", "2026-01-01T00:00:00+00:00"))
    _run_sync(_set_completed_at(db, "RNEW", "2026-05-05T00:00:00+00:00"))

    result = _invoke_undo(
        ["reclaim", "--undo", "--ticket", "410", "--json", "--db", str(db)],
        _make_undo_stub(),
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["run_id"] == "RNEW"
    assert _fetch_row(db, "RNEW")["status"] == "open"  # type: ignore[index]
    assert _fetch_row(db, "ROLD")["status"] == "cancelled"  # type: ignore[index]


def test_undo_tracker_failure_leaves_the_run_cancelled(tmp_path: Path) -> None:
    """Tracker-first, like reclaim: a failed restore leaves work still to undo.

    If the row were re-opened first and the tracker then failed, the ticket would
    sit in Todo with the ``reclaimed`` label while a run claimed to be open — and
    a retry would read ``already_undone`` and never fix the tracker.
    """
    db = tmp_path / "harness.db"
    _seed_reclaimed(db, run_id="RTFAIL", ticket="411")
    stub = _make_undo_stub(
        raise_on_transition=TrackerRequestError("tracker 502")
    )

    result = _invoke_undo(
        ["reclaim", "--undo", "RTFAIL", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "tracker_error"
    assert _fetch_row(db, "RTFAIL")["status"] == "cancelled"  # type: ignore[index]
    assert _fetch_events(db, "RTFAIL", "reclaim_undone") == []


def test_undo_on_a_tracker_less_repo_reopens_the_run_only(tmp_path: Path) -> None:
    """``tracker: none``: there is no ticket state, so do the local half."""
    db = tmp_path / "harness.db"
    _seed_reclaimed(db, run_id="RNOTRACKER", ticket="412")
    stub = _make_undo_stub()

    result = _invoke_undo(
        ["reclaim", "--undo", "RNOTRACKER", "--json", "--db", str(db)],
        stub,
        backend="none",
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_in_progress.assert_not_awaited()
    assert _fetch_row(db, "RNOTRACKER")["status"] == "open"  # type: ignore[index]
    assert len(_fetch_events(db, "RNOTRACKER", "reclaim_undone")) == 1


def test_undo_refuses_an_unknown_run_id(tmp_path: Path) -> None:
    db = tmp_path / "harness.db"
    _run_sync(store.init_db(db))
    result = _invoke_undo(
        ["reclaim", "--undo", "RNOPE", "--json", "--db", str(db)], _make_undo_stub()
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "unknown_run"


def test_undo_refuses_combination_with_stale(tmp_path: Path) -> None:
    """``--stale`` sweeps; ``--undo`` reverses one target. Together is meaningless."""
    db = tmp_path / "harness.db"
    result = _invoke_undo(
        ["reclaim", "--undo", "--stale", "--json", "--db", str(db)], _make_undo_stub()
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "ambiguous_mode"


def test_undo_requires_exactly_one_selector(tmp_path: Path) -> None:
    """Neither selector, and both selectors, are each refused."""
    db = tmp_path / "harness.db"
    neither = _invoke_undo(
        ["reclaim", "--undo", "--json", "--db", str(db)], _make_undo_stub()
    )
    assert neither.exit_code == 2, neither.output
    assert json.loads(neither.output)["reason"] == "ambiguous_selector"

    both = _invoke_undo(
        ["reclaim", "--undo", "R1", "--ticket", "413", "--json", "--db", str(db)],
        _make_undo_stub(),
    )
    assert both.exit_code == 2, both.output
    assert json.loads(both.output)["reason"] == "ambiguous_selector"


def test_a_sweep_after_an_undo_spares_the_restored_ticket(tmp_path: Path) -> None:
    """The regression closing the loop between this ticket's two halves.

    Undo re-opens the run, so ``idx_runs_ticket_open`` sees it again — and the
    next hourly pre-flight sweep runs against a ticket whose tracker ``updatedAt``
    is still ancient and whose ``started_at`` is still long past. Without the
    ``reclaim_undone`` event counting as ledger activity, the very next sweep
    would re-reclaim the ticket the operator just restored, in a loop.
    """
    db = tmp_path / "harness.db"
    _seed_reclaimed(db, run_id="RLOOP", ticket="414")
    assert _invoke_undo(
        ["reclaim", "--undo", "RLOOP", "--json", "--db", str(db)], _make_undo_stub()
    ).exit_code == 0

    sweep_stub = _make_sweep_stub(
        [{"identifier": "414", "updated_at": _iso_minutes_ago(300)}]
    )
    result = _invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        sweep_stub,
    )
    assert result.exit_code == 0, result.output
    sweep_stub.transition_to_unstarted.assert_not_awaited()
    assert json.loads(result.output)["skipped"] == ["414"]
    assert _fetch_row(db, "RLOOP")["status"] == "open"  # type: ignore[index]


def test_undo_refuses_a_run_id_when_there_is_no_ledger_at_all(tmp_path: Path) -> None:
    """A ``<run-id>`` names a specific local row; with no DB there is no such row.

    Without this branch the target would fall through to the tracker-only path
    carrying ``ticket=None`` — and undo would go on to "restore" a ticket whose
    identifier is the string ``'None'``. ``--ticket`` legitimately degrades to a
    tracker-only reversal; a run-id cannot.
    """
    db = tmp_path / "absent" / "harness.db"  # never created
    stub = _make_undo_stub()

    result = _invoke_undo(
        ["reclaim", "--undo", "RGHOST", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "unknown_run"
    stub.transition_to_in_progress.assert_not_awaited()


def test_undo_refuses_a_run_cancelled_after_a_prior_undo(tmp_path: Path) -> None:
    """The **newest** abandon reason decides — a later `cancel` is not undoable.

    A run can carry several ``workflow_failed`` events: reclaimed, undone, then
    deliberately cancelled by the operator. Reading the oldest would see
    ``reason='reclaimed'`` and happily re-open a run the operator had *chosen* to
    abandon, ignoring their more recent decision.
    """
    db = tmp_path / "harness.db"
    _seed_reclaimed(db, run_id="RTHENCANCEL", ticket="415")
    assert _invoke_undo(
        ["reclaim", "--undo", "RTHENCANCEL", "--json", "--db", str(db)],
        _make_undo_stub(),
    ).exit_code == 0
    _run_sync(_cancel_deliberately(db, "RTHENCANCEL"))

    stub = _make_undo_stub()
    result = _invoke_undo(
        ["reclaim", "--undo", "RTHENCANCEL", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "not_reclaimed"
    stub.transition_to_in_progress.assert_not_awaited()
    assert _fetch_row(db, "RTHENCANCEL")["status"] == "cancelled"  # type: ignore[index]


def test_undo_refuses_when_a_competing_run_appears_after_the_precheck(
    tmp_path: Path,
) -> None:
    """The re-open transaction re-checks the competing-open-run condition itself.

    The friendly pre-check runs before any write, so it is racy by construction: a
    second session can ``harness start`` on the ticket in the window between the
    check and the ``UPDATE``. ``idx_runs_ticket_open`` would then reject the write,
    but only if the statement is actually guarded — so the transaction re-asserts
    the condition rather than trusting the pre-check. Simulated by blinding the
    pre-check while a competing row genuinely exists.
    """
    db = tmp_path / "harness.db"
    _seed_reclaimed(db, run_id="RRACE", ticket="416")
    assert _insert_fresh_open(db, run_id="RRACEWINNER", ticket="416") is True

    async def _blind(_conn: Any, _ticket: str, _run_id: str) -> str | None:
        return None

    with patch.object(reclaim_undo, "_competing_open_run", _blind):
        result = _invoke_undo(
            ["reclaim", "--undo", "RRACE", "--json", "--db", str(db)],
            _make_undo_stub(),
        )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "ticket_has_open_run"
    assert _fetch_row(db, "RRACE")["status"] == "cancelled"  # type: ignore[index]
    assert _fetch_events(db, "RRACE", "reclaim_undone") == []


def test_undo_does_not_reopen_a_run_that_became_terminal_after_the_precheck(
    tmp_path: Path,
) -> None:
    """The re-open is guarded on the status it observed — never a blind UPDATE.

    If a concurrent ``close`` lands between the pre-check and the write, an
    unguarded statement would drag a **closed** (merged) run back to ``open``:
    the ledger would then show merged work as in-flight, and ``close``'s
    'a start exists' gate would be reading a run that already landed.
    """
    db = tmp_path / "harness.db"
    _seed_reclaimed(db, run_id="RCLOSED", ticket="417")

    async def _close_it_mid_flight(_conn: Any, _ticket: str, _run_id: str) -> None:
        await _set_status(db, "RCLOSED", "closed")
        return None

    with patch.object(reclaim_undo, "_competing_open_run", _close_it_mid_flight):
        result = _invoke_undo(
            ["reclaim", "--undo", "RCLOSED", "--json", "--db", str(db)],
            _make_undo_stub(),
        )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "ticket_has_open_run"
    assert _fetch_row(db, "RCLOSED")["status"] == "closed"  # type: ignore[index]
    assert _fetch_events(db, "RCLOSED", "reclaim_undone") == []


def test_undo_by_ticket_refuses_when_the_newest_cancellation_was_deliberate(
    tmp_path: Path,
) -> None:
    """`--ticket` applies the same newest-reason gate the run-id path does.

    A run can accumulate several `workflow_failed` events: reclaimed, undone, then
    deliberately cancelled by the operator. Selecting on "has a reclaimed event
    *anywhere* in its history" would match that run and re-open something the
    operator had chosen to abandon — the bounded-authority invariant says only a
    run whose **current** cancellation is a reclamation is undoable, and the
    selector must not be a way around it.
    """
    db = tmp_path / "harness.db"
    _seed_reclaimed(db, run_id="RTICKETCANCEL", ticket="418")
    assert _invoke_undo(
        ["reclaim", "--undo", "RTICKETCANCEL", "--json", "--db", str(db)],
        _make_undo_stub(),
    ).exit_code == 0
    _run_sync(_cancel_deliberately(db, "RTICKETCANCEL"))

    stub = _make_undo_stub()
    result = _invoke_undo(
        ["reclaim", "--undo", "--ticket", "418", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "not_reclaimed"
    stub.transition_to_in_progress.assert_not_awaited()
    stub.remove_label.assert_not_awaited()
    assert _fetch_row(db, "RTICKETCANCEL")["status"] == "cancelled"  # type: ignore[index]
