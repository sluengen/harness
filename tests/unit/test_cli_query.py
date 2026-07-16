"""Tests for harness CLI read-side query commands — see SPEC §11.

Covers:
    harness status <run-id>          [--json]
    harness logs   <run-id>          [--follow] [--node <id>]
    harness events <run-id>          [--type <event_type>] [--json]
    harness worktrees list           [--json]
    harness worktrees cleanup        [--age <duration>] [--merged]
    harness version                  [--json]

All write paths are deferred — these tests cover the read surface only. The CLI
is invoked via Typer's :class:`CliRunner` so we get stable exit codes and
captured stdout.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from harness.cli import app, query_events
from harness.state import store

runner = CliRunner()


# ---------------------------------------------------------------------------
# DB seeding helpers
#
# CLI tests run synchronously (the Typer ``CliRunner`` enters its own event
# loop via ``asyncio.run`` inside command bodies). pytest-asyncio is in
# ``auto`` mode in this repo, which means ``async def`` tests have a running
# loop — so we expose the seeders as plain sync functions that drive their
# coroutine via ``asyncio.run`` themselves.
# ---------------------------------------------------------------------------


async def _seed_run_async(
    db_path: Path,
    *,
    run_id: str,
    workflow_name: str,
    workflow_version: int,
    status: str,
    state_json: str,
    inputs_json: str,
    base_branch: str | None,
    worktree_branch: str | None,
    exit_code: int | None,
    started_at: str,
    completed_at: str | None,
    duration_ms: int | None,
) -> None:
    await store.init_db(db_path)
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, base_branch, worktree_branch, exit_code, "
            "started_at, completed_at, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                workflow_name,
                workflow_version,
                status,
                state_json,
                inputs_json,
                base_branch,
                worktree_branch,
                exit_code,
                started_at,
                completed_at,
                duration_ms,
            ),
        )
        await conn.commit()


def _run_sync(coro: Any) -> Any:
    """Run a coroutine to completion regardless of whether pytest-asyncio left
    an event loop dangling on the current thread. ``asyncio.run`` refuses to
    run when any loop is "running", so we use a fresh loop with explicit
    teardown."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _seed_run(
    db_path: Path,
    *,
    run_id: str = "R1",
    workflow_name: str = "feature",
    workflow_version: int = 1,
    status: str = "completed",
    state_json: str = "{}",
    inputs_json: str = "{}",
    base_branch: str | None = "main",
    worktree_branch: str | None = None,
    exit_code: int | None = 0,
    started_at: str = "2026-05-08T12:00:00Z",
    completed_at: str | None = "2026-05-08T12:30:00Z",
    duration_ms: int | None = 1_800_000,
) -> None:
    _run_sync(
        _seed_run_async(
            db_path,
            run_id=run_id,
            workflow_name=workflow_name,
            workflow_version=workflow_version,
            status=status,
            state_json=state_json,
            inputs_json=inputs_json,
            base_branch=base_branch,
            worktree_branch=worktree_branch,
            exit_code=exit_code,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
        )
    )


async def _seed_event_async(
    db_path: Path,
    *,
    run_id: str,
    node_id: str | None,
    event_type: str,
    timestamp: str,
    duration_ms: int | None,
    data: dict[str, Any] | None,
) -> None:
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO events (run_id, node_id, event_type, timestamp, "
            "duration_ms, data_json) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, node_id, event_type, timestamp, duration_ms,
             json.dumps(data or {})),
        )
        await conn.commit()


