"""CAL-906 — the ledger-backed spend breakers wired into ``harness review``.

The review verb is the loop boundary: before it invokes an engine it counts the
prior ``review`` events for the run and reads the run's ``started_at``, then
enforces the two breakers from :mod:`harness.loop_budget`. A trip raises the
verb's refusal contract (a dedicated exit code + machine-readable ``reason``,
mirroring the CAL-866 infra-failure shape) and records **no** review event — the
engine is never run.

These tests inject a fake runner (no real engine) and seed the ledger directly,
exactly like ``test_cli_review.py``.
"""

from __future__ import annotations

import json
import subprocess
import unittest.mock as mock
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli import review as review_mod
from harness.cli._runs import attendance_inputs_json
from harness.loop_budget import (
    REVIEW_CYCLE_CEILING_REASON,
    WALL_CLOCK_BUDGET_REASON,
)
from harness.state import store
from tests._asyncutil import run_sync
from tests._ledger import seed_design_event

cli_runner = CliRunner()

_PASS_LINE = 'SUBMIT: {"verdict": "pass", "issues": []}\n'
_FAIL_LINE = 'SUBMIT: {"verdict": "fail", "issues": ["x"]}\n'


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


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
    (repo_root / "README.md").write_text("hello\n")
    _git(repo_root, "add", "README.md")
    _git(repo_root, "commit", "-m", "initial")
    return repo_root


@pytest.fixture
def db_path(repo: Path) -> Path:
    return repo / ".harness" / "harness.db"


_RUN_ID = "01JRUNBREAKERXXXXXXXXXXXX01"


def _seed_run(
    db_path: Path,
    repo: Path,
    *,
    started_at: datetime,
    prior_fail_reviews: int = 0,
    attended: bool = False,
    inputs_json: str | None = None,
) -> str:
    """Seed an open run plus ``prior_fail_reviews`` recorded fail ``review`` events.

    ``attended`` writes the row through :func:`attendance_inputs_json` — the same
    writer ``start`` uses — so a seeded row can never disagree with production
    about how the key is spelled. ``inputs_json`` overrides it with a raw string,
    for the malformed-value case only.
    """

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
                    _RUN_ID,
                    "",
                    0,
                    "open",
                    "{}",
                    inputs_json
                    if inputs_json is not None
                    else attendance_inputs_json(attended),
                    "dev",
                    str(repo),
                    f"harness/{_RUN_ID}",
                    "CAL-906",
                    started_at.isoformat(),
                    1234,
                ),
            )
            for _ in range(prior_fail_reviews):
                await conn.execute(
                    "INSERT INTO events (run_id, event_type, timestamp, data_json) "
                    "VALUES (?, 'review', ?, ?)",
                    (
                        _RUN_ID,
                        started_at.isoformat(),
                        json.dumps({"verdict": "fail", "reviewed_sha": "deadbeef"}),
                    ),
                )
            await conn.commit()

    run_sync(_insert())
    # #212: review requires a recorded design attempt. These tests are about the
    # spend breakers, which refuse *before* that check — seeding it keeps the
    # non-tripping cases reaching the engine as they always did.
    seed_design_event(db_path, _RUN_ID)
    return _RUN_ID


def _tracking_runner(stdout: str, calls: list[int]) -> Any:
    """A fake engine runner that records each time it is invoked."""

    async def _runner(
        *,
        cmd: list[str],
        stdin: str,
        env: dict[str, str],
        cwd: Path | None,
        timeout: float | None = None,
    ) -> review_mod.RunResult:
        calls.append(1)
        return review_mod.RunResult(stdout=stdout, stderr="", returncode=0)

    return _runner


def _invoke(repo: Path, db_path: Path, runner: Any, *, linear_stub: Any | None = None) -> Any:
    argv = ["review", "--repo", str(repo), "--db", str(db_path), "--run-id", _RUN_ID, "--json"]
    with mock.patch.object(review_mod, "_default_runner", runner):
        if linear_stub is None:
            return cli_runner.invoke(app, argv)
        with (
            mock.patch("harness.tracker.LinearClient", return_value=linear_stub),
            mock.patch("harness.tracker.linear_api_key", return_value="test-key"),
        ):
            return cli_runner.invoke(app, argv)


