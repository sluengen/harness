"""Tests for ``harness design`` — #211 (ADR 0007, proposal ``design-verb``).

AC-1: on an open run the verb invokes the engine and, on success, appends a
      ``design`` event carrying ``design_hash`` + ``grounded_sha`` bound to the
      run, posts the marked ticket comment, and emits valid ``DesignOutput``.
AC-2: engine failure and timeout each append a ``status="failed"`` design event
      with a reason, post no comment, and exit non-zero (degrade-and-record, D4).
AC-3: no open run / unknown run-id refuses per the verb refusal conventions.
AC-4: the comment marker is single-sourced (``test_design_marker.py``).

No test spawns a real engine: every one injects a fake runner, so the protocol
from #210 is exercised without the ``claude`` binary.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import unittest.mock as mock
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli import design as design_mod
from harness.design_marker import DESIGN_MARKER
from harness.state import store

cli_runner = CliRunner()

_RUN_ID = "01JRUNDESIGNXXXXXXXXXXXX01"
_DESIGN = "### Data model\n\nNo change.\n\n### Test strategy\n\nUnit tests.\n"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


@pytest.fixture(autouse=True)
def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Permit the tmp test tree through the ``HARNESS_WORKSPACE_ROOTS`` gate."""
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "dev")
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    (repo_root / "README.md").write_text("hello\n")
    _git(repo_root, "add", "README.md")
    _git(repo_root, "commit", "-m", "initial")
    return repo_root


@pytest.fixture
def db_path(repo: Path) -> Path:
    return repo / ".harness" / "harness.db"


def _head_sha(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _sync(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _seed_open_run(db_path: Path, repo: Path, *, ticket: str | None = "211") -> str:
    """Insert an ``open`` runs row whose worktree_path == repo; return run_id."""

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
                    _RUN_ID,
                    "",
                    0,
                    "open",
                    "{}",
                    "{}",
                    "dev",
                    str(repo),
                    f"harness/{_RUN_ID}",
                    ticket,
                    datetime.now(UTC).isoformat(),
                    1234,
                ),
            )
            await conn.commit()

    _sync(_insert())
    return _RUN_ID


async def _fetch_design_events(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT run_id, data_json FROM events WHERE event_type = 'design' "
            "ORDER BY id"
        ) as cur,
    ):
        rows = await cur.fetchall()
    return [{"run_id": r[0], "data": json.loads(r[1])} for r in rows]


def design_events(db_path: Path) -> list[dict[str, Any]]:
    return _sync(_fetch_design_events(db_path))


def _make_runner(stdout: str, *, stderr: str = "", returncode: int = 0) -> Any:
    async def _runner(
        *,
        cmd: list[str],
        stdin: str,
        env: dict[str, str],
        cwd: Path | None,
        timeout: float | None = None,
    ) -> design_mod.RunResult:
        return design_mod.RunResult(stdout=stdout, stderr=stderr, returncode=returncode)

    return _runner


def _make_capturing_runner(stdout: str, captured: dict[str, Any]) -> Any:
    """A fake runner recording the ``cmd``/``stdin``/``cwd`` it was handed."""

    async def _runner(
        *,
        cmd: list[str],
        stdin: str,
        env: dict[str, str],
        cwd: Path | None,
        timeout: float | None = None,
    ) -> design_mod.RunResult:
        captured["cmd"] = cmd
        captured["stdin"] = stdin
        captured["cwd"] = cwd
        captured["timeout"] = timeout
        return design_mod.RunResult(stdout=stdout, stderr="", returncode=0)

    return _runner


def _make_raising_runner(exc: BaseException) -> Any:
    async def _runner(
        *,
        cmd: list[str],
        stdin: str,
        env: dict[str, str],
        cwd: Path | None,
        timeout: float | None = None,
    ) -> design_mod.RunResult:
        raise exc

    return _runner


def _submit(design: str = _DESIGN) -> str:
    return "thinking about it\nSUBMIT: " + json.dumps({"design_markdown": design})


def _tracker_stub(
    *, title: str = "Add the design verb", description: str = "## Problem\n\nNo verb.\n"
) -> Any:
    stub = mock.MagicMock()
    stub.fetch_issue = mock.AsyncMock(
        return_value={"title": title, "description": description, "labels": []}
    )
    stub.post_comment = mock.AsyncMock(return_value=None)
    return stub


