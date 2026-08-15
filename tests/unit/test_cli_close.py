"""Tests for ``harness close <TICKET>`` — CAL-572.

The close verb is the enforcement linchpin: closing a ticket must be impossible
unless a run was started AND the current tree passed review (a ``review`` event
with ``verdict='pass'`` whose ``reviewed_sha`` equals the worktree HEAD).

AC-1: close succeeds only when a pass event's ``reviewed_sha == HEAD``;
      merge/push/Done/closed all occur.
AC-2: pass-then-edit (HEAD advanced past the reviewed SHA) → refusal
      ``stale_review``, no merge, ticket not Done.
AC-3: no passing review → refusal ``no_passing_review``, no side effects.
AC-4: no open run → refusal ``no_run``.
AC-5: on success the run row is ``status='closed'`` and the ticket is Done.
AC-context-economy: ``close`` returns a compact result (merge/close status, or
      a structured refusal ``reason``); git merge/push output stays inside the
      verb and never enters the printed JSON.

The Linear Done transition and the git merge/push are faked/injected so tests
never hit the network or a real remote — mirroring how ``test_cli_start.py``
patches the Linear client and ``test_cli_review.py`` injects the runner.
"""

# size: the close gate — the enforcement linchpin. Every case is a variation on one
# invariant (a pass whose reviewed_sha equals HEAD, or no merge), and the module's
# value is that the whole refusal matrix is readable in one place; splitting it
# hides which refusals are covered.

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Any, get_args
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from harness import close_merge
from harness.cli import app, close_retry
from harness.cli import close as close_mod
from harness.cli.close_tracker import TicketFailureKind
from harness.events.emitter import EventEmitter
from harness.events.payloads import CLOSE_OUTCOME_OK, CLOSE_OUTCOME_PATH
from harness.linear import LinearConfigError
from harness.state import store
from harness.tracker_errors import (
    TrackerNotFound,
    TrackerRequestError,
    TrackerTransitionUnconfirmed,
)
from tests._asyncutil import run_sync

cli_runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(autouse=True)
def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Permit the tmp test tree through the ``HARNESS_WORKSPACE_ROOTS`` gate (CAL-584).

    These verb tests predate the allowlist and point ``--repo`` at paths under
    ``tmp_path``; without a configured root the gate fails closed.
    """
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))


@pytest.fixture(autouse=True)
def retry_delays(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record the retry's sleeps instead of paying them (#301).

    Autouse because the retry is now on the step-6 and step-7 paths several
    pre-existing tests already exercise (a ``push_rejected`` merge, a raising
    tracker): unpatched, each would really sleep 2s + 8s. Tests that assert the
    bound request the fixture by name and read the recorded delays; the rest are
    simply spared the wall time.
    """
    recorded: list[float] = []

    async def _record(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(close_retry, "_sleep", _record)
    return recorded


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throw-away git repo with one commit on ``dev``.

    ``.harness/`` is gitignored exactly as in the real repo (.gitignore:24) so
    the ledger DB the verbs create under it never registers as a dirty worktree
    — the ``dirty_worktree`` gate (CAL-586) keys off ``git status --porcelain``,
    which excludes ignored paths.
    """
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


def _head_sha(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


RUN_ID = "01JRUNCLOSEXXXXXXXXXXXXX01"

# #261: both ends of the duration measurement are pinned, so the tests assert an
# exact integer rather than a tolerance window. ``_seed_open_run`` writes
# ``SEEDED_STARTED_AT`` into the run row; the tests patch ``close``'s clock to
# ``FIXED_CLOSED_AT``. 62.5s elapsed → 62_500ms.
SEEDED_STARTED_AT = "2026-06-10T00:00:00Z"
# #263: the verb's *first* clock reading is now ``invoked_at``, captured right
# after the run resolves and before the gate. It is not what #261's stamps
# measure — those run from ``started_at`` — so it is pinned separately and
# simply consumed ahead of the close reading.
FIXED_INVOKED_AT = "2026-06-10T00:00:30.000000Z"
FIXED_CLOSED_AT = "2026-06-10T00:01:02.500000Z"
EXPECTED_DURATION_MS = 62_500
# Every clock reading after the second. Distinct on purpose — see _pin_close_clock.
LATER_CLOCK_READING = "2026-06-10T00:05:00.000000Z"


def _pin_close_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``close``'s clock: ``invoked_at``, then ``closed_at``, then *later*.

    A constant stub would make the AC-1 equality vacuous — an implementation
    that read the clock a second time for ``completed_at`` would still match the
    close event's timestamp, so the drift the single reading exists to prevent
    would go unguarded. Handing out a distinct value once the two the verb
    legitimately takes are consumed is what makes both assertions bite.
    """
    readings = iter([FIXED_INVOKED_AT, FIXED_CLOSED_AT])
    monkeypatch.setattr(
        close_mod,
        "iso_z",
        lambda *_a, **_k: next(readings, LATER_CLOCK_READING),
    )


def _seed_open_run(
    db_path: Path,
    repo: Path,
    run_id: str = RUN_ID,
    ticket: str = "CAL-572",
    started_at: str = SEEDED_STARTED_AT,
) -> str:
    """Insert an ``open`` runs row whose worktree_path == repo, return run_id."""

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
                    "open",
                    "{}",
                    "{}",
                    "dev",
                    str(repo),
                    f"harness/{run_id}",
                    ticket,
                    started_at,
                    1234,
                ),
            )
            await conn.commit()

    run_sync(_insert())
    return run_id


#: The verify-gate evidence a green gate records (CAL-1082) — what a current
#: ``harness review`` always writes onto a ``review`` event.
_GREEN_GATE_EVIDENCE = {
    "gate_ran": True,
    "gate_command": "bash scripts/verify.sh",
    "gate_exit_code": 0,
}


def _emit_review(
    db_path: Path,
    run_id: str,
    reviewed_sha: str,
    verdict: str,
    issues: list[str] | None = None,
    gate: dict[str, Any] | None = None,
) -> None:
    """Append a ``review`` event mirroring what ``harness review`` records.

    ``gate`` defaults to the evidence a green verify gate records (CAL-1082) —
    what a current ``harness review`` always writes — so these tests exercise the
    close gate rather than its verify-gate backstop. Pass ``gate={}`` to seed the
    *legacy* payload (no ``gate_ran`` key), which the backstop refuses.
    """

    async def _emit() -> None:
        emitter = EventEmitter(db_path)
        await emitter.emit(
            run_id=run_id,
            event_type="review",
            data={
                "run_id": run_id,
                "reviewed_sha": reviewed_sha,
                "verdict": verdict,
                "issues": issues or [],
                "created_at": "2026-06-10T00:00:00Z",
                **(_GREEN_GATE_EVIDENCE if gate is None else gate),
            },
        )

    run_sync(_emit())


async def _fetch_run_status(db_path: Path, run_id: str) -> str | None:
    async with (
        store.connect(db_path) as conn,
        conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)) as cur,
    ):
        row = await cur.fetchone()
    return None if row is None else str(row[0])


def fetch_run_status(db_path: Path, run_id: str) -> str | None:
    return run_sync(_fetch_run_status(db_path, run_id))


async def _fetch_close_events(db_path: Path, run_id: str) -> list[tuple[Any, ...]]:
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT id, data_json FROM events "
            "WHERE run_id = ? AND event_type = 'close'",
            (run_id,),
        ) as cur,
    ):
        return list(await cur.fetchall())


def fetch_close_events(db_path: Path, run_id: str) -> list[tuple[Any, ...]]:
    return run_sync(_fetch_close_events(db_path, run_id))


