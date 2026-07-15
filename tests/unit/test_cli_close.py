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
from harness.linear import LinearConfigError
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


@pytest.fixture(autouse=True)
def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Permit the tmp test tree through the ``HARNESS_WORKSPACE_ROOTS`` gate (CAL-584).

    These verb tests predate the allowlist and point ``--repo`` at paths under
    ``tmp_path``; without a configured root the gate fails closed.
    """
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throw-away git repo with one commit on ``dev``.

    ``.harness/`` is gitignored exactly as in the real repo (.gitignore:24) so
    the ledger DB the verbs create under it never registers as a dirty worktree
    — the ``dirty_worktree`` gate (CAL-586) keys off ``git status --porcelain``,
    which excludes ignored paths.
    """
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
    gate: dict[str, Any] | None = None,
) -> None:
    """Append a ``review`` event mirroring what ``harness review`` records.

    ``gate`` defaults to the evidence a green verify gate records (CAL-1082) —
    what a current ``harness review`` always writes — so these tests exercise the
    close gate rather than its verify-gate backstop. Pass ``gate={}`` to seed the
    *legacy* payload (no ``gate_ran`` key), which the backstop refuses.
    """

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
                **(
                    {"gate_ran": True, "gate_command": "bash scripts/verify.sh", "gate_exit_code": 0}
                    if gate is None
                    else gate
                ),
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


async def _fetch_close_events(db_path: Path, run_id: str) -> list[tuple[Any, ...]]:
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT id, data_json FROM events "
            "WHERE run_id = ? AND event_type = 'close'",
            (run_id,),
        ) as cur,
    ):
        return list(await cur.fetchall())


def fetch_close_events(db_path: Path, run_id: str) -> list[tuple[Any, ...]]:
    return _sync(_fetch_close_events(db_path, run_id))


def _install_close_event_failure_trigger(db_path: Path) -> None:
    """Make the close-event INSERT fail deterministically at the DB layer.

    A ``BEFORE INSERT`` trigger that ``RAISE(ABORT)``s only for the ``close``
    event, so the failure lands on exactly the write CAL-1002 makes atomic —
    and lands identically whether the emit runs on its own connection (the
    pre-fix code) or inside the status-flip transaction (the fix). The review
    seed (``event_type='review'``) is untouched, so the gate still passes.
    """

    async def _install() -> None:
        async with store.connect(db_path) as conn:
            await conn.execute(
                "CREATE TRIGGER _fail_close_event BEFORE INSERT ON events "
                "WHEN NEW.event_type = 'close' "
                "BEGIN SELECT RAISE(ABORT, 'injected close-event write failure'); END"
            )
            await conn.commit()

    _sync(_install())


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
# AC-dirty: pass-then-edit-without-committing → refusal dirty_worktree (CAL-586)
# ---------------------------------------------------------------------------


def test_dirty_worktree_refused_when_uncommitted_edits(repo: Path, db_path: Path) -> None:
    """A pass for HEAD does NOT cover uncommitted edits — close must refuse.

    CAL-586 / CODE-1: the gate binds to HEAD, but ``_merge_and_push`` used to
    auto-commit a dirty worktree, merging content that no review ever saw.
    ``stale_review`` catches commit-after-review; it does NOT catch
    edit-without-committing because HEAD is unchanged. The dirty tree must be
    refused outright (``dirty_worktree``) before any merge.
    """
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")

    # Edit the worktree WITHOUT committing — HEAD still equals the reviewed SHA.
    (repo / "sneaky.txt").write_text("unreviewed content\n")
    assert _head_sha(repo) == head  # the pass still nominally matches HEAD

    stub = _make_linear_stub()
    result, merge = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["reason"] == "dirty_worktree"

    # No merge, no Done, run still open — the unreviewed edit never lands.
    merge.assert_not_called()
    stub.transition_to_done.assert_not_called()
    assert fetch_run_status(db_path, run_id) == "open"


def test_dirty_worktree_refused_with_modified_tracked_file(repo: Path, db_path: Path) -> None:
    """Modifying a tracked file (not just adding an untracked one) is also refused."""
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")

    (repo / "README.md").write_text("hello\nedited after review\n")
    assert _head_sha(repo) == head

    stub = _make_linear_stub()
    result, merge = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code != 0
    assert json.loads(result.output)["reason"] == "dirty_worktree"
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
# CAL-1082 AC-6: a pass carrying no verify-gate evidence → no_gate_evidence
# ---------------------------------------------------------------------------


def test_pass_without_gate_evidence_is_refused(repo: Path, db_path: Path) -> None:
    """A pass written before the verify gate existed carries no ``gate_ran`` key.

    ``json_extract`` yields NULL for it, and the backstop reads that as "no
    evidence a test ever ran" and refuses — fail-safe, so no ledger migration is
    needed and a pre-CAL-1082 pass cannot be spent on a merge.
    """
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass", gate={})  # legacy payload
    stub = _make_linear_stub()

    result, merge = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["reason"] == "no_gate_evidence"

    merge.assert_not_called()
    stub.transition_to_done.assert_not_called()
    assert fetch_run_status(db_path, run_id) == "open"


