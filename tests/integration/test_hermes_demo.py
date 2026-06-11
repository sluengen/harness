"""End-to-end Hermes launch-handle demo — the local stand-in (CAL-585).

This is the demonstration the supersession header deferred (AC-1/AC-2/AC-3 of
``specs/hermes-orchestration.md`` §Runtime topology → *Launch handle and
decision record*, Ticket 5). It wires the **real** pieces — the launcher control
socket (:mod:`harness.launcher`), the three lifecycle verbs, and the trigger
stand-in (:mod:`harness.trigger`) — and drives a ticket from ``start`` to
``close`` exactly as the deployed topology would, with the outcome read solely
from the ledger.

Strategy (settled with the human 2026-06-11; changes to Nous' Hermes agent are
out of scope): a **local stand-in** plays the trigger. It launches a per-session
agent-runtime stand-in that drives ``start → implement → review → close``, each
verb requested **over the control socket** so it runs as a one-shot sibling
"container" *outside* the agent runtime. Here that sibling launch is executed
in-process (the launcher's runner is injected) with Linear / codex / git
merge-push faked — exactly as the verb unit tests fake them — so the demo is
hermetic yet exercises the real verbs, the real gate, and the real ledger.

* **AC-1** — every verb (start, review, close) is spawned outside the agent
  runtime via the launcher socket, as a one-shot ``docker run --rm`` sibling,
  and ``close``'s gate still enforces review
  (``test_end_to_end_demo_*`` + ``test_gate_refuses_close_without_passing_review``).
* **AC-2** — one session drives all three verbs: the ``run_id`` ``start`` opened
  is the one ``review`` and ``close`` are bound to (context retained).
* **AC-3** — the trigger determines the outcome solely by reading the ledger
  (``status`` / ``events``); its readback writes nothing to the DB.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import unittest.mock as mock
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli import close as close_mod
from harness.cli import review as review_mod
from harness.launcher import ControlServer, RunResult
from harness.launcher_client import LauncherClient, verb_argv_to_request
from harness.trigger import AgentLaunch, HermesTrigger

pytestmark = pytest.mark.integration

cli_runner = CliRunner()

IMAGE = "harness:dev"
TICKET = "CAL-585"


# ---------------------------------------------------------------------------
# Git helpers + a throw-away repo on ``dev`` (mirrors the verb unit tests).
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "dev")
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    # .harness/ and .worktrees/ gitignored exactly as in the real repo so neither
    # the ledger DB nor the run worktree registers as a dirty tree.
    (repo_root / ".gitignore").write_text(".harness/\n.worktrees/\n")
    (repo_root / "README.md").write_text("hello\n")
    _git(repo_root, "add", ".gitignore", "README.md")
    _git(repo_root, "commit", "-m", "initial")
    return repo_root


@pytest.fixture
def db_path(repo: Path) -> Path:
    return repo / ".harness" / "harness.db"


@pytest.fixture(autouse=True)
def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Permit the tmp tree through the ``HARNESS_WORKSPACE_ROOTS`` gate (CAL-584)."""
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))


@pytest.fixture
def socket_path() -> Iterator[Path]:
    # AF_UNIX bind paths are length-capped; bind under a short /tmp dir.
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="hns-") as d:
        yield Path(d) / "control.sock"


# ---------------------------------------------------------------------------
# The launcher's runner, executed in-process: a socket request → a real verb
# invocation (the "one-shot sibling container", run here as a subprocess-free
# CLI call). Records every launch argv for the AC-1 / AC-2 assertions.
# ---------------------------------------------------------------------------


class _InProcessVerbRunner:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> RunResult:
        self.calls.append(argv)
        tail = argv[argv.index(IMAGE) + 1 :]
        # The real sibling container resolves the ledger under the mounted repo
        # (`-w <repo>`); in-process there is no cwd switch, so point every verb
        # at the test DB explicitly. This is the only test-harness adaptation.
        invoke_args = [*tail, "--db", str(self._db_path)]
        result = cli_runner.invoke(app, invoke_args)
        return RunResult(exit_code=result.exit_code, stdout=result.stdout)


def _make_review_runner(verdict: str) -> Any:
    """A fake codex runner that emits a single SUBMIT line with ``verdict``."""

    async def _runner(
        *, cmd: list[str], stdin: str, env: dict[str, str], cwd: Path | None
    ) -> AsyncIterator[str]:
        yield f'SUBMIT: {{"verdict": "{verdict}", "issues": []}}\n'

    return _runner


