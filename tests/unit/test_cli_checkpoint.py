"""Tests for ``harness checkpoint`` — push the run branch so WIP survives the
container dying (CAL-738, breakdown item 5 of ``stale-run-reclamation``).

Decision D4 of the proposal is **preserve/resume**, but resume is only real if
the WIP is durable: a worktree on a dead ephemeral container is gone, so the
only recoverable work is what was **pushed** before the run died. ``checkpoint``
is the verb the orchestrating run calls after each green increment to push its
branch to ``origin`` — the load-bearing half of D4. The push goes through a verb
(not a hand-rolled ``git push``) so it honours the routing-discipline rule
(``commands/harness.md`` — never raw git in the loop) and lands in the ledger as
an auditable ``checkpoint`` event.

Contract under test:

* ``harness checkpoint`` resolves the open run (by ``--run-id`` or by
  ``worktree_path == --repo``), pushes that run's ``worktree_branch`` to
  ``origin``, and appends a ``checkpoint`` event bound to the pushed SHA.
* It **never merges** — only the feature branch is pushed, so the ``close`` gate
  (a pass whose reviewed SHA == HEAD, merge to base) is untouched.
* No open run resolved → exit 2 (mirrors ``review`` / ``close``).
* A push failure (no remote, network error) → exit 1; the verb reports it rather
  than silently dropping the WIP.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.state import store

cli_runner = CliRunner()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


@pytest.fixture(autouse=True)
def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Permit the tmp test tree through the ``HARNESS_WORKSPACE_ROOTS`` gate."""
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))


RUN_ID = "01JRUNCHECKPOINTXXXXXXXXX1"
BRANCH = f"harness/{RUN_ID}"


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A bare repo standing in for ``origin``."""
    bare = tmp_path / "remote.git"
    bare.mkdir()
    _git(bare, "init", "--bare", "-b", "dev")
    return bare


@pytest.fixture
def repo(tmp_path: Path, remote: Path) -> Path:
    """A git repo checked out on the run branch with ``origin`` set.

    Stands in for the run's worktree: ``.harness`` is gitignored so the ledger
    DB does not dirty the tree, the run branch carries one WIP commit, and
    ``origin`` points at the bare ``remote`` so a real ``git push`` lands there.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "dev")
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    _git(repo_root, "remote", "add", "origin", str(remote))
    (repo_root / ".gitignore").write_text(".harness/\n.worktrees/\n")
    (repo_root / "README.md").write_text("hello\n")
    _git(repo_root, "add", ".gitignore", "README.md")
    _git(repo_root, "commit", "-m", "initial")
    # Move onto the run branch and add a WIP commit — what checkpoint preserves.
    _git(repo_root, "checkout", "-b", BRANCH)
    (repo_root / "wip.txt").write_text("work in progress\n")
    _git(repo_root, "add", "wip.txt")
    _git(repo_root, "commit", "-m", "wip")
    return repo_root


@pytest.fixture
def db_path(repo: Path) -> Path:
    return repo / ".harness" / "harness.db"


def _sync(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _seed_open_run(
    db_path: Path,
    repo: Path,
    *,
    run_id: str = RUN_ID,
    branch: str = BRANCH,
    ticket: str = "CAL-738",
) -> str:
    """Insert an ``open`` runs row whose worktree_path == repo, return run_id."""

    async def _insert() -> None:
        await store.init_db(db_path)
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs ("
                "run_id, workflow_name, workflow_version, status, state_json, "
                "inputs_json, base_branch, worktree_path, worktree_branch, "
                "ticket, started_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id, "", 0, "open", "{}", "{}", "dev",
                    str(repo), branch, ticket, "2026-06-16T00:00:00Z",
                ),
            )
            await conn.commit()

    _sync(_insert())
    return run_id


def _checkpoint_events(db_path: Path, run_id: str) -> list[dict[str, Any]]:
    async def _select() -> list[dict[str, Any]]:
        async with store.connect(db_path) as conn:
            cur = await conn.execute(
                "SELECT data_json FROM events "
                "WHERE run_id = ? AND event_type = 'checkpoint'",
                (run_id,),
            )
            rows = await cur.fetchall()
        return [json.loads(r[0]) for r in rows]

    return _sync(_select())


def _remote_has_branch(remote: Path, branch: str) -> bool:
    out = subprocess.run(
        ["git", "ls-remote", "--heads", str(remote), branch],
        check=True, capture_output=True, text=True,
    )
    return bool(out.stdout.strip())


# ===========================================================================
# AC-1: a checkpoint pushes the branch (durable WIP) and records the event
# ===========================================================================


