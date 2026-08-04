"""Tests for the ``harness reclaim`` **verb** — reclaim a run whose orchestrator
died (CAL-735 single-target, CAL-736 ``--stale`` sweep).

Breakdown items 2 + 3 of the accepted proposal ``stale-run-reclamation``. A run
whose driving session died leaves the Linear ticket stuck *In Progress*, an
``open`` ``runs`` row, and a worktree/branch. ``harness cancel`` only flips the
local row — it never touches Linear, so the ticket stays In Progress and every
dependent stays blocked. ``reclaim`` is the one auditable verb that reverts the
ticket and reconciles the local ledger.

This module covers ``harness/cli/reclaim.py``: the single-target revert, the
invocation refusals, the ``--stale`` sweep's own orchestration, and the #260
anti-drift guard. Since #274 the three extracted modules are tested beside their
production counterparts — ``test_reclaim_liveness.py`` (#216/#254 clocks),
``test_reclaim_closable.py`` (#255 classifier), ``test_reclaim_undo.py`` (#254
``--undo``) — with the shared fixtures in ``tests/_reclaim.py``.

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
* ``--stale --project <name> [--older-than <dur>]`` enumerates the project's active
  tickets — In Progress **and** In Review (CAL-1103) — and reclaims each idle past
  the threshold (reusing the single-target ``--ticket`` path per ticket), skipping
  any inside the threshold; an empty / already-reverted project is a clean no-op.
"""

# size: what is left of the verb's own surface after #274 split the three extracted
# modules out (2,774 -> ~790). 40 lines over, and the remaining content has no
# production seam to split on: it is reclaim.py's single-target revert, its
# invocation refusals, its --stale orchestration, and the #260 anti-drift guard.
# Removable by rehoming the #260 block (~165 lines), which pins loop_budget and
# reclaim *agreeing* and so belongs to neither alone — a placement decision #274
# did not take.

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from harness.cli import app, reclaim
from harness.loop_budget import evaluate_breakers, load_loop_budget
from harness.state import store
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
    seed_checkpoint,
    seed_run,
)

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


# ===========================================================================
# AC: revert Linear (Todo + label + comment) AND flip the local run — run-id
# ===========================================================================


def test_reclaim_reverts_linear_and_flips_run(tmp_path: Path) -> None:
    """The happy path: revert the ticket to Todo + reclaimed label + comment, and
    flip the open run to cancelled with a reclaimed event."""
    db = tmp_path / "harness.db"
    seed_run(db, run_id="R1", status="open", ticket="CAL-735",
              worktree_branch="harness/cal-735")
    seed_checkpoint(db, "R1")  # the run checkpoint-pushed → branch is durable
    stub = _make_linear_stub()

    result = invoke(["reclaim", "R1", "--db", str(db)], stub)
    assert result.exit_code == 0, result.output

    # Linear revert.
    stub.transition_to_unstarted.assert_awaited_once_with("CAL-735")
    stub.apply_label.assert_awaited_once_with("CAL-735", "reclaimed")
    stub.post_comment.assert_awaited_once()
    # Comment names the preserved (checkpoint-pushed) branch ref.
    (_ident, body) = stub.post_comment.await_args.args
    assert "harness/cal-735" in body

    # Local ledger: open -> cancelled with a completion stamp.
    row = fetch_row(db, "R1")
    assert row is not None
    assert row["status"] == "cancelled"
    assert row["completed_at"] is not None

    # The audit event carries reason='reclaimed' (distinct from cancel).
    events = fetch_events(db, "R1", "workflow_failed")
    assert len(events) == 1
    assert events[0].get("reason") == "reclaimed"


def test_reclaim_frees_the_open_ticket_index(tmp_path: Path) -> None:
    """After reclaim, ``idx_runs_ticket_open`` no longer blocks a fresh open run."""
    db = tmp_path / "harness.db"
    seed_run(db, run_id="R1", status="open", ticket="CAL-735")
    # Before: a second open row for the same ticket is rejected by the index.
    assert insert_fresh_open(db, run_id="DUP", ticket="CAL-735") is False

    result = invoke(["reclaim", "R1", "--db", str(db)], _make_linear_stub())
    assert result.exit_code == 0, result.output
    assert count_open_for_ticket(db, "CAL-735") == 0

    # After: a fresh start (new open row) for the ticket now succeeds.
    assert insert_fresh_open(db, run_id="R2", ticket="CAL-735") is True