def _review_events(db_path: Path) -> list[dict[str, Any]]:
    async def _fetch() -> list[dict[str, Any]]:
        async with (
            store.connect(db_path) as conn,
            conn.execute(
                "SELECT data_json FROM events WHERE event_type = 'review'"
            ) as cur,
        ):
            rows = await cur.fetchall()
        return [json.loads(r[0]) for r in rows]

    return run_sync(_fetch())


# ---------------------------------------------------------------------------
# AC-1: the call after the cycle budget stops + escalates, and runs no engine
# ---------------------------------------------------------------------------


def test_the_call_after_the_budget_refuses_without_running_the_engine(
    repo: Path, db_path: Path
) -> None:
    """5 prior reviews spend the whole budget → the next call trips, no engine."""
    _seed_run(db_path, repo, started_at=datetime.now(UTC), prior_fail_reviews=5)
    calls: list[int] = []
    result = _invoke(repo, db_path, _tracking_runner(_FAIL_LINE, calls))

    assert result.exit_code == review_mod.EXIT_BREAKER_TRIPPED
    payload = json.loads(result.output)
    assert payload["reason"] == REVIEW_CYCLE_CEILING_REASON
    assert calls == [], "the engine must not run once the ceiling is reached"
    # No 6th *verdict*: the trip records its refusal (#262) but the 5 seeded
    # fails stay the only events carrying one — and the refusal row must not
    # itself count toward the ceiling, or the budget would shrink as it is spent.
    events = _review_events(db_path)
    assert len([e for e in events if "verdict" in e]) == 5, events
    assert events[-1]["reason"] == REVIEW_CYCLE_CEILING_REASON
    assert run_sync(review_mod._count_review_events(db_path, _RUN_ID)) == 5


def test_breaker_trip_leaves_ticket_state_untouched(repo: Path, db_path: Path) -> None:
    """CAL-1103 AC-3: a breaker trip (exit 4) transitions nothing — the breaker
    check runs *before* review's In-Review move, so an escalating run's ticket
    stays where it stopped (In Progress)."""
    _seed_run(db_path, repo, started_at=datetime.now(UTC), prior_fail_reviews=5)
    stub = mock.MagicMock()
    stub.transition_to_in_review = mock.AsyncMock(return_value=None)
    stub.transition_to_in_progress = mock.AsyncMock(return_value=None)

    result = _invoke(repo, db_path, _tracking_runner(_FAIL_LINE, []), linear_stub=stub)

    assert result.exit_code == review_mod.EXIT_BREAKER_TRIPPED
    stub.transition_to_in_review.assert_not_awaited()
    stub.transition_to_in_progress.assert_not_awaited()


def test_fifth_cycle_still_runs(repo: Path, db_path: Path) -> None:
    """4 prior reviews → the 5th runs normally (engine invoked, event recorded)."""
    _seed_run(db_path, repo, started_at=datetime.now(UTC), prior_fail_reviews=4)
    calls: list[int] = []
    result = _invoke(repo, db_path, _tracking_runner(_FAIL_LINE, calls))

    assert result.exit_code == 0, result.output
    assert calls == [1], "the 5th cycle must run the engine"
    assert len(_review_events(db_path)) == 5


# ---------------------------------------------------------------------------
# AC-2: the judged window is surfaced as an advisory (retuned by #329)
# ---------------------------------------------------------------------------


def test_unconditional_cycle_has_no_convergence_advisory(repo: Path, db_path: Path) -> None:
    """The 2nd cycle (1 prior) is followed by another unconditional one (#329).

    The advisory speaks about the cycle the agent would spend *next*, so it is
    silent only while that next cycle is still unconditional. At the shipped 3/5
    that is cycles 1 and 2; the 3rd is covered by the sibling below, because the
    cycle it precedes is judged.
    """
    _seed_run(db_path, repo, started_at=datetime.now(UTC), prior_fail_reviews=1)
    result = _invoke(repo, db_path, _tracking_runner(_FAIL_LINE, []))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["convergence_check_required"] is False


