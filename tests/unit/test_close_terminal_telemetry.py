"""#263 — ``close`` records its gate refusals (sizing the ``stale_review`` rate).

Every one of ``close``'s gate refusals raised before any ledger write, so the
close gate's refusal *rate* was unrecorded: the ledger held landed merges and no
denominator. That blocks a specific decision — ADR 0010 accepted delta-scoped
re-review on a 24-excess-pass **upper bound** precisely because the
``stale_review`` rate could not be measured. These tests pin the row that
produces the number.

Per [ADR 0009] the event type stays ``close`` and an ``outcome`` field
discriminates, exactly as #262 did for ``review``. ``close`` needs **three**
values where ``review`` had two, and they are the verb's own exit codes named:
``ok`` (0), ``refused`` (2 — the gate declined before any side effect) and
``failed`` (1). Keying on the exit code rather than on which ``reason`` fired is
what stops the two drifting: a ``reason`` added later cannot land on the wrong
side of a membership table, because there is no table.

Whether the merge **landed** is a separate fact, carried by ``merged_sha`` and
not by ``outcome`` — the two are genuinely independent, since a ticket
transition can fail (exit 1) with the merge already in. That separation is what
stops the ledger reporting a landed merge as a blocked one.

These tests pin:

* AC-1 — one test per recordable refusal (``dirty_worktree`` /
  ``no_passing_review`` / ``stale_review`` / ``no_gate_evidence``), asserting
  **exactly one** event with the right ``reason``, ``outcome='refused'``, no
  ``merged_sha``, and an unchanged exit code;
* AC-2 — ``no_run`` writes **no** event and its refusal JSON is unchanged;
* AC-3 — each ``FailureReason`` is recorded, carries the merged SHA, and is
  distinguishable from a gate refusal by ``outcome`` — not by a reader
  enumerating the ``reason`` vocabulary;
* AC-4 — an observation write that raises alters neither exit code nor JSON;
* AC-5 — the ``stale_review`` rate is one SQL query over the ledger;
* and the hazard the ticket's own design did not name: a refusal row must not be
  readable as a landed close. #233 made the ``close`` event's *existence* carry
  the "tracker confirmed Done" claim, so putting non-success rows under the same
  type would silently widen it. Both the ``outcome`` discriminator and the absent
  ``merged_sha`` keep it narrow, and both are pinned here rather than left to
  inspection.

Fixtures mirror ``test_cli_close.py``: the tracker client and the git merge/push
are faked, and the ledger is seeded directly.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli import close as close_mod
from harness.cli.close_telemetry import outcome_for_exit_code
from harness.events import observation as observation_mod
from harness.events.emitter import EventEmitter
from harness.events.payloads import (
    CLOSE_OUTCOME_FAILED,
    CLOSE_OUTCOME_OK,
    CLOSE_OUTCOME_PATH,
    CLOSE_OUTCOME_REFUSED,
    CLOSE_REASON_PATH,
    CLOSE_UNEXPECTED_REASON,
)
from harness.state import store

cli_runner = CliRunner()

RUN_ID = "01JRUNCLOSETELEMETRYXXXXX1"
TICKET = "CAL-572"

# Both ends of the *event's* duration are pinned, so the assertion is an exact
# integer rather than a tolerance window. Note this is the close **verb's** own
# invocation duration — distinct from #261's run-lifetime ``runs.duration_ms``,
# which measures ``started_at`` → ``completed_at``.
SEEDED_STARTED_AT = "2026-06-10T00:00:00Z"
FIXED_INVOKED_AT = "2026-06-10T00:01:00.000000Z"
FIXED_CLOSED_AT = "2026-06-10T00:01:02.500000Z"
LATER_CLOCK_READING = "2026-06-10T00:09:00.000000Z"
EXPECTED_EVENT_DURATION_MS = 2_500


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture(autouse=True)
def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "dev")
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    (repo_root / ".gitignore").write_text(".harness/\n.worktrees/\n")
    (repo_root / "README.md").write_text("hello\n")
    _git(repo_root, "add", ".gitignore", "README.md")
    _git(repo_root, "commit", "-m", "initial")
    return repo_root


@pytest.fixture
def db_path(repo: Path) -> Path:
    return repo / ".harness" / "harness.db"


def _sync(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _head_sha(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _pin_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hand ``close`` ``invoked_at`` then its terminal reading, then a later one.

    Distinct successive readings on purpose (#261's lesson): a constant stub
    cannot tell one clock reading from two, so an implementation that read the
    clock again would still satisfy an equality the pinning exists to enforce.
    The refusal path reads its clock in ``close_telemetry``, which imports
    ``iso_z`` from ``harness._time`` — patched at the source so both paths draw
    from the same iterator.
    """
    readings = iter([FIXED_INVOKED_AT, FIXED_CLOSED_AT])
    stub = lambda *_a, **_k: next(readings, LATER_CLOCK_READING)  # noqa: E731
    monkeypatch.setattr(close_mod, "iso_z", stub)
    monkeypatch.setattr("harness.cli.close_telemetry.iso_z", stub)


