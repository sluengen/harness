"""The control-socket client and its direct-spawn fallback (#307, AC-3).

ADR 0012's first listed consequence:

    A process that must be running is a failure mode the script does not have.
    The client must fall back to spawning the container directly when the socket
    is unreachable, built in from the start rather than added after the first
    outage.

So the fallback is not an error path bolted on — it is the second of two equal
paths, and both construct the container through the *same*
:mod:`harness.hostenv.spawn`, which is what keeps them from drifting into two
security postures. The fallback runs on exactly the days the socket is broken,
which is the worst possible time to discover a divergence.

**The one asymmetry, and it is deliberate:** falling back is a *connect-time*
decision only. Once the request bytes are on the wire the verb may already be
running, so a lost response must never cause a second spawn — re-running a
mutating verb (a ``close`` that merges and pushes) is the worst failure this
design can produce. That case exits 1 and says the ledger is the record.

Docker is stubbed by a script on ``PATH`` that records its argv, the idiom
``tests/unit/test_wrapper_*.py`` already uses — every assertion here is about
the argv the client would run, which needs no daemon.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import socket
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from harness.hostenv import client, protocol

pytestmark = pytest.mark.usefixtures("stub_docker")


@pytest.fixture
def stub_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A ``docker`` on PATH that records its argv and exits with a set code."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    record = tmp_path / "docker-argv.log"
    exit_code_file = tmp_path / "docker-exit"
    exit_code_file.write_text("0")

    stub = bindir / "docker"
    stub.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{record}"\n'
        f'exit "$(cat "{exit_code_file}")"\n'
    )
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return record


def _spawns(record: Path) -> list[str]:
    return record.read_text().splitlines() if record.exists() else []


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    (path / ".git").mkdir(parents=True)
    return path


def _env(tmp_path: Path, socket_at: Path) -> dict[str, str]:
    return {
        "HOME": str(tmp_path / "home"),
        "HARNESS_CONTROL_SOCKET": str(socket_at),
        "PATH": os.environ["PATH"],
    }


# ---------------------------------------------------------------------------
# A server we control, so "unreachable" can be produced in each of its shapes.
# ---------------------------------------------------------------------------


class _Server:
    """A one-connection control-socket server with scriptable behaviour."""

    def __init__(self, path: Path, behaviour: str = "ok", exit_code: int = 0) -> None:
        self.path = path
        self.behaviour = behaviour
        self.exit_code = exit_code
        self.requests: list[protocol.Request] = []
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(path))
        self._sock.listen(1)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        conn, _ = self._sock.accept()
        with conn:
            payload, _fds, _flags, _addr = socket.recv_fds(
                conn, protocol.MAX_REQUEST_BYTES, 3
            )
            if payload:
                with contextlib.suppress(protocol.BadRequest):
                    self.requests.append(protocol.decode_request(payload))
            if self.behaviour == "hangup":
                return  # close with no response, after the request was received
            conn.sendall(protocol.encode_success(exit_code=self.exit_code).encode())

    def close(self) -> None:
        self._sock.close()


@pytest.fixture
def socket_path() -> Iterator[Path]:
    """A socket path short enough for ``AF_UNIX``.

    Not ``tmp_path``: the platform caps a unix socket path at ~104 bytes and
    pytest's per-test directory alone exceeds that on macOS. The cap is the
    reason :func:`harness.hostenv.protocol.socket_path` prefers
    ``$XDG_RUNTIME_DIR`` over a path built under ``$HOME``.
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="h", dir="/tmp"))
    try:
        yield tmpdir / "c.sock"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def stdio(tmp_path: Path) -> Iterator[tuple[int, int, int]]:
    """Three real file descriptors for the client to hand to the container.

    pytest's capture replaces ``sys.stdin`` with a pseudofile that has no
    ``fileno()``, so the fd-passing path is unreachable without injecting real
    ones. That the client *accepts* them is the point — the fds it forwards are
    part of the call, not ambient interpreter state.
    """
    read_fd = os.open(os.devnull, os.O_RDONLY)
    out_fd = os.open(tmp_path / "out", os.O_WRONLY | os.O_CREAT)
    err_fd = os.open(tmp_path / "err", os.O_WRONLY | os.O_CREAT)
    try:
        yield (read_fd, out_fd, err_fd)
    finally:
        for fd in (read_fd, out_fd, err_fd):
            os.close(fd)


