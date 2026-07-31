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

import asyncio
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
from harness.loop_budget import (
    REVIEW_CYCLE_CEILING_REASON,
    WALL_CLOCK_BUDGET_REASON,
)
from harness.state import store
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


def _sync(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


_RUN_ID = "01JRUNBREAKERXXXXXXXXXXXX01"


def _seed_run(
    db_path: Path,
    repo: Path,
    *,
    started_at: datetime,
    prior_fail_reviews: int = 0,
) -> str:
    """Seed an open run plus ``prior_fail_reviews`` recorded fail ``review`` events."""

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
                    "{}",
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

    _sync(_insert())
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

    return _sync(_fetch())


# ---------------------------------------------------------------------------
# AC-1: the 6th review→fix cycle stops + escalates, and runs no engine
# ---------------------------------------------------------------------------


def test_sixth_cycle_refuses_without_running_the_engine(repo: Path, db_path: Path) -> None:
    """5 prior reviews → the 6th invocation trips, exits non-zero, runs no engine."""
    _seed_run(db_path, repo, started_at=datetime.now(UTC), prior_fail_reviews=5)
    calls: list[int] = []
    result = _invoke(repo, db_path, _tracking_runner(_FAIL_LINE, calls))

    assert result.exit_code == review_mod.EXIT_BREAKER_TRIPPED
    payload = json.loads(result.output)
    assert payload["reason"] == REVIEW_CYCLE_CEILING_REASON
    assert calls == [], "the engine must not run once the ceiling is reached"
    # No 6th review event recorded — only the 5 seeded fails remain.
    assert len(_review_events(db_path)) == 5


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
# AC-2: cycles 1–3 unconditional; the post-3 convergence path is surfaced
# ---------------------------------------------------------------------------


def test_unconditional_cycle_has_no_convergence_advisory(repo: Path, db_path: Path) -> None:
    """The 3rd cycle (2 prior) is unconditional — no convergence advisory."""
    _seed_run(db_path, repo, started_at=datetime.now(UTC), prior_fail_reviews=2)
    result = _invoke(repo, db_path, _tracking_runner(_FAIL_LINE, []))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["convergence_check_required"] is False


def test_post_unconditional_fail_surfaces_convergence_advisory(
    repo: Path, db_path: Path
) -> None:
    """The 4th cycle (3 prior) returns a fail flagged for convergence assessment (AC-2)."""
    _seed_run(db_path, repo, started_at=datetime.now(UTC), prior_fail_reviews=3)
    result = _invoke(repo, db_path, _tracking_runner(_FAIL_LINE, []))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["convergence_check_required"] is True


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
# AC-4: the thresholds are read from CONTEXT.md, not hardcoded
# ---------------------------------------------------------------------------


def test_context_md_tightens_the_cycle_ceiling(repo: Path, db_path: Path) -> None:
    """A CONTEXT.md ceiling of 2 trips at the 2nd cycle, proving the verb reads it."""
    (repo / "CONTEXT.md").write_text(
        "```yaml\nloop:\n  max_review_cycles: 2\n  wall_clock_budget_minutes: 90\n```\n"
    )
    _seed_run(db_path, repo, started_at=datetime.now(UTC), prior_fail_reviews=1)
    calls: list[int] = []
    result = _invoke(repo, db_path, _tracking_runner(_FAIL_LINE, calls))

    assert result.exit_code == review_mod.EXIT_BREAKER_TRIPPED
    assert json.loads(result.output)["reason"] == REVIEW_CYCLE_CEILING_REASON
    assert calls == []