# ``runs.ticket`` is UNIQUE, so a test seeding more than one run must give each
# its own ticket — and pass the same one to ``_invoke``, since the payload
# records the ticket the close was for.
def _seed_open_run(
    db_path: Path, repo: Path, run_id: str = RUN_ID, ticket: str = TICKET
) -> str:
    async def _insert() -> None:
        await store.init_db(db_path)
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs ("
                "run_id, workflow_name, workflow_version, status, state_json, "
                "inputs_json, base_branch, worktree_path, worktree_branch, "
                "ticket, started_at, pid"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    "",
                    0,
                    "open",
                    "{}",
                    "{}",
                    "dev",
                    str(repo),
                    f"harness/{run_id}",
                    ticket,
                    SEEDED_STARTED_AT,
                    1234,
                ),
            )
            await conn.commit()

    _sync(_insert())
    return run_id


_GREEN_GATE_EVIDENCE = {
    "gate_ran": True,
    "gate_command": "bash scripts/verify.sh",
    "gate_exit_code": 0,
}


def _emit_review(
    db_path: Path,
    run_id: str,
    reviewed_sha: str,
    verdict: str = "pass",
    gate: dict[str, Any] | None = None,
) -> None:
    async def _emit() -> None:
        await EventEmitter(db_path).emit(
            run_id=run_id,
            event_type="review",
            data={
                "run_id": run_id,
                "reviewed_sha": reviewed_sha,
                "verdict": verdict,
                "issues": [],
                "created_at": "2026-06-10T00:00:00Z",
                **(_GREEN_GATE_EVIDENCE if gate is None else gate),
            },
        )

    _sync(_emit())


async def _fetch_close_payloads(db_path: Path, run_id: str) -> list[dict[str, Any]]:
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT data_json FROM events WHERE run_id = ? AND event_type = 'close' ORDER BY id",
            (run_id,),
        ) as cur,
    ):
        rows = await cur.fetchall()
    return [json.loads(row[0]) for row in rows]


def fetch_close_payloads(db_path: Path, run_id: str) -> list[dict[str, Any]]:
    return _sync(_fetch_close_payloads(db_path, run_id))


def _make_tracker_stub(raise_on_transition: Exception | None = None) -> MagicMock:
    stub = MagicMock()
    if raise_on_transition is not None:
        stub.transition_to_done = AsyncMock(side_effect=raise_on_transition)
    else:
        stub.transition_to_done = AsyncMock(return_value=None)
    return stub


def _invoke(
    repo: Path,
    db_path: Path,
    run_id: str,
    tracker_stub: MagicMock | None = None,
    merge_push: MagicMock | None = None,
    ticket: str = TICKET,
) -> Any:
    stub = tracker_stub if tracker_stub is not None else _make_tracker_stub()
    merge = merge_push if merge_push is not None else MagicMock(return_value=None)
    with (
        patch("harness.tracker.LinearClient", return_value=stub),
        patch("harness.tracker.linear_api_key", return_value="test-key"),
        patch("harness.close_merge.merge_run_branch", merge),
    ):
        result = cli_runner.invoke(
            app,
            [
                "close",
                ticket,
                "--repo",
                str(repo),
                "--db",
                str(db_path),
                "--run-id",
                run_id,
                "--json",
            ],
        )
    return result, merge, stub


# ---------------------------------------------------------------------------
# AC-1 — every recordable gate refusal writes exactly one event
# ---------------------------------------------------------------------------


def _assert_one_refusal(db_path: Path, run_id: str, reason: str) -> dict[str, Any]:
    payloads = fetch_close_payloads(db_path, run_id)
    assert len(payloads) == 1, f"exactly one event — a double-emit fails too: {payloads}"
    assert payloads[0]["reason"] == reason
    assert payloads[0]["outcome"] == CLOSE_OUTCOME_REFUSED
    assert "merged_sha" not in payloads[0], "nothing merged, so nothing to report merged"
    return payloads[0]


