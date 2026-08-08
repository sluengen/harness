"""#244 — a missing ledger file is a distinct refusal from "no open run",
across all four verbs that resolve an open run (``checkpoint`` / ``review`` /
``close`` / ``design``).

Before this ticket, ``resolve_open_run`` returned ``None`` for two unrelated
situations — "the ledger was read and holds no open row" and "there is no
ledger file at all" — and every caller rendered both as the identical
``no open run found for worktree ...`` message. That conflates a genuinely
absent run with working-directory drift (the resolved root has no
``.harness/harness.db``), which is the most common verb failure seen in
Sonnet-orchestrated sessions per the ticket's transcript audit.

This locks the *emitted JSON* each verb's real CLI produces (not the resolver
directly — ``test_runs_resolver.py`` covers that), parametrized over all four
verbs so a fix landing in the one shared resolver is proven to reach every
caller, and a future fifth caller that reintroduces its own ``db_path.exists()``
check would not silently regress this guard for the other four.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.state import store
from tests._asyncutil import run_sync
from tests._gitutil import init_repo

cli_runner = CliRunner()


#: argv per verb, minus ``--repo``/``--db`` (filled at call time). ``close``
#: needs a ticket positional; the resolver refusal fires before any tracker
#: lookup, so a dummy identifier never reaches the network.
_ARGV: dict[str, list[str]] = {
    "checkpoint": ["checkpoint"],
    "review": ["review"],
    "close": ["close", "CAL-1"],
    "design": ["design"],
}


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    init_repo(root)
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))
    return root


@pytest.mark.parametrize("verb", sorted(_ARGV))
def test_absent_ledger_reports_no_ledger(verb: str, repo: Path, tmp_path: Path) -> None:
    """AC-1: no ``.harness/harness.db`` at the resolved path → a distinct,
    machine-readable ``no_ledger`` refusal naming the path — not the historical
    "no open run found" message."""
    absent_db = tmp_path / "absent.db"
    assert not absent_db.exists()

    result = cli_runner.invoke(
        app, [*_ARGV[verb], "--repo", str(repo), "--db", str(absent_db)]
    )

    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == "no_ledger"
    assert payload["ledger_path"] == str(absent_db)
    assert "no open run found" not in payload["error"]


@pytest.mark.parametrize("verb", sorted(_ARGV))
def test_present_but_empty_ledger_is_unchanged(verb: str, repo: Path, tmp_path: Path) -> None:
    """AC-2: when the ledger exists and simply holds no open row, the historical
    message and reason are byte-for-byte what they were before this ticket."""
    db_path = tmp_path / "harness.db"
    run_sync(store.init_db(db_path))

    result = cli_runner.invoke(
        app, [*_ARGV[verb], "--repo", str(repo), "--db", str(db_path)]
    )

    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload.get("reason") != "no_ledger"
    assert "no open run found" in payload["error"]


@pytest.mark.parametrize("verb", sorted(_ARGV))
def test_no_ledger_and_empty_ledger_reasons_differ(
    verb: str, repo: Path, tmp_path: Path
) -> None:
    """AC-3: the two cases must never converge on the same ``reason`` — pinned
    directly so a future re-conflation fails loudly rather than silently."""
    absent_db = tmp_path / "absent.db"
    absent_result = cli_runner.invoke(
        app, [*_ARGV[verb], "--repo", str(repo), "--db", str(absent_db)]
    )

    empty_db = tmp_path / "empty.db"
    run_sync(store.init_db(empty_db))
    empty_result = cli_runner.invoke(
        app, [*_ARGV[verb], "--repo", str(repo), "--db", str(empty_db)]
    )

    absent_reason = json.loads(absent_result.output).get("reason")
    empty_reason = json.loads(empty_result.output).get("reason")
    assert absent_reason != empty_reason


def test_absent_ledger_creates_no_files(repo: Path, tmp_path: Path) -> None:
    """The refusal must not have the side effect of planting a ledger where
    none existed — a verb pointed at an unrelated directory must not create
    ``.harness/`` there."""
    absent_db = tmp_path / "nested" / "harness.db"
    assert not absent_db.parent.exists()

    cli_runner.invoke(app, ["checkpoint", "--repo", str(repo), "--db", str(absent_db)])

    assert not absent_db.parent.exists()


def test_worktree_walkup_still_resolves_main_checkout_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-4: #179's worktree walk-up (a verb run with ``--repo <worktree>``, no
    ``--db``) still finds the main checkout's ledger unaffected by this change."""
    import subprocess

    main = tmp_path / "main"
    init_repo(main)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=main,
        check=True,
        capture_output=True,
        text=True,
        env={
            **__import__("os").environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        },
    )
    worktree = tmp_path / "worktree"
    subprocess.run(
        ["git", "worktree", "add", "-b", "wt-branch", str(worktree)],
        cwd=main,
        check=True,
        capture_output=True,
        text=True,
    )
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))

    db_path = main / ".harness" / "harness.db"
    run_id = "01JWALKUPXXXXXXXXXXXXXXXX1"

    async def _seed() -> None:
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
                    str(worktree),
                    "wt-branch",
                    "CAL-1",
                    "2026-06-12T00:00:00Z",
                    1234,
                ),
            )
            await conn.commit()

    run_sync(_seed())

    result = cli_runner.invoke(app, ["checkpoint", "--repo", str(worktree)])

    # Not a no_ledger refusal — the walk-up found the main checkout's ledger.
    payload = json.loads(result.output) if result.output.strip().startswith("{") else {}
    assert payload.get("reason") != "no_ledger", result.output
