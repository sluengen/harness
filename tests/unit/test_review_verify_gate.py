"""CAL-1082 — ``review`` requires recorded verify-gate evidence.

The verb loop's close gate checked three things (a run exists, the worktree is
clean, a ``verdict='pass'`` is bound to HEAD) — none of them evidence that a test
ever *ran*. So a ``pass`` from a reviewer that only read the diff was
byte-identical in the ledger to one backed by a green gate, against this repo's
own iron law ("no completion claim without fresh evidence").

The harness stays a **scaffold**: the gate runs where the toolchain lives (the
orchestrating session, host-side), and the verb *enforces and records* the
evidence rather than executing the gate itself. An earlier build had ``review``
run the gate in-container and proved the catch-22 that motivates this shape — the
image cannot carry every target repo's toolchain (``harness:dev`` is built
``--no-dev``, so not even this repo's own gate runs there; an Xcode target never
runs in a Linux container).

These tests pin the evidence contract:

* :mod:`harness.gate` reads ``CONTEXT.md`` → ``verify:`` for the record, and
  bounds a log tail (AC-1/AC-2);
* ``review`` refuses exit 5 ``no_gate_evidence`` when a gate is configured and no
  evidence is supplied, before any engine (AC-1);
* ``--gate-exit`` non-zero refuses exit 5 ``gate_failed`` with the bounded tail
  and records no event (AC-2);
* green evidence → the engine runs and the event carries the evidence bound to
  ``reviewed_sha`` (AC-3);
* an unconfigured ``verify:`` records ``not_configured`` and proceeds (AC-4);
* the verb never *executes* the gate command, so no in-container toolchain is
  required (AC-6);
* the spend breakers still refuse *before* the gate is considered.

``close``'s side of the contract (AC-5) lives in ``test_cli_close.py``.

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
    read_gate_log_tail,
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


def _write_log(repo: Path, text: str) -> Path:
    log = repo / "gate.log"
    log.write_text(text)
    return log


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


def _invoke(repo: Path, db_path: Path, runner: Any, *gate_args: str) -> Any:
    with mock.patch.object(review_mod, "_default_runner", runner):
        return cli_runner.invoke(
            app,
            [
                "review",
                "--repo",
                str(repo),
                "--db",
                str(db_path),
                "--run-id",
                _RUN_ID,
                "--json",
                *gate_args,
            ],
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
# load_gate_command reads CONTEXT.md → verify: (for the record, not to run it)
# ---------------------------------------------------------------------------


def test_load_gate_command_reads_the_verify_key(tmp_path: Path) -> None:
    _write_context(tmp_path, "bash scripts/verify.sh")
    assert load_gate_command(tmp_path) == "bash scripts/verify.sh"


def test_load_gate_command_is_none_without_context_md(tmp_path: Path) -> None:
    assert load_gate_command(tmp_path) is None


def test_load_gate_command_is_none_when_verify_key_absent(tmp_path: Path) -> None:
    _write_context(tmp_path, None)
    assert load_gate_command(tmp_path) is None


def test_load_gate_command_reads_this_repos_own_context() -> None:
    """The real CONTEXT.md parses — the regex is pinned against the live file."""
    assert load_gate_command(Path(__file__).resolve().parents[2]) == "bash scripts/verify.sh"


# ---------------------------------------------------------------------------
# read_gate_log_tail — the tail, bounded (the diagnosis is at the end)
# ---------------------------------------------------------------------------


def test_read_gate_log_tail_returns_the_tail_not_the_head(tmp_path: Path) -> None:
    log = tmp_path / "gate.log"
    log.write_text("HEAD-MARKER\n" + ("x" * GATE_OUTPUT_TAIL_LIMIT) + "\nTAIL-MARKER")
    tail = read_gate_log_tail(log)
    assert tail.endswith("TAIL-MARKER")
    assert "HEAD-MARKER" not in tail
    assert len(tail) <= GATE_OUTPUT_TAIL_LIMIT


def test_read_gate_log_tail_is_empty_for_a_missing_log(tmp_path: Path) -> None:
    """An unreadable log degrades to no tail — evidence stands on the exit code."""
    assert read_gate_log_tail(tmp_path / "nope.log") == ""


def test_read_gate_log_tail_is_empty_when_no_log_is_given() -> None:
    assert read_gate_log_tail(None) == ""


# ---------------------------------------------------------------------------
# AC-1: verify: configured + no evidence → exit 5 no_gate_evidence, no engine
# ---------------------------------------------------------------------------


def test_missing_evidence_refuses_before_the_engine(repo: Path, db_path: Path) -> None:
    _write_context(repo, "bash scripts/verify.sh")
    _seed_run(db_path, repo)
    calls: list[int] = []

    result = _invoke(repo, db_path, _tracking_runner(_PASS_LINE, calls))

    assert result.exit_code == review_mod.EXIT_GATE_FAILED
    payload = json.loads(result.stdout)
    assert payload["reason"] == review_mod.NO_GATE_EVIDENCE_REASON
    assert calls == [], "the engine must not run without gate evidence"
    assert _review_events(db_path) == [], "no event may be recorded on a refusal"


# ---------------------------------------------------------------------------
# AC-2: --gate-exit non-zero → exit 5 gate_failed + bounded tail, no event
# ---------------------------------------------------------------------------


def test_red_evidence_refuses_with_the_bounded_tail(repo: Path, db_path: Path) -> None:
    _write_context(repo, "bash scripts/verify.sh")
    _seed_run(db_path, repo)
    log = _write_log(repo, "HEAD-NOISE\n" + "y" * GATE_OUTPUT_TAIL_LIMIT + "\nFAILED test_x")
    calls: list[int] = []

    result = _invoke(
        repo, db_path, _tracking_runner(_PASS_LINE, calls),
        "--gate-exit", "1", "--gate-log", str(log),
    )

    assert result.exit_code == review_mod.EXIT_GATE_FAILED
    payload = json.loads(result.stdout)
    assert payload["reason"] == review_mod.GATE_FAILED_REASON
    tail = payload["gate_output_tail"]
    assert tail.endswith("FAILED test_x")
    assert "HEAD-NOISE" not in tail
    assert len(tail) <= GATE_OUTPUT_TAIL_LIMIT
    assert calls == [], "a red gate must not spend tokens on a review"
    assert _review_events(db_path) == []


# ---------------------------------------------------------------------------
# AC-3: green evidence → engine runs, evidence on the event bound to the SHA
# ---------------------------------------------------------------------------


def test_green_evidence_records_the_evidence_on_the_event(repo: Path, db_path: Path) -> None:
    _write_context(repo, "bash scripts/verify.sh")
    _seed_run(db_path, repo)
    log = _write_log(repo, "42 passed in 1.2s")
    calls: list[int] = []

    result = _invoke(
        repo, db_path, _tracking_runner(_PASS_LINE, calls),
        "--gate-exit", "0", "--gate-log", str(log),
    )

    assert result.exit_code == 0, result.stdout
    assert calls == [1], "green evidence must let the engine run"
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (event,) = _review_events(db_path)
    assert event["gate_ran"] is True
    assert event["gate_command"] == "bash scripts/verify.sh"
    assert event["gate_exit_code"] == 0
    assert event["gate_output_tail"] == "42 passed in 1.2s"
    assert event["reviewed_sha"] == head, "evidence is bound to the reviewed SHA"


# ---------------------------------------------------------------------------
# AC-4: no verify: configured → not_configured recorded; review proceeds
# ---------------------------------------------------------------------------


def test_unconfigured_gate_records_the_absence_and_runs_the_engine(
    repo: Path, db_path: Path
) -> None:
    _write_context(repo, None)
    _seed_run(db_path, repo)
    calls: list[int] = []

    result = _invoke(repo, db_path, _tracking_runner(_PASS_LINE, calls))

    assert result.exit_code == 0, result.stdout
    assert calls == [1], "the harness cannot gate what a repo does not define"
    (event,) = _review_events(db_path)
    assert event["gate_ran"] is False
    assert event["gate_reason"] == GATE_NOT_CONFIGURED_REASON
    assert event.get("gate_command") is None


# ---------------------------------------------------------------------------
# AC-6: the verb never EXECUTES the gate — no in-container toolchain needed
# ---------------------------------------------------------------------------


def test_the_verb_never_executes_the_gate_command(repo: Path, db_path: Path) -> None:
    """The scaffold decision, pinned behaviourally.

    ``verify:`` here would create a sentinel and exit non-zero *if it ran*. The
    verb records the command string as evidence metadata and never invokes it, so
    the sentinel never appears and the supplied green evidence stands. This is
    what dissolves the ``--no-dev`` image catch-22: the gate runs host-side,
    where the toolchain lives.
    """
    sentinel = repo / "gate-executed.sentinel"
    _write_context(repo, f"touch {sentinel} && exit 7")
    _seed_run(db_path, repo)
    calls: list[int] = []

    result = _invoke(
        repo, db_path, _tracking_runner(_PASS_LINE, calls), "--gate-exit", "0"
    )

    assert result.exit_code == 0, result.stdout
    assert not sentinel.exists(), "the verb must not execute the repo's gate command"
    assert calls == [1]


def test_gate_module_spawns_no_subprocess() -> None:
    """No execution path survives in the gate module (the scaffold decision)."""
    source = (Path(review_mod.__file__).parent.parent / "gate.py").read_text()
    assert "subprocess" not in source
    assert not hasattr(__import__("harness.gate", fromlist=["x"]), "run_gate")


# ---------------------------------------------------------------------------
# The spend breakers still refuse before the gate is considered
# ---------------------------------------------------------------------------


def test_tripped_breaker_refuses_before_the_gate(repo: Path, db_path: Path) -> None:
    """A bounded-out run is refused without demanding gate evidence first."""
    _write_context(repo, "bash scripts/verify.sh")
    _seed_run(db_path, repo)
    _seed_reviews(db_path, 5)
    calls: list[int] = []

    result = _invoke(repo, db_path, _tracking_runner(_PASS_LINE, calls))

    assert result.exit_code == review_mod.EXIT_BREAKER_TRIPPED
    payload = json.loads(result.stdout)
    assert payload["reason"] == REVIEW_CYCLE_CEILING_REASON
    assert calls == []


def test_wall_clock_trip_also_precedes_the_gate(repo: Path, db_path: Path) -> None:
    _write_context(repo, "bash scripts/verify.sh")
    _seed_run(db_path, repo, started_at=datetime.now(UTC) - timedelta(minutes=120))
    calls: list[int] = []

    result = _invoke(repo, db_path, _tracking_runner(_PASS_LINE, calls))

    assert result.exit_code == review_mod.EXIT_BREAKER_TRIPPED
    assert calls == []


# ---------------------------------------------------------------------------
# The payload contract the close backstop reads
# ---------------------------------------------------------------------------


def test_gate_ran_path_is_derived_from_the_model() -> None:
    assert REVIEW_GATE_RAN_PATH == "$.gate_ran"
    assert "gate_ran" in ReviewEventData.model_fields


def test_gate_ran_is_always_present_on_a_new_event() -> None:
    """``gate_ran`` is non-optional, so it survives ``exclude_none=True``."""
    data = ReviewEventData(
        run_id=_RUN_ID,
        verdict="pass",
        issues=[],
        reviewed_sha="abc",
        engine="claude",
        convergence_check_required=False,
        created_at="2026-07-16T00:00:00Z",
        gate_ran=False,
    )
    assert "gate_ran" in json.loads(data.model_dump_json(exclude_none=True))
