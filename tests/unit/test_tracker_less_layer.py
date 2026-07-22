"""The verbs run tracker-less under ``layers.linear: false`` — CAL-1104.

``CONTEXT.md`` advertises ``layers.linear: false`` for a repo not wired to a
tracker, but the engine hard-required Linear: ``start`` validated
``LINEAR_API_KEY`` and fetched the issue, ``close`` validated the key before any
local side effect and transitioned Done, ``reclaim`` reverted the ticket. There
was no code path to open or close a run without a tracker.

These tests pin the four acceptance criteria:

AC-1: layer off + **no** ``LINEAR_API_KEY`` → ``start`` … ``close`` completes green.
AC-2: ``reclaim`` works tracker-less — ledger cleared, branch preserved, no tracker calls.
AC-3: layer **on** + missing key still fails fast exactly as today.
AC-4: covered by ``tests/unit/test_context_template_tracker_fields.py`` (the template).

**How "no tracker calls" is proved.** Each tracker-less test removes
``LINEAR_API_KEY`` from the environment entirely — so the real
:func:`harness.linear.linear_api_key` would raise — *and* replaces
``LinearClient`` with a stub that fails the test if it is ever constructed. A
verb that completes under both conditions demonstrably never reached Linear;
nothing is stubbed into succeeding.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli.review import _park_ticket
from harness.events.emitter import EventEmitter
from harness.state import store

cli_runner = CliRunner()

RUN_ID = "01J0000000000000000000TRKL"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


@pytest.fixture(autouse=True)
def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))


@pytest.fixture(autouse=True)
def _no_linear_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No tracker credentials anywhere — the tracker-less repo's real condition.

    Autouse so a stray key in the developer's environment cannot mask a verb
    that still reaches for Linear. AC-3's tests rely on this too: it is what
    makes "missing key" real rather than simulated.
    """
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throw-away git repo on ``dev`` whose CONTEXT.md turns the layer off.

    The ``repo:`` block carries a ``linear:`` key of its own, mirroring a real
    CONTEXT.md — so these tests also exercise the reader's block scoping through
    the verbs, not just in isolation.

    ``.harness/`` is gitignored exactly as in the real repo (.gitignore:29) so the
    ledger DB the verbs create under it never registers as a dirty worktree — the
    ``dirty_worktree`` gate keys off ``git status --porcelain``, which excludes
    ignored paths.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "dev")
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    (repo_root / ".gitignore").write_text(".harness/\n.worktrees/\n")
    (repo_root / "README.md").write_text("hello\n")
    (repo_root / "CONTEXT.md").write_text(
        "repo:\n"
        "  name: tracker-less-repo\n"
        "  linear: none\n"
        "layers:\n"
        "  linear: false   # this repo has no tracker\n"
        "  feature_specs: true\n"
    )
    _git(repo_root, "add", ".gitignore", "README.md", "CONTEXT.md")
    _git(repo_root, "commit", "-m", "initial")
    return repo_root


@pytest.fixture
def tracked_repo(repo: Path) -> Path:
    """The same repo with the layer back **on** — the AC-3 control."""
    (repo / "CONTEXT.md").write_text(
        "repo:\n  name: tracked-repo\n  linear: CAL\nlayers:\n  linear: true\n"
    )
    _git(repo, "add", "CONTEXT.md")
    _git(repo, "commit", "-m", "layer on")
    return repo


@pytest.fixture
def db_path(repo: Path) -> Path:
    return repo / ".harness" / "harness.db"


def _exploding_client() -> MagicMock:
    """A ``LinearClient`` replacement that fails loudly if ever constructed."""
    return MagicMock(
        side_effect=AssertionError(
            "LinearClient was constructed in a tracker-less run — the verb "
            "reached for the tracker with layers.linear: false"
        )
    )


