"""#353 — ``harness start`` persists the boundary the trivial classifier diffs from.

The classifier must judge a run on *the diff ``close`` will merge*. That diff is
``base_sha...HEAD`` where ``base_sha`` is the run's **merge target** at ``start``,
and the distinction from the worktree's *start point* is the load-bearing part:
for a clean start the two coincide, but a ``--resume`` starts the worktree at the
recovered WIP tip, which already carries the dead run's commits. Anchoring to the
start point would classify only what the new run added while ``close`` merged the
lot — so the resume case gets its own test, and it is the one that fails if
someone "simplifies" the capture to reuse ``start_point``.

The reader's failure directions live here too, because every one of them answers
``None`` and ``None`` means *ineligible* — a damaged or absent boundary can only
make a run more verified, never less.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli._runs import read_run_base_sha
from harness.state import store
from tests._asyncutil import run_sync
from tests._ledger import seed_premigration_ledger

cli_runner = CliRunner()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


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


def _stub(*, resume_branch: str | None = None) -> MagicMock:
    ticket: dict[str, Any] = {
        "id": "abc-123-uuid",
        "identifier": "353",
        "title": "certify eligible trivial diffs",
        "description": "Body.",
        "url": "https://github.com/sluengen/harness/issues/353",
        "labels": [],
    }
    mock = MagicMock()
    mock.fetch_issue = AsyncMock(return_value=ticket)
    mock.transition_to_in_progress = AsyncMock(return_value=None)
    mock.fetch_resume_branch = AsyncMock(return_value=resume_branch)
    mock.fetch_handoff_branch = AsyncMock(return_value=None)
    return mock


def _start(repo: Path, db_path: Path, stub: MagicMock, *args: str) -> Any:
    with (
        patch("harness.tracker.LinearClient", return_value=stub),
        patch("harness.tracker.linear_api_key", return_value="test-key"),
    ):
        return cli_runner.invoke(
            app,
            ["start", "353", "--repo", str(repo), "--db", str(db_path), *args],
        )


def _only_run_id(db_path: Path) -> str:
    async def _read() -> str:
        async with (
            store.connect(db_path) as conn,
            conn.execute("SELECT run_id FROM runs") as cur,
        ):
            rows = await cur.fetchall()
        assert len(rows) == 1, f"expected exactly one run row, got {rows!r}"
        return str(rows[0][0])

    return run_sync(_read())


def _worktree_start_sha(db_path: Path, repo: Path) -> str:
    async def _read() -> str:
        async with (
            store.connect(db_path) as conn,
            conn.execute("SELECT worktree_path FROM runs") as cur,
        ):
            rows = await cur.fetchall()
        return str(rows[0][0])

    return _git(Path(run_sync(_read())), "rev-parse", "HEAD")


# ---------------------------------------------------------------------------
# The capture
# ---------------------------------------------------------------------------


def test_start_persists_the_merge_target_sha_as_the_run_boundary(
    repo: Path, db_path: Path
) -> None:
    """A clean start records the SHA of the ref it will merge back into."""
    result = _start(repo, db_path, _stub())

    assert result.exit_code == 0, result.output
    recorded = run_sync(read_run_base_sha(db_path, _only_run_id(db_path)))
    assert recorded == _git(repo, "rev-parse", "dev")


def test_the_boundary_is_the_merge_target_not_the_resumed_start_point(
    repo: Path, db_path: Path
) -> None:
    """A ``--resume`` anchors to ``dev``, not to the recovered WIP tip.

    The WIP branch already carries the dead run's commits and ``close`` merges
    them, so a boundary taken from the worktree's start point would classify a
    resumed run on a strictly smaller diff than the one that lands. This is the
    only test that distinguishes the two; a clean start cannot, because there
    the two SHAs are equal.
    """
    _git(repo, "checkout", "-b", "wip")
    (repo / "harness" ).mkdir()
    (repo / "harness" / "leftover.py").write_text("x = 1\n")
    _git(repo, "add", "harness/leftover.py")
    _git(repo, "commit", "-m", "dead run's work")
    wip_tip = _git(repo, "rev-parse", "wip")
    _git(repo, "checkout", "dev")
    _git(repo, "remote", "add", "origin", str(repo))
    _git(repo, "fetch", "origin")

    result = _start(repo, db_path, _stub(resume_branch="wip"), "--resume")

    assert result.exit_code == 0, result.output
    dev_tip = _git(repo, "rev-parse", "dev")
    assert wip_tip != dev_tip, "the fixture must make the two boundaries differ"
    assert _worktree_start_sha(db_path, repo) == wip_tip, (
        "the fixture must actually take the resume path — otherwise this test "
        "measures a clean start and proves nothing"
    )
    recorded = run_sync(read_run_base_sha(db_path, _only_run_id(db_path)))
    assert recorded == dev_tip


# ---------------------------------------------------------------------------
# The reader's one direction
# ---------------------------------------------------------------------------


def test_a_missing_ledger_reports_no_boundary(tmp_path: Path) -> None:
    assert run_sync(read_run_base_sha(tmp_path / "absent.db", "01RUN")) is None


def test_a_run_that_is_not_there_reports_no_boundary(repo: Path, db_path: Path) -> None:
    run_sync(store.init_db(db_path))
    assert run_sync(read_run_base_sha(db_path, "01NOSUCHRUN")) is None


def test_a_row_written_before_the_migration_reports_no_boundary(
    repo: Path, db_path: Path
) -> None:
    """A ``NULL`` column is the correct answer, so no backfill is needed."""
    run_sync(store.init_db(db_path))

    async def _insert() -> None:
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
                "state_json, inputs_json, base_branch, worktree_path, worktree_branch, "
                "ticket, started_at) "
                "VALUES ('01LEGACY', '', 0, 'open', '{}', '{}', 'dev', ?, "
                "'harness/01LEGACY', '353', '2026-01-01T00:00:00Z')",
                (str(repo),),
            )
            await conn.commit()

    run_sync(_insert())
    assert run_sync(read_run_base_sha(db_path, "01LEGACY")) is None


def test_a_ledger_that_predates_the_column_reports_no_boundary(
    repo: Path, db_path: Path
) -> None:
    """The column is *absent*, not NULL — an ``OperationalError`` on read.

    ``_migrate`` runs only from ``store.init_db``, whose caller is ``start``, so
    a run opened by an older harness reaches ``certify`` against a ledger that
    has no such column. That must read as *no boundary*, not raise past the
    verb's refusal contract.
    """
    seed_premigration_ledger(
        db_path,
        run_id="01OLD",
        worktree_path=str(repo),
        ticket="353",
        started_at="2026-01-01T00:00:00Z",
    )
    assert run_sync(read_run_base_sha(db_path, "01OLD")) is None


def test_the_premigration_ledger_really_lacks_the_column(
    repo: Path, db_path: Path
) -> None:
    """The floor under the test above.

    Without it, a fixture that silently gained ``base_sha`` would turn the
    ``OperationalError`` case into an ordinary ``NULL`` read and the guard would
    keep passing while covering nothing.
    """
    seed_premigration_ledger(
        db_path,
        run_id="01OLD",
        worktree_path=str(repo),
        ticket="353",
        started_at="2026-01-01T00:00:00Z",
    )

    async def _select() -> None:
        async with aiosqlite.connect(db_path) as conn:
            await conn.execute("SELECT base_sha FROM runs")

    with pytest.raises(aiosqlite.OperationalError):
        run_sync(_select())


def test_the_migration_adds_the_column_to_an_existing_ledger(
    repo: Path, db_path: Path
) -> None:
    """``init_db`` heals a pre-#353 ledger in place, with no data loss."""
    seed_premigration_ledger(
        db_path,
        run_id="01OLD",
        worktree_path=str(repo),
        ticket="353",
        started_at="2026-01-01T00:00:00Z",
    )
    run_sync(store.init_db(db_path))

    async def _read() -> list[Any]:
        async with (
            store.connect(db_path) as conn,
            conn.execute("SELECT run_id, base_sha FROM runs") as cur,
        ):
            return list(await cur.fetchall())

    assert [tuple(r) for r in run_sync(_read())] == [("01OLD", None)]
