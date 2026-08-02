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

# size: the design verb's acceptance suite (ADR 0007) — engine invocation, the
# degrade-and-record failure contract, the marked ticket comment, and the ledger
# event. The degrade paths are only checkable against the success path they degrade
# from, so they stay together.

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import unittest.mock as mock
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness._time import iso_z
from harness.cli import app, design_protocol
from harness.cli import design as design_mod
from harness.cli import design_tracker as design_tracker_mod
from harness.design_marker import DESIGN_MARKER
from harness.loop_budget import DEFAULT_ENGINE_TIMEOUT_SECONDS
from harness.state import store
from harness.tracker_errors import TrackerNotFound, TrackerRequestError

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
            "SELECT run_id, data_json, duration_ms FROM events "
            "WHERE event_type = 'design' ORDER BY id"
        ) as cur,
    ):
        rows = await cur.fetchall()
    return [
        {
            "run_id": r[0],
            "data": json.loads(r[1]),
            # The **column**, not ``json_extract(data_json, ...)``: #264 records
            # the verb's latency in the typed column ``harness events`` already
            # surfaces. Widening the dict is non-breaking — every existing caller
            # indexes ``["data"]`` or ``["run_id"]``.
            "duration_ms": None if r[2] is None else int(r[2]),
        }
        for r in rows
    ]


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
        with mock.patch.object(
            design_tracker_mod, "tracker_client", return_value=tracker_stub
        ):
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
    # The fixture repo writes no CONTEXT.md, so this measures the *wiring* — that
    # the unconfigured ceiling reaching the runner is the one `load_loop_budget`
    # resolves — rather than pinning a literal a retune has to chase (#291).
    assert captured["timeout"] == DEFAULT_ENGINE_TIMEOUT_SECONDS


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
    # A legitimate sequential re-run (this invocation started well after the
    # prior one finished) must never be flagged as concurrent (#236).
    assert "concurrent_prior_at" not in events[1]["data"]
    assert "concurrent_prior_at" not in json.loads(second.output.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# #236 — a nested/overlapping invocation is detected and flagged
# ---------------------------------------------------------------------------


def test_concurrent_invocation_flags_the_later_writer(repo: Path, db_path: Path) -> None:
    """The incident this ticket exists for: a second invocation's event lands
    on the ledger while this invocation's engine is still running. The later
    writer — the one that silently becomes authoritative — must flag it."""
    _seed_open_run(db_path, repo)
    stub = _tracker_stub()
    captured: dict[str, Any] = {}

    async def _insert_stray_event() -> str:
        from harness._time import iso_z as _iso_z

        ts = _iso_z()
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO events (run_id, event_type, timestamp, data_json) "
                "VALUES (?, 'design', ?, ?)",
                (_RUN_ID, ts, json.dumps({"run_id": _RUN_ID, "status": "ok"})),
            )
            await conn.commit()
        return ts

    async def _runner(**_: Any) -> design_mod.RunResult:
        captured["injected_ts"] = await _insert_stray_event()
        return design_mod.RunResult(stdout=_submit(), stderr="", returncode=0)

    result = _invoke(repo, db_path, _runner, tracker_stub=stub)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["concurrent_prior_at"] == captured["injected_ts"]
    events = design_events(db_path)
    assert events[-1]["data"]["concurrent_prior_at"] == captured["injected_ts"]
    assert "warning:" in result.output
    assert _RUN_ID in result.output


def test_first_design_has_no_flag(repo: Path, db_path: Path) -> None:
    """No prior event at all: nothing to flag."""
    _seed_open_run(db_path, repo)

    result = _invoke(repo, db_path, _make_runner(_submit()), tracker_stub=_tracker_stub())

    assert result.exit_code == 0, result.output
    assert "concurrent_prior_at" not in json.loads(result.output.strip().splitlines()[-1])
    assert "concurrent_prior_at" not in design_events(db_path)[0]["data"]