def _sync(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _head_sha(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _fetch_runs(db_path: Path) -> list[dict[str, Any]]:
    async def _q() -> list[dict[str, Any]]:
        if not db_path.exists():
            return []
        async with store.connect(db_path) as conn:
            conn.row_factory = None
            async with conn.execute(
                "SELECT run_id, ticket, status, worktree_branch FROM runs"
            ) as cur:
                cols = [d[0] for d in cur.description]  # type: ignore[union-attr]
                rows = await cur.fetchall()
        return [dict(zip(cols, row, strict=True)) for row in rows]

    return _sync(_q())


def _seed_open_run(db_path: Path, repo: Path, ticket: str = "RUN-1") -> str:
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
                    RUN_ID,
                    "",
                    0,
                    "open",
                    "{}",
                    "{}",
                    "dev",
                    str(repo),
                    f"harness/{RUN_ID}",
                    ticket,
                    "2026-07-16T00:00:00Z",
                    1234,
                ),
            )
            await conn.commit()

    _sync(_insert())
    return RUN_ID


def _emit_green_review(db_path: Path, run_id: str, sha: str) -> None:
    """A passing review carrying green verify-gate evidence (CAL-1082)."""

    async def _emit() -> None:
        await EventEmitter(db_path).emit(
            run_id=run_id,
            event_type="review",
            data={
                "run_id": run_id,
                "reviewed_sha": sha,
                "verdict": "pass",
                "issues": [],
                "created_at": "2026-07-16T00:00:00Z",
                "gate_ran": True,
                "gate_command": "bash scripts/verify.sh",
                "gate_exit_code": 0,
            },
        )

    _sync(_emit())


# ---------------------------------------------------------------------------
# AC-1 — start runs tracker-less
# ---------------------------------------------------------------------------


def test_ac1_start_opens_a_run_without_a_tracker(repo: Path, db_path: Path) -> None:
    """``start`` opens the run with no key, no fetch, no transition."""
    with patch("harness.tracker.LinearClient", _exploding_client()):
        result = cli_runner.invoke(
            app,
            ["start", "RUN-1", "--repo", str(repo), "--db", str(db_path), "--json"],
        )

    assert result.exit_code == 0, result.output

    rows = _fetch_runs(db_path)
    assert len(rows) == 1
    assert rows[0]["ticket"] == "RUN-1"
    assert rows[0]["status"] == "open"