def test_ac1_dirty_worktree_refusal_is_recorded(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo))
    (repo / "scratch.txt").write_text("uncommitted\n")

    result, merge, _stub = _invoke(repo, db_path, run_id)

    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "dirty_worktree"
    merge.assert_not_called()
    _assert_one_refusal(db_path, run_id, "dirty_worktree")


def test_ac1_no_passing_review_refusal_is_recorded(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)

    result, merge, _stub = _invoke(repo, db_path, run_id)

    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "no_passing_review"
    merge.assert_not_called()
    _assert_one_refusal(db_path, run_id, "no_passing_review")


def test_ac1_stale_review_refusal_is_recorded(repo: Path, db_path: Path) -> None:
    """The datum ADR 0010 is waiting on: how often does a pass go stale?"""
    run_id = _seed_open_run(db_path, repo)
    reviewed = _head_sha(repo)
    _emit_review(db_path, run_id, reviewed)
    (repo / "feature.txt").write_text("more work\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "more work")
    assert _head_sha(repo) != reviewed

    result, merge, _stub = _invoke(repo, db_path, run_id)

    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "stale_review"
    merge.assert_not_called()
    _assert_one_refusal(db_path, run_id, "stale_review")


def test_ac1_no_gate_evidence_refusal_is_recorded(repo: Path, db_path: Path) -> None:
    """In scope, contra the proposal's prose: it is a gate conjunct returned by
    ``_evaluate_gate`` on a fully resolved run, so excluding it would leave the
    *fifth* declared ``RefusalReason`` as the only unmeasured one."""
    run_id = _seed_open_run(db_path, repo)
    # A legacy pass: covers HEAD, but carries no verify-gate evidence (CAL-1082).
    _emit_review(db_path, run_id, _head_sha(repo), gate={})

    result, merge, _stub = _invoke(repo, db_path, run_id)

    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "no_gate_evidence"
    merge.assert_not_called()
    _assert_one_refusal(db_path, run_id, "no_gate_evidence")


def test_ac1_refusal_event_carries_the_run_ticket_and_detail(
    repo: Path, db_path: Path
) -> None:
    """The row is diagnosable on its own: which run, which ticket, and the verb's
    own message — the ``reason``-to-branch-on / message-to-diagnose-from split
    ``VerbError`` already makes."""
    run_id = _seed_open_run(db_path, repo)

    result, _merge, _stub = _invoke(repo, db_path, run_id)

    payload = fetch_close_payloads(db_path, run_id)[0]
    assert payload["run_id"] == run_id
    assert payload["ticket"] == TICKET
    assert payload["detail"] == json.loads(result.output)["error"]


def test_ac1_untagged_tracker_config_refusal_is_recorded(
    repo: Path, db_path: Path
) -> None:
    """The fifth exit-2 path: an unconfigured tracker. It is deliberately
    untagged in its printed JSON, so it records :data:`CLOSE_UNEXPECTED_REASON`
    rather than a NULL — in the denominator without pretending to a tag it never
    carried. Giving it a ``reason`` would change the printed refusal JSON, which
    this ticket holds fixed."""
    run_id = _seed_open_run(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo))

    with patch(
        "harness.cli.close.tracker_client",
        side_effect=close_mod.TrackerConfigError("LINEAR_API_KEY is not set"),
    ):
        result = cli_runner.invoke(
            app,
            ["close", TICKET, "--repo", str(repo), "--db", str(db_path),
             "--run-id", run_id, "--json"],
        )

    assert result.exit_code == 2, result.output
    assert "reason" not in json.loads(result.output), "printed JSON unchanged"

    payloads = fetch_close_payloads(db_path, run_id)
    assert len(payloads) == 1
    assert payloads[0]["outcome"] == CLOSE_OUTCOME_REFUSED
    assert payloads[0]["reason"] == CLOSE_UNEXPECTED_REASON
    assert "merged_sha" not in payloads[0]


# ---------------------------------------------------------------------------
# AC-2 — ``no_run`` writes nothing (the accepted, deliberate limitation)
# ---------------------------------------------------------------------------


