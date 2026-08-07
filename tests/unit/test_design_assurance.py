"""#352 — ``harness design`` runs only where the run's assurance requires it.

ADR 0007 D1 made the design stage unconditional, so every run paid for one
top-tier engine call whatever the change was worth. The parent proposal
(``specs/proposals/assurance-led-lifecycle.md``) replaces that with the run's
snapshotted assurance: ``complex`` requires a design that *succeeded*, and every
other level requires none.

AC-3 is a **count**, so these tests measure one: the engine runner is handed to
the verb and asserted never to have been called. A structural assertion — that
the code has an early return — is not evidence the early return is on the path
the CLI takes, and neither is a bare exit-0.

The skip must also leave no trace that could be mistaken for a design: no
``design`` event (``review``'s precondition and ``design_adopt``'s
authentication both read those), and no ticket comment (which is where a
resumed run recovers a design text from). A skip that recorded a
``status='ok'`` event would manufacture exactly the artifact the proposal says
must not be manufactured, and would satisfy a ``complex`` review it never
earned.

:func:`test_a_complex_run_still_invokes_the_engine` is the control that keeps
all of the above honest: without it a resolver that answered "not required"
for *every* run would pass every other test in this module.
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

from harness.cli import app, design_protocol
from harness.cli import design as design_mod
from harness.cli import design_tracker as design_tracker_mod
from harness.design_marker import DESIGN_MARKER
from harness.state import store
from tests._asyncutil import run_sync

cli_runner = CliRunner()

_RUN_ID = "01JRUNASSURANCEXXXXXXXXX01"
_DESIGN = "### Data model\n\nNo change.\n\n### Test strategy\n\nUnit tests."

#: The keys ``DesignOutput`` has emitted since #211. The ``not_required`` path
#: must not change the shape of the contract — only the value of ``status``.
_DESIGN_OUTPUT_KEYS = {
    "run_id",
    "design_markdown",
    "design_hash",
    "grounded_sha",
    "model",
    "status",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


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


def _seed_open_run(db_path: Path, repo: Path, *, assurance: str | None) -> str:
    """An ``open`` run whose ``worktree_path == repo``, at ``assurance``.

    ``None`` writes ``NULL``, i.e. a run row from before the migration — which
    must behave exactly as ``simple`` does.
    """

    async def _insert() -> None:
        await store.init_db(db_path)
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs ("
                "run_id, workflow_name, workflow_version, status, state_json, "
                "inputs_json, base_branch, worktree_path, worktree_branch, "
                "ticket, started_at, assurance, assurance_reason"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    "label" if assurance else None,
                ),
            )
            await conn.commit()

    run_sync(_insert())
    return _RUN_ID


def _design_events(db_path: Path) -> list[dict[str, Any]]:
    async def _read() -> list[dict[str, Any]]:
        async with (
            store.connect(db_path) as conn,
            conn.execute(
                "SELECT data_json FROM events WHERE event_type = 'design'"
            ) as cur,
        ):
            rows = await cur.fetchall()
        return [json.loads(row[0]) for row in rows]

    return run_sync(_read())


class _CountingRunner:
    """An engine stub that records how often it was called.

    It also *works*: on a run that genuinely requires a design, the same object
    delivers one through the file channel, so the control test measures the same
    seam the skip test does rather than a second, differently-shaped stub.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(
        self,
        *,
        cmd: list[str],
        stdin: str,
        env: dict[str, str],
        cwd: Path | None,
        timeout: float | None = None,
    ) -> design_mod.RunResult:
        self.calls += 1
        _design_output_path(cmd).write_text(_DESIGN, encoding="utf-8")
        return design_mod.RunResult(stdout="", stderr="", returncode=0)


def _design_output_path(cmd: list[str]) -> Path:
    """The file the engine is told to write its design to, read back off argv.

    Reconstructed from the command the verb actually built rather than passed
    in — the same rule ``test_cli_design.py::_design_path`` follows — so this
    stub writes where the *real* engine would be told to.
    """
    return Path(cmd[cmd.index("--add-dir") + 1]) / design_protocol.DESIGN_OUT_FILENAME


def _tracker_stub() -> Any:
    stub = mock.MagicMock()
    stub.fetch_issue = mock.AsyncMock(
        return_value={"title": "t", "description": "d", "labels": []}
    )
    stub.post_comment = mock.AsyncMock(return_value=None)
    return stub


