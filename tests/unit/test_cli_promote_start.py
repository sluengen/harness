"""``harness promote start`` / ``continue`` mechanics — CAL-1115 (ADR 0003).

End-to-end CLI tests over a real throw-away repo with an ``origin`` remote
carrying ``dev`` and ``staging``. They exercise the worktree/merge mechanics the
way an orchestrator drives them, covering the five AC-4 paths:

* **clean merge** (AC-1) — a worktree/branch is created and the merged HEAD recorded;
* **conflict** (AC-2) — a resumable worktree plus structured conflict files + a
  classification (``agent_may_fix`` / ``needs_ticket``);
* **invalid branch pair** (AC-4) — refused before any state is created;
* **dirty worktree** (AC-4) — ``continue`` refuses an unresolved repair;
* **resume** (AC-3) — ``continue`` after a bounded repair records the merged HEAD
  and increments the attempt count.

The remote is a local bare repo, so ``git fetch origin`` is real but offline.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from harness.cli import app

cli_runner = CliRunner()


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture(autouse=True)
def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Permit the tmp tree through the ``HARNESS_WORKSPACE_ROOTS`` gate (CAL-584)."""
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))


@pytest.fixture
def work(tmp_path: Path) -> Path:
    """A work repo whose ``origin`` (a local bare repo) carries ``dev`` + ``staging``.

    Both branches start at one shared ``base`` commit; the per-test helpers below
    push divergent tips. Left checked out on ``dev``.
    """
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "dev", str(origin))

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "dev")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    _git(work, "remote", "add", "origin", str(origin))
    (work / ".gitignore").write_text(".harness/\n.worktrees/\n")
    (work / "README.md").write_text("base\n")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "base")
    _git(work, "push", "-u", "origin", "dev")
    _git(work, "checkout", "-b", "staging")
    _git(work, "push", "-u", "origin", "staging")
    _git(work, "checkout", "dev")
    return work


def _advance(work: Path, branch: str, path: str, content: str, msg: str) -> None:
    """Commit ``content`` at ``path`` on ``branch`` and push it to ``origin``.

    Leaves the work repo back on ``dev`` so a later helper starts from a known
    branch.
    """
    _git(work, "checkout", branch)
    target = work / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    _git(work, "add", path)
    _git(work, "commit", "-m", msg)
    _git(work, "push", "origin", branch)
    _git(work, "checkout", "dev")


def _start(work: Path, *args: str) -> subprocess.CompletedProcess[str] | object:
    return cli_runner.invoke(
        app, ["promote", "start", "--repo", str(work), *args]
    )


# --- AC-1: clean merge --------------------------------------------------------


def test_clean_merge_creates_worktree_and_records_merged_head(work: Path) -> None:
    """A non-conflicting ``dev`` → ``staging`` promotion creates the worktree/branch
    and records the merged HEAD; status is ``opened`` (awaiting the gate, CAL-1116)."""
    _advance(work, "dev", "feature.txt", "shipped\n", "add feature on dev")

    result = _start(work, "--from", "dev", "--to", "staging")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert payload["status"] == "opened"
    assert payload["conflict_files"] == []
    assert payload["from_branch"] == "dev"
    assert payload["to_branch"] == "staging"
    assert payload["promotion_branch"].startswith("promote/")
    assert payload["promotion_branch"].endswith("-dev-to-staging")
    # The merged HEAD is a real commit in the promotion worktree.
    merged = payload["merged_sha"]
    assert merged
    worktree = Path(payload["worktree_path"])
    assert worktree.is_dir()
    assert _git(worktree, "rev-parse", "HEAD").strip() == merged
    # The merge actually brought dev's file onto the promotion branch.
    assert (worktree / "feature.txt").read_text() == "shipped\n"

    # The promotion is persisted and readable back by id.
    status = cli_runner.invoke(
        app, ["promote", "status", "--promotion-id", payload["promotion_id"], "--repo", str(work)]
    )
    assert status.exit_code == 0, status.output
    assert json.loads(status.output)["merged_sha"] == merged


# --- AC-2: conflict path ------------------------------------------------------


