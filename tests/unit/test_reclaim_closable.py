"""Tests for the ``harness reclaim --stale`` closable classifier (#255).

Split from ``test_cli_reclaim.py`` in #274; covers
``harness/cli/reclaim_closable.py``. A run that passed ``review`` and then lost
its session is still ``open``, and ``close`` has no spend breaker — so it was
finishable in place the whole time. Reverting it to Todo would throw away a
passing review and force a fresh run to re-design and re-review to reach a
``close`` that was one command away, so the sweep reports it in a third list and
leaves it completely alone: no revert, no label, no comment, no ledger write.

Contract under test:

* The classifier is additive in the same one-way shape as #216/#254 — it can only
  divert a ticket the sweep was *already about to revert*, and every uncertainty
  (no ledger, an unreachable worktree, a wedged git probe) resolves to "not
  closable", i.e. to today's behaviour.
* **Ordering is load-bearing.** ``locally_live`` is checked first, so a live
  session paused at a clean, previously-passed HEAD reads as ``skipped`` (spared
  because alive), never ``closable`` (finished, and therefore drainable). The two
  mean opposite things downstream.
* A dirty worktree, a pass bound to a different SHA, a pass carrying no
  verify-gate evidence, and a run whose only verdict is ``fail`` are all *not*
  closable.
* The sweep stays a classifier: it closes nothing itself, and reports the same
  closable run on every tick.

The three cross-arm tests live here rather than with the verb because the third
outcome is what makes them non-trivial — disjointness/totality of the three
outcomes, the spared-before-closable ordering, and the anti-drift pin that the
``closable`` predicate agrees with ``close``'s own gate.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import call, patch

from harness.cli import _review_gate, reclaim, reclaim_closable, reclaim_liveness
from harness.cli import close as close_mod
from harness.state import store
from tests._asyncutil import run_sync
from tests._gitutil import init_repo
from tests._reclaim import (
    fetch_events,
    fetch_row,
    invoke,
    iso_minutes_ago,
    make_sweep_stub,
    seed_run,
    seed_worktree,
)

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