def _seed_event(
    db_path: Path,
    *,
    run_id: str = "R1",
    node_id: str | None = None,
    event_type: str = "workflow_started",
    timestamp: str | None = None,
    duration_ms: int | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    _run_sync(
        _seed_event_async(
            db_path,
            run_id=run_id,
            node_id=node_id,
            event_type=event_type,
            timestamp=timestamp or "2026-05-08T12:00:00Z",
            duration_ms=duration_ms,
            data=data,
        )
    )


def _init_db(db_path: Path) -> None:
    _run_sync(store.init_db(db_path))


# ---------------------------------------------------------------------------
# harness version  — existing command, confirm both forms
# ---------------------------------------------------------------------------


def test_version_human_form_prints_slate_harness() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "harness" in result.stdout


def test_version_json_form_emits_version_key() -> None:
    result = runner.invoke(app, ["version", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "version" in payload
    assert isinstance(payload["version"], str)


# ---------------------------------------------------------------------------
# harness status <run-id>  [--json]
# ---------------------------------------------------------------------------


def test_status_prints_summary_for_known_run(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(
        db_path,
        run_id="R1",
        workflow_name="feature",
        status="completed",
        started_at="2026-05-08T12:00:00Z",
        completed_at="2026-05-08T12:30:00Z",
        exit_code=0,
    )
    result = runner.invoke(app, ["status", "R1", "--db", str(db_path)])
    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert "R1" in out
    assert "completed" in out
    assert "2026-05-08T12:00:00Z" in out
    assert "2026-05-08T12:30:00Z" in out
    # exit_code 0 must appear somewhere recognisable.
    assert "0" in out
    # The engine-era workflow fields are always empty (CAL-574 retired the
    # engine); the human form no longer echoes them (CAL-1107 item 2).
    assert "workflow_name" not in out
    assert "workflow_version" not in out


def test_status_json_returns_full_row(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(
        db_path,
        run_id="R-json",
        workflow_name="bugfix",
        workflow_version=2,
        status="failed",
        state_json='{"k": "v"}',
        inputs_json='{"linear": "PROJ-1"}',
        base_branch="staging",
        worktree_branch="harness/R-json",
        exit_code=1,
        duration_ms=12_345,
    )
    result = runner.invoke(app, ["status", "R-json", "--db", str(db_path), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["run_id"] == "R-json"
    assert payload["workflow_name"] == "bugfix"
    assert payload["workflow_version"] == 2
    assert payload["status"] == "failed"
    assert payload["base_branch"] == "staging"
    assert payload["worktree_branch"] == "harness/R-json"
    assert payload["exit_code"] == 1
    assert payload["started_at"] == "2026-05-08T12:00:00Z"
    assert payload["completed_at"] == "2026-05-08T12:30:00Z"
    assert payload["duration_ms"] == 12_345
    # state_json + inputs_json round-trip as parsed objects (not raw strings).
    assert payload["state"] == {"k": "v"}
    assert payload["inputs"] == {"linear": "PROJ-1"}


def test_status_unknown_run_exits_2(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    _init_db(db_path)
    result = runner.invoke(app, ["status", "missing", "--db", str(db_path)])
    assert result.exit_code == 2
    # Error message includes the offending id so users can see what they asked
    # for; Typer routes stderr-style errors through .stdout in CliRunner.
    combined = result.stdout + (result.stderr or "")
    assert "missing" in combined


# ---------------------------------------------------------------------------
# harness logs <run-id>  [--node <id>]  [--follow]
# ---------------------------------------------------------------------------


def test_logs_prints_timeline_in_order(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="R1")
    _seed_event(
        db_path, run_id="R1", event_type="workflow_started",
        timestamp="2026-05-08T12:00:00Z",
    )
    _seed_event(
        db_path, run_id="R1", event_type="node_started", node_id="step-a",
        timestamp="2026-05-08T12:00:01Z",
    )
    _seed_event(
        db_path, run_id="R1", event_type="node_completed", node_id="step-a",
        timestamp="2026-05-08T12:00:02Z",
    )

    result = runner.invoke(app, ["logs", "R1", "--db", str(db_path)])
    assert result.exit_code == 0, result.stdout
    out = result.stdout
    # All three events surface in their seeded order.
    idx_ws = out.find("workflow_started")
    idx_ns = out.find("node_started")
    idx_nc = out.find("node_completed")
    assert -1 < idx_ws < idx_ns < idx_nc
    assert "step-a" in out


def test_logs_node_filter_only_shows_matching_node(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="R1")
    _seed_event(
        db_path, run_id="R1", event_type="workflow_started",
        timestamp="2026-05-08T12:00:00Z",
    )
    _seed_event(
        db_path, run_id="R1", event_type="node_started", node_id="step-a",
        timestamp="2026-05-08T12:00:01Z",
    )
    _seed_event(
        db_path, run_id="R1", event_type="node_started", node_id="step-b",
        timestamp="2026-05-08T12:00:02Z",
    )

    result = runner.invoke(
        app, ["logs", "R1", "--db", str(db_path), "--node", "step-a"]
    )
    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert "step-a" in out
    assert "step-b" not in out
    # workflow_started has no node_id, so the filter excludes it too.
    assert "workflow_started" not in out


def test_logs_unknown_run_exits_2(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    _init_db(db_path)
    result = runner.invoke(app, ["logs", "ghost", "--db", str(db_path)])
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# harness events <run-id>  [--type ...]  [--json]
# ---------------------------------------------------------------------------


def test_events_json_emits_one_json_per_line(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="R1")
    _seed_event(
        db_path, run_id="R1", event_type="workflow_started",
        timestamp="2026-05-08T12:00:00Z",
    )
    _seed_event(
        db_path, run_id="R1", event_type="node_started", node_id="s1",
        timestamp="2026-05-08T12:00:01Z", data={"x": 1},
    )

    result = runner.invoke(
        app, ["events", "R1", "--db", str(db_path), "--json"]
    )
    assert result.exit_code == 0, result.stdout
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 2
    e0 = json.loads(lines[0])
    e1 = json.loads(lines[1])
    assert e0["event_type"] == "workflow_started"
    assert e0["run_id"] == "R1"
    assert e1["event_type"] == "node_started"
    assert e1["node_id"] == "s1"
    assert e1["data"] == {"x": 1}


def test_events_type_filter_excludes_other_types(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="R1")
    _seed_event(
        db_path, run_id="R1", event_type="workflow_started",
        timestamp="2026-05-08T12:00:00Z",
    )
    _seed_event(
        db_path, run_id="R1", event_type="node_started", node_id="s1",
        timestamp="2026-05-08T12:00:01Z",
    )
    _seed_event(
        db_path, run_id="R1", event_type="tool_called", node_id="s1",
        timestamp="2026-05-08T12:00:02Z",
    )

    result = runner.invoke(
        app, ["events", "R1", "--db", str(db_path), "--json",
              "--type", "tool_called"]
    )
    assert result.exit_code == 0, result.stdout
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["event_type"] == "tool_called"


def test_events_human_form_compact(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="R1")
    _seed_event(
        db_path, run_id="R1", event_type="workflow_started",
        timestamp="2026-05-08T12:00:00Z",
    )

    result = runner.invoke(app, ["events", "R1", "--db", str(db_path)])
    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert "workflow_started" in out
    assert "2026-05-08T12:00:00Z" in out


def test_events_unknown_run_exits_2(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    _init_db(db_path)
    result = runner.invoke(app, ["events", "missing", "--db", str(db_path)])
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# harness worktrees list  [--json]
# ---------------------------------------------------------------------------


def _make_worktree_dir(repo_root: Path, run_id: str) -> Path:
    """Create a ``.worktrees/harness/<run_id>/`` directory with a stub branch
    name file. The CLI reads either the on-disk listing or
    ``git worktree list`` — for unit tests, the on-disk side is enough.
    """
    wt = repo_root / ".worktrees" / "harness" / run_id
    wt.mkdir(parents=True, exist_ok=True)
    return wt


def test_worktrees_list_returns_empty_when_directory_missing(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path
    result = runner.invoke(
        app, ["worktrees", "list", "--repo-root", str(repo_root), "--json"]
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout or "[]")
    assert payload == []


def test_worktrees_list_finds_worktree_dirs(tmp_path: Path) -> None:
    repo_root = tmp_path
    _make_worktree_dir(repo_root, "R1")
    _make_worktree_dir(repo_root, "R2")
    result = runner.invoke(
        app, ["worktrees", "list", "--repo-root", str(repo_root), "--json"]
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    ids = sorted(item["run_id"] for item in payload)
    assert ids == ["R1", "R2"]
    # Each entry exposes path + last_modified at minimum.
    for item in payload:
        assert "path" in item
        assert "last_modified" in item


def test_worktrees_list_human_form_prints_paths(tmp_path: Path) -> None:
    repo_root = tmp_path
    _make_worktree_dir(repo_root, "R1")
    result = runner.invoke(
        app, ["worktrees", "list", "--repo-root", str(repo_root)]
    )
    assert result.exit_code == 0, result.stdout
    assert "R1" in result.stdout


# ---------------------------------------------------------------------------
# harness worktrees cleanup  [--age <duration>] [--merged]
# ---------------------------------------------------------------------------


def test_worktrees_cleanup_age_removes_old(tmp_path: Path) -> None:
    """A worktree directory whose mtime is older than ``--age`` is removed."""
    repo_root = tmp_path
    # Real git repo (cleanup invokes `git worktree remove`).
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(repo_root)], check=True
    )
    # Set a committer to avoid environment-dependent failures.
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.email", "t@t"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.name", "t"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "--allow-empty",
         "-q", "-m", "init"], check=True
    )

    # Create a real worktree via git so cleanup can remove it cleanly.
    wt_old_path = repo_root / ".worktrees" / "harness" / "R-old"
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", "-b",
         "harness/R-old", str(wt_old_path)],
        check=True,
    )
    # Backdate the worktree directory mtime by two days.
    old_time = (datetime.now(UTC) - timedelta(days=2)).timestamp()
    import os
    os.utime(wt_old_path, (old_time, old_time))

    wt_new_path = repo_root / ".worktrees" / "harness" / "R-new"
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", "-b",
         "harness/R-new", str(wt_new_path)],
        check=True,
    )

    result = runner.invoke(
        app,
        ["worktrees", "cleanup", "--repo-root", str(repo_root), "--age", "1d"],
    )
    assert result.exit_code == 0, result.stdout
    assert not wt_old_path.exists()
    assert wt_new_path.exists()
    # The CLI reports what it removed.
    assert "R-old" in result.stdout


def test_worktrees_cleanup_no_filter_removes_nothing(tmp_path: Path) -> None:
    """Without filters the cleanup is a no-op. It must not delete worktrees
    blindly."""
    repo_root = tmp_path
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(repo_root)], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.email", "t@t"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.name", "t"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "--allow-empty",
         "-q", "-m", "init"], check=True
    )
    wt = repo_root / ".worktrees" / "harness" / "R1"
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", "-b",
         "harness/R1", str(wt)], check=True,
    )

    result = runner.invoke(
        app, ["worktrees", "cleanup", "--repo-root", str(repo_root)]
    )
    # Exit 0 (nothing to do) — the worktree survives.
    assert result.exit_code == 0, result.stdout
    assert wt.exists()


