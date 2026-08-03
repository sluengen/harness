"""End-to-end ``harness close`` against a real advanced ``origin`` — CAL-777, CAL-1154.

``close`` integrates ``origin/<base>`` before it lands the run branch. When
``origin/<base>`` advanced after ``start`` — a concurrent ``/harness routine
build`` or another session landing a ticket — a naive ``push`` was rejected
non-fast-forward and close exited 1 (observed 2026-06-18: CAL-767 landed on
``dev`` mid-CAL-764-run). The mechanics fetch ``origin/<base>`` and merge the run
branch onto that current tip; the HEAD-bound gate is preserved — only the reviewed
SHA's commit rides in (it is the merge's second parent).

**CAL-1154** moved that merge off the main checkout entirely: it now runs in a
throwaway worktree (:mod:`harness.close_merge`), so a close never mutates the main
checkout on any path. The mechanics themselves are unit-tested in
``test_close_merge.py``; these tests drive the **close verb** end-to-end against a
real bare ``origin`` (only Linear faked), which ``test_cli_close.py`` (mocked
merge) does not.

AC-4: origin/base advances non-conflicting after start → close completes fully
      (merge + push + ticket Done + run closed); origin gets the merge.
AC-5: a conflicting advance → close fails cleanly, the run stays open and
      resumable, and the recovery lands. #266 retired the *prescription* of a
      rebase — `close` integrates `origin/<base>` itself, so the documented
      route is now merge-base-into-branch → re-review → close; a rebase remains
      legal and is still pinned as such.
AC-1: a close leaves the main checkout byte-identical even when it is dirty —
      the merge cannot touch it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.events.emitter import EventEmitter
from harness.state import store
from tests._asyncutil import run_sync

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


def _merge_in_progress(repo: Path) -> bool:
    """True iff ``repo`` has a merge in progress (``MERGE_HEAD`` present)."""
    return subprocess.run(
        ["git", "rev-parse", "--verify", "-q", "MERGE_HEAD"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    ).returncode == 0


RUN_ID = "01JRUNINTEGRATEBASE0000001"


# ---------------------------------------------------------------------------
# Close verb end-to-end with a real merge (only Linear faked)
# ---------------------------------------------------------------------------


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

    run_sync(_insert())


def _emit_pass(db_path: Path, run_id: str, reviewed_sha: str) -> None:
    """A pass as ``harness review`` records one — including the verify-gate
    evidence the close gate's backstop requires (CAL-1082)."""

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
                "gate_ran": True,
                "gate_command": "bash scripts/verify.sh",
                "gate_exit_code": 0,
            },
        )

    run_sync(_emit())


def _run_status(db_path: Path, run_id: str) -> str | None:
    async def _fetch() -> str | None:
        async with (
            store.connect(db_path) as conn,
            conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)) as cur,
        ):
            row = await cur.fetchone()
        return None if row is None else str(row[0])

    return run_sync(_fetch())


def _make_linear_stub() -> MagicMock:
    stub = MagicMock()
    stub.transition_to_done = AsyncMock(return_value=None)
    return stub


