"""Tests for ``harness reclaim --undo`` — reversing a confirmed false-positive
reclaim (#254).

Split from ``test_cli_reclaim.py`` in #274: ``reclaim`` is decomposed across four
production modules, and this one covers ``harness/cli/reclaim_undo.py``. The
shared ledger seeders and the patched-tracker ``invoke`` live in
``tests/_reclaim.py``; the helpers below have this module as their only consumer,
so they stay private here.

Contract under test:

* ``--undo`` re-opens only a run it can *prove* was reclaim-cancelled — the
  ``workflow_failed`` event's ``reason`` is the whole gate, so a run abandoned by
  ``harness cancel`` (``reason='cancelled'``) is deliberate and must not be
  undoable.
* It restores the tracker side it can (``transition_to_in_progress`` /
  ``remove_label`` / ``post_comment``, all pre-existing seam methods) and re-opens
  the local row, so a fresh ``harness start`` is no longer blocked.
* It refuses outright when the ticket already carries a competing open run rather
  than arbitrating between two sessions — including when that run appears *after*
  the precheck.
* Idempotent: undoing an already-undone run is a safe no-op, and a run reclaimed
  again after a prior undo is undoable again.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from harness.cli import app, reclaim_undo
from harness.reclaim_marker import UNRECLAIM_MARKER
from harness.state import store
from harness.tracker_errors import TrackerRequestError
from tests._asyncutil import run_sync
from tests._reclaim import (
    cli_runner,
    count_open_for_ticket,
    fetch_events,
    fetch_row,
    insert_fresh_open,
    invoke,
    iso_minutes_ago,
    make_sweep_stub,
    seed_run,
)

# ---------------------------------------------------------------------------
# Ledger mutations the undo gate reads — each has this module as its only
# consumer, so they stay private here (tests/_reclaim.py holds the shared ones)
# ---------------------------------------------------------------------------



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
    """``invoke`` for the undo arm: the client is resolved in ``reclaim_undo``."""
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
    seed_run(db_path, run_id=run_id, status="cancelled", ticket=ticket,
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

    run_sync(_finish())


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
    row = fetch_row(db, "RUNDO")
    assert row["status"] == "open"  # type: ignore[index]
    assert row["completed_at"] is None  # type: ignore[index]
    # 5. the reversal is appended; the reclamation event SURVIVES (append-only).
    undone = fetch_events(db, "RUNDO", "reclaim_undone")
    assert len(undone) == 1
    assert undone[0]["ticket"] == "401"
    assert fetch_events(db, "RUNDO", "workflow_failed")[0]["reason"] == "reclaimed"
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
    assert insert_fresh_open(db, run_id="RPROBE0", ticket="402") is True
    # Undo cannot run while that probe row holds the slot — remove it and retry.
    run_sync(_delete_run(db, "RPROBE0"))

    result = _invoke_undo(
        ["reclaim", "--undo", "RSLOT", "--json", "--db", str(db)], _make_undo_stub()
    )
    assert result.exit_code == 0, result.output
    assert count_open_for_ticket(db, "402") == 1
    assert insert_fresh_open(db, run_id="RPROBE1", ticket="402") is False


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
    assert insert_fresh_open(db, run_id="RWINNER", ticket="403") is True
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
    assert fetch_row(db, "RLOSER")["status"] == "cancelled"  # type: ignore[index]


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
    assert fetch_row(db, "RCANCEL")["status"] == "cancelled"  # type: ignore[index]


def test_undo_refuses_a_cancelled_run_with_no_abandon_event(tmp_path: Path) -> None:
    """A ``cancelled`` row with no ``workflow_failed`` at all cannot be proven
    to have been reclaimed, so it is refused rather than assumed."""
    db = tmp_path / "harness.db"
    seed_run(db, run_id="RNOEVENT", status="cancelled", ticket="405",
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
    seed_run(db, run_id="RLIVE", status="open", ticket="406",
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
    assert len(fetch_events(db, "RTWICE", "reclaim_undone")) == 1


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
    run_sync(_recancel(db, "RAGAIN"))

    stub = _make_undo_stub()
    result = _invoke_undo(
        ["reclaim", "--undo", "RAGAIN", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["outcome"] == "undone"
    assert fetch_row(db, "RAGAIN")["status"] == "open"  # type: ignore[index]
    assert len(fetch_events(db, "RAGAIN", "reclaim_undone")) == 2


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
    run_sync(_set_completed_at(db, "ROLD", "2026-01-01T00:00:00+00:00"))
    run_sync(_set_completed_at(db, "RNEW", "2026-05-05T00:00:00+00:00"))

    result = _invoke_undo(
        ["reclaim", "--undo", "--ticket", "410", "--json", "--db", str(db)],
        _make_undo_stub(),
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["run_id"] == "RNEW"
    assert fetch_row(db, "RNEW")["status"] == "open"  # type: ignore[index]
    assert fetch_row(db, "ROLD")["status"] == "cancelled"  # type: ignore[index]


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
    assert fetch_row(db, "RTFAIL")["status"] == "cancelled"  # type: ignore[index]
    assert fetch_events(db, "RTFAIL", "reclaim_undone") == []


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
    assert fetch_row(db, "RNOTRACKER")["status"] == "open"  # type: ignore[index]
    assert len(fetch_events(db, "RNOTRACKER", "reclaim_undone")) == 1


def test_undo_refuses_an_unknown_run_id(tmp_path: Path) -> None:
    db = tmp_path / "harness.db"
    run_sync(store.init_db(db))
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

    sweep_stub = make_sweep_stub(
        [{"identifier": "414", "updated_at": iso_minutes_ago(300)}]
    )
    result = invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        sweep_stub,
    )
    assert result.exit_code == 0, result.output
    sweep_stub.transition_to_unstarted.assert_not_awaited()
    assert json.loads(result.output)["skipped"] == ["414"]
    assert fetch_row(db, "RLOOP")["status"] == "open"  # type: ignore[index]


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
    run_sync(_cancel_deliberately(db, "RTHENCANCEL"))

    stub = _make_undo_stub()
    result = _invoke_undo(
        ["reclaim", "--undo", "RTHENCANCEL", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "not_reclaimed"
    stub.transition_to_in_progress.assert_not_awaited()
    assert fetch_row(db, "RTHENCANCEL")["status"] == "cancelled"  # type: ignore[index]


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
    assert insert_fresh_open(db, run_id="RRACEWINNER", ticket="416") is True

    async def _blind(_conn: Any, _ticket: str, _run_id: str) -> str | None:
        return None

    with patch.object(reclaim_undo, "_competing_open_run", _blind):
        result = _invoke_undo(
            ["reclaim", "--undo", "RRACE", "--json", "--db", str(db)],
            _make_undo_stub(),
        )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "ticket_has_open_run"
    assert fetch_row(db, "RRACE")["status"] == "cancelled"  # type: ignore[index]
    assert fetch_events(db, "RRACE", "reclaim_undone") == []


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
    assert fetch_row(db, "RCLOSED")["status"] == "closed"  # type: ignore[index]
    assert fetch_events(db, "RCLOSED", "reclaim_undone") == []


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
    run_sync(_cancel_deliberately(db, "RTICKETCANCEL"))

    stub = _make_undo_stub()
    result = _invoke_undo(
        ["reclaim", "--undo", "--ticket", "418", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "not_reclaimed"
    stub.transition_to_in_progress.assert_not_awaited()
    stub.remove_label.assert_not_awaited()
    assert fetch_row(db, "RTICKETCANCEL")["status"] == "cancelled"  # type: ignore[index]