def test_a_concurrent_event_on_another_run_is_ignored(repo: Path, db_path: Path) -> None:
    """Scope is one run: an overlapping ``design`` event on a *different*
    run_id must never flag this one."""
    _seed_open_run(db_path, repo)
    other_run_id = "01JOTHERRUNXXXXXXXXXXXXX01"

    async def _seed_other_run() -> None:
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
                "state_json, inputs_json, base_branch, worktree_path, worktree_branch, "
                "ticket, started_at, pid) VALUES (?, '', 0, 'open', '{}', '{}', 'dev', "
                "?, ?, '999', ?, 1)",
                (
                    other_run_id,
                    str(repo) + "-other",
                    f"harness/{other_run_id}",
                    datetime.now(UTC).isoformat(),
                ),
            )
            await conn.commit()

    async def _insert_other_run_event() -> None:
        from harness._time import iso_z as _iso_z

        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO events (run_id, event_type, timestamp, data_json) "
                "VALUES (?, 'design', ?, ?)",
                (other_run_id, _iso_z(), json.dumps({"run_id": other_run_id})),
            )
            await conn.commit()

    _sync(_seed_other_run())

    async def _runner(**_: Any) -> design_mod.RunResult:
        await _insert_other_run_event()
        return design_mod.RunResult(stdout=_submit(), stderr="", returncode=0)

    result = _invoke(repo, db_path, _runner, tracker_stub=_tracker_stub())

    assert result.exit_code == 0, result.output
    assert "concurrent_prior_at" not in json.loads(result.output.strip().splitlines()[-1])


def test_failed_attempt_carries_the_flag(repo: Path, db_path: Path) -> None:
    """The nastier variant: a stray invocation that *fails* still supersedes a
    good design, and the exit-3 failure must carry the same evidence."""
    _seed_open_run(db_path, repo)
    stub = _tracker_stub()
    captured: dict[str, Any] = {}

    async def _insert_stray_event() -> str:
        from harness._time import iso_z as _iso_z

        ts = _iso_z()
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO events (run_id, event_type, timestamp, data_json) "
                "VALUES (?, 'design', ?, ?)",
                (_RUN_ID, ts, json.dumps({"run_id": _RUN_ID, "status": "ok"})),
            )
            await conn.commit()
        return ts

    async def _runner(**_: Any) -> design_mod.RunResult:
        captured["injected_ts"] = await _insert_stray_event()
        raise design_mod.EngineTimeoutError(600.0)

    result = _invoke(repo, db_path, _runner, tracker_stub=stub)

    assert result.exit_code == design_mod.EXIT_DESIGN_FAILED
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["concurrent_prior_at"] == captured["injected_ts"]
    assert payload["reason"] == "engine_timeout"
    events = design_events(db_path)
    assert events[-1]["data"]["concurrent_prior_at"] == captured["injected_ts"]
    assert "warning:" in result.output


def test_detection_failure_does_not_break_the_design(repo: Path, db_path: Path) -> None:
    """Detection fails open: a broken reader never wedges the write (D4)."""
    _seed_open_run(db_path, repo)

    with mock.patch.object(
        design_mod, "_read_latest_design_timestamp", side_effect=RuntimeError("db locked")
    ):
        result = _invoke(repo, db_path, _make_runner(_submit()), tracker_stub=_tracker_stub())

    assert result.exit_code == 0, result.output
    assert "concurrent_prior_at" not in json.loads(result.output.strip().splitlines()[-1])
    events = design_events(db_path)
    assert len(events) == 1
    assert events[0]["data"]["status"] == "ok"


def test_microsecond_boundary_uses_parsed_not_string_comparison(
    repo: Path, db_path: Path
) -> None:
    """A prior timestamp with no microseconds must still compare correctly
    against an ``invoked_at`` that has them — ``parse_iso_z``, never a bare
    string comparison (#236). ``datetime.isoformat()`` omits a zero
    microsecond field, so lexicographically ``"...:00Z"`` sorts *after*
    ``"...:00.5Z"`` — a string comparison would misjudge a genuinely earlier,
    non-concurrent prior event as an overlap.

    Exercises :func:`design_mod._record_design_event` directly (the helper
    level), rather than a full CLI invocation whose real-clock ``invoked_at``
    cannot be pinned to this exact boundary.
    """
    _seed_open_run(db_path, repo)

    async def _seed_prior_event() -> None:
        await store.init_db(db_path)
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO events (run_id, event_type, timestamp, data_json) "
                "VALUES (?, 'design', ?, ?)",
                (_RUN_ID, "2026-07-28T00:00:00Z", json.dumps({"run_id": _RUN_ID})),
            )
            await conn.commit()

    _sync(_seed_prior_event())

    data = design_mod.DesignEventData(
        run_id=_RUN_ID,
        status="ok",
        engine="claude",
        model="opus",
        designed_at="2026-07-28T00:00:00.500001Z",
        invoked_at="2026-07-28T00:00:00.500000Z",
        design_hash="abc123",
        grounded_sha="def456",
    )

    recorded = _sync(design_mod._record_design_event(db_path, data))

    assert recorded.concurrent_prior_at is None, (
        "the prior event (00:00:00, no microseconds) is chronologically "
        "earlier than invoked_at (00:00:00.5) and must not be flagged; a "
        "bare string comparison sorts '...:00Z' after '...:00.5Z' and would "
        "wrongly flag it"
    )


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