def test_pass_with_unconfigured_gate_is_allowed(repo: Path, db_path: Path) -> None:
    """A repo defining no ``verify:`` records the absence honestly, and closes.

    The harness cannot gate what a repo does not define; refusing here would
    strand every repo without a gate, which is its own decision to make.
    """
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(
        db_path, run_id, head, "pass", gate={"gate_ran": False, "gate_reason": "not_configured"}
    )
    stub = _make_linear_stub()

    result, merge = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code == 0, result.output
    merge.assert_called_once()
    stub.transition_to_done.assert_called_once()


def test_pass_with_green_gate_evidence_closes(repo: Path, db_path: Path) -> None:
    """The evidence a green gate records opens the close gate (the happy path)."""
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")  # defaults to green-gate evidence
    stub = _make_linear_stub()

    result, _ = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code == 0, result.output


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
# Unconfigured Linear: missing LINEAR_API_KEY → exit 2, no reason, no side effect
# ---------------------------------------------------------------------------


def test_close_exits_2_when_linear_unconfigured(repo: Path, db_path: Path) -> None:
    """A missing ``LINEAR_API_KEY`` exits 2 with no ``reason`` — not exit 1.

    The key check (close.py step 5) runs *after* the gate passes but *before*
    any side effect, so an unset key on an otherwise-closeable run refuses
    cleanly without half-merging a tree. ``LinearConfigError`` is not a gate
    refusal, so the JSON carries an ``error`` but no ``reason``. Pins the exit-2
    branch the docstring exit-code block must document (guarded by
    ``test_close_docstring_exit_codes_match_contract``).
    """
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")
    stub = _make_linear_stub()
    merge = MagicMock(return_value=None)

    with (
        patch("harness.cli.close.LinearClient", return_value=stub),
        patch(
            "harness.cli.close.linear_api_key",
            side_effect=LinearConfigError("LINEAR_API_KEY is not set"),
        ),
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

    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert "error" in payload
    assert "reason" not in payload  # a config error is not a gate refusal

    # The gate passed, but the unset key blocks before any side effect.
    merge.assert_not_called()
    stub.transition_to_done.assert_not_called()
    assert fetch_run_status(db_path, run_id) == "open"


def test_close_docstring_exit_codes_match_contract() -> None:
    """The module docstring's exit-code block must match the tested behaviour.

    ``close`` raises exit 2 not only for the four gate refusals but also when
    Linear is unconfigured (a missing ``LINEAR_API_KEY`` →
    :class:`LinearConfigError`, close.py step 5). That config error is *not* a
    gate refusal and carries no ``reason``; it must not be documented as a
    generic "Linear error" under exit 1. Guards against the exit-2 entry
    drifting back to a gate-refusal-only list and the exit-1 entry claiming a
    Linear configuration error exits 1 — both falsified by
    ``test_close_exits_2_when_linear_unconfigured``.
    """
    doc = close_mod.__doc__ or ""
    exit_block = doc[doc.index("Exit codes") :]
    # The exit-2 entry is the last bullet; it runs from "* 2" to the end of the
    # block, spanning its continuation lines. The exit-1 entry runs from "* 1"
    # up to "* 2".
    two_entry = exit_block[exit_block.index("* 2") :]
    one_entry = exit_block[exit_block.index("* 1") : exit_block.index("* 2")]

    assert "LINEAR_API_KEY" in two_entry, (
        "exit 2 covers a missing LINEAR_API_KEY (LinearConfigError), not just "
        "the four gate-refusal reasons; document it in the exit-2 entry"
    )
    assert "Linear error" not in one_entry, (
        "a missing/unconfigured Linear key exits 2, not 1; the exit-1 entry "
        "must not claim a generic 'Linear error' exits 1"
    )


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


# ---------------------------------------------------------------------------
# AC-teardown (CAL-767): a successful close reclaims the worktree + branch
# ---------------------------------------------------------------------------

WT_RUN_ID = "01JRUNCLOSEWORKTREE0000001"


def _seed_run_with_worktree(db_path: Path, repo: Path) -> tuple[str, Path, str]:
    """Seed an open run backed by a REAL worktree under .worktrees/harness/.

    Unlike :func:`_seed_open_run` (whose ``worktree_path`` is the repo itself),
    this creates an actual ``git worktree`` so the teardown step has something to
    reclaim. The worktree HEAD equals the repo's ``dev`` tip, so the gate binds
    to ``_head_sha(repo)``.
    """
    path = repo / ".worktrees" / "harness" / WT_RUN_ID
    branch = f"harness/{WT_RUN_ID}"
    _git(repo, "worktree", "add", "-b", branch, str(path), "dev")

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
                    WT_RUN_ID, "", 0, "open", "{}", "{}", "dev",
                    str(path), branch, "CAL-572", "2026-06-10T00:00:00Z", 1234,
                ),
            )
            await conn.commit()

    _sync(_insert())
    return WT_RUN_ID, path, branch