def test_post_unconditional_fail_surfaces_convergence_advisory(
    repo: Path, db_path: Path
) -> None:
    """A fail preceding a judged cycle is flagged for convergence assessment (AC-2).

    3 prior reviews → this is cycle 4, whose fail precedes cycle 5 — the last
    the budget allows and the second the canonical rule requires a recorded
    judgment before.
    """
    _seed_run(db_path, repo, started_at=datetime.now(UTC), prior_fail_reviews=3)
    result = _invoke(repo, db_path, _tracking_runner(_FAIL_LINE, []))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["convergence_check_required"] is True


# ---------------------------------------------------------------------------
# #329: a fail on the last allowed cycle is surfaced as exhaustion
# ---------------------------------------------------------------------------


def test_a_fail_on_the_last_allowed_cycle_surfaces_exhaustion(
    repo: Path, db_path: Path
) -> None:
    """The 5th cycle's fail carries ``cycles_exhausted`` on verdict *and* ledger.

    This is what makes the stop land where the canonical rule says it lands. Its
    absence is not merely a missing field: the orchestrator would read an
    ordinary flagged fail, implement once more, and only learn the budget was
    gone from the exit-4 refusal of a call it should never have made.
    """
    _seed_run(db_path, repo, started_at=datetime.now(UTC), prior_fail_reviews=4)
    result = _invoke(repo, db_path, _tracking_runner(_FAIL_LINE, []))

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["cycles_exhausted"] is True
    assert payload["convergence_check_required"] is False, (
        "an exhausted run is not being asked to judge whether to spend another"
    )
    recorded = [e for e in _review_events(db_path) if "verdict" in e]
    assert recorded[-1]["cycles_exhausted"] is True


def test_a_fail_inside_the_budget_is_not_exhaustion(repo: Path, db_path: Path) -> None:
    """The 4th cycle still has one to spend, so it advises rather than ends."""
    _seed_run(db_path, repo, started_at=datetime.now(UTC), prior_fail_reviews=3)
    result = _invoke(repo, db_path, _tracking_runner(_FAIL_LINE, []))

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["cycles_exhausted"] is False
    assert payload["convergence_check_required"] is True


def test_a_pass_on_the_last_allowed_cycle_is_not_exhaustion(
    repo: Path, db_path: Path
) -> None:
    """Spending the last cycle on a pass is a finished run heading to ``close``."""
    _seed_run(db_path, repo, started_at=datetime.now(UTC), prior_fail_reviews=4)
    result = _invoke(repo, db_path, _tracking_runner(_PASS_LINE, []))

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["cycles_exhausted"] is False


# ---------------------------------------------------------------------------
# AC-3: the configured wall-clock is flagged at the verb boundary (#260 AC-5)
# ---------------------------------------------------------------------------


def test_wall_clock_exceeded_trips_at_review_boundary(repo: Path, db_path: Path) -> None:
    """A run older than the 110-minute budget trips the breaker on the next review.

    111 rather than 91: the budget is the configured
    ``loop.wall_clock_budget_minutes``, now 110 (#260), and a fixture sitting
    just inside it would pass for the wrong reason.
    """
    old = datetime.now(UTC) - timedelta(minutes=111)
    _seed_run(db_path, repo, started_at=old, prior_fail_reviews=0)
    calls: list[int] = []
    result = _invoke(repo, db_path, _tracking_runner(_FAIL_LINE, calls))

    assert result.exit_code == review_mod.EXIT_BREAKER_TRIPPED
    payload = json.loads(result.output)
    assert payload["reason"] == WALL_CLOCK_BUDGET_REASON
    assert calls == [], "the engine must not run past the wall-clock budget"


def test_wall_clock_within_budget_runs(repo: Path, db_path: Path) -> None:
    """A run well within the 110-minute budget reviews normally."""
    recent = datetime.now(UTC) - timedelta(minutes=5)
    _seed_run(db_path, repo, started_at=recent, prior_fail_reviews=0)
    result = _invoke(repo, db_path, _tracking_runner(_PASS_LINE, []))
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# #296 (ADR 0011): the wall clock is scoped to unattended runs
#
# The elapsed value below is the same 111 minutes
# ``test_wall_clock_exceeded_trips_at_review_boundary`` uses — that test is this
# pair's unattended half, end to end, and is deliberately left as written.
# ---------------------------------------------------------------------------

