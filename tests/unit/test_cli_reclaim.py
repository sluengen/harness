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
* ``--stale --project <name> [--older-than <dur>]`` enumerates the project's active
  tickets — In Progress **and** In Review (CAL-1103) — and reclaims each idle past
  the threshold (reusing the single-target ``--ticket`` path per ticket), skipping
  any inside the threshold; an empty / already-reverted project is a clean no-op.
"""

# size: the reclaim verb's whole acceptance surface — the single-target revert, the
# --stale sweep's three liveness clocks, the closable classifier, and --undo. Over
# the ceiling because those four production modules are one verb's arms and the
# cross-arm orderings (spared-before-closable) are only assertable side by side; the
# per-arm split is tracked in #274.

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from harness.cli import _review_gate, app, reclaim, reclaim_closable, reclaim_liveness
from harness.loop_budget import evaluate_breakers, load_loop_budget
from harness.state import store
from tests._gitutil import init_repo
from tests._reclaim import (
    cli_runner,
    count_open_for_ticket,
    fetch_events,
    fetch_row,
    insert_fresh_open,
    invoke,
    iso_minutes_ago,
    make_sweep_stub,
    run_sync,
    seed_checkpoint,
    seed_run,
    seed_worktree,
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

    Distinct from :func:`seed_worktree` in the one way that matters here:
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

    ``timestamp`` is **required**, unlike :func:`seed_checkpoint`'s optional
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

    run_sync(_emit())


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
    seed_run(
        db, run_id=run_id, status="open", ticket=ticket,
        worktree_branch=f"harness/{ticket}", worktree_path=str(worktree),
        started_at=iso_minutes_ago(400),
    )
    _seed_review(
        db, run_id,
        reviewed_sha=sha_override if sha_override is not None else head,
        verdict=verdict, gate=gate, timestamp=iso_minutes_ago(180),
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
    stub = make_sweep_stub([{"identifier": "400", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
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
    assert fetch_row(db, "RCLOSE")["status"] == "open"  # type: ignore[index]
    assert fetch_events(db, "RCLOSE", "workflow_failed") == []


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
    issues = [{"identifier": "401", "updated_at": iso_minutes_ago(300)}]

    for _tick in range(2):
        stub = make_sweep_stub(issues)
        result = invoke(
            ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
            stub,
        )
        assert result.exit_code == 0, result.output
        assert [c["ticket"] for c in json.loads(result.output)["closable"]] == ["401"]
        stub.transition_to_unstarted.assert_not_awaited()

    assert fetch_row(db, "RTWICE")["status"] == "open"  # type: ignore[index]
    assert fetch_events(db, "RTWICE", "workflow_failed") == []


def test_stale_sweep_reclaims_a_pass_bound_to_a_different_sha(tmp_path: Path) -> None:
    """AC-3: HEAD advanced after the review, so the pass no longer covers the tree
    that would merge — ``close`` refuses ``stale_review``, so this is not closable."""
    db = tmp_path / "harness.db"
    _seed_closable(tmp_path, ticket="402", run_id="RSTALE", sha_override="0" * 40)
    stub = make_sweep_stub([{"identifier": "402", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)], stub
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["closable"] == []
    stub.transition_to_unstarted.assert_awaited_once_with("402")
    assert fetch_row(db, "RSTALE")["status"] == "cancelled"  # type: ignore[index]


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
    stub = make_sweep_stub([{"identifier": "403", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
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
    stub = make_sweep_stub([{"identifier": "404", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
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
    stub = make_sweep_stub([{"identifier": "405", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
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
    seed_run(
        db, run_id="RNESTED", status="open", ticket="406",
        worktree_branch="harness/406", worktree_path=str(inner),
        started_at=iso_minutes_ago(400),
    )
    _seed_review(
        db, "RNESTED", reviewed_sha=outer_head, timestamp=iso_minutes_ago(180)
    )
    stub = make_sweep_stub([{"identifier": "406", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
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
    stub = make_sweep_stub([{"identifier": "407", "updated_at": iso_minutes_ago(300)}])

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
        result = invoke(
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
    seed_run(
        db, run_id="RLIVE", status="open", ticket="408",
        worktree_branch="harness/408", worktree_path=str(worktree),
        started_at=iso_minutes_ago(400),
    )
    _seed_review(db, "RLIVE", reviewed_sha=head, timestamp=iso_minutes_ago(180))
    stub = make_sweep_stub([{"identifier": "408", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
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
    stub = make_sweep_stub(
        [
            {"identifier": "409", "updated_at": iso_minutes_ago(300)},
            {"identifier": "410", "updated_at": iso_minutes_ago(10)},
            {"identifier": "411", "updated_at": iso_minutes_ago(400)},
        ]
    )

    result = invoke(
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
    stub = make_sweep_stub([{"identifier": "412", "updated_at": iso_minutes_ago(5)}])

    async def _never_closable(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the closable predicate ran for a tracker-fresh ticket")

    def _never_git(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("a git probe ran for a tracker-fresh ticket")

    with (
        patch.object(reclaim, "closable_run", _never_closable),
        patch.object(reclaim_closable, "rev_parse_head", _never_git),
        patch.object(reclaim_liveness, "worktree_last_activity", _never_git),
    ):
        result = invoke(
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
    live_wt = seed_worktree(tmp_path / "wt-mixlive", minutes_ago=2)
    seed_run(
        db, run_id="RMIXLIVE", status="open", ticket="421",
        worktree_branch="harness/421", worktree_path=str(live_wt),
        started_at=iso_minutes_ago(400),
    )
    # dead: no local run row at all (the revert-only path).
    stub = make_sweep_stub(
        [
            {"identifier": "419", "updated_at": iso_minutes_ago(5)},    # fresh
            {"identifier": "420", "updated_at": iso_minutes_ago(300)},  # closable
            {"identifier": "421", "updated_at": iso_minutes_ago(300)},  # live
            {"identifier": "422", "updated_at": iso_minutes_ago(300)},  # dead
        ]
    )

    result = invoke(
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
    stub = make_sweep_stub([{"identifier": "423", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
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
    stub = make_sweep_stub([{"identifier": "424", "updated_at": iso_minutes_ago(300)}])

    with patch.object(_review_gate, "REVIEW_VERDICT_PATH", "$.not_the_verdict"):
        result = invoke(
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

        liveness = run_sync(reclaim_liveness.open_run_liveness(db, f"5{index:02d}"))
        predicted = run_sync(reclaim_closable.closable_run(db, liveness))  # type: ignore[arg-type]
        gate = run_sync(close_mod._evaluate_gate(db, f"RAGREE{index}", head))

        assert (predicted is not None) == (gate is None), (
            f"{label}: sweep says closable={predicted is not None}, "
            f"close gate says {gate}"
        )




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
    """
    import inspect

    source = inspect.getsource(reclaim.reclaim_command)
    assert '"90m"' not in source
    assert '"110m"' not in source
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
