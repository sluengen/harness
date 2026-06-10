"""End-to-end test of the launcher control socket (CAL-579, AC-1).

Drives the launcher exactly as Hermes would: over a unix domain socket, with
*only* that socket — no docker socket. The docker runner is a fake that records
the argv and returns canned verb output, so the test is hermetic (no real
containers) yet exercises the real transport: bind the UDS, connect, send a
request line, read the response line.

AC-1: with only the control socket, a client can ``start`` a run, poll
``status`` / ``events``, ``cancel``, and submit a ``decision``.
AC-5 (over the wire): an operation outside the named surface is refused.
"""

from __future__ import annotations

import json
import socket
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from harness.launcher import ControlServer, RunResult


@pytest.fixture
def socket_path() -> Iterator[Path]:
    """A control-socket path in a *short* directory.

    ``AF_UNIX`` bind paths are capped (~104 chars on macOS), and pytest's
    ``tmp_path`` can exceed that under a deeply nested worktree. Bind under a
    short ``/tmp`` dir instead; repo paths (plain files) may still be long.
    """
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="hns-") as d:
        yield Path(d) / "control.sock"


class _RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> RunResult:
        self.calls.append(argv)
        # Echo back the verb name so the client can tell responses apart.
        verb = argv[argv.index("harness:dev") + 1] if "harness:dev" in argv else "?"
        return RunResult(exit_code=0, stdout=json.dumps({"verb": verb}))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "work" / "repo"
    r.mkdir(parents=True)
    return r


def _request(socket_path: Path, payload: dict[str, object]) -> dict[str, object]:
    """Open a fresh connection, send one request line, read one response line."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(socket_path))
        client.sendall((json.dumps(payload) + "\n").encode())
        client.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    result: dict[str, object] = json.loads(b"".join(chunks))
    return result


def test_full_verb_cycle_over_the_socket(repo: Path, tmp_path: Path, socket_path: Path) -> None:
    runner = _RecordingRunner()
    server_obj = ControlServer(
        runner=runner,
        image="harness:dev",
        roots=[(tmp_path / "work").resolve()],
        host_env={},
    )
    server = server_obj.create_server(socket_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # start
        resp = _request(
            socket_path, {"op": "start", "params": {"repo": str(repo), "ticket": "CAL-1"}}
        )
        assert resp["ok"] is True
        assert json.loads(str(resp["stdout"]))["verb"] == "start"

        # status / events (read ops)
        for op in ("status", "events"):
            resp = _request(
                socket_path, {"op": op, "params": {"repo": str(repo), "run_id": "R1"}}
            )
            assert resp["ok"] is True
            assert json.loads(str(resp["stdout"]))["verb"] == op

        # cancel
        resp = _request(
            socket_path, {"op": "cancel", "params": {"repo": str(repo), "run_id": "R1"}}
        )
        assert resp["ok"] is True

        # decision
        resp = _request(
            socket_path,
            {"op": "decision", "params": {"repo": str(repo), "run_id": "R1", "value": "approve"}},
        )
        assert resp["ok"] is True
        assert json.loads(str(resp["stdout"]))["verb"] == "decision"

        # AC-5 over the wire: an unnamed operation is refused, runner untouched.
        before = len(runner.calls)
        resp = _request(socket_path, {"op": "docker", "params": {"repo": str(repo)}})
        assert resp["ok"] is False
        assert resp["reason"] == "unknown_operation"
        assert len(runner.calls) == before

        # Every recorded launch was a one-shot sibling (docker run --rm), and the
        # control socket itself never handed out the docker socket.
        assert runner.calls
        for argv in runner.calls:
            assert argv[:3] == ["docker", "run", "--rm"]
            assert "--privileged" not in argv
            assert "/var/run/docker.sock" not in " ".join(argv)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_repo_outside_allowlist_refused_over_the_socket(
    repo: Path, tmp_path: Path, socket_path: Path
) -> None:
    runner = _RecordingRunner()
    server_obj = ControlServer(
        runner=runner,
        image="harness:dev",
        roots=[(tmp_path / "work").resolve()],
        host_env={},
    )
    server = server_obj.create_server(socket_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        resp = _request(
            socket_path, {"op": "start", "params": {"repo": str(outside), "ticket": "CAL-1"}}
        )
        assert resp["ok"] is False
        assert resp["reason"] == "repo_not_allowed"
        assert runner.calls == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
