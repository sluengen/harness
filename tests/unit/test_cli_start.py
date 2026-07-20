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

import aiosqlite
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


async def _fetch_all_events(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    async with store.connect(db_path) as conn:
        conn.row_factory = None  # raw tuples
        async with conn.execute("SELECT run_id, event_type FROM events") as cur:
            cols = [d[0] for d in cur.description]  # type: ignore[union-attr]
            rows = await cur.fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


def fetch_events(db_path: Path) -> list[dict[str, Any]]:
    return _sync(_fetch_all_events(db_path))


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


@pytest.mark.slow
def test_start_emits_no_event_open_run_is_the_runs_row(
    repo: Path, db_path: Path
) -> None:
    """``start`` records the open run as the ``runs`` row, not an event (SPEC §4.7).

    Only ``review`` and ``close`` append events, so a run is reconstructed from
    the ``runs`` row **plus** its events — not from the event log alone.
    """
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
    assert len(fetch_runs(db_path)) == 1  # the open run is recorded …
    assert fetch_events(db_path) == []  # … but start emits no event


# ---------------------------------------------------------------------------
# CAL-1106: --base resolves from CONTEXT.md branches.integration, not a literal
# ---------------------------------------------------------------------------


def _repo_on(tmp_path: Path, branch: str, integration: str | None) -> Path:
    """A one-commit git repo on ``branch``, optionally with a ``branches:`` block."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", branch)
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    if integration is not None:
        (repo_root / "CONTEXT.md").write_text(
            f"branches:\n  integration: {integration}\n"
        )
    (repo_root / "README.md").write_text("hello\n")
    _git(repo_root, "add", "-A")
    _git(repo_root, "commit", "-m", "initial")
    return repo_root


@pytest.mark.slow
def test_base_resolves_to_configured_integration_branch(tmp_path: Path) -> None:
    """AC-1: a repo whose CONTEXT.md says ``integration: main`` opens the worktree
    off ``main`` when ``start`` is called with no ``--base``."""
    repo_root = _repo_on(tmp_path, "main", integration="main")
    db = repo_root / ".harness" / "harness.db"
    stub = _make_linear_stub()
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result = cli_runner.invoke(
            app, ["start", "CAL-570", "--repo", str(repo_root), "--db", str(db)]
        )

    assert result.exit_code == 0, result.output
    rows = fetch_runs(db)
    assert len(rows) == 1
    assert rows[0]["base_branch"] == "main"


@pytest.mark.slow
def test_base_integration_dev_is_unchanged(tmp_path: Path) -> None:
    """AC-3: a repo configured ``integration: dev`` still opens off ``dev`` — the
    existing behaviour is preserved for the common case."""
    repo_root = _repo_on(tmp_path, "dev", integration="dev")
    db = repo_root / ".harness" / "harness.db"
    stub = _make_linear_stub()
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result = cli_runner.invoke(
            app, ["start", "CAL-570", "--repo", str(repo_root), "--db", str(db)]
        )

    assert result.exit_code == 0, result.output
    assert fetch_runs(db)[0]["base_branch"] == "dev"


@pytest.mark.slow
def test_explicit_base_flag_still_wins(tmp_path: Path) -> None:
    """An explicit ``--base`` overrides the configured integration branch."""
    repo_root = _repo_on(tmp_path, "main", integration="main")
    # A second branch the explicit flag can target.
    _git(repo_root, "branch", "release")
    db = repo_root / ".harness" / "harness.db"
    stub = _make_linear_stub()
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result = cli_runner.invoke(
            app,
            ["start", "CAL-570", "--repo", str(repo_root), "--db", str(db),
             "--base", "release"],
        )

    assert result.exit_code == 0, result.output
    assert fetch_runs(db)[0]["base_branch"] == "release"


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
# CAL-1164: an incoherent tracker/address config is rejected before any work
# ---------------------------------------------------------------------------


def test_incoherent_tracker_config_rejected_before_side_effects(
    repo: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``tracker: linear`` with no ``repo.linear`` address → start refuses up front.

    The coherence guard fires at step 0, before the key check or any fetch, so it
    is the *config* error the caller sees (naming ``repo.linear``), not a
    downstream missing-key error, and nothing is created.
    """
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    (repo / "CONTEXT.md").write_text(
        "repo:\n  name: acme\n  linear: none\ntracker: linear\n"
    )
    _git(repo, "add", "CONTEXT.md")
    _git(repo, "commit", "-m", "incoherent tracker config")

    result = cli_runner.invoke(
        app,
        ["start", "CAL-570", "--repo", str(repo), "--db", str(db_path), "--json"],
    )

    assert result.exit_code != 0
    assert "repo.linear" in result.output
    assert fetch_runs(db_path) == []
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


# ---------------------------------------------------------------------------
# CAL-587: start no longer writes the vestigial runs.pid column
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_start_does_not_write_pid(repo: Path, db_path: Path) -> None:
    """The open run row leaves ``pid`` NULL.

    ``pid`` only ever served the engine-era ``harness cancel`` SIGTERM path,
    which was dead on arrival under the verb model (``start`` writes the row and
    exits, so the PID never named a live process). CAL-587 removed the write.
    """
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

    async def _fetch_pid() -> Any:
        async with store.connect(db_path) as conn:
            cur = await conn.execute("SELECT pid FROM runs")
            row = await cur.fetchone()
        return row[0] if row is not None else "no-row"

    assert _sync(_fetch_pid()) is None


# ---------------------------------------------------------------------------
# AC-docstring-contract: the exit-code block must match tested behaviour
# ---------------------------------------------------------------------------


def test_start_docstring_exit_codes_match_contract() -> None:
    """The module docstring's exit-code block must match the tested behaviour.

    A duplicate ``start`` for the same ticket surfaces the existing run on
    exit 0 (proven by ``test_canonical_identifier_dedupes_mixed_case``), so
    "duplicate run" must not appear on the exit-2 line as an invocation error.
    Guards against the docstring drifting back to the false "duplicate run →
    exit 2" claim that ``test_canonical_identifier_dedupes_mixed_case`` and the
    ``_find_open_run`` short-circuit (``start.py`` step 4) prove wrong.
    """
    from harness.cli import start

    doc = start.__doc__ or ""
    exit_block = doc[doc.index("Exit codes") :]

    # Collect the WHOLE exit-2 entry — the ``* 2`` line plus any wrapped
    # continuation lines, stopping at the next bullet or a blank line — so the
    # claim cannot slip past the guard by wrapping onto a continuation line.
    lines = exit_block.splitlines()
    start_idx = next(
        i for i, line in enumerate(lines) if line.lstrip().startswith("* 2")
    )
    entry = [lines[start_idx]]
    for line in lines[start_idx + 1 :]:
        if not line.strip() or line.lstrip().startswith("* "):
            break
        entry.append(line)
    two_entry = " ".join(entry)
    assert "duplicate" not in two_entry.lower(), (
        "a duplicate start surfaces the existing run on exit 0, not 2; "
        "remove the false claim from the exit-2 entry"
    )
    assert "existing run" in exit_block, (
        "docstring should document the exit-0 existing-run (duplicate start) case"
    )


# ---------------------------------------------------------------------------
# --resume: continue a reclaimed run from its preserved WIP branch (CAL-739)
#
# When the routine picks a `reclaimed` ticket carrying a checkpoint-pushed
# branch, `harness start --resume` bases the new run's worktree on that branch
# (fetch + continue) instead of a clean branch off `dev`. With no durable WIP —
# or a branch that no longer fetches — it falls back to a clean start. Either
# way `base_branch` stays `dev` (the merge target), so close's HEAD-bound gate
# keeps the merge safe from double-merge.
# ---------------------------------------------------------------------------


def _make_resume_stub(
    resume_branch: str | None, handoff_branch: str | None = None
) -> MagicMock:
    """A Linear stub whose reclaim/handoff resume readers return the given branches.

    ``fetch_resume_branch`` returns ``resume_branch`` (the death-keyed source);
    ``fetch_handoff_branch`` returns ``handoff_branch`` (the CAL-923 proactive
    source), defaulting to ``None`` so a stub set up for the reclamation path still
    answers the fall-through ``fetch_handoff_branch`` call cleanly.
    """
    mock = _make_linear_stub()
    mock.fetch_resume_branch = AsyncMock(return_value=resume_branch)
    mock.fetch_handoff_branch = AsyncMock(return_value=handoff_branch)
    return mock


def _setup_origin_with_wip(repo: Path) -> tuple[str, str]:
    """Give ``repo`` an ``origin`` carrying a checkpoint-pushed WIP branch.

    Returns ``(wip_branch, wip_sha)``. The WIP branch is removed locally after
    the push, mirroring the cloud regime: the dead run's worktree is gone and the
    branch survives only because it was checkpoint-pushed to ``origin``.
    """
    origin = repo.parent / "origin.git"
    _git(repo, "init", "--bare", str(origin))
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "origin", "dev")
    _git(repo, "checkout", "-b", "harness/wip")
    (repo / "wip.txt").write_text("recovered work\n")
    _git(repo, "add", "wip.txt")
    _git(repo, "commit", "-m", "wip checkpoint")
    wip_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "push", "origin", "harness/wip")
    _git(repo, "checkout", "dev")
    _git(repo, "branch", "-D", "harness/wip")
    # Drop the remote-tracking ref the push created, so the only path back to the
    # WIP tip is an explicit fetch — proving resume fetches, not a local lookup.
    _git(repo, "update-ref", "-d", "refs/remotes/origin/harness/wip")
    return "harness/wip", wip_sha