def test_checkpoint_pushes_branch_and_emits_event(
    repo: Path, db_path: Path, remote: Path
) -> None:
    """The happy path: the run branch lands on ``origin`` and a ``checkpoint``
    event bound to the pushed SHA is appended to the ledger."""
    _seed_open_run(db_path, repo)
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()

    result = cli_runner.invoke(
        app,
        ["checkpoint", "--run-id", RUN_ID, "--repo", str(repo), "--db", str(db_path)],
    )
    assert result.exit_code == 0, result.output

    # The branch is now durable on the remote.
    assert _remote_has_branch(remote, BRANCH)

    # An auditable checkpoint event bound to the pushed SHA.
    events = _checkpoint_events(db_path, RUN_ID)
    assert len(events) == 1
    assert events[0]["branch"] == BRANCH
    assert events[0]["pushed_sha"] == head


def test_checkpoint_json_output(repo: Path, db_path: Path) -> None:
    """``--json`` emits the run, branch, pushed SHA, and pushed flag."""
    _seed_open_run(db_path, repo)
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()

    result = cli_runner.invoke(
        app,
        ["checkpoint", "--run-id", RUN_ID, "--repo", str(repo), "--db", str(db_path),
         "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["run_id"] == RUN_ID
    assert payload["branch"] == BRANCH
    assert payload["pushed_sha"] == head
    assert payload["pushed"] is True


def test_checkpoint_resolves_run_by_worktree(repo: Path, db_path: Path, remote: Path) -> None:
    """With no ``--run-id`` the open run is resolved by ``worktree_path == --repo``."""
    _seed_open_run(db_path, repo)
    result = cli_runner.invoke(
        app, ["checkpoint", "--repo", str(repo), "--db", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    assert _remote_has_branch(remote, BRANCH)


def test_checkpoint_is_repeatable(repo: Path, db_path: Path, remote: Path) -> None:
    """A second checkpoint after more WIP fast-forwards the remote branch and
    records a second event — the cadence is 'after each green increment'."""
    _seed_open_run(db_path, repo)
    cli_runner.invoke(
        app, ["checkpoint", "--run-id", RUN_ID, "--repo", str(repo), "--db", str(db_path)]
    )
    # More work, another checkpoint.
    (repo / "more.txt").write_text("more\n")
    _git(repo, "add", "more.txt")
    _git(repo, "commit", "-m", "more wip")
    head2 = _git(repo, "rev-parse", "HEAD").stdout.strip()

    result = cli_runner.invoke(
        app, ["checkpoint", "--run-id", RUN_ID, "--repo", str(repo), "--db", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    events = _checkpoint_events(db_path, RUN_ID)
    assert len(events) == 2
    assert events[-1]["pushed_sha"] == head2
    # The remote branch advanced to the latest WIP.
    remote_sha = subprocess.run(
        ["git", "ls-remote", "--heads", str(remote), BRANCH],
        check=True, capture_output=True, text=True,
    ).stdout.split()[0]
    assert remote_sha == head2


# ===========================================================================
# CAL-1162: a rebased run branch re-checkpoints (force-with-lease), and the
# lease still refuses when origin carries a commit the run has not seen.
# ===========================================================================


def test_checkpoint_re_pushes_a_rebased_run_branch(
    repo: Path, db_path: Path, remote: Path
) -> None:
    """A checkpoint after the run branch is *rebased* still lands the rewritten
    tip on ``origin``.

    Rebase-before-close is the standing move when ``dev`` advances mid-run, and
    it **rewrites** the run branch — so a plain push is rejected non-fast-forward
    and durability silently reverts to the pre-rebase commit. The force-with-lease
    push makes checkpoint match its own contract across the rebase: the run branch
    is the run's private, rewritable WIP ref (CAL-1162)."""
    _seed_open_run(db_path, repo)
    # First checkpoint pushes the pre-rebase tip.
    r1 = cli_runner.invoke(
        app, ["checkpoint", "--run-id", RUN_ID, "--repo", str(repo), "--db", str(db_path)]
    )
    assert r1.exit_code == 0, r1.output

    # dev advances and the run branch is rebased onto it — its tip is rewritten.
    _git(repo, "checkout", "dev")
    (repo / "dev.txt").write_text("dev moved\n")
    _git(repo, "add", "dev.txt")
    _git(repo, "commit", "-m", "dev moved")
    _git(repo, "checkout", BRANCH)
    _git(repo, "rebase", "dev")
    rebased_head = _git(repo, "rev-parse", "HEAD").stdout.strip()

    # The re-checkpoint must succeed and advance origin to the rebased tip.
    r2 = cli_runner.invoke(
        app, ["checkpoint", "--run-id", RUN_ID, "--repo", str(repo), "--db", str(db_path)]
    )
    assert r2.exit_code == 0, r2.output
    remote_sha = subprocess.run(
        ["git", "ls-remote", "--heads", str(remote), BRANCH],
        check=True, capture_output=True, text=True,
    ).stdout.split()[0]
    assert remote_sha == rebased_head
    events = _checkpoint_events(db_path, RUN_ID)
    assert events[-1]["pushed_sha"] == rebased_head


def test_checkpoint_lease_refuses_when_origin_has_unseen_commit(
    repo: Path, db_path: Path, remote: Path, tmp_path: Path
) -> None:
    """The lease still does its job: when ``origin``'s run branch carries a commit
    this run has not seen, the checkpoint is refused with a **named,
    machine-readable outcome** (``reason='stale_remote'``, not a raw git blob) and
    ``origin`` is left untouched (CAL-1162, AC-3)."""
    _seed_open_run(db_path, repo)
    # First checkpoint: origin/BRANCH == our tip; our remote-tracking ref records it.
    cli_runner.invoke(
        app, ["checkpoint", "--run-id", RUN_ID, "--repo", str(repo), "--db", str(db_path)]
    )

    # A *different* clone advances origin/BRANCH — a commit this run never fetches.
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(remote), str(other)],
        check=True, capture_output=True, text=True,
    )
    _git(other, "config", "user.email", "other@example.com")
    _git(other, "config", "user.name", "Other")
    _git(other, "checkout", BRANCH)
    (other / "unseen.txt").write_text("unseen by the run\n")
    _git(other, "add", "unseen.txt")
    _git(other, "commit", "-m", "unseen")
    _git(other, "push", "origin", BRANCH)
    unseen_sha = _git(other, "rev-parse", "HEAD").stdout.strip()

    # The run rewrites its own tip (a rebase) and tries to re-checkpoint.
    _git(repo, "commit", "--amend", "--no-edit", "-m", "wip rebased")
    result = cli_runner.invoke(
        app,
        ["checkpoint", "--run-id", RUN_ID, "--repo", str(repo), "--db", str(db_path),
         "--json"],
    )
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == "stale_remote"
    # A human sentence, not the raw git rejection blob.
    assert "not seen" in payload["error"]
    assert "[rejected]" not in payload["error"]

    # The lease did its job: origin still carries the unseen commit, un-clobbered.
    remote_sha = subprocess.run(
        ["git", "ls-remote", "--heads", str(remote), BRANCH],
        check=True, capture_output=True, text=True,
    ).stdout.split()[0]
    assert remote_sha == unseen_sha
    # No fabricated durability: no second checkpoint event was recorded.
    assert len(_checkpoint_events(db_path, RUN_ID)) == 1


# ===========================================================================
# Refusals
# ===========================================================================


def test_checkpoint_no_open_run_refused(repo: Path, db_path: Path) -> None:
    """No open run for the worktree → exit 2 (mirrors review/close)."""
    _sync(store.init_db(db_path))  # empty ledger
    result = cli_runner.invoke(
        app, ["checkpoint", "--repo", str(repo), "--db", str(db_path)]
    )
    assert result.exit_code == 2


def test_checkpoint_push_failure_exits_1(tmp_path: Path) -> None:
    """A push that fails (no ``origin``) exits 1 — the WIP failure is surfaced,
    not silently dropped."""
    repo_root = tmp_path / "norepo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "dev")
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    (repo_root / ".gitignore").write_text(".harness/\n")
    (repo_root / "f.txt").write_text("x\n")
    _git(repo_root, "add", ".gitignore", "f.txt")
    _git(repo_root, "commit", "-m", "init")
    _git(repo_root, "checkout", "-b", BRANCH)
    db = repo_root / ".harness" / "harness.db"
    _seed_open_run(db, repo_root)

    result = cli_runner.invoke(
        app, ["checkpoint", "--run-id", RUN_ID, "--repo", str(repo_root), "--db", str(db)]
    )
    assert result.exit_code == 1


# ===========================================================================
# The push must not undermine the close gate — only the feature branch moves
# ===========================================================================


def test_checkpoint_does_not_emit_a_review_or_close_event(
    repo: Path, db_path: Path
) -> None:
    """checkpoint records only a ``checkpoint`` event — it never fabricates a
    review pass or a close, so the gate stays the close verb's sole authority."""
    _seed_open_run(db_path, repo)
    cli_runner.invoke(
        app, ["checkpoint", "--run-id", RUN_ID, "--repo", str(repo), "--db", str(db_path)]
    )

    async def _types() -> set[str]:
        async with store.connect(db_path) as conn:
            cur = await conn.execute(
                "SELECT DISTINCT event_type FROM events WHERE run_id = ?", (RUN_ID,)
            )
            return {r[0] for r in await cur.fetchall()}

    assert _sync(_types()) == {"checkpoint"}