def _invoke(
    repo: Path,
    db_path: Path,
    runner: Any,
    *,
    run_id: str | None = _RUN_ID,
    model: str | None = None,
    tracker_stub: Any | None = None,
) -> Any:
    argv = ["design", "--repo", str(repo), "--db", str(db_path), "--json"]
    if run_id is not None:
        argv += ["--run-id", run_id]
    if model is not None:
        argv += ["--model", model]
    with mock.patch.object(design_mod, "_default_runner", runner):
        if tracker_stub is None:
            # Hermetic env: no LINEAR_API_KEY, so the tracker cannot be resolved
            # and the verb takes its no-ticket-spec degrade path.
            return cli_runner.invoke(app, argv)
        with mock.patch.object(design_mod, "tracker_client", return_value=tracker_stub):
            return cli_runner.invoke(app, argv)


# ---------------------------------------------------------------------------
# AC-1 — the success path
# ---------------------------------------------------------------------------


def test_success_records_an_ok_event_bound_to_the_run(repo: Path, db_path: Path) -> None:
    """A valid SUBMIT appends one ``design`` event with the recorded provenance."""
    _seed_open_run(db_path, repo)
    stub = _tracker_stub()

    result = _invoke(repo, db_path, _make_runner(_submit()), tracker_stub=stub)

    assert result.exit_code == 0, result.output
    events = design_events(db_path)
    assert len(events) == 1
    data = events[0]["data"]
    assert events[0]["run_id"] == _RUN_ID
    assert data["run_id"] == _RUN_ID
    assert data["status"] == "ok"
    assert data["engine"] == "claude"
    assert data["model"] == "opus"
    assert data["grounded_sha"] == _head_sha(repo)
    assert "reason" not in data
    assert data["designed_at"].endswith("Z")


def test_success_records_the_sha256_of_the_design(repo: Path, db_path: Path) -> None:
    """``design_hash`` is the design's content hash — the measurable binding."""
    _seed_open_run(db_path, repo)

    result = _invoke(repo, db_path, _make_runner(_submit()), tracker_stub=_tracker_stub())

    assert result.exit_code == 0, result.output
    expected = hashlib.sha256(_DESIGN.encode("utf-8")).hexdigest()
    assert design_events(db_path)[0]["data"]["design_hash"] == expected


def test_success_posts_the_marked_comment_once(repo: Path, db_path: Path) -> None:
    """The artifact lands on the ticket as one marked comment (ADR 0007)."""
    _seed_open_run(db_path, repo)
    stub = _tracker_stub()

    result = _invoke(repo, db_path, _make_runner(_submit()), tracker_stub=stub)

    assert result.exit_code == 0, result.output
    stub.post_comment.assert_awaited_once()
    ticket, body = stub.post_comment.await_args.args
    assert ticket == "211"
    assert body.startswith(DESIGN_MARKER)
    assert _DESIGN in body


def test_success_emits_the_design_output_contract(repo: Path, db_path: Path) -> None:
    """The printed JSON is exactly ``DesignOutput``'s documented keys."""
    _seed_open_run(db_path, repo)

    result = _invoke(repo, db_path, _make_runner(_submit()), tracker_stub=_tracker_stub())

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert set(payload) == {
        "run_id",
        "design_markdown",
        "design_hash",
        "grounded_sha",
        "model",
        "status",
    }
    assert payload["status"] == "ok"
    assert payload["design_markdown"] == _DESIGN
    assert payload["grounded_sha"] == _head_sha(repo)


def test_printed_output_omits_the_engine_reasoning(repo: Path, db_path: Path) -> None:
    """Context economy: the engine's pre-SUBMIT chatter never escapes the verb."""
    _seed_open_run(db_path, repo)
    chatter = "let me enumerate every file in the repository first"
    stdout = f"{chatter}\n{_submit()}"

    result = _invoke(repo, db_path, _make_runner(stdout), tracker_stub=_tracker_stub())

    assert result.exit_code == 0, result.output
    assert chatter not in result.output


def test_engine_runs_read_only_on_opus_in_the_worktree(
    repo: Path, db_path: Path
) -> None:
    """The command is #210's builder output — plan mode, Opus, cwd = worktree."""
    _seed_open_run(db_path, repo)
    captured: dict[str, Any] = {}

    result = _invoke(
        repo, db_path, _make_capturing_runner(_submit(), captured), tracker_stub=_tracker_stub()
    )

    assert result.exit_code == 0, result.output
    assert captured["cmd"] == [
        "claude",
        "-p",
        "--permission-mode",
        "plan",
        "--model",
        "opus",
    ]
    assert captured["cwd"] == repo
    assert captured["timeout"] == 600


