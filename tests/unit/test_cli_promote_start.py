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

# size: promote start/continue mechanics (ADR 0003) against one real throw-away repo
# with an origin remote. That fixture is expensive and shared by all five AC-4
# paths, so splitting re-creates the remote per module for no separation gain.

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from harness import promotion as mechanics
from harness.cli import app
from harness.cli import promote as promote_cli
from harness.gate import GATE_UNRUNNABLE_EXIT
from harness.state import promotions
from harness.state.promotions import Promotion

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


def _configure_gate(work: Path, command: str) -> None:
    """Commit a ``CONTEXT.md`` with ``verify: "<command>"`` onto both branches so the
    promotion worktree (merged from them) carries the gate config the promotion
    runs (CAL-1116). Leaves the work repo back on ``dev``."""
    for branch in ("staging", "dev"):
        _git(work, "checkout", branch)
        (work / "CONTEXT.md").write_text(f'commands:\n  verify: "{command}"\n')
        _git(work, "add", "CONTEXT.md")
        _git(work, "commit", "-m", f"gate config on {branch}")
        _git(work, "push", "origin", branch)
    _git(work, "checkout", "dev")


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


# --- AC-2 / AC-3: start classifies the caller's reported gate (CAL-1159) -------


def _gate_log(tmp_path: Path, text: str) -> str:
    """Write a gate log the caller would capture and return its path (as ``str``)."""
    log = tmp_path / "gate.log"
    log.write_text(text)
    return str(log)


def test_clean_merge_green_gate_is_pr_ready(work: Path, tmp_path: Path) -> None:
    """AC-2: a clean merge given a green ``--gate-exit 0`` + ``--gate-log`` reaches
    ``pr_ready``, records the gated SHA (== merged HEAD), and draws bounded evidence
    from the supplied log."""
    _configure_gate(work, "bash scripts/verify.sh")
    _advance(work, "dev", "feature.txt", "shipped\n", "add feature on dev")
    log = _gate_log(tmp_path, "gate-ok all green\n")

    result = _start(
        work, "--from", "dev", "--to", "staging", "--gate-exit", "0", "--gate-log", log
    )
    payload = json.loads(result.output)
    assert payload["status"] == "pr_ready"
    assert payload["gated_sha"] == payload["merged_sha"]
    assert payload["gated_sha"]
    assert "gate-ok" in payload["evidence"]
    # #188 AC-2: a green promotion that DOES advance must carry real evidence.
    assert payload["evidence"]


def test_clean_merge_green_gate_unreadable_log_stays_gate_pending(
    work: Path, tmp_path: Path
) -> None:
    """#188: a green ``--gate-exit 0`` whose ``--gate-log`` path cannot be read (the
    observed failure — a host-side path handed to the container-side verb) must
    fail closed, not silently advance to ``pr_ready`` with an empty evidence tail.
    It rests at ``gate_pending`` with the machine-readable ``gate_log_unreadable``
    reason — the same resumable shape as ``no_gate_evidence`` — so the caller can
    resupply a readable log rather than the promotion recording a false pass."""
    _configure_gate(work, "bash scripts/verify.sh")
    _advance(work, "dev", "feature.txt", "shipped\n", "add feature on dev")
    unreadable_log = str(tmp_path / "does-not-exist.log")

    result = _start(
        work,
        "--from",
        "dev",
        "--to",
        "staging",
        "--gate-exit",
        "0",
        "--gate-log",
        unreadable_log,
    )
    payload = json.loads(result.output)
    assert payload["status"] == "gate_pending"
    assert payload["reason"] == "gate_log_unreadable"
    assert payload["gated_sha"] is None
    assert payload["merged_sha"]  # the merge still happened
    assert Path(payload["worktree_path"]).is_dir()


