"""CAL-1082 — ``review`` runs the repo's verify gate and records the evidence.

The verb loop's close gate checked three things (a run exists, the worktree is
clean, a ``verdict='pass'`` is bound to HEAD) — none of them evidence that a test
ever *executed*. So a ``pass`` from a reviewer that only read the diff was
byte-identical in the ledger to one backed by a green gate, against this repo's
own iron law ("no completion claim without fresh evidence").

These tests pin the fix end to end:

* :mod:`harness.gate` reads ``CONTEXT.md`` → ``verify:`` and runs it (AC-1);
* ``review`` runs that gate **before** any engine, records the evidence on the
  ``review`` event (AC-2), refuses a red gate without spawning the engine (AC-3)
  and carries the bounded output tail on the refusal (AC-4), and records the
  absence honestly when no gate is configured (AC-5);
* ``close`` refuses a pass carrying no gate evidence (AC-6);
* the spend breakers still refuse *before* the gate spends any time (AC-7).

They inject a fake engine runner and seed the ledger directly, exactly like
``test_review_breakers.py``.
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
from harness.events.payloads import REVIEW_GATE_RAN_PATH, ReviewEventData
from harness.gate import (
    GATE_NOT_CONFIGURED_REASON,
    GATE_OUTPUT_TAIL_LIMIT,
    load_gate_command,
    run_gate,
)
from harness.loop_budget import REVIEW_CYCLE_CEILING_REASON
from harness.state import store

cli_runner = CliRunner()

_PASS_LINE = 'SUBMIT: {"verdict": "pass", "issues": []}\n'
_RUN_ID = "01JRUNGATEXXXXXXXXXXXXXXX01"


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


def _write_context(repo: Path, verify: str | None) -> None:
    """Write a CONTEXT.md whose ``verify:`` is ``verify`` (omitted when None)."""
    body = "```yaml\nrepo:\n  name: t\n"
    if verify is not None:
        body += f'verify: "{verify}"\n'
    body += "```\n"
    (repo / "CONTEXT.md").write_text(body)


def _seed_run(db_path: Path, repo: Path, *, started_at: datetime | None = None) -> str:
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
                    "CAL-1082",
                    (started_at or datetime.now(UTC)).isoformat(),
                    1234,
                ),
            )
            await conn.commit()

    _sync(_insert())
    return _RUN_ID


def _seed_reviews(db_path: Path, count: int) -> None:
    """Append ``count`` prior fail ``review`` events (to drive the cycle ceiling)."""

    async def _insert() -> None:
        async with store.connect(db_path) as conn:
            for _ in range(count):
                await conn.execute(
                    "INSERT INTO events (run_id, event_type, timestamp, data_json) "
                    "VALUES (?, 'review', ?, ?)",
                    (
                        _RUN_ID,
                        "2026-07-16T00:00:00Z",
                        json.dumps({"verdict": "fail", "reviewed_sha": "deadbeef"}),
                    ),
                )
            await conn.commit()

    _sync(_insert())


def _tracking_runner(stdout: str, calls: list[int]) -> Any:
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


def _invoke(repo: Path, db_path: Path, runner: Any) -> Any:
    with mock.patch.object(review_mod, "_default_runner", runner):
        return cli_runner.invoke(
            app,
            ["review", "--repo", str(repo), "--db", str(db_path), "--run-id", _RUN_ID, "--json"],
        )


def _review_events(db_path: Path) -> list[dict[str, Any]]:
    async def _fetch() -> list[dict[str, Any]]:
        async with (
            store.connect(db_path) as conn,
            conn.execute("SELECT data_json FROM events WHERE event_type = 'review'") as cur,
        ):
            rows = await cur.fetchall()
        return [json.loads(r[0]) for r in rows]

    return _sync(_fetch())


# ---------------------------------------------------------------------------
# AC-1: load_gate_command reads CONTEXT.md → verify:
# ---------------------------------------------------------------------------


def test_load_gate_command_reads_the_verify_key(tmp_path: Path) -> None:
    _write_context(tmp_path, "bash scripts/verify.sh")
    assert load_gate_command(tmp_path) == "bash scripts/verify.sh"


def test_load_gate_command_is_none_without_context_md(tmp_path: Path) -> None:
    """No CONTEXT.md at all → nothing to gate on."""
    assert load_gate_command(tmp_path) is None


def test_load_gate_command_is_none_when_verify_key_absent(tmp_path: Path) -> None:
    """A CONTEXT.md that configures no ``verify:`` → nothing to gate on."""
    _write_context(tmp_path, None)
    assert load_gate_command(tmp_path) is None


def test_load_gate_command_reads_this_repos_own_context() -> None:
    """The real CONTEXT.md at the repo root resolves — the parser is not a
    tmp-path-only fiction (this repo's canonical gate is scripts/verify.sh)."""
    repo_root = Path(__file__).resolve().parents[2]
    assert load_gate_command(repo_root) == "bash scripts/verify.sh"


def test_run_gate_reports_exit_code_and_runs_in_the_worktree(tmp_path: Path) -> None:
    """The gate runs with cwd=worktree, so a repo-relative command resolves."""
    (tmp_path / "ok.sh").write_text("exit 0\n")
    result = run_gate(tmp_path, "bash ok.sh", timeout_s=30)
    assert result.ran is True
    assert result.exit_code == 0


def test_run_gate_captures_a_failure_exit_code_and_output(tmp_path: Path) -> None:
    (tmp_path / "bad.sh").write_text("echo 'boom happened'\nexit 3\n")
    result = run_gate(tmp_path, "bash bad.sh", timeout_s=30)
    assert result.exit_code == 3
    assert "boom happened" in result.output_tail


# ---------------------------------------------------------------------------
# AC-2: a green gate → engine runs, evidence lands on the ledger event
# ---------------------------------------------------------------------------


def test_green_gate_records_evidence_on_the_review_event(repo: Path, db_path: Path) -> None:
    """The persisted event — not the printed output — carries the gate evidence."""
    _write_context(repo, "bash ok.sh")
    (repo / "ok.sh").write_text("exit 0\n")
    _seed_run(db_path, repo)
    calls: list[int] = []

    result = _invoke(repo, db_path, _tracking_runner(_PASS_LINE, calls))

    assert result.exit_code == 0, result.output
    assert calls == [1], "a green gate must let the engine run"
    events = _review_events(db_path)
    assert len(events) == 1
    assert events[0]["gate_ran"] is True
    assert events[0]["gate_exit_code"] == 0
    assert events[0]["gate_command"] == "bash ok.sh"


# ---------------------------------------------------------------------------
# AC-3: a red gate → exit 5, no event, no engine
# ---------------------------------------------------------------------------


def test_red_gate_refuses_before_the_engine(repo: Path, db_path: Path) -> None:
    _write_context(repo, "bash bad.sh")
    (repo / "bad.sh").write_text("echo 'tests failed'\nexit 1\n")
    _seed_run(db_path, repo)
    calls: list[int] = []

    result = _invoke(repo, db_path, _tracking_runner(_PASS_LINE, calls))

    assert result.exit_code == review_mod.EXIT_GATE_FAILED
    payload = json.loads(result.output)
    assert payload["reason"] == review_mod.GATE_FAILED_REASON
    assert calls == [], "the engine must not be spawned on a red gate"
    assert _review_events(db_path) == [], "a red gate records no review event"


# ---------------------------------------------------------------------------
# AC-4: the refusal carries the gate's output tail, bounded to <= 2 KB
# ---------------------------------------------------------------------------


def test_red_gate_refusal_carries_a_bounded_output_tail(repo: Path, db_path: Path) -> None:
    """A gate emitting > 2 KB is carried as its *tail*, bounded to the limit —
    the agent can act on the failure without re-running it, and the verb's
    context economy still holds."""
    _write_context(repo, "bash noisy.sh")
    # 8000 chars of noise, then the line that actually explains the failure.
    (repo / "noisy.sh").write_text(
        "python3 -c \"print('x' * 8000)\"\necho 'FINAL_FAILURE_LINE'\nexit 1\n"
    )
    _seed_run(db_path, repo)

    result = _invoke(repo, db_path, _tracking_runner(_PASS_LINE, []))

    assert result.exit_code == review_mod.EXIT_GATE_FAILED
    payload = json.loads(result.output)
    tail = payload["gate_output_tail"]
    assert len(tail) <= GATE_OUTPUT_TAIL_LIMIT, f"tail is {len(tail)} chars, over the limit"
    assert GATE_OUTPUT_TAIL_LIMIT == 2048
    # It is the *tail*: the last, most diagnostic output survives the bounding.
    assert "FINAL_FAILURE_LINE" in tail


# ---------------------------------------------------------------------------
# AC-5: no verify: configured → the absence is recorded honestly, close allows
# ---------------------------------------------------------------------------


def test_unconfigured_gate_records_the_absence_and_runs_the_engine(
    repo: Path, db_path: Path
) -> None:
    """The harness cannot gate what a repo does not define — it says so plainly
    rather than implying a gate ran."""
    _write_context(repo, None)
    _seed_run(db_path, repo)
    calls: list[int] = []

    result = _invoke(repo, db_path, _tracking_runner(_PASS_LINE, calls))

    assert result.exit_code == 0, result.output
    assert calls == [1]
    event = _review_events(db_path)[0]
    assert event["gate_ran"] is False
    assert event["gate_reason"] == GATE_NOT_CONFIGURED_REASON
    assert "gate_exit_code" not in event, "no exit code when the gate never ran"


# ---------------------------------------------------------------------------
# AC-7: a tripped spend breaker refuses BEFORE the gate spends any time
# ---------------------------------------------------------------------------


def test_tripped_breaker_refuses_before_the_gate_runs(repo: Path, db_path: Path) -> None:
    """A run bounded out must not spend minutes on a gate before being refused.

    The gate command writes a marker file; its absence proves the gate never ran.
    """
    marker = repo / "gate-ran.marker"
    _write_context(repo, f"touch {marker.name}")
    _seed_run(db_path, repo)
    _seed_reviews(db_path, 5)  # the 6th review trips the cycle ceiling

    result = _invoke(repo, db_path, _tracking_runner(_PASS_LINE, []))

    assert result.exit_code == review_mod.EXIT_BREAKER_TRIPPED
    assert json.loads(result.output)["reason"] == REVIEW_CYCLE_CEILING_REASON
    assert not marker.exists(), "the gate must not run once a breaker has tripped"


def test_wall_clock_trip_also_precedes_the_gate(repo: Path, db_path: Path) -> None:
    marker = repo / "gate-ran.marker"
    _write_context(repo, f"touch {marker.name}")
    _seed_run(db_path, repo, started_at=datetime.now(UTC) - timedelta(minutes=91))

    result = _invoke(repo, db_path, _tracking_runner(_PASS_LINE, []))

    assert result.exit_code == review_mod.EXIT_BREAKER_TRIPPED
    assert not marker.exists()


# ---------------------------------------------------------------------------
# AC-8: the reader constant is derived from the model (the rename guard)
# ---------------------------------------------------------------------------


def test_gate_ran_path_is_derived_from_the_model() -> None:
    """``REVIEW_GATE_RAN_PATH`` is derived via ``_field_path``, so renaming the
    field raises at import rather than silently breaking the close backstop."""
    assert REVIEW_GATE_RAN_PATH == "$.gate_ran"
    assert "gate_ran" in ReviewEventData.model_fields


def test_gate_ran_is_always_present_on_a_new_event() -> None:
    """``gate_ran`` is a non-optional bool, so ``exclude_none=True`` never drops
    it — a new event always states its gate evidence, either way."""
    dumped = ReviewEventData(
        run_id="R1",
        reviewed_sha="abc",
        verdict="pass",
        issues=[],
        engine="claude",
        convergence_check_required=False,
        created_at="2026-07-16T00:00:00Z",
        gate_ran=False,
        gate_reason=GATE_NOT_CONFIGURED_REASON,
    ).model_dump(exclude_none=True)
    assert dumped["gate_ran"] is False