def test_submit_failure_records_the_unparseable_payload(
    repo: Path, db_path: Path
) -> None:
    """#277: the event must diagnose, not just tally.

    The failure is silent by design (D4 degrades and the run ships), so this
    event is the only evidence a later reader gets.
    """
    _seed_open_run(db_path, repo)
    stdout = 'SUBMIT: {"design_markdown": "### Data model\n'

    result = _invoke(repo, db_path, _make_runner(stdout), tracker_stub=_tracker_stub())

    assert result.exit_code == design_mod.EXIT_DESIGN_FAILED
    data = design_events(db_path)[0]["data"]
    assert data["submit_excerpt"] == stdout
    assert data["stdout_chars"] == len(stdout)


def test_submit_failure_excerpt_stays_bounded_in_the_ledger(
    repo: Path, db_path: Path
) -> None:
    """A 17 KB stdout must not land in the ledger whole (#271/#272/#273 sizes)."""
    _seed_open_run(db_path, repo)
    stdout = "SUBMIT: {" + "x" * 17_000

    result = _invoke(repo, db_path, _make_runner(stdout), tracker_stub=_tracker_stub())

    assert result.exit_code == design_mod.EXIT_DESIGN_FAILED
    data = design_events(db_path)[0]["data"]
    assert data["stdout_chars"] == len(stdout), "the true length is still recorded"
    assert len(data["submit_excerpt"]) <= design_protocol.SUBMIT_EXCERPT_MAX_CHARS


def test_the_excerpt_never_reaches_stdout(repo: Path, db_path: Path) -> None:
    """DesignOutput promises only the parsed payload escapes, never reasoning.

    The excerpt is exactly that reasoning; it is for an operator reading the
    ledger, not for the orchestrator's context.
    """
    _seed_open_run(db_path, repo)
    stdout = "SUBMIT: {UNIQUEMARK"

    result = _invoke(repo, db_path, _make_runner(stdout), tracker_stub=_tracker_stub())

    assert "UNIQUEMARK" not in result.output
    assert "submit_excerpt" not in result.output


def test_a_successful_design_records_neither_field(repo: Path, db_path: Path) -> None:
    """exclude_none=True keeps the ok shape exactly as pinned since #211."""
    _seed_open_run(db_path, repo)

    result = _invoke(repo, db_path, _make_runner(_submit()), tracker_stub=_tracker_stub())

    assert result.exit_code == 0
    data = design_events(db_path)[0]["data"]
    assert "submit_excerpt" not in data
    assert "stdout_chars" not in data


def test_a_timeout_records_no_excerpt(repo: Path, db_path: Path) -> None:
    """The child was killed; there is no stdout to quote, and an empty one lies."""
    _seed_open_run(db_path, repo)

    runner = _make_raising_runner(design_mod.EngineTimeoutError(600.0))

    result = _invoke(repo, db_path, runner, tracker_stub=_tracker_stub())

    assert result.exit_code == design_mod.EXIT_DESIGN_FAILED
    data = design_events(db_path)[0]["data"]
    assert data["reason"] == "engine_timeout"
    assert "submit_excerpt" not in data
    assert "stdout_chars" not in data


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


# ---------------------------------------------------------------------------
# #218 — the tracker boundary: each degrade branch, and the one expected exit 1
# ---------------------------------------------------------------------------


def test_docstring_exit_codes_document_the_comment_post_failure() -> None:
    """The exit-1 entry must name the comment-post failure and its empty ledger.

    ``design`` has exactly one *expected* exit-1 path: the engine produced a
    design but :func:`post_design_comment` could not publish it, so the verb
    raises before ``_record_design_event`` and the run is left with **no**
    ``design`` event. That asymmetry is what an orchestrator branches on — every
    exit-3 degrade records an attempt that satisfies ``review``'s ``no_design``
    check, while this one does not, and the next ``review`` refuses until
    ``design`` is re-run. Documenting exit 1 as only "unexpected error" hides the
    one exit-1 case a caller can actually plan for; pinned against
    ``test_a_failed_comment_post_exits_1_and_records_nothing``.

    Asserts on the load-bearing substrings rather than the sentence, so rewording
    that keeps the facts does not break the test.
    """
    doc = design_mod.__doc__ or ""
    block = doc[doc.index("Exit codes") :]
    one_entry = block[block.index("* 1") : block.index("* 2")]

    assert "comment" in one_entry, (
        "exit 1 covers a design that could not be posted to its ticket, not just "
        "unexpected errors; name it in the exit-1 entry"
    )
    assert "event" in one_entry, (
        "the comment-post failure deliberately records no design event — the "
        "fact that distinguishes it from every exit-3 degrade; say so"
    )
    assert "unexpected error" in one_entry, (
        "the pre-existing exit-1 causes (git failure, DB error) must survive "
        "the addition, not be replaced by it"
    )