def test_ac2_no_run_refusal_writes_no_event(repo: Path, db_path: Path) -> None:
    """``events.run_id`` is ``NOT NULL`` with an FK to ``runs``, so a refusal
    with no resolved run has nothing to anchor to. ADR 0009 accepts the gap
    rather than paying for it with synthetic ``runs`` rows — asserted so it stays
    deliberate rather than becoming accidental, and so a later reader does not
    "fix" it. It is the one hole in the denominator: the measured rate is per
    *resolved-run* close attempt."""
    _sync(store.init_db(db_path))

    result, merge, _stub = _invoke(repo, db_path, RUN_ID)

    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == "no_run"
    assert set(payload) == {"error", "reason"}, "refusal JSON unchanged"
    merge.assert_not_called()

    assert _sync(_count_all_close_events(db_path)) == 0


async def _count_all_close_events(db_path: Path) -> int:
    async with (
        store.connect(db_path) as conn,
        conn.execute("SELECT COUNT(*) FROM events WHERE event_type = 'close'") as cur,
    ):
        row = await cur.fetchone()
    return int(row[0])


# ---------------------------------------------------------------------------
# AC-3 — a post-merge ticket failure is recorded, and is NOT a gate refusal
# ---------------------------------------------------------------------------


def test_ac3_ticket_transition_failed_is_recorded_with_the_merged_sha(
    repo: Path, db_path: Path
) -> None:
    from harness.tracker_errors import TrackerRequestError

    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head)
    stub = _make_tracker_stub(TrackerRequestError("permission denied"))

    result, merge, _stub = _invoke(repo, db_path, run_id, tracker_stub=stub)

    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["reason"] == "ticket_transition_failed"
    merge.assert_called_once()

    payloads = fetch_close_payloads(db_path, run_id)
    assert len(payloads) == 1
    assert payloads[0]["reason"] == "ticket_transition_failed"
    assert payloads[0]["outcome"] == CLOSE_OUTCOME_FAILED
    assert payloads[0]["merged_sha"] == head, "the merge landed — the row must say so"


def test_ac3_ticket_transition_unconfirmed_is_recorded_with_the_merged_sha(
    repo: Path, db_path: Path
) -> None:
    from harness.tracker_errors import TrackerTransitionUnconfirmed

    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head)
    stub = _make_tracker_stub(TrackerTransitionUnconfirmed("post-write state is In Review"))

    result, merge, _stub = _invoke(repo, db_path, run_id, tracker_stub=stub)

    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["reason"] == "ticket_transition_unconfirmed"
    merge.assert_called_once()

    payloads = fetch_close_payloads(db_path, run_id)
    assert len(payloads) == 1
    assert payloads[0]["reason"] == "ticket_transition_unconfirmed"
    assert payloads[0]["outcome"] == CLOSE_OUTCOME_FAILED
    assert payloads[0]["merged_sha"] == head


def test_ac3_post_merge_failure_is_not_counted_as_a_blocked_close(
    repo: Path, db_path: Path
) -> None:
    """"Distinguishable" is the criterion, not "recorded": a query for "how often
    did the gate block a close?" must return none of these rows. ``outcome``
    carries that — a reader does not have to enumerate the ``reason``
    vocabulary to tell the two families apart."""
    from harness.tracker_errors import TrackerRequestError

    blocked = _seed_open_run(
        db_path, repo, run_id="01JRUNCLOSEBLOCKEDXXXXXXX1", ticket="CAL-901"
    )
    landed = _seed_open_run(
        db_path, repo, run_id="01JRUNCLOSELANDEDXXXXXXXX1", ticket="CAL-902"
    )
    _emit_review(db_path, landed, _head_sha(repo))

    _invoke(repo, db_path, blocked, ticket="CAL-901")  # no pass → gate refusal
    _invoke(
        repo,
        db_path,
        landed,
        tracker_stub=_make_tracker_stub(TrackerRequestError("boom")),
        ticket="CAL-902",
    )

    async def _refused_run_ids() -> list[str]:
        async with (
            store.connect(db_path) as conn,
            conn.execute(
                "SELECT run_id FROM events WHERE event_type = 'close' "
                f"AND json_extract(data_json, '{CLOSE_OUTCOME_PATH}') = ?",
                (CLOSE_OUTCOME_REFUSED,),
            ) as cur,
        ):
            rows = await cur.fetchall()
        return [row[0] for row in rows]

    assert _sync(_refused_run_ids()) == [blocked]