def _invoke(repo: Path, db_path: Path, runner: Any, tracker: Any) -> Any:
    argv = [
        "design",
        "--repo",
        str(repo),
        "--db",
        str(db_path),
        "--run-id",
        _RUN_ID,
        "--json",
    ]
    with (
        mock.patch.object(design_mod, "_default_runner", runner),
        mock.patch.object(design_tracker_mod, "tracker_client", return_value=tracker),
    ):
        return cli_runner.invoke(app, argv)


# --- AC-3: the stage is skipped, and leaves nothing behind ---------------------


@pytest.mark.parametrize("assurance", ["simple", None], ids=["simple", "legacy-null"])
def test_a_run_that_does_not_require_design_makes_zero_engine_calls(
    repo: Path, db_path: Path, assurance: str | None
) -> None:
    """AC-3, measured: the engine runner is never called, and exit is 0.

    The legacy-``NULL`` case rides the same assertion because a run row written
    before the migration reads as ``simple`` — the level whose whole point is
    that it costs no design call. If it did not, every in-flight run at upgrade
    time would keep paying for a stage it is not required to pay for.
    """
    _seed_open_run(db_path, repo, assurance=assurance)
    runner = _CountingRunner()
    tracker = _tracker_stub()

    result = _invoke(repo, db_path, runner, tracker)

    assert result.exit_code == 0, result.output
    assert runner.calls == 0


def test_the_skip_emits_the_contract_with_a_not_required_status(
    repo: Path, db_path: Path
) -> None:
    """Same six keys as every other design invocation; only ``status`` differs.

    The output contract is locked, so the skip reports itself through the value
    of a field rather than by dropping or adding one — an orchestrator branches
    on ``status``, and an empty ``design_markdown`` says plainly there is
    nothing to stage for ``review``'s ``--design-file``.
    """
    _seed_open_run(db_path, repo, assurance="simple")

    result = _invoke(repo, db_path, _CountingRunner(), _tracker_stub())

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert set(payload) == _DESIGN_OUTPUT_KEYS
    assert payload["status"] == "not_required"
    assert payload["run_id"] == _RUN_ID
    assert payload["design_markdown"] == ""


def test_the_skip_manufactures_no_design_artifact(repo: Path, db_path: Path) -> None:
    """No ``design`` event and no ticket comment — the load-bearing half of AC-3.

    Both are read as evidence a design exists: ``review``'s precondition keys on
    the event, and a resumed run recovers the design *text* from the comment. A
    skip that wrote either would let a ``complex`` run inherit a design nothing
    produced.
    """
    _seed_open_run(db_path, repo, assurance="simple")
    tracker = _tracker_stub()

    result = _invoke(repo, db_path, _CountingRunner(), tracker)

    assert result.exit_code == 0, result.output
    assert _design_events(db_path) == []
    assert tracker.post_comment.await_count == 0


def test_the_skip_reads_no_ticket(repo: Path, db_path: Path) -> None:
    """A stage that does not run needs no ticket spec to run it against.

    Measured for the same reason as the engine count: the tracker round-trip is
    part of what the skip is meant to save, and nothing else in this module
    would notice it happening.
    """
    _seed_open_run(db_path, repo, assurance="simple")
    tracker = _tracker_stub()

    result = _invoke(repo, db_path, _CountingRunner(), tracker)

    assert result.exit_code == 0, result.output
    assert tracker.fetch_issue.await_count == 0


# --- The control: a run that DOES require design still gets it ----------------


def test_a_complex_run_still_invokes_the_engine(repo: Path, db_path: Path) -> None:
    """The control that makes every assertion above discriminating.

    Without it, a policy that answered "not required" for every run — or a verb
    that skipped unconditionally — would satisfy all four skip tests. This one
    asserts the same three observables in the opposite direction: the engine
    ran, an ``ok`` event was recorded, and the comment was posted.
    """
    _seed_open_run(db_path, repo, assurance="complex")
    runner = _CountingRunner()
    tracker = _tracker_stub()

    result = _invoke(repo, db_path, runner, tracker)

    assert result.exit_code == 0, result.output
    assert runner.calls == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["design_markdown"] == _DESIGN
    events = _design_events(db_path)
    assert len(events) == 1
    assert events[0]["status"] == "ok"
    assert tracker.post_comment.await_count == 1
    assert DESIGN_MARKER in tracker.post_comment.await_args.args[1]
