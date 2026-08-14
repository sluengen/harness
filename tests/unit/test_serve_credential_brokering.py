"""``harness serve`` brokering the agent credential, over the real socket (#309).

A new module rather than more of ``test_cli_serve.py``, which is at 617 of the
750-line ceiling. The split is by subject, not by size: everything here is about
*where the agent credential comes from* and *what happens when it cannot be
renewed*, driven through ``serve.build_server`` — the production constructor —
so the wiring itself is exercised rather than described.

Docker is a stub on ``PATH`` that records its argv and the credential
environment it was handed, which is exactly what the assertions need: secrets
cross by name (``-e NAME``) and their values arrive through the subprocess
``env=``, so what real docker would inject is what this stub sees.
"""

from __future__ import annotations

import os
import shutil
import socket
import tempfile
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from harness.cli import serve
from harness.hostenv import container_env, protocol
from harness.hostenv import host as host_module
from harness.hostenv.broker import CredentialBroker, RenewalOutcome
from harness.hostenv.credentials import (
    REFRESH_WINDOW_MS,
    AgentCredential,
    TrackerCredentials,
)
from harness.hostenv.host import GitIdentity, HostPlatform

#: Pinned wall clock; nothing here reads the real one.
NOW_MS = 1_700_000_000_000

#: The value AC-3 hunts for. Distinctive enough that a substring match anywhere
#: in an argv, a log line or a repr is unambiguous.
SENTINEL = "SENTINELTOKENVALUE"

#: Env names the stub docker records.
_RECORDED = (
    "GITHUB_TOKEN",
    "LINEAR_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_EXPIRES_AT",
)


class FakeHost(HostPlatform):
    """A host whose store, clock and refresh behaviour the test owns."""

    def __init__(
        self,
        credential: AgentCredential | None = None,
        *,
        env: dict[str, str] | None = None,
    ) -> None:
        super().__init__(name="fake", env=env or {})
        self.credential = credential
        self.reads = 0
        self.refreshes = 0
        #: ``None`` models the failure this ticket exists for: ``claude -p ok``
        #: exits 0, complains about nothing, and writes nothing to the store.
        self.refresh_installs: AgentCredential | None = None

    def now_ms(self) -> int:
        return NOW_MS

    def agent_credential(self) -> AgentCredential | None:
        self.reads += 1
        return self.credential

    def refresh_agent_credential(self, timeout_seconds: int | None = None) -> None:
        self.refreshes += 1
        if self.refresh_installs is not None:
            self.credential = self.refresh_installs

    def tracker_credentials(self, workdir: Path) -> TrackerCredentials:
        return TrackerCredentials(
            linear_api_key="linear-value", github_token="github-value", sources={}
        )

    def git_identity(self) -> GitIdentity:
        return GitIdentity(name="Fake Op", email="op@example.test")

    def ssh_agent_is_live(self) -> bool:
        return False


class RefusingHost(FakeHost):
    """A provider that raises if the request path asks it anything about credentials.

    A raise rather than only a counter: any call is red immediately, regardless
    of what a later assertion happens to check, and the traceback names the
    caller. This is what makes AC-1 an observation of the *call site* rather than
    a timing claim.
    """

    def agent_credential(self) -> AgentCredential | None:
        raise AssertionError("the request path read the credential store")

    def refresh_agent_credential(self, timeout_seconds: int | None = None) -> None:
        raise AssertionError("the request path ran a credential refresh")


def fresh(token: str = SENTINEL) -> AgentCredential:
    return AgentCredential(token=token, expires_at_ms=NOW_MS + 8 * 60 * 60 * 1000)