def test_worktrees_cleanup_merged_removes_branch_merged_into_dev(
    tmp_path: Path,
) -> None:
    """``--merged`` treats a branch merged into ``dev`` as a removal candidate.

    With no CONTEXT.md configuring a branch model, ``resolve_base_branch`` falls
    back to ``dev`` (this repo's integration branch), so a worktree whose branch
    has landed on ``dev`` (the common case) must be cleaned up. The configured
    non-``dev`` case is locked by
    ``test_worktrees_cleanup_merged_uses_configured_base`` (CAL-1106).
    """
    repo_root = tmp_path
    subprocess.run(
        ["git", "init", "-q", "-b", "dev", str(repo_root)], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.email", "t@t"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.name", "t"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "--allow-empty",
         "-q", "-m", "init"], check=True
    )
    # A worktree whose branch points at the same commit as dev is "merged".
    wt = repo_root / ".worktrees" / "harness" / "R-merged"
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add",
         "-b", "harness/R-merged", str(wt)],
        check=True,
    )

    result = runner.invoke(
        app,
        ["worktrees", "cleanup", "--repo-root", str(repo_root), "--merged"],
    )
    assert result.exit_code == 0, result.stdout
    assert not wt.exists()
    assert "R-merged" in result.stdout
    # CAL-767: --merged also deletes the merged branch (it is provably integrated).
    branches = subprocess.run(
        ["git", "-C", str(repo_root), "branch", "--format=%(refname:short)"],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    assert "harness/R-merged" not in branches


def test_worktrees_cleanup_merged_deletes_remote_branch(tmp_path: Path) -> None:
    """CAL-767: ``--merged`` deletes the branch on ``origin`` too — a checkpoint
    push may have created it, and once merged it is dead weight."""
    repo_root = tmp_path / "repo"
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "dev", str(repo_root)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(repo_root), "config", k, v], check=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "--allow-empty", "-q", "-m", "init"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "remote", "add", "origin", str(bare)], check=True
    )
    wt = repo_root / ".worktrees" / "harness" / "R-pushed"
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", "-b",
         "harness/R-pushed", str(wt)], check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "push", "-q", "origin", "harness/R-pushed"],
        check=True,
    )

    result = runner.invoke(
        app, ["worktrees", "cleanup", "--repo-root", str(repo_root), "--merged"]
    )
    assert result.exit_code == 0, result.stdout
    assert not wt.exists()
    remote_refs = subprocess.run(
        ["git", "-C", str(repo_root), "ls-remote", "--heads", "origin", "harness/R-pushed"],
        check=True, capture_output=True, text=True,
    ).stdout
    assert "harness/R-pushed" not in remote_refs


