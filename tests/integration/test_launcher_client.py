"""Round-trip the launcher-socket client against the real server (CAL-585).

Proves the agent-side client (:mod:`harness.launcher_client`) and the host-side
server (:mod:`harness.launcher.ControlServer`) speak the same protocol over a
real ``AF_UNIX`` socket: a verb CLI argv → a request line → a server-side launch
(faked runner) → the verb's stdout + exit code back to the client. This is the
transport the agent runtime uses for every verb (decision #1) — exercised here
end-to-end, without docker.
"""

from __future__ import annotations

import json
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from harness.launcher import ControlServer, RunResult
from harness.launcher_client import LauncherClient, verb_argv_to_request

pytestmark = pytest.mark.integration


@pytest.fixture
def socket_path() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="hns-") as d:
        yield Path(d) / "control.sock"


class _RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> RunResult:
        self.calls.append(argv)
        verb = argv[argv.index("harness:dev") + 1] if "harness:dev" in argv else "?"
        return RunResult(exit_code=0, stdout=json.dumps({"verb": verb}))


def test_client_drives_each_verb_over_the_socket(tmp_path: Path, socket_path: Path) -> None:
    repo = tmp_path / "work" / "repo"
    repo.mkdir(parents=True)
    runner = _RecordingRunner()
    server_obj = ControlServer(
        runner=runner,
        image="harness:dev",
        roots=[(tmp_path / "work").resolve()],
        host_env={},
        home=tmp_path / "home",
    )
    server = server_obj.create_server(socket_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = LauncherClient(socket_path)
    try:
        for argv, expected_verb in (
            (["start", "CAL-1", "--base", "dev"], "start"),
            (["review", "--run-id", "R1"], "review"),
            (["status", "R1", "--json"], "status"),
            (["close", "CAL-1", "--run-id", "R1"], "close"),
        ):
            req = verb_argv_to_request(argv, repo=str(repo))
            resp = client.request(req["op"], req["params"])
            assert resp["ok"] is True, resp
            assert json.loads(resp["stdout"])["verb"] == expected_verb
            assert resp["exit_code"] == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    # Every launch the client triggered was a one-shot sibling, and the client
    # never handed out (or referenced) the docker socket.
    launched = [a[a.index("harness:dev") + 1] for a in runner.calls]
    assert launched == ["start", "review", "status", "close"]
    for argv in runner.calls:
        assert argv[:3] == ["docker", "run", "--rm"]
        assert "/var/run/docker.sock" not in " ".join(argv)