# ---------------------------------------------------------------------------
# AC-3 — every shape of "the socket is unreachable" still runs the verb.
# ---------------------------------------------------------------------------


def test_a_missing_socket_falls_back_to_a_direct_spawn(
    tmp_path: Path, repo: Path, socket_path: Path, stub_docker: Path,
    stdio: tuple[int, int, int],
) -> None:
    code = client.run(
        repo=repo, argv=["status", "R1"], env=_env(tmp_path, socket_path), stdio=stdio
    )

    assert code == 0
    assert len(_spawns(stub_docker)) == 1, "the verb did not run"
    assert "status R1" in _spawns(stub_docker)[0]


def test_a_plain_file_where_the_socket_should_be_falls_back(
    tmp_path: Path, repo: Path, socket_path: Path, stub_docker: Path,
    stdio: tuple[int, int, int],
) -> None:
    socket_path.write_text("not a socket")

    code = client.run(
        repo=repo, argv=["version"], env=_env(tmp_path, socket_path), stdio=stdio
    )

    assert code == 0
    assert len(_spawns(stub_docker)) == 1


def test_a_socket_that_refuses_the_connection_falls_back(
    tmp_path: Path, repo: Path, socket_path: Path, stub_docker: Path,
    stdio: tuple[int, int, int],
) -> None:
    """A stale socket file left by a killed server: it exists, nothing listens."""
    dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    dead.bind(str(socket_path))
    dead.close()  # the path survives; no listener

    code = client.run(repo=repo, argv=["version"], env=_env(tmp_path, socket_path), stdio=stdio)

    assert code == 0
    assert len(_spawns(stub_docker)) == 1


def test_the_fallback_announces_itself_on_stderr(
    tmp_path: Path,
    repo: Path,
    socket_path: Path,
    capsys: pytest.CaptureFixture[str],
    stdio: tuple[int, int, int],
) -> None:
    """"Not running" must be visible, not silent — ADR 0012's stated risk of
    client-side autostart is that an outage becomes invisible."""
    client.run(repo=repo, argv=["version"], env=_env(tmp_path, socket_path), stdio=stdio)

    err = capsys.readouterr().err
    assert str(socket_path) in err and "directly" in err


def test_the_fallback_propagates_the_containers_exit_code(
    tmp_path: Path, repo: Path, socket_path: Path, stub_docker: Path,
    stdio: tuple[int, int, int],
) -> None:
    (stub_docker.parent / "docker-exit").write_text("5")

    code = client.run(repo=repo, argv=["review"], env=_env(tmp_path, socket_path), stdio=stdio)

    assert code == 5, "a gate refusal's exit code must survive the fallback"


# ---------------------------------------------------------------------------
# The socket path
# ---------------------------------------------------------------------------


def test_a_reachable_socket_is_used_and_nothing_is_spawned_locally(
    tmp_path: Path, repo: Path, socket_path: Path, stub_docker: Path,
    stdio: tuple[int, int, int],
) -> None:
    server = _Server(socket_path, exit_code=3)
    try:
        code = client.run(
            repo=repo,
            argv=["review", "--run-id", "R1"],
            env=_env(tmp_path, socket_path),
            stdio=stdio,
        )
    finally:
        server.close()

    assert code == 3, "the server's exit code must be adopted verbatim"
    assert _spawns(stub_docker) == [], (
        "the client spawned a container itself while the socket was up — the "
        "verb would have run twice"
    )
    assert server.requests[0].argv == ["review", "--run-id", "R1"]
    assert server.requests[0].repo == repo.resolve()