def _make_start_linear_stub() -> mock.MagicMock:
    stub = mock.MagicMock()
    stub.fetch_issue = mock.AsyncMock(
        return_value={
            "id": "uuid-585",
            "identifier": TICKET,
            "title": "feat(harness): Hermes launch handle — end-to-end demo",
            "description": "Demonstrate the launch handle end-to-end.",
            "url": f"https://linear.app/team/issue/{TICKET}",
        }
    )
    stub.transition_to_in_progress = mock.AsyncMock(return_value=None)
    return stub


def _make_close_linear_stub() -> mock.MagicMock:
    stub = mock.MagicMock()
    stub.transition_to_done = mock.AsyncMock(return_value=None)
    return stub


def _verb_patches(stack: ExitStack, *, review_verdict: str) -> mock.MagicMock:
    """Activate the Linear / codex / merge-push fakes for the verb invocations.

    ``mock.patch`` replaces process-global module attributes, so the fakes are
    visible from the launcher server's handler thread too. Returns the
    merge-push mock so a test can assert whether the merge fired.
    """
    stack.enter_context(
        mock.patch("harness.cli.start.LinearClient", return_value=_make_start_linear_stub())
    )
    stack.enter_context(mock.patch("harness.cli.start.linear_api_key", return_value="k"))
    stack.enter_context(
        mock.patch("harness.cli.close.LinearClient", return_value=_make_close_linear_stub())
    )
    stack.enter_context(mock.patch("harness.cli.close.linear_api_key", return_value="k"))
    merge = mock.MagicMock(return_value=None)
    stack.enter_context(mock.patch.object(close_mod, "_merge_and_push", merge))
    stack.enter_context(
        mock.patch.object(review_mod, "_default_runner", _make_review_runner(review_verdict))
    )
    return merge


# ---------------------------------------------------------------------------
# The control socket transport. The agent-runtime stand-in and the trigger both
# drive verbs through the *real* production client (harness.launcher_client) over
# the socket — the same path docker/entrypoint.sh installs in agent-mode.
# ---------------------------------------------------------------------------


def _call(socket_path: Path, argv: list[str], repo: Path) -> dict[str, Any]:
    """Issue one ``harness <verb> …`` over the socket via the production client."""
    request = verb_argv_to_request(argv, repo=str(repo))
    return LauncherClient(socket_path).request(str(request["op"]), request["params"])


def _verb(socket_path: Path, argv: list[str], repo: Path) -> dict[str, Any]:
    resp = _call(socket_path, argv, repo)
    assert resp["ok"] is True, resp
    return resp


