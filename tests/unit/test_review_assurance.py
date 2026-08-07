"""#352 — ``review``'s design precondition is the run's assurance, not a presence check.

Before this, ADR 0007 D3/D4 gave ``review`` one rule for every run: a ``design``
event must exist, and a ``status='failed'`` one satisfied it. That made the gate
prove *invocation* rather than a usable outcome — a complex change could ship
after the design stage produced nothing, while a small one was refused for
skipping a stage it did not need.

The rule is now the run's snapshotted assurance:

===========  =====================  ==========================================
Assurance    Latest ``design``      Result
===========  =====================  ==========================================
``simple``   absent / failed / ok   proceed
``complex``  absent                 refuse ``no_design``
``complex``  present, not ``ok``    refuse ``design_not_usable``
``complex``  present, ``ok``        proceed
===========  =====================  ==========================================

Both refusals are asserted **before the engine** — the runner is handed in and
its captured prompts must be empty — because "refuses" and "refuses without
spending an engine call" are different claims and only the second is the one the
gate makes. The tag-level matrix lives in ``test_assurance_policy.py`` as a pure
table; what this module measures is that the CLI is wired to that policy and to
nothing else.

``test_a_simple_run_with_no_design_reaches_the_engine`` is the AC-4 half and the
control on all of it: without it, a wiring that refused every run would satisfy
both refusal tests.
"""

from __future__ import annotations

import json
import subprocess
import unittest.mock as mock
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.assurance import DESIGN_NOT_USABLE_REASON, NO_DESIGN_REASON
from harness.cli import app
from harness.cli import review as review_mod
from harness.state import store
from tests._asyncutil import run_sync
from tests._ledger import seed_design_event

cli_runner = CliRunner()

_RUN_ID = "01JRUNREVASSURANCEXXXXXX01"
_PASS_LINE = 'SUBMIT: {"verdict": "pass", "issues": []}'


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


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


@pytest.fixture
def gate_log(tmp_path: Path) -> Path:
    """A green verify-gate log, so the gate-evidence check is never what refuses."""
    path = tmp_path / "gate.log"
    path.write_text("=== pytest ===\n42 passed\n")
    return path


def _seed_run(db_path: Path, repo: Path, *, assurance: str | None) -> str:
    """An open run at ``assurance``; ``None`` writes NULL (a pre-migration row)."""

    async def _insert() -> None:
        await store.init_db(db_path)
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs ("
                "run_id, workflow_name, workflow_version, status, state_json, "
                "inputs_json, base_branch, worktree_path, worktree_branch, "
                "ticket, started_at, assurance"
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
                    "352",
                    datetime.now(UTC).isoformat(),
                    assurance,
                ),
            )
            await conn.commit()

    run_sync(_insert())
    return _RUN_ID


def _capturing_runner(prompts: list[str]) -> Any:
    async def _runner(
        *,
        cmd: list[str],
        stdin: str,
        env: dict[str, str],
        cwd: Path | None,
        timeout: float | None = None,
    ) -> review_mod.RunResult:
        prompts.append(stdin)
        return review_mod.RunResult(stdout=_PASS_LINE, stderr="", returncode=0)

    return _runner


def _invoke(repo: Path, db_path: Path, runner: Any, gate_log: Path) -> Any:
    with mock.patch.object(review_mod, "_default_runner", runner):
        return cli_runner.invoke(
            app,
            [
                "review",
                "--repo",
                str(repo),
                "--db",
                str(db_path),
                "--run-id",
                _RUN_ID,
                "--gate-exit",
                "0",
                "--gate-log",
                str(gate_log),
                "--json",
            ],
        )


def _review_events(db_path: Path) -> list[dict[str, Any]]:
    async def _fetch() -> list[dict[str, Any]]:
        async with (
            store.connect(db_path) as conn,
            conn.execute("SELECT data_json FROM events WHERE event_type = 'review'") as cur,
        ):
            rows = await cur.fetchall()
        return [json.loads(r[0]) for r in rows]

    return run_sync(_fetch())


# --- AC-5: a complex run is refused unless its design succeeded ---------------


def test_a_complex_run_with_no_design_is_refused_before_the_engine(
    repo: Path, db_path: Path, gate_log: Path
) -> None:
    _seed_run(db_path, repo, assurance="complex")
    prompts: list[str] = []

    result = _invoke(repo, db_path, _capturing_runner(prompts), gate_log)

    assert result.exit_code == review_mod.EXIT_GATE_FAILED
    assert json.loads(result.stdout)["reason"] == NO_DESIGN_REASON
    assert prompts == [], "the refusal must precede any engine invocation"


def test_a_complex_run_with_a_failed_design_is_refused_before_the_engine(
    repo: Path, db_path: Path, gate_log: Path
) -> None:
    """AC-5's new half: a *failed* attempt no longer satisfies a complex review.

    ADR 0007 D4 let any recorded attempt through, so an infra flake could cost
    the run its design and still let it ship. For work judged complex that is
    the wrong trade: the stage exists to produce something to review against, and
    a failure means there is nothing.
    """
    _seed_run(db_path, repo, assurance="complex")
    seed_design_event(db_path, _RUN_ID, status="failed")
    prompts: list[str] = []

    result = _invoke(repo, db_path, _capturing_runner(prompts), gate_log)

    assert result.exit_code == review_mod.EXIT_GATE_FAILED
    payload = json.loads(result.stdout)
    assert payload["reason"] == DESIGN_NOT_USABLE_REASON
    assert prompts == []