def _invoke_close(main: Path, db_path: Path, run_id: str, stub: MagicMock) -> Any:
    """Invoke ``harness close`` with the REAL throwaway-worktree merge (only Linear faked)."""
    with (
        patch("harness.tracker.LinearClient", return_value=stub),
        patch("harness.tracker.linear_api_key", return_value="test-key"),
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
    # #266 AC-2, verb level: the reviewed SHA that landed is the one the run
    # already had — no rebase happened anywhere in the path — and the base
    # advancing produced no gate refusal.
    assert payload["reviewed_sha"] == reviewed
    assert "reason" not in payload

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
    # The reviewed commit rode in as the merge's second parent, unrewritten.
    assert _head(verify, "HEAD^2") == reviewed


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

    # CAL-1154: the main checkout is untouched by construction — the conflict
    # happened in a throwaway worktree that was torn down wholesale, so there is
    # no merge in progress, no unmerged paths, no staged residue in the main tree.
    assert _git(main, "status", "--porcelain").stdout.strip() == ""
    assert not _merge_in_progress(main)
    assert _git(main, "diff", "--cached", "--name-only").stdout.strip() == ""


def test_close_leaves_a_dirty_main_checkout_untouched(
    tmp_path: Path, _allow_tmp_workspace: None
) -> None:
    """AC-1: a close never mutates the main checkout — even a dirty one lands cleanly.

    The whole point of the throwaway-worktree merge (CAL-1154): the state of the
    main checkout is irrelevant to a close. Where the CAL-1151 design *refused* a
    dirty base checkout (``dirty_base_checkout``), the merge now happens off the
    main tree entirely, so a close succeeds and the main checkout — its HEAD, its
    uncommitted edits, its untracked files — is byte-identical before and after.
    """
    origin, main = _setup_origin_and_main(tmp_path)
    path, branch = _add_run_worktree(main, RUN_ID, filename="feature.txt", content="run\n")
    reviewed = _head(main, branch)
    db_path = main / ".harness" / "harness.db"
    _seed_open_run(db_path, path, branch)
    _emit_pass(db_path, RUN_ID, reviewed)

    # A human edit and a stray scratch file leave the main checkout dirty — the
    # exact state CAL-1151 refused. It must no longer matter.
    (main / "README.md").write_text("local uncommitted edit\n")
    (main / "scratch.txt").write_text("untracked scratch\n")
    head_before = _head(main)
    status_before = _git(main, "status", "--porcelain").stdout

    result = _invoke_close(main, db_path, RUN_ID, _make_linear_stub())

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["merged"] is True
    assert _run_status(db_path, RUN_ID) == "closed"

    # The main checkout is byte-identical: same HEAD, same dirt, edit preserved.
    assert _head(main) == head_before
    assert _git(main, "status", "--porcelain").stdout == status_before
    assert (main / "README.md").read_text() == "local uncommitted edit\n"
    assert not _merge_in_progress(main)

    # And origin still received the run's work.
    verify = tmp_path / "verify"
    subprocess.run(
        ["git", "clone", str(origin), str(verify)],
        check=True, capture_output=True, text=True,
    )
    assert (verify / "feature.txt").exists()


def test_close_recovery_by_merging_base_into_the_run_branch_succeeds(
    tmp_path: Path, _allow_tmp_workspace: None
) -> None:
    """#266: the route the conflict message now names must actually land.

    The defect being fixed is a message that prescribed a remedy nothing
    verified. Naming a *new* remedy without driving it end-to-end would repeat
    that defect one line down — so this drives it exactly as the message reads:
    fetch, merge `origin/<base>` into the run branch, resolve, commit, re-review
    (the resolution moved HEAD, so the gate needs a fresh pass), close again.
    No history is rewritten: the run's original commit stays reachable.
    """
    origin, main = _setup_origin_and_main(tmp_path)
    path, branch = _add_run_worktree(main, RUN_ID, filename="README.md", content="run line\n")
    original = _head(main, branch)
    db_path = main / ".harness" / "harness.db"
    _seed_open_run(db_path, path, branch)
    _emit_pass(db_path, RUN_ID, original)

    _advance_origin(tmp_path, origin, filename="README.md", content="other line\n")

    stub = _make_linear_stub()
    assert _invoke_close(main, db_path, RUN_ID, stub).exit_code == 1  # conflict refusal

    # The newly documented recovery, verbatim: merge the base into the run
    # branch and commit the resolution — no rebase, so every SHA already on the
    # branch survives.
    _git(main, "fetch", "origin", "dev")
    subprocess.run(
        ["git", "merge", "origin/dev"],
        cwd=path, check=False, capture_output=True, text=True,
    )
    (path / "README.md").write_text("resolved line\n")
    _git(path, "add", "README.md")
    _git(path, "-c", "core.editor=true", "commit", "--no-edit")
    resolved = _head(path)
    _emit_pass(db_path, RUN_ID, resolved)  # the resolution moved HEAD → re-review

    result = _invoke_close(main, db_path, RUN_ID, stub)

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["merged"] is True
    assert _run_status(db_path, RUN_ID) == "closed"
    # Nothing was rewritten — the originally reviewed commit is still an ancestor.
    verify = tmp_path / "verify"
    subprocess.run(
        ["git", "clone", str(origin), str(verify)],
        check=True, capture_output=True, text=True,
    )
    assert subprocess.run(
        ["git", "merge-base", "--is-ancestor", original, "HEAD"],
        cwd=verify, check=False, capture_output=True, text=True,
    ).returncode == 0


def test_close_recovery_after_conflict_refusal_succeeds(
    tmp_path: Path, _allow_tmp_workspace: None
) -> None:
    """CAL-1151 AC-3 / CAL-1154: a rebase recovery still lands, with no manual git.

    #266 retired the *prescription* of a rebase — it did not remove the
    capability, and a rebase remains a legal way to resolve the conflict. This
    pins that it still works end-to-end. Under CAL-1151 it used to hit a
    *different*, misleading error because an abandoned merge sat in the base
    checkout; the throwaway-worktree merge removes that failure mode structurally
    (nothing is ever left in the main tree). This drives the whole recovery.
    """
    origin, main = _setup_origin_and_main(tmp_path)
    path, branch = _add_run_worktree(main, RUN_ID, filename="README.md", content="run line\n")
    db_path = main / ".harness" / "harness.db"
    _seed_open_run(db_path, path, branch)
    _emit_pass(db_path, RUN_ID, _head(main, branch))

    _advance_origin(tmp_path, origin, filename="README.md", content="other line\n")

    stub = _make_linear_stub()
    assert _invoke_close(main, db_path, RUN_ID, stub).exit_code == 1  # conflict refusal

    # A rebase recovery: rebase the run branch on the updated base, resolve,
    # re-review (rewritten SHAs → a fresh pass), close again. No `git merge
    # --abort` in the main checkout — that is the bug, not the cure.
    _git(main, "fetch", "origin", "dev")
    subprocess.run(
        ["git", "rebase", "origin/dev"],
        cwd=path, check=False, capture_output=True, text=True,
    )
    (path / "README.md").write_text("resolved line\n")
    _git(path, "add", "README.md")
    subprocess.run(
        ["git", "-c", "core.editor=true", "rebase", "--continue"],
        cwd=path, check=True, capture_output=True, text=True,
    )
    _emit_pass(db_path, RUN_ID, _head(path))  # re-review binds a pass to the new HEAD

    result = _invoke_close(main, db_path, RUN_ID, stub)

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["merged"] is True
    assert _run_status(db_path, RUN_ID) == "closed"


def test_merge_run_branch_is_idempotent_for_an_already_landed_run(
    tmp_path: Path, _allow_tmp_workspace: None
) -> None:
    """#233's retry path (re-running ``close`` after a confirmed-failed ticket
    transition) is only safe because re-merging an already-landed run branch is
    a clean no-op: ``git merge --no-ff`` of a ref already an ancestor of the
    fetched tip reports "Already up to date" rather than erroring, and pushing
    the unchanged tip back is a no-op push. This pins that fact directly against
    :func:`harness.close_merge.merge_run_branch`, independent of the close verb.
    """
    from harness.close_merge import merge_run_branch

    origin, main = _setup_origin_and_main(tmp_path)
    path, branch = _add_run_worktree(main, RUN_ID, filename="feature.txt", content="run work\n")

    merge_run_branch(repo_root=main, run_id=RUN_ID, base_branch="dev", worktree_branch=branch)
    origin_tip_after_first = _git(main, "rev-parse", "origin/dev").stdout.strip()

    # Re-run for the same run branch — exactly what a `ticket_transition_failed`
    # retry does, since close's merge step precedes the ticket-Done step.
    merge_run_branch(repo_root=main, run_id=RUN_ID, base_branch="dev", worktree_branch=branch)
    origin_tip_after_second = _git(main, "rev-parse", "origin/dev").stdout.strip()

    assert origin_tip_after_second == origin_tip_after_first
