"""Tests for harness CLI read-side query commands — see SPEC §11.

Covers:
    harness status <run-id>          [--json]
    harness logs   <run-id>          [--follow] [--node <id>]
    harness events <run-id>          [--type <event_type>] [--json]
    harness worktrees list           [--json]
    harness worktrees cleanup        [--age <duration>] [--merged]
    harness validate <workflow.yaml>
    harness version                  [--json]

All write paths are deferred — these tests cover the read surface and the
``validate`` static check only. The CLI is invoked via Typer's
:class:`CliRunner` so we get stable exit codes and captured stdout.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import textwrap
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from harness.cli import app
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
    assert "slate-harness" in result.stdout


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
    assert "feature" in out
    assert "completed" in out
    assert "2026-05-08T12:00:00Z" in out
    assert "2026-05-08T12:30:00Z" in out
    # exit_code 0 must appear somewhere recognisable.
    assert "0" in out


def test_status_json_returns_full_row(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    _seed_run(
        db_path,
        run_id="R-json",
        workflow_name="bugfix",
        workflow_version=2,
        status="failed",
        state_json='{"k": "v"}',
        inputs_json='{"linear": "CAL-1"}',
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
    assert payload["inputs"] == {"linear": "CAL-1"}


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


# ---------------------------------------------------------------------------
# harness validate <workflow.yaml>
# ---------------------------------------------------------------------------


def test_validate_known_good_workflow_prints_ok(tmp_path: Path) -> None:
    workflow_yaml = tmp_path / "workflows" / "demo.yaml"
    workflow_yaml.parent.mkdir(parents=True, exist_ok=True)
    workflow_yaml.write_text(textwrap.dedent("""\
        name: demo
        version: 1
        description: demo
        steps:
          - id: hello
            type: check
            expr: "1 + 1 == 2"
    """))
    result = runner.invoke(app, ["validate", str(workflow_yaml)])
    assert result.exit_code == 0, result.stdout
    assert "OK" in result.stdout
    assert "demo" in result.stdout
    assert "1" in result.stdout


def test_validate_invalid_workflow_exits_2(tmp_path: Path) -> None:
    workflow_yaml = tmp_path / "workflows" / "bad.yaml"
    workflow_yaml.parent.mkdir(parents=True, exist_ok=True)
    workflow_yaml.write_text("this: is: not: valid\n")
    result = runner.invoke(app, ["validate", str(workflow_yaml)])
    assert result.exit_code == 2


def test_validate_missing_file_exits_2(tmp_path: Path) -> None:
    workflow_yaml = tmp_path / "absent.yaml"
    result = runner.invoke(app, ["validate", str(workflow_yaml)])
    assert result.exit_code == 2


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
    assert "slate-harness" in result.stdout


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