def _serving(server_obj: ControlServer, socket_path: Path) -> Any:
    server = server_obj.create_server(socket_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


# ---------------------------------------------------------------------------
# AC-1 / AC-2 / AC-3: the full demo.
# ---------------------------------------------------------------------------


def test_end_to_end_demo_launch_handle_via_socket_and_ledger(
    repo: Path, db_path: Path, socket_path: Path, tmp_path: Path
) -> None:
    runner = _InProcessVerbRunner(db_path)
    server_obj = ControlServer(
        runner=runner, image=IMAGE, roots=[tmp_path.resolve()], host_env={}
    )
    server, thread = _serving(server_obj, socket_path)

    # Captured by the agent-runtime stand-in so the trigger's read-back can be
    # checked for "writes nothing" (AC-3): the DB bytes the instant the session
    # finished, before the trigger reads it.
    observed: dict[str, Any] = {}

    def agent_runtime(ticket: str) -> AgentLaunch:
        """One per-session agent runtime: start → implement → review → close.

        Each verb is requested over the control socket (a one-shot sibling spawned
        *outside* this session). The ``run_id`` is threaded start→review→close in
        local state — context retained because this is one session (AC-2).
        """
        start_resp = _verb(socket_path, ["start", ticket, "--base", "dev"], repo)
        start = json.loads(start_resp["stdout"])
        run_id = start["run_id"]
        worktree = Path(start["worktree_path"])

        # Implement: the same session writes code in the worktree and commits it.
        (worktree / "feature.txt").write_text("the implemented change\n")
        _git(worktree, "add", "feature.txt")
        _git(worktree, "commit", "-m", "implement CAL-585")

        review = json.loads(_verb(socket_path, ["review", "--run-id", run_id], repo)["stdout"])
        assert review["verdict"] == "pass", review

        close = json.loads(
            _verb(socket_path, ["close", ticket, "--run-id", run_id], repo)["stdout"]
        )
        observed["run_id"] = run_id
        observed["merged"] = close.get("merged")
        observed["db_after_session"] = db_path.read_bytes()
        return AgentLaunch(run_id=run_id, exit_code=0)

    # The trigger reads the ledger *over the same socket*, read-only.
    def read_status(run_id: str) -> Mapping[str, Any]:
        out = _verb(socket_path, ["status", run_id], repo)["stdout"]
        parsed: Mapping[str, Any] = json.loads(out)
        return parsed

    def read_events(run_id: str) -> Sequence[Mapping[str, Any]]:
        out = _verb(socket_path, ["events", run_id], repo)["stdout"]
        return [json.loads(line) for line in out.splitlines() if line.strip()]

    try:
        with ExitStack() as stack:
            _verb_patches(stack, review_verdict="pass")
            trigger = HermesTrigger(
                launch_agent=agent_runtime,
                read_status=read_status,
                read_events=read_events,
            )
            outcome = trigger.run(TICKET)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    # The session reached close, merged, ticket Done — derived from the ledger.
    assert outcome.run_id == observed["run_id"]
    assert outcome.closed is True
    assert outcome.status == "closed"
    assert outcome.review_passed is True
    assert observed["merged"] is True

    # AC-3: the trigger's read-back wrote nothing — the DB is byte-identical to
    # the moment the session finished.
    assert db_path.read_bytes() == observed["db_after_session"]

    # AC-1: every verb crossed the socket as a one-shot `docker run --rm` sibling.
    verbs_launched = [argv[argv.index(IMAGE) + 1] for argv in runner.calls]
    assert verbs_launched[:3] == ["start", "review", "close"]
    for argv in runner.calls:
        assert argv[:3] == ["docker", "run", "--rm"]
        assert "--privileged" not in argv
        assert "/var/run/docker.sock" not in " ".join(argv)

    # AC-2: one session, one run — the id start opened is the id review and close
    # were bound to (context retained across verbs).
    assert verbs_launched.count("start") == 1
    review_argv = next(a for a in runner.calls if IMAGE in a and a[a.index(IMAGE) + 1] == "review")
    close_argv = next(a for a in runner.calls if IMAGE in a and a[a.index(IMAGE) + 1] == "close")
    assert observed["run_id"] in review_argv
    assert observed["run_id"] in close_argv


def test_gate_refuses_close_without_passing_review(
    repo: Path, db_path: Path, socket_path: Path, tmp_path: Path
) -> None:
    """AC-1 (gate still enforces review): close over the socket is refused when
    no HEAD-bound passing review exists — the gate runs inside the verb, not in
    the caller, so the socket cannot be used to bypass it."""
    runner = _InProcessVerbRunner(db_path)
    server_obj = ControlServer(
        runner=runner, image=IMAGE, roots=[tmp_path.resolve()], host_env={}
    )
    server, thread = _serving(server_obj, socket_path)

    try:
        with ExitStack() as stack:
            merge = _verb_patches(stack, review_verdict="fail")
            start = json.loads(
                _verb(socket_path, ["start", TICKET, "--base", "dev"], repo)["stdout"]
            )
            run_id = start["run_id"]
            worktree = Path(start["worktree_path"])
            (worktree / "feature.txt").write_text("change\n")
            _git(worktree, "add", "feature.txt")
            _git(worktree, "commit", "-m", "implement")

            # Review records a FAIL — no passing verdict on record.
            review = json.loads(
                _verb(socket_path, ["review", "--run-id", run_id], repo)["stdout"]
            )
            assert review["verdict"] == "fail"

            # close over the socket: the request itself is well-formed (ok), but
            # the verb refuses the gate with no_passing_review (exit code 2).
            resp = _call(socket_path, ["close", TICKET, "--run-id", run_id], repo)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert resp["ok"] is True  # the launch happened…
    assert resp["exit_code"] == 2  # …but the verb refused the gate.
    payload = json.loads(resp["stdout"])
    assert payload["reason"] == "no_passing_review"
    # No merge fired — the unreviewed tree never landed.
    merge.assert_not_called()