def _recording_runner(ran: dict[str, bool], stdout: str = "") -> Any:
    """A runner that records having been called, rather than raising.

    A runner that raises would prove nothing: ``_produce_design``'s broad
    ``except Exception`` catches it and records a ``failed`` / ``engine_error``
    event, so the verb still exits 3 and a naive assertion still passes — for
    the wrong reason. The flag is the only honest proof the engine was skipped.
    """

    async def _runner(**_: Any) -> design_mod.RunResult:
        ran["called"] = True
        return design_mod.RunResult(
            stdout=stdout or _submit(), stderr="", returncode=0
        )

    return _runner


def test_a_run_without_a_ticket_degrades_before_the_tracker(
    repo: Path, db_path: Path
) -> None:
    """A NULL ``runs.ticket`` degrades even though the tracker *is* resolvable.

    ``runs.ticket`` is nullable, so a run carrying none is a legitimate state,
    not a corrupt row. Supplying a working tracker stub is what makes this
    branch distinguishable from the config-error branch the suite already
    covers: the client resolved fine and was still never consulted, so the
    degrade can only have come from the missing ticket.
    """
    _seed_open_run(db_path, repo, ticket=None)
    stub = _tracker_stub()
    ran = {"called": False}

    result = _invoke(repo, db_path, _recording_runner(ran), tracker_stub=stub)

    assert result.exit_code == design_mod.EXIT_DESIGN_FAILED, result.output
    assert ran["called"] is False
    events = design_events(db_path)
    assert len(events) == 1
    assert events[0]["data"]["status"] == "failed"
    assert events[0]["data"]["reason"] == "no_ticket_spec"
    # Four branches collapse onto one ``reason``; ``detail`` is the only
    # discriminator, so assert which of them ran.
    assert "no ticket" in events[0]["data"]["detail"]
    stub.fetch_issue.assert_not_awaited()
    stub.post_comment.assert_not_awaited()


@pytest.mark.parametrize(
    "exc",
    [
        TrackerNotFound("issue 211 does not exist"),
        TrackerRequestError("tracker returned HTTP 503"),
    ],
    ids=["not_found", "request_error"],
)
def test_a_failed_ticket_fetch_degrades_and_records(
    repo: Path, db_path: Path, exc: Exception
) -> None:
    """Both arms of the fetch ``except`` map to the same recorded degrade.

    ``fetch_ticket_spec`` catches ``TrackerNotFound`` and ``TrackerRequestError``
    in one clause; asserting only one leaves the other's mapping unproven at the
    cost of a single parametrize line.
    """
    _seed_open_run(db_path, repo)
    stub = _tracker_stub()
    stub.fetch_issue = mock.AsyncMock(side_effect=exc)
    ran = {"called": False}

    result = _invoke(repo, db_path, _recording_runner(ran), tracker_stub=stub)

    assert result.exit_code == design_mod.EXIT_DESIGN_FAILED, result.output
    assert ran["called"] is False
    events = design_events(db_path)
    assert len(events) == 1
    assert events[0]["data"]["status"] == "failed"
    assert events[0]["data"]["reason"] == "no_ticket_spec"
    detail = events[0]["data"]["detail"]
    assert "211" in detail, "the recorded detail names which ticket was unreadable"
    assert str(exc) in detail, "and carries the tracker's own message"
    stub.post_comment.assert_not_awaited()


def test_a_failed_comment_post_exits_1_and_records_nothing(
    repo: Path, db_path: Path
) -> None:
    """The one *expected* exit 1 — and the one failure that records no event.

    The comment is the artifact ADR 0007 specifies. Recording a ``design`` event
    for a design nobody can read would leave the ledger claiming an artifact
    that does not exist, so the verb raises before ``_record_design_event``. The
    empty ledger is the recovery mechanism, not an oversight: the run's next
    ``review`` refuses with ``no_design`` until ``design`` is re-run, which is
    why the error text names the re-run.
    """
    _seed_open_run(db_path, repo)
    stub = _tracker_stub()
    stub.post_comment = mock.AsyncMock(
        side_effect=TrackerRequestError("tracker returned HTTP 502")
    )

    result = _invoke(repo, db_path, _make_runner(_submit()), tracker_stub=stub)

    # Explicitly *not* EXIT_DESIGN_FAILED: a design was produced, so this is a
    # publish failure, not a failure to design.
    assert result.exit_code == 1, result.output
    assert result.exit_code != design_mod.EXIT_DESIGN_FAILED
    assert design_events(db_path) == []
    stub.post_comment.assert_awaited_once()
    payload = json.loads(result.output)
    assert "error" in payload
    # Unlike every exit-3 degrade, this carries no ``reason`` — the asymmetry an
    # orchestrator branches on.
    assert "reason" not in payload
    assert "re-run" in payload["error"]