def test_reclaim_preserves_the_worktree(tmp_path: Path) -> None:
    """Proposal D4: reclaim never prunes the worktree/branch."""
    db = tmp_path / "harness.db"
    wt = tmp_path / "wt-cal-735"
    wt.mkdir()
    (wt / "marker.txt").write_text("wip")
    seed_run(db, run_id="R1", status="open", ticket="CAL-735",
              worktree_path=str(wt), worktree_branch="harness/cal-735")

    result = invoke(["reclaim", "R1", "--db", str(db)], _make_linear_stub())
    assert result.exit_code == 0, result.output
    # The worktree dir and its WIP marker survive — nothing was pruned.
    assert wt.exists()
    assert (wt / "marker.txt").read_text() == "wip"


def test_reclaim_surfaces_failure_reason_in_status(tmp_path: Path) -> None:
    """End-to-end: ``harness status`` reports ``failure_reason='reclaimed'``."""
    db = tmp_path / "harness.db"
    seed_run(db, run_id="R1", status="open", ticket="CAL-735")
    assert invoke(["reclaim", "R1", "--db", str(db)],
                   _make_linear_stub()).exit_code == 0

    status_result = cli_runner.invoke(app, ["status", "R1", "--json", "--db", str(db)])
    assert status_result.exit_code == 0, status_result.output
    payload = json.loads(status_result.output)
    assert payload["status"] == "cancelled"
    assert payload["failure_reason"] == "reclaimed"


def test_reclaim_json_output(tmp_path: Path) -> None:
    """``--json`` emits the run, ticket, outcome, and preserved branch."""
    db = tmp_path / "harness.db"
    seed_run(db, run_id="R1", status="open", ticket="CAL-735",
              worktree_branch="harness/cal-735")
    seed_checkpoint(db, "R1")  # checkpoint-pushed → the branch is resumable
    result = invoke(["reclaim", "R1", "--json", "--db", str(db)], _make_linear_stub())
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
    seed_run(db, run_id="R1", status="open", ticket="CAL-735",
              worktree_branch="harness/cal-735")
    # No checkpoint event seeded — nothing was pushed.
    stub = _make_linear_stub()
    result = invoke(["reclaim", "R1", "--json", "--db", str(db)], stub)
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
    seed_run(db, run_id="R1", status="open", ticket="CAL-900",
              worktree_branch="harness/cal-900")
    stub = _make_linear_stub()
    result = invoke(["reclaim", "--ticket", "CAL-900", "--db", str(db)], stub)
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("CAL-900")
    assert fetch_row(db, "R1")["status"] == "cancelled"  # type: ignore[index]


def test_reclaim_by_ticket_with_no_local_run_still_reverts_linear(
    tmp_path: Path,
) -> None:
    """The load-bearing path the ``--stale`` sweep (CAL-736) builds on: a stranded
    ticket with no local open run (the cloud regime) is still reverted on Linear."""
    db = tmp_path / "harness.db"
    run_sync(store.init_db(db))  # empty ledger — no run rows
    stub = _make_linear_stub()
    result = invoke(["reclaim", "--ticket", "CAL-901", "--json", "--db", str(db)], stub)
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
    seed_run(db, run_id="R1", status="open", ticket="CAL-735")
    assert invoke(["reclaim", "R1", "--db", str(db)],
                   _make_linear_stub()).exit_code == 0

    # Second reclaim — the run is now cancelled.
    second_stub = _make_linear_stub()
    result = invoke(["reclaim", "R1", "--json", "--db", str(db)], second_stub)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["outcome"] == "already_reclaimed"
    # No Linear mutation on the idempotent re-run.
    second_stub.transition_to_unstarted.assert_not_awaited()
    second_stub.post_comment.assert_not_awaited()
    # No duplicate audit event.
    assert len(fetch_events(db, "R1", "workflow_failed")) == 1


# ===========================================================================
# Refusals
# ===========================================================================


