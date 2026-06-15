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

from __future__ import annotations

import asyncio
import json
import subprocess
import unittest.mock as mock
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli import review as review_mod
from harness.state import store

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
                    "CAL-571",
                    "2026-06-10T00:00:00Z",
                    1234,
                ),
            )
            await conn.commit()

    _sync(_insert())
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


def _make_runner(stdout: str, *, stderr: str = "", returncode: int = 0) -> Any:
    """Build a fake engine runner returning the given stdout/stderr/exit code.

    The runner signature mirrors the production runner: keyword args
    (cmd, stdin, env, cwd) and a :class:`RunResult` (CAL-702). ``stderr`` /
    ``returncode`` default to a clean success so existing call sites are
    unaffected.
    """

    async def _runner(
        *, cmd: list[str], stdin: str, env: dict[str, str], cwd: Path | None
    ) -> review_mod.RunResult:
        return review_mod.RunResult(stdout=stdout, stderr=stderr, returncode=returncode)

    return _runner


def _invoke(
    repo: Path,
    db_path: Path,
    run_id: str,
    runner: Any,
    *,
    engine: str | None = None,
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
    with mock.patch.object(review_mod, "_default_runner", runner):
        return cli_runner.invoke(app, argv)


def _make_capturing_runner(stdout: str, captured: dict[str, Any]) -> Any:
    """A fake runner that records the ``cmd`` it was handed, then yields stdout.

    Lets a test assert *which engine command* the verb built (AC-1/AC-3) without
    spawning a real subprocess.
    """

    async def _runner(
        *, cmd: list[str], stdin: str, env: dict[str, str], cwd: Path | None
    ) -> review_mod.RunResult:
        captured["cmd"] = cmd
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
# AC-3: missing / garbled SUBMIT line → recorded fail with sentinel issue
# ---------------------------------------------------------------------------


SENTINEL = "reviewer emitted no valid SUBMIT line"


def test_ac3_no_submit_line_records_fail_sentinel(repo: Path, db_path: Path) -> None:
    run_id = _seed_open_run(db_path, repo)
    runner = _make_runner("I looked at the code and it seems fine to me.\n")

    result = _invoke(repo, db_path, run_id, runner)
    assert result.exit_code == 0, result.output

    events = fetch_review_events(db_path)
    assert len(events) == 1
    assert events[0]["data"]["verdict"] == "fail"
    assert SENTINEL in events[0]["data"]["issues"]


def test_ac3_garbled_submit_json_records_fail_sentinel(
    repo: Path, db_path: Path
) -> None:
    run_id = _seed_open_run(db_path, repo)
    runner = _make_runner("SUBMIT: {this is not valid json\n")

    result = _invoke(repo, db_path, run_id, runner)
    assert result.exit_code == 0, result.output

    events = fetch_review_events(db_path)
    assert events[0]["data"]["verdict"] == "fail"
    assert SENTINEL in events[0]["data"]["issues"]


def test_ac3_unknown_verdict_records_fail_sentinel(repo: Path, db_path: Path) -> None:
    """A SUBMIT line whose verdict is not pass/fail/defer is treated as garbled."""
    run_id = _seed_open_run(db_path, repo)
    runner = _make_runner('SUBMIT: {"verdict": "maybe", "issues": []}\n')

    result = _invoke(repo, db_path, run_id, runner)
    assert result.exit_code == 0, result.output

    events = fetch_review_events(db_path)
    assert events[0]["data"]["verdict"] == "fail"
    assert SENTINEL in events[0]["data"]["issues"]


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
    # Only the bounded verdict fields are present (engine is provenance, CAL-701).
    assert set(payload.keys()) <= {"verdict", "issues", "reviewed_sha", "run_id", "engine"}
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
    runs under the read-only sandbox (matching commands/build-codex.md)."""
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
        *, cmd: list[str], stdin: str, env: dict[str, str], cwd: Path | None
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
    assert result.exit_code == 0, result.output

    assert order == ["codex"]  # no fallback hop

    payload = json.loads(result.output)
    assert payload["verdict"] == "fail"
    assert payload["engine"] == "codex"

    event = fetch_review_events(db_path)[0]["data"]
    assert event["engine"] == "codex"
    assert "fallback_from" not in event


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
    assert result.exit_code == 0, result.output

    assert order == ["claude"]  # ran once, no hop to codex
    event = fetch_review_events(db_path)[0]["data"]
    assert event["engine"] == "claude"
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