def expiring(token: str = SENTINEL) -> AgentCredential:
    """Inside the five-minute window, but not yet expired.

    Not an already-expired credential: the predicate under test is ``is_stale``,
    and a fixture past expiry would keep passing under the weaker
    ``expires_at_ms <= now``.
    """
    return AgentCredential(token=token, expires_at_ms=NOW_MS + REFRESH_WINDOW_MS // 2)


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """The server forwards ``os.environ`` to the child, so a real token on this
    machine would be recorded and every "no credential reached the container"
    assertion would be measuring the developer's shell."""
    for name in _RECORDED:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def stub_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A ``docker`` on PATH recording its own argv and credential environment."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    record = tmp_path / "spawns.log"
    dumps = "".join(
        f'printf "%s=%s\\n" {name} "${name}" >> "{record}";' for name in _RECORDED
    )
    stub = bindir / "docker"
    stub.write_text(
        f'#!/bin/sh\nprintf "ARGV=%s\\n" "$*" >> "{record}"\n{dumps}\n'
        f"printf -- '---\\n' >> \"{record}\"\nexit 0\n"
    )
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return record


def spawns(record: Path) -> list[dict[str, str]]:
    """One dict per spawn, in order; ``ARGV`` alongside the credential names."""
    if not record.exists():
        return []
    out: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in record.read_text().splitlines():
        if line == "---":
            out.append(current)
            current = {}
            continue
        key, _, value = line.partition("=")
        current[key] = value
    return out


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    (path / ".git").mkdir(parents=True)
    return path


@dataclass
class Running:
    """A production-built server, its broker, and the sink both log through."""

    server: serve.VerbServer
    broker: CredentialBroker | None
    log: list[str]


@pytest.fixture
def running(tmp_path: Path, stub_docker: Path, repo: Path):
    """Build a server through ``serve.build_server`` and serve it in a thread."""
    made: list[tuple[serve.VerbServer, CredentialBroker | None, Path]] = []

    def build(host: HostPlatform) -> Running:
        tmpdir = Path(tempfile.mkdtemp(prefix="hs", dir="/tmp"))
        lines: list[str] = []
        server, broker, _sweeper = serve.build_server(
            socket_path=tmpdir / "c.sock",
            roots=[repo.resolve()],
            image="harness:dev",
            log=lines.append,
            host=host,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        made.append((server, broker, tmpdir))
        return Running(server=server, broker=broker, log=lines)

    yield build

    for server, broker, tmpdir in made:
        server.shutdown()
        server.server_close()
        if broker is not None:
            broker.stop()
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def stdio() -> Iterator[tuple[int, int, int]]:
    read, write = os.pipe()
    try:
        yield (read, write, write)
    finally:
        os.close(read)
        os.close(write)


def request_verb(
    server: serve.VerbServer, repo: Path, argv: list[str]
) -> protocol.Response:
    """One request over the real socket, with three real file descriptors."""
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.connect(str(server.socket_path))
    devnull = os.open(os.devnull, os.O_RDWR)
    try:
        socket.send_fds(
            conn,
            [protocol.encode_request(repo=repo, argv=argv).encode()],
            [devnull, devnull, devnull],
        )
        chunks = []
        while chunk := conn.recv(65536):
            chunks.append(chunk)
        return protocol.decode_response(b"".join(chunks))
    finally:
        os.close(devnull)
        conn.close()


# ---------------------------------------------------------------------------
# AC-1 — the request path reads no store and calls no refresh
# ---------------------------------------------------------------------------


def test_the_brokered_request_path_reads_no_store_and_calls_no_refresh(
    repo: Path,
    stub_docker: Path,
    stdio: tuple[int, int, int],
    running,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-1, observed at the call site rather than at a stopwatch.

    The broker is primed over a cooperating host. The host the *request* then
    detects is one that raises on any credential question — so this cannot pass
    because "the broker happened to keep it fresh": there is no reachable code
    on the request path that could ask. The counters are checked too, because a
    raise proves only that nothing raised, not that the value forwarded came
    from the broker.
    """
    cooperating = FakeHost(fresh(token="brokered-value"))
    live = running(cooperating)
    reads_after_priming = cooperating.reads
    refreshes_after_priming = cooperating.refreshes

    monkeypatch.setattr(host_module, "detect_host", lambda **_: RefusingHost())
    live.server.spawn(repo=repo, argv=["status", "R1"], fds=list(stdio))

    recorded = spawns(stub_docker)
    assert len(recorded) == 1, "the verb container did not run"
    assert recorded[0]["CLAUDE_CODE_OAUTH_TOKEN"] == "brokered-value", (
        "the container was not given the broker's credential"
    )
    assert cooperating.reads == reads_after_priming, (
        "the credential store was read on the request path — that read is the "
        "per-request cost this ticket exists to remove"
    )
    assert cooperating.refreshes == refreshes_after_priming


def test_the_refusing_provider_is_reachable_on_the_unbrokered_path(
    tmp_path: Path,
    repo: Path,
    stub_docker: Path,
    stdio: tuple[int, int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The non-vacuity floor for AC-1.

    Same raising provider, same spawn, but a server built with the default
    request-refreshing source. It must blow up — otherwise the test above is
    passing because the provider was never on the request path at all, and would
    keep passing if brokering were removed tomorrow.
    """
    monkeypatch.setattr(host_module, "detect_host", lambda **_: RefusingHost())
    tmpdir = Path(tempfile.mkdtemp(prefix="hs", dir="/tmp"))
    server = serve.VerbServer(
        socket_path=tmpdir / "c.sock",
        roots=[repo.resolve()],
        image="harness:dev",
        env=dict(os.environ),
    )
    try:
        with pytest.raises(AssertionError, match="read the credential store"):
            server.spawn(repo=repo, argv=["status", "R1"], fds=list(stdio))
    finally:
        server.server_close()
        shutil.rmtree(tmpdir, ignore_errors=True)

    assert spawns(stub_docker) == []


# ---------------------------------------------------------------------------
# AC-2 — a named credential error, before any container is spawned
# ---------------------------------------------------------------------------


def test_a_failed_renewal_refuses_on_the_wire_before_docker(
    repo: Path,
    stub_docker: Path,
    running,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S2. The refusal is named, exits 2, is audited, and spawns nothing.

    The last assertion is the one that matters: a refusal is only a pre-spawn
    control if *no container ran*, and the exit code cannot show that.
    """
    host = FakeHost(expiring())
    host.refresh_installs = None  # the refresh exits 0 and writes nothing
    live = running(host)
    assert live.broker is not None
    assert live.broker.state.outcome is RenewalOutcome.FAILED

    monkeypatch.setattr(host_module, "detect_host", lambda **_: host)
    response = request_verb(live.server, repo, ["status", "R1"])

    assert response.ok is False
    assert response.reason is protocol.Reason.CREDENTIAL_UNAVAILABLE
    assert protocol.exit_code_for(response) == 2
    assert any("refused=credential_unavailable" in line for line in live.log), (
        f"the socket's only audit trail does not name the refusal: {live.log}"
    )
    assert spawns(stub_docker) == [], "a container was spawned despite the refusal"


def test_a_healthy_broker_spawns_rather_than_refusing(
    repo: Path,
    stub_docker: Path,
    running,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The paired discriminator: a pre-flight refusing unconditionally would
    satisfy every assertion above while breaking every verb."""
    host = FakeHost(fresh())
    live = running(host)

    monkeypatch.setattr(host_module, "detect_host", lambda **_: host)
    response = request_verb(live.server, repo, ["status", "R1"])

    assert response.ok is True, f"refused: {response.reason} {response.error}"
    assert len(spawns(stub_docker)) == 1


def test_the_absent_store_is_not_a_renewal_failure(
    repo: Path,
    stub_docker: Path,
    running,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3, and D2's guard — the one a careless implementation breaks.

    A host with no Claude installed at all must still run ``status`` and
    ``worktrees cleanup``. There is nothing to renew, so nothing failed to renew.
    """
    host = FakeHost(None)
    live = running(host)
    assert live.broker is not None
    assert live.broker.state.outcome is RenewalOutcome.ABSENT

    monkeypatch.setattr(host_module, "detect_host", lambda **_: host)
    response = request_verb(live.server, repo, ["status", "R1"])

    assert response.ok is True, f"refused: {response.reason} {response.error}"
    recorded = spawns(stub_docker)
    assert len(recorded) == 1
    assert recorded[0]["CLAUDE_CODE_OAUTH_TOKEN"] == "", (
        "a credential appeared from nowhere on a host whose store holds none"
    )


def test_an_exported_token_short_circuits_the_refusal(
    repo: Path,
    stub_docker: Path,
    running,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4: the caller's own export precedes the credential question entirely.

    The broker is in ``FAILED`` — every other request would be refused — and this
    one runs, because there was never anything to renew for it.
    """
    host = FakeHost(expiring(), env={"CLAUDE_CODE_OAUTH_TOKEN": "exported-value"})
    host.refresh_installs = None
    live = running(host)
    assert live.broker is not None
    assert live.broker.state.outcome is RenewalOutcome.FAILED

    monkeypatch.setattr(host_module, "detect_host", lambda **_: host)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "exported-value")
    response = request_verb(live.server, repo, ["status", "R1"])

    assert response.ok is True, f"refused: {response.reason} {response.error}"
    recorded = spawns(stub_docker)
    assert len(recorded) == 1
    assert recorded[0]["CLAUDE_CODE_OAUTH_TOKEN"] == "exported-value"


# ---------------------------------------------------------------------------
# AC-3 — no credential value in an argv, a log line, or a repr
# ---------------------------------------------------------------------------


def test_no_credential_value_reaches_an_argv_a_log_line_or_a_repr(
    repo: Path,
    stub_docker: Path,
    running,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-existing property that this change puts at risk for the first time.

    Nothing asserted it before, because nothing logged the agent token and
    nothing held it between requests. Now the broker holds it continuously and
    writes a line about it every failing cycle, so both surfaces are new.

    One healthy request and one failing one, over the real socket, with every
    surface the value could escape through checked: the docker argv, the audit
    and renewal log, the refusal frame the client prints, and the reprs of the
    server and the broker.
    """
    host = FakeHost(fresh())
    live = running(host)
    monkeypatch.setattr(host_module, "detect_host", lambda **_: host)

    healthy = request_verb(live.server, repo, ["status", "R1"])
    assert healthy.ok is True, f"refused: {healthy.reason} {healthy.error}"

    # Drive the same broker into failure, then ask again.
    host.credential = expiring()
    host.refresh_installs = None
    assert live.broker is not None
    assert live.broker.renew_once().outcome is RenewalOutcome.FAILED
    refused = request_verb(live.server, repo, ["status", "R2"])
    assert refused.reason is protocol.Reason.CREDENTIAL_UNAVAILABLE

    recorded = spawns(stub_docker)
    assert recorded[0]["CLAUDE_CODE_OAUTH_TOKEN"] == SENTINEL, (
        "the recorder never saw the value, so every absence below is a blind "
        "probe rather than a statement about where the value is placed"
    )
    assert SENTINEL not in recorded[0]["ARGV"], (
        "the credential value entered the container argv — it would then be "
        "readable in `ps` by any process on this host"
    )
    for line in live.log:
        assert SENTINEL not in line, f"a credential value reached a log line: {line!r}"
    assert SENTINEL not in (refused.error or "")
    assert SENTINEL not in repr(vars(live.server))
    assert SENTINEL not in repr(live.broker)


# ---------------------------------------------------------------------------
# ADR 0012 — the broker is host configuration, not run state
# ---------------------------------------------------------------------------


def test_a_request_writes_nothing_into_the_broker(
    repo: Path,
    stub_docker: Path,
    running,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0012: "if the host process ever holds run state, it has exceeded the
    carve-out." The credential the broker holds names no run, ticket, verb, argv
    or repo, and — decisively — nothing on the request path writes it."""
    host = FakeHost(fresh())
    live = running(host)
    monkeypatch.setattr(host_module, "detect_host", lambda **_: host)
    before = live.broker.state if live.broker else None

    for ticket in ("SENTINEL-TICKET-A", "SENTINEL-TICKET-B"):
        assert request_verb(live.server, repo, ["status", ticket]).ok

    assert live.broker is not None
    assert live.broker.state == before, "a request rewrote the broker's record"
    rendered = repr(vars(live.server)) + repr(live.broker)
    for ticket in ("SENTINEL-TICKET-A", "SENTINEL-TICKET-B"):
        assert ticket not in rendered, f"the host retained {ticket} after the request"


# ---------------------------------------------------------------------------
# The fallback: no broker, and no new startup failure mode
# ---------------------------------------------------------------------------


def test_an_unsupported_host_still_binds_a_server_with_no_broker(
    repo: Path,
    stub_docker: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detection failing at startup must not become a new way for ``serve`` to die.

    It falls back to the request-refreshing source with no broker, so every
    request refuses at the *existing* per-request site with the existing
    message — a degradation to today's behaviour, not an outage.
    """

    def unsupported(**_: object) -> HostPlatform:
        raise host_module.UnsupportedHost(platform="plan9", needed="credential-store")

    monkeypatch.setattr(host_module, "detect_host", unsupported)
    tmpdir = Path(tempfile.mkdtemp(prefix="hs", dir="/tmp"))
    lines: list[str] = []
    try:
        server, broker, _sweeper = serve.build_server(
            socket_path=tmpdir / "c.sock",
            roots=[repo.resolve()],
            image="harness:dev",
            log=lines.append,
        )
        try:
            assert broker is None
            assert isinstance(
                server.credentials, container_env.RequestRefreshingSource
            )
            assert any("plan9" in line for line in lines), (
                f"the fallback was silent: {lines}"
            )
        finally:
            server.server_close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