def test_outcome_for_exit_code_maps_the_verbs_documented_codes() -> None:
    """The mapping has one home and its own test, because it is the join between
    two published contracts: the verb's exit codes and the payload's
    discriminator."""
    assert outcome_for_exit_code(2) == CLOSE_OUTCOME_REFUSED
    assert outcome_for_exit_code(1) == CLOSE_OUTCOME_FAILED


# ---------------------------------------------------------------------------
# AC-4 — observation is subordinate to the thing observed (ADR 0009)
# ---------------------------------------------------------------------------


def test_ac4_observation_write_failure_leaves_exit_code_and_json_unchanged(
    repo: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A verb already refusing must refuse with exactly the exit code and JSON it
    had before this telemetry existed. Losing a row costs a statistic; letting
    its failure escape would cost the run its actual answer — and would do it at
    the moment the verb was already reporting a problem.

    The *real* emit is patched, not the writer: stubbing ``record_terminal_close``
    would only prove the stub raised.
    """
    run_id = _seed_open_run(db_path, repo)

    class _Exploding:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            raise RuntimeError("ledger is on fire")

    monkeypatch.setattr(observation_mod, "EventEmitter", _Exploding)
    broken, _merge, _stub = _invoke(repo, db_path, run_id)
    assert fetch_close_payloads(db_path, run_id) == [], "no partial row left behind"

    # The same refusal on the same run with the writer healthy: the gate reads
    # only the ledger and touches nothing, so the two invocations are comparable
    # byte for byte rather than merely similarly shaped.
    monkeypatch.undo()
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(repo.parent))
    healthy, _m, _s = _invoke(repo, db_path, run_id)

    assert broken.exit_code == healthy.exit_code == 2
    assert json.loads(broken.output) == json.loads(healthy.output)
    assert len(fetch_close_payloads(db_path, run_id)) == 1, "only the healthy write landed"


def test_ac4_unexpected_error_without_a_reason_is_still_recorded(
    repo: Path, db_path: Path
) -> None:
    """A raise site carrying no ``reason`` of its own (here: a failed merge/push)
    records :data:`CLOSE_UNEXPECTED_REASON` rather than a NULL, so those paths
    stay distinguishable from one another in the aggregate instead of collapsing.
    The printed JSON keeps its historical bare ``{"error": ...}`` shape, and the
    row carries no ``merged_sha`` — the merge did not land."""
    run_id = _seed_open_run(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo))
    exploding_merge = MagicMock(side_effect=RuntimeError("push exploded"))

    result, _merge, _stub = _invoke(repo, db_path, run_id, merge_push=exploding_merge)

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert "reason" not in payload, "an unreasoned raise site keeps its bare JSON"

    payloads = fetch_close_payloads(db_path, run_id)
    assert len(payloads) == 1
    assert payloads[0]["reason"] == CLOSE_UNEXPECTED_REASON
    assert payloads[0]["outcome"] == CLOSE_OUTCOME_FAILED
    assert "merged_sha" not in payloads[0]


# ---------------------------------------------------------------------------
# AC-5 — the rate is one SQL query
# ---------------------------------------------------------------------------


def test_ac5_stale_review_rate_is_one_sql_query(repo: Path, db_path: Path) -> None:
    """The whole point of the ticket: ADR 0010's upper bound becomes a measured
    rate. One query, no timestamp arithmetic, no joining against ``runs`` — and
    the measured quantity itself is asserted, not merely the shape that carries
    it."""
    for suffix, ticket in (("A", "CAL-911"), ("B", "CAL-912")):
        run_id = _seed_open_run(
            db_path, repo, run_id=f"01JRUNCLOSESTALE{suffix}XXXXXXX1", ticket=ticket
        )
        _emit_review(db_path, run_id, _head_sha(repo))
        (repo / f"feature{suffix}.txt").write_text("more\n")
        _git(repo, "add", f"feature{suffix}.txt")
        _git(repo, "commit", "-m", f"more {suffix}")
        _invoke(repo, db_path, run_id, ticket=ticket)  # stale_review

    landed = _seed_open_run(
        db_path, repo, run_id="01JRUNCLOSELANDEDOKXXXXXX1", ticket="CAL-913"
    )
    _emit_review(db_path, landed, _head_sha(repo))
    result, _merge, _stub = _invoke(repo, db_path, landed, ticket="CAL-913")
    assert result.exit_code == 0, result.output

    async def _rate() -> tuple[int, int]:
        async with (
            store.connect(db_path) as conn,
            conn.execute(
                "SELECT COUNT(*), "
                f"SUM(json_extract(data_json, '{CLOSE_REASON_PATH}') = ?) "
                "FROM events WHERE event_type = 'close'",
                ("stale_review",),
            ) as cur,
        ):
            row = await cur.fetchone()
        return int(row[0]), int(row[1] or 0)

    assert _sync(_rate()) == (3, 2)


def test_ac5_a_pre_existing_close_row_reads_as_a_landed_close(
    repo: Path, db_path: Path
) -> None:
    """No backfill: a row written before ``outcome`` existed must read as the
    landed close it in fact was. ``COALESCE`` is what makes the historical closes
    count in the denominator instead of reading as unknown."""
    run_id = _seed_open_run(db_path, repo)

    async def _seed_legacy() -> None:
        await EventEmitter(db_path).emit(
            run_id=run_id,
            event_type="close",
            data={
                "run_id": run_id,
                "ticket": TICKET,
                "merged_sha": _head_sha(repo),
                "closed_at": "2026-06-10T00:00:00Z",
            },
        )

    _sync(_seed_legacy())

    async def _count_ok() -> int:
        async with (
            store.connect(db_path) as conn,
            conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_type = 'close' "
                f"AND COALESCE(json_extract(data_json, '{CLOSE_OUTCOME_PATH}'), ?) = ?",
                (CLOSE_OUTCOME_OK, CLOSE_OUTCOME_OK),
            ) as cur,
        ):
            row = await cur.fetchone()
        return int(row[0])

    assert _sync(_count_ok()) == 1


# ---------------------------------------------------------------------------
# The semantic this change moves: "did this run land?" is outcome, not presence
# ---------------------------------------------------------------------------


def test_a_retry_after_a_failed_transition_leaves_two_events_one_ok(
    repo: Path, db_path: Path
) -> None:
    """#233 made a ``close`` event's *existence* carry "the tracker was confirmed
    Done". Refusals now share the type, so the claim moves to ``outcome='ok'`` —
    the one semantic this change does move, and the pair of rows *is* the retry
    story."""
    from harness.tracker_errors import TrackerTransitionUnconfirmed

    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head)

    first, _m, _s = _invoke(
        repo,
        db_path,
        run_id,
        tracker_stub=_make_tracker_stub(TrackerTransitionUnconfirmed("not yet Done")),
    )
    assert first.exit_code == 1, first.output

    second, _m2, _s2 = _invoke(repo, db_path, run_id)
    assert second.exit_code == 0, second.output

    payloads = fetch_close_payloads(db_path, run_id)
    assert [p["outcome"] for p in payloads] == [CLOSE_OUTCOME_FAILED, CLOSE_OUTCOME_OK]
    assert [p["merged_sha"] for p in payloads] == [head, head]


def test_success_event_records_outcome_and_its_own_duration(
    repo: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A landed close records ``outcome='ok'`` and the verb's own invocation
    latency. That duration is **not** #261's ``runs.duration_ms``: this measures
    ``close``'s own work, that one measures the whole run's life."""
    run_id = _seed_open_run(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo))
    _pin_clock(monkeypatch)

    result, _merge, _stub = _invoke(repo, db_path, run_id)
    assert result.exit_code == 0, result.output

    payloads = fetch_close_payloads(db_path, run_id)
    assert len(payloads) == 1
    assert payloads[0]["outcome"] == CLOSE_OUTCOME_OK
    assert payloads[0]["merged_sha"] == _head_sha(repo)
    assert payloads[0]["invoked_at"] == FIXED_INVOKED_AT
    assert payloads[0]["closed_at"] == FIXED_CLOSED_AT
    assert payloads[0]["duration_ms"] == EXPECTED_EVENT_DURATION_MS


def test_refusal_event_records_its_own_duration(
    repo: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal is timed too — a gate that refuses after a slow git probe is a
    different operational fact from one decided on a ledger read."""
    run_id = _seed_open_run(db_path, repo)
    _pin_clock(monkeypatch)

    _invoke(repo, db_path, run_id)

    payload = fetch_close_payloads(db_path, run_id)[0]
    assert payload["invoked_at"] == FIXED_INVOKED_AT
    assert payload["created_at"] == FIXED_CLOSED_AT
    assert payload["duration_ms"] == EXPECTED_EVENT_DURATION_MS
