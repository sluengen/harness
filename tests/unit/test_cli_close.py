"""Tests for ``harness close <TICKET>`` — CAL-572.

The close verb is the enforcement linchpin: closing a ticket must be impossible
unless a run was started AND the current tree passed review (a ``review`` event
with ``verdict='pass'`` whose ``reviewed_sha`` equals the worktree HEAD).

AC-1: close succeeds only when a pass event's ``reviewed_sha == HEAD``;
      merge/push/Done/closed all occur.
AC-2: pass-then-edit (HEAD advanced past the reviewed SHA) → refusal
      ``stale_review``, no merge, ticket not Done.
AC-3: no passing review → refusal ``no_passing_review``, no side effects.
AC-4: no open run → refusal ``no_run``.
AC-5: on success the run row is ``status='closed'`` and the ticket is Done.
AC-context-economy: ``close`` returns a compact result (merge/close status, or
      a structured refusal ``reason``); git merge/push output stays inside the
      verb and never enters the printed JSON.

The Linear Done transition and the git merge/push are faked/injected so tests
never hit the network or a real remote — mirroring how ``test_cli_start.py``
patches the Linear client and ``test_cli_review.py`` injects the runner.
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
from harness.events.emitter import EventEmitter
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


def _sync(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


RUN_ID = "01JRUNCLOSEXXXXXXXXXXXXX01"


def _seed_open_run(
    db_path: Path,
    repo: Path,
    run_id: str = RUN_ID,
    ticket: str = "CAL-572",
) -> str:
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
                    ticket,
                    "2026-06-10T00:00:00Z",
                    1234,
                ),
            )
            await conn.commit()

    _sync(_insert())
    return run_id


def _emit_review(
    db_path: Path,
    run_id: str,
    reviewed_sha: str,
    verdict: str,
    issues: list[str] | None = None,
) -> None:
    """Append a ``review`` event mirroring what ``harness review`` records."""

    async def _emit() -> None:
        emitter = EventEmitter(db_path)
        await emitter.emit(
            run_id=run_id,
            event_type="review",
            data={
                "run_id": run_id,
                "reviewed_sha": reviewed_sha,
                "verdict": verdict,
                "issues": issues or [],
                "created_at": "2026-06-10T00:00:00Z",
            },
        )

    _sync(_emit())


async def _fetch_run_status(db_path: Path, run_id: str) -> str | None:
    async with (
        store.connect(db_path) as conn,
        conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)) as cur,
    ):
        row = await cur.fetchone()
    return None if row is None else str(row[0])


def fetch_run_status(db_path: Path, run_id: str) -> str | None:
    return _sync(_fetch_run_status(db_path, run_id))


def _make_linear_stub(raise_on_transition: Exception | None = None) -> MagicMock:
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
    linear_stub: MagicMock,
    merge_push: MagicMock | None = None,
) -> Any:
    """Invoke ``harness close`` with the Linear client and git side effects faked."""
    merge = merge_push if merge_push is not None else MagicMock(return_value=None)
    with (
        patch("harness.cli.close.LinearClient", return_value=linear_stub),
        patch("harness.cli.close.linear_api_key", return_value="test-key"),
        patch.object(close_mod, "_merge_and_push", merge),
    ):
        result = cli_runner.invoke(
            app,
            [
                "close",
                "CAL-572",
                "--repo",
                str(repo),
                "--db",
                str(db_path),
                "--run-id",
                run_id,
                "--json",
            ],
        )
    return result, merge


# ---------------------------------------------------------------------------
# AC-1 / AC-5: pass for HEAD → merge/push/Done/closed all occur
# ---------------------------------------------------------------------------


def test_ac1_close_succeeds_when_pass_for_head(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")
    stub = _make_linear_stub()

    result, merge = _invoke(repo, db_path, run_id, stub)
    assert result.exit_code == 0, result.output

    # Merge/push happened, ticket transitioned to Done.
    merge.assert_called_once()
    stub.transition_to_done.assert_called_once_with("CAL-572")

    payload = json.loads(result.output)
    assert payload["run_id"] == run_id
    assert payload["merged"] is True
    assert payload["ticket_done"] is True
    assert payload["status"] == "closed"


def test_ac5_run_closed_and_ticket_done_on_success(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")
    stub = _make_linear_stub()

    result, _merge = _invoke(repo, db_path, run_id, stub)
    assert result.exit_code == 0, result.output

    # Run row flipped to closed.
    assert fetch_run_status(db_path, run_id) == "closed"
    # Ticket Done transition fired exactly once.
    stub.transition_to_done.assert_called_once_with("CAL-572")


# ---------------------------------------------------------------------------
# AC-2: pass-then-edit (HEAD advanced) → refusal stale_review, no side effects
# ---------------------------------------------------------------------------


def test_ac2_stale_review_when_head_advanced(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    reviewed = _head_sha(repo)
    _emit_review(db_path, run_id, reviewed, "pass")

    # Advance HEAD past the reviewed SHA.
    (repo / "feature.txt").write_text("more work\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "more work")
    assert _head_sha(repo) != reviewed

    stub = _make_linear_stub()
    result, merge = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["reason"] == "stale_review"

    # No merge, no Done, run still open.
    merge.assert_not_called()
    stub.transition_to_done.assert_not_called()
    assert fetch_run_status(db_path, run_id) == "open"


# ---------------------------------------------------------------------------
# AC-3: no passing review → refusal no_passing_review, no side effects
# ---------------------------------------------------------------------------


def test_ac3_no_passing_review_only_fail(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "fail", issues=["bug"])
    stub = _make_linear_stub()

    result, merge = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["reason"] == "no_passing_review"

    merge.assert_not_called()
    stub.transition_to_done.assert_not_called()
    assert fetch_run_status(db_path, run_id) == "open"


def test_ac3_no_review_at_all(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    stub = _make_linear_stub()

    result, merge = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["reason"] == "no_passing_review"

    merge.assert_not_called()
    stub.transition_to_done.assert_not_called()
    assert fetch_run_status(db_path, run_id) == "open"


# ---------------------------------------------------------------------------
# AC-4: no open run → refusal no_run
# ---------------------------------------------------------------------------


def test_ac4_no_open_run(repo: Path, db_path: Path) -> None:
    _sync(store.init_db(db_path))  # empty DB, no runs
    stub = _make_linear_stub()

    result, merge = _invoke(repo, db_path, "01JNONEXISTENTRUNIDXXXXXX0", stub)

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["reason"] == "no_run"

    merge.assert_not_called()
    stub.transition_to_done.assert_not_called()


# ---------------------------------------------------------------------------
# AC-context-economy: compact result, no raw git output in the printed JSON
# ---------------------------------------------------------------------------


def test_context_economy_no_git_output_in_json(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")
    stub = _make_linear_stub()

    # The fake merge/push returns verbose git output — it must stay inside the
    # verb and never leak into the printed JSON.
    noisy = "Merge made by the 'ort' strategy.\n 1 file changed\nTo origin\n   abc..def"
    merge = MagicMock(return_value=noisy)
    result, _merge = _invoke(repo, db_path, run_id, stub, merge_push=merge)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    # Compact result: only bounded status fields, no raw git chatter.
    assert set(payload.keys()) <= {
        "run_id",
        "ticket",
        "reviewed_sha",
        "merged",
        "ticket_done",
        "status",
    }
    assert noisy not in result.output
    assert "Merge made by" not in result.output


# ---------------------------------------------------------------------------
# close command registered in CLI help
# ---------------------------------------------------------------------------


def test_close_command_registered() -> None:
    result = cli_runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "close" in result.output


# ---------------------------------------------------------------------------
# LinearClient.transition_to_done — targets the completed-type state
# ---------------------------------------------------------------------------


async def test_linear_transition_to_done_prefers_named_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """transition_to_done targets a state literally named 'Done' over other completed states."""
    from harness.linear import LinearClient

    calls: list[dict[str, Any]] = []

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        calls.append({"query": query, "variables": variables})
        if "states" in query:
            return {
                "data": {
                    "issue": {
                        "id": "issue-id",
                        "team": {
                            "states": {
                                "nodes": [
                                    {"id": "state-cancel", "name": "Canceled", "type": "canceled"},
                                    {"id": "state-shipped", "name": "Shipped", "type": "completed"},
                                    {"id": "state-done", "name": "Done", "type": "completed"},
                                ]
                            }
                        },
                    }
                }
            }
        return {"data": {"issueUpdate": {"success": True}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    await client.transition_to_done("CAL-572")

    mutation_calls = [c for c in calls if "issueUpdate" in c["query"]]
    assert len(mutation_calls) == 1
    # The named "Done" state (not the first completed-type "Shipped") was chosen.
    assert mutation_calls[0]["variables"]["stateId"] == "state-done"


async def test_linear_transition_to_done_falls_back_to_first_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no state named 'Done', the first completed-type state is used."""
    from harness.linear import LinearClient

    calls: list[dict[str, Any]] = []

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        calls.append({"query": query, "variables": variables})
        if "states" in query:
            return {
                "data": {
                    "issue": {
                        "id": "issue-id",
                        "team": {
                            "states": {
                                "nodes": [
                                    {"id": "state-shipped", "name": "Shipped", "type": "completed"},
                                ]
                            }
                        },
                    }
                }
            }
        return {"data": {"issueUpdate": {"success": True}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    await client.transition_to_done("CAL-572")

    mutation_calls = [c for c in calls if "issueUpdate" in c["query"]]
    assert mutation_calls[0]["variables"]["stateId"] == "state-shipped"


async def test_linear_transition_to_done_raises_when_no_completed_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """transition_to_done raises LinearRequestError when no completed state exists."""
    from harness.linear import LinearClient, LinearRequestError

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {
            "data": {
                "issue": {
                    "id": "issue-id",
                    "team": {
                        "states": {
                            "nodes": [
                                {"id": "state-ip", "name": "In Progress", "type": "started"}
                            ]
                        }
                    },
                }
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")

    with pytest.raises(LinearRequestError, match="no 'completed' workflow state"):
        await client.transition_to_done("CAL-572")
