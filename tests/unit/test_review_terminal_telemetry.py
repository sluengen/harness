"""#262 — ``review`` records a terminal event on **every** exit path.

``review`` wrote an event only when a verdict parsed. Every other terminal path
returned without writing anything: an engine timeout, a tripped spend breaker,
``no_design``, ``no_gate_evidence``, ``gate_failed``, the sandbox wall. So the
ledger held verdicts and **no denominator** — "how often does review succeed?"
and "how often does the engine time out?" were unanswerable, not merely slow.

Per [ADR 0009] the event type stays ``review``; a non-success is distinguished
by an ``outcome`` field, following ``design``'s proved ``status: ok | failed``
shape. Two payload models rather than one loosened model: ``ReviewEventData``
keeps every field the close gate reads **required**, and refusals use the
separate :class:`~harness.events.payloads.ReviewRefusalEventData`. Loosening
``reviewed_sha`` / ``verdict`` to optional would have re-opened exactly the
CAL-1012 hazard the typed contract exists to close.

These tests pin:

* AC-1 — one test per terminal path, asserting **exactly one** event (a
  double-emit fails, not just a missing one);
* AC-2 — every path's exit code is unchanged from today's behaviour;
* AC-3 — a refusal event cannot open the close gate;
* AC-4 — an observation write that raises changes neither exit code nor output;
* AC-5 — ``duration_ms`` / ``invoked_at`` are populated on a passing event;
* AC-6 — verb success rate is one SQL query with no timestamp arithmetic;
* and the hazard the ticket's own design missed: a refusal must **not** consume
  a review cycle. ``_count_review_events`` counts every ``review`` row, so
  writing refusals under the same event type would charge a run for engine
  spend it never incurred — the same trap #259 had to dodge for inherited
  passes, and a direct contradiction of the recorded contract that an
  ``engine_timeout`` costs no cycle.

They inject a fake engine runner and seed the ledger directly, exactly like
``test_review_breakers.py`` and ``test_review_verify_gate.py``.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import unittest.mock as mock
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli import review as review_mod
from harness.cli._engine import EngineTimeoutError
from harness.cli._review_gate import certify_head
from harness.cli.review_protocol import NO_DESIGN_REASON, NO_SUBMIT_SENTINEL
from harness.events.emitter import EventEmitter
from harness.events.payloads import (
    NO_SUBMIT_REASON,
    REVIEW_OUTCOME_FAILED,
    REVIEW_OUTCOME_OK,
    REVIEW_OUTCOME_PATH,
    REVIEW_UNEXPECTED_REASON,
    ReviewRefusalEventData,
)
from harness.loop_budget import REVIEW_CYCLE_CEILING_REASON
from harness.state import store
from tests._ledger import seed_design_event

cli_runner = CliRunner()

_RUN_ID = "01JRUNTELEMETRYXXXXXXXXX01"
_PASS_LINE = 'SUBMIT: {"verdict": "pass", "issues": []}\n'
_FAIL_LINE = 'SUBMIT: {"verdict": "fail", "issues": ["nope"]}\n'
_DEFER_LINE = 'SUBMIT: {"verdict": "defer", "issues": ["out of scope"]}\n'
_BWRAP = "bwrap: No permissions to create a new namespace"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture(autouse=True)
def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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


def _sync(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _write_context(repo: Path, verify: str | None = "bash scripts/verify.sh") -> None:
    body = "```yaml\nrepo:\n  name: t\n"
    if verify is not None:
        body += f'verify: "{verify}"\n'
    body += "```\n"
    (repo / "CONTEXT.md").write_text(body)


def _seed_run(
    db_path: Path,
    repo: Path,
    *,
    started_at: datetime | None = None,
    prior_fail_reviews: int = 0,
    design: bool = True,
) -> str:
    async def _insert() -> None:
        await store.init_db(db_path)
        started = (started_at or datetime.now(UTC)).isoformat()
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
                    "262",
                    started,
                    1234,
                ),
            )
            for _ in range(prior_fail_reviews):
                await conn.execute(
                    "INSERT INTO events (run_id, event_type, timestamp, data_json) "
                    "VALUES (?, 'review', ?, ?)",
                    (
                        _RUN_ID,
                        started,
                        json.dumps({"verdict": "fail", "reviewed_sha": "deadbeef"}),
                    ),
                )
            await conn.commit()

    _sync(_insert())
    if design:
        seed_design_event(db_path, _RUN_ID)
    return _RUN_ID


def _runner(stdout: str = _PASS_LINE, stderr: str = "", returncode: int = 0) -> Any:
    async def _run(
        *,
        cmd: list[str],
        stdin: str,
        env: dict[str, str],
        cwd: Path | None,
        timeout: float | None = None,
    ) -> review_mod.RunResult:
        return review_mod.RunResult(stdout=stdout, stderr=stderr, returncode=returncode)

    return _run


def _invoke(repo: Path, db_path: Path, runner: Any | None = None, *extra: str) -> Any:
    argv = [
        "review",
        "--repo",
        str(repo),
        "--db",
        str(db_path),
        "--run-id",
        _RUN_ID,
        "--json",
        *extra,
    ]
    with mock.patch.object(review_mod, "_default_runner", runner or _runner()):
        return cli_runner.invoke(app, argv)


def _events(db_path: Path) -> list[dict[str, Any]]:
    async def _fetch() -> list[dict[str, Any]]:
        async with (
            store.connect(db_path) as conn,
            conn.execute(
                "SELECT data_json FROM events WHERE event_type = 'review' ORDER BY id"
            ) as cur,
        ):
            rows = await cur.fetchall()
        return [json.loads(r[0]) for r in rows]

    return _sync(_fetch())


def _green(repo: Path) -> tuple[str, ...]:
    """The gate-evidence flags a review needs when ``CONTEXT.md`` configures one."""
    log = repo / "gate.log"
    log.write_text("all green\n")
    return ("--gate-exit", "0", "--gate-log", str(log))


# ---------------------------------------------------------------------------
# AC-1 + AC-2: every terminal path writes exactly one event, exit code unchanged
# ---------------------------------------------------------------------------


def test_engine_timeout_records_one_event_and_still_exits_three(
    repo: Path, db_path: Path
) -> None:
    _write_context(repo)
    _seed_run(db_path, repo)

    async def _boom(**_: Any) -> Any:
        raise EngineTimeoutError(timeout=720.0)

    with mock.patch.object(review_mod, "run_engine_subprocess", _boom):
        result = _invoke(repo, db_path, review_mod._default_runner, *_green(repo))

    assert result.exit_code == review_mod.EXIT_INFRA_FAILURE
    events = _events(db_path)
    assert len(events) == 1, events
    assert events[0][REVIEW_OUTCOME_PATH.removeprefix("$.")] == REVIEW_OUTCOME_FAILED
    assert events[0]["reason"] == review_mod.ENGINE_TIMEOUT_REASON
    assert "verdict" not in events[0]


def test_breaker_trip_records_one_event_and_still_exits_four(
    repo: Path, db_path: Path
) -> None:
    _write_context(repo)
    _seed_run(db_path, repo, prior_fail_reviews=5)

    result = _invoke(repo, db_path, None, *_green(repo))

    assert result.exit_code == review_mod.EXIT_BREAKER_TRIPPED
    # The 5 seeded rows are the prior cycles; the 6th row is this refusal.
    events = _events(db_path)
    assert len(events) == 6, events
    assert events[-1]["reason"] == REVIEW_CYCLE_CEILING_REASON
    assert events[-1][REVIEW_OUTCOME_PATH.removeprefix("$.")] == REVIEW_OUTCOME_FAILED


def test_no_design_records_one_event_and_still_exits_five(repo: Path, db_path: Path) -> None:
    _write_context(repo)
    _seed_run(db_path, repo, design=False)

    result = _invoke(repo, db_path, None, *_green(repo))

    assert result.exit_code == review_mod.EXIT_GATE_FAILED
    events = _events(db_path)
    assert len(events) == 1, events
    assert events[0]["reason"] == NO_DESIGN_REASON


def test_no_gate_evidence_records_one_event_and_still_exits_five(
    repo: Path, db_path: Path
) -> None:
    _write_context(repo)
    _seed_run(db_path, repo)

    result = _invoke(repo, db_path)  # no --gate-exit

    assert result.exit_code == review_mod.EXIT_GATE_FAILED
    events = _events(db_path)
    assert len(events) == 1, events
    assert events[0]["reason"] == review_mod.NO_GATE_EVIDENCE_REASON


def test_red_gate_records_one_event_and_still_exits_five(repo: Path, db_path: Path) -> None:
    _write_context(repo)
    _seed_run(db_path, repo)
    log = repo / "gate.log"
    log.write_text("boom\n")

    result = _invoke(repo, db_path, None, "--gate-exit", "1", "--gate-log", str(log))

    assert result.exit_code == review_mod.EXIT_GATE_FAILED
    events = _events(db_path)
    assert len(events) == 1, events
    assert events[0]["reason"] == review_mod.GATE_FAILED_REASON


def test_sandbox_wall_records_one_event_and_still_exits_three(
    repo: Path, db_path: Path
) -> None:
    _write_context(repo)
    _seed_run(db_path, repo)

    result = _invoke(repo, db_path, _runner(stdout="", stderr=_BWRAP, returncode=1), *_green(repo))

    assert result.exit_code == review_mod.EXIT_INFRA_FAILURE
    events = _events(db_path)
    assert len(events) == 1, events
    assert events[0]["reason"] == review_mod.SANDBOX_INIT_REASON


@pytest.mark.parametrize(
    ("stdout", "verdict"),
    [(_PASS_LINE, "pass"), (_FAIL_LINE, "fail"), (_DEFER_LINE, "defer")],
)
def test_each_verdict_records_exactly_one_ok_event(
    repo: Path, db_path: Path, stdout: str, verdict: str
) -> None:
    _write_context(repo)
    _seed_run(db_path, repo)

    result = _invoke(repo, db_path, _runner(stdout=stdout), *_green(repo))

    assert result.exit_code == 0
    events = _events(db_path)
    assert len(events) == 1, events
    assert events[0]["verdict"] == verdict
    assert events[0][REVIEW_OUTCOME_PATH.removeprefix("$.")] == REVIEW_OUTCOME_OK


def test_a_raise_site_with_no_reason_records_the_unexpected_tag(
    repo: Path, db_path: Path
) -> None:
    """The exit-1 paths carry no ``reason``, so the row would record NULL.

    A failed HEAD read and an engine that cannot be invoked both raise without a
    machine-readable tag. Left as ``None`` they would be indistinguishable from
    each other — and from any future untagged raise — in the very aggregate this
    ticket exists to make readable, so they record
    :data:`REVIEW_UNEXPECTED_REASON`.
    """
    _write_context(repo)
    _seed_run(db_path, repo)

    def _boom(*_: Any, **__: Any) -> str:
        raise OSError("HEAD is unreadable")

    with mock.patch.object(review_mod, "rev_parse_head", _boom):
        result = _invoke(repo, db_path, _runner(), *_green(repo))

    assert result.exit_code == 1
    events = _events(db_path)
    assert len(events) == 1, events
    assert events[0]["reason"] == REVIEW_UNEXPECTED_REASON
    assert events[0][REVIEW_OUTCOME_PATH.removeprefix("$.")] == REVIEW_OUTCOME_FAILED
    assert "verdict" not in events[0]


def test_malformed_submit_records_one_event_as_an_infra_refusal(
    repo: Path, db_path: Path
) -> None:
    """The separate defect this test used to defer to is now fixed (#270).

    It pinned the then-current behaviour deliberately — a missing SUBMIT recorded
    as an ``ok`` outcome carrying a ``fail`` verdict — and its docstring named
    the defect it was setting aside: *a reviewer protocol failure that reads as a
    real* ``fail`` *costs the run a review cycle*. #270 reclassified that path as
    infra, so what belongs here is #262's own property, unchanged in substance:
    the path still records **exactly one** event. Only which shape it is moved,
    from a verdict to a refusal — the same shape
    :func:`test_engine_timeout_records_one_event_and_still_exits_three` asserts,
    which is the point, since both are engines that produced no verdict.

    The reclassification's own behaviour — the exit code, the two ``reason``
    tags, and the review cycle that is not consumed — is pinned in
    ``test_review_no_submit_infra.py``.
    """
    _write_context(repo)
    _seed_run(db_path, repo)

    runner = _runner(stdout="I have opinions but no SUBMIT line\n")
    result = _invoke(repo, db_path, runner, *_green(repo))

    assert result.exit_code == review_mod.EXIT_INFRA_FAILURE
    events = _events(db_path)
    assert len(events) == 1, events
    assert events[0][REVIEW_OUTCOME_PATH.removeprefix("$.")] == REVIEW_OUTCOME_FAILED
    assert events[0]["reason"] == NO_SUBMIT_REASON
    assert "verdict" not in events[0]
    # The sentinel still names the failure to a human — now in the refusal's
    # ``detail``, rather than as an issue on a verdict never delivered.
    assert NO_SUBMIT_SENTINEL in events[0]["detail"]


# ---------------------------------------------------------------------------
# AC-3: a refusal event cannot open the close gate
# ---------------------------------------------------------------------------


def test_refusal_events_do_not_open_the_close_gate(repo: Path, db_path: Path) -> None:
    _write_context(repo)
    _seed_run(db_path, repo)
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()

    # Two refusals, no verdict anywhere.
    _invoke(repo, db_path)
    _invoke(repo, db_path)

    events = _events(db_path)
    assert len(events) == 2, events
    assert all("verdict" not in e for e in events)

    certification = _sync(certify_head(db_path, _RUN_ID, head))
    assert certification.verdict == "no_passing_review"
    assert not certification.certified


# ---------------------------------------------------------------------------
# The hazard the ticket's design missed: a refusal must not consume a cycle
# ---------------------------------------------------------------------------


def test_refusal_events_do_not_consume_a_review_cycle(repo: Path, db_path: Path) -> None:
    """A refusal runs no engine, so it must not be charged against the ceiling.

    Without the exclusion, five ``no_gate_evidence`` refusals — which spend
    nothing — would leave the run one cycle from the ceiling and its very next
    real review would trip the breaker.
    """
    _write_context(repo)
    _seed_run(db_path, repo)

    for _ in range(5):
        assert _invoke(repo, db_path).exit_code == review_mod.EXIT_GATE_FAILED
    assert len(_events(db_path)) == 5

    counted = _sync(review_mod._count_review_events(db_path, _RUN_ID))
    assert counted == 0

    # The next real review runs the engine rather than tripping the breaker.
    result = _invoke(repo, db_path, _runner(), *_green(repo))
    assert result.exit_code == 0
    assert json.loads(result.stdout)["verdict"] == "pass"


# ---------------------------------------------------------------------------
# AC-4: the observation write is subordinate
# ---------------------------------------------------------------------------


def test_a_raising_observation_write_changes_neither_exit_code_nor_output(
    repo: Path, db_path: Path
) -> None:
    """The real write is made to fail, rather than the writer being stubbed out.

    Stubbing ``record_terminal_refusal`` itself would only prove the stub raised;
    what has to hold is that the *emit* failing — a locked database, a disk that
    is full — leaves the refusal the caller is already reporting untouched.
    """
    _write_context(repo)
    _seed_run(db_path, repo)

    async def _explode(*_: Any, **__: Any) -> None:
        raise RuntimeError("the telemetry write is broken")

    healthy = _invoke(repo, db_path)
    assert len(_events(db_path)) == 1

    with mock.patch.object(EventEmitter, "emit", _explode):
        broken = _invoke(repo, db_path)

    assert broken.exit_code == healthy.exit_code == review_mod.EXIT_GATE_FAILED
    assert json.loads(broken.stdout) == json.loads(healthy.stdout)
    assert json.loads(broken.stdout)["reason"] == review_mod.NO_GATE_EVIDENCE_REASON
    # The failed write left no row behind — the count is still the healthy one.
    assert len(_events(db_path)) == 1


# ---------------------------------------------------------------------------
# AC-5: duration_ms + invoked_at on a passing event
# ---------------------------------------------------------------------------


def test_a_passing_event_carries_invoked_at_and_a_whole_ms_duration(
    repo: Path, db_path: Path
) -> None:
    _write_context(repo)
    _seed_run(db_path, repo)

    start = datetime(2026, 7, 31, 8, 0, 0, tzinfo=UTC)
    # Distinct successive readings: a constant stub cannot tell one clock read
    # from two, which would make the duration assertion vacuous.
    readings = iter(
        [
            start.isoformat().replace("+00:00", "Z"),
            (start + timedelta(milliseconds=1500)).isoformat().replace("+00:00", "Z"),
        ]
    )
    last = (start + timedelta(milliseconds=1500)).isoformat().replace("+00:00", "Z")

    with mock.patch.object(review_mod, "iso_z", lambda: next(readings, last)):
        result = _invoke(repo, db_path, _runner(), *_green(repo))

    assert result.exit_code == 0
    events = _events(db_path)
    assert len(events) == 1, events
    assert events[0]["invoked_at"] == start.isoformat().replace("+00:00", "Z")
    assert events[0]["duration_ms"] == 1500
    assert isinstance(events[0]["duration_ms"], int)


# ---------------------------------------------------------------------------
# AC-6: success rate is one SQL query, no timestamp arithmetic
# ---------------------------------------------------------------------------


def test_success_rate_is_one_query_over_the_outcome_field(repo: Path, db_path: Path) -> None:
    _write_context(repo)
    _seed_run(db_path, repo)

    _invoke(repo, db_path)  # no_gate_evidence  -> failed
    _invoke(repo, db_path)  # no_gate_evidence  -> failed
    _invoke(repo, db_path, _runner(), *_green(repo))  # pass -> ok

    async def _rate() -> tuple[int, int]:
        async with (
            store.connect(db_path) as conn,
            conn.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN COALESCE(json_extract(data_json, ?), ?) = ? THEN 1 ELSE 0 END) "
                "FROM events WHERE event_type = 'review'",
                (REVIEW_OUTCOME_PATH, REVIEW_OUTCOME_OK, REVIEW_OUTCOME_OK),
            ) as cur,
        ):
            row = await cur.fetchone()
        return int(row[0]), int(row[1])

    total, ok = _sync(_rate())
    assert (total, ok) == (3, 1)


# ---------------------------------------------------------------------------
# The payload contract
# ---------------------------------------------------------------------------


def test_a_refusal_payload_carries_no_verdict_key() -> None:
    data = ReviewRefusalEventData(
        run_id=_RUN_ID,
        reason="engine_timeout",
        detail="the engine was killed",
        created_at="2026-07-31T08:00:00Z",
        invoked_at="2026-07-31T07:59:00Z",
        duration_ms=60_000,
    ).model_dump(exclude_none=True)

    assert data[REVIEW_OUTCOME_PATH.removeprefix("$.")] == REVIEW_OUTCOME_FAILED
    assert "verdict" not in data
    assert "reviewed_sha" not in data