def test_worktrees_cleanup_merged_uses_configured_base(tmp_path: Path) -> None:
    """CAL-1106: ``--merged`` reclaims a branch merged into the repo's *configured*
    integration branch, not just the literal ``dev``/``main``/``master`` set.

    A ``trunk``-based repo — whose branch names are absent from the old hardcoded
    set — must still have its merged worktrees reclaimed once CONTEXT.md declares
    ``branches.integration: trunk``.
    """
    repo_root = tmp_path
    subprocess.run(["git", "init", "-q", "-b", "trunk", str(repo_root)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(repo_root), "config", k, v], check=True)
    (repo_root / "CONTEXT.md").write_text("branches:\n  integration: trunk\n")
    subprocess.run(
        ["git", "-C", str(repo_root), "add", "-A"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-q", "-m", "init"], check=True
    )
    wt = repo_root / ".worktrees" / "harness" / "R-trunk"
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", "-b",
         "harness/R-trunk", str(wt)],
        check=True,
    )

    result = runner.invoke(
        app, ["worktrees", "cleanup", "--repo-root", str(repo_root), "--merged"]
    )
    assert result.exit_code == 0, result.stdout
    assert not wt.exists()
    assert "R-trunk" in result.stdout


def test_worktrees_cleanup_age_removes_orphaned_dir(tmp_path: Path) -> None:
    """CAL-767: an orphaned directory (never/no-longer a registered worktree, so
    ``git worktree remove`` errors on it) is still reclaimed by ``--age`` via the
    rmtree fallback. This is the GB-of-cruft case that accumulated."""
    import os

    repo_root = tmp_path
    subprocess.run(["git", "init", "-q", "-b", "dev", str(repo_root)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(repo_root), "config", k, v], check=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "--allow-empty", "-q", "-m", "init"],
        check=True,
    )
    orphan = repo_root / ".worktrees" / "harness" / "R-orphan"
    orphan.mkdir(parents=True)
    (orphan / "leftover.txt").write_text("cruft\n")
    old = (datetime.now(UTC) - timedelta(days=2)).timestamp()
    os.utime(orphan, (old, old))

    result = runner.invoke(
        app, ["worktrees", "cleanup", "--repo-root", str(repo_root), "--age", "1d"]
    )
    assert result.exit_code == 0, result.stdout
    assert not orphan.exists()
    assert "R-orphan" in result.stdout


