"""End-to-end test of the launcher control socket (CAL-579, AC-1).

Drives the launcher exactly as Hermes would: over a unix domain socket, with
*only* that socket — no docker socket. The docker runner is a fake that records
the argv and returns canned verb output, so the test is hermetic (no real
containers) yet exercises the real transport: bind the UDS, connect, send a
request line, read the response line.

AC-1: with only the control socket, a client can ``start`` a run, poll
``status`` / ``events``, and ``cancel``.
AC-5 (over the wire): an operation outside the named surface is refused.
"""

from __future__ import annotations

import json
import os
import socket
import stat
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
        # No half-close after sending: the request line is newline-framed, and
        # the server writes its response then closes (signalling EOF). Tearing
        # down the write side here would race the server's close and raise
        # ENOTCONN under load (CAL-605). recv loops to EOF below.
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    result: dict[str, object] = json.loads(b"".join(chunks))
    return result


def test_request_does_not_half_close_its_write_side(socket_path: Path) -> None:
    """Regression for CAL-605: ``_request`` must not half-close after sending.

    The original helper called ``shutdown(SHUT_WR)`` after ``sendall``; under
    load that raced the server's close and raised ``ENOTCONN`` (a sporadic gate
    exit 1). The fix removes it — the request is newline-framed and the response
    is read to EOF, so the half-close is unnecessary.

    This detects the half-close *behaviorally* and deterministically, with no
    dependence on the platform's ``shutdown`` error semantics: a
    ``shutdown(SHUT_WR)`` delivers EOF to the server's read side in-stream,
    right after the request bytes. So after the server reads the newline-framed
    request, one more ``recv`` returns ``b""`` immediately iff the client
    half-closed (bug), or blocks until a short timeout iff the write side is
    still open (fixed). The server reports which it observed; the test asserts
    the client did *not* half-close. Reintroducing ``shutdown(SHUT_WR)`` flips
    ``half_closed`` to ``True`` and fails this test.
    """
    ready = threading.Event()

    def serve() -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as srv:
            srv.bind(str(socket_path))
            srv.listen(1)
            ready.set()
            conn, _ = srv.accept()
            with conn:
                buf = b""
                while not buf.endswith(b"\n"):
                    part = conn.recv(4096)
                    if not part:
                        break
                    buf += part
                # Probe the client's write side: EOF now == it half-closed.
                conn.settimeout(0.5)
                try:
                    half_closed = conn.recv(4096) == b""
                except (TimeoutError, OSError):
                    half_closed = False
                conn.settimeout(None)
                conn.sendall((json.dumps({"half_closed": half_closed}) + "\n").encode())

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert ready.wait(5)
    try:
        resp = _request(socket_path, {"op": "ping"})
        assert resp == {"half_closed": False}
    finally:
        thread.join(5)


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


def test_control_socket_is_owner_only(repo: Path, tmp_path: Path, socket_path: Path) -> None:
    """CAL-617: the bound control socket must be owner-only (no group/other bits).

    On macOS (the documented target, where ``$XDG_RUNTIME_DIR`` is unset) the
    socket falls back to ``~/.harness/control.sock``, and ``AF_UNIX`` honours
    mode bits there — so another local account/process could ``connect()`` and
    drive verb launches. ``create_server`` must restrict the socket to ``0600``,
    matching the ``0700`` protection the Linux ``$XDG_RUNTIME_DIR`` path gets
    for free.
    """
    server_obj = ControlServer(
        runner=_RecordingRunner(),
        image="harness:dev",
        roots=[(tmp_path / "work").resolve()],
        host_env={},
    )
    # A *non-existent* nested parent, so create_server must create it — this
    # exercises the mkdir mode, not the test fixture's pre-made temp dir.
    nested = socket_path.parent / "rt" / "control.sock"
    server = server_obj.create_server(nested)
    try:
        mode = os.stat(nested).st_mode
        assert stat.S_ISSOCK(mode), oct(mode)
        assert mode & 0o077 == 0, oct(mode)
        # The parent dir create_server makes is owner-only too.
        parent_mode = os.stat(nested.parent).st_mode
        assert parent_mode & 0o077 == 0, oct(parent_mode)
    finally:
        server.server_close()


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
