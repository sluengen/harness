"""Tests for ``harness close`` integrating ``origin/<base>`` before push — CAL-777.

``_merge_and_push`` used to ``checkout base → merge --no-ff run-branch → push``
with **no fetch first**. When ``origin/<base>`` advanced after ``start`` — a
concurrent ``/harness routine build`` or another session landing a ticket — the
push was rejected **non-fast-forward** and close exited 1, leaving the run open.
Observed 2026-06-18: CAL-767 landed on ``dev`` mid-CAL-764-run, so CAL-764's
close failed and had to be merged via a server-side PR.

The fix: ``close`` fetches ``origin/<base>`` and fast-forwards the local base to
it before merging the run branch, so a base that advanced with non-conflicting
changes pushes cleanly. The HEAD-bound gate is preserved — only the reviewed
SHA's commit is merged (it is the run branch tip and becomes the merge's second
parent). A genuine conflict between the run branch and the advanced base fails
cleanly with a clear message (not a raw git error), aborts the merge, and leaves
the run resumable.

These tests exercise the **real** ``_merge_and_push`` against a real bare
``origin`` (the existing ``test_cli_close.py`` mocks the merge entirely), and the
close verb end-to-end with only Linear faked.

AC-1/AC-4: origin/base advances non-conflicting after start → close completes
           (merge + push + ticket Done + run closed); origin gets the merge.
AC-2/AC-5: a conflicting advance → close refuses cleanly with a clear message,
           the run stays open, the checkout is left clean (resumable).
AC-3:      only the reviewed SHA's commit is merged (merge second parent ==
           run branch tip); no unreviewed content rides in.
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
from harness.cli.close import _CloseError, _merge_and_push
from harness.events.emitter import EventEmitter
from harness.state import store

cli_runner = CliRunner()


# ---------------------------------------------------------------------------
# git / repo helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _configure(repo: Path, name: str, email: str) -> None:
    _git(repo, "config", "user.email", email)
    _git(repo, "config", "user.name", name)


def _setup_origin_and_main(tmp_path: Path) -> tuple[Path, Path]:
    """A bare ``origin`` with a single ``dev`` commit, and a ``main`` clone of it.

    ``main`` is the checkout the close verb operates on (``repo_root``): it is on
    ``dev`` and has ``origin`` configured, exactly like the harness's working
    copy. ``.harness/`` and ``.worktrees/`` are gitignored as in the real repo so
    neither registers as a dirty worktree.
    """
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "dev", str(origin)],
        check=True,
        capture_output=True,
        text=True,
    )

    main = tmp_path / "main"
    subprocess.run(
        ["git", "clone", str(origin), str(main)],
        check=True,
        capture_output=True,
        text=True,
    )
    _configure(main, "Main", "main@example.com")
    (main / ".gitignore").write_text(".harness/\n.worktrees/\n")
    (main / "README.md").write_text("hello\n")
    _git(main, "add", ".gitignore", "README.md")
    _git(main, "commit", "-m", "initial")
    _git(main, "push", "origin", "dev")
    return origin, main


def _add_run_worktree(
    main: Path,
    run_id: str,
    *,
    filename: str,
    content: str,
) -> tuple[Path, str]:
    """Create a run worktree off ``dev`` with one committed change; return it."""
    path = main / ".worktrees" / "harness" / run_id
    branch = f"harness/{run_id}"
    _git(main, "worktree", "add", "-b", branch, str(path), "dev")
    (path / filename).write_text(content)
    _git(path, "add", filename)
    _git(path, "commit", "-m", f"work {run_id}")
    return path, branch


def _advance_origin(
    tmp_path: Path,
    origin: Path,
    *,
    filename: str,
    content: str,
    name: str = "other",
) -> str:
    """Land a commit on ``origin/dev`` from a separate clone; return its SHA.

    Models a concurrent session landing a ticket after ``start`` captured the
    base. ``filename`` distinct from the run branch's file → non-conflicting;
    the same file/lines → a merge conflict.
    """
    other = tmp_path / name
    subprocess.run(
        ["git", "clone", str(origin), str(other)],
        check=True,
        capture_output=True,
        text=True,
    )
    _configure(other, "Other", "other@example.com")
    (other / filename).write_text(content)
    _git(other, "add", filename)
    _git(other, "commit", "-m", "concurrent landing")
    _git(other, "push", "origin", "dev")
    return _git(other, "rev-parse", "HEAD").stdout.strip()


def _head(repo: Path, ref: str = "HEAD") -> str:
    return _git(repo, "rev-parse", ref).stdout.strip()


# ---------------------------------------------------------------------------
# Unit: _merge_and_push against a real advanced origin
# ---------------------------------------------------------------------------


RUN_ID = "01JRUNINTEGRATEBASE0000001"


def test_merge_and_push_integrates_advanced_origin(tmp_path: Path) -> None:
    """Origin advanced non-conflicting after start → merge/push succeeds (AC-1)."""
    origin, main = _setup_origin_and_main(tmp_path)
    _path, branch = _add_run_worktree(main, RUN_ID, filename="feature.txt", content="run work\n")
    reviewed_sha = _head(main, branch)

    # A concurrent session lands a non-conflicting change on origin/dev.
    advanced = _advance_origin(tmp_path, origin, filename="other.txt", content="other work\n")
    assert _head(main, "dev") != advanced  # local dev is now behind origin/dev

    # The real merge+push must integrate origin/dev first, so the push lands.
    _merge_and_push(repo_root=main, base_branch="dev", worktree_branch=branch)

    # origin/dev now carries BOTH the concurrent change and the run's work.
    verify = tmp_path / "verify"
    subprocess.run(
        ["git", "clone", str(origin), str(verify)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert (verify / "other.txt").exists()
    assert (verify / "feature.txt").exists()

    # AC-3: only the reviewed SHA's commit was merged — it is the merge's second
    # parent, and the advanced origin commit is reachable as the first parent.
    assert _head(main, "HEAD^2") == reviewed_sha
    assert advanced == _head(main, "HEAD^1")


def test_merge_and_push_conflict_refuses_cleanly(tmp_path: Path) -> None:
    """A genuine conflict with the advanced base → clean refusal, repo left clean (AC-2)."""
    origin, main = _setup_origin_and_main(tmp_path)
    # Run branch rewrites README's first line.
    _path, branch = _add_run_worktree(main, RUN_ID, filename="README.md", content="run line\n")
    # Concurrent landing rewrites the SAME line differently → guaranteed conflict.
    _advance_origin(tmp_path, origin, filename="README.md", content="other line\n")

    with pytest.raises(_CloseError) as excinfo:
        _merge_and_push(repo_root=main, base_branch="dev", worktree_branch=branch)

    err = excinfo.value
    assert err.code == 1
    # A clear message, not a raw git conflict dump.
    assert "conflict" in str(err).lower()
    assert "CONFLICT (content)" not in str(err)
    assert "<<<<<<<" not in str(err)

    # The merge was aborted: the checkout is clean and no merge is in progress.
    assert _git(main, "status", "--porcelain").stdout.strip() == ""
    merge_head = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", "MERGE_HEAD"],
        cwd=main, check=False, capture_output=True, text=True,
    )
    assert merge_head.returncode != 0  # no merge left in progress


# ---------------------------------------------------------------------------
# Close verb end-to-end with a real merge (only Linear faked)
# ---------------------------------------------------------------------------


def _sync(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _seed_open_run(
    db_path: Path,
    worktree_path: Path,
    branch: str,
    run_id: str = RUN_ID,
    ticket: str = "CAL-572",
) -> None:
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
                    run_id, "", 0, "open", "{}", "{}", "dev",
                    str(worktree_path), branch, ticket, "2026-06-18T00:00:00Z", 1234,
                ),
            )
            await conn.commit()

    _sync(_insert())


def _emit_pass(db_path: Path, run_id: str, reviewed_sha: str) -> None:
    async def _emit() -> None:
        await EventEmitter(db_path).emit(
            run_id=run_id,
            event_type="review",
            data={
                "run_id": run_id,
                "reviewed_sha": reviewed_sha,
                "verdict": "pass",
                "issues": [],
                "created_at": "2026-06-18T00:00:00Z",
            },
        )

    _sync(_emit())


def _run_status(db_path: Path, run_id: str) -> str | None:
    async def _fetch() -> str | None:
        async with (
            store.connect(db_path) as conn,
            conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)) as cur,
        ):
            row = await cur.fetchone()
        return None if row is None else str(row[0])

    return _sync(_fetch())


def _make_linear_stub() -> MagicMock:
    stub = MagicMock()
    stub.transition_to_done = AsyncMock(return_value=None)
    return stub


def _invoke_close(main: Path, db_path: Path, run_id: str, stub: MagicMock) -> Any:
    """Invoke ``harness close`` with the REAL ``_merge_and_push`` (only Linear faked)."""
    with (
        patch("harness.cli.close.LinearClient", return_value=stub),
        patch("harness.cli.close.linear_api_key", return_value="test-key"),
    ):
        return cli_runner.invoke(
            app,
            [
                "close",
                "CAL-572",
                "--repo",
                str(main),
                "--db",
                str(db_path),
                "--run-id",
                run_id,
                "--json",
            ],
        )


@pytest.fixture
def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))


def test_close_completes_when_origin_advanced_nonconflicting(
    tmp_path: Path, _allow_tmp_workspace: None
) -> None:
    """AC-4: origin/dev advances non-conflicting after start → close completes fully."""
    origin, main = _setup_origin_and_main(tmp_path)
    path, branch = _add_run_worktree(main, RUN_ID, filename="feature.txt", content="run work\n")
    reviewed = _head(main, branch)
    db_path = main / ".harness" / "harness.db"
    _seed_open_run(db_path, path, branch)
    _emit_pass(db_path, RUN_ID, reviewed)

    _advance_origin(tmp_path, origin, filename="other.txt", content="other work\n")

    stub = _make_linear_stub()
    result = _invoke_close(main, db_path, RUN_ID, stub)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["merged"] is True
    assert payload["ticket_done"] is True
    assert payload["status"] == "closed"
    assert payload["reviewed_sha"] == reviewed

    stub.transition_to_done.assert_called_once_with("CAL-572")
    assert _run_status(db_path, RUN_ID) == "closed"

    # origin/dev carries the run's work.
    verify = tmp_path / "verify"
    subprocess.run(
        ["git", "clone", str(origin), str(verify)],
        check=True, capture_output=True, text=True,
    )
    assert (verify / "feature.txt").exists()
    assert (verify / "other.txt").exists()


def test_close_refuses_on_conflict_and_leaves_run_open(
    tmp_path: Path, _allow_tmp_workspace: None
) -> None:
    """AC-5: a conflicting advance → close fails cleanly; run stays open, ticket not Done."""
    origin, main = _setup_origin_and_main(tmp_path)
    path, branch = _add_run_worktree(main, RUN_ID, filename="README.md", content="run line\n")
    reviewed = _head(main, branch)
    db_path = main / ".harness" / "harness.db"
    _seed_open_run(db_path, path, branch)
    _emit_pass(db_path, RUN_ID, reviewed)

    _advance_origin(tmp_path, origin, filename="README.md", content="other line\n")

    stub = _make_linear_stub()
    result = _invoke_close(main, db_path, RUN_ID, stub)

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert "error" in payload
    assert "conflict" in payload["error"].lower()
    # Not a gate refusal — no machine reason key, contract unchanged.
    assert "reason" not in payload

    # The run is resumable: still open, ticket never transitioned, checkout clean.
    stub.transition_to_done.assert_not_called()
    assert _run_status(db_path, RUN_ID) == "open"
    assert _git(main, "status", "--porcelain").stdout.strip() == ""