def test_prompt_carries_the_fetched_ticket_spec(repo: Path, db_path: Path) -> None:
    """The design answers to the ticket, so its title/description reach the engine."""
    _seed_open_run(db_path, repo)
    captured: dict[str, Any] = {}
    stub = _tracker_stub(title="A distinctive title", description="A distinctive body")

    result = _invoke(
        repo, db_path, _make_capturing_runner(_submit(), captured), tracker_stub=stub
    )

    assert result.exit_code == 0, result.output
    assert "A distinctive title" in captured["stdin"]
    assert "A distinctive body" in captured["stdin"]


def test_model_flag_overrides_the_opus_default(repo: Path, db_path: Path) -> None:
    """``--model`` is the host/testing override, recorded as what actually ran."""
    _seed_open_run(db_path, repo)
    captured: dict[str, Any] = {}

    result = _invoke(
        repo,
        db_path,
        _make_capturing_runner(_submit(), captured),
        model="sonnet",
        tracker_stub=_tracker_stub(),
    )

    assert result.exit_code == 0, result.output
    assert captured["cmd"][-2:] == ["--model", "sonnet"]
    assert design_events(db_path)[0]["data"]["model"] == "sonnet"


def test_re_running_appends_a_second_event(repo: Path, db_path: Path) -> None:
    """Idempotent re-run: append-only, the latest event authoritative."""
    _seed_open_run(db_path, repo)
    stub = _tracker_stub()

    first = _invoke(repo, db_path, _make_runner(_submit()), tracker_stub=stub)
    second = _invoke(
        repo, db_path, _make_runner(_submit("### Data model\n\nRevised.\n")), tracker_stub=stub
    )

    assert first.exit_code == 0 and second.exit_code == 0
    events = design_events(db_path)
    assert len(events) == 2
    assert events[0]["data"]["design_hash"] != events[1]["data"]["design_hash"]
    assert stub.post_comment.await_count == 2


# ---------------------------------------------------------------------------
# AC-2 — degrade and record (ADR 0007 D4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stdout", "expected_reason"),
    [
        ("I have decided not to comply.", "no_submit"),
        ("SUBMIT: {not json at all}", "malformed_submit"),
        ('SUBMIT: {"design_markdown": "   "}', "malformed_submit"),
    ],
)
def test_unusable_engine_output_degrades_and_records(
    repo: Path, db_path: Path, stdout: str, expected_reason: str
) -> None:
    """Each unusable-output shape records a distinguishable failed attempt."""
    _seed_open_run(db_path, repo)
    stub = _tracker_stub()

    result = _invoke(repo, db_path, _make_runner(stdout), tracker_stub=stub)

    assert result.exit_code == design_mod.EXIT_DESIGN_FAILED
    events = design_events(db_path)
    assert len(events) == 1
    assert events[0]["data"]["status"] == "failed"
    assert events[0]["data"]["reason"] == expected_reason
    assert events[0]["data"]["detail"]
    assert "design_hash" not in events[0]["data"]
    stub.post_comment.assert_not_awaited()
    assert json.loads(result.output.strip().splitlines()[-1])["reason"] == expected_reason


def test_engine_timeout_degrades_and_records(repo: Path, db_path: Path) -> None:
    """A killed engine is a recorded failed attempt, not a hang (CAL-1004 shape)."""
    _seed_open_run(db_path, repo)
    stub = _tracker_stub()
    runner = _make_raising_runner(design_mod.EngineTimeoutError(600.0))

    result = _invoke(repo, db_path, runner, tracker_stub=stub)

    assert result.exit_code == design_mod.EXIT_DESIGN_FAILED
    events = design_events(db_path)
    assert len(events) == 1
    assert events[0]["data"]["status"] == "failed"
    assert events[0]["data"]["reason"] == "engine_timeout"
    assert "600s" in events[0]["data"]["detail"]
    stub.post_comment.assert_not_awaited()


def test_engine_invocation_error_degrades_and_records(repo: Path, db_path: Path) -> None:
    """An engine that cannot be spawned at all is recorded, never swallowed."""
    _seed_open_run(db_path, repo)
    stub = _tracker_stub()
    runner = _make_raising_runner(FileNotFoundError("claude: not found"))

    result = _invoke(repo, db_path, runner, tracker_stub=stub)

    assert result.exit_code == design_mod.EXIT_DESIGN_FAILED
    events = design_events(db_path)
    assert len(events) == 1
    assert events[0]["data"]["reason"] == "engine_error"
    assert "claude: not found" in events[0]["data"]["detail"]
    stub.post_comment.assert_not_awaited()