def test_worktrees_cleanup_help_lists_all_merge_bases() -> None:
    """The ``--merged`` help text must match the real check, not just ``main``.

    The implementation tests the branch against ``dev``, ``main``, and
    ``master``; the user-facing help must not understate that to ``main`` alone.
    """
    result = runner.invoke(app, ["worktrees", "cleanup", "--help"])
    assert result.exit_code == 0, result.stdout
    assert "dev" in result.stdout


# ---------------------------------------------------------------------------
# Subprocess smoke — the entrypoint still wires up under `python -m harness.cli`
# ---------------------------------------------------------------------------


def test_cli_module_entrypoint_still_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "version"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0
    assert "harness" in result.stdout


# ---------------------------------------------------------------------------
# logs --follow — exits cleanly when run is terminal
# ---------------------------------------------------------------------------


def test_logs_follow_exits_when_run_is_terminal(tmp_path: Path) -> None:
    """``--follow`` polls until the run's status is terminal, then exits."""
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="R1", status="completed")
    _seed_event(
        db_path, run_id="R1", event_type="workflow_started",
        timestamp="2026-05-08T12:00:00Z",
    )
    _seed_event(
        db_path, run_id="R1", event_type="workflow_completed",
        timestamp="2026-05-08T12:30:00Z",
    )
    start = time.monotonic()
    result = runner.invoke(
        app, ["logs", "R1", "--db", str(db_path), "--follow"]
    )
    elapsed = time.monotonic() - start
    assert result.exit_code == 0, result.stdout
    # Should exit promptly once it sees a terminal state on the first poll.
    assert elapsed < 5.0
    assert "workflow_started" in result.stdout
    assert "workflow_completed" in result.stdout