def _worktree_head(worktree_path: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=worktree_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.mark.slow
def test_resume_continues_from_preserved_branch(repo: Path, db_path: Path) -> None:
    """AC-1: a `reclaimed` ticket with a pushed WIP branch resumes from it — the
    new worktree continues from the WIP tip, while `base_branch` stays `dev`."""
    wip_branch, wip_sha = _setup_origin_with_wip(repo)
    stub = _make_resume_stub(wip_branch)
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result = cli_runner.invoke(
            app,
            ["start", "CAL-570", "--repo", str(repo), "--db", str(db_path),
             "--resume", "--json"],
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    # The worktree continues from the recovered WIP commit, not a clean dev branch.
    assert _worktree_head(Path(payload["worktree_path"])) == wip_sha
    # The merge target (base_branch) is still dev — close merges into dev, so the
    # HEAD-bound gate keeps the resumed run safe from double-merge (AC-3).
    rows = fetch_runs(db_path)
    assert len(rows) == 1
    assert rows[0]["base_branch"] == "dev"
    stub.fetch_resume_branch.assert_awaited_once_with("CAL-570")


@pytest.mark.slow
def test_resume_continues_from_handoff_branch(repo: Path, db_path: Path) -> None:
    """CAL-923: a proactively handed-off ticket (still In Progress, no `reclaimed`
    label, so `fetch_resume_branch` finds nothing) resumes the SAME ticket from its
    handoff branch — resume falls through to the handoff marker. `base_branch`
    stays `dev`, so close's HEAD-bound gate keeps it safe from double-merge."""
    wip_branch, wip_sha = _setup_origin_with_wip(repo)
    stub = _make_resume_stub(None, handoff_branch=wip_branch)
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result = cli_runner.invoke(
            app,
            ["start", "CAL-570", "--repo", str(repo), "--db", str(db_path),
             "--resume", "--json"],
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert _worktree_head(Path(payload["worktree_path"])) == wip_sha
    rows = fetch_runs(db_path)
    assert len(rows) == 1
    assert rows[0]["base_branch"] == "dev"
    # Reclamation source is consulted first, then the CAL-923 handoff fall-through.
    stub.fetch_resume_branch.assert_awaited_once_with("CAL-570")
    stub.fetch_handoff_branch.assert_awaited_once_with("CAL-570")


@pytest.mark.slow
def test_resume_with_no_durable_wip_restarts_clean(repo: Path, db_path: Path) -> None:
    """AC-2: `--resume` on a ticket with no preserved branch starts clean off dev."""
    dev_sha = _git(repo, "rev-parse", "dev").stdout.strip()
    stub = _make_resume_stub(None)
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result = cli_runner.invoke(
            app,
            ["start", "CAL-570", "--repo", str(repo), "--db", str(db_path),
             "--resume", "--json"],
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert _worktree_head(Path(payload["worktree_path"])) == dev_sha
    assert fetch_runs(db_path)[0]["base_branch"] == "dev"


@pytest.mark.slow
def test_resume_falls_back_clean_when_branch_does_not_fetch(
    repo: Path, db_path: Path
) -> None:
    """AC-2 / best-effort: a named branch that no longer fetches degrades to a
    clean restart rather than blocking the queue."""
    # An origin exists, but the named resume branch is not on it.
    origin = repo.parent / "origin.git"
    _git(repo, "init", "--bare", str(origin))
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "origin", "dev")
    dev_sha = _git(repo, "rev-parse", "dev").stdout.strip()

    stub = _make_resume_stub("harness/ghost-never-pushed")
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result = cli_runner.invoke(
            app,
            ["start", "CAL-570", "--repo", str(repo), "--db", str(db_path),
             "--resume", "--json"],
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    # Fell back to a clean branch off dev — the run still opens.
    assert _worktree_head(Path(payload["worktree_path"])) == dev_sha
    assert fetch_runs(db_path)[0]["base_branch"] == "dev"


@pytest.mark.slow
def test_no_resume_flag_never_probes_for_a_branch(repo: Path, db_path: Path) -> None:
    """Without `--resume`, start never calls fetch_resume_branch — a plain start
    is unchanged (an ordinary interactive run pays no resume cost)."""
    stub = _make_resume_stub("harness/should-not-be-used")
    with (
        patch("harness.cli.start.LinearClient", return_value=stub),
        patch("harness.cli.start.linear_api_key", return_value="test-key"),
    ):
        result = cli_runner.invoke(
            app,
            ["start", "CAL-570", "--repo", str(repo), "--db", str(db_path), "--json"],
        )

    assert result.exit_code == 0, result.output
    stub.fetch_resume_branch.assert_not_awaited()


# ---------------------------------------------------------------------------
# CAL-1154: a clean start bases the run worktree off origin/<base>, with a
# local-<base> fallback, since close no longer advances the local base branch.
# ---------------------------------------------------------------------------


def test_clean_start_bases_worktree_off_origin_base(repo: Path, db_path: Path) -> None:
    """A clean start bases the worktree off ``origin/dev`` when it is ahead of local.

    Since CAL-1154 ``close`` pushes ``origin/<base>`` without advancing local
    ``dev``, basing a new run off local ``dev`` would start it on a tree that lags
    the merged work. Here ``origin/dev`` carries a commit local ``dev`` does not;
    a clean ``start`` must produce a worktree at the ``origin/dev`` tip (so the file
    only on ``origin/dev`` is present), while recording ``base_branch`` = ``dev``.
    """
    origin = repo.parent / "origin.git"
    _git(repo, "init", "--bare", str(origin))
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "origin", "dev")
    # Land a commit on origin/dev via a feeder branch pushed from THIS repo — the
    # push advances the local origin/dev tracking ref (exactly what a close push
    # does), while local dev is left behind.
    _git(repo, "checkout", "-b", "feeder")
    (repo / "on_origin.txt").write_text("only on origin/dev\n")
    _git(repo, "add", "on_origin.txt")
    _git(repo, "commit", "-m", "advance origin/dev")
    _git(repo, "push", "origin", "feeder:dev")
    _git(repo, "checkout", "dev")
    _git(repo, "branch", "-D", "feeder")
    origin_dev = _git(repo, "rev-parse", "origin/dev").stdout.strip()
    local_dev = _git(repo, "rev-parse", "dev").stdout.strip()
    assert origin_dev != local_dev  # precondition: local dev lags origin/dev

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
    wt = Path(payload["worktree_path"])
    # The worktree starts at the origin/dev tip — the file only on origin/dev is
    # present, and its HEAD equals origin/dev, not the lagging local dev.
    assert (wt / "on_origin.txt").exists()
    assert _worktree_head(wt) == origin_dev
    # The recorded merge target is still the local base name.
    assert payload["base_branch"] == "dev"


def test_clean_start_falls_back_to_local_base_without_origin(
    repo: Path, db_path: Path
) -> None:
    """No ``origin`` remote → a clean start bases off local ``dev`` (unchanged).

    The fallback that keeps offline / no-origin repos — and much of the test suite
    — behaving exactly as before CAL-1154.
    """
    local_dev = _git(repo, "rev-parse", "dev").stdout.strip()
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
    assert _worktree_head(Path(payload["worktree_path"])) == local_dev
    assert payload["base_branch"] == "dev"


# ---------------------------------------------------------------------------
# CAL-1007: the two silent error paths are un-swallowed.
#
# 1. `_find_open_run` must not read a locked/corrupt DB as "no existing run":
#    a real read failure surfaces with its cause (as `_StartError`), while an
#    uninitialized DB (file exists, no `runs` table) stays the quiet empty case.
# 2. `_delete_run_row` (rollback) must stay best-effort — never re-raise — but a
#    failed rollback is no longer silent: it warns to stderr naming the orphaned
#    run_id and the manual remedy, so the orphan open row that would block every
#    future start for the ticket is visible rather than invisible.
# ---------------------------------------------------------------------------


def test_find_open_run_surfaces_db_read_failure(repo: Path, db_path: Path) -> None:
    """A locked/corrupt DB read surfaces as `_StartError` carrying its cause.

    The old `except Exception: return None` masqueraded a failed read as "no
    existing open run", so start proceeded and later reported the misleading
    "concurrent start conflict but no existing run found". The real cause must
    surface instead (CAL-1007, swallow #1).
    """
    from harness.cli.start import _find_open_run, _StartError

    # The file must exist so the `db_path.exists()` short-circuit does not fire —
    # this is the "DB present but unreadable" case, not "DB missing".
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_bytes(b"")

    boom = aiosqlite.OperationalError("database is locked")
    with patch("harness.cli.start.store.connect", side_effect=boom):  # noqa: SIM117
        with pytest.raises(_StartError) as excinfo:
            _sync(_find_open_run(db_path, "CAL-570"))

    assert "database is locked" in str(excinfo.value), (
        "the underlying DB error must be carried in the surfaced message"
    )
    assert excinfo.value.code == 1


def test_find_open_run_returns_none_for_uninitialized_db(
    repo: Path, db_path: Path
) -> None:
    """A DB file that exists but has no `runs` table genuinely has no open run.

    Guards the *empty* side of the narrowing: only a real read failure raises;
    an uninitialized DB (no `runs` table yet) is a quiet `None`, not an error
    (CAL-1007, swallow #1 boundary).
    """
    from harness.cli.start import _find_open_run

    db_path.parent.mkdir(parents=True, exist_ok=True)

    async def _make_db_without_runs_table() -> None:
        async with store.connect(db_path) as conn:
            await conn.execute("CREATE TABLE unrelated (x)")
            await conn.commit()

    _sync(_make_db_without_runs_table())

    assert _sync(_find_open_run(db_path, "CAL-570")) is None


def test_delete_run_row_warns_when_rollback_fails(
    repo: Path, db_path: Path
) -> None:
    """A failed rollback DELETE warns (naming run_id + remedy) but never raises.

    The old `except Exception: pass` left an orphan `open` row — whose partial
    unique index blocks every future start for that ticket — completely silent.
    The rollback stays best-effort (must not re-raise, or it would mask the
    original error), but it now emits an actionable stderr warning (CAL-1007,
    swallow #2).
    """
    from harness.cli import start as start_mod

    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_bytes(b"")  # exists → passes the `db_path.exists()` guard

    boom = aiosqlite.OperationalError("database is locked")
    with (
        patch("harness.cli.start.store.connect", side_effect=boom),
        patch("harness.cli.start.typer.echo") as mock_echo,
    ):
        # Best-effort: a failed rollback must NOT propagate.
        _sync(start_mod._delete_run_row(db_path, "01TESTRUNID"))

    mock_echo.assert_called_once()
    args, kwargs = mock_echo.call_args
    message = args[0]
    assert "01TESTRUNID" in message, "the warning must name the orphaned run_id"
    assert kwargs.get("err") is True, "the warning must go to stderr"
    assert "cancel" in message or "reclaim" in message, (
        "the warning must name an actionable manual remedy"
    )


def test_delete_run_row_silent_on_successful_rollback(
    repo: Path, db_path: Path
) -> None:
    """A rollback that succeeds deletes the row and emits no warning.

    Guards against over-warning: the stderr notice is for the *failed* rollback
    only, not the ordinary successful one (CAL-1007, swallow #2 boundary).
    """
    from harness.cli import start as start_mod

    async def _seed_open_run() -> None:
        await store.init_db(db_path)
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs (run_id, workflow_name, workflow_version, "
                "status, state_json, inputs_json, base_branch, worktree_path, "
                "worktree_branch, ticket, started_at) "
                "VALUES (?, '', 0, 'open', '{}', '{}', 'dev', '/wt', "
                "'harness/x', 'CAL-570', '2026-01-01T00:00:00+00:00')",
                ("01TESTRUNID",),
            )
            await conn.commit()

    _seed_open_run_result = _seed_open_run()
    _sync(_seed_open_run_result)

    with patch("harness.cli.start.typer.echo") as mock_echo:
        _sync(start_mod._delete_run_row(db_path, "01TESTRUNID"))

    mock_echo.assert_not_called()
    assert fetch_runs(db_path) == [], "the row must be deleted on a clean rollback"
