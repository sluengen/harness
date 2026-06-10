"""Tests for ``harness review`` — CAL-571.

AC-1: a ``review`` event is written with ``reviewed_sha`` == worktree HEAD at
      invocation (test asserts equality).
AC-2: pass/fail/defer verdicts are parsed from the SUBMIT line and persisted
      (test per verdict).
AC-3: missing/garbled SUBMIT line → recorded fail with the sentinel issue.
AC-4: the reviewer runs against HEAD, not base or a stale tree (recorded SHA).
AC-context-economy: the printed JSON contains only the bounded verdict fields
      (verdict, issues, reviewed_sha, run_id) and never raw codex stdout.

None of these tests spawn a real codex subprocess: every test injects a fake
runner via the ``--run-id`` override + a patched runner so the SUBMIT-line
scanner is exercised without the codex binary.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import unittest.mock as mock
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli import review as review_mod
from harness.state import store

cli_runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throw-away git repo with one commit on ``dev``."""
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


def _head_sha(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _seed_open_run(db_path: Path, repo: Path, run_id: str = "01JRUNREVIEWXXXXXXXXXXXX01") -> str:
    """Insert an ``open`` runs row whose worktree_path == repo, return run_id."""

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
                    "CAL-571",
                    "2026-06-10T00:00:00Z",
                    1234,
                ),
            )
            await conn.commit()

    _sync(_insert())
    return run_id


def _sync(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _fetch_review_events(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT run_id, event_type, data_json FROM events WHERE event_type = 'review'"
        ) as cur,
    ):
        rows = await cur.fetchall()
    out: list[dict[str, Any]] = []
    for run_id, event_type, data_json in rows:
        out.append(
            {"run_id": run_id, "event_type": event_type, "data": json.loads(data_json)}
        )
    return out


def fetch_review_events(db_path: Path) -> list[dict[str, Any]]:
    return _sync(_fetch_review_events(db_path))


def _make_runner(stdout: str) -> Any:
    """Build a fake codex runner yielding the given stdout as one stream chunk.

    The runner signature mirrors the production runner: keyword args
    (cmd, stdin, env, cwd) and an async-iterator of stdout text.
    """

    async def _runner(
        *, cmd: list[str], stdin: str, env: dict[str, str], cwd: Path | None
    ) -> AsyncIterator[str]:
        for line in stdout.splitlines(keepends=True):
            yield line

    return _runner


def _invoke(repo: Path, db_path: Path, run_id: str, runner: Any) -> Any:
    # Patch the module-level default runner so the command uses the fake.
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
                run_id,
                "--json",
            ],
        )


# ---------------------------------------------------------------------------
# AC-1 / AC-4: review event records reviewed_sha == worktree HEAD
# ---------------------------------------------------------------------------


