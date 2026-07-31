"""Tests for ``harness review`` — CAL-571.

AC-1: a ``review`` event is written with ``reviewed_sha`` == worktree HEAD at
      invocation (test asserts equality).
AC-2: pass/fail/defer verdicts are parsed from the SUBMIT line and persisted
      (test per verdict).
AC-3: missing/garbled SUBMIT line → recorded fail with the sentinel issue.
AC-4: the reviewer runs against HEAD, not base or a stale tree (recorded SHA).
AC-context-economy: the printed JSON contains only the bounded verdict fields
      (verdict, issues, reviewed_sha, run_id) and never raw codex stdout.

None of these tests spawn a real codex subprocess: every test injects a fake
runner via the ``--run-id`` override + a patched runner so the SUBMIT-line
scanner is exercised without the codex binary.
"""

# size: the review verb's acceptance suite — verdict parsing, SHA binding, breaker
# paths, and engine dispatch, all against one stubbed engine harness every case
# shares. Length is case count over that harness, not accreted logic.

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import unittest.mock as mock
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli import review as review_mod
from harness.events.payloads import MALFORMED_SUBMIT_REASON, NO_SUBMIT_REASON
from harness.state import store
from tests._ledger import seed_design_event

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


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throw-away git repo with one commit on ``dev``."""
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


def _seed_open_run(db_path: Path, repo: Path, run_id: str = "01JRUNREVIEWXXXXXXXXXXXX01") -> str:
    """Insert an ``open`` runs row whose worktree_path == repo, return run_id.

    Also seeds the ``design`` event ``review`` has required since #212 — these
    tests exercise the review flow, not the design gate (that is
    ``test_review_design_linkage.py``), so the stage is satisfied and stays out
    of their way.
    """

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
                    "CAL-571",
                    # A *recent* started_at: the CAL-906 wall-clock breaker is
                    # measured from this, so a stale literal would trip it before
                    # the engine runs. These tests exercise the review flow, not
                    # the breaker (that is test_review_breakers.py).
                    datetime.now(UTC).isoformat(),
                    1234,
                ),
            )
            await conn.commit()

    _sync(_insert())
    seed_design_event(db_path, run_id)
    return run_id


def _sync(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _fetch_review_events(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT run_id, event_type, data_json FROM events WHERE event_type = 'review'"
        ) as cur,
    ):
        rows = await cur.fetchall()
    out: list[dict[str, Any]] = []
    for run_id, event_type, data_json in rows:
        out.append(
            {"run_id": run_id, "event_type": event_type, "data": json.loads(data_json)}
        )
    return out


def fetch_review_events(db_path: Path) -> list[dict[str, Any]]:
    return _sync(_fetch_review_events(db_path))


def assert_no_verdict_recorded(db_path: Path, reason: str) -> None:
    """The terminal path is on the ledger and carries **no verdict** (#262).

    These sites used to assert ``fetch_review_events(db_path) == []``, which
    conflated two different claims: *no verdict was recorded* (the invariant —
    an infra wall must never read as pass/fail, and must never open the close
    gate) and *nothing at all was recorded* (an accident of the verb having no
    telemetry). #262 records the path deliberately, so the invariant is asserted
    on its own terms: exactly one row, no ``verdict`` key, and the right
    ``reason`` — so a refusal for the wrong cause cannot pass either.
    """
    events = fetch_review_events(db_path)
    assert len(events) == 1, events
    assert "verdict" not in events[0]["data"], events[0]["data"]
    assert events[0]["data"]["reason"] == reason, events[0]["data"]


def _make_runner(stdout: str, *, stderr: str = "", returncode: int = 0) -> Any:
    """Build a fake engine runner returning the given stdout/stderr/exit code.

    The runner signature mirrors the production runner: keyword args
    (cmd, stdin, env, cwd) and a :class:`RunResult` (CAL-702). ``stderr`` /
    ``returncode`` default to a clean success so existing call sites are
    unaffected.
    """

    async def _runner(
        *,
        cmd: list[str],
        stdin: str,
        env: dict[str, str],
        cwd: Path | None,
        timeout: float | None = None,
    ) -> review_mod.RunResult:
        return review_mod.RunResult(stdout=stdout, stderr=stderr, returncode=returncode)

    return _runner


def _make_linear_stub(*, in_review_error: Exception | None = None) -> Any:
    """A LinearClient stub whose transition methods are AsyncMocks (CAL-1103).

    ``in_review_error`` makes the In-Review transition *raise*, to exercise the
    warn-but-record path (AC-4). Tests that pass this stub to ``_invoke`` also
    patch ``linear_api_key`` so the verb builds the stub instead of degrading to
    the tracker-less no-op the hermetic ``LINEAR_API_KEY``-less env otherwise
    forces. ``fetch_issue`` is stubbed with no labels so the #177 model-tier
    resolution (which every review now performs) has an awaitable to call.
    """
    stub = mock.MagicMock()
    if in_review_error is not None:
        stub.transition_to_in_review = mock.AsyncMock(side_effect=in_review_error)
    else:
        stub.transition_to_in_review = mock.AsyncMock(return_value=None)
    stub.transition_to_in_progress = mock.AsyncMock(return_value=None)
    stub.fetch_issue = mock.AsyncMock(return_value={"labels": []})
    return stub


def _make_tracker_stub(labels: list[str] | None = None) -> Any:
    """A tracker-agnostic client stub carrying a ticket's ``labels`` (#177).

    Patching ``review_mod.tracker_client`` with this (rather than the
    Linear-specific credential stubbing ``linear_stub`` needs) exercises the
    review verb's model-tiering wiring without pinning to either backend —
    ``fetch_issue`` is the same seam both ``LinearClient`` and ``GitHubClient``
    implement.
    """
    stub = mock.MagicMock()
    stub.fetch_issue = mock.AsyncMock(return_value={"labels": labels or []})
    stub.transition_to_in_review = mock.AsyncMock(return_value=None)
    stub.transition_to_in_progress = mock.AsyncMock(return_value=None)
    return stub


def _invoke(
    repo: Path,
    db_path: Path,
    run_id: str,
    runner: Any,
    *,
    engine: str | None = None,
    model: str | None = None,
    linear_stub: Any | None = None,
    tracker_stub: Any | None = None,
) -> Any:
    # Patch the module-level default runner so the command uses the fake.
    argv = [
        "review",
        "--repo",
        str(repo),
        "--db",
        str(db_path),
        "--run-id",
        run_id,
        "--json",
    ]
    if engine is not None:
        argv += ["--engine", engine]
    if model is not None:
        argv += ["--model", model]
    with mock.patch.object(review_mod, "_default_runner", runner):
        if tracker_stub is not None:
            with mock.patch.object(review_mod, "tracker_client", return_value=tracker_stub):
                return cli_runner.invoke(app, argv)
        if linear_stub is None:
            # No Linear patch: the hermetic env has no LINEAR_API_KEY, so the verb
            # takes the tracker-less no-op path and never touches the network.
            return cli_runner.invoke(app, argv)
        with (
            mock.patch("harness.tracker.LinearClient", return_value=linear_stub),
            mock.patch("harness.tracker.linear_api_key", return_value="test-key"),
        ):
            return cli_runner.invoke(app, argv)


def _make_capturing_runner(stdout: str, captured: dict[str, Any]) -> Any:
    """A fake runner that records the ``cmd`` and ``env`` it was handed, then
    yields stdout.

    Lets a test assert *which engine command* the verb built (AC-1/AC-3), and
    *what environment it built it with* (#278), without spawning a real
    subprocess.
    """

    async def _runner(
        *,
        cmd: list[str],
        stdin: str,
        env: dict[str, str],
        cwd: Path | None,
        timeout: float | None = None,
    ) -> review_mod.RunResult:
        captured["cmd"] = cmd
        captured["env"] = env
        return review_mod.RunResult(stdout=stdout, stderr="", returncode=0)

    return _runner


# ---------------------------------------------------------------------------
# AC-1 / AC-4: review event records reviewed_sha == worktree HEAD
# ---------------------------------------------------------------------------


def test_ac1_review_event_reviewed_sha_equals_head(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    head = _head_sha(repo)
    runner = _make_runner('SUBMIT: {"verdict": "pass", "issues": []}\n')

    result = _invoke(repo, db_path, run_id, runner)
    assert result.exit_code == 0, result.output

    events = fetch_review_events(db_path)
    assert len(events) == 1
    assert events[0]["run_id"] == run_id
    assert events[0]["data"]["reviewed_sha"] == head


def test_ac4_reviewed_sha_tracks_head_after_new_commit(repo: Path, db_path: Path) -> None:
    """AC-4: review binds to the *current* HEAD, not a stale/base tree."""
    run_id = _seed_open_run(db_path, repo)
    # Advance HEAD with a new commit — review must record THIS sha, not the old one.
    (repo / "feature.txt").write_text("work\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "feature work")
    new_head = _head_sha(repo)

    runner = _make_runner('SUBMIT: {"verdict": "pass", "issues": []}\n')
    result = _invoke(repo, db_path, run_id, runner)
    assert result.exit_code == 0, result.output

    events = fetch_review_events(db_path)
    assert events[0]["data"]["reviewed_sha"] == new_head

    payload = json.loads(result.output)
    assert payload["reviewed_sha"] == new_head


# ---------------------------------------------------------------------------
# AC-2: pass / fail / defer verdicts parsed from SUBMIT line and persisted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verdict", ["pass", "fail", "defer"])
def test_ac2_verdict_parsed_and_persisted(
    repo: Path, db_path: Path, verdict: str
) -> None:
    run_id = _seed_open_run(db_path, repo)
    issues = [] if verdict == "pass" else ["something is wrong"]
    runner = _make_runner(
        f'SUBMIT: {{"verdict": "{verdict}", "issues": {json.dumps(issues)}}}\n'
    )

    result = _invoke(repo, db_path, run_id, runner)
    assert result.exit_code == 0, result.output

    events = fetch_review_events(db_path)
    assert len(events) == 1
    assert events[0]["data"]["verdict"] == verdict
    assert events[0]["data"]["issues"] == issues

    payload = json.loads(result.output)
    assert payload["verdict"] == verdict


def test_ac2_fail_with_issues_list(repo: Path, db_path: Path) -> None:
    """AC-2: findings → fail event carrying the issues list."""
    run_id = _seed_open_run(db_path, repo)
    runner = _make_runner(
        'SUBMIT: {"verdict": "fail", "issues": ["missing test", "bad name"]}\n'
    )

    result = _invoke(repo, db_path, run_id, runner)
    assert result.exit_code == 0, result.output

    events = fetch_review_events(db_path)
    assert events[0]["data"]["verdict"] == "fail"
    assert events[0]["data"]["issues"] == ["missing test", "bad name"]


# ---------------------------------------------------------------------------
# AC-3 (as amended by #270): missing / garbled SUBMIT line → an INFRA failure
# carrying no verdict, not a recorded ``fail``.
#
# These three cases were CAL-571's AC-3 and pinned "the verb never raises on a
# bad reviewer, it records the failure" — exit 0, ``verdict='fail'``, the
# sentinel as the sole issue. #270 reclassified them: a reviewer that emitted no
# parseable SUBMIT line delivered no verdict, so it is the same infra wall as an
# engine timeout, and recording it as a rejected diff cost a review cycle and
# inflated the fail rate. What survives from AC-3 is the half that was never in
# question — the verb still does not crash on a bad reviewer, it still records
# the failure — now as #262's refusal shape. The full behaviour lives in
# ``test_review_no_submit_infra.py``; these keep the three input shapes pinned
# where CAL-571's own tests can see them.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stdout", "expected_reason"),
    [
        ("I looked at the code and it seems fine to me.\n", NO_SUBMIT_REASON),
        ("SUBMIT: {this is not valid json\n", MALFORMED_SUBMIT_REASON),
        ('SUBMIT: {"verdict": "maybe", "issues": []}\n', MALFORMED_SUBMIT_REASON),
    ],
    ids=["no_submit_line", "garbled_json", "unknown_verdict"],
)
def test_ac3_unparseable_submit_is_infra_carrying_no_verdict(
    repo: Path, db_path: Path, stdout: str, expected_reason: str
) -> None:
    run_id = _seed_open_run(db_path, repo)
    runner = _make_runner(stdout)

    result = _invoke(repo, db_path, run_id, runner)
    assert result.exit_code == review_mod.EXIT_INFRA_FAILURE, result.output
    assert json.loads(result.output)["reason"] == expected_reason

    events = fetch_review_events(db_path)
    assert len(events) == 1
    assert "verdict" not in events[0]["data"]
    assert events[0]["data"]["reason"] == expected_reason


# ---------------------------------------------------------------------------
# AC-context-economy: printed JSON contains only bounded verdict fields,
# never raw codex stdout / reasoning.
# ---------------------------------------------------------------------------


def test_context_economy_only_bounded_fields_no_raw_stdout(
    repo: Path, db_path: Path
) -> None:
    run_id = _seed_open_run(db_path, repo)
    secret_reasoning = "INTERNAL_CHAIN_OF_THOUGHT_THAT_MUST_NOT_LEAK"
    stdout = (
        f"{secret_reasoning}\n"
        "Let me think about this in great detail ... lots of tokens ...\n"
        'SUBMIT: {"verdict": "fail", "issues": ["one issue"]}\n'
        "more trailing reasoning after submit\n"
    )
    runner = _make_runner(stdout)

    result = _invoke(repo, db_path, run_id, runner)
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    # Only the bounded verdict fields are present (engine is provenance, CAL-701;
    # convergence_check_required is the bounded CAL-906 advisory bool).
    assert set(payload.keys()) <= {
        "verdict",
        "issues",
        "reviewed_sha",
        "run_id",
        "engine",
        "convergence_check_required",
    }
    assert payload["verdict"] == "fail"
    assert payload["issues"] == ["one issue"]

    # Raw codex stdout / reasoning never leaks into the printed JSON.
    assert secret_reasoning not in result.output
    assert "trailing reasoning" not in result.output

    # …nor into the persisted event payload.
    events = fetch_review_events(db_path)
    assert secret_reasoning not in json.dumps(events[0]["data"])


# ---------------------------------------------------------------------------
# Resolution / invocation-error behaviour
# ---------------------------------------------------------------------------


def test_no_open_run_for_repo_is_invocation_error(repo: Path, db_path: Path) -> None:
    """No matching open run → exit 2, no review event written."""
    _sync(store.init_db(db_path))  # empty DB, no runs
    runner = _make_runner('SUBMIT: {"verdict": "pass", "issues": []}\n')

    result = _invoke(repo, db_path, "01JNONEXISTENTRUNIDXXXXXX0", runner)
    assert result.exit_code == 2, result.output
    assert fetch_review_events(db_path) == []


# ---------------------------------------------------------------------------
# CAL-701 — review engine is an arg (Claude default, Codex opt-in), read-only,
# with engine provenance.
# ---------------------------------------------------------------------------

_SUBMIT_PASS = 'SUBMIT: {"verdict": "pass", "issues": []}\n'


# AC-2: the Claude engine is a `claude -p` CLI subprocess (no SDK).


def test_ac2_build_cmd_claude_is_claude_p_cli() -> None:
    """The Claude engine command is a headless ``claude -p`` CLI invocation."""
    cmd = review_mod._build_cmd("claude")
    assert cmd[:2] == ["claude", "-p"], cmd


def test_ac2_review_verb_uses_the_claude_cli_not_the_agent_sdk() -> None:
    """A grep guard: the review verb never imports the Agent SDK / anthropic.

    The diff + ticket are untrusted prompt content; the engine must be a
    sandboxed CLI subprocess, never an in-process SDK call (CAL-701 AC-2,
    architecture-principles "a review engine is a CLI subprocess").
    """
    source = (Path(review_mod.__file__)).read_text()
    for forbidden in ("import anthropic", "from anthropic", "claude_agent_sdk"):
        assert forbidden not in source, (
            f"review verb must not use the Agent SDK ({forbidden!r} found)"
        )


# AC-3: both engines run read-only.


def test_ac3_codex_cmd_is_read_only_not_dangerous_bypass() -> None:
    """The Codex engine no longer carries the dangerous full-access bypass; it
    runs under the read-only sandbox (matching commands/build.md)."""
    cmd = review_mod._build_cmd("codex")
    assert "--dangerously-bypass-approvals-and-sandbox" not in cmd, cmd
    # contiguous `--sandbox read-only` pair
    assert "--sandbox" in cmd and cmd[cmd.index("--sandbox") + 1] == "read-only", cmd


def test_ac3_claude_cmd_carries_no_write_capability() -> None:
    """The Claude engine runs in a read-only permission mode (plan) and carries
    no edit/write/bypass capability."""
    cmd = review_mod._build_cmd("claude")
    assert "--permission-mode" in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "plan", cmd
    for writeish in ("acceptEdits", "bypassPermissions", "--dangerously-skip-permissions"):
        assert writeish not in cmd, cmd


# --- #177 AC-2/AC-3: _build_cmd's ``model`` kwarg -----------------------------


def test_ac2_build_cmd_claude_with_model_appends_model_flag() -> None:
    """A ``model`` tier appends ``--model <alias>`` to the claude command."""
    cmd = review_mod._build_cmd("claude", model="opus")
    assert cmd[-2:] == ["--model", "opus"], cmd


def test_ac2_build_cmd_claude_no_model_omits_the_flag() -> None:
    """No ``model`` (the default) omits ``--model`` entirely."""
    cmd = review_mod._build_cmd("claude")
    assert "--model" not in cmd, cmd


def test_ac3_build_cmd_codex_ignores_model() -> None:
    """The review tier is a claude-only control signal: codex's command is
    byte-identical whether or not a model tier is supplied."""
    assert review_mod._build_cmd("codex", model="opus") == review_mod._build_cmd("codex")


# AC-1: --engine accepted, default claude; both selections build the right cmd
# and record the right provenance.


def test_ac1_default_engine_is_claude(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    captured: dict[str, Any] = {}
    runner = _make_capturing_runner(_SUBMIT_PASS, captured)

    result = _invoke(repo, db_path, run_id, runner)  # no --engine
    assert result.exit_code == 0, result.output

    assert captured["cmd"][:2] == ["claude", "-p"], captured["cmd"]
    assert json.loads(result.output)["engine"] == "claude"
    assert fetch_review_events(db_path)[0]["data"]["engine"] == "claude"


def test_ac1_engine_codex_selects_codex(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    captured: dict[str, Any] = {}
    runner = _make_capturing_runner(_SUBMIT_PASS, captured)

    result = _invoke(repo, db_path, run_id, runner, engine="codex")
    assert result.exit_code == 0, result.output

    assert captured["cmd"][0] == "codex", captured["cmd"]
    assert json.loads(result.output)["engine"] == "codex"
    assert fetch_review_events(db_path)[0]["data"]["engine"] == "codex"


def test_ac1_engine_claude_selects_claude(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    captured: dict[str, Any] = {}
    runner = _make_capturing_runner(_SUBMIT_PASS, captured)

    result = _invoke(repo, db_path, run_id, runner, engine="claude")
    assert result.exit_code == 0, result.output

    assert captured["cmd"][:2] == ["claude", "-p"], captured["cmd"]
    assert json.loads(result.output)["engine"] == "claude"


# AC-4: ReviewOutput and the review event include `engine`.


def test_ac4_output_and_event_record_engine_provenance(
    repo: Path, db_path: Path
) -> None:
    run_id = _seed_open_run(db_path, repo)
    runner = _make_runner(_SUBMIT_PASS)

    result = _invoke(repo, db_path, run_id, runner, engine="codex")
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    assert payload["engine"] == "codex"
    assert fetch_review_events(db_path)[0]["data"]["engine"] == "codex"


# ---------------------------------------------------------------------------
# #177 — per-ticket model tiering: the claude engine command carries --model
# resolved from the ticket's review:<tier> label (default sonnet), a claude
# --model override wins over the resolved tier, and the codex command is
# unaffected by any of it.
# ---------------------------------------------------------------------------


def test_cal177_review_opus_label_appends_model_opus(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    captured: dict[str, Any] = {}
    runner = _make_capturing_runner(_SUBMIT_PASS, captured)
    stub = _make_tracker_stub(labels=["review:opus"])

    result = _invoke(repo, db_path, run_id, runner, tracker_stub=stub)
    assert result.exit_code == 0, result.output
    assert captured["cmd"][-2:] == ["--model", "opus"], captured["cmd"]


def test_cal177_no_review_label_defaults_model_sonnet(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    captured: dict[str, Any] = {}
    runner = _make_capturing_runner(_SUBMIT_PASS, captured)
    stub = _make_tracker_stub(labels=[])

    result = _invoke(repo, db_path, run_id, runner, tracker_stub=stub)
    assert result.exit_code == 0, result.output
    assert captured["cmd"][-2:] == ["--model", "sonnet"], captured["cmd"]


def test_cal177_codex_engine_ignores_review_tier_label(repo: Path, db_path: Path) -> None:
    """A review:opus label never reaches the codex command (claude-only signal)."""
    run_id = _seed_open_run(db_path, repo)
    captured: dict[str, Any] = {}
    runner = _make_capturing_runner(_SUBMIT_PASS, captured)
    stub = _make_tracker_stub(labels=["review:opus"])

    result = _invoke(repo, db_path, run_id, runner, engine="codex", tracker_stub=stub)
    assert result.exit_code == 0, result.output
    assert "--model" not in captured["cmd"], captured["cmd"]
    assert captured["cmd"] == review_mod._build_cmd("codex"), captured["cmd"]


def test_cal177_explicit_model_overrides_resolved_tier(repo: Path, db_path: Path) -> None:
    """An explicit --model wins over the ticket's resolved review:sonnet tier."""
    run_id = _seed_open_run(db_path, repo)
    captured: dict[str, Any] = {}
    runner = _make_capturing_runner(_SUBMIT_PASS, captured)
    stub = _make_tracker_stub(labels=["review:sonnet"])

    result = _invoke(repo, db_path, run_id, runner, model="opus", tracker_stub=stub)
    assert result.exit_code == 0, result.output
    assert captured["cmd"][-2:] == ["--model", "opus"], captured["cmd"]


# AC-5: SUBMIT parsing / verdict are unchanged across engines.


# ---------------------------------------------------------------------------
# CAL-702 — Codex→Claude usage-limit fallback.
#
# The real exhausted-tier signal, captured empirically 2026-06-15 by running
# `echo ... | codex exec --sandbox read-only --ephemeral -` against a depleted
# tier: stdout was EMPTY, the message below landed on STDERR, and the process
# exited 1.  The URLs and reset date vary; the matcher keys on the stable phrase.
# ---------------------------------------------------------------------------

_REAL_CODEX_USAGE_LIMIT_STDERR = (
    "OpenAI Codex v0.137.0\n"
    "--------\n"
    "ERROR: You've hit your usage limit. Upgrade to Pro "
    "(https://chatgpt.com/explore/pro), visit "
    "https://chatgpt.com/codex/settings/usage to purchase more credits or try "
    "again at Jun 18th, 2026 8:18 PM.\n"
)


def _make_engine_runner(
    by_engine: dict[str, review_mod.RunResult], order: list[str]
) -> Any:
    """A fake runner that dispatches on the engine in ``cmd`` and records order.

    Lets a fallback test give Codex a usage-limit result and Claude a pass, then
    assert which engines ran and in what sequence.
    """

    async def _runner(
        *,
        cmd: list[str],
        stdin: str,
        env: dict[str, str],
        cwd: Path | None,
        timeout: float | None = None,
    ) -> review_mod.RunResult:
        engine = "codex" if cmd[0] == "codex" else "claude"
        order.append(engine)
        return by_engine[engine]

    return _runner


# AC-3: the matcher is unit-tested against the captured real signal and a
# near-miss that must NOT match.


def test_ac3_matcher_true_on_captured_real_signal() -> None:
    assert review_mod.is_codex_usage_limit(_REAL_CODEX_USAGE_LIMIT_STDERR, 1) is True


def test_ac3_matcher_false_on_near_miss_failure() -> None:
    """An ordinary Codex failure mentioning 'limit' must NOT trigger fallback."""
    near_miss = "ERROR: rate limit exceeded for model gpt-5.5 — retry later\n"
    assert review_mod.is_codex_usage_limit(near_miss, 1) is False


def test_ac3_matcher_false_on_clean_exit_even_with_phrase() -> None:
    """A zero exit never counts as a usage limit (narrow match, no false hop)."""
    assert review_mod.is_codex_usage_limit(_REAL_CODEX_USAGE_LIMIT_STDERR, 0) is False


# ---------------------------------------------------------------------------
# CAL-1004: a hung review engine is bounded by a subprocess timeout — it does
# not hang the verb forever waiting on the external kill. On expiry the process
# is killed and the run surfaces the infra-failure shape (exit 3 + a stable,
# machine-readable reason), never a code-review verdict.
# ---------------------------------------------------------------------------


def test_default_runner_kills_hung_engine_and_raises_infra_exit3() -> None:
    """A never-returning engine subprocess hits the ceiling → infra exit 3 + reason.

    Exercises the REAL mechanism: a genuinely hanging child process (a python
    sleep that ignores stdin and never exits) under a tiny timeout. ``asyncio``'s
    ``wait_for`` must fire, the process must be killed (so the test returns
    promptly rather than blocking on the 30s sleep), and ``_default_runner`` must
    raise the ``_ReviewError`` carrying ``EXIT_INFRA_FAILURE`` and the stable
    ``ENGINE_TIMEOUT_REASON`` — not a swallowed failure, not a verdict.
    """
    hang = [sys.executable, "-c", "import time; time.sleep(30)"]

    async def _run() -> None:
        await review_mod._default_runner(
            cmd=hang,
            stdin="ignored",
            env=dict(os.environ),
            cwd=None,
            timeout=0.2,
        )

    with pytest.raises(review_mod._ReviewError) as excinfo:
        asyncio.run(_run())
    err = excinfo.value
    assert err.code == review_mod.EXIT_INFRA_FAILURE == 3
    assert err.reason == review_mod.ENGINE_TIMEOUT_REASON == "engine_timeout"


def test_default_runner_no_timeout_still_runs_to_completion() -> None:
    """With ``timeout=None`` the runner keeps its old unbounded behaviour.

    A fast-exiting child returns its RunResult normally — the timeout is a
    ceiling, not a mandatory wait, so the no-timeout path is unchanged.
    """
    echo = [sys.executable, "-c", "print('SUBMIT: {\"verdict\": \"pass\", \"issues\": []}')"]

    async def _run() -> review_mod.RunResult:
        return await review_mod._default_runner(
            cmd=echo, stdin="", env=dict(os.environ), cwd=None, timeout=None
        )

    result = asyncio.run(_run())
    assert result.returncode == 0
    assert "SUBMIT:" in result.stdout


def test_review_cli_surfaces_engine_timeout_as_exit3_reason(
    repo: Path, db_path: Path
) -> None:
    """End-to-end: a timed-out engine surfaces exit 3 + ``reason`` on the CLI JSON.

    Injects a runner that raises the timeout ``_ReviewError`` (as the real
    ``_default_runner`` does on expiry) and drives the full ``review`` command.
    The verb must exit 3, print the machine-readable ``reason``, and record NO
    review event — a hung engine never reviewed the diff, so it is infra, not a
    verdict (mirrors the sandbox-init contract).
    """
    run_id = _seed_open_run(db_path, repo)

    async def _timeout_runner(
        *,
        cmd: list[str],
        stdin: str,
        env: dict[str, str],
        cwd: Path | None,
        timeout: float | None = None,
    ) -> review_mod.RunResult:
        raise review_mod._ReviewError(
            "review engine exceeded its timeout and was killed",
            review_mod.EXIT_INFRA_FAILURE,
            reason=review_mod.ENGINE_TIMEOUT_REASON,
        )

    result = _invoke(repo, db_path, run_id, _timeout_runner)
    assert result.exit_code == 3, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == "engine_timeout"
    # No verdict recorded: infra failure, not a review.
    assert_no_verdict_recorded(db_path, review_mod.ENGINE_TIMEOUT_REASON)


# AC-1 / AC-4: a usage-limit Codex run falls back to Claude exactly once, the
# Claude verdict is authoritative, and the event records fallback_from=codex.


def test_ac1_codex_usage_limit_falls_back_to_claude(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    order: list[str] = []
    runner = _make_engine_runner(
        {
            "codex": review_mod.RunResult(
                stdout="", stderr=_REAL_CODEX_USAGE_LIMIT_STDERR, returncode=1
            ),
            "claude": review_mod.RunResult(
                stdout='SUBMIT: {"verdict": "pass", "issues": []}\n',
                stderr="",
                returncode=0,
            ),
        },
        order,
    )

    result = _invoke(repo, db_path, run_id, runner, engine="codex")
    assert result.exit_code == 0, result.output

    # Exactly one fallback hop: codex first, then claude once.
    assert order == ["codex", "claude"]

    payload = json.loads(result.output)
    assert payload["verdict"] == "pass"  # Claude's verdict is authoritative
    assert payload["engine"] == "claude"

    event = fetch_review_events(db_path)[0]["data"]
    assert event["engine"] == "claude"
    assert event["fallback_from"] == "codex"


# AC-2: a non-limit Codex failure does NOT fall back — verdict fail, engine codex.


def test_ac2_non_limit_codex_failure_does_not_fall_back(
    repo: Path, db_path: Path
) -> None:
    run_id = _seed_open_run(db_path, repo)
    order: list[str] = []
    runner = _make_engine_runner(
        {
            "codex": review_mod.RunResult(
                stdout="", stderr="ERROR: connection reset by peer\n", returncode=1
            ),
            # Present but must never be reached.
            "claude": review_mod.RunResult(
                stdout='SUBMIT: {"verdict": "pass", "issues": []}\n',
                stderr="",
                returncode=0,
            ),
        },
        order,
    )

    result = _invoke(repo, db_path, run_id, runner, engine="codex")

    # The property under test is the ABSENCE of a fallback hop, and it holds.
    assert order == ["codex"]

    # An ordinary Codex failure produces no parseable SUBMIT line, so since #270
    # it is infra rather than a recorded ``fail``. That is the fix working, not a
    # weakening of this test: "connection reset by peer" was never a reviewer
    # rejecting the diff. What CAL-702 asserts here — that a non-limit failure
    # does not silently become a Claude verdict — is untouched.
    assert result.exit_code == review_mod.EXIT_INFRA_FAILURE, result.output
    assert json.loads(result.output)["reason"] == NO_SUBMIT_REASON
    assert all(e["data"].get("verdict") is None for e in fetch_review_events(db_path))


def test_default_claude_never_falls_back(repo: Path, db_path: Path) -> None:
    """The default Claude engine never engages fallback logic (single-hop only)."""
    run_id = _seed_open_run(db_path, repo)
    order: list[str] = []
    runner = _make_engine_runner(
        {
            # Even if Claude emitted the limit phrase, no fallback engages.
            "claude": review_mod.RunResult(
                stdout="", stderr=_REAL_CODEX_USAGE_LIMIT_STDERR, returncode=1
            ),
            "codex": review_mod.RunResult(
                stdout='SUBMIT: {"verdict": "pass", "issues": []}\n',
                stderr="",
                returncode=0,
            ),
        },
        order,
    )

    result = _invoke(repo, db_path, run_id, runner)  # default engine = claude

    assert order == ["claude"]  # ran once, no hop to codex — the property here
    # No SUBMIT line came back, so #270 classifies it as infra; the recorded row
    # is a refusal, which by construction carries no ``fallback_from`` either.
    assert result.exit_code == review_mod.EXIT_INFRA_FAILURE, result.output
    event = fetch_review_events(db_path)[0]["data"]
    assert "fallback_from" not in event


@pytest.mark.parametrize("engine", ["claude", "codex"])
def test_ac5_submit_parsing_unchanged_across_engines(
    repo: Path, db_path: Path, engine: str
) -> None:
    run_id = _seed_open_run(db_path, repo)
    runner = _make_runner('SUBMIT: {"verdict": "defer", "issues": ["x"]}\n')

    result = _invoke(repo, db_path, run_id, runner, engine=engine)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["verdict"] == "defer"
    assert fetch_review_events(db_path)[0]["data"]["verdict"] == "defer"


# AC-6: docs record the new default + the principle.

_REPO_ROOT = Path(__file__).parent.parent.parent


def test_ac6_harness_md_documents_engine_option() -> None:
    text = (_REPO_ROOT / "commands" / "harness.md").read_text()
    assert "--engine" in text, "commands/harness.md must document the --engine option"
    assert "codex" in text and "claude" in text.lower()


def test_ac6_principle_recorded_in_architecture_principles() -> None:
    text = (_REPO_ROOT / "specs" / "architecture-principles.md").read_text()
    assert "CLI subprocess" in text, (
        "architecture-principles.md must record the 'a review engine is a CLI "
        "subprocess emitting the SUBMIT: contract — never the Agent SDK' principle"
    )


# ---------------------------------------------------------------------------
# CAL-866 — a review-engine sandbox/init failure is INFRA, not a code-review
# ``fail``.
#
# When ``codex exec --sandbox read-only`` runs inside a non-privileged Docker
# container, bwrap cannot create a user namespace (stock Docker seccomp blocks
# CLONE_NEWUSER) and exits non-zero with the marker below on STDERR.  Before
# CAL-866 this fell through to ``scan_submit_line`` and was recorded as
# ``verdict="fail"`` + the no-SUBMIT sentinel — indistinguishable from "the
# reviewer genuinely rejected the diff".  The fix mirrors ``is_codex_usage_limit``
# (a narrow stderr match + non-zero exit) and surfaces the failure as a distinct,
# machine-readable infra signal: a dedicated exit code + ``reason`` on the error
# JSON, NOT a verdict.  The real captured line was:
#
#   bwrap: No permissions to create a new namespace
#
# The lowercased invariant core is the marker.
# ---------------------------------------------------------------------------

_REAL_SANDBOX_INIT_STDERR = (
    "OpenAI Codex v0.137.0\n"
    "--------\n"
    "bwrap: No permissions to create a new namespace\n"
)


# AC-1 / AC-2: the matcher is true on the captured real signal and narrow —
# false on a clean exit and on an ordinary failure that merely mentions
# "namespace".


def test_cal866_sandbox_matcher_true_on_captured_real_signal() -> None:
    assert review_mod.is_sandbox_init_failure(_REAL_SANDBOX_INIT_STDERR, 1) is True


def test_cal866_sandbox_matcher_false_on_clean_exit() -> None:
    """A zero exit never counts as a sandbox failure (narrow match)."""
    assert review_mod.is_sandbox_init_failure(_REAL_SANDBOX_INIT_STDERR, 0) is False


def test_cal866_sandbox_matcher_false_on_near_miss_failure() -> None:
    """An ordinary failure mentioning 'namespace' must NOT count as infra."""
    near_miss = "ERROR: namespace 'foo' already registered in the registry\n"
    assert review_mod.is_sandbox_init_failure(near_miss, 1) is False


def test_cal866_sandbox_and_usage_limit_detectors_are_disjoint() -> None:
    """The two infra detectors never co-fire — distinct stderr phrases (AC-c)."""
    assert review_mod.is_sandbox_init_failure(_REAL_CODEX_USAGE_LIMIT_STDERR, 1) is False
    assert review_mod.is_codex_usage_limit(_REAL_SANDBOX_INIT_STDERR, 1) is False


# AC-1 / AC-3: a sandbox-init failure surfaces as a distinct infra signal —
# a dedicated non-zero exit + a machine-readable ``reason`` — and is NEVER
# recorded as a verdict (no ``pass``, no ``fail``, not swallowed).


def test_cal866_sandbox_init_failure_surfaces_as_infra_not_fail(
    repo: Path, db_path: Path
) -> None:
    run_id = _seed_open_run(db_path, repo)
    runner = _make_runner("", stderr=_REAL_SANDBOX_INIT_STDERR, returncode=1)

    result = _invoke(repo, db_path, run_id, runner, engine="codex")

    # Distinct, non-zero exit (not a recorded review's exit 0) — the dedicated
    # infra-failure code, separate from "unexpected error" (1) / "no run" (2).
    assert result.exit_code == review_mod.EXIT_INFRA_FAILURE
    assert result.exit_code not in (0, 1, 2)

    payload = json.loads(result.output)
    # Machine-readable signal — the orchestrator keys on ``reason``.
    assert payload["reason"] == "sandbox_init_failure"
    assert "error" in payload

    # No verdict was recorded: an infra failure must NOT read as pass/fail and
    # must NOT be swallowed into the ledger as a review verdict.
    assert_no_verdict_recorded(db_path, review_mod.SANDBOX_INIT_REASON)


def test_cal866_sandbox_init_failure_not_recorded_as_fail_verdict(
    repo: Path, db_path: Path
) -> None:
    """Regression for the conflation bug: the bwrap wall is no longer a fail."""
    run_id = _seed_open_run(db_path, repo)
    runner = _make_runner("", stderr=_REAL_SANDBOX_INIT_STDERR, returncode=1)

    result = _invoke(repo, db_path, run_id, runner, engine="codex")

    assert result.exit_code == review_mod.EXIT_INFRA_FAILURE
    # The pre-fix bug recorded verdict="fail" + the no-SUBMIT sentinel; assert it
    # no longer does (no review event at all, so certainly not a fail).
    events = fetch_review_events(db_path)
    assert all(e["data"].get("verdict") != "fail" for e in events)


# AC-b (as amended by #270): a no-SUBMIT on a CLEAN exit is a SUBMIT-protocol
# failure, and specifically NOT the sandbox wall — CAL-866's detector must stay
# narrow enough to leave it alone.
#
# This test read "…still records a code-review ``fail``" before #270, which
# reclassified that outcome. The half CAL-866 actually owns survives and is what
# is asserted now: the two infra paths stay *distinguishable*. A clean exit with
# no SUBMIT line is ``no_submit``; only the bwrap marker earns
# ``sandbox_init_failure``. Collapsing them would lose the difference between "the
# reviewer said nothing" and "the reviewer could not run a single command", which
# is the whole reason CAL-866 has its own reason tag.


def test_cal866_genuine_no_submit_on_clean_exit_is_not_the_sandbox_wall(
    repo: Path, db_path: Path
) -> None:
    run_id = _seed_open_run(db_path, repo)
    # Reviewer ran fine (exit 0) but emitted no SUBMIT line, and said nothing
    # about bwrap: a protocol failure, not a sandbox failure.
    runner = _make_runner("I reviewed it and have nothing structured to add.\n", returncode=0)

    result = _invoke(repo, db_path, run_id, runner, engine="codex")
    assert result.exit_code == review_mod.EXIT_INFRA_FAILURE, result.output

    reason = json.loads(result.output)["reason"]
    assert reason == NO_SUBMIT_REASON
    assert reason != review_mod.SANDBOX_INIT_REASON

    events = fetch_review_events(db_path)
    assert len(events) == 1
    assert events[0]["data"]["reason"] == NO_SUBMIT_REASON


# ---------------------------------------------------------------------------
# CAL-924 — a bwrap-blocked Codex ``defer`` is INFRA, not a shippable verdict.
#
# The CAL-866 detector keys on codex's OWN non-zero exit + the bwrap marker on
# STDERR.  It misses the subtler case seen in the CAL-906 dogfood: ``codex exec``
# exits **0**, but every read-only command it shells out to inspect the diff is
# killed by bwrap, so Codex reviews nothing yet emits a well-formed
# ``SUBMIT: {"verdict": "defer", ...}`` whose reasoning is "I could not run any
# command (bwrap: No permissions to create a new namespace)".  That read as a
# normal, shippable ``defer`` — a review that never happened.  The fix surfaces
# it as the SAME infra signal as CAL-866 (exit EXIT_INFRA_FAILURE, reason
# sandbox_init_failure, NO review event), narrowed to a Codex ``defer`` carrying
# the marker so a genuine defer — or any Claude verdict — is never swallowed.
# ---------------------------------------------------------------------------

# A realistic bwrap-blocked codex stdout: exit 0, a well-formed ``defer`` whose
# issue text is the reviewer explaining every command was killed by the wall.
_BWRAP_BLOCKED_DEFER_STDOUT = (
    'SUBMIT: {"verdict": "defer", "issues": ["I could not inspect the diff: '
    "every command I ran failed with 'bwrap: No permissions to create a new "
    "namespace', so I reviewed nothing.\"]}\n"
)


# AC-2 (narrowness) — the matcher: true only on a Codex ``defer`` whose reasoning
# carries the bwrap marker; false on a genuine defer, a non-defer verdict, or a
# Claude verdict.


def test_cal924_matcher_true_on_bwrap_blocked_codex_defer() -> None:
    issues = [
        "I could not inspect the diff: every command failed with 'bwrap: No "
        "permissions to create a new namespace'."
    ]
    assert review_mod.is_sandbox_blocked_defer("defer", issues, "codex") is True


def test_cal924_matcher_false_on_genuine_codex_defer() -> None:
    """A genuine defer (real finding, no bwrap marker) is never swallowed."""
    issues = ["The retry knob needs its own ticket — out of scope here."]
    assert review_mod.is_sandbox_blocked_defer("defer", issues, "codex") is False


def test_cal924_matcher_false_on_non_defer_verdict() -> None:
    """Only a ``defer`` masquerades this way; pass/fail stay untouched."""
    issues = ["bwrap: No permissions to create a new namespace"]
    assert review_mod.is_sandbox_blocked_defer("pass", issues, "codex") is False
    assert review_mod.is_sandbox_blocked_defer("fail", issues, "codex") is False


def test_cal924_matcher_false_on_claude_engine() -> None:
    """Claude runs in plan mode, not bwrap — a Claude defer is never infra."""
    issues = ["bwrap: No permissions to create a new namespace"]
    assert review_mod.is_sandbox_blocked_defer("defer", issues, "claude") is False


def test_cal924_matcher_disjoint_from_stderr_detector() -> None:
    """The two sandbox detectors read different channels and never conflate.

    The CAL-866 detector keys on stderr + a non-zero exit; this one keys on the
    parsed defer's issue text at exit 0.  A clean stdout defer is not a stderr
    failure, and a genuine defer is not blocked.
    """
    # The exit-0 defer marker is invisible to the stderr/non-zero detector.
    assert review_mod.is_sandbox_init_failure("", 0) is False
    # A genuine defer with no marker is not blocked.
    assert review_mod.is_sandbox_blocked_defer("defer", ["out of scope"], "codex") is False


# AC-1 / AC-3: a bwrap-blocked codex defer surfaces as the CAL-866 infra signal —
# a dedicated non-zero exit + machine-readable ``reason`` — and records NO event.


def test_cal924_bwrap_blocked_defer_surfaces_as_infra_not_verdict(
    repo: Path, db_path: Path
) -> None:
    run_id = _seed_open_run(db_path, repo)
    runner = _make_runner(_BWRAP_BLOCKED_DEFER_STDOUT, returncode=0)

    result = _invoke(repo, db_path, run_id, runner, engine="codex")

    # Same dedicated exit + reason as the CAL-866 stderr case — one contract.
    assert result.exit_code == review_mod.EXIT_INFRA_FAILURE
    assert result.exit_code not in (0, 1, 2)
    payload = json.loads(result.output)
    assert payload["reason"] == review_mod.SANDBOX_INIT_REASON
    assert "error" in payload

    # A review that never happened must NOT read as a defer (or any verdict).
    assert_no_verdict_recorded(db_path, review_mod.SANDBOX_INIT_REASON)


# AC-2 / AC-3: a genuine defer (the reviewer actually inspected the diff) is
# still recorded as a ``defer`` verdict — the detector stays narrow.


def test_cal924_genuine_codex_defer_still_recorded(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    genuine = (
        'SUBMIT: {"verdict": "defer", "issues": ["Refactoring the store belongs '
        'in its own ticket; out of scope here."]}\n'
    )
    runner = _make_runner(genuine, returncode=0)

    result = _invoke(repo, db_path, run_id, runner, engine="codex")
    assert result.exit_code == 0, result.output

    events = fetch_review_events(db_path)
    assert len(events) == 1
    assert events[0]["data"]["verdict"] == "defer"


# ===========================================================================
# CAL-1103: review parks the ticket In Review; a fail hands it back In Progress
# ===========================================================================
#
# The seeded run's ticket is "CAL-571" (see ``_seed_open_run``); the transitions
# assert against it. All Linear I/O is a stub — no network.


def test_cal1103_ac1_green_review_moves_ticket_to_in_review(
    repo: Path, db_path: Path
) -> None:
    """AC-1: a green-path review moves the ticket In Progress → In Review."""
    run_id = _seed_open_run(db_path, repo)
    stub = _make_linear_stub()
    runner = _make_runner('SUBMIT: {"verdict": "pass", "issues": []}\n')

    result = _invoke(repo, db_path, run_id, runner, linear_stub=stub)
    assert result.exit_code == 0, result.output

    stub.transition_to_in_review.assert_awaited_once_with("CAL-571")
    # A pass leaves it In Review — no hand-back to In Progress.
    stub.transition_to_in_progress.assert_not_awaited()


def test_cal1103_ac1_in_review_happens_before_the_engine_runs(
    repo: Path, db_path: Path
) -> None:
    """AC-1: the In-Review transition is awaited *before* the engine subprocess."""
    run_id = _seed_open_run(db_path, repo)
    stub = _make_linear_stub()
    observed: dict[str, int] = {}

    async def _runner(
        *,
        cmd: list[str],
        stdin: str,
        env: dict[str, str],
        cwd: Path | None,
        timeout: float | None = None,
    ) -> review_mod.RunResult:
        # Capture how many times In-Review was awaited by the time the engine runs.
        observed["in_review_awaits_at_engine_time"] = (
            stub.transition_to_in_review.await_count
        )
        return review_mod.RunResult(
            stdout='SUBMIT: {"verdict": "pass", "issues": []}\n', stderr="", returncode=0
        )

    result = _invoke(repo, db_path, run_id, _runner, linear_stub=stub)
    assert result.exit_code == 0, result.output
    assert observed["in_review_awaits_at_engine_time"] == 1


@pytest.mark.parametrize(
    "verdict,hands_back",
    [("pass", False), ("defer", False), ("fail", True)],
)
def test_cal1103_ac2_fail_hands_back_to_in_progress(
    repo: Path, db_path: Path, verdict: str, hands_back: bool
) -> None:
    """AC-2: a ``fail`` returns the ticket to In Progress; ``pass``/``defer`` leave
    it In Review."""
    run_id = _seed_open_run(db_path, repo)
    stub = _make_linear_stub()
    issues = [] if verdict == "pass" else ["blocking finding"]
    runner = _make_runner(
        f'SUBMIT: {{"verdict": "{verdict}", "issues": {json.dumps(issues)}}}\n'
    )

    result = _invoke(repo, db_path, run_id, runner, linear_stub=stub)
    assert result.exit_code == 0, result.output

    stub.transition_to_in_review.assert_awaited_once_with("CAL-571")
    if hands_back:
        stub.transition_to_in_progress.assert_awaited_once_with("CAL-571")
    else:
        stub.transition_to_in_progress.assert_not_awaited()


def test_cal1103_ac3_gate_refusal_leaves_ticket_state_untouched(
    repo: Path, db_path: Path
) -> None:
    """AC-3: a gate-evidence refusal (exit 5) transitions nothing — the check is
    before the In-Review move."""
    run_id = _seed_open_run(db_path, repo)
    # A configured verify gate + no --gate-exit → exit 5 before any engine/transition.
    (repo / "CONTEXT.md").write_text(
        '```yaml\nrepo:\n  name: t\nverify: "bash scripts/verify.sh"\n```\n'
    )
    stub = _make_linear_stub()
    runner = _make_runner('SUBMIT: {"verdict": "pass", "issues": []}\n')

    result = _invoke(repo, db_path, run_id, runner, linear_stub=stub)
    assert result.exit_code == review_mod.EXIT_GATE_FAILED
    assert json.loads(result.output)["reason"] == review_mod.NO_GATE_EVIDENCE_REASON
    stub.transition_to_in_review.assert_not_awaited()
    stub.transition_to_in_progress.assert_not_awaited()


def test_cal1103_ac4_transition_failure_warns_but_records_the_verdict(
    repo: Path, db_path: Path
) -> None:
    """AC-4: a Linear transition failure must not lose the review — the verdict is
    recorded, the verb exits 0, and a warning is emitted."""
    run_id = _seed_open_run(db_path, repo)
    stub = _make_linear_stub(
        in_review_error=review_mod.TrackerRequestError("tracker API HTTP 500")
    )
    runner = _make_runner('SUBMIT: {"verdict": "pass", "issues": []}\n')

    result = _invoke(repo, db_path, run_id, runner, linear_stub=stub)
    # The transition blew up, but the review is still a success and recorded.
    assert result.exit_code == 0, result.output
    events = fetch_review_events(db_path)
    assert len(events) == 1
    assert events[0]["data"]["verdict"] == "pass"
    # The failure was surfaced (warned), not swallowed silently.
    assert "warning" in result.output.lower()


def test_cal1103_tracker_less_review_records_verdict_without_transition(
    repo: Path, db_path: Path
) -> None:
    """A tracker-less repo (layers.linear off) records the verdict and makes no
    Linear call — the transition is a silent no-op."""
    run_id = _seed_open_run(db_path, repo)
    (repo / "CONTEXT.md").write_text(
        "```yaml\nrepo:\n  name: t\nlayers:\n  linear: false\n```\n"
    )
    stub = _make_linear_stub()
    runner = _make_runner('SUBMIT: {"verdict": "pass", "issues": []}\n')

    result = _invoke(repo, db_path, run_id, runner, linear_stub=stub)
    assert result.exit_code == 0, result.output
    stub.transition_to_in_review.assert_not_awaited()
    stub.transition_to_in_progress.assert_not_awaited()
    assert len(fetch_review_events(db_path)) == 1


# ---------------------------------------------------------------------------
# The engine subprocess inherits the container's environment unfiltered (#278)
# ---------------------------------------------------------------------------


def test_engine_subprocess_inherits_bytecode_suppression(
    repo: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The engine subprocess inherits the process environment unfiltered.

    The #278 fix pins ``PYTHONDONTWRITEBYTECODE=1`` on the container, and relies
    on that flag reaching whatever Python the *review engine* runs against the
    mounted worktree — not merely the harness process. That works only because
    the verb hands the engine ``env=dict(os.environ)``. Locking it here means a
    future env allowlist on that seam fails this test instead of silently
    reintroducing the bytecode leak.
    """
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    run_id = _seed_open_run(db_path, repo)
    captured: dict[str, Any] = {}
    runner = _make_capturing_runner(_SUBMIT_PASS, captured)

    result = _invoke(repo, db_path, run_id, runner)
    assert result.exit_code == 0, result.output

    assert captured["env"].get("PYTHONDONTWRITEBYTECODE") == "1", (
        "the review engine subprocess must inherit PYTHONDONTWRITEBYTECODE from "
        "the verb's environment, or the engine's own Python still writes "
        f"container-path bytecode into the mount (#278): {captured['env']!r}"
    )