def test_ac1_start_degrades_ticket_context_to_the_identifier(
    repo: Path, db_path: Path
) -> None:
    """With no tracker to fetch, ``StartOutput.ticket`` is just the identifier.

    The argument is an opaque run identifier: it round-trips verbatim, and every
    field that only a tracker could supply is ``None`` rather than invented.
    """
    with patch("harness.tracker.LinearClient", _exploding_client()):
        result = cli_runner.invoke(
            app,
            [
                "start",
                "my-feature-42",
                "--repo",
                str(repo),
                "--db",
                str(db_path),
                "--json",
            ],
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert payload["ticket"]["identifier"] == "my-feature-42"
    assert payload["ticket"]["title"] is None
    assert payload["ticket"]["description"] is None
    assert payload["ticket"]["url"] is None
    assert payload["ticket"]["id"] is None
    # The run is otherwise fully formed — worktree and base branch are local.
    assert payload["base_branch"] == "dev"
    assert payload["worktree_branch"] == f"harness/{payload['run_id']}"


def test_ac1_start_creates_the_worktree_tracker_less(
    repo: Path, db_path: Path
) -> None:
    """The local half of ``start`` is unchanged — the worktree really exists."""
    with patch("harness.tracker.LinearClient", _exploding_client()):
        result = cli_runner.invoke(
            app,
            ["start", "RUN-1", "--repo", str(repo), "--db", str(db_path), "--json"],
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    worktree = Path(payload["worktree_path"])
    assert worktree.is_dir()
    assert (worktree / "README.md").exists()


def test_ac1_duplicate_start_still_refused_tracker_less(
    repo: Path, db_path: Path
) -> None:
    """The opaque identifier still dedupes: a second start returns the same run.

    Without a tracker there is no canonical identifier to resolve against, so the
    argument itself is the key — the duplicate-run guard must still hold.
    """
    with patch("harness.tracker.LinearClient", _exploding_client()):
        first = cli_runner.invoke(
            app,
            ["start", "RUN-1", "--repo", str(repo), "--db", str(db_path), "--json"],
        )
        second = cli_runner.invoke(
            app,
            ["start", "RUN-1", "--repo", str(repo), "--db", str(db_path), "--json"],
        )

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert json.loads(first.output)["run_id"] == json.loads(second.output)["run_id"]
    assert len(_fetch_runs(db_path)) == 1


# ---------------------------------------------------------------------------
# AC-1 — close runs tracker-less
# ---------------------------------------------------------------------------


def test_ac1_close_merges_without_a_tracker(repo: Path, db_path: Path) -> None:
    """``close`` enforces its gate and merges with no key and no Done transition."""
    run_id = _seed_open_run(db_path, repo)
    _emit_green_review(db_path, run_id, _head_sha(repo))
    merge = MagicMock(return_value=None)

    with (
        patch("harness.tracker.LinearClient", _exploding_client()),
        patch("harness.close_merge.merge_run_branch", merge),
    ):
        result = cli_runner.invoke(
            app,
            [
                "close",
                "RUN-1",
                "--repo",
                str(repo),
                "--db",
                str(db_path),
                "--run-id",
                run_id,
                "--json",
            ],
        )

    assert result.exit_code == 0, result.output
    merge.assert_called_once()

    payload = json.loads(result.output)
    assert payload["merged"] is True
    assert payload["status"] == "closed"


def test_ac1_close_reports_ticket_done_false_tracker_less(
    repo: Path, db_path: Path
) -> None:
    """``ticket_done`` is an honest ``False`` — no tracker was moved to Done.

    The field is the record of a remote side effect. Reporting ``True`` for a
    transition that never happened would make the ledger lie about the one thing
    it exists to attest.
    """
    run_id = _seed_open_run(db_path, repo)
    _emit_green_review(db_path, run_id, _head_sha(repo))

    with (
        patch("harness.tracker.LinearClient", _exploding_client()),
        patch("harness.close_merge.merge_run_branch", MagicMock(return_value=None)),
    ):
        result = cli_runner.invoke(
            app,
            [
                "close",
                "RUN-1",
                "--repo",
                str(repo),
                "--db",
                str(db_path),
                "--run-id",
                run_id,
                "--json",
            ],
        )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["ticket_done"] is False


def test_ac1_close_still_enforces_the_review_gate_tracker_less(
    repo: Path, db_path: Path
) -> None:
    """Tracker-less does not mean gate-less: no passing review still refuses.

    Turning off the tracker must not weaken the gate — it is the one thing
    protecting the merge.
    """
    run_id = _seed_open_run(db_path, repo)  # no review emitted
    merge = MagicMock(return_value=None)

    with (
        patch("harness.tracker.LinearClient", _exploding_client()),
        patch("harness.close_merge.merge_run_branch", merge),
    ):
        result = cli_runner.invoke(
            app,
            [
                "close",
                "RUN-1",
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
    assert json.loads(result.output)["reason"] == "no_passing_review"
    merge.assert_not_called()


# ---------------------------------------------------------------------------
# AC-2 — reclaim runs tracker-less
# ---------------------------------------------------------------------------


def test_ac2_reclaim_clears_the_ledger_without_a_tracker(
    repo: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``reclaim`` reconciles the ledger and skips the revert, with no key.

    ``reclaim`` has no ``--repo`` flag — like its read-side siblings it is
    anchored on the CWD — so the layer is read from the CWD's CONTEXT.md.
    """
    run_id = _seed_open_run(db_path, repo)
    monkeypatch.chdir(repo)

    with patch("harness.tracker.LinearClient", _exploding_client()):
        result = cli_runner.invoke(
            app,
            ["reclaim", run_id, "--db", str(db_path), "--json"],
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["outcome"] == "reclaimed"
    assert payload["ticket"] == "RUN-1"

    # The ledger row is reconciled so a fresh start on the same id is not blocked.
    assert _fetch_runs(db_path)[0]["status"] == "cancelled"


def test_ac2_reclaim_preserves_the_branch_tracker_less(
    repo: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The WIP branch is still preserved — D4 holds without a tracker."""
    run_id = _seed_open_run(db_path, repo)
    monkeypatch.chdir(repo)

    async def _emit_checkpoint() -> None:
        await EventEmitter(db_path).emit(
            run_id=run_id,
            event_type="checkpoint",
            data={"run_id": run_id, "branch": f"harness/{RUN_ID}", "pushed": True},
        )

    _sync(_emit_checkpoint())

    with patch("harness.tracker.LinearClient", _exploding_client()):
        result = cli_runner.invoke(
            app, ["reclaim", run_id, "--db", str(db_path), "--json"]
        )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["branch_preserved"] == f"harness/{RUN_ID}"


def test_ac2_stale_sweep_is_a_clean_noop_tracker_less(
    repo: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--stale`` no-ops tracker-less rather than crashing the Build routine.

    The sweep keys entirely on the tracker's ``updatedAt`` — with no tracker
    there is no In-Progress ticket state to enumerate, so the honest answer is
    "swept nothing". The Build routine runs this every tick as a pre-flight, so
    it must degrade to a no-op, not an error.
    """
    monkeypatch.chdir(repo)

    with patch("harness.tracker.LinearClient", _exploding_client()):
        result = cli_runner.invoke(
            app,
            [
                "reclaim",
                "--stale",
                "--project",
                "Anything",
                "--db",
                str(db_path),
                "--json",
            ],
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["reclaimed"] == []
    assert payload["scanned"] == 0


# ---------------------------------------------------------------------------
# AC-3 — layer on + missing key still fails fast, exactly as today
# ---------------------------------------------------------------------------


def test_ac3_start_still_fails_fast_when_layer_on_and_key_missing(
    tracked_repo: Path, db_path: Path
) -> None:
    """The control: ``layers.linear: true`` + no key → the same exit 2 as today."""
    result = cli_runner.invoke(
        app,
        ["start", "CAL-570", "--repo", str(tracked_repo), "--db", str(db_path), "--json"],
    )

    assert result.exit_code == 2, result.output
    assert "LINEAR_API_KEY" in result.output
    assert _fetch_runs(db_path) == []


def test_ac3_close_still_fails_fast_when_layer_on_and_key_missing(
    tracked_repo: Path, db_path: Path
) -> None:
    """``close`` still validates the key *before* any local side effect."""
    run_id = _seed_open_run(db_path, tracked_repo, ticket="CAL-572")
    _emit_green_review(db_path, run_id, _head_sha(tracked_repo))
    merge = MagicMock(return_value=None)

    with patch("harness.close_merge.merge_run_branch", merge):
        result = cli_runner.invoke(
            app,
            [
                "close",
                "CAL-572",
                "--repo",
                str(tracked_repo),
                "--db",
                str(db_path),
                "--run-id",
                run_id,
                "--json",
            ],
        )

    assert result.exit_code == 2, result.output
    assert "LINEAR_API_KEY" in result.output
    # Fail-fast means fail *before* the merge — no half-landed tree.
    merge.assert_not_called()


def test_ac3_a_repo_with_no_context_file_still_requires_a_tracker(
    tmp_path: Path, db_path: Path
) -> None:
    """No CONTEXT.md at all → the layer defaults on, so today's behaviour holds.

    The conservative default matters most here: a repo the reader cannot parse
    must not silently degrade into a tracker-less run.
    """
    bare = tmp_path / "bare"
    bare.mkdir()
    _git(bare, "init", "-b", "dev")
    _git(bare, "config", "user.email", "test@example.com")
    _git(bare, "config", "user.name", "Test")
    (bare / "README.md").write_text("hello\n")
    _git(bare, "add", "README.md")
    _git(bare, "commit", "-m", "initial")

    result = cli_runner.invoke(
        app,
        ["start", "CAL-570", "--repo", str(bare), "--db", str(bare / "h.db"), "--json"],
    )

    assert result.exit_code == 2, result.output
    assert "LINEAR_API_KEY" in result.output


# ---------------------------------------------------------------------------
# tracker: github with NO github: block — a misconfiguration that fails LOUD
# ---------------------------------------------------------------------------
# The counterpart to the tracker-less (``none``) case above (CAL-1197/CAL-1105):
# ``none`` is a clean no-op, but a ``tracker: github`` that omits its ``github:``
# config block is a *misconfiguration*, so every verb that needs the tracker
# rejects it through the uniform verb-error contract (exit 2) — never a raw
# traceback, and never the tracker-less no-op path that ``linear_enabled`` used to
# conflate ``github`` into. (A *complete* github config resolves a working
# GitHubClient — see ``test_github.py``.) ``review`` is the one deliberate
# exception: its transition is non-essential bookkeeping.


@pytest.fixture
def repo_github(repo: Path) -> Path:
    """The same git repo, but CONTEXT selects github *without* its config block."""
    (repo / "CONTEXT.md").write_text(
        "repo:\n  name: gh-repo\n  project: Build\ntracker: github\n"
    )
    _git(repo, "add", "CONTEXT.md")
    _git(repo, "commit", "-m", "tracker: github")
    return repo


def test_start_github_tracker_fails_loud_no_side_effects(
    repo_github: Path, db_path: Path
) -> None:
    """``start`` rejects ``tracker: github`` with exit 2 and leaves no run row."""
    result = cli_runner.invoke(
        app,
        ["start", "GH-1", "--repo", str(repo_github), "--db", str(db_path), "--json"],
    )
    assert result.exit_code == 2, result.output
    assert "github" in result.output.lower()
    assert _fetch_runs(db_path) == []


def test_close_github_tracker_fails_loud_before_merge(
    repo_github: Path, db_path: Path
) -> None:
    """A passing-gate ``close`` still refuses ``tracker: github`` (exit 2) — and
    the misconfig stops it *before* the merge, so nothing is pushed."""
    run_id = _seed_open_run(db_path, repo_github)
    _emit_green_review(db_path, run_id, _head_sha(repo_github))
    merge = MagicMock(return_value=None)
    with patch("harness.close_merge.merge_run_branch", merge):
        result = cli_runner.invoke(
            app,
            [
                "close",
                "RUN-1",
                "--repo",
                str(repo_github),
                "--db",
                str(db_path),
                "--run-id",
                run_id,
                "--json",
            ],
        )
    assert result.exit_code == 2, result.output
    assert "github" in result.output.lower()
    merge.assert_not_called()


def test_defer_github_tracker_fails_loud(
    repo_github: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``defer`` no longer mistakes ``github`` for tracker-less (the old
    ``linear_enabled`` gate did) — it fails loudly (exit 2), not a silent skip."""
    monkeypatch.chdir(repo_github)
    result = cli_runner.invoke(
        app, ["defer", "GH-1", "--reason", "x", "--db", str(db_path), "--json"]
    )
    assert result.exit_code == 2, result.output
    assert "github" in result.output.lower()
    assert "skipped_no_tracker" not in result.output
    # A config gap surfaces as the machine-readable tracker_config reason.
    assert json.loads(result.output)["reason"] == "tracker_config"


def test_reclaim_stale_github_tracker_fails_loud(
    repo_github: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``reclaim --stale`` fails loudly for ``github`` rather than sweeping
    nothing — the tracker-less no-op is reserved for ``tracker: none``."""
    monkeypatch.chdir(repo_github)
    result = cli_runner.invoke(
        app,
        ["reclaim", "--stale", "--project", "Build", "--db", str(db_path), "--json"],
    )
    assert result.exit_code == 2, result.output
    assert "github" in result.output.lower()


def test_review_transition_tolerates_github_tracker(repo_github: Path) -> None:
    """``review``'s transition is the one deliberate exception: a misconfigured
    tracker (here github with no config block) is swallowed (a verdict must never
    be lost to a tracker problem), so ``_park_ticket`` is a silent no-op — it
    returns without raising and never constructs a client."""
    with patch("harness.tracker.LinearClient", _exploding_client()):
        result = _sync(_park_ticket(repo_github, "GH-1", to="in_review"))
    assert result is None