async def _fetch_landed_close_events(db_path: Path, run_id: str) -> list[tuple[Any, ...]]:
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT id, data_json FROM events "
            "WHERE run_id = ? AND event_type = 'close' "
            f"AND COALESCE(json_extract(data_json, '{CLOSE_OUTCOME_PATH}'), ?) = ?",
            (run_id, CLOSE_OUTCOME_OK, CLOSE_OUTCOME_OK),
        ) as cur,
    ):
        return list(await cur.fetchall())


def fetch_landed_close_events(db_path: Path, run_id: str) -> list[tuple[Any, ...]]:
    """The ``close`` events for a run that actually **landed** (#263).

    Before #263 a ``close`` event existed only on success, so "did this run
    land?" was "is there a close event". Refusals now share the event type and
    discriminate on ``outcome``, so the question moved to ``outcome='ok'`` — the
    ``COALESCE`` keeping a pre-#263 row reading as the landed close it was.
    """
    return run_sync(_fetch_landed_close_events(db_path, run_id))


async def _fetch_run_completion(
    db_path: Path, run_id: str
) -> tuple[str | None, int | None]:
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT completed_at, duration_ms FROM runs WHERE run_id = ?",
            (run_id,),
        ) as cur,
    ):
        row = await cur.fetchone()
        return (None, None) if row is None else (row[0], row[1])


def fetch_run_completion(db_path: Path, run_id: str) -> tuple[str | None, int | None]:
    """Return the run row's ``(completed_at, duration_ms)`` — #261's stamps."""
    return run_sync(_fetch_run_completion(db_path, run_id))


async def _fetch_close_event_timestamp(db_path: Path, run_id: str) -> str | None:
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT timestamp FROM events "
            "WHERE run_id = ? AND event_type = 'close'",
            (run_id,),
        ) as cur,
    ):
        row = await cur.fetchone()
        return None if row is None else row[0]


def fetch_close_event_timestamp(db_path: Path, run_id: str) -> str | None:
    return run_sync(_fetch_close_event_timestamp(db_path, run_id))


def _install_close_event_failure_trigger(db_path: Path) -> None:
    """Make the close-event INSERT fail deterministically at the DB layer.

    A ``BEFORE INSERT`` trigger that ``RAISE(ABORT)``s only for the ``close``
    event, so the failure lands on exactly the write CAL-1002 makes atomic —
    and lands identically whether the emit runs on its own connection (the
    pre-fix code) or inside the status-flip transaction (the fix). The review
    seed (``event_type='review'``) is untouched, so the gate still passes.
    """

    async def _install() -> None:
        async with store.connect(db_path) as conn:
            await conn.execute(
                "CREATE TRIGGER _fail_close_event BEFORE INSERT ON events "
                "WHEN NEW.event_type = 'close' "
                "BEGIN SELECT RAISE(ABORT, 'injected close-event write failure'); END"
            )
            await conn.commit()

    run_sync(_install())


def _make_linear_stub(raise_on_transition: Exception | None = None) -> MagicMock:
    stub = MagicMock()
    if raise_on_transition is not None:
        stub.transition_to_done = AsyncMock(side_effect=raise_on_transition)
    else:
        stub.transition_to_done = AsyncMock(return_value=None)
    return stub


def _invoke(
    repo: Path,
    db_path: Path,
    run_id: str,
    linear_stub: MagicMock,
    merge_push: MagicMock | None = None,
) -> Any:
    """Invoke ``harness close`` with the Linear client and git side effects faked."""
    merge = merge_push if merge_push is not None else MagicMock(return_value=None)
    with (
        patch("harness.tracker.LinearClient", return_value=linear_stub),
        patch("harness.tracker.linear_api_key", return_value="test-key"),
        patch("harness.close_merge.merge_run_branch", merge),
    ):
        result = cli_runner.invoke(
            app,
            [
                "close",
                "CAL-572",
                "--repo",
                str(repo),
                "--db",
                str(db_path),
                "--run-id",
                run_id,
                "--json",
            ],
        )
    return result, merge


# ---------------------------------------------------------------------------
# AC-1 / AC-5: pass for HEAD → merge/push/Done/closed all occur
# ---------------------------------------------------------------------------