def test_ac1_review_event_reviewed_sha_equals_head(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    runner = _make_runner('SUBMIT: {"verdict": "pass", "issues": []}\n')

    result = _invoke(repo, db_path, run_id, runner)
    assert result.exit_code == 0, result.output

    events = fetch_review_events(db_path)
    assert len(events) == 1
    assert events[0]["run_id"] == run_id
    assert events[0]["data"]["reviewed_sha"] == head


def test_ac4_reviewed_sha_tracks_head_after_new_commit(repo: Path, db_path: Path) -> None:
    """AC-4: review binds to the *current* HEAD, not a stale/base tree."""
    run_id = _seed_open_run(db_path, repo)
    # Advance HEAD with a new commit — review must record THIS sha, not the old one.
    (repo / "feature.txt").write_text("work\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "feature work")
    new_head = _head_sha(repo)

    runner = _make_runner('SUBMIT: {"verdict": "pass", "issues": []}\n')
    result = _invoke(repo, db_path, run_id, runner)
    assert result.exit_code == 0, result.output

    events = fetch_review_events(db_path)
    assert events[0]["data"]["reviewed_sha"] == new_head

    payload = json.loads(result.output)
    assert payload["reviewed_sha"] == new_head


# ---------------------------------------------------------------------------
# AC-2: pass / fail / defer verdicts parsed from SUBMIT line and persisted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verdict", ["pass", "fail", "defer"])
def test_ac2_verdict_parsed_and_persisted(
    repo: Path, db_path: Path, verdict: str
) -> None:
    run_id = _seed_open_run(db_path, repo)
    issues = [] if verdict == "pass" else ["something is wrong"]
    runner = _make_runner(
        f'SUBMIT: {{"verdict": "{verdict}", "issues": {json.dumps(issues)}}}\n'
    )

    result = _invoke(repo, db_path, run_id, runner)
    assert result.exit_code == 0, result.output

    events = fetch_review_events(db_path)
    assert len(events) == 1
    assert events[0]["data"]["verdict"] == verdict
    assert events[0]["data"]["issues"] == issues

    payload = json.loads(result.output)
    assert payload["verdict"] == verdict


def test_ac2_fail_with_issues_list(repo: Path, db_path: Path) -> None:
    """AC-2: findings → fail event carrying the issues list."""
    run_id = _seed_open_run(db_path, repo)
    runner = _make_runner(
        'SUBMIT: {"verdict": "fail", "issues": ["missing test", "bad name"]}\n'
    )

    result = _invoke(repo, db_path, run_id, runner)
    assert result.exit_code == 0, result.output

    events = fetch_review_events(db_path)
    assert events[0]["data"]["verdict"] == "fail"
    assert events[0]["data"]["issues"] == ["missing test", "bad name"]


# ---------------------------------------------------------------------------
# AC-3: missing / garbled SUBMIT line → recorded fail with sentinel issue
# ---------------------------------------------------------------------------


SENTINEL = "reviewer emitted no valid SUBMIT line"


def test_ac3_no_submit_line_records_fail_sentinel(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    runner = _make_runner("I looked at the code and it seems fine to me.\n")

    result = _invoke(repo, db_path, run_id, runner)
    assert result.exit_code == 0, result.output

    events = fetch_review_events(db_path)
    assert len(events) == 1
    assert events[0]["data"]["verdict"] == "fail"
    assert SENTINEL in events[0]["data"]["issues"]


def test_ac3_garbled_submit_json_records_fail_sentinel(
    repo: Path, db_path: Path
) -> None:
    run_id = _seed_open_run(db_path, repo)
    runner = _make_runner("SUBMIT: {this is not valid json\n")

    result = _invoke(repo, db_path, run_id, runner)
    assert result.exit_code == 0, result.output

    events = fetch_review_events(db_path)
    assert events[0]["data"]["verdict"] == "fail"
    assert SENTINEL in events[0]["data"]["issues"]


def test_ac3_unknown_verdict_records_fail_sentinel(repo: Path, db_path: Path) -> None:
    """A SUBMIT line whose verdict is not pass/fail/defer is treated as garbled."""
    run_id = _seed_open_run(db_path, repo)
    runner = _make_runner('SUBMIT: {"verdict": "maybe", "issues": []}\n')

    result = _invoke(repo, db_path, run_id, runner)
    assert result.exit_code == 0, result.output

    events = fetch_review_events(db_path)
    assert events[0]["data"]["verdict"] == "fail"
    assert SENTINEL in events[0]["data"]["issues"]


# ---------------------------------------------------------------------------
# AC-context-economy: printed JSON contains only bounded verdict fields,
# never raw codex stdout / reasoning.
# ---------------------------------------------------------------------------


def test_context_economy_only_bounded_fields_no_raw_stdout(
    repo: Path, db_path: Path
) -> None:
    run_id = _seed_open_run(db_path, repo)
    secret_reasoning = "INTERNAL_CHAIN_OF_THOUGHT_THAT_MUST_NOT_LEAK"
    stdout = (
        f"{secret_reasoning}\n"
        "Let me think about this in great detail ... lots of tokens ...\n"
        'SUBMIT: {"verdict": "fail", "issues": ["one issue"]}\n'
        "more trailing reasoning after submit\n"
    )
    runner = _make_runner(stdout)

    result = _invoke(repo, db_path, run_id, runner)
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    # Only the bounded verdict fields are present.
    assert set(payload.keys()) <= {"verdict", "issues", "reviewed_sha", "run_id"}
    assert payload["verdict"] == "fail"
    assert payload["issues"] == ["one issue"]

    # Raw codex stdout / reasoning never leaks into the printed JSON.
    assert secret_reasoning not in result.output
    assert "trailing reasoning" not in result.output

    # …nor into the persisted event payload.
    events = fetch_review_events(db_path)
    assert secret_reasoning not in json.dumps(events[0]["data"])


# ---------------------------------------------------------------------------
# Resolution / invocation-error behaviour
# ---------------------------------------------------------------------------


def test_no_open_run_for_repo_is_invocation_error(repo: Path, db_path: Path) -> None:
    """No matching open run → exit 2, no review event written."""
    _sync(store.init_db(db_path))  # empty DB, no runs
    runner = _make_runner('SUBMIT: {"verdict": "pass", "issues": []}\n')

    result = _invoke(repo, db_path, "01JNONEXISTENTRUNIDXXXXXX0", runner)
    assert result.exit_code == 2, result.output
    assert fetch_review_events(db_path) == []
