"""Tests for ``harness start <TICKET>`` — AC-1 through AC-5.

AC-1: creates exactly one open ``runs`` row with the expected fields.
AC-2: transitions the ticket to In Progress (GraphQL mutation called).
AC-3: worktree created at the expected path on the run branch.
AC-4: invalid ticket → non-zero exit, zero side effects.
AC-5: ``--json`` output validates against the documented schema.
AC-context-economy: compact ticket blob only (not raw GraphQL response).
AC-description-bound: description truncated at TICKET_DESCRIPTION_MAX_CHARS.
AC-schema-existing-run: existing-run response validates against StartOutput.
AC-concurrent-start: DB unique index prevents duplicate open rows.
AC-canonical-identifier: mixed-case/alias inputs cannot open duplicate runs.
AC-transport-rollback: a transport failure (e.g. timeout) leaves zero side effects.
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


def _fake_ticket() -> dict[str, Any]:
    """Minimal ticket payload returned by the stubbed Linear client."""
    return {
        "id": "abc-123-uuid",
        "identifier": "CAL-570",
        "title": "feat: harness start verb",
        "description": "Build the start command.",
        "url": "https://linear.app/team/issue/CAL-570",
    }


def _make_linear_stub(
    ticket: dict[str, Any] | None = None,
    raise_on_fetch: Exception | None = None,
    raise_on_transition: Exception | None = None,
) -> MagicMock:
    """Return a mock :class:`LinearClient` whose async methods return canned data.

    ``fetch_issue`` and ``transition_to_in_progress`` are awaited by the
    command, so they are :class:`AsyncMock` instances.
    """
    mock = MagicMock()
    if raise_on_fetch is not None:
        mock.fetch_issue = AsyncMock(side_effect=raise_on_fetch)
    else:
        mock.fetch_issue = AsyncMock(return_value=ticket or _fake_ticket())

    if raise_on_transition is not None:
        mock.transition_to_in_progress = AsyncMock(side_effect=raise_on_transition)
    else:
        mock.transition_to_in_progress = AsyncMock(return_value=None)

    return mock


# ---------------------------------------------------------------------------
# Helper — query DB for runs rows
# ---------------------------------------------------------------------------


async def _fetch_all_runs(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    async with store.connect(db_path) as conn:
        conn.row_factory = None  # raw tuples
        async with conn.execute(
            "SELECT run_id, ticket, status, base_branch, worktree_path, "
            "worktree_branch, started_at FROM runs"
        ) as cur:
            cols = [d[0] for d in cur.description]  # type: ignore[union-attr]
            rows = await cur.fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


def _sync(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def fetch_runs(db_path: Path) -> list[dict[str, Any]]:
    return _sync(_fetch_all_runs(db_path))


# ---------------------------------------------------------------------------
# AC-1: creates exactly one open runs row with the right fields
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_ac1_creates_one_open_run_row(repo: Path, db_path: Path) -> None:
    """AC-1: one ``runs`` row with status=open and all required fields."""
    stub = _make_linear_stub()
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result = cli_runner.invoke(
            app,
            ["start", "CAL-570", "--repo", str(repo), "--db", str(db_path), "--json"],
        )

    assert result.exit_code == 0, result.output

    rows = fetch_runs(db_path)
    assert len(rows) == 1
    row = rows[0]

    assert row["ticket"] == "CAL-570"
    assert row["status"] == "open"
    assert row["base_branch"] == "dev"
    assert row["worktree_path"] is not None
    assert row["worktree_branch"] is not None
    assert row["started_at"] is not None
    # run_id must be a 26-char ULID
    assert row["run_id"] is not None
    assert len(row["run_id"]) == 26


# ---------------------------------------------------------------------------
# AC-2: ticket transitions to In Progress
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_ac2_transitions_ticket_to_in_progress(repo: Path, db_path: Path) -> None:
    """AC-2: Linear mutation called with the canonical ticket identifier."""
    stub = _make_linear_stub()
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result = cli_runner.invoke(
            app,
            ["start", "CAL-570", "--repo", str(repo), "--db", str(db_path), "--json"],
        )

    assert result.exit_code == 0, result.output
    stub.transition_to_in_progress.assert_called_once_with("CAL-570")


# ---------------------------------------------------------------------------
# AC-3: worktree created at the expected path on the run branch
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_ac3_worktree_created_at_expected_path(repo: Path, db_path: Path) -> None:
    """AC-3: worktree dir exists and is on the expected harness/<run_id> branch."""
    stub = _make_linear_stub()
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result = cli_runner.invoke(
            app,
            ["start", "CAL-570", "--repo", str(repo), "--db", str(db_path), "--json"],
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    worktree_path = Path(payload["worktree_path"])
    assert worktree_path.exists(), f"worktree path {worktree_path} does not exist"

    # The branch must be harness/<run_id>
    run_id = payload["run_id"]
    assert payload["worktree_branch"] == f"harness/{run_id}"

    # The worktree must be under .worktrees/harness/<run_id>
    expected_root = repo / ".worktrees" / "harness" / run_id
    assert worktree_path == expected_root


# ---------------------------------------------------------------------------
# AC-4: invalid ticket → non-zero exit, zero side effects
# ---------------------------------------------------------------------------


def test_ac4_invalid_ticket_nonzero_exit_no_side_effects(
    repo: Path, db_path: Path
) -> None:
    """AC-4: missing ticket → exit 2, no runs row, no worktree."""
    from harness.linear import LinearNotFound

    stub = _make_linear_stub(raise_on_fetch=LinearNotFound("CAL-999 not found"))
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result = cli_runner.invoke(
            app,
            ["start", "CAL-999", "--repo", str(repo), "--db", str(db_path), "--json"],
        )

    assert result.exit_code != 0

    # No runs row created.
    rows = fetch_runs(db_path)
    assert rows == []

    # No worktree directory created.
    wt_root = repo / ".worktrees" / "harness"
    assert not wt_root.exists() or not list(wt_root.iterdir())


# ---------------------------------------------------------------------------
# AC-5: --json output validates against the documented schema (both paths)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_ac5_json_output_schema_new_run(repo: Path, db_path: Path) -> None:
    """AC-5: new-run JSON output parses and validates against StartOutput schema."""
    from harness.cli.start import StartOutput

    stub = _make_linear_stub()
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result = cli_runner.invoke(
            app,
            ["start", "CAL-570", "--repo", str(repo), "--db", str(db_path), "--json"],
        )

    assert result.exit_code == 0, result.output

    # Validate via Pydantic model — this is the authoritative schema check.
    output = StartOutput.model_validate_json(result.output)

    assert len(output.run_id) == 26  # ULID
    assert output.ticket.identifier == "CAL-570"
    assert output.ticket.id is not None
    assert output.ticket.title is not None
    assert output.ticket.description is not None
    assert isinstance(output.worktree_path, str)
    assert isinstance(output.worktree_branch, str)
    assert isinstance(output.base_branch, str)

    # Must NOT include extra Linear fields
    raw = json.loads(result.output)
    ticket = raw["ticket"]
    assert "team" not in ticket
    assert "nodes" not in ticket


@pytest.mark.slow
def test_ac5_json_output_schema_existing_run(repo: Path, db_path: Path) -> None:
    """AC-5: existing-run JSON output parses and validates against StartOutput schema."""
    from harness.cli.start import StartOutput

    stub = _make_linear_stub()
    invoke_args = [
        "start", "CAL-570", "--repo", str(repo), "--db", str(db_path), "--json"
    ]
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result1 = cli_runner.invoke(app, invoke_args)
        result2 = cli_runner.invoke(app, invoke_args)

    assert result1.exit_code == 0, result1.output
    assert result2.exit_code == 0, result2.output

    # Both outputs must validate against the same Pydantic schema.
    out1 = StartOutput.model_validate_json(result1.output)
    out2 = StartOutput.model_validate_json(result2.output)

    # Existing-run response must carry the same run_id as the first run.
    assert out1.run_id == out2.run_id

    # Existing-run response must have full ticket context, not just identifier.
    assert out2.ticket.id is not None
    assert out2.ticket.title is not None


# ---------------------------------------------------------------------------
# AC-context-economy: no raw GraphQL payload in output
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_context_economy_compact_blob(repo: Path, db_path: Path) -> None:
    """Context economy: output is bounded and contains only agent-relevant fields."""
    # Simulate a fat Linear response that the LinearClient normalises
    fat_ticket = {
        "id": "abc-123-uuid",
        "identifier": "CAL-570",
        "title": "feat: harness start verb",
        "description": "Build the start command.",
        "url": "https://linear.app/team/issue/CAL-570",
        # these extra fields must NOT appear in the output
        "team": {"id": "team-id", "states": {"nodes": []}},
        "extra_field": "should_be_dropped",
    }
    stub = _make_linear_stub(ticket=fat_ticket)
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result = cli_runner.invoke(
            app,
            ["start", "CAL-570", "--repo", str(repo), "--db", str(db_path), "--json"],
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    ticket = payload["ticket"]

    # Compact — only the declared fields
    allowed_ticket_keys = {"id", "identifier", "title", "description", "url"}
    assert set(ticket.keys()) <= allowed_ticket_keys
    assert "team" not in ticket
    assert "extra_field" not in ticket


# ---------------------------------------------------------------------------
# AC-4 extension: duplicate ticket → refuse, no second run row
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_duplicate_ticket_refused(repo: Path, db_path: Path) -> None:
    """A second ``harness start`` for the same ticket surfaces the existing run."""
    stub = _make_linear_stub()
    invoke_args = [
        "start", "CAL-570", "--repo", str(repo), "--db", str(db_path), "--json"
    ]
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result1 = cli_runner.invoke(app, invoke_args)
        result2 = cli_runner.invoke(app, invoke_args)

    assert result1.exit_code == 0, result1.output

    # Either way there must be exactly one runs row.
    rows = fetch_runs(db_path)
    assert len(rows) == 1, f"expected exactly 1 run row, got {len(rows)}"

    if result2.exit_code == 0:
        # Surfaced existing run — must return the same run_id
        p1 = json.loads(result1.output)
        p2 = json.loads(result2.output)
        assert p1["run_id"] == p2["run_id"]
    # else: refused with non-zero, which is also acceptable


# ---------------------------------------------------------------------------
# AC-canonical-identifier: mixed-case input dedupes to one run
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_canonical_identifier_dedupes_mixed_case(repo: Path, db_path: Path) -> None:
    """A lowercase alias then the canonical spelling must not open two runs.

    The Linear payload's ``identifier`` (``CAL-570``) is authoritative — both
    invocations key off it, so the second call surfaces the existing run.
    """
    stub = _make_linear_stub()  # always returns identifier "CAL-570"
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result1 = cli_runner.invoke(
            app,
            ["start", "cal-570", "--repo", str(repo), "--db", str(db_path), "--json"],
        )
        result2 = cli_runner.invoke(
            app,
            ["start", "CAL-570", "--repo", str(repo), "--db", str(db_path), "--json"],
        )

    assert result1.exit_code == 0, result1.output
    assert result2.exit_code == 0, result2.output

    rows = fetch_runs(db_path)
    assert len(rows) == 1, f"expected exactly 1 run row, got {len(rows)}"
    assert rows[0]["ticket"] == "CAL-570"

    # Both responses point at the same run.
    p1 = json.loads(result1.output)
    p2 = json.loads(result2.output)
    assert p1["run_id"] == p2["run_id"]


# ---------------------------------------------------------------------------
# AC-description-bound: description truncated at TICKET_DESCRIPTION_MAX_CHARS
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_description_truncated_at_max_chars(repo: Path, db_path: Path) -> None:
    """AC-description-bound: oversized description is capped at TICKET_DESCRIPTION_MAX_CHARS."""
    from harness.cli.start import TICKET_DESCRIPTION_MAX_CHARS, StartOutput

    oversized_desc = "x" * (TICKET_DESCRIPTION_MAX_CHARS + 500)
    fat_ticket = {
        "id": "abc-123-uuid",
        "identifier": "CAL-570",
        "title": "feat: harness start verb",
        "description": oversized_desc,
        "url": "https://linear.app/team/issue/CAL-570",
    }
    stub = _make_linear_stub(ticket=fat_ticket)
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result = cli_runner.invoke(
            app,
            ["start", "CAL-570", "--repo", str(repo), "--db", str(db_path), "--json"],
        )

    assert result.exit_code == 0, result.output

    output = StartOutput.model_validate_json(result.output)
    assert output.ticket.description is not None
    # The description in the output must not exceed the limit + truncation suffix.
    assert len(output.ticket.description) <= TICKET_DESCRIPTION_MAX_CHARS + len("... [truncated]")
    # Original oversized description must be shorter in the output.
    assert len(output.ticket.description) < len(oversized_desc)
    # The sentinel suffix must be present so readers know truncation happened.
    assert output.ticket.description.endswith("... [truncated]")


# ---------------------------------------------------------------------------
# AC-concurrent-start: DB unique index prevents duplicate open rows
# ---------------------------------------------------------------------------


async def test_concurrent_start_conflict_handled(tmp_path: Path) -> None:
    """AC-concurrent-start: inserting a second open row for the same ticket raises IntegrityError.

    This test directly exercises the database-level uniqueness guarantee by
    inserting two rows with the same ticket and status='open', asserting that
    SQLite raises IntegrityError on the second insert.
    """
    import aiosqlite

    db_path = tmp_path / ".harness" / "harness.db"
    await store.init_db(db_path)

    run_id_1 = "01ABCDEFGHIJKLMNOPQRSTUV01"
    run_id_2 = "01ABCDEFGHIJKLMNOPQRSTUV02"
    common_row = {
        "workflow_name": "",
        "workflow_version": 0,
        "status": "open",
        "state_json": "{}",
        "inputs_json": "{}",
        "base_branch": "dev",
        "worktree_path": "/tmp/wt1",
        "worktree_branch": "harness/run1",
        "ticket": "CAL-570",
        "started_at": "2026-01-01T00:00:00+00:00",
        "pid": 1,
    }

    async with store.connect(db_path) as conn:
        # First insert must succeed.
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, base_branch, worktree_path, worktree_branch, "
            "ticket, started_at, pid) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id_1, *common_row.values()),
        )
        await conn.commit()

        # Second insert for the same ticket with status='open' must raise
        # IntegrityError from the partial unique index.
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
                "state_json, inputs_json, base_branch, worktree_path, worktree_branch, "
                "ticket, started_at, pid) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id_2, *common_row.values()),
            )
            await conn.commit()


# ---------------------------------------------------------------------------
# Unit tests for LinearClient (no git, no db) — async client
# ---------------------------------------------------------------------------


async def test_linear_client_fetch_issue_returns_compact_ticket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LinearClient.fetch_issue returns a compact dict with required keys."""
    from harness.linear import LinearClient

    captured: list[dict[str, Any]] = []

    response_data = {
        "data": {
            "issue": {
                "id": "abc-uuid",
                "identifier": "CAL-1",
                "title": "Test ticket",
                "description": "A description.",
                "url": "https://linear.app/x",
            }
        }
    }

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        captured.append({"query": query, "variables": variables})
        return response_data

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    ticket = await client.fetch_issue("CAL-1")

    assert ticket["identifier"] == "CAL-1"
    assert ticket["title"] == "Test ticket"
    assert "id" in ticket
    assert "description" in ticket

    # Assert the query uses the documented `issue(id: ...)` field, not `issueByIdentifier`.
    assert len(captured) == 1
    assert "issue(id:" in captured[0]["query"] or "issue(" in captured[0]["query"]
    assert "issueByIdentifier" not in captured[0]["query"]
    assert captured[0]["variables"] == {"id": "CAL-1"}