def test_clean_merge_red_gate_needs_ticket(work: Path, tmp_path: Path) -> None:
    """AC-3: a clean merge given a non-zero ``--gate-exit`` records the failure with
    bounded evidence and no gated SHA — out of local repair authority in v1, so
    ``needs_ticket``."""
    _configure_gate(work, "bash scripts/verify.sh")
    _advance(work, "dev", "feature.txt", "shipped\n", "add feature on dev")
    log = _gate_log(tmp_path, "gate-broke: 1 failed\n")

    result = _start(
        work, "--from", "dev", "--to", "staging", "--gate-exit", "1", "--gate-log", log
    )
    payload = json.loads(result.output)
    assert payload["status"] == "needs_ticket"
    assert payload["gated_sha"] is None
    assert payload["merged_sha"]  # the merge still happened
    assert "gate-broke" in payload["evidence"]


def test_clean_merge_unrunnable_gate_is_blocked(work: Path, tmp_path: Path) -> None:
    """CAL-1160: a clean merge whose host-side gate could not run — reported via the
    reserved ``--gate-exit GATE_UNRUNNABLE_EXIT`` — classifies ``blocked`` (an
    infrastructure failure), not ``needs_ticket`` (a red tree).

    This drives ``blocked`` through the **real classifier path** with no
    monkeypatch and no fabricated ``exit_code=None`` — the reachability the old
    ``test_clean_merge_blocked_when_gate_unrunnable`` faked (it stubbed the
    now-retired ``run_promotion_gate`` to return ``None``, a value no real
    ``--gate-exit`` produces). ``blocked`` here is what keeps the orchestrator from
    escalating an environment problem as a code fix."""
    _configure_gate(work, "bash scripts/verify.sh")
    _advance(work, "dev", "feature.txt", "shipped\n", "add feature on dev")
    log = _gate_log(tmp_path, "gate precondition failed: 'ruff' is not runnable\n")

    result = _start(
        work,
        "--from",
        "dev",
        "--to",
        "staging",
        "--gate-exit",
        str(GATE_UNRUNNABLE_EXIT),
        "--gate-log",
        log,
    )
    payload = json.loads(result.output)
    assert payload["status"] == "blocked"
    assert payload["gated_sha"] is None
    assert payload["merged_sha"]  # the merge still happened
    assert "precondition failed" in payload["evidence"]


def test_success_path_reachable_when_configured_gate_would_fail(
    work: Path, tmp_path: Path
) -> None:
    """AC-4: the promotion success path is reachable even when the repo's configured
    ``verify:`` command **cannot run where the verb runs** — the exact case that was
    dead before CAL-1159 (in-container, ``ruff`` et al. are absent, so an
    in-verb gate returned red/empty and ``pr_ready`` was unreachable).

    We configure a ``verify:`` that would fail if the verb executed it (a binary
    that does not exist), then supply a green ``--gate-exit 0`` from the caller's
    host-side run. Reaching ``pr_ready`` proves the verb does **not** execute the
    gate: if it did, this configured command would fail and no gated SHA would be
    recorded."""
    _configure_gate(work, "definitely-not-a-real-binary-xyz --check")
    _advance(work, "dev", "feature.txt", "shipped\n", "add feature on dev")
    log = _gate_log(tmp_path, "caller ran the real gate host-side: all green\n")

    result = _start(
        work, "--from", "dev", "--to", "staging", "--gate-exit", "0", "--gate-log", log
    )
    payload = json.loads(result.output)
    # The dead path is alive: pr_ready with the gated SHA == the merged HEAD.
    assert payload["status"] == "pr_ready"
    assert payload["gated_sha"] == payload["merged_sha"]
    assert payload["gated_sha"]


def test_clean_merge_without_gate_config_stays_opened(work: Path) -> None:
    """With no ``verify:`` in the merged tree there is nothing to run: the clean
    merge rests at ``opened`` (ungated) — it cannot advance to ``pr_ready`` without
    evidence (matches review/close's ``not_configured`` honesty)."""
    _advance(work, "dev", "feature.txt", "shipped\n", "add feature on dev")

    payload = json.loads(_start(work, "--from", "dev", "--to", "staging").output)
    assert payload["status"] == "opened"
    assert payload["gated_sha"] is None
    assert payload["evidence"] is None


