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

from pathlib import Path

import pytest

from harness.cli._runs import LedgerNotFoundError, resolve_open_run
from harness.state import store
from tests._asyncutil import run_sync

RUN_ID = "01JRUNRESOLVEXXXXXXXXXXX01"


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

    run_sync(_insert())
    return run_id


def test_resolves_open_run_by_explicit_run_id(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    repo = tmp_path / "repo"
    repo.mkdir()
    run_id = _seed_run(db_path, repo)

    resolved = run_sync(resolve_open_run(db_path, repo, run_id))

    assert resolved == (run_id, str(repo), "dev", f"harness/{run_id}")


def test_resolves_open_run_by_worktree_path_when_no_run_id(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    repo = tmp_path / "repo"
    repo.mkdir()
    run_id = _seed_run(db_path, repo)

    resolved = run_sync(resolve_open_run(db_path, repo, None))

    assert resolved == (run_id, str(repo), "dev", f"harness/{run_id}")


def test_closed_run_is_not_resolved(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    repo = tmp_path / "repo"
    repo.mkdir()
    run_id = _seed_run(db_path, repo, status="closed")

    # Neither dispatch path may return a non-open run: the gate trusts this filter.
    assert run_sync(resolve_open_run(db_path, repo, run_id)) is None
    assert run_sync(resolve_open_run(db_path, repo, None)) is None


def test_no_matching_run_returns_none(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_run(db_path, repo)

    assert run_sync(resolve_open_run(db_path, repo, "01JOTHERRUNIDXXXXXXXXXXX99")) is None
    other_repo = tmp_path / "elsewhere"
    other_repo.mkdir()
    assert run_sync(resolve_open_run(db_path, other_repo, None)) is None


def test_missing_ledger_raises_ledger_not_found(tmp_path: Path) -> None:
    """#244: no ledger file at all is a distinct outcome from "no open run" —
    the lookup never happened, so it must not be conflated with ``None``."""
    db_path = tmp_path / "does-not-exist.db"
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(LedgerNotFoundError) as exc:
        run_sync(resolve_open_run(db_path, repo, None))

    assert exc.value.reason == "no_ledger"
    assert exc.value.code == 2
    assert str(db_path) in exc.value.message
    assert exc.value.extra == {"ledger_path": str(db_path)}


def test_missing_ledger_creates_no_files(tmp_path: Path) -> None:
    """The refusal must not plant a ``.harness/`` directory as a side effect —
    the guard runs before ``store.connect`` would create one."""
    db_path = tmp_path / ".harness" / "harness.db"
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(LedgerNotFoundError):
        run_sync(resolve_open_run(db_path, repo, None))

    assert not (tmp_path / ".harness").exists()