# ---------------------------------------------------------------------------
# #264 — the verb's own latency, in the ledger's typed duration column
# ---------------------------------------------------------------------------


def _pin_clock(elapsed_ms: int) -> Any:
    """Patch ``design``'s ``iso_z`` with distinct successive readings.

    A constant stub cannot distinguish one clock read from two, so an
    implementation that read the clock a second time for ``designed_at`` would
    still satisfy the equality — and the duration would pass vacuously at 0
    (#261's lesson).
    """
    start = datetime(2026, 7, 31, 8, 0, 0, tzinfo=UTC)
    readings = iter([iso_z(start), iso_z(start + timedelta(milliseconds=elapsed_ms))])
    return mock.patch.object(
        design_mod, "iso_z", lambda *_a, **_k: next(readings, iso_z(start))
    )


def test_design_records_its_duration_in_the_event_column(
    repo: Path, db_path: Path
) -> None:
    """AC-1: a successful design records the engine's latency as whole ms.

    This is the case the ticket exists for — ``design``'s latency previously had
    to be reconstructed by subtracting ``designed_at`` from ``invoked_at``, the
    archaeology that raising the engine timeout 600 → 720 required.
    """
    _seed_open_run(db_path, repo)
    with _pin_clock(1_500_000):
        result = _invoke(
            repo, db_path, _make_runner(_submit()), tracker_stub=_tracker_stub()
        )
    assert result.exit_code == 0, result.output

    (event,) = design_events(db_path)
    assert event["duration_ms"] == 1_500_000
    assert isinstance(event["duration_ms"], int)


def test_design_payload_gains_no_duration_key(repo: Path, db_path: Path) -> None:
    """One quantity, one home — the payload keeps its exact #263 key set.

    ``invoked_at`` and ``designed_at`` stay (ADR 0009 keeps the two-timestamp
    form because it survives a verb that dies before writing a duration), but the
    derived duration lives only in the column.
    """
    _seed_open_run(db_path, repo)
    with _pin_clock(1_500_000):
        _invoke(repo, db_path, _make_runner(_submit()), tracker_stub=_tracker_stub())

    (event,) = design_events(db_path)
    assert "duration_ms" not in event["data"]


def test_failed_design_records_its_duration_alongside_the_reason(
    repo: Path, db_path: Path
) -> None:
    """AC-2: the degrade-and-record path is timed too.

    A killed engine is the *most* worth timing — it is the row that says how long
    the run waited before giving up. The verb still exits ``EXIT_DESIGN_FAILED``
    with its unchanged reason, so ADR 0007 D4 is not regressed.
    """
    _seed_open_run(db_path, repo)
    runner = _make_raising_runner(design_mod.EngineTimeoutError(600.0))

    with _pin_clock(600_000):
        result = _invoke(repo, db_path, runner, tracker_stub=_tracker_stub())

    assert result.exit_code == design_mod.EXIT_DESIGN_FAILED
    (event,) = design_events(db_path)
    assert event["duration_ms"] == 600_000
    assert event["data"]["status"] == "failed"
    assert event["data"]["reason"] == "engine_timeout"


def test_design_latency_is_one_query_over_the_column(
    repo: Path, db_path: Path
) -> None:
    """AC-3: latency reads from ``duration_ms`` alone.

    The measuring test for the ticket's actual goal: no ``json_extract``, no
    ``designed_at - invoked_at`` subtraction. Item 5 (``harness stats``) is the
    reader this makes possible, so the query shape is asserted, not just the
    number.
    """
    _seed_open_run(db_path, repo)
    with _pin_clock(1_500_000):
        _invoke(repo, db_path, _make_runner(_submit()), tracker_stub=_tracker_stub())

    query = (
        "SELECT MAX(duration_ms) FROM events "
        "WHERE event_type = 'design' AND duration_ms IS NOT NULL"
    )
    assert "json_extract" not in query

    async def _worst() -> int | None:
        async with store.connect(db_path) as conn, conn.execute(query) as cur:
            row = await cur.fetchone()
        return None if row is None or row[0] is None else int(row[0])

    assert _sync(_worst()) == 1_500_000