# --- CAL-1159: the gate is host-side; start no longer executes it -------------


def test_clean_merge_with_gate_config_no_evidence_is_gate_pending(work: Path) -> None:
    """AC-1 (CAL-1159): a clean merge whose repo defines a ``verify:`` gate but to
    which no ``--gate-exit`` evidence is supplied does **not** reach ``pr_ready`` —
    it rests at ``gate_pending`` (the merge is done, the worktree waits to be gated
    host-side) and emits the machine-readable ``no_gate_evidence`` reason. The
    ``exit 0`` gate command is deliberately *not* run: the merged worktree exists
    for the caller to gate, not for the verb to execute."""
    _configure_gate(work, "exit 0")
    _advance(work, "dev", "feature.txt", "shipped\n", "add feature on dev")

    result = _start(work, "--from", "dev", "--to", "staging")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "gate_pending"
    assert payload["reason"] == "no_gate_evidence"
    assert payload["gated_sha"] is None
    assert payload["merged_sha"]  # the merge still happened
    # The worktree is preserved so the caller can run the gate against it.
    assert Path(payload["worktree_path"]).is_dir()


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


def test_continue_on_clean_promotion_is_not_resumable(work: Path) -> None:
    """``continue`` only resumes a conflict awaiting repair — a clean ``opened``
    merge has nothing to continue and is refused ``not_resumable``."""
    _advance(work, "dev", "feature.txt", "shipped\n", "add feature on dev")
    started = json.loads(_start(work, "--from", "dev", "--to", "staging").output)
    assert started["status"] == "opened"

    result = cli_runner.invoke(
        app, ["promote", "continue", "--promotion-id", started["promotion_id"], "--repo", str(work)]
    )
    assert result.exit_code == 2, result.output
    refusal = json.loads(result.output)
    assert refusal["reason"] == "not_resumable"
    assert refusal["status"] == "opened"