def test_reclaim_unknown_run_refused(tmp_path: Path) -> None:
    """Unknown run-id → exit 2, no Linear mutation."""
    db = tmp_path / "harness.db"
    run_sync(store.init_db(db))
    stub = _make_linear_stub()
    result = invoke(["reclaim", "NOPE", "--db", str(db)], stub)
    assert result.exit_code == 2
    stub.transition_to_unstarted.assert_not_awaited()


def test_reclaim_closed_run_refused(tmp_path: Path) -> None:
    """A finished-terminal run (``closed``) is refused — nothing to reclaim."""
    db = tmp_path / "harness.db"
    seed_run(db, run_id="R1", status="closed", ticket="CAL-735")
    stub = _make_linear_stub()
    result = invoke(["reclaim", "R1", "--db", str(db)], stub)
    assert result.exit_code == 2
    stub.transition_to_unstarted.assert_not_awaited()
    # Row untouched.
    assert fetch_row(db, "R1") == {"status": "closed", "completed_at": None}


def test_reclaim_unrecognised_status_refused(tmp_path: Path) -> None:
    """A status outside the known set is refused, never silently overwritten."""
    db = tmp_path / "harness.db"
    seed_run(db, run_id="R1", status="bogus", ticket="CAL-735")
    stub = _make_linear_stub()
    result = invoke(["reclaim", "R1", "--db", str(db)], stub)
    assert result.exit_code == 2
    assert fetch_row(db, "R1") == {"status": "bogus", "completed_at": None}
    stub.transition_to_unstarted.assert_not_awaited()


def test_reclaim_requires_a_selector(tmp_path: Path) -> None:
    """Neither run-id nor --ticket → exit 2 (ambiguous invocation)."""
    db = tmp_path / "harness.db"
    result = invoke(["reclaim", "--db", str(db)], _make_linear_stub())
    assert result.exit_code == 2


def test_reclaim_rejects_both_selectors(tmp_path: Path) -> None:
    """Both run-id and --ticket → exit 2 (ambiguous invocation)."""
    db = tmp_path / "harness.db"
    seed_run(db, run_id="R1", status="open", ticket="CAL-735")
    result = invoke(["reclaim", "R1", "--ticket", "CAL-735", "--db", str(db)],
                     _make_linear_stub())
    assert result.exit_code == 2


def test_reclaim_run_without_ticket_refused(tmp_path: Path) -> None:
    """A run with no associated ticket cannot be reverted — exit 2."""
    db = tmp_path / "harness.db"
    seed_run(db, run_id="R1", status="open", ticket=None)
    stub = _make_linear_stub()
    result = invoke(["reclaim", "R1", "--db", str(db)], stub)
    assert result.exit_code == 2
    stub.transition_to_unstarted.assert_not_awaited()


# ===========================================================================
# Load-bearing ordering — the Linear revert gates the local reconcile
# ===========================================================================


def test_reclaim_linear_failure_leaves_run_in_flight(tmp_path: Path) -> None:
    """Linear is the load-bearing substrate, so the revert runs first: if it
    fails, the local run stays in-flight (a retry still sees work to reclaim)."""
    db = tmp_path / "harness.db"
    seed_run(db, run_id="R1", status="open", ticket="CAL-735")
    stub = _make_linear_stub(raise_on_transition=RuntimeError("Linear down"))
    result = invoke(["reclaim", "R1", "--json", "--db", str(db)], stub)
    assert result.exit_code != 0
    # The local flip never happened — the run is still abandonable on retry.
    assert fetch_row(db, "R1")["status"] == "open"  # type: ignore[index]
    assert fetch_events(db, "R1", "workflow_failed") == []