_PAST_BUDGET_MINUTES = 111


def test_attended_run_past_the_wall_clock_reaches_the_engine(
    repo: Path, db_path: Path
) -> None:
    """AC-5: an attended run past the budget reviews normally, engine and all.

    Asserting the engine *ran* and the verdict *landed* is stronger than
    asserting "not exit 4": it proves the run reached the engine rather than
    dying somewhere else on the way there.
    """
    old = datetime.now(UTC) - timedelta(minutes=_PAST_BUDGET_MINUTES)
    _seed_run(db_path, repo, started_at=old, prior_fail_reviews=0, attended=True)
    calls: list[int] = []
    result = _invoke(repo, db_path, _tracking_runner(_PASS_LINE, calls))

    assert result.exit_code == 0, result.output
    assert calls == [1], "the attended run must reach the engine"
    verdicts = [e for e in _review_events(db_path) if "verdict" in e]
    assert [e["verdict"] for e in verdicts] == ["pass"], verdicts


def test_attended_run_still_trips_the_cycle_ceiling(repo: Path, db_path: Path) -> None:
    """The ceiling is unconditional — attendance exempts the clock only."""
    _seed_run(
        db_path, repo, started_at=datetime.now(UTC), prior_fail_reviews=5, attended=True
    )
    calls: list[int] = []
    result = _invoke(repo, db_path, _tracking_runner(_FAIL_LINE, calls))

    assert result.exit_code == review_mod.EXIT_BREAKER_TRIPPED
    assert json.loads(result.output)["reason"] == REVIEW_CYCLE_CEILING_REASON
    assert calls == []


def test_a_non_literal_true_does_not_buy_the_exemption(
    repo: Path, db_path: Path
) -> None:
    """The verb routes ``inputs_json`` through ``resolve_attended``, not truthiness.

    A truthy-but-not-``true`` value is exactly what a hand-edited or corrupted
    ledger produces, and it must fail *toward* the bound. This pins the wiring;
    ``resolve_attended``'s own strictness table is #295's and is not restated.
    """
    old = datetime.now(UTC) - timedelta(minutes=_PAST_BUDGET_MINUTES)
    _seed_run(
        db_path,
        repo,
        started_at=old,
        prior_fail_reviews=0,
        inputs_json='{"attended": "true"}',
    )
    calls: list[int] = []
    result = _invoke(repo, db_path, _tracking_runner(_PASS_LINE, calls))

    assert result.exit_code == review_mod.EXIT_BREAKER_TRIPPED
    assert json.loads(result.output)["reason"] == WALL_CLOCK_BUDGET_REASON
    assert calls == []


# ---------------------------------------------------------------------------
# AC-4: the thresholds are read from CONTEXT.md, not hardcoded
# ---------------------------------------------------------------------------


def test_context_md_tightens_the_cycle_ceiling(repo: Path, db_path: Path) -> None:
    """A CONTEXT.md budget of 2 spends 2 cycles and refuses the 3rd call.

    The verb reads the configured budget, not a literal — and reads it with the
    #329 meaning: ``max_review_cycles`` is the count of cycles the run may
    spend, so a budget of 2 is exhausted by 2 prior reviews.
    """
    (repo / "CONTEXT.md").write_text(
        "```yaml\nloop:\n  max_review_cycles: 2\n  wall_clock_budget_minutes: 90\n```\n"
    )
    _seed_run(db_path, repo, started_at=datetime.now(UTC), prior_fail_reviews=2)
    calls: list[int] = []
    result = _invoke(repo, db_path, _tracking_runner(_FAIL_LINE, calls))

    assert result.exit_code == review_mod.EXIT_BREAKER_TRIPPED
    assert json.loads(result.output)["reason"] == REVIEW_CYCLE_CEILING_REASON
    assert calls == []