def test_continue_with_missing_worktree_is_refused(work: Path) -> None:
    """An ``agent_may_fix`` promotion whose worktree directory is gone is refused
    ``worktree_missing`` — there is nothing to resume from."""
    db_path = work / ".harness" / "harness.db"
    promo = Promotion(
        promotion_id="p-missing",
        repo=str(work),
        from_branch="dev",
        to_branch="staging",
        status="agent_may_fix",
        created_at="2026-07-17T00:00:00Z",
        updated_at="2026-07-17T00:00:00Z",
        worktree_path=str(work / ".worktrees" / "harness" / "gone"),
    )
    asyncio.run(promotions.insert_promotion(promo, db_path=db_path))

    result = cli_runner.invoke(
        app, ["promote", "continue", "--promotion-id", "p-missing", "--repo", str(work)]
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "worktree_missing"


# --- AC-5: continue classifies the caller's gate; pr enforces gate freshness ---


def _continue(work: Path, promotion_id: str, *args: str) -> dict[str, object]:
    result = cli_runner.invoke(
        app,
        ["promote", "continue", "--promotion-id", promotion_id, "--repo", str(work), *args],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_continue_green_gate_reaches_pr_ready(work: Path, tmp_path: Path) -> None:
    """AC-5: after the orchestrator resolves the conflict and gates the resolved
    tree host-side, ``continue`` given a green ``--gate-exit 0`` advances the
    resumed merge to ``pr_ready`` with a gated SHA — the bounded repair spent (one
    attempt), the staged resolution *is* the merged tree the caller gated."""
    _configure_gate(work, "bash scripts/verify.sh")
    payload = _start_conflict(work)
    worktree = Path(str(payload["worktree_path"]))
    (worktree / "README.md").write_text("resolved\n")
    _git(worktree, "add", "README.md")
    log = _gate_log(tmp_path, "gate-ok all green\n")

    resumed = _continue(
        work, str(payload["promotion_id"]), "--gate-exit", "0", "--gate-log", log
    )
    assert resumed["status"] == "pr_ready"
    assert resumed["attempts"] == 1
    assert resumed["gated_sha"] == resumed["merged_sha"]
    assert "gate-ok" in resumed["evidence"]


def test_continue_red_gate_needs_ticket(work: Path, tmp_path: Path) -> None:
    """AC-5: a resumed merge given a red ``--gate-exit`` has spent its one bounded
    repair — it escalates to ``needs_ticket`` with bounded evidence and no gated
    SHA."""
    _configure_gate(work, "bash scripts/verify.sh")
    payload = _start_conflict(work)
    worktree = Path(str(payload["worktree_path"]))
    (worktree / "README.md").write_text("resolved\n")
    _git(worktree, "add", "README.md")
    log = _gate_log(tmp_path, "still-red: 1 failed\n")

    resumed = _continue(
        work, str(payload["promotion_id"]), "--gate-exit", "1", "--gate-log", log
    )
    assert resumed["status"] == "needs_ticket"
    assert resumed["attempts"] == 1
    assert resumed["gated_sha"] is None


def test_continue_agent_may_fix_no_evidence_lands_gate_pending(
    work: Path,
) -> None:
    """AC-5: an ``agent_may_fix`` repair completed *without* gate evidence lands at
    ``gate_pending`` (the resolved merge is committed and the attempt spent, but the
    caller has not gated it yet) — resumable by a second ``continue --gate-exit``."""
    _configure_gate(work, "bash scripts/verify.sh")
    payload = _start_conflict(work)
    worktree = Path(str(payload["worktree_path"]))
    (worktree / "README.md").write_text("resolved\n")
    _git(worktree, "add", "README.md")

    resumed = _continue(work, str(payload["promotion_id"]))
    assert resumed["status"] == "gate_pending"
    assert resumed["reason"] == "no_gate_evidence"
    assert resumed["attempts"] == 1
    assert resumed["gated_sha"] is None

    # A second continue supplies the gate evidence and advances to pr_ready without
    # spending another attempt.
    final = _continue(
        work, str(payload["promotion_id"]), "--gate-exit", "0"
    )
    assert final["status"] == "pr_ready"
    assert final["attempts"] == 1
    assert final["gated_sha"] == final["merged_sha"]


def test_continue_gate_pending_from_start_reaches_pr_ready(
    work: Path, tmp_path: Path
) -> None:
    """AC-1 → AC-5 end to end: a clean ``start`` with a gated repo rests at
    ``gate_pending``; the caller gates the worktree host-side and ``continue
    --gate-exit 0`` advances it to ``pr_ready`` — the real two-call flow."""
    _configure_gate(work, "bash scripts/verify.sh")
    _advance(work, "dev", "feature.txt", "shipped\n", "add feature on dev")
    started = json.loads(_start(work, "--from", "dev", "--to", "staging").output)
    assert started["status"] == "gate_pending"

    log = _gate_log(tmp_path, "gate-ok\n")
    resumed = _continue(
        work, str(started["promotion_id"]), "--gate-exit", "0", "--gate-log", log
    )
    assert resumed["status"] == "pr_ready"
    assert resumed["attempts"] == 0  # no repair — gating is not a bounded attempt
    assert resumed["gated_sha"] == resumed["merged_sha"]
    assert resumed["gated_sha"] == started["merged_sha"]
    assert "gate-ok" in resumed["evidence"]


def test_continue_green_gate_unreadable_log_stays_gate_pending_then_resumes(
    work: Path, tmp_path: Path
) -> None:
    """#188's exact repro shape: a ``gate_pending`` merge resumed with a green
    ``--gate-exit 0`` but an unreadable ``--gate-log`` must not advance to
    ``pr_ready`` with empty evidence — it stays ``gate_pending`` (``reason:
    gate_log_unreadable``), still resumable, and a follow-up ``continue`` with a
    readable log reaches ``pr_ready`` with real evidence — no attempt spent either
    time, since gating a ``gate_pending`` merge is not a bounded repair."""
    _configure_gate(work, "bash scripts/verify.sh")
    _advance(work, "dev", "feature.txt", "shipped\n", "add feature on dev")
    started = json.loads(_start(work, "--from", "dev", "--to", "staging").output)
    assert started["status"] == "gate_pending"

    unreadable_log = str(tmp_path / "does-not-exist.log")
    resumed = _continue(
        work,
        str(started["promotion_id"]),
        "--gate-exit",
        "0",
        "--gate-log",
        unreadable_log,
    )
    assert resumed["status"] == "gate_pending"
    assert resumed["reason"] == "gate_log_unreadable"
    assert resumed["gated_sha"] is None
    assert resumed["attempts"] == 0

    log = _gate_log(tmp_path, "gate-ok all green\n")
    final = _continue(
        work, str(started["promotion_id"]), "--gate-exit", "0", "--gate-log", log
    )
    assert final["status"] == "pr_ready"
    assert final["gated_sha"] == final["merged_sha"]
    assert "gate-ok" in final["evidence"]


def _pr(work: Path, promotion_id: str) -> object:
    return cli_runner.invoke(
        app, ["promote", "pr", "--promotion-id", promotion_id, "--repo", str(work)]
    )


def test_pr_on_fresh_green_promotion_publishes(
    work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``pr_ready`` promotion whose branch HEAD still equals the gated SHA passes
    both gates and publishes (CAL-1117) — end-to-end from a real ``start``.

    This module's hop is ``dev → staging``, which CAL-1158 made a **direct push**:
    publishing lands the gated candidate on ``staging`` itself and opens no PR, so
    the promotion reaches the terminal ``promoted`` state. The push against the bare
    origin is real. (Which path each hop takes — and that ``staging → main`` still
    opens a PR — is owned by ``test_promote_staging_hop.py``.)"""
    _configure_gate(work, "exit 0")
    _advance(work, "dev", "feature.txt", "shipped\n", "add feature on dev")
    started = json.loads(
        _start(work, "--from", "dev", "--to", "staging", "--gate-exit", "0").output
    )
    assert started["status"] == "pr_ready"
    gated_sha = str(started["gated_sha"])

    def _no_pr(*args: object, **kwargs: object):
        raise AssertionError("the staging hop must not open a PR (CAL-1158)")

    monkeypatch.setattr(promote_cli, "create_pull_request", _no_pr)

    result = _pr(work, str(started["promotion_id"]))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "promoted"
    assert payload["pr_url"] is None

    # The gated candidate is now staging itself — the promotion is complete.
    _git(work, "fetch", "origin")
    assert _git(work, "rev-parse", "origin/staging").strip() == gated_sha


def test_pr_push_failure_is_a_structured_refusal(
    work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed push surfaces as a structured ``push_failed`` refusal (exit 2)
    with the promotion left un-advanced — never a bare traceback.

    On this module's ``dev → staging`` hop the push is the **target** push
    (CAL-1158); a rejected one (e.g. staging moved under us) must leave the
    promotion ``pr_ready`` so it can be re-gated, not half-finished."""
    _configure_gate(work, "exit 0")
    _advance(work, "dev", "feature.txt", "shipped\n", "add feature on dev")
    started = json.loads(
        _start(work, "--from", "dev", "--to", "staging", "--gate-exit", "0").output
    )
    assert started["status"] == "pr_ready"

    def _boom(repo_root, *, target, gated_sha):
        raise mechanics.PromotionMechanicsError("remote rejected", reason="push_failed")

    monkeypatch.setattr(promote_cli, "push_target_branch", _boom)

    result = _pr(work, str(started["promotion_id"]))
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "push_failed"

    # The promotion is untouched — still pr_ready, no PR URL.
    status = cli_runner.invoke(
        app, ["promote", "status", "--promotion-id", started["promotion_id"], "--repo", str(work)]
    )
    after = json.loads(status.output)
    assert after["status"] == "pr_ready"
    assert after["pr_url"] is None


def test_pr_refused_when_branch_head_moved_past_gated_sha(work: Path) -> None:
    """AC-3: once the promotion branch tip moves past the gated SHA, the recorded
    green gate no longer covers what would be pushed — ``promote pr`` refuses
    ``stale_gate``."""
    _configure_gate(work, "exit 0")
    _advance(work, "dev", "feature.txt", "shipped\n", "add feature on dev")
    started = json.loads(
        _start(work, "--from", "dev", "--to", "staging", "--gate-exit", "0").output
    )
    assert started["status"] == "pr_ready"
    worktree = Path(str(started["worktree_path"]))

    # Someone commits onto the promotion branch after the gate — HEAD != gated_sha.
    (worktree / "extra.txt").write_text("post-gate change\n")
    _git(worktree, "add", "extra.txt")
    _git(worktree, "commit", "-m", "sneak a change past the gate")

    result = _pr(work, str(started["promotion_id"]))
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == "stale_gate"
    assert payload["gated_sha"] == started["gated_sha"]


# --- mechanics-level failure branches (parity with WorktreeNode) --------------


def test_fetch_origin_nonzero_raises(tmp_path: Path) -> None:
    """A non-zero ``git fetch origin`` (an unreachable remote) surfaces as
    ``fetch_failed`` — the promotion cannot proceed on stale refs."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "dev")
    _git(repo, "remote", "add", "origin", str(tmp_path / "does-not-exist.git"))
    with pytest.raises(mechanics.PromotionMechanicsError) as exc_info:
        mechanics.fetch_origin(repo)
    assert exc_info.value.reason == "fetch_failed"


def test_create_worktree_refuses_existing_path(work: Path) -> None:
    """``create_promotion_worktree`` never silently reuses a path — a pre-existing
    directory at the promotion-id location is refused ``worktree_exists``."""
    mechanics.fetch_origin(work)
    existing = work / ".worktrees" / "harness" / "collide"
    existing.mkdir(parents=True)
    with pytest.raises(mechanics.PromotionMechanicsError) as exc_info:
        mechanics.create_promotion_worktree(
            work, "collide", to_branch="staging", branch_name="promote/x"
        )
    assert exc_info.value.reason == "worktree_exists"


def test_create_worktree_fails_on_unknown_target(work: Path) -> None:
    """``git worktree add`` from a target ``origin`` does not carry surfaces as
    ``worktree_create_failed`` and leaves no half-made directory behind."""
    mechanics.fetch_origin(work)
    with pytest.raises(mechanics.PromotionMechanicsError) as exc_info:
        mechanics.create_promotion_worktree(
            work, "badtarget", to_branch="ghost", branch_name="promote/x"
        )
    assert exc_info.value.reason == "worktree_create_failed"
    assert not (work / ".worktrees" / "harness" / "badtarget").exists()


def test_unrelated_histories_is_merge_failed(tmp_path: Path) -> None:
    """A pair whose branches share no history is a real git error (not a content
    conflict): ``start`` refuses ``merge_failed`` and tears its worktree down."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "dev", str(origin))
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "dev")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    _git(work, "remote", "add", "origin", str(origin))
    (work / ".gitignore").write_text(".harness/\n.worktrees/\n")
    (work / "a.txt").write_text("dev root\n")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "dev root")
    _git(work, "push", "-u", "origin", "dev")
    # An orphan staging with no shared ancestry.
    _git(work, "checkout", "--orphan", "staging")
    _git(work, "rm", "-rf", ".")
    (work / "b.txt").write_text("staging root\n")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "staging root")
    _git(work, "push", "-u", "origin", "staging")
    _git(work, "checkout", "dev")

    result = _start(work, "--from", "dev", "--to", "staging")
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "merge_failed"
    # The fresh worktree was cleaned up — nothing left to resume from.
    assert not (work / ".worktrees" / "harness").exists() or not any(
        (work / ".worktrees" / "harness").iterdir()
    )