def test_logs_follow_tails_open_run_until_closed(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """``--follow`` keeps polling while a run is ``open`` (the verb model's live
    status) and tails events that arrive across polls, exiting only once the run
    becomes ``closed``.

    Regression for CAL-640: ``_IN_PROGRESS_STATUSES`` was the retired engine's
    ``{"pending", "running"}`` and omitted ``open``, so the first poll saw a
    live run as terminal and the loop returned after one pass — ``--follow``
    never tailed any live run. This test seeds an ``open`` run with one event,
    lands a second event mid-follow, then closes the run; it fails against the
    engine-era set (the second event is never tailed and the loop polls once)
    and passes once ``open`` is in the in-progress set.
    """
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="R1", status="open")
    _seed_event(
        db_path, run_id="R1", event_type="workflow_started",
        timestamp="2026-05-08T12:00:00Z",
    )

    # Drive the loop deterministically: no real sleeping between polls.
    monkeypatch.setattr(query_events, "_FOLLOW_POLL_INTERVAL_SECONDS", 0)

    # Drive the run's lifecycle through the status polls. On the first poll the
    # run is still ``open`` and a second event lands; on the second poll it has
    # ``closed`` so the loop exits. Events are fetched before the status check,
    # so the second event must arrive while the loop still believes the run is
    # live for it to be tailed — exactly what the bug prevented.
    calls = {"n": 0}

    async def fake_fetch_status(db: Path, run_id: str) -> str | None:
        calls["n"] += 1
        if calls["n"] == 1:
            # Land a second event mid-follow, on the loop's own event loop (the
            # sync seeder would spin up a nested loop and fail). Insert it before
            # reporting the run still ``open`` so the next poll can tail it.
            await _seed_event_async(
                db_path, run_id="R1", node_id=None,
                event_type="workflow_completed",
                timestamp="2026-05-08T12:30:00Z",
                duration_ms=None, data=None,
            )
            return "open"
        return "closed"

    monkeypatch.setattr(query_events, "_fetch_status", fake_fetch_status)

    result = runner.invoke(
        app, ["logs", "R1", "--db", str(db_path), "--follow"]
    )
    assert result.exit_code == 0, result.stdout
    # The loop polled past the first ``open`` status instead of exiting on it.
    assert calls["n"] >= 2, (
        f"follow exited after {calls['n']} poll(s) — it treated `open` as "
        "terminal and never tailed the live run"
    )
    # Both the initial event and the one that arrived mid-follow are tailed.
    assert "workflow_started" in result.stdout
    assert "workflow_completed" in result.stdout