def test_both_paths_construct_the_same_container(
    tmp_path: Path, repo: Path, socket_path: Path, stub_docker: Path,
    stdio: tuple[int, int, int],
) -> None:
    """The anti-drift assertion: the fallback is not a second, laxer construction.

    Both paths call :func:`harness.hostenv.spawn.build_docker_argv`, so this
    compares what the client would spawn against what the server would, for the
    same request.

    The identity is resolved through the same provider both paths use (#307). What
    is being compared is the **call site** — which arguments each path passes — so
    resolving it here rather than pinning a literal keeps the comparison about
    drift between the two callers instead of about this machine's git config.
    """
    from harness.hostenv import host, spawn

    client.run(repo=repo, argv=["start", "307"], env=_env(tmp_path, socket_path), stdio=stdio)
    fallback = _spawns(stub_docker)[0]

    server_side = spawn.build_docker_argv(
        repo=repo.resolve(),
        argv=spawn.rewrite_repo_argument(["start", "307"], repo.resolve()),
        image=client.DEFAULT_IMAGE,
        env_names=client.FORWARDED_ENV_NAMES,
        home=Path(str(tmp_path / "home")),
        **{
            key: getattr(host.resolve_container_env(repo.resolve()), key)
            for key in ("git_identity", "ssh_auth_sock")
        },
    )

    # The stub records "$*" — docker's own argv minus argv[0].
    assert fallback == " ".join(server_side[1:])


# ---------------------------------------------------------------------------
# The asymmetry — a lost response must not re-run a mutating verb.
# ---------------------------------------------------------------------------


def test_a_connection_lost_after_the_request_does_not_fall_back(
    tmp_path: Path, repo: Path, socket_path: Path, stub_docker: Path,
    stdio: tuple[int, int, int],
) -> None:
    """The worst failure this design can produce, and the guard against it.

    The server received the request — so ``close`` may already have merged and
    pushed — and then died before answering. Re-spawning would run it twice.
    """
    server = _Server(socket_path, behaviour="hangup")
    try:
        code = client.run(
            repo=repo, argv=["close", "307"], env=_env(tmp_path, socket_path), stdio=stdio
        )
    finally:
        server.close()

    assert server.requests, "the request never reached the server — wrong scenario"
    assert code == 1
    assert _spawns(stub_docker) == [], (
        "the client re-spawned a verb that may already have run"
    )


def test_a_lost_response_says_the_ledger_is_the_record(
    tmp_path: Path,
    repo: Path,
    socket_path: Path,
    capsys: pytest.CaptureFixture[str],
    stdio: tuple[int, int, int],
) -> None:
    server = _Server(socket_path, behaviour="hangup")
    try:
        client.run(repo=repo, argv=["close", "307"], env=_env(tmp_path, socket_path), stdio=stdio)
    finally:
        server.close()

    err = capsys.readouterr().err.lower()
    assert "may have run" in err and "ledger" in err


# ---------------------------------------------------------------------------
# Argv handling
# ---------------------------------------------------------------------------


def test_an_explicit_repo_argument_is_translated_before_it_is_sent(
    tmp_path: Path, repo: Path, socket_path: Path, stub_docker: Path,
    stdio: tuple[int, int, int],
) -> None:
    """#351's argv half, on the client path."""
    client.run(
        repo=repo,
        argv=["review", "--repo", str(repo)],
        env=_env(tmp_path, socket_path),
        stdio=stdio,
    )

    assert "--repo /workspace" in _spawns(stub_docker)[0]


def test_a_repo_argument_naming_another_repo_is_refused_before_any_spawn(
    tmp_path: Path, repo: Path, socket_path: Path, stub_docker: Path,
    stdio: tuple[int, int, int],
) -> None:
    code = client.run(
        repo=repo,
        argv=["review", "--repo", "/somewhere/else"],
        env=_env(tmp_path, socket_path), stdio=stdio,
    )

    assert code == 2
    assert _spawns(stub_docker) == [], "a refused request must not reach docker"


def test_the_cli_entrypoint_splits_repo_from_verb_argv() -> None:
    parsed = client.parse_argv(["/work/repo", "--", "review", "--run-id", "R1"])

    assert parsed.repo == Path("/work/repo")
    assert parsed.argv == ["review", "--run-id", "R1"]


def test_the_entrypoint_rejects_a_missing_separator() -> None:
    with pytest.raises(SystemExit):
        client.parse_argv(["/work/repo", "review"])