def test_ac1_close_succeeds_when_pass_for_head(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")
    stub = _make_linear_stub()

    result, merge = _invoke(repo, db_path, run_id, stub)
    assert result.exit_code == 0, result.output

    # Merge/push happened, ticket transitioned to Done.
    merge.assert_called_once()
    stub.transition_to_done.assert_called_once_with("CAL-572")

    payload = json.loads(result.output)
    assert payload["run_id"] == run_id
    assert payload["merged"] is True
    assert payload["ticket_done"] is True
    assert payload["status"] == "closed"


def test_ac5_run_closed_and_ticket_done_on_success(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")
    stub = _make_linear_stub()

    result, _merge = _invoke(repo, db_path, run_id, stub)
    assert result.exit_code == 0, result.output

    # Run row flipped to closed.
    assert fetch_run_status(db_path, run_id) == "closed"
    # Ticket Done transition fired exactly once.
    stub.transition_to_done.assert_called_once_with("CAL-572")


# ---------------------------------------------------------------------------
# AC-2: pass-then-edit (HEAD advanced) → refusal stale_review, no side effects
# ---------------------------------------------------------------------------


def test_ac2_stale_review_when_head_advanced(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    reviewed = _head_sha(repo)
    _emit_review(db_path, run_id, reviewed, "pass")

    # Advance HEAD past the reviewed SHA.
    (repo / "feature.txt").write_text("more work\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "more work")
    assert _head_sha(repo) != reviewed

    stub = _make_linear_stub()
    result, merge = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["reason"] == "stale_review"

    # No merge, no Done, run still open.
    merge.assert_not_called()
    stub.transition_to_done.assert_not_called()
    assert fetch_run_status(db_path, run_id) == "open"


# ---------------------------------------------------------------------------
# AC-dirty: pass-then-edit-without-committing → refusal dirty_worktree (CAL-586)
# ---------------------------------------------------------------------------


def test_dirty_worktree_refused_when_uncommitted_edits(repo: Path, db_path: Path) -> None:
    """A pass for HEAD does NOT cover uncommitted edits — close must refuse.

    CAL-586 / CODE-1: the gate binds to HEAD, but an earlier close used to
    auto-commit a dirty worktree, merging content that no review ever saw.
    ``stale_review`` catches commit-after-review; it does NOT catch
    edit-without-committing because HEAD is unchanged. The dirty tree must be
    refused outright (``dirty_worktree``) before any merge.
    """
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")

    # Edit the worktree WITHOUT committing — HEAD still equals the reviewed SHA.
    (repo / "sneaky.txt").write_text("unreviewed content\n")
    assert _head_sha(repo) == head  # the pass still nominally matches HEAD

    stub = _make_linear_stub()
    result, merge = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["reason"] == "dirty_worktree"

    # No merge, no Done, run still open — the unreviewed edit never lands.
    merge.assert_not_called()
    stub.transition_to_done.assert_not_called()
    assert fetch_run_status(db_path, run_id) == "open"


def test_dirty_worktree_refused_with_modified_tracked_file(repo: Path, db_path: Path) -> None:
    """Modifying a tracked file (not just adding an untracked one) is also refused."""
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")

    (repo / "README.md").write_text("hello\nedited after review\n")
    assert _head_sha(repo) == head

    stub = _make_linear_stub()
    result, merge = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code != 0
    assert json.loads(result.output)["reason"] == "dirty_worktree"
    merge.assert_not_called()
    stub.transition_to_done.assert_not_called()
    assert fetch_run_status(db_path, run_id) == "open"


# ---------------------------------------------------------------------------
# AC-3: no passing review → refusal no_passing_review, no side effects
# ---------------------------------------------------------------------------


def test_ac3_no_passing_review_only_fail(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "fail", issues=["bug"])
    stub = _make_linear_stub()

    result, merge = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["reason"] == "no_passing_review"

    merge.assert_not_called()
    stub.transition_to_done.assert_not_called()
    assert fetch_run_status(db_path, run_id) == "open"


def test_ac3_no_review_at_all(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    stub = _make_linear_stub()

    result, merge = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["reason"] == "no_passing_review"

    merge.assert_not_called()
    stub.transition_to_done.assert_not_called()
    assert fetch_run_status(db_path, run_id) == "open"


# ---------------------------------------------------------------------------
# CAL-1082 AC-6: a pass carrying no verify-gate evidence → no_gate_evidence
# ---------------------------------------------------------------------------


def test_pass_without_gate_evidence_is_refused(repo: Path, db_path: Path) -> None:
    """A pass written before the verify gate existed carries no ``gate_ran`` key.

    ``json_extract`` yields NULL for it, and the backstop reads that as "no
    evidence a test ever ran" and refuses — fail-safe, so no ledger migration is
    needed and a pre-CAL-1082 pass cannot be spent on a merge.
    """
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass", gate={})  # legacy payload
    stub = _make_linear_stub()

    result, merge = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["reason"] == "no_gate_evidence"

    merge.assert_not_called()
    stub.transition_to_done.assert_not_called()
    assert fetch_run_status(db_path, run_id) == "open"


def test_pass_with_unconfigured_gate_is_allowed(repo: Path, db_path: Path) -> None:
    """A repo defining no ``verify:`` records the absence honestly, and closes.

    The harness cannot gate what a repo does not define; refusing here would
    strand every repo without a gate, which is its own decision to make.
    """
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(
        db_path, run_id, head, "pass", gate={"gate_ran": False, "gate_reason": "not_configured"}
    )
    stub = _make_linear_stub()

    result, merge = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code == 0, result.output
    merge.assert_called_once()
    stub.transition_to_done.assert_called_once()


def test_pass_with_green_gate_evidence_closes(repo: Path, db_path: Path) -> None:
    """The evidence a green gate records opens the close gate (the happy path)."""
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")  # defaults to green-gate evidence
    stub = _make_linear_stub()

    result, _ = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# AC-4: no open run → refusal no_run
# ---------------------------------------------------------------------------


def test_ac4_no_open_run(repo: Path, db_path: Path) -> None:
    run_sync(store.init_db(db_path))  # empty DB, no runs
    stub = _make_linear_stub()

    result, merge = _invoke(repo, db_path, "01JNONEXISTENTRUNIDXXXXXX0", stub)

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["reason"] == "no_run"

    merge.assert_not_called()
    stub.transition_to_done.assert_not_called()


# ---------------------------------------------------------------------------
# Unconfigured Linear: missing LINEAR_API_KEY → exit 2, no reason, no side effect
# ---------------------------------------------------------------------------


def test_close_exits_2_when_linear_unconfigured(repo: Path, db_path: Path) -> None:
    """A missing ``LINEAR_API_KEY`` exits 2 with no ``reason`` — not exit 1.

    The key check (close.py step 5) runs *after* the gate passes but *before*
    any side effect, so an unset key on an otherwise-closeable run refuses
    cleanly without half-merging a tree. ``LinearConfigError`` is not a gate
    refusal, so the JSON carries an ``error`` but no ``reason``. Pins the exit-2
    branch the docstring exit-code block must document (guarded by
    ``test_close_docstring_exit_codes_match_contract``).
    """
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")
    stub = _make_linear_stub()
    merge = MagicMock(return_value=None)

    with (
        patch("harness.tracker.LinearClient", return_value=stub),
        patch(
            "harness.tracker.linear_api_key",
            side_effect=LinearConfigError("LINEAR_API_KEY is not set"),
        ),
        patch("harness.close_merge.merge_run_branch", merge),
    ):
        result = cli_runner.invoke(
            app,
            [
                "close",
                "CAL-572",
                "--repo",
                str(repo),
                "--db",
                str(db_path),
                "--run-id",
                run_id,
                "--json",
            ],
        )

    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert "error" in payload
    assert "reason" not in payload  # a config error is not a gate refusal

    # The gate passed, but the unset key blocks before any side effect.
    merge.assert_not_called()
    stub.transition_to_done.assert_not_called()
    assert fetch_run_status(db_path, run_id) == "open"


def test_close_docstring_exit_codes_match_contract() -> None:
    """The module docstring's exit-code block must match the tested behaviour.

    ``close`` raises exit 2 not only for the four gate refusals but also when
    Linear is unconfigured (a missing ``LINEAR_API_KEY`` →
    :class:`LinearConfigError`, close.py step 5). That config error is *not* a
    gate refusal and carries no ``reason``; it must not be documented as a
    generic "Linear error" under exit 1. Guards against the exit-2 entry
    drifting back to a gate-refusal-only list and the exit-1 entry claiming a
    Linear configuration error exits 1 — both falsified by
    ``test_close_exits_2_when_linear_unconfigured``.
    """
    doc = close_mod.__doc__ or ""
    exit_block = doc[doc.index("Exit codes") :]
    # The exit-2 entry is the last bullet; it runs from "* 2" to the end of the
    # block, spanning its continuation lines. The exit-1 entry runs from "* 1"
    # up to "* 2".
    two_entry = exit_block[exit_block.index("* 2") :]
    one_entry = exit_block[exit_block.index("* 1") : exit_block.index("* 2")]

    assert "LINEAR_API_KEY" in two_entry, (
        "exit 2 covers a missing LINEAR_API_KEY (LinearConfigError), not just "
        "the four gate-refusal reasons; document it in the exit-2 entry"
    )
    assert "Linear error" not in one_entry, (
        "a missing/unconfigured Linear key exits 2, not 1; the exit-1 entry "
        "must not claim a generic 'Linear error' exits 1"
    )
    assert "ticket_transition_failed" in one_entry, (
        "exit 1 covers a raised tracker error while transitioning the ticket "
        "to Done (#233); document its reason tag in the exit-1 entry"
    )
    assert "ticket_transition_unconfirmed" in one_entry, (
        "exit 1 also covers a transition whose post-write state could not be "
        "confirmed (#233); document its reason tag in the exit-1 entry"
    )
    assert "ticket_transition_failed" not in two_entry, (
        "ticket_transition_failed is an exit-1 reason (the merge already "
        "landed); it must not appear in the exit-2 gate-refusal entry"
    )
    assert "ticket_transition_unconfirmed" not in two_entry, (
        "ticket_transition_unconfirmed is an exit-1 reason (the merge already "
        "landed); it must not appear in the exit-2 gate-refusal entry"
    )
    assert "merge_conflict" in one_entry, (
        "exit 1 also covers a merge/push failure carrying the reason "
        "close_merge computed (#300); document its tag in the exit-1 entry"
    )
    assert "merge_conflict" not in two_entry, (
        "merge_conflict is an exit-1 reason, not a gate refusal; it must not "
        "appear in the exit-2 entry"
    )


#: The paragraph in the activated `/harness run` gate-refusal section that classifies
#: a step-6 failure. Sliced by the stable sentence it opens with, because the
#: two recovery paragraphs *below* it already name `merge_conflict` and
#: `push_rejected` for unrelated reasons — a section-wide containment check
#: would pass on a paragraph that had dropped the tags entirely.
# ---------------------------------------------------------------------------
# AC-context-economy: compact result, no raw git output in the printed JSON
# ---------------------------------------------------------------------------


def test_context_economy_no_git_output_in_json(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")
    stub = _make_linear_stub()

    # The fake merge/push returns verbose git output — it must stay inside the
    # verb and never leak into the printed JSON.
    noisy = "Merge made by the 'ort' strategy.\n 1 file changed\nTo origin\n   abc..def"
    merge = MagicMock(return_value=noisy)
    result, _merge = _invoke(repo, db_path, run_id, stub, merge_push=merge)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    # Compact result: only bounded status fields, no raw git chatter.
    assert set(payload.keys()) <= {
        "run_id",
        "ticket",
        "reviewed_sha",
        "merged",
        "ticket_done",
        "status",
        # #353: which kind of evidence opened the gate. A bounded status field
        # like the rest — it carries no git output, which is what this guard is
        # about.
        "evidence_kind",
    }
    assert noisy not in result.output
    assert "Merge made by" not in result.output


# ---------------------------------------------------------------------------
# close command registered in CLI help
# ---------------------------------------------------------------------------


def test_close_command_registered() -> None:
    result = cli_runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "close" in result.output


# ---------------------------------------------------------------------------
# LinearClient.transition_to_done — targets the completed-type state
# ---------------------------------------------------------------------------


async def test_linear_transition_to_done_prefers_named_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """transition_to_done targets a state literally named 'Done' over other completed states."""
    from harness.linear import LinearClient

    calls: list[dict[str, Any]] = []

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        calls.append({"query": query, "variables": variables})
        if "states" in query:
            return {
                "data": {
                    "issue": {
                        "id": "issue-id",
                        "team": {
                            "states": {
                                "nodes": [
                                    {"id": "state-cancel", "name": "Canceled", "type": "canceled"},
                                    {"id": "state-shipped", "name": "Shipped", "type": "completed"},
                                    {"id": "state-done", "name": "Done", "type": "completed"},
                                ]
                            }
                        },
                    }
                }
            }
        return {
            "data": {
                "issueUpdate": {
                    "success": True,
                    "issue": {"id": "issue-id", "state": {"id": "state-done", "name": "Done"}},
                }
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    await client.transition_to_done("CAL-572")

    mutation_calls = [c for c in calls if "issueUpdate" in c["query"]]
    assert len(mutation_calls) == 1
    # The named "Done" state (not the first completed-type "Shipped") was chosen.
    assert mutation_calls[0]["variables"]["stateId"] == "state-done"


async def test_linear_transition_to_done_falls_back_to_first_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no state named 'Done', the first completed-type state is used."""
    from harness.linear import LinearClient

    calls: list[dict[str, Any]] = []

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        calls.append({"query": query, "variables": variables})
        if "states" in query:
            return {
                "data": {
                    "issue": {
                        "id": "issue-id",
                        "team": {
                            "states": {
                                "nodes": [
                                    {"id": "state-shipped", "name": "Shipped", "type": "completed"},
                                ]
                            }
                        },
                    }
                }
            }
        return {
            "data": {
                "issueUpdate": {
                    "success": True,
                    "issue": {
                        "id": "issue-id",
                        "state": {"id": "state-shipped", "name": "Shipped"},
                    },
                }
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    await client.transition_to_done("CAL-572")

    mutation_calls = [c for c in calls if "issueUpdate" in c["query"]]
    assert mutation_calls[0]["variables"]["stateId"] == "state-shipped"


async def test_linear_transition_to_done_raises_when_no_completed_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """transition_to_done raises LinearRequestError when no completed state exists."""
    from harness.linear import LinearClient, LinearRequestError

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {
            "data": {
                "issue": {
                    "id": "issue-id",
                    "team": {
                        "states": {
                            "nodes": [
                                {"id": "state-ip", "name": "In Progress", "type": "started"}
                            ]
                        }
                    },
                }
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")

    with pytest.raises(LinearRequestError, match="no 'completed' workflow state"):
        await client.transition_to_done("CAL-572")


# ---------------------------------------------------------------------------
# LinearClient._transition confirmation (#233) — a self-reported ``success``
# is not proof the state actually changed; the post-write state must match.
# ---------------------------------------------------------------------------


async def test_transition_to_done_raises_when_post_state_is_not_the_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduces the reported incident at the layer that lied: the mutation
    reports ``success: true``, but the returned post-write state is still In
    Review, not the "Done" state that was requested."""
    from harness.linear import LinearClient, TrackerTransitionUnconfirmed

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        if "states" in query:
            return {
                "data": {
                    "issue": {
                        "id": "issue-id",
                        "team": {
                            "states": {
                                "nodes": [{"id": "state-done", "name": "Done", "type": "completed"}]
                            }
                        },
                    }
                }
            }
        return {
            "data": {
                "issueUpdate": {
                    "success": True,
                    "issue": {
                        "id": "issue-id",
                        "state": {"id": "state-inreview", "name": "In Review"},
                    },
                }
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(TrackerTransitionUnconfirmed):
        await client.transition_to_done("CAL-992")


async def test_transition_to_done_raises_unconfirmed_when_state_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mutation reporting ``success: true`` but omitting ``issue``/``state``
    entirely is refused, not trusted — absent evidence is not evidence."""
    from harness.linear import LinearClient, TrackerTransitionUnconfirmed

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        if "states" in query:
            return {
                "data": {
                    "issue": {
                        "id": "issue-id",
                        "team": {
                            "states": {
                                "nodes": [{"id": "state-done", "name": "Done", "type": "completed"}]
                            }
                        },
                    }
                }
            }
        return {"data": {"issueUpdate": {"success": True}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(TrackerTransitionUnconfirmed):
        await client.transition_to_done("CAL-992")


# ---------------------------------------------------------------------------
# AC-teardown (CAL-767): a successful close reclaims the worktree + branch
# ---------------------------------------------------------------------------

WT_RUN_ID = "01JRUNCLOSEWORKTREE0000001"


def _seed_run_with_worktree(db_path: Path, repo: Path) -> tuple[str, Path, str]:
    """Seed an open run backed by a REAL worktree under .worktrees/harness/.

    Unlike :func:`_seed_open_run` (whose ``worktree_path`` is the repo itself),
    this creates an actual ``git worktree`` so the teardown step has something to
    reclaim. The worktree HEAD equals the repo's ``dev`` tip, so the gate binds
    to ``_head_sha(repo)``.
    """
    path = repo / ".worktrees" / "harness" / WT_RUN_ID
    branch = f"harness/{WT_RUN_ID}"
    _git(repo, "worktree", "add", "-b", branch, str(path), "dev")

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
                    WT_RUN_ID, "", 0, "open", "{}", "{}", "dev",
                    str(path), branch, "CAL-572", "2026-06-10T00:00:00Z", 1234,
                ),
            )
            await conn.commit()

    run_sync(_insert())
    return WT_RUN_ID, path, branch


def _local_branches(repo: Path) -> set[str]:
    out = _git(repo, "branch", "--format=%(refname:short)").stdout
    return set(out.split())


def test_close_reclaims_worktree_and_branch_on_success(repo: Path, db_path: Path) -> None:
    """CAL-767: after a successful close the worktree dir and local branch are gone."""
    run_id, path, branch = _seed_run_with_worktree(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo), "pass")
    assert path.exists()
    assert branch in _local_branches(repo)

    result, _merge = _invoke(repo, db_path, run_id, _make_linear_stub())

    assert result.exit_code == 0, result.output
    assert not path.exists()
    assert branch not in _local_branches(repo)


def test_close_does_not_reclaim_on_gate_refusal(repo: Path, db_path: Path) -> None:
    """A stale-review refusal exits before teardown — the worktree survives."""
    run_id, path, branch = _seed_run_with_worktree(db_path, repo)
    _emit_review(db_path, run_id, "0" * 40, "pass")  # pass for a different SHA

    result, merge = _invoke(repo, db_path, run_id, _make_linear_stub())

    assert result.exit_code == 2
    assert json.loads(result.output)["reason"] == "stale_review"
    merge.assert_not_called()
    assert path.exists()  # worktree NOT torn down
    assert branch in _local_branches(repo)


def test_close_succeeds_even_if_teardown_raises(repo: Path, db_path: Path) -> None:
    """Teardown is best-effort: an exception in it never fails an already-landed
    close (merge/Done/ledger have all succeeded)."""
    run_id = _seed_open_run(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo), "pass")

    with patch.object(close_mod, "teardown_worktree", side_effect=RuntimeError("boom")):
        result, merge = _invoke(repo, db_path, run_id, _make_linear_stub())

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "closed"
    assert payload["merged"] is True
    assert payload["ticket_done"] is True
    merge.assert_called_once()


# ---------------------------------------------------------------------------
# CAL-1002: the status flip and the close event land in ONE transaction
# ---------------------------------------------------------------------------


def test_close_records_close_event_on_success(repo: Path, db_path: Path) -> None:
    """A successful close appends exactly one ``close`` event carrying the run,
    ticket and merged SHA — guards the atomic write against silently dropping
    the audit event when the emit is inlined into the status-flip transaction."""
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")

    result, _merge = _invoke(repo, db_path, run_id, _make_linear_stub())
    assert result.exit_code == 0, result.output

    events = fetch_close_events(db_path, run_id)
    assert len(events) == 1
    data = json.loads(events[0][1])
    assert data["run_id"] == run_id
    assert data["ticket"] == "CAL-572"
    assert data["merged_sha"] == head


# ---------------------------------------------------------------------------
# #300: a step-6 merge/push failure carries the reason ``close_merge`` computed
# ---------------------------------------------------------------------------

_CLOSE_MERGE_SOURCE = Path(close_merge.__file__)


def _raised_reasons(source: Path) -> set[str]:
    """Every ``reason`` a ``CloseMergeError`` is constructed with in ``source``.

    Derived from the module text by AST, never hand-listed (#300 AC-5): a reason
    added to ``close_merge`` later must fail the tests below, not silently
    bypass them. A non-literal ``reason=`` would make this derivation
    *under-count* — and so make the totality assertion vacuously easier — so it
    is refused outright rather than skipped.

    This is the single derivation the totality assertion, both propagation
    parametrizations, and the non-vacuity floor all call. They must share it:
    a floor that re-implements the scan it protects cannot detect the scan
    breaking, which is the whole failure it exists to catch.
    """
    tree = ast.parse(source.read_text())
    kwargs = [
        kw
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "CloseMergeError"
        for kw in node.keywords
        if kw.arg == "reason"
    ]
    non_literal = [kw for kw in kwargs if not isinstance(kw.value, ast.Constant)]
    assert not non_literal, (
        f"every CloseMergeError(reason=...) in {source.name} must be a string "
        f"literal, or this derivation under-counts and the totality check below "
        f"passes on an incomplete set ({len(non_literal)} computed reason(s) found)"
    )
    return {kw.value.value for kw in kwargs}


def test_the_reason_derivation_is_not_vacuous() -> None:
    """Floor under the derived totality + propagation tests (#300).

    Those tests are parametrized over :func:`_raised_reasons`. An empty or
    broken derivation would collect **zero** cases and report green, so this
    asserts the scan actually reaches the raise sites — calling the same
    function they do, not its own copy of the walk.
    """
    derived = _raised_reasons(_CLOSE_MERGE_SOURCE)

    assert len(derived) >= 7, (
        f"the AST scan of {_CLOSE_MERGE_SOURCE.name} found only {len(derived)} "
        f"reason(s) ({sorted(derived)}); it reached at least 7 when written, so "
        f"a smaller set means the derivation broke, not that the module shrank"
    )
    # Two anchors confirmed present at the raise sites, and the two an
    # orchestrating agent actually branches on.
    assert {"merge_conflict", "push_rejected"} <= derived, (
        f"the derivation must reach merge_run_branch's own raise sites; got {sorted(derived)}"
    )


def test_the_derivation_reads_the_source_not_the_declared_vocabulary(tmp_path: Path) -> None:
    """Control: :func:`_raised_reasons` parses source text, not ``CloseMergeReason``.

    Without this, the totality assertion below is satisfiable by a derivation
    that simply returns the declared vocabulary — a tautology that would pass
    while a reason added to ``close_merge`` and never declared slipped through
    untagged, which is precisely what AC-5 exists to prevent. Proven on a
    synthetic module carrying a reason **no** literal declares, so an
    implementation reading the type cannot produce this answer.
    """
    invented = "a_reason_no_literal_declares"
    assert invented not in get_args(close_merge.CloseMergeReason), (
        "the control's reason must be absent from the declared vocabulary, or "
        "it cannot tell a source-reading derivation from a type-reading one"
    )
    synthetic = tmp_path / "synthetic_close_merge.py"
    synthetic.write_text(
        "def f() -> None:\n"
        f'    raise CloseMergeError("boom", reason="{invented}")\n'
    )

    assert _raised_reasons(synthetic) == {invented}


def test_the_derivation_refuses_a_computed_reason(tmp_path: Path) -> None:
    """A non-literal ``reason=`` is refused, not skipped.

    Skipping it would make the derived set *smaller*, so the totality assertion
    would pass on an incomplete set — the failure mode is silent under-counting,
    which is why this is an error rather than a tolerated case.
    """
    synthetic = tmp_path / "computed_close_merge.py"
    synthetic.write_text(
        "def f(tag: str) -> None:\n    raise CloseMergeError('boom', reason=tag)\n"
    )

    with pytest.raises(AssertionError, match="string literal"):
        _raised_reasons(synthetic)


def test_every_raised_reason_is_declared_in_the_vocabulary() -> None:
    """``CloseMergeReason`` covers every raise site, and declares nothing dead.

    Asserted in both directions, so adding a reason without declaring it fails
    here, and declaring one nothing raises fails here too (#300 AC-5).
    """
    assert _raised_reasons(_CLOSE_MERGE_SOURCE) == set(get_args(close_merge.CloseMergeReason))


@pytest.mark.parametrize("reason", sorted(_raised_reasons(_CLOSE_MERGE_SOURCE)))
def test_every_reason_propagates_from_the_merge_step(
    repo: Path, db_path: Path, reason: str
) -> None:
    """Step 6 propagates whatever reason ``close_merge`` raised (#300 AC-5).

    Parametrized over the derived set rather than a hand-written table, so a new
    reason is covered automatically. Propagation is asserted as a property of
    the *boundary* — ``close`` passes the reason through — which is why every
    reason is exercised here regardless of which helper raises it in production.
    """
    run_id = _seed_open_run(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo), "pass")
    merge = MagicMock(side_effect=close_merge.CloseMergeError("boom", reason=reason))

    result, _ = _invoke(repo, db_path, run_id, _make_linear_stub(), merge_push=merge)

    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["reason"] == reason


@pytest.mark.parametrize("reason", sorted(_raised_reasons(_CLOSE_MERGE_SOURCE)))
def test_every_reason_propagates_from_the_status_step(
    repo: Path, db_path: Path, reason: str
) -> None:
    """Step 3's ``worktree_porcelain`` boundary propagates too (#300 AC-5).

    The ticket names step 6, but ``git_status_failed`` is raised by
    ``worktree_porcelain`` and is reachable from ``close`` **only** here — so
    totality over the module's reasons is unmet without this second boundary.
    A status read that succeeds and reports edits is a different branch and
    still exits 2 (``dirty_worktree``); see the tests above.
    """
    run_id = _seed_open_run(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo), "pass")
    porcelain = MagicMock(side_effect=close_merge.CloseMergeError("boom", reason=reason))

    with patch("harness.close_merge.worktree_porcelain", porcelain):
        result, _ = _invoke(repo, db_path, run_id, _make_linear_stub())

    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["reason"] == reason


def test_the_two_exit_one_families_stay_disjoint() -> None:
    """A merge reason means the merge did **not** land; a ticket reason means it did.

    The ticket's technical note calls out this asymmetry as the thing to
    preserve. Overlapping vocabularies would make it unreadable from the wire.
    """
    merge_reasons = set(get_args(close_mod.MergeFailureReason))
    ticket_reasons = set(get_args(close_mod.TicketFailureReason))

    assert merge_reasons and ticket_reasons
    assert not (merge_reasons & ticket_reasons)
    flattened = {v for lit in get_args(close_mod.FailureReason) for v in get_args(lit)}
    assert flattened == merge_reasons | ticket_reasons
    # AC-3: no exit-2 refusal gains or loses a reason.
    assert not (set(get_args(close_mod.RefusalReason)) & (merge_reasons | ticket_reasons))


@pytest.mark.parametrize("reason", ["merge_conflict", "push_rejected"])
def test_close_merge_failure_carries_its_reason(
    repo: Path, db_path: Path, reason: str
) -> None:
    """A step-6 failure reports the ``reason`` ``close_merge`` already computed (#300).

    ``merge_conflict`` needs human work (merge the base, commit, re-review);
    ``push_rejected`` is a lost race and is a plain retry. Both were exit 1 with
    no ``reason`` key, so an orchestrating agent had to parse the human message
    or guess. Exit stays **1** — this changes what the failure reports, not how
    it is classified against the gate.
    """
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")
    stub = _make_linear_stub()
    merge = MagicMock(
        side_effect=close_merge.CloseMergeError(
            "boom", reason=reason, conflict=reason == "merge_conflict"
        )
    )

    result, _ = _invoke(repo, db_path, run_id, stub, merge_push=merge)

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == reason, (
        f"a step-6 {reason} must surface the reason close_merge computed, so a "
        f"caller can tell a conflict from a lost push race"
    )
    # The merge did not land, so nothing downstream may have run (AC-3).
    assert "merged" not in payload
    assert fetch_run_status(db_path, run_id) == "open"
    stub.transition_to_done.assert_not_called()


def test_close_transition_failure_after_merge_leaves_run_open(
    repo: Path, db_path: Path
) -> None:
    """A Linear Done-transition failure AFTER merge+push exits 1 and leaves the
    ledger consistent — the run stays ``open`` and no ``close`` event is written,
    so close is re-drivable (CAL-1002). Tagged with the #233 ``reason`` — the
    merge already landed, so this is not a gate refusal."""
    from harness.linear import LinearRequestError

    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")
    stub = _make_linear_stub(
        raise_on_transition=LinearRequestError("permission denied")
    )

    result, merge = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == "ticket_transition_failed"
    assert payload["merged"] is True
    assert payload["run_id"] == run_id

    # Merge+push happened before the failure; the Done transition was attempted.
    # Three times, not once (#301): a request error is the transient arm, so the
    # verb absorbs it up to the bound before reporting the same failure it
    # always reported. The merge count is what stays at one — a transition retry
    # never re-enters step 6.
    merge.assert_called_once()
    assert stub.transition_to_done.call_count == 3
    stub.transition_to_done.assert_called_with("CAL-572")

    # Ledger stays consistent: run still open, and no *landed* close event.
    # #263 records the failure itself as a close event carrying
    # ``outcome='failed'`` and the merged SHA, so the invariant this asserts is
    # "nothing reads as landed", not "nothing was written".
    assert fetch_run_status(db_path, run_id) == "open"
    assert fetch_landed_close_events(db_path, run_id) == []


def test_close_transition_unconfirmed_after_merge_leaves_run_open(
    repo: Path, db_path: Path
) -> None:
    """The CAL-992 incident, reproduced at the ``close`` mapping layer: the
    transition mutation does not raise, but the backend could not confirm the
    post-write state — must exit 1 with the distinct ``ticket_transition_unconfirmed``
    reason (#233), not report success, and leave the run open/re-drivable."""
    from harness.tracker_errors import TrackerTransitionUnconfirmed

    run_id, path, branch = _seed_run_with_worktree(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo), "pass")
    stub = _make_linear_stub(
        raise_on_transition=TrackerTransitionUnconfirmed(
            "issueUpdate reported success, but the post-write state is In Review"
        )
    )

    result, merge = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == "ticket_transition_unconfirmed"
    assert payload["merged"] is True
    assert payload["run_id"] == run_id

    # As above (#301): the unconfirmed arm is retried to the bound, the merge is
    # not re-entered, and the reported failure is unchanged.
    merge.assert_called_once()
    assert stub.transition_to_done.call_count == 3
    stub.transition_to_done.assert_called_with("CAL-572")

    # Ledger stays consistent, and — unlike a successful close — the worktree
    # and branch are never torn down (teardown is reached only after a closed
    # ledger row).
    assert fetch_run_status(db_path, run_id) == "open"
    assert fetch_landed_close_events(db_path, run_id) == []  # #263: none landed
    assert path.exists()
    assert branch in _local_branches(repo)


def test_close_retry_after_unconfirmed_transition_completes_normally(
    repo: Path, db_path: Path
) -> None:
    """The recovery property the CAL-992 incident lacked: re-running the
    identical ``harness close`` once the tracker is healthy completes the run —
    the merge (already landed) is a no-op, the transition is retried, and the
    ticket is confirmed Done (#233)."""
    from harness.tracker_errors import TrackerTransitionUnconfirmed

    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")

    failing = _make_linear_stub(
        raise_on_transition=TrackerTransitionUnconfirmed("not yet Done")
    )
    first = _invoke(repo, db_path, run_id, failing)
    assert first[0].exit_code == 1, first[0].output
    assert fetch_run_status(db_path, run_id) == "open"

    confirming = _make_linear_stub()
    second, merge = _invoke(repo, db_path, run_id, confirming)

    assert second.exit_code == 0, second.output
    payload = json.loads(second.output)
    assert payload["ticket_done"] is True
    merge.assert_called_once()
    assert fetch_run_status(db_path, run_id) == "closed"
    # #263: the ledger now holds the failed attempt *and* the landed one — the
    # pair is the retry story. Exactly one of them reads as landed.
    assert len(fetch_close_events(db_path, run_id)) == 2
    assert len(fetch_landed_close_events(db_path, run_id)) == 1


def test_close_event_write_failure_leaves_ledger_consistent(
    repo: Path, db_path: Path
) -> None:
    """If the close-event write fails, the status flip must NOT persist.

    CAL-1002: before the fix ``_mark_run_closed`` committed ``status='closed'``
    on its own connection, then emitted the ``close`` event on a *second*
    connection — a failed event write left a terminal ``closed`` run with no
    close event, an inconsistent ledger no retry can repair (nothing re-drives a
    terminal run). The fix makes the flip and the event one ``BEGIN IMMEDIATE``
    transaction, so a failed event write rolls the flip back: the run stays
    ``open`` and re-drivable.
    """
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")
    _install_close_event_failure_trigger(db_path)

    stub = _make_linear_stub()
    result, merge = _invoke(repo, db_path, run_id, stub)

    # The ledger write failed → exit 1 (unexpected error, not a gate refusal).
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert "reason" not in payload

    # The failure is AFTER merge+push and the Done transition.
    merge.assert_called_once()
    stub.transition_to_done.assert_called_once_with("CAL-572")

    # Atomic: the failed close-event write rolled the status flip back.
    assert fetch_run_status(db_path, run_id) == "open"
    # Still *no* close event at all, not merely none that landed: the injected
    # trigger aborts every ``close`` INSERT, so #263's best-effort observation
    # write is suppressed and writes nothing either. This is the one place the
    # two writers meet.
    assert fetch_close_events(db_path, run_id) == []

    # #261: the completion stamps ride the same transaction, so the rollback
    # leaves them unset exactly as it leaves ``status`` unflipped.
    assert fetch_run_completion(db_path, run_id) == (None, None)


# ---------------------------------------------------------------------------
# #261: close stamps completed_at + duration_ms on the run row
# ---------------------------------------------------------------------------


def test_close_stamps_completed_at_equal_to_the_close_event_timestamp(
    repo: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-1: the closed run's ``completed_at`` is the close event's timestamp.

    ``close`` reads the clock **once** (``closed_at = iso_z()``) and uses it for
    the event payload, the event's ``timestamp`` column, and — as of #261 — the
    run row's ``completed_at``. Asserting equality with the event's own
    timestamp, rather than merely non-null, is what pins the single reading: a
    second ``iso_z()`` call for the run row would still be non-null and would
    still look right, but the two columns would drift by the write latency.
    """
    _pin_close_clock(monkeypatch)
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")

    result, _merge = _invoke(repo, db_path, run_id, _make_linear_stub())
    assert result.exit_code == 0, result.output

    completed_at, _duration_ms = fetch_run_completion(db_path, run_id)
    assert completed_at is not None
    assert completed_at == fetch_close_event_timestamp(db_path, run_id)
    assert completed_at == FIXED_CLOSED_AT


def test_close_stamps_duration_ms_measured_from_started_at(
    repo: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-2: ``duration_ms`` is the exact elapsed milliseconds, not a range.

    Both ends of the measurement are fixed — ``_seed_open_run`` writes
    ``started_at`` as ``SEEDED_STARTED_AT`` and the clock is pinned to
    ``FIXED_CLOSED_AT`` — so the assertion is a single integer. A tolerance
    window here would pass just as happily on a duration computed from the
    wrong origin (e.g. the review event) as on the right one.
    """
    _pin_close_clock(monkeypatch)
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")

    result, _merge = _invoke(repo, db_path, run_id, _make_linear_stub())
    assert result.exit_code == 0, result.output

    _completed_at, duration_ms = fetch_run_completion(db_path, run_id)
    assert duration_ms == EXPECTED_DURATION_MS


def test_close_measures_duration_from_the_production_started_at_shape(
    repo: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two stored shapes of ``started_at`` must yield the same number.

    ``harness start`` writes a plain ``.isoformat()`` (``+00:00``) while the
    close clock is the trailing-``Z`` form, so every other duration assertion in
    this file runs on a shape **no production run row carries**. Seeding the
    ``+00:00`` form is what proves the parse reads the live ledger, not just the
    fixture.
    """
    _pin_close_clock(monkeypatch)
    run_id = _seed_open_run(db_path, repo, started_at="2026-06-10T00:00:00+00:00")
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")

    result, _merge = _invoke(repo, db_path, run_id, _make_linear_stub())
    assert result.exit_code == 0, result.output

    _completed_at, duration_ms = fetch_run_completion(db_path, run_id)
    assert duration_ms == EXPECTED_DURATION_MS


@pytest.mark.parametrize(
    "started_at",
    [
        pytest.param("not-a-timestamp", id="unparseable"),
        pytest.param("2026-06-10T00:00:00", id="tz-naive"),
    ],
)
def test_close_lands_with_a_null_duration_when_started_at_cannot_be_differenced(
    repo: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch, started_at: str
) -> None:
    """A ``started_at`` the verb cannot difference costs the duration, not the close.

    By the time the stamps are written the merge has landed and the ticket is
    Done, and the only recovery is re-running ``close`` — which would re-read the
    same bad cell and fail identically, stranding a merged run ``open`` forever.
    So the derived value degrades to ``NULL`` (a state the column and both
    readers already model) while ``completed_at``, which needs no input beyond
    the clock reading the verb already holds, is stamped regardless.
    """
    _pin_close_clock(monkeypatch)
    run_id = _seed_open_run(db_path, repo, started_at=started_at)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")

    result, _merge = _invoke(repo, db_path, run_id, _make_linear_stub())
    assert result.exit_code == 0, result.output
    assert fetch_run_status(db_path, run_id) == "closed"

    completed_at, duration_ms = fetch_run_completion(db_path, run_id)
    assert completed_at == FIXED_CLOSED_AT
    assert duration_ms is None


def test_harness_runs_renders_the_duration_close_stamped(
    repo: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stamped duration reaches the reader — the point of storing it.

    ``harness runs`` already knew how to render ``duration_ms``; before #261 a
    closed run had none, so the column read blank for every run the verb loop
    ever finished. This is the only assertion that spans close → reader, rather
    than seeding the column the reader is asked to print.
    """
    _pin_close_clock(monkeypatch)
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    _emit_review(db_path, run_id, head, "pass")
    close_result, _merge = _invoke(repo, db_path, run_id, _make_linear_stub())
    assert close_result.exit_code == 0, close_result.output

    listed = cli_runner.invoke(app, ["runs", "--db", str(db_path)])
    assert listed.exit_code == 0, listed.output
    assert f"{EXPECTED_DURATION_MS}ms" in listed.stdout


# ---------------------------------------------------------------------------
# #301: transient merge/transition failures are absorbed by a bounded retry
# ---------------------------------------------------------------------------


def _landed_close_payload(db_path: Path, run_id: str) -> dict[str, Any]:
    """The landed ``close`` event's payload — where the retry record lands."""
    events = fetch_landed_close_events(db_path, run_id)
    assert len(events) == 1, f"expected exactly one landed close event, got {len(events)}"
    return dict(json.loads(events[0][1]))


def _failed_close_payload(db_path: Path, run_id: str) -> dict[str, Any]:
    """The terminal ``close`` event a failed close records — exactly one (#263)."""
    events = fetch_close_events(db_path, run_id)
    assert len(events) == 1, (
        f"a retried failure must still record exactly ONE terminal close event; "
        f"got {len(events)} — a retry that re-entered the recording boundary "
        f"would double-count the refusal denominator (#263)"
    )
    return dict(json.loads(events[0][1]))


@pytest.mark.parametrize("reason", sorted(close_retry.RETRYABLE_MERGE_REASONS))
def test_a_transient_merge_failure_is_attempted_exactly_three_times(
    repo: Path, db_path: Path, retry_delays: list[float], reason: str
) -> None:
    """AC-6: the bound is counted through the verb, not inferred.

    Parametrized over the retry set itself, so a reason moved into that set
    without the verb actually retrying it fails here.
    """
    run_id = _seed_open_run(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo), "pass")
    merge = MagicMock(side_effect=close_merge.CloseMergeError("boom", reason=reason))

    result, _ = _invoke(repo, db_path, run_id, _make_linear_stub(), merge_push=merge)

    assert merge.call_count == 3, (
        f"a {reason} must be attempted 3 times (initial + 2 retries); "
        f"got {merge.call_count}"
    )
    assert retry_delays == [2.0, 8.0]
    # AC-9: exhausting the retry reports exactly what it reported before.
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == reason
    assert "merged" not in payload
    assert fetch_run_status(db_path, run_id) == "open"


@pytest.mark.parametrize(
    "reason",
    sorted(set(get_args(close_merge.CloseMergeReason)) - close_retry.RETRYABLE_MERGE_REASONS),
)
def test_a_deterministic_merge_failure_is_attempted_exactly_once(
    repo: Path, db_path: Path, retry_delays: list[float], reason: str
) -> None:
    """AC-3: everything outside the retry set keeps its single-attempt behaviour.

    The subject set is *derived* — the whole declared vocabulary minus what the
    retry claims — so a reason added to ``close_merge`` lands here automatically
    rather than being silently uncovered. ``merge_conflict`` is the one the
    ticket names explicitly: retrying it in any form is out of scope, because a
    second attempt conflicts identically.
    """
    run_id = _seed_open_run(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo), "pass")
    merge = MagicMock(side_effect=close_merge.CloseMergeError("boom", reason=reason))

    result, _ = _invoke(repo, db_path, run_id, _make_linear_stub(), merge_push=merge)

    assert merge.call_count == 1, (
        f"{reason} needs work on the run branch or the machine — retrying it "
        f"burns the budget and delays the escalation; got {merge.call_count} attempts"
    )
    assert retry_delays == []
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["reason"] == reason


def test_a_merge_that_recovers_on_the_second_attempt_lands_and_records_it(
    repo: Path, db_path: Path, retry_delays: list[float]
) -> None:
    """The case the whole ticket exists for: a lost push race closes in one turn."""
    run_id = _seed_open_run(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo), "pass")
    merge = MagicMock(
        side_effect=[close_merge.CloseMergeError("lost the race", reason="push_rejected"), None]
    )

    result, _ = _invoke(repo, db_path, run_id, _make_linear_stub(), merge_push=merge)

    assert result.exit_code == 0, result.output
    assert merge.call_count == 2
    assert retry_delays == [2.0]
    # AC-10: the absorbed failure is observable in the ledger, not silently hidden.
    payload = _landed_close_payload(db_path, run_id)
    assert payload["retries"] == 1
    assert payload["retried_reasons"] == ["push_rejected"]


def test_a_close_with_nothing_to_absorb_records_a_zero_retry_count(
    repo: Path, db_path: Path
) -> None:
    """The common path stays legible: ``retries: 0`` and no reason list at all.

    A scalar always present is what makes ``retries`` aggregatable; omitting the
    list when it is empty keeps the payload the same shape it had.
    """
    run_id = _seed_open_run(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo), "pass")

    result, _ = _invoke(repo, db_path, run_id, _make_linear_stub())
    assert result.exit_code == 0, result.output

    payload = _landed_close_payload(db_path, run_id)
    assert payload["retries"] == 0
    assert "retried_reasons" not in payload


@pytest.mark.parametrize(
    ("raised", "kind"),
    [
        (TrackerTransitionUnconfirmed("post-write state is In Review"), "unconfirmed"),
        (TrackerRequestError("503 from the tracker"), "request_error"),
    ],
)
def test_a_transient_transition_failure_is_attempted_exactly_three_times(
    repo: Path, db_path: Path, retry_delays: list[float], raised: Exception, kind: str
) -> None:
    """AC-6 for step 7, and AC-7: the retry re-attempts *only* the transition.

    The merge assertion is the load-bearing half. Retrying at any outer boundary
    would re-enter step 6 and push a second merge for a close that already
    landed one.
    """
    assert kind in close_retry.RETRYABLE_TICKET_KINDS
    run_id = _seed_open_run(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo), "pass")
    stub = _make_linear_stub(raise_on_transition=raised)

    result, merge = _invoke(repo, db_path, run_id, stub)

    assert stub.transition_to_done.call_count == 3
    assert merge.call_count == 1, (
        "a step-7 retry must not re-enter step 6 — the merge already landed"
    )
    assert retry_delays == [2.0, 8.0]
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["merged"] is True
    assert fetch_run_status(db_path, run_id) == "open"


def test_a_missing_ticket_is_attempted_exactly_once(
    repo: Path, db_path: Path, retry_delays: list[float]
) -> None:
    """AC-3: the not-found arm is deterministic, so it escalates immediately.

    Its sibling arm — a request error — is retried, and both exit as
    ``ticket_transition_failed``. Only the attempt count can tell them apart
    from outside, which is what makes this test the one that proves AC-1's
    widening is actually load-bearing rather than decorative.
    """
    run_id = _seed_open_run(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo), "pass")
    stub = _make_linear_stub(raise_on_transition=TrackerNotFound("no such issue"))

    result, _merge = _invoke(repo, db_path, run_id, stub)

    assert stub.transition_to_done.call_count == 1
    assert retry_delays == []
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == "ticket_transition_failed"
    assert payload["merged"] is True


def test_an_exhausted_transition_retry_records_one_event_carrying_the_count(
    repo: Path, db_path: Path, retry_delays: list[float]
) -> None:
    """AC-10 + AC-7: one terminal event, carrying what the retry absorbed.

    A degrading tracker is the thing the count exists to surface — absorbed
    silently, it would look like a healthy close that merely took 10s longer.
    """
    run_id = _seed_open_run(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo), "pass")
    stub = _make_linear_stub(raise_on_transition=TrackerRequestError("503"))

    result, _merge = _invoke(repo, db_path, run_id, stub)
    assert result.exit_code == 1, result.output

    payload = _failed_close_payload(db_path, run_id)
    assert payload["reason"] == "ticket_transition_failed"
    assert payload["retries"] == 2
    assert payload["retried_reasons"] == [
        "ticket_transition_request_error",
        "ticket_transition_request_error",
    ]
    # The merge landed before step 7, and the record must still say so.
    assert payload["merged_sha"] == _head_sha(repo)


@pytest.mark.parametrize(
    ("seed", "expected_reason"),
    [
        ("stale", "stale_review"),
        ("none", "no_passing_review"),
    ],
)
def test_a_gate_refusal_reaches_no_retry_at_all(
    repo: Path, db_path: Path, retry_delays: list[float], seed: str, expected_reason: str
) -> None:
    """AC-3: every exit-2 refusal is upstream of the retry, so it cannot retry.

    Asserted on the observable — nothing was attempted and nothing slept —
    rather than on the code's ordering, which a later edit could change without
    touching this test.
    """
    run_id = _seed_open_run(db_path, repo)
    if seed == "stale":
        _emit_review(db_path, run_id, "0" * 40, "pass")

    stub = _make_linear_stub()
    result, merge = _invoke(repo, db_path, run_id, stub)

    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == expected_reason
    assert merge.call_count == 0
    assert stub.transition_to_done.call_count == 0
    assert retry_delays == []


def test_a_tracker_less_repo_enters_no_retry_path(
    repo: Path, db_path: Path, retry_delays: list[float]
) -> None:
    """AC-5: with no tracker there is no transition, so there is nothing to retry.

    The close still lands; ``ticket_done`` stays ``False`` exactly as before.
    """
    run_id = _seed_open_run(db_path, repo)
    _emit_review(db_path, run_id, _head_sha(repo), "pass")

    with patch.object(close_mod, "tracker_client", return_value=None):
        merge = MagicMock(return_value=None)
        with patch("harness.close_merge.merge_run_branch", merge):
            result = cli_runner.invoke(
                app,
                ["close", "CAL-572", "--repo", str(repo), "--db", str(db_path),
                 "--run-id", run_id, "--json"],
            )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ticket_done"] is False
    assert payload["merged"] is True
    assert retry_delays == []
    assert _landed_close_payload(db_path, run_id)["retries"] == 0


def test_the_verb_retries_exactly_the_kinds_the_retry_table_declares() -> None:
    """The verb-level cases above are parametrized from the table; this pins the table.

    Without it, moving ``not_found`` into ``RETRYABLE_TICKET_KINDS`` would flip
    the parametrization and the single-attempt case would simply stop being
    generated — a test disappearing rather than failing.
    """
    assert set(get_args(TicketFailureKind)) - close_retry.RETRYABLE_TICKET_KINDS == {
        "not_found"
    }
    assert (
        set(get_args(close_merge.CloseMergeReason)) - close_retry.RETRYABLE_MERGE_REASONS
    ) == {"merge_conflict", "merge_failed", "git_status_failed", "worktree_create_failed"}