# ---------------------------------------------------------------------------
# DB resolution — the `--db` flag is honoured everywhere (sanity)
# ---------------------------------------------------------------------------


def test_db_flag_overrides_default(tmp_path: Path) -> None:
    """Confirm read commands consult ``--db`` and not the cwd-relative
    default. This is the test that pins the contract; the implementation
    must accept ``--db`` on every read command."""
    db_path = tmp_path / "alt.db"
    _seed_run(db_path, run_id="ALT1")
    result = runner.invoke(app, ["status", "ALT1", "--db", str(db_path)])
    assert result.exit_code == 0, result.stdout


# ---------------------------------------------------------------------------
# harness status --json: enriched fields (failure_reason, artifact_paths)
#
# The live DB→status wiring (a ``workflow_failed`` event surfacing as
# ``failure_reason``) is covered end-to-end by
# ``test_cancel_surfaces_failure_reason_in_status`` in ``test_cli_cancel.py`` —
# ``harness cancel`` is the sole live emitter of ``workflow_failed``. We do not
# manufacture synthetic ``workflow_failed`` events here (that was the CODE-4 /
# CAL-589 false-green pattern).
# ---------------------------------------------------------------------------


def test_status_json_omits_current_node(tmp_path: Path) -> None:
    """``current_node`` is no longer emitted (CAL-589).

    It derived from ``node_started``, which only the engine retired in CAL-574
    ever emitted — always ``null`` under the verb model. This locks its removal:
    the field must be absent from the ``status --json`` payload (this test fails
    against the parent implementation, which still emitted it).
    """
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="R1", status="running")

    result = runner.invoke(app, ["status", "R1", "--db", str(db_path), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert "current_node" not in payload


def test_status_json_failure_reason_none_when_no_failure(tmp_path: Path) -> None:
    """``failure_reason`` is None for a run that has not failed."""
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="R1", status="completed", exit_code=0)

    result = runner.invoke(app, ["status", "R1", "--db", str(db_path), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["failure_reason"] is None


def test_status_json_artifact_paths_populated_from_state(tmp_path: Path) -> None:
    """``artifact_paths`` surfaces non-None artifact fields from ``state``.

    Only schema-declared artifact fields are injected — ``BaseState`` forbids
    extra keys, so a real ``state`` blob can never carry anything else (guarded
    by ``test_artifact_keys_are_declared_state_fields``).
    """
    db_path = tmp_path / ".harness" / "harness.db"
    state = {
        "run_id": "R1", "workflow_name": "build", "base_branch": "main",
        "artifacts_dir": "/tmp/arts", "started_at": "2026-05-08T12:00:00Z",
        "notes": [], "worktree_path": None,
        "worktree_branch": "harness/R1",
    }
    _seed_run(db_path, run_id="R1", status="completed",
              state_json=json.dumps(state))

    result = runner.invoke(app, ["status", "R1", "--db", str(db_path), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["artifact_paths"] is not None
    assert payload["artifact_paths"]["worktree_branch"] == "harness/R1"
    # worktree_path is None in state, so it must not appear.
    assert "worktree_path" not in payload["artifact_paths"]


def test_status_json_artifact_paths_none_when_no_artifacts(tmp_path: Path) -> None:
    """``artifact_paths`` is None when state has no artifact fields set."""
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="R1", status="running", state_json="{}")

    result = runner.invoke(app, ["status", "R1", "--db", str(db_path), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["artifact_paths"] is None


# ---------------------------------------------------------------------------
# harness events --after-id  (incremental polling)
# ---------------------------------------------------------------------------


def test_events_after_id_returns_only_newer_events(tmp_path: Path) -> None:
    """``--after-id N`` returns only events with row id > N."""
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="R1")
    _seed_event(db_path, run_id="R1", event_type="workflow_started",
                timestamp="2026-05-08T12:00:00Z")
    _seed_event(db_path, run_id="R1", event_type="node_started", node_id="s1",
                timestamp="2026-05-08T12:00:01Z")
    _seed_event(db_path, run_id="R1", event_type="node_completed", node_id="s1",
                timestamp="2026-05-08T12:00:02Z")

    # Fetch all events once to discover their IDs.
    all_result = runner.invoke(app, ["events", "R1", "--db", str(db_path), "--json"])
    assert all_result.exit_code == 0
    all_lines = [ln for ln in all_result.stdout.splitlines() if ln.strip()]
    assert len(all_lines) == 3
    first_id = json.loads(all_lines[0])["id"]

    # --after-id first_id should return only the two events after the first.
    incremental_result = runner.invoke(
        app, ["events", "R1", "--db", str(db_path), "--json",
              "--after-id", str(first_id)]
    )
    assert incremental_result.exit_code == 0, incremental_result.stdout
    inc_lines = [ln for ln in incremental_result.stdout.splitlines() if ln.strip()]
    assert len(inc_lines) == 2
    types = [json.loads(ln)["event_type"] for ln in inc_lines]
    assert types == ["node_started", "node_completed"]


def test_events_after_id_zero_returns_all_events(tmp_path: Path) -> None:
    """``--after-id 0`` (the default) returns all events."""
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="R1")
    _seed_event(db_path, run_id="R1", event_type="workflow_started",
                timestamp="2026-05-08T12:00:00Z")
    _seed_event(db_path, run_id="R1", event_type="workflow_completed",
                timestamp="2026-05-08T12:30:00Z")

    result = runner.invoke(
        app, ["events", "R1", "--db", str(db_path), "--json", "--after-id", "0"]
    )
    assert result.exit_code == 0, result.stdout
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 2


def test_events_after_id_past_last_returns_empty(tmp_path: Path) -> None:
    """``--after-id`` larger than all event IDs returns no events."""
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(db_path, run_id="R1")
    _seed_event(db_path, run_id="R1", event_type="workflow_started",
                timestamp="2026-05-08T12:00:00Z")

    result = runner.invoke(
        app, ["events", "R1", "--db", str(db_path), "--json", "--after-id", "9999"]
    )
    assert result.exit_code == 0, result.stdout
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 0



def _db_help_text(command: str) -> str:
    """Return the ``--help`` output for ``command`` with ANSI colour codes and
    rich box-drawing borders stripped and whitespace collapsed, so an option's
    help string can be matched without caring how the renderer wrapped *or
    coloured* it across lines.

    CI renders help with colour at 80 cols (``FORCE_COLOR``); the ANSI SGR codes
    then interleave the help text, so they must be stripped before matching —
    otherwise a contiguous-substring check passes locally (no colour) but fails
    on CI (CAL-751)."""
    out = runner.invoke(app, [command, "--help"]).stdout
    out = re.sub(r"\x1b\[[0-9;]*m", "", out)  # strip ANSI SGR colour codes
    return re.sub(r"\s+", " ", re.sub(r"[│|]", " ", out))


def test_events_db_help_documents_default(tmp_path: Path) -> None:
    """``events --help`` documents the ``--db`` default like its siblings.

    Every read-side command resolves ``--db`` through the same
    ``_resolve_db_path`` default (``$cwd/.harness/harness.db``); the help text
    must say so, as ``status``/``runs``/``doctor`` already do.
    """
    assert (
        "Path to harness.db (defaults to .harness/harness.db)"
        in _db_help_text("events")
    )


def test_logs_db_help_documents_default(tmp_path: Path) -> None:
    """``logs --help`` documents the ``--db`` default, matching its siblings."""
    assert (
        "Path to harness.db (defaults to .harness/harness.db)"
        in _db_help_text("logs")
    )
