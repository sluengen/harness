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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from harness._time import iso_z
from harness.cli import app
from harness.state import store

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
) -> None:
    """Seed a run row with the ticket + branch fields reclaim reads."""

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
                    "2026-01-01T00:00:00+00:00",
                ),
            )
            await conn.commit()

    _run_sync(_insert())


def _seed_checkpoint(db_path: Path, run_id: str, branch: str = "harness/cal-735") -> None:
    """Emit a ``checkpoint`` event for ``run_id`` — the durable-WIP signal a
    checkpoint-push leaves (CAL-738). reclaim reports a resumable branch only when
    one exists; a run with none has no pushed WIP."""
    from harness.events.emitter import EventEmitter

    async def _emit() -> None:
        await EventEmitter(db_path).emit(
            run_id=run_id,
            event_type="checkpoint",
            data={"run_id": run_id, "branch": branch, "pushed_sha": "deadbeef"},
        )

    _run_sync(_emit())


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
    _seed_checkpoint(db, "R9", branch="harness/cal-840")  # durable WIP pushed
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


# --- --stale invocation refusals ----------------------------------------------


def test_stale_requires_project(tmp_path: Path) -> None:
    """``--stale`` without ``--project`` is refused (no unbounded workspace sweep)."""
    db = tmp_path / "harness.db"
    _run_sync(store.init_db(db))
    result = _invoke(["reclaim", "--stale", "--db", str(db)], _make_sweep_stub([]))
    assert result.exit_code == 2
    # Nothing was enumerated or reverted.
    # (the stub's fetch is never reached when the invocation is refused)


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