@pytest.mark.parametrize(
    "reason", [NO_DESIGN_REASON, DESIGN_NOT_USABLE_REASON], ids=["absent", "failed"]
)
def test_neither_refusal_records_a_verdict(
    repo: Path, db_path: Path, gate_log: Path, reason: str
) -> None:
    """A refusal is not a ``fail``: it records *that it happened*, never a verdict.

    Both halves matter and pull in opposite directions. Since #262 every terminal
    path writes one ``review`` event, so the ledger has a denominator — a refusal
    that wrote nothing would be invisible. But the row must carry **no**
    ``verdict`` key, because ``close``'s gate filters ``$.verdict = 'pass'`` and
    a recorded ``fail`` would additionally consume a review cycle and tell the
    orchestrator to fix findings nobody made. The new refusal has to land on the
    same contract as the ones beside it, which is what this pins.
    """
    _seed_run(db_path, repo, assurance="complex")
    if reason == DESIGN_NOT_USABLE_REASON:
        seed_design_event(db_path, _RUN_ID, status="failed")

    result = _invoke(repo, db_path, _capturing_runner([]), gate_log)

    payload = json.loads(result.stdout)
    assert payload["reason"] == reason
    events = _review_events(db_path)
    assert len(events) == 1, events
    assert events[0]["reason"] == reason
    assert "verdict" not in events[0], (
        "a refusal that records a verdict is a verdict the close gate can read"
    )


def test_a_complex_run_with_a_successful_design_proceeds(
    repo: Path, db_path: Path, gate_log: Path
) -> None:
    _seed_run(db_path, repo, assurance="complex")
    seed_design_event(db_path, _RUN_ID, status="ok")
    prompts: list[str] = []

    result = _invoke(repo, db_path, _capturing_runner(prompts), gate_log)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["verdict"] == "pass"
    assert len(prompts) == 1


def test_the_latest_design_event_decides(repo: Path, db_path: Path, gate_log: Path) -> None:
    """A failed attempt followed by a successful one proceeds.

    The latest event is authoritative, as it already is for design *context* —
    otherwise re-running ``harness design`` after a flake could never clear the
    refusal, which would make an engine flake wedge the run permanently. Ordered
    by the event timestamp, so this also pins that the read is a lookup rather
    than an "any failed event anywhere" scan.
    """
    _seed_run(db_path, repo, assurance="complex")
    seed_design_event(db_path, _RUN_ID, status="failed", timestamp="2026-08-07T10:00:00Z")
    seed_design_event(db_path, _RUN_ID, status="ok", timestamp="2026-08-07T11:00:00Z")
    prompts: list[str] = []

    result = _invoke(repo, db_path, _capturing_runner(prompts), gate_log)

    assert result.exit_code == 0, result.output
    assert len(prompts) == 1


# --- AC-4: a simple run needs no design at all --------------------------------


@pytest.mark.parametrize("assurance", ["simple", None], ids=["simple", "legacy-null"])
def test_a_simple_run_with_no_design_reaches_the_engine(
    repo: Path, db_path: Path, gate_log: Path, assurance: str | None
) -> None:
    """AC-4, and the control on every refusal above.

    This is the shape ``harness design``'s skip produces, so it is the normal
    post-#352 run rather than an edge case — a ``no_design`` refusal here would
    make the two verbs contradict each other and wedge every simple run.

    The legacy-``NULL`` row rides the same assertion: a run opened before the
    migration recorded no design requirement, and refusing it would strand every
    in-flight run at upgrade time.
    """
    _seed_run(db_path, repo, assurance=assurance)
    prompts: list[str] = []

    result = _invoke(repo, db_path, _capturing_runner(prompts), gate_log)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["verdict"] == "pass"
    assert len(prompts) == 1


def test_a_simple_run_with_a_failed_design_still_proceeds_without_context(
    repo: Path, db_path: Path, gate_log: Path
) -> None:
    """The pre-#352 degradation stays reachable where design is not required.

    A legacy run reading as ``simple`` can still carry a ``failed`` design event,
    and it must review exactly as it did before — proceeding with no design
    context, recorded as ``design_failed``. The refusal and the degradation now
    coexist, keyed on assurance, and this is what pins that #352 narrowed the
    old behaviour rather than replacing it.
    """
    _seed_run(db_path, repo, assurance="simple")
    seed_design_event(db_path, _RUN_ID, status="failed")

    result = _invoke(repo, db_path, _capturing_runner([]), gate_log)

    assert result.exit_code == 0, result.output
    events = _review_events(db_path)
    assert len(events) == 1
    assert events[0]["design_context"] is False
    assert events[0]["design_context_reason"] == "design_failed"
