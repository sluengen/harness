"""#270 — a reviewer that emits no parseable SUBMIT line is infra, not a ``fail``.

``scan_submit_line`` mapped a missing, malformed, or unknown-verdict SUBMIT line
to ``_Parsed(verdict="fail", issues=[NO_SUBMIT_SENTINEL])``. That is an **engine
protocol failure** — the reviewer never delivered a verdict — but it was recorded
as an ordinary code-review ``fail``, with three consequences: it consumed one of
the run's six review cycles, it handed the ticket back to In Progress as though
the diff were rejected, and it was indistinguishable in the ledger from a real
failure, inflating the very ``fail`` rate #262's telemetry made queryable. It was
33% of that rate when measured (38 of 115 recorded fails).

The neighbouring paths were already classified the other way on the stated
principle that *an engine which never reviewed the diff produced no verdict*: an
engine timeout (:data:`~harness.cli.review.ENGINE_TIMEOUT_REASON`) and both
sandbox walls (:data:`~harness.cli.review.SANDBOX_INIT_REASON`) raise
``EXIT_INFRA_FAILURE``. ``review`` was the outlier; the ``design`` verb had
already resolved the identical case as ``no_submit`` / ``malformed_submit``.

These tests pin, in the order the ticket's ACs state them:

* the exit-code contract decided in the change spec — ``EXIT_INFRA_FAILURE`` with
  a per-shape ``reason``, one for each of the two protocol failures;
* **the measuring test for the ticket's central quantity** — the review consumes
  no cycle, asserted by reading ``_count_review_events`` either side of it rather
  than by inferring it from the refusal's shape;
* the ledger distinguishing it from a code-review ``fail`` (#262's refusal shape:
  ``outcome='failed'`` + ``reason``, and **no** ``verdict`` key);
* #262's close-gate property still holding for the new path;
* the removed In-Progress bounce — the ticket rests In Review, where the timeout
  and sandbox walls already leave it;
* and the teeth: a *genuine* ``fail`` still exits 0, still records a verdict, and
  still consumes a cycle, so none of the above was bought by breaking the path it
  is distinguished from.

They inject a fake engine runner and seed the ledger directly, exactly like
``test_review_terminal_telemetry.py``.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import unittest.mock as mock
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli import review as review_mod
from harness.cli._review_gate import certify_head
from harness.cli.review_protocol import (
    MALFORMED_SUBMIT_SENTINEL,
    NO_SUBMIT_SENTINEL,
    scan_submit_line,
)
from harness.events.payloads import (
    MALFORMED_SUBMIT_REASON,
    NO_SUBMIT_REASON,
    REVIEW_OUTCOME_FAILED,
    REVIEW_OUTCOME_OK,
    REVIEW_OUTCOME_PATH,
)
from harness.state import store
from tests._ledger import seed_design_event

cli_runner = CliRunner()

_RUN_ID = "01JRNOSUBMITINFRAXXXXXXX70"
_PASS_LINE = 'SUBMIT: {"verdict": "pass", "issues": []}\n'
_FAIL_LINE = 'SUBMIT: {"verdict": "fail", "issues": ["a real finding"]}\n'

#: The three engine outputs that yield no verdict, and the ``reason`` each earns.
#: Parametrized rather than written out three times so a fourth shape added to
#: the scanner cannot quietly acquire no coverage.
_NO_VERDICT_OUTPUTS: tuple[tuple[str, str, str], ...] = (
    ("no_submit_line_at_all", "I have opinions but never submitted them.\n", NO_SUBMIT_REASON),
    ("unparseable_json", "SUBMIT: {this is not valid json\n", MALFORMED_SUBMIT_REASON),
    (
        "unknown_verdict",
        'SUBMIT: {"verdict": "looks-fine", "issues": []}\n',
        MALFORMED_SUBMIT_REASON,
    ),
)


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


def _write_context(repo: Path) -> None:
    (repo / "CONTEXT.md").write_text(
        '```yaml\nrepo:\n  name: t\nverify: "bash scripts/verify.sh"\n```\n'
    )


def _seed_run(db_path: Path, repo: Path) -> str:
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
                    "270",
                    datetime.now(UTC).isoformat(),
                    1234,
                ),
            )
            await conn.commit()

    _sync(_insert())
    seed_design_event(db_path, _RUN_ID)
    return _RUN_ID


def _runner(stdout: str) -> Any:
    async def _run(
        *,
        cmd: list[str],
        stdin: str,
        env: dict[str, str],
        cwd: Path | None,
        timeout: float | None = None,
    ) -> review_mod.RunResult:
        return review_mod.RunResult(stdout=stdout, stderr="", returncode=0)

    return _run


def _green(repo: Path) -> tuple[str, ...]:
    log = repo / "gate.log"
    log.write_text("all green\n")
    return ("--gate-exit", "0", "--gate-log", str(log))


def _invoke(repo: Path, db_path: Path, stdout: str) -> Any:
    argv = [
        "review",
        "--repo",
        str(repo),
        "--db",
        str(db_path),
        "--run-id",
        _RUN_ID,
        "--json",
        *_green(repo),
    ]
    with mock.patch.object(review_mod, "_default_runner", _runner(stdout)):
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


def _cycles(db_path: Path) -> int:
    return int(_sync(review_mod._count_review_events(db_path, _RUN_ID)))


# ---------------------------------------------------------------------------
# The exit-code contract (change-spec Decision 1) + the two reasons (Decision 2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("label", "stdout", "expected_reason"), _NO_VERDICT_OUTPUTS)
def test_no_parseable_verdict_exits_infra_failure_with_its_own_reason(
    repo: Path, db_path: Path, label: str, stdout: str, expected_reason: str
) -> None:
    """Each no-verdict shape raises the infra contract, tagged for what happened.

    The exit code is the one the timeout and sandbox walls already use, on the
    identical principle. The ``reason`` is what makes "did the reviewer stop
    submitting, or start submitting badly?" an aggregate question rather than an
    unanswerable one — the two collapsed into a single bucket before.
    """
    _write_context(repo)
    _seed_run(db_path, repo)

    result = _invoke(repo, db_path, stdout)

    assert result.exit_code == review_mod.EXIT_INFRA_FAILURE, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == expected_reason
    # The message must name the fix, not merely the fault: this path is retryable.
    assert "review again" in payload["error"].lower()


@pytest.mark.parametrize(("label", "stdout", "expected_reason"), _NO_VERDICT_OUTPUTS)
def test_no_parseable_verdict_records_one_refusal_carrying_no_verdict(
    repo: Path, db_path: Path, label: str, stdout: str, expected_reason: str
) -> None:
    """AC-3: the ledger distinguishes it from a code-review ``fail``.

    #262's refusal shape — ``outcome='failed'`` plus the path's own ``reason``,
    and no ``verdict`` key at all — so a ``fail``-rate query excludes it rather
    than counting protocol noise as a rejected diff.
    """
    _write_context(repo)
    _seed_run(db_path, repo)

    _invoke(repo, db_path, stdout)

    events = _events(db_path)
    assert len(events) == 1, events
    assert events[0][REVIEW_OUTCOME_PATH.removeprefix("$.")] == REVIEW_OUTCOME_FAILED
    assert events[0]["reason"] == expected_reason
    assert "verdict" not in events[0]


# ---------------------------------------------------------------------------
# AC-2: the measuring test for the ticket's central quantity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("label", "stdout", "expected_reason"), _NO_VERDICT_OUTPUTS)
def test_no_parseable_verdict_consumes_no_review_cycle(
    repo: Path, db_path: Path, label: str, stdout: str, expected_reason: str
) -> None:
    """The cycle count is identical either side of the review.

    Stated as the AC states it — measured, not inferred. Reading the counter
    before and after is what makes this a test of the *quantity* the ticket is
    about (one of six cycles spent on nothing) rather than a structural claim
    about the event's shape, which the test above already covers.
    """
    _write_context(repo)
    _seed_run(db_path, repo)

    before = _cycles(db_path)
    _invoke(repo, db_path, stdout)
    after = _cycles(db_path)

    assert before == 0
    assert after == before


# ---------------------------------------------------------------------------
# AC-4: #262's close-gate property still holds for the new path
# ---------------------------------------------------------------------------


def test_no_submit_refusal_cannot_open_the_close_gate(repo: Path, db_path: Path) -> None:
    """A refusal row cannot certify HEAD however many of them there are.

    Enforcement by absence: the gate filters ``$.verdict = 'pass'`` and the row
    carries no ``verdict`` key, so ``json_extract`` answers NULL.
    """
    _write_context(repo)
    _seed_run(db_path, repo)

    _invoke(repo, db_path, "no submit line here\n")

    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    certification = _sync(certify_head(db_path, _RUN_ID, head))
    assert certification.verdict != "certified"


# ---------------------------------------------------------------------------
# The removed In-Progress bounce (change-spec Decision 3)
# ---------------------------------------------------------------------------


def test_no_submit_leaves_the_ticket_in_review_and_never_bounces_it(
    repo: Path, db_path: Path
) -> None:
    """The ticket rests In Review — the state the timeout and sandbox walls leave.

    Recorded as a *negative*: ``in_progress`` must never be requested. Asserting
    only that ``in_review`` happened would still pass if the bounce fired after
    it, which is precisely the defect.
    """
    _write_context(repo)
    _seed_run(db_path, repo)

    parked: list[str] = []

    async def _record(repo_root: Path, ticket: str | None, *, to: str) -> None:
        parked.append(to)

    with mock.patch.object(review_mod, "_park_ticket", _record):
        result = _invoke(repo, db_path, "no submit line here\n")

    assert result.exit_code == review_mod.EXIT_INFRA_FAILURE
    assert parked == ["in_review"]


# ---------------------------------------------------------------------------
# Teeth: the path this is distinguished FROM is untouched
# ---------------------------------------------------------------------------


def test_a_genuine_fail_still_exits_zero_records_a_verdict_and_costs_a_cycle(
    repo: Path, db_path: Path
) -> None:
    """Out of scope is out of scope: a real ``fail`` behaves exactly as before.

    Without this, every assertion above could be satisfied by classifying *all*
    fails as infra — which would be a far worse defect than the one being fixed.
    """
    _write_context(repo)
    _seed_run(db_path, repo)

    parked: list[str] = []

    async def _record(repo_root: Path, ticket: str | None, *, to: str) -> None:
        parked.append(to)

    with mock.patch.object(review_mod, "_park_ticket", _record):
        result = _invoke(repo, db_path, _FAIL_LINE)

    assert result.exit_code == 0, result.output
    events = _events(db_path)
    assert len(events) == 1, events
    assert events[0]["verdict"] == "fail"
    assert events[0]["issues"] == ["a real finding"]
    assert events[0][REVIEW_OUTCOME_PATH.removeprefix("$.")] == REVIEW_OUTCOME_OK
    assert _cycles(db_path) == 1
    assert parked == ["in_review", "in_progress"]


def test_a_pass_is_untouched(repo: Path, db_path: Path) -> None:
    """The other verdict that must keep working, and keep opening the gate."""
    _write_context(repo)
    _seed_run(db_path, repo)

    result = _invoke(repo, db_path, _PASS_LINE)

    assert result.exit_code == 0, result.output
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert _sync(certify_head(db_path, _RUN_ID, head)).verdict == "certified"


# ---------------------------------------------------------------------------
# The scanner: the protocol layer reports WHICH failure, purely
# ---------------------------------------------------------------------------


def test_scanner_distinguishes_a_missing_line_from_a_malformed_one() -> None:
    """``scan_submit_line`` carries the discriminator; the verb maps it to a tag.

    The same split ``design_protocol`` has, and the reason the verb branches on
    structure rather than string-matching ``issues[0]``.
    """
    missing = scan_submit_line("no submit anywhere\n")
    malformed = scan_submit_line("SUBMIT: not json at all\n")

    assert missing.submit_failure == NO_SUBMIT_SENTINEL
    assert malformed.submit_failure == MALFORMED_SUBMIT_SENTINEL
    assert NO_SUBMIT_SENTINEL != MALFORMED_SUBMIT_SENTINEL


def test_scanner_reports_no_submit_failure_on_a_valid_line() -> None:
    """The discriminator is absent exactly when a verdict parsed."""
    parsed = scan_submit_line(_PASS_LINE)

    assert parsed.submit_failure is None
    assert parsed.verdict == "pass"


def test_scanner_still_prefers_a_later_valid_line_over_an_earlier_bad_one() -> None:
    """A stray ``SUBMIT:`` in the engine's reasoning must not mask the real one.

    Pinned here because the new ``saw_submit_line`` bookkeeping runs alongside
    that scan: a rewrite that returned early on the first bad line would keep
    every test above green while silently discarding real verdicts.
    """
    parsed = scan_submit_line("SUBMIT: garbage\n" + _PASS_LINE)

    assert parsed.submit_failure is None
    assert parsed.verdict == "pass"