async def test_linear_client_raises_not_found_for_null_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LinearClient raises LinearNotFound when the API returns null issue."""
    from harness.linear import LinearClient, LinearNotFound

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {"data": {"issue": None}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearNotFound):
        await client.fetch_issue("CAL-999")


async def test_linear_client_transition_calls_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LinearClient.transition_to_in_progress fires a mutation using issue(id:) field."""
    from harness.linear import LinearClient

    calls: list[dict[str, Any]] = []

    # First call: fetch states (query). Second call: update (mutation).
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
                                    {"id": "state-ip-id", "name": "In Progress", "type": "started"}
                                ]
                            }
                        }
                    }
                }
            }
        # mutation call
        return {"data": {"issueUpdate": {"success": True}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    await client.transition_to_in_progress("CAL-570")

    # At least one call must carry the issueUpdate mutation.
    mutation_calls = [c for c in calls if "issueUpdate" in c["query"]]
    assert len(mutation_calls) >= 1

    # The states query must use `issue(id:)`, not `issueByIdentifier`.
    states_calls = [c for c in calls if "states" in c["query"]]
    assert len(states_calls) >= 1
    assert "issueByIdentifier" not in states_calls[0]["query"]
    assert "issue(" in states_calls[0]["query"]
    assert states_calls[0]["variables"] == {"id": "CAL-570"}


async def test_linear_transition_raises_when_no_started_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """transition_to_in_progress raises LinearRequestError when no started state exists."""
    from harness.linear import LinearClient, LinearRequestError

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {
            "data": {
                "issue": {
                    "id": "issue-id",
                    "team": {
                        "states": {
                            "nodes": [
                                # Only a backlog state — no 'started' type.
                                {"id": "state-backlog", "name": "Backlog", "type": "backlog"}
                            ]
                        }
                    }
                }
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")

    with pytest.raises(LinearRequestError, match="no 'started' workflow state"):
        await client.transition_to_in_progress("CAL-570")


async def test_linear_transition_raises_when_success_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """transition_to_in_progress raises LinearRequestError when issueUpdate.success is false."""
    from harness.linear import LinearClient, LinearRequestError

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        if "states" in query:
            return {
                "data": {
                    "issue": {
                        "id": "issue-id",
                        "team": {
                            "states": {
                                "nodes": [
                                    {"id": "state-ip-id", "name": "In Progress", "type": "started"}
                                ]
                            }
                        }
                    }
                }
            }
        # Mutation returns success: false (e.g. permission denied).
        return {"data": {"issueUpdate": {"success": False}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")

    with pytest.raises(LinearRequestError, match="did not report success"):
        await client.transition_to_in_progress("CAL-570")


async def test_linear_request_converts_timeout_to_request_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A socket timeout (TimeoutError/OSError) is converted to LinearRequestError.

    Guarantees callers only ever see Linear boundary exceptions — never a raw
    transport error escaping the client.
    """
    import urllib.request

    from harness.linear import LinearClient, LinearRequestError

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise TimeoutError("the read operation timed out")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    client = LinearClient(api_key="fake-key")

    with pytest.raises(LinearRequestError):
        await client.fetch_issue("CAL-1")


async def test_linear_api_key_reads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """linear_api_key() returns the value from LINEAR_API_KEY env var."""
    from harness.linear import linear_api_key

    monkeypatch.setenv("LINEAR_API_KEY", "test-key-value")
    assert linear_api_key() == "test-key-value"


async def test_linear_api_key_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """linear_api_key() raises when LINEAR_API_KEY is not set."""
    from harness.linear import LinearConfigError, linear_api_key

    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    with pytest.raises(LinearConfigError):
        linear_api_key()


# ---------------------------------------------------------------------------
# DB migration: runs table gains ticket + worktree_path columns
# ---------------------------------------------------------------------------


async def test_runs_schema_has_ticket_column(tmp_path: Path) -> None:
    """After init_db, runs table has a ticket column."""
    db_path = tmp_path / "harness.db"
    await store.init_db(db_path)

    async with (
        store.connect(db_path) as conn,
        conn.execute("PRAGMA table_info(runs)") as cur,
    ):
        cols = {row[1] async for row in cur}

    assert "ticket" in cols, f"ticket column missing from runs; found: {cols}"
    assert "worktree_path" in cols, f"worktree_path column missing; found: {cols}"


# ---------------------------------------------------------------------------
# start command registered in CLI help
# ---------------------------------------------------------------------------


def test_start_command_registered() -> None:
    """start must appear in the CLI help output."""
    result = cli_runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "start" in result.output


# ---------------------------------------------------------------------------
# Operation ordering: worktree failure → no DB row, no transition
# ---------------------------------------------------------------------------


def test_worktree_failure_leaves_no_db_row_and_no_transition(
    repo: Path, db_path: Path
) -> None:
    """If worktree creation fails, no DB row is inserted and no transition is attempted."""
    from harness.worktree import WorktreeNodeError

    stub = _make_linear_stub()
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
        patch(
            "harness.cli.start.WorktreeNode.create",
            side_effect=WorktreeNodeError("git failed"),
        ),
    ):
        result = cli_runner.invoke(
            app,
            ["start", "CAL-570", "--repo", str(repo), "--db", str(db_path), "--json"],
        )

    assert result.exit_code != 0

    # No DB row must have been inserted.
    rows = fetch_runs(db_path)
    assert rows == [], f"expected no runs row, got {rows}"

    # Linear transition must NOT have been called.
    stub.transition_to_in_progress.assert_not_called()


# ---------------------------------------------------------------------------
# Operation ordering: DB insert failure → worktree removed, no transition
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_db_failure_removes_worktree_and_no_transition(
    repo: Path, db_path: Path
) -> None:
    """If DB insert fails, the worktree is cleaned up and no transition is attempted."""
    stub = _make_linear_stub()
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
        patch(
            "harness.cli.start._insert_open_run",
            side_effect=Exception("DB write failed"),
        ),
        patch(
            "harness.cli.start._cleanup_worktree_sync"
        ) as mock_cleanup,
    ):
        result = cli_runner.invoke(
            app,
            ["start", "CAL-570", "--repo", str(repo), "--db", str(db_path), "--json"],
        )

    assert result.exit_code != 0

    # Cleanup must have been called.
    mock_cleanup.assert_called_once()

    # Linear transition must NOT have been called.
    stub.transition_to_in_progress.assert_not_called()


# ---------------------------------------------------------------------------
# Operation ordering: transition failure → DB row deleted, worktree removed
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_transition_failure_rolls_back_worktree_and_db_row(
    repo: Path, db_path: Path
) -> None:
    """If transition fails, the DB row is deleted and worktree is removed."""
    from harness.linear import LinearRequestError

    stub = _make_linear_stub(
        raise_on_transition=LinearRequestError("permission denied")
    )
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result = cli_runner.invoke(
            app,
            ["start", "CAL-570", "--repo", str(repo), "--db", str(db_path), "--json"],
        )

    assert result.exit_code != 0

    # DB row must have been rolled back.
    rows = fetch_runs(db_path)
    assert rows == [], f"expected no runs row after transition failure, got {rows}"

    # No worktree directory should remain.
    wt_root = repo / ".worktrees" / "harness"
    remaining = list(wt_root.iterdir()) if wt_root.exists() else []
    assert remaining == [], f"expected no worktrees after transition failure, got {remaining}"


# ---------------------------------------------------------------------------
# Transport-rollback: a timeout during transition leaves zero side effects
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_timeout_during_transition_rolls_back(repo: Path, db_path: Path) -> None:
    """A transport failure (timeout, surfaced as LinearRequestError) rolls back all state."""
    from harness.linear import LinearRequestError

    stub = _make_linear_stub(
        raise_on_transition=LinearRequestError("Linear API request failed: timed out")
    )
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result = cli_runner.invoke(
            app,
            ["start", "CAL-570", "--repo", str(repo), "--db", str(db_path), "--json"],
        )

    assert result.exit_code != 0

    rows = fetch_runs(db_path)
    assert rows == [], f"expected no runs row after timeout, got {rows}"

    wt_root = repo / ".worktrees" / "harness"
    remaining = list(wt_root.iterdir()) if wt_root.exists() else []
    assert remaining == [], f"expected no worktrees after timeout, got {remaining}"


# ---------------------------------------------------------------------------
# Finding 3: default DB path resolves relative to --repo, not CWD
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_default_db_resolves_relative_to_repo(repo: Path, tmp_path: Path) -> None:
    """Without --db, the DB file is created inside --repo, not the caller's CWD."""
    stub = _make_linear_stub()
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result = cli_runner.invoke(
            app,
            # No --db flag: let the command choose the path.
            ["start", "CAL-570", "--repo", str(repo), "--json"],
        )

    assert result.exit_code == 0, result.output

    # The DB must have been created inside the repo, not anywhere else.
    expected_db = repo / ".harness" / "harness.db"
    assert expected_db.exists(), (
        f"DB not created at expected path {expected_db}; "
        f"check that default resolution uses repo, not CWD"
    )

    rows = fetch_runs(expected_db)
    assert len(rows) == 1