def test_conflict_leaves_resumable_worktree_and_classifies(work: Path) -> None:
    """Conflicting edits to the same file classify ``agent_may_fix`` and leave the
    worktree with the conflict in progress (resumable)."""
    _advance(work, "dev", "README.md", "dev change\n", "dev edits readme")
    _advance(work, "staging", "README.md", "staging change\n", "staging edits readme")

    result = _start(work, "--from", "dev", "--to", "staging")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert payload["status"] == "agent_may_fix"
    assert payload["merged_sha"] is None
    assert payload["conflict_files"] == ["README.md"]
    # The worktree is left mid-merge (resumable): the file carries conflict markers.
    worktree = Path(payload["worktree_path"])
    assert "<<<<<<<" in (worktree / "README.md").read_text()


def test_conflict_in_sensitive_file_needs_a_ticket(work: Path) -> None:
    """A conflict touching a schema migration escalates to ``needs_ticket`` (ADR 0003
    repair authority) — an add/add conflict on the same migration path."""
    _advance(work, "dev", "db/migrations/0002_x.py", "dev migration\n", "dev migration")
    _advance(work, "staging", "db/migrations/0002_x.py", "staging migration\n", "staging migration")

    result = _start(work, "--from", "dev", "--to", "staging")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "needs_ticket"
    assert payload["conflict_files"] == ["db/migrations/0002_x.py"]


# --- AC-4: invalid branch pair ------------------------------------------------


def test_promote_into_itself_is_refused(work: Path) -> None:
    """``--from`` == ``--to`` is a degenerate pair — refused, no promotion created."""
    result = _start(work, "--from", "dev", "--to", "dev")
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "invalid_branch_pair"


def test_unknown_branch_is_refused(work: Path) -> None:
    """A branch ``origin`` does not carry is an unclean base — refused."""
    result = _start(work, "--from", "nope", "--to", "staging")
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "invalid_branch_pair"


# --- AC-3 / AC-4: continue (resume) and the dirty-worktree refusal ------------


def _start_conflict(work: Path) -> dict[str, object]:
    """Open a conflicting promotion and return its ``start`` payload."""
    _advance(work, "dev", "README.md", "dev change\n", "dev edits readme")
    _advance(work, "staging", "README.md", "staging change\n", "staging edits readme")
    result = _start(work, "--from", "dev", "--to", "staging")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "agent_may_fix"
    return payload


def test_continue_without_resolving_refuses_dirty_worktree(work: Path) -> None:
    """``continue`` on a still-conflicted worktree refuses ``dirty_worktree`` and
    reports the unresolved files, without advancing the promotion."""
    payload = _start_conflict(work)
    result = cli_runner.invoke(
        app, ["promote", "continue", "--promotion-id", payload["promotion_id"], "--repo", str(work)]
    )
    assert result.exit_code == 2, result.output
    refusal = json.loads(result.output)
    assert refusal["reason"] == "dirty_worktree"
    assert refusal["conflict_files"] == ["README.md"]

    # The promotion is untouched — still agent_may_fix, still 0 attempts.
    status = cli_runner.invoke(
        app, ["promote", "status", "--promotion-id", payload["promotion_id"], "--repo", str(work)]
    )
    after = json.loads(status.output)
    assert after["status"] == "agent_may_fix"
    assert after["attempts"] == 0


def test_continue_after_repair_records_merge_and_increments_attempts(work: Path) -> None:
    """After the orchestrator resolves + stages the conflict, ``continue`` commits the
    merge, records the merged HEAD, and increments the repair attempt count (AC-3)."""
    payload = _start_conflict(work)
    worktree = Path(str(payload["worktree_path"]))

    # The orchestrator's bounded repair: resolve the conflict and stage it.
    (worktree / "README.md").write_text("resolved\n")
    _git(worktree, "add", "README.md")

    result = cli_runner.invoke(
        app, ["promote", "continue", "--promotion-id", payload["promotion_id"], "--repo", str(work)]
    )
    assert result.exit_code == 0, result.output
    resumed = json.loads(result.output)

    assert resumed["status"] == "opened"
    assert resumed["attempts"] == 1
    assert resumed["conflict_files"] == []
    merged = resumed["merged_sha"]
    assert merged
    assert _git(worktree, "rev-parse", "HEAD").strip() == merged
    # The committed merge carries the resolved content.
    assert (worktree / "README.md").read_text() == "resolved\n"


def test_continue_on_unknown_promotion_is_not_found(work: Path) -> None:
    """``continue`` on an unknown id is a structured ``not_found`` (exit 2)."""
    result = cli_runner.invoke(
        app, ["promote", "continue", "--promotion-id", "ghost", "--repo", str(work)]
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["error"] == "not_found"
