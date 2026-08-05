"""Tests for the ``harness reclaim --stale`` liveness clocks (#216, #254).

Split from ``test_cli_reclaim.py`` in #274; covers
``harness/cli/reclaim_liveness.py``. The sweep reads **three** clocks, not one:
the tracker's ``updatedAt`` is the baseline every regime has, and the two local
signals below are additive in one direction only — they can *spare* a run, never
condemn one the tracker would have kept.

Both arms live here because they are the same question asked of two substrates,
and a change to ``reclaim_liveness.py`` is what breaks either. The ``--stale``
*invocation* refusals (selector ambiguity, ``--older-than`` parsing, unscoped
``--project``) stay in ``test_cli_reclaim.py``: they pin the verb's option
handling, which no liveness change touches.

Contract under test:

* **#216 — the ledger clock.** The newest of ``runs.started_at`` and the run's
  newest event. ``start`` emits no event, so ``started_at`` is the only signal a
  pre-``design`` run has; a run with a fresh ledger is spared even when the
  tracker calls it stale.
* **#254 — the worktree clock.** The newest mtime among the open run's worktree's
  *tracked* files, for the observed case where a session works for hours with
  zero commits and zero events. Every uncertainty — no recorded worktree path, a
  path that is absent or not a git top-level, a wedged or failing ``ls-files``
  probe — resolves to "not fresh", i.e. to reclaiming as before.
* Both respect a custom ``--older-than`` threshold, and neither is consulted for
  a ticket the tracker already considers fresh (the sweep spends nothing there).
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from harness.cli import reclaim_liveness
from harness.state import store
from tests._asyncutil import run_sync
from tests._gitutil import init_repo
from tests._reclaim import (
    fetch_events,
    fetch_row,
    invoke,
    iso_minutes_ago,
    make_sweep_stub,
    seed_checkpoint,
    seed_run,
    seed_worktree,
)

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
    seed_run(db, run_id="R216", status="open", ticket="216",
              worktree_branch="harness/216")
    seed_checkpoint(db, "R216", branch="harness/216",
                     timestamp=iso_minutes_ago(20))  # alive 20m ago
    stub = make_sweep_stub([{"identifier": "216", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    # The live run is left strictly alone: no revert, no label, no comment.
    stub.transition_to_unstarted.assert_not_awaited()
    stub.apply_label.assert_not_awaited()
    stub.post_comment.assert_not_awaited()
    assert fetch_row(db, "R216")["status"] == "open"  # type: ignore[index]
    payload = json.loads(result.stdout)
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
    seed_run(db, run_id="RFRESH", status="open", ticket="217",
              worktree_branch="harness/217", started_at=iso_minutes_ago(5))
    stub = make_sweep_stub([{"identifier": "217", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_not_awaited()
    assert fetch_row(db, "RFRESH")["status"] == "open"  # type: ignore[index]
    assert json.loads(result.stdout)["skipped"] == ["217"]


def test_stale_sweep_still_reclaims_when_the_ledger_is_also_stale(
    tmp_path: Path,
) -> None:
    """AC-2: a genuinely dead run is still reclaimed — the fix narrows, not blocks.

    Both signals are past the threshold (``started_at`` old, no events), so the
    sweep reverts the ticket and reconciles the ledger exactly as before.
    """
    db = tmp_path / "harness.db"
    seed_run(db, run_id="RDEAD", status="open", ticket="218",
              worktree_branch="harness/218", started_at=iso_minutes_ago(240))
    stub = make_sweep_stub([{"identifier": "218", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("218")
    assert fetch_row(db, "RDEAD")["status"] == "cancelled"  # type: ignore[index]
    assert fetch_events(db, "RDEAD", "workflow_failed")[0]["reason"] == "reclaimed"
    assert json.loads(result.stdout)["reclaimed"][0]["ticket"] == "218"


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
    run_sync(store.init_db(db))  # reachable ledger, no row for this ticket
    stub = make_sweep_stub([{"identifier": "219", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("219")
    assert json.loads(result.stdout)["reclaimed"][0]["ticket"] == "219"


def test_stale_sweep_reclaims_when_no_ledger_exists(tmp_path: Path) -> None:
    """AC-2 tail: an absent DB is the pure cloud regime — tracker-only, unchanged."""
    db = tmp_path / "absent" / "harness.db"  # never created
    stub = make_sweep_stub([{"identifier": "220", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("220")
    assert json.loads(result.stdout)["reclaimed"][0]["ticket"] == "220"


def test_stale_sweep_ledger_liveness_respects_a_custom_threshold(
    tmp_path: Path,
) -> None:
    """The ledger is compared against the *same* cutoff as the tracker signal.

    Two runs whose last ledger activity straddles a custom ``--older-than 30m``:
    the 10-minute one is spared, the 50-minute one is reclaimed. Pins that the
    ledger comparison uses the resolved threshold rather than a hardcoded 90m.
    """
    db = tmp_path / "harness.db"
    seed_run(db, run_id="RIN", status="open", ticket="221",
              worktree_branch="harness/221", started_at=iso_minutes_ago(10))
    seed_run(db, run_id="ROUT", status="open", ticket="222",
              worktree_branch="harness/222", started_at=iso_minutes_ago(50))
    stub = make_sweep_stub(
        [
            {"identifier": "221", "updated_at": iso_minutes_ago(300)},
            {"identifier": "222", "updated_at": iso_minutes_ago(300)},
        ]
    )

    result = invoke(
        ["reclaim", "--stale", "--project", "Harness", "--older-than", "30m",
         "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["skipped"] == ["221"]
    assert [r["ticket"] for r in payload["reclaimed"]] == ["222"]


def test_stale_sweep_partitions_tracker_stale_tickets_by_ledger(
    tmp_path: Path,
) -> None:
    """Each ticket is judged independently; ``scanned`` still counts them all."""
    db = tmp_path / "harness.db"
    seed_run(db, run_id="RALIVE", status="open", ticket="223",
              worktree_branch="harness/223", started_at=iso_minutes_ago(200))
    seed_checkpoint(db, "RALIVE", branch="harness/223",
                     timestamp=iso_minutes_ago(15))  # alive despite an old start
    seed_run(db, run_id="RGONE", status="open", ticket="224",
              worktree_branch="harness/224", started_at=iso_minutes_ago(200))
    stub = make_sweep_stub(
        [
            {"identifier": "223", "updated_at": iso_minutes_ago(300)},
            {"identifier": "224", "updated_at": iso_minutes_ago(300)},
        ]
    )

    result = invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
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
    stub = make_sweep_stub([{"identifier": "225", "updated_at": iso_minutes_ago(10)}])

    result = invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(not_a_db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["skipped"] == ["225"]


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
    worktree = seed_worktree(tmp_path / "wt-254", minutes_ago=5)
    seed_run(db, run_id="R254", status="open", ticket="254",
              worktree_branch="harness/254", worktree_path=str(worktree),
              started_at=iso_minutes_ago(240))
    seed_checkpoint(db, "R254", branch="harness/254",
                     timestamp=iso_minutes_ago(160))  # last event, already stale
    stub = make_sweep_stub([{"identifier": "254", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    # The live run is left strictly alone: no revert, no label, no comment.
    stub.transition_to_unstarted.assert_not_awaited()
    stub.apply_label.assert_not_awaited()
    stub.post_comment.assert_not_awaited()
    assert fetch_row(db, "R254")["status"] == "open"  # type: ignore[index]
    payload = json.loads(result.stdout)
    assert payload["reclaimed"] == []
    assert payload["skipped"] == ["254"]


def test_stale_sweep_reclaims_when_the_worktree_is_also_stale(tmp_path: Path) -> None:
    """AC-2: all three clocks stale → still reclaimed. The fix narrows, not blocks."""
    db = tmp_path / "harness.db"
    worktree = seed_worktree(tmp_path / "wt-dead", minutes_ago=180)
    seed_run(db, run_id="RWDEAD", status="open", ticket="301",
              worktree_branch="harness/301", worktree_path=str(worktree),
              started_at=iso_minutes_ago(240))
    stub = make_sweep_stub([{"identifier": "301", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("301")
    assert fetch_row(db, "RWDEAD")["status"] == "cancelled"  # type: ignore[index]
    assert json.loads(result.stdout)["reclaimed"][0]["ticket"] == "301"


def test_stale_sweep_reclaims_when_the_run_recorded_no_worktree_path(
    tmp_path: Path,
) -> None:
    """AC-2 tail: a NULL ``worktree_path`` is no opinion, not a spare.

    Every pre-CAL-570 run row, and any row a caller wrote without the column, has
    nothing to probe. The ticket falls back to the tracker+ledger verdict.
    """
    db = tmp_path / "harness.db"
    seed_run(db, run_id="RNOPATH", status="open", ticket="302",
              worktree_branch="harness/302", worktree_path=None,
              started_at=iso_minutes_ago(240))
    stub = make_sweep_stub([{"identifier": "302", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("302")
    assert json.loads(result.stdout)["reclaimed"][0]["ticket"] == "302"


def test_stale_sweep_reclaims_when_the_worktree_path_is_absent(tmp_path: Path) -> None:
    """AC-2 tail, the cloud regime: a recorded path that does not resolve here.

    ``start`` records the path as the *container* saw it (``/workspace/…``), so a
    ledger read on another host — or in a fresh container — names a directory that
    is simply not there. No opinion, today's behaviour.
    """
    db = tmp_path / "harness.db"
    seed_run(db, run_id="RGONEPATH", status="open", ticket="303",
              worktree_branch="harness/303",
              worktree_path=str(tmp_path / "never-existed"),
              started_at=iso_minutes_ago(240))
    stub = make_sweep_stub([{"identifier": "303", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
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
    seed_run(db, run_id="RPLAIN", status="open", ticket="304",
              worktree_branch="harness/304", worktree_path=str(plain),
              started_at=iso_minutes_ago(240))
    stub = make_sweep_stub([{"identifier": "304", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
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
    seed_run(db, run_id="RNESTED", status="open", ticket="305",
              worktree_branch="harness/305", worktree_path=str(nested),
              started_at=iso_minutes_ago(240))
    stub = make_sweep_stub([{"identifier": "305", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
        ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("305")
    assert json.loads(result.stdout)["reclaimed"][0]["ticket"] == "305"


def test_stale_sweep_reclaims_when_the_worktree_index_is_empty(tmp_path: Path) -> None:
    """A git tree with nothing tracked has no mtime to read — no opinion.

    The file exists and is fresh, but it was never ``git add``ed, so ``ls-files``
    lists nothing. This is the documented limit of the signal (the index bounds
    the scan) and the reason ``--undo`` is the backstop.
    """
    db = tmp_path / "harness.db"
    empty = init_repo(tmp_path / "wt-untracked")
    (empty / "never-added.py").write_text("live edits, never staged\n")
    seed_run(db, run_id="REMPTY", status="open", ticket="306",
              worktree_branch="harness/306", worktree_path=str(empty),
              started_at=iso_minutes_ago(240))
    stub = make_sweep_stub([{"identifier": "306", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
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
    worktree = seed_worktree(tmp_path / "wt-deleted", minutes_ago=200)
    (worktree / "impl.py").unlink()
    seed_run(db, run_id="RDELETED", status="open", ticket="307",
              worktree_branch="harness/307", worktree_path=str(worktree),
              started_at=iso_minutes_ago(240))
    stub = make_sweep_stub([{"identifier": "307", "updated_at": iso_minutes_ago(300)}])

    result = invoke(
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
    worktree = seed_worktree(tmp_path / "wt-wedged", minutes_ago=1)  # fresh!
    seed_run(db, run_id="RWEDGED", status="open", ticket="308",
              worktree_branch="harness/308", worktree_path=str(worktree),
              started_at=iso_minutes_ago(240))
    stub = make_sweep_stub([{"identifier": "308", "updated_at": iso_minutes_ago(300)}])

    real_run_git = reclaim_liveness.run_git

    def _wedge(cwd: Path, *args: str, **kwargs: Any) -> Any:
        if args[:1] == ("ls-files",):
            raise subprocess.TimeoutExpired(cmd="git ls-files", timeout=15)
        return real_run_git(cwd, *args, **kwargs)

    with patch.object(reclaim_liveness, "run_git", _wedge):
        result = invoke(
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
    worktree = seed_worktree(tmp_path / "wt-broken", minutes_ago=1)  # fresh!
    seed_run(db, run_id="RBROKEN", status="open", ticket="309",
              worktree_branch="harness/309", worktree_path=str(worktree),
              started_at=iso_minutes_ago(240))
    stub = make_sweep_stub([{"identifier": "309", "updated_at": iso_minutes_ago(300)}])

    real_run_git = reclaim_liveness.run_git

    def _fail(cwd: Path, *args: str, **kwargs: Any) -> Any:
        if args[:1] == ("ls-files",):
            return subprocess.CompletedProcess(
                args=["git"], returncode=128, stdout="impl.py\0",
                stderr="fatal: index file corrupt",
            )
        return real_run_git(cwd, *args, **kwargs)

    with patch.object(reclaim_liveness, "run_git", _fail):
        result = invoke(
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
    fresh = seed_worktree(tmp_path / "wt-in", minutes_ago=10)
    stale = seed_worktree(tmp_path / "wt-out", minutes_ago=50)
    seed_run(db, run_id="RWIN", status="open", ticket="310",
              worktree_branch="harness/310", worktree_path=str(fresh),
              started_at=iso_minutes_ago(200))
    seed_run(db, run_id="RWOUT", status="open", ticket="311",
              worktree_branch="harness/311", worktree_path=str(stale),
              started_at=iso_minutes_ago(200))
    stub = make_sweep_stub(
        [
            {"identifier": "310", "updated_at": iso_minutes_ago(300)},
            {"identifier": "311", "updated_at": iso_minutes_ago(300)},
        ]
    )

    result = invoke(
        ["reclaim", "--stale", "--project", "Harness", "--older-than", "30m",
         "--json", "--db", str(db)],
        stub,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
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
    worktree = seed_worktree(tmp_path / "wt-fresh-tracker", minutes_ago=200)
    seed_run(db, run_id="RFRESHTRACKER", status="open", ticket="312",
              worktree_branch="harness/312", worktree_path=str(worktree),
              started_at=iso_minutes_ago(240))
    stub = make_sweep_stub([{"identifier": "312", "updated_at": iso_minutes_ago(5)}])

    def _never(_worktree: Path) -> None:
        raise AssertionError("the worktree probe ran for a tracker-fresh ticket")

    with patch.object(reclaim_liveness, "worktree_last_activity", _never):
        result = invoke(
            ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
            stub,
        )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["skipped"] == ["312"]


def test_stale_sweep_does_not_probe_when_the_ledger_is_already_fresh(
    tmp_path: Path,
) -> None:
    """Nor does a ledger-fresh ticket: the cheaper signal short-circuits first."""
    db = tmp_path / "harness.db"
    worktree = seed_worktree(tmp_path / "wt-ledger-fresh", minutes_ago=200)
    seed_run(db, run_id="RLEDGERFRESH", status="open", ticket="313",
              worktree_branch="harness/313", worktree_path=str(worktree),
              started_at=iso_minutes_ago(10))
    stub = make_sweep_stub([{"identifier": "313", "updated_at": iso_minutes_ago(300)}])

    def _never(_worktree: Path) -> None:
        raise AssertionError("the worktree probe ran for a ledger-fresh ticket")

    with patch.object(reclaim_liveness, "worktree_last_activity", _never):
        result = invoke(
            ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
            stub,
        )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["skipped"] == ["313"]


def test_stale_sweep_does_not_probe_when_there_is_no_open_run(tmp_path: Path) -> None:
    """No open run row → no probe at all, and the revert-only path runs unchanged."""
    db = tmp_path / "harness.db"
    run_sync(store.init_db(db))  # reachable ledger, no row for this ticket
    stub = make_sweep_stub([{"identifier": "314", "updated_at": iso_minutes_ago(300)}])

    def _never(_worktree: Path) -> None:
        raise AssertionError("the worktree probe ran with no open run row")

    with patch.object(reclaim_liveness, "worktree_last_activity", _never):
        result = invoke(
            ["reclaim", "--stale", "--project", "Harness", "--json", "--db", str(db)],
            stub,
        )
    assert result.exit_code == 0, result.output
    stub.transition_to_unstarted.assert_awaited_once_with("314")


# ===========================================================================
# #297: the declared mode rides on the same row as the three clocks
# ===========================================================================


def _liveness(db: Path, ticket: str) -> reclaim_liveness.RunLiveness | None:
    """``open_run_liveness`` driven directly — the projection under test."""
    return run_sync(reclaim_liveness.open_run_liveness(db, ticket))


def test_the_projection_reads_a_declared_attended_row(tmp_path: Path) -> None:
    """An attended run's mode reaches the sweep off the *same* row as its clocks.

    Unit-level on ``open_run_liveness`` rather than only through the verb: a
    wiring mistake — projecting the wrong column, or forgetting the parse — is
    localised here instead of surfacing three layers up as a mysterious
    reclamation.
    """
    db = tmp_path / "harness.db"
    seed_run(db, run_id="R-ATT", status="open", ticket="ATT-1", attended=True)

    liveness = _liveness(db, "ATT-1")

    assert liveness is not None
    assert liveness.attended is True
    assert liveness.run_id == "R-ATT"


def test_the_projection_reads_an_undeclared_row_as_unattended(tmp_path: Path) -> None:
    """The ``"{}"`` every pre-#295 row holds means unattended, as it always did."""
    db = tmp_path / "harness.db"
    seed_run(db, run_id="R-UNATT", status="open", ticket="UNATT-1")

    liveness = _liveness(db, "UNATT-1")

    assert liveness is not None
    assert liveness.attended is False


def test_the_projection_reads_a_hand_edited_row_as_unattended(tmp_path: Path) -> None:
    """A corrupted or hand-edited ``inputs_json`` fails *toward* the bound.

    Declaring attendance is what buys the longer threshold, so every ambiguous
    value must resolve unattended — the strictness ``resolve_attended`` owns
    (#295), exercised here at the seam that now consumes it. A ``bool()``-style
    parse would read ``"true"`` as a declaration.
    """
    db = tmp_path / "harness.db"
    seed_run(db, run_id="R-BAD", status="open", ticket="BAD-1")

    async def _corrupt() -> None:
        async with store.connect(db) as conn:
            await conn.execute(
                "UPDATE runs SET inputs_json = ? WHERE run_id = ?", ('"true"', "R-BAD")
            )
            await conn.commit()

    run_sync(_corrupt())

    liveness = _liveness(db, "BAD-1")

    assert liveness is not None
    assert liveness.attended is False


def test_the_projection_has_no_opinion_without_an_open_run(tmp_path: Path) -> None:
    """No open row → ``None``, so there is no mode to inherit (AC-5's seam)."""
    db = tmp_path / "harness.db"
    run_sync(store.init_db(db))

    assert _liveness(db, "ABSENT-1") is None