def _local_branches(repo: Path) -> set[str]:
    out = _git(repo, "branch", "--format=%(refname:short)").stdout
    return set(out.split())


def test_close_reclaims_worktree_and_branch_on_success(repo: Path, db_path: Path) -> None:
    """CAL-767: after a successful close the worktree dir and local branch are gone."""
    run_id, path, branch = _seed_run_with_worktree(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo), "pass")
    assert path.exists()
    assert branch in _local_branches(repo)

    result, _merge = _invoke(repo, db_path, run_id, _make_linear_stub())

    assert result.exit_code == 0, result.output
    assert not path.exists()
    assert branch not in _local_branches(repo)


def test_close_does_not_reclaim_on_gate_refusal(repo: Path, db_path: Path) -> None:
    """A stale-review refusal exits before teardown — the worktree survives."""
    run_id, path, branch = _seed_run_with_worktree(db_path, repo)
    _emit_review(db_path, run_id, "0" * 40, "pass")  # pass for a different SHA

    result, merge = _invoke(repo, db_path, run_id, _make_linear_stub())

    assert result.exit_code == 2
    assert json.loads(result.output)["reason"] == "stale_review"
    merge.assert_not_called()
    assert path.exists()  # worktree NOT torn down
    assert branch in _local_branches(repo)


def test_close_succeeds_even_if_teardown_raises(repo: Path, db_path: Path) -> None:
    """Teardown is best-effort: an exception in it never fails an already-landed
    close (merge/Done/ledger have all succeeded)."""
    run_id = _seed_open_run(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo), "pass")

    with patch.object(close_mod, "teardown_worktree", side_effect=RuntimeError("boom")):
        result, merge = _invoke(repo, db_path, run_id, _make_linear_stub())

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "closed"
    assert payload["merged"] is True
    assert payload["ticket_done"] is True
    merge.assert_called_once()


# ---------------------------------------------------------------------------
# CAL-1002: the status flip and the close event land in ONE transaction
# ---------------------------------------------------------------------------


def test_close_records_close_event_on_success(repo: Path, db_path: Path) -> None:
    """A successful close appends exactly one ``close`` event carrying the run,
    ticket and merged SHA — guards the atomic write against silently dropping
    the audit event when the emit is inlined into the status-flip transaction."""
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")

    result, _merge = _invoke(repo, db_path, run_id, _make_linear_stub())
    assert result.exit_code == 0, result.output

    events = fetch_close_events(db_path, run_id)
    assert len(events) == 1
    data = json.loads(events[0][1])
    assert data["run_id"] == run_id
    assert data["ticket"] == "CAL-572"
    assert data["merged_sha"] == head


def test_close_transition_failure_after_merge_leaves_run_open(
    repo: Path, db_path: Path
) -> None:
    """A Linear Done-transition failure AFTER merge+push exits 1 and leaves the
    ledger consistent — the run stays ``open`` and no ``close`` event is written,
    so close is re-drivable. Exercises the previously-unused
    ``_make_linear_stub(raise_on_transition=...)`` path (CAL-1002)."""
    from harness.linear import LinearRequestError

    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")
    stub = _make_linear_stub(
        raise_on_transition=LinearRequestError("permission denied")
    )

    result, merge = _invoke(repo, db_path, run_id, stub)

    # Exit 1 (an unexpected error), not a gate refusal (no ``reason``).
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert "reason" not in payload
    assert "transition ticket to Done" in payload["error"]

    # Merge+push happened before the failure; the Done transition was attempted.
    merge.assert_called_once()
    stub.transition_to_done.assert_called_once_with("CAL-572")

    # Ledger stays consistent: run still open, no close event.
    assert fetch_run_status(db_path, run_id) == "open"
    assert fetch_close_events(db_path, run_id) == []


def test_close_event_write_failure_leaves_ledger_consistent(
    repo: Path, db_path: Path
) -> None:
    """If the close-event write fails, the status flip must NOT persist.

    CAL-1002: before the fix ``_mark_run_closed`` committed ``status='closed'``
    on its own connection, then emitted the ``close`` event on a *second*
    connection — a failed event write left a terminal ``closed`` run with no
    close event, an inconsistent ledger no retry can repair (nothing re-drives a
    terminal run). The fix makes the flip and the event one ``BEGIN IMMEDIATE``
    transaction, so a failed event write rolls the flip back: the run stays
    ``open`` and re-drivable.
    """
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")
    _install_close_event_failure_trigger(db_path)

    stub = _make_linear_stub()
    result, merge = _invoke(repo, db_path, run_id, stub)

    # The ledger write failed → exit 1 (unexpected error, not a gate refusal).
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert "reason" not in payload

    # The failure is AFTER merge+push and the Done transition.
    merge.assert_called_once()
    stub.transition_to_done.assert_called_once_with("CAL-572")

    # Atomic: the failed close-event write rolled the status flip back.
    assert fetch_run_status(db_path, run_id) == "open"
    assert fetch_close_events(db_path, run_id) == []
