"""Tests for the shared open-run resolver ``harness.cli._runs.resolve_open_run``
(CAL-631).

``review`` and ``close`` both answer the same question — "which ``runs`` row is
the active run for this invocation?" — with the identical dispatch rule: an
explicit ``run_id`` matches ``WHERE run_id = ? AND status = 'open'``, otherwise
the run is the one whose ``worktree_path`` equals the resolved repo. The
``status = 'open'`` filter is load-bearing — the close gate trusts that a verb
only ever acts on a live run. These tests lock the one shared implementation
directly, so the rule cannot drift between the two verbs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from harness.cli._runs import resolve_open_run
from harness.state import store

RUN_ID = "01JRUNRESOLVEXXXXXXXXXXX01"


def _sync(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _seed_run(
    db_path: Path,
    repo: Path,
    *,
    status: str = "open",
    run_id: str = RUN_ID,
) -> str:
    """Insert a ``runs`` row whose ``worktree_path == repo`` with ``status``."""

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
                    status,
                    "{}",
                    "{}",
                    "dev",
                    str(repo),
                    f"harness/{run_id}",
                    "CAL-631",
                    "2026-06-12T00:00:00Z",
                    1234,
                ),
            )
            await conn.commit()

    _sync(_insert())
    return run_id


def test_resolves_open_run_by_explicit_run_id(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    repo = tmp_path / "repo"
    repo.mkdir()
    run_id = _seed_run(db_path, repo)

    resolved = _sync(resolve_open_run(db_path, repo, run_id))

    assert resolved == (run_id, str(repo), "dev", f"harness/{run_id}")


def test_resolves_open_run_by_worktree_path_when_no_run_id(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    repo = tmp_path / "repo"
    repo.mkdir()
    run_id = _seed_run(db_path, repo)

    resolved = _sync(resolve_open_run(db_path, repo, None))

    assert resolved == (run_id, str(repo), "dev", f"harness/{run_id}")


def test_closed_run_is_not_resolved(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    repo = tmp_path / "repo"
    repo.mkdir()
    run_id = _seed_run(db_path, repo, status="closed")

    # Neither dispatch path may return a non-open run: the gate trusts this filter.
    assert _sync(resolve_open_run(db_path, repo, run_id)) is None
    assert _sync(resolve_open_run(db_path, repo, None)) is None


def test_no_matching_run_returns_none(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_run(db_path, repo)

    assert _sync(resolve_open_run(db_path, repo, "01JOTHERRUNIDXXXXXXXXXXX99")) is None
    other_repo = tmp_path / "elsewhere"
    other_repo.mkdir()
    assert _sync(resolve_open_run(db_path, other_repo, None)) is None


def test_missing_db_returns_none(tmp_path: Path) -> None:
    db_path = tmp_path / "does-not-exist.db"
    repo = tmp_path / "repo"
    repo.mkdir()

    assert _sync(resolve_open_run(db_path, repo, None)) is None