def test_reclaim_unconfirmed_transition_leaves_run_in_flight(tmp_path: Path) -> None:
    """``TrackerTransitionUnconfirmed`` subclasses ``TrackerRequestError`` (#233),
    so it takes the same in-flight-preserving path as any other tracker
    failure — pinned directly rather than only inferred from the subclass
    relationship."""
    from harness.tracker_errors import TrackerTransitionUnconfirmed

    db = tmp_path / "harness.db"
    seed_run(db, run_id="R1", status="open", ticket="CAL-735")
    stub = _make_linear_stub(
        raise_on_transition=TrackerTransitionUnconfirmed("post-write state still In Progress")
    )
    result = invoke(["reclaim", "R1", "--json", "--db", str(db)], stub)
    assert result.exit_code != 0
    assert fetch_row(db, "R1")["status"] == "open"  # type: ignore[index]
    assert fetch_events(db, "R1", "workflow_failed") == []


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
    run_sync(store.init_db(db))  # empty ledger — cloud regime
    stub = make_sweep_stub([{"identifier": "CAL-800", "updated_at": iso_minutes_ago(150)}])

    result = invoke(
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
    run_sync(store.init_db(db))  # cloud regime: revert-only, no local run
    stub = make_sweep_stub([{"identifier": "CAL-900", "updated_at": iso_minutes_ago(150)}])

    result = invoke(
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
    run_sync(store.init_db(db))
    stub = make_sweep_stub([{"identifier": "CAL-801", "updated_at": iso_minutes_ago(10)}])

    result = invoke(
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
    run_sync(store.init_db(db))
    stub = make_sweep_stub(
        [
            {"identifier": "CAL-810", "updated_at": iso_minutes_ago(200)},  # stale
            {"identifier": "CAL-811", "updated_at": iso_minutes_ago(30)},  # fresh
        ]
    )

    result = invoke(
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
    run_sync(store.init_db(db))
    stub = make_sweep_stub([{"identifier": "CAL-820", "updated_at": iso_minutes_ago(30)}])

    result = invoke(
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
    run_sync(store.init_db(db))
    stub = make_sweep_stub([])

    result = invoke(
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
    run_sync(store.init_db(db))
    # Tick 1: the ticket is stale and In Progress → reclaimed.
    tick1 = make_sweep_stub([{"identifier": "CAL-830", "updated_at": iso_minutes_ago(150)}])
    assert invoke(
        ["reclaim", "--stale", "--project", "Harness v3", "--db", str(db)], tick1
    ).exit_code == 0
    tick1.transition_to_unstarted.assert_awaited_once_with("CAL-830")
    # Tick 2: it is now Todo, so it is no longer enumerated → nothing to do.
    tick2 = make_sweep_stub([])
    assert invoke(
        ["reclaim", "--stale", "--project", "Harness v3", "--db", str(db)], tick2
    ).exit_code == 0
    tick2.transition_to_unstarted.assert_not_awaited()


def test_stale_sweep_full_reclaim_when_local_run_exists(tmp_path: Path) -> None:
    """In the local regime the sweep does a full reclaim: the open run flips to
    cancelled and the comment names the preserved branch (reuses the single path)."""
    db = tmp_path / "harness.db"
    seed_run(db, run_id="R9", status="open", ticket="CAL-840",
              worktree_branch="harness/cal-840")
    # Durable WIP pushed — back-dated past the threshold so the run reads as dead
    # on *both* signals (#216): an event stamped "now" would make this a live run.
    seed_checkpoint(
        db, "R9", branch="harness/cal-840", timestamp=iso_minutes_ago(150)
    )
    stub = make_sweep_stub([{"identifier": "CAL-840", "updated_at": iso_minutes_ago(150)}])

    result = invoke(
        ["reclaim", "--stale", "--project", "Harness v3", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    assert fetch_row(db, "R9")["status"] == "cancelled"  # type: ignore[index]
    assert fetch_events(db, "R9", "workflow_failed")[0]["reason"] == "reclaimed"
    (_ident, body) = stub.post_comment.await_args.args
    assert "harness/cal-840" in body
    payload = json.loads(result.output)
    assert payload["reclaimed"][0]["outcome"] == "reclaimed"


# --- --stale invocation refusals ----------------------------------------------


def test_stale_without_project_sweeps_the_whole_queue(tmp_path: Path) -> None:
    """AC-1/AC-2 (#174): ``--stale`` with no ``--project`` is no longer refused — it
    sweeps the whole tracker queue via ``fetch_reclaimable_issues(project=None)``, each
    backend interpreting "unset" as its natural full queue (Linear: the team; GitHub:
    the board). A stale ticket is reverted exactly as in the scoped sweep."""
    db = tmp_path / "harness.db"
    run_sync(store.init_db(db))
    stub = make_sweep_stub(
        [{"identifier": "CAL-900", "updated_at": iso_minutes_ago(150)}]
    )
    result = invoke(["reclaim", "--stale", "--json", "--db", str(db)], stub)
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
    run_sync(store.init_db(db))
    result = invoke(["reclaim", "--stale", "--db", str(db)], make_sweep_stub([]))
    assert result.exit_code == 0, result.output
    assert "whole tracker queue" in result.output
    assert "None" not in result.output


def test_stale_rejects_a_run_id_selector(tmp_path: Path) -> None:
    """``--stale`` combined with a single-target ``<run-id>`` is ambiguous → exit 2."""
    db = tmp_path / "harness.db"
    run_sync(store.init_db(db))
    result = invoke(
        ["reclaim", "R1", "--stale", "--project", "Harness v3", "--db", str(db)],
        make_sweep_stub([]),
    )
    assert result.exit_code == 2


def test_stale_rejects_a_ticket_selector(tmp_path: Path) -> None:
    """``--stale`` combined with ``--ticket`` is ambiguous → exit 2."""
    db = tmp_path / "harness.db"
    run_sync(store.init_db(db))
    result = invoke(
        ["reclaim", "--stale", "--ticket", "CAL-1", "--project", "Harness v3",
         "--db", str(db)],
        make_sweep_stub([]),
    )
    assert result.exit_code == 2


def test_stale_rejects_a_bad_duration(tmp_path: Path) -> None:
    """A malformed ``--older-than`` is refused (exit 2, like worktrees cleanup)."""
    db = tmp_path / "harness.db"
    run_sync(store.init_db(db))
    result = invoke(
        ["reclaim", "--stale", "--older-than", "soon", "--project", "Harness v3",
         "--db", str(db)],
        make_sweep_stub([]),
    )
    assert result.exit_code == 2


# ===========================================================================
# #260: one config key drives BOTH the wall-clock breaker and reclamation
# staleness — the anti-drift guard
# ===========================================================================


def test_one_context_key_drives_both_the_breaker_and_reclaim_staleness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-2 — the core of #260: **one** ``CONTEXT.md`` edit moves both consumers.

    The wall-clock breaker and reclamation staleness are the same quantity read
    from two directions — prospectively (stop spending on a run past it) and
    retrospectively (a run past it is presumed dead). They used to be two
    independent literals kept equal by a comment asking humans to remember; this
    test is what makes divergence impossible.

    45 is chosen deliberately: it is neither the old hardcoded 90 nor the new
    configured 110, so neither a surviving literal nor the new default can
    satisfy it. Against today's code the reclaim half fails — a 46-minute-idle
    ticket is fresh under the hardcoded ``90m`` and is never reclaimed.
    """
    (tmp_path / "CONTEXT.md").write_text(
        "```yaml\nloop:\n  max_review_cycles: 6\n  wall_clock_budget_minutes: 45\n```\n"
    )

    # --- Consumer 1: the per-run wall-clock breaker (harness review) ---------
    budget = load_loop_budget(tmp_path)
    assert budget.wall_clock_budget_minutes == 45
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    assert (
        evaluate_breakers(
            prior_review_count=0,
            started_at=t0,
            now=t0 + timedelta(minutes=46),
            budget=budget,
        )
        is not None
    ), "a 46-minute run must trip a 45-minute budget"
    assert (
        evaluate_breakers(
            prior_review_count=0,
            started_at=t0,
            now=t0 + timedelta(minutes=44),
            budget=budget,
        )
        is None
    ), "a 44-minute run is inside a 45-minute budget"

    # --- Consumer 2: reclamation staleness (harness reclaim --stale) ---------
    # ``reclaim`` is CWD-anchored (no ``--repo``), so chdir is how the same
    # CONTEXT.md above reaches it — patching ``load_loop_budget`` instead would
    # prove nothing about the file actually being read.
    db = tmp_path / "harness.db"
    run_sync(store.init_db(db))
    stub = make_sweep_stub(
        [
            {"identifier": "STALE-46", "updated_at": iso_minutes_ago(46)},
            {"identifier": "FRESH-44", "updated_at": iso_minutes_ago(44)},
        ]
    )
    monkeypatch.chdir(tmp_path)

    result = invoke(["reclaim", "--stale", "--json", "--db", str(db)], stub)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [r["ticket"] for r in payload["reclaimed"]] == ["STALE-46"]
    assert payload["skipped"] == ["FRESH-44"]
    # The resolved threshold is echoed as a duration string, so the JSON shape
    # is unchanged and the resolution is observable rather than inferred.
    assert payload["older_than"] == "45m"


def test_reclaim_carries_no_default_duration_literal_of_its_own() -> None:
    """AC-1 — the hardcoded ``"90m"`` is *deleted*, not updated.

    The point of #260 is that reclamation owns no duration constant at all: the
    ``--older-than`` option defaults to ``None`` and the value is resolved from
    the loop budget. A literal reintroduced here — even one that happens to read
    ``110m`` today — restores exactly the two-places-to-edit drift this removed,
    so the *absence* is the thing worth pinning.

    Since #297 the same holds for the attended threshold: it is a second value
    resolved from the same loader, and ``"480m"`` written here would be the
    identical mistake made twice.
    """
    import inspect

    source = inspect.getsource(reclaim.reclaim_command)
    assert '"90m"' not in source
    assert '"110m"' not in source
    assert '"480m"' not in source
    # The resolution goes through the shared loader, not a private copy.
    assert reclaim.load_loop_budget is load_loop_budget


def test_shipped_context_configures_the_same_value_the_code_defaults_to() -> None:
    """AC-5/AC-4 — this repo's CONTEXT.md configures 110, and the code's fallback
    agrees with it.

    Two numbers that must not drift: the value shipped in ``CONTEXT.md`` and the
    constant a repo with no ``loop:`` block falls back to. If they diverge, a
    consuming repo silently runs a different budget from this one and the
    boundary tests below describe nobody's actual configuration.
    """
    repo_root = Path(__file__).resolve().parents[2]
    assert load_loop_budget(repo_root).wall_clock_budget_minutes == 110
    from harness.loop_budget import DEFAULT_WALL_CLOCK_BUDGET_MINUTES

    assert DEFAULT_WALL_CLOCK_BUDGET_MINUTES == 110


def test_stale_sweep_brackets_the_configured_110_minute_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-5, reclaim side — the sweep's boundary sits at the configured 110.

    Bracketed at 109/111 rather than asserted at exactly 110: the sweep compares
    against ``datetime.now(UTC)`` at execution time, so a fixture built as
    "exactly 110 minutes ago" has already aged past the cutoff by the time the
    comparison runs and would flake. The exact boundary is pinned on the pure,
    clock-injected side (``test_wall_clock_within_budget_does_not_trip`` /
    ``..._exceeded_trips``); here the resolved threshold string carries it.
    """
    (tmp_path / "CONTEXT.md").write_text(
        "```yaml\nloop:\n  wall_clock_budget_minutes: 110\n```\n"
    )
    db = tmp_path / "harness.db"
    run_sync(store.init_db(db))
    stub = make_sweep_stub(
        [
            {"identifier": "PAST-111", "updated_at": iso_minutes_ago(111)},
            {"identifier": "INSIDE-109", "updated_at": iso_minutes_ago(109)},
        ]
    )
    monkeypatch.chdir(tmp_path)

    result = invoke(["reclaim", "--stale", "--json", "--db", str(db)], stub)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [r["ticket"] for r in payload["reclaimed"]] == ["PAST-111"]
    assert payload["skipped"] == ["INSIDE-109"]
    assert payload["older_than"] == "110m"


def test_stale_sweep_falls_back_to_the_shared_default_without_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-4 — no CONTEXT.md at all, and reclamation still lands on the *same*
    constant the breaker falls back to, so the unconfigured path cannot drift
    either. A repo that never wrote a ``loop:`` block gets one coherent budget,
    not a configured breaker beside a hardcoded sweep."""
    from harness.loop_budget import DEFAULT_WALL_CLOCK_BUDGET_MINUTES

    db = tmp_path / "harness.db"
    run_sync(store.init_db(db))
    stub = make_sweep_stub([])
    monkeypatch.chdir(tmp_path)  # no CONTEXT.md written

    result = invoke(["reclaim", "--stale", "--json", "--db", str(db)], stub)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["older_than"] == f"{DEFAULT_WALL_CLOCK_BUDGET_MINUTES}m"
    assert (
        load_loop_budget(tmp_path).wall_clock_budget_minutes
        == DEFAULT_WALL_CLOCK_BUDGET_MINUTES
    )


# ===========================================================================
# #297 — the sweep selects its threshold by declared mode (ADR 0011)
# ===========================================================================

#: A ``loop:`` block naming both thresholds, so a test that writes it measures
#: the two configured numbers rather than whichever constants happen to ship.
_BOTH_THRESHOLDS = (
    "```yaml\nloop:\n  wall_clock_budget_minutes: 110\n"
    "  attended_idle_minutes: 480\n```\n"
)


def _sweep_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    ticket: str,
    idle_minutes: int,
    attended: bool,
    tracker_idle_minutes: int | None = None,
    extra_args: list[str] | None = None,
) -> tuple[dict[str, Any], MagicMock]:
    """Sweep one seeded run and return ``(payload, stub)``.

    ``idle_minutes`` ages *every* clock the sweep reads — the run's
    ``started_at`` and, unless ``tracker_idle_minutes`` overrides it, the
    tracker's ``updatedAt``. Splitting them is how the tracker-clock scenario is
    expressed: local signals ancient, tracker recent.
    """
    (tmp_path / "CONTEXT.md").write_text(_BOTH_THRESHOLDS)
    db = tmp_path / "harness.db"
    seed_run(
        db,
        run_id=f"R{ticket}",
        status="open",
        ticket=ticket,
        started_at=iso_minutes_ago(idle_minutes),
        attended=attended,
    )
    tracker_idle = idle_minutes if tracker_idle_minutes is None else tracker_idle_minutes
    stub = make_sweep_stub(
        [{"identifier": ticket, "updated_at": iso_minutes_ago(tracker_idle)}]
    )
    monkeypatch.chdir(tmp_path)

    result = invoke(
        ["reclaim", "--stale", "--json", "--db", str(db), *(extra_args or [])], stub
    )

    assert result.exit_code == 0, result.output
    return json.loads(result.stdout), stub


def test_an_attended_run_between_the_two_thresholds_is_spared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-1 — attended, idle 300 min: past the 110 wall clock, inside the 480
    attended threshold, so the sweep leaves it alone.

    Both numbers are configured in the fixture and the idle sits strictly
    between them, so this measures the thresholds rather than asserting that
    some structure exists. 300 is bracketed well away from either boundary for
    the reason the 109/111 test gives: the sweep reads ``datetime.now(UTC)`` at
    execution time.

    The operator is mid-question here. Reverting the ticket underneath them is
    the failure ADR 0011 names as unfixable by measurement — a human thinking
    touches none of the three liveness clocks.
    """
    payload, stub = _sweep_one(
        tmp_path, monkeypatch, ticket="ATT-300", idle_minutes=300, attended=True
    )

    assert payload["skipped"] == ["ATT-300"]
    assert payload["reclaimed"] == []
    stub.transition_to_unstarted.assert_not_awaited()
    stub.apply_label.assert_not_awaited()
    assert fetch_row(tmp_path / "harness.db", "RATT-300")["status"] == "open"


def test_an_unattended_run_at_the_same_idle_is_reclaimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-3 — the identical fixture with the mode flipped is reclaimed.

    Same three clocks, same two configured numbers, same 300-minute idle,
    opposite outcome. This pair is what proves the *mode* is the variable: a
    change that merely raised the one threshold for everybody would pass AC-1
    and fail here.
    """
    payload, stub = _sweep_one(
        tmp_path, monkeypatch, ticket="UNATT-300", idle_minutes=300, attended=False
    )

    assert [r["ticket"] for r in payload["reclaimed"]] == ["UNATT-300"]
    assert payload["skipped"] == []
    stub.transition_to_unstarted.assert_awaited_once_with("UNATT-300")


def test_an_attended_run_past_the_attended_threshold_is_reclaimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-2 — a longer threshold, not an exemption.

    At 500 minutes idle the attended run is past 480 on every clock and is
    reclaimed exactly as an unattended one: reverted to Todo, labelled, and the
    ledger row flipped. Without this the change would be indistinguishable from
    exempting attended runs, which ADR 0011 rejected — an abandoned attended
    session would leak an open row, a worktree and an In-Progress ticket
    indefinitely.
    """
    payload, stub = _sweep_one(
        tmp_path, monkeypatch, ticket="ATT-500", idle_minutes=500, attended=True
    )

    assert [r["ticket"] for r in payload["reclaimed"]] == ["ATT-500"]
    stub.transition_to_unstarted.assert_awaited_once_with("ATT-500")
    stub.apply_label.assert_awaited()
    assert fetch_row(tmp_path / "harness.db", "RATT-500")["status"] == "cancelled"


def test_the_tracker_clock_is_compared_against_the_attended_cutoff_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mode selects the value *every* clock is measured against, not just the
    local two.

    Local signals ancient (``started_at`` 600 min, no events, no worktree), the
    tracker's ``updatedAt`` 300 min — so the newest of the three is the tracker's
    and it sits inside the attended threshold. An implementation that selects the
    looser cutoff only for ``locally_live`` reclaims this run, and nothing else
    in this family catches it: the mode would then *condemn* on a clock, which is
    the one thing the sweep's additive-in-one-direction invariant forbids.
    """
    payload, stub = _sweep_one(
        tmp_path,
        monkeypatch,
        ticket="ATT-TRACKER",
        idle_minutes=600,
        attended=True,
        tracker_idle_minutes=300,
    )

    assert payload["skipped"] == ["ATT-TRACKER"]
    stub.transition_to_unstarted.assert_not_awaited()


def test_a_ticket_with_no_run_row_is_bounded_by_the_wall_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-5 — an unresolvable mode is unattended, the bounded default.

    The cloud regime: the ledger exists but holds no ``open`` row for the ticket,
    so ``open_run_liveness`` has no opinion and there is no mode to read. At 300
    minutes idle — inside 480, past 110 — the ticket is reclaimed, i.e. it did
    **not** inherit the attended threshold. Unknown fails toward the bound, the
    same direction ``resolve_attended`` itself fails in.
    """
    (tmp_path / "CONTEXT.md").write_text(_BOTH_THRESHOLDS)
    db = tmp_path / "harness.db"
    run_sync(store.init_db(db))  # ledger present, no run for this ticket
    stub = make_sweep_stub([{"identifier": "NOROW-300", "updated_at": iso_minutes_ago(300)}])
    monkeypatch.chdir(tmp_path)

    result = invoke(["reclaim", "--stale", "--json", "--db", str(db)], stub)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [r["ticket"] for r in payload["reclaimed"]] == ["NOROW-300"]
    assert payload["older_than"] == "110m"
    assert payload["attended_older_than"] == "480m"


def test_explicit_older_than_overrides_both_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A one-off sweep means what it says — for an attended run too.

    ``--older-than 20m`` against a 30-minute-idle attended run reclaims it: the
    supplied value replaces *both* resolved thresholds, so the operator asking
    for a 20-minute sweep does not silently get an 8-hour one on some tickets.
    """
    payload, stub = _sweep_one(
        tmp_path,
        monkeypatch,
        ticket="ATT-30",
        idle_minutes=30,
        attended=True,
        extra_args=["--older-than", "20m"],
    )

    assert [r["ticket"] for r in payload["reclaimed"]] == ["ATT-30"]
    stub.transition_to_unstarted.assert_awaited_once_with("ATT-30")
    assert payload["older_than"] == payload["attended_older_than"] == "20m"


def test_shipped_context_configures_the_attended_threshold_the_code_defaults_to() -> None:
    """This repo's ``attended_idle_minutes`` and the constant agree (AC-4).

    The same anti-drift pairing ``test_shipped_context_configures_the_same_value_
    the_code_defaults_to`` keeps for the wall clock: a consuming repo with no
    ``loop:`` block must run the value this repo runs, not a different one.
    """
    repo_root = Path(__file__).resolve().parents[2]
    assert load_loop_budget(repo_root).attended_idle_minutes == 480
    from harness.loop_budget import DEFAULT_ATTENDED_IDLE_MINUTES

    assert DEFAULT_ATTENDED_IDLE_MINUTES == 480