def test_unreadable_ticket_spec_degrades_without_running_the_engine(
    repo: Path, db_path: Path
) -> None:
    """No spec, no design: recorded as failed rather than designed from nothing.

    The prompt is built from the ticket, and ``start`` persists no title/body —
    so a tracker the verb cannot resolve leaves nothing to design against.
    Running the engine anyway would post a confidently-ungrounded design.
    """
    _seed_open_run(db_path, repo)
    ran = {"called": False}

    async def _runner(**_: Any) -> design_mod.RunResult:
        ran["called"] = True
        return design_mod.RunResult(stdout=_submit(), stderr="", returncode=0)

    result = _invoke(repo, db_path, _runner)

    assert result.exit_code == design_mod.EXIT_DESIGN_FAILED
    assert ran["called"] is False
    events = design_events(db_path)
    assert len(events) == 1
    assert events[0]["data"]["status"] == "failed"
    assert events[0]["data"]["reason"] == "no_ticket_spec"


def test_a_recorded_failure_still_names_the_engine_and_model(
    repo: Path, db_path: Path
) -> None:
    """A failed attempt records what was attempted, so the ledger is readable."""
    _seed_open_run(db_path, repo)

    result = _invoke(repo, db_path, _make_runner("no submit here"), tracker_stub=_tracker_stub())

    assert result.exit_code == design_mod.EXIT_DESIGN_FAILED
    data = design_events(db_path)[0]["data"]
    assert data["engine"] == "claude"
    assert data["model"] == "opus"


# ---------------------------------------------------------------------------
# AC-3 — refusals follow the verb conventions
# ---------------------------------------------------------------------------


def test_unknown_run_id_refuses_exit_2_without_an_event(
    repo: Path, db_path: Path
) -> None:
    """An unknown run-id is an invocation error — no engine, no event."""
    _seed_open_run(db_path, repo)

    result = _invoke(
        repo, db_path, _make_runner(_submit()), run_id="01JNOSUCHRUNXXXXXXXXXXXX01"
    )

    assert result.exit_code == 2
    assert design_events(db_path) == []
    assert "error" in json.loads(result.output.strip().splitlines()[-1])


def test_no_open_run_for_the_worktree_refuses_exit_2(repo: Path, db_path: Path) -> None:
    """With no run ever opened here there is nothing to design for."""
    result = _invoke(repo, db_path, _make_runner(_submit()), run_id=None)

    assert result.exit_code == 2
    assert design_events(db_path) == []


def test_a_closed_run_is_not_designable(repo: Path, db_path: Path) -> None:
    """Only a ``status='open'`` run resolves — the shared resolver's contract."""
    _seed_open_run(db_path, repo)

    async def _close_it() -> None:
        async with store.connect(db_path) as conn:
            await conn.execute(
                "UPDATE runs SET status = 'closed' WHERE run_id = ?", (_RUN_ID,)
            )
            await conn.commit()

    _sync(_close_it())

    result = _invoke(repo, db_path, _make_runner(_submit()))

    assert result.exit_code == 2
    assert design_events(db_path) == []


# ---------------------------------------------------------------------------
# The shared engine-subprocess seam — this change's watchlist outcome
# ---------------------------------------------------------------------------


def test_the_engine_subprocess_driver_is_not_duplicated() -> None:
    """One driver serves both engine verbs (the watchlist seam extraction).

    ``design`` needs the identical bounded subprocess driver ``review`` owned —
    spawn, feed stdin, kill and reap on timeout. A second copy differing only in
    which exception it raises is exactly the duplication ``code-quality`` Part A
    forbids, so the driver was extracted to ``harness.cli._engine`` and each verb
    keeps only a thin translator to its own ``VerbError``.
    """
    cli_dir = Path(design_mod.__file__).parent
    spawners = sorted(
        path.name
        for path in cli_dir.glob("*.py")
        if "create_subprocess_exec" in path.read_text(encoding="utf-8")
    )
    assert spawners == ["_engine.py"], (
        f"the engine subprocess driver must live only in harness/cli/_engine.py, "
        f"found a spawner in: {spawners}"
    )


def test_both_verbs_translate_the_one_neutral_timeout_error() -> None:
    """``review`` and ``design`` share the neutral error the driver raises."""
    from harness.cli import _engine
    from harness.cli import review as review_mod

    assert design_mod.EngineTimeoutError is _engine.EngineTimeoutError
    assert review_mod.EngineTimeoutError is _engine.EngineTimeoutError
    assert design_mod.RunResult is _engine.RunResult
