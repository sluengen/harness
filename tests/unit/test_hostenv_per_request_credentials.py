"""Credentials are resolved per request, by the host, on both spawn paths (#307).

The design's *Interface / contract* section commits to this in one sentence:

    Credentials are resolved per request through the existing
    ``harness.hostenv.host`` providers and passed to the child by **name**
    (``-e NAME``, value supplied via the subprocess ``env=``), never in argv.
    Per-request resolution, not caching: it preserves today's freshness
    semantics, and brokering is #309.

Both halves matter, and they fail differently:

* **By the host, not from the ambient environment.** ``harness serve`` is a
  long-lived process an operator starts from some shell. If it merely forwards
  whatever ``os.environ`` happened to hold at bind time, a server started from a
  shell without credentials spawns credential-less containers forever — and the
  failure surfaces much later as an in-container 401 that reads as a review
  failure (CAL-941), not as "the server has no credentials".
* **Per request, not once.** A Claude OAuth token expires. A value resolved at
  bind time and cached is correct for an hour and silently wrong after that, in
  a process designed to outlive many verbs. This is the property the wrapper had
  for free by re-running its bash on every call, and the one a persistent host
  process is most likely to lose.

The tests below assert both against a fake provider that **rotates its token on
every read**, so a cached implementation cannot pass: it would hand the second
container the first container's token.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from harness.cli import serve as serve_module
from harness.hostenv import client, container_env
from harness.hostenv import host as host_module
from harness.hostenv.credentials import AgentCredential, TrackerCredentials
from harness.hostenv.host import GitIdentity, HostPlatform

#: Env names the stub docker records, so a test can read what the child was given.
_RECORDED = (
    "GITHUB_TOKEN",
    "LINEAR_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_EXPIRES_AT",
)


class RotatingHost(HostPlatform):
    """A provider whose credentials differ on every resolution.

    Rotation is the discriminator. A resolver called once and cached returns
    ``token-1`` twice; a resolver called per request returns ``token-1`` then
    ``token-2``. No structural assertion can tell those apart — this can.
    """

    def __init__(self, env: dict[str, str] | None = None) -> None:
        super().__init__(name="fake", env=env or {})
        self.reads = 0
        self.refreshes = 0
        self.stale = False
        self.workdirs: list[Path] = []
        self.agent_is_live = False
        self.liveness_probes = 0

    def ssh_agent_is_live(self) -> bool:
        self.liveness_probes += 1
        return self.agent_is_live

    def _next(self) -> int:
        self.reads += 1
        return self.reads

    def agent_credential(self) -> AgentCredential | None:
        nth = self._next()
        # expires_at_ms 0 reads as stale, which is how the refresh path is reached.
        return AgentCredential(token=f"agent-{nth}", expires_at_ms=0 if self.stale else 10**15)

    def refresh_agent_credential(self, timeout_seconds: int | None = None) -> None:
        self.refreshes += 1

    def tracker_credentials(self, workdir: Path) -> TrackerCredentials:
        self.workdirs.append(Path(workdir))
        nth = self._next()
        return TrackerCredentials(
            linear_api_key=f"linear-{nth}", github_token=f"github-{nth}", sources={}
        )

    def git_identity(self) -> GitIdentity:
        return GitIdentity(name="Rotating Op", email="op@example.test")


@pytest.fixture
def rotating(monkeypatch: pytest.MonkeyPatch) -> RotatingHost:
    """Install ``RotatingHost`` as the host every resolution detects."""
    fake = RotatingHost()
    monkeypatch.setattr(host_module, "detect_host", lambda **_: fake)
    return fake


@pytest.fixture
def stub_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A ``docker`` on PATH that records the environment it was handed.

    It records its **own** env, which is exactly what the assertion needs: the
    values are supplied through the subprocess ``env=`` and forwarded by name, so
    what real docker would inject into the container is what this process sees.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    record = tmp_path / "docker-env.log"

    dumps = "".join(f'printf "%s=%s\\n" {name} "${name}" >> "{record}";' for name in _RECORDED)
    stub = bindir / "docker"
    stub.write_text(f"#!/bin/sh\n{dumps}\nprintf -- '---\\n' >> \"{record}\"\nexit 0\n")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return record


def spawned_envs(record: Path) -> list[dict[str, str]]:
    """One dict per spawn, in order."""
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


@pytest.fixture
def stdio() -> tuple[int, int, int]:
    read, write = os.pipe()
    try:
        yield (read, write, write)
    finally:
        os.close(read)
        os.close(write)


@pytest.fixture
def server_factory(tmp_path: Path, stub_docker: Path):
    """A bound ``VerbServer`` on a short-enough AF_UNIX path.

    These tests call :meth:`VerbServer.spawn` directly rather than going over the
    wire — resolution is a property of the spawn, and driving a live socket would
    add a thread and a protocol round trip to an assertion about neither.
    """
    made: list[serve_module.VerbServer] = []

    def build(repo: Path) -> serve_module.VerbServer:
        tmpdir = Path(tempfile.mkdtemp(prefix="hs", dir="/tmp"))
        server = serve_module.VerbServer(
            socket_path=tmpdir / "c.sock",
            roots=[repo.resolve()],
            image="harness:dev",
            env={"HOME": str(tmp_path / "home"), "PATH": os.environ["PATH"]},
        )
        made.append((server, tmpdir))
        return server

    try:
        yield build
    finally:
        for server, tmpdir in made:
            server.server_close()
            shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def unreachable_socket(tmp_path: Path) -> Path:
    """A socket path nothing listens on, so ``client.run`` takes the AC-3 path."""
    return tmp_path / "no-such.sock"


def _client_env(tmp_path: Path, socket_at: Path) -> dict[str, str]:
    """A caller environment holding **no** credentials.

    This is the scenario the finding names: a ``harness serve`` (or a wrapper
    invocation) started from a shell that never exported a token. Every credential
    in the spawned container must therefore have come from the provider.
    """
    return {
        "HOME": str(tmp_path / "home"),
        "HARNESS_CONTROL_SOCKET": str(socket_at),
        "PATH": os.environ["PATH"],
    }


# ---------------------------------------------------------------------------
# Resolution happens at all — the credential-less shell scenario.
# ---------------------------------------------------------------------------


def test_the_direct_spawn_resolves_credentials_rather_than_forwarding_the_ambient_env(
    tmp_path: Path,
    repo: Path,
    rotating: RotatingHost,
    stub_docker: Path,
    unreachable_socket: Path,
    stdio: tuple[int, int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in _RECORDED:
        monkeypatch.delenv(name, raising=False)

    code = client.run(
        repo=repo,
        argv=["status", "R1"],
        env=_client_env(tmp_path, unreachable_socket),
        stdio=stdio,
    )

    assert code == 0
    envs = spawned_envs(stub_docker)
    assert len(envs) == 1, "the verb container did not run"
    assert envs[0]["GITHUB_TOKEN"].startswith("github-"), (
        "the container was spawned with no resolved GITHUB_TOKEN — the client "
        "forwarded the ambient environment instead of asking the host providers"
    )
    assert envs[0]["CLAUDE_CODE_OAUTH_TOKEN"].startswith("agent-")
    assert envs[0]["LINEAR_API_KEY"].startswith("linear-")


def test_the_server_resolves_credentials_rather_than_forwarding_the_ambient_env(
    tmp_path: Path,
    repo: Path,
    rotating: RotatingHost,
    stub_docker: Path,
    stdio: tuple[int, int, int],
    server_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in _RECORDED:
        monkeypatch.delenv(name, raising=False)
    server = server_factory(repo)

    server.spawn(repo=repo, argv=["status", "R1"], fds=list(stdio))

    envs = spawned_envs(stub_docker)
    assert len(envs) == 1, "the verb container did not run"
    assert envs[0]["GITHUB_TOKEN"].startswith("github-"), (
        "a `harness serve` started from a shell with no credentials spawned a "
        "credential-less container — resolution must go through the providers"
    )
    assert envs[0]["CLAUDE_CODE_OAUTH_TOKEN"].startswith("agent-")


# ---------------------------------------------------------------------------
# Per request, not once — the property a persistent process is apt to lose.
# ---------------------------------------------------------------------------


def test_the_direct_spawn_resolves_afresh_on_every_request(
    tmp_path: Path,
    repo: Path,
    rotating: RotatingHost,
    stub_docker: Path,
    unreachable_socket: Path,
    stdio: tuple[int, int, int],
) -> None:
    env = _client_env(tmp_path, unreachable_socket)

    client.run(repo=repo, argv=["status", "R1"], env=env, stdio=stdio)
    client.run(repo=repo, argv=["status", "R2"], env=env, stdio=stdio)

    envs = spawned_envs(stub_docker)
    assert len(envs) == 2
    assert envs[0]["GITHUB_TOKEN"] != envs[1]["GITHUB_TOKEN"], (
        "both containers were given the same token from a rotating provider — the "
        "resolution is cached, so an expired token is never renewed"
    )


def test_the_server_resolves_afresh_on_every_request(
    tmp_path: Path,
    repo: Path,
    rotating: RotatingHost,
    stub_docker: Path,
    stdio: tuple[int, int, int],
    server_factory,
) -> None:
    """The load-bearing case: one process, many verbs, a token that expires."""
    server = server_factory(repo)

    server.spawn(repo=repo, argv=["status", "R1"], fds=list(stdio))
    server.spawn(repo=repo, argv=["status", "R2"], fds=list(stdio))

    envs = spawned_envs(stub_docker)
    assert len(envs) == 2
    assert envs[0]["CLAUDE_CODE_OAUTH_TOKEN"] != envs[1]["CLAUDE_CODE_OAUTH_TOKEN"], (
        "the second verb ran with the first verb's agent token — a long-lived "
        "server that caches credentials serves a stale token until it restarts"
    )


def test_a_stale_agent_token_is_refreshed_before_the_container_is_spawned(
    tmp_path: Path,
    repo: Path,
    rotating: RotatingHost,
    stub_docker: Path,
    unreachable_socket: Path,
    stdio: tuple[int, int, int],
) -> None:
    """Freshness semantics, not merely re-reading a stale store."""
    rotating.stale = True

    client.run(
        repo=repo,
        argv=["status", "R1"],
        env=_client_env(tmp_path, unreachable_socket),
        stdio=stdio,
    )

    assert rotating.refreshes == 1, (
        "a token at or inside the refresh window was passed through unrefreshed"
    )


def test_the_tracker_credentials_are_resolved_against_the_requested_repo(
    tmp_path: Path,
    repo: Path,
    rotating: RotatingHost,
    stub_docker: Path,
    unreachable_socket: Path,
    stdio: tuple[int, int, int],
) -> None:
    """``.env`` lives in the target repo, so the workdir must be *that* repo.

    Resolving against the server's own cwd would read the wrong ``.env`` — the
    exact bug a persistent process invites, since its cwd is whatever shell
    started it rather than the repo any given request names.
    """
    client.run(
        repo=repo,
        argv=["status", "R1"],
        env=_client_env(tmp_path, unreachable_socket),
        stdio=stdio,
    )

    assert rotating.workdirs == [repo.resolve()], (
        f"tracker credentials were resolved against {rotating.workdirs} rather "
        f"than the requested repo {repo.resolve()}"
    )


# ---------------------------------------------------------------------------
# Non-vacuity: the recorder must be capable of reporting a missing value.
# ---------------------------------------------------------------------------


def test_the_recorder_reports_an_unset_variable_as_empty(
    tmp_path: Path,
    repo: Path,
    stub_docker: Path,
    unreachable_socket: Path,
    stdio: tuple[int, int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control for every assertion above.

    With **no** provider installed and nothing in the environment, the recorded
    values must come back empty. If the recorder reported something either way,
    ``startswith("github-")`` above would be proving nothing about resolution.
    """
    for name in _RECORDED:
        monkeypatch.delenv(name, raising=False)

    class NoCredentials(RotatingHost):
        def agent_credential(self) -> AgentCredential | None:
            return None

        def tracker_credentials(self, workdir: Path) -> TrackerCredentials:
            return TrackerCredentials(linear_api_key=None, github_token=None, sources={})

    monkeypatch.setattr(host_module, "detect_host", lambda **_: NoCredentials())

    client.run(
        repo=repo,
        argv=["status", "R1"],
        env=_client_env(tmp_path, unreachable_socket),
        stdio=stdio,
    )

    envs = spawned_envs(stub_docker)
    assert len(envs) == 1
    assert envs[0]["GITHUB_TOKEN"] == ""
    assert envs[0]["CLAUDE_CODE_OAUTH_TOKEN"] == ""


def test_an_unsupported_host_stops_the_client_before_a_blank_credential_ships(
    tmp_path: Path,
    repo: Path,
    stub_docker: Path,
    unreachable_socket: Path,
    stdio: tuple[int, int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wrapper's exit-2 contract, preserved across the rewire.

    ``python3 -m harness.hostenv env`` exits 2 on an unsupported host and the
    wrapper stops. The client inherits that surface, so the behaviour must not be
    lost when the wrapper stops calling it.
    """

    def unsupported(**_: object) -> HostPlatform:
        raise host_module.UnsupportedHost(platform="plan9", needed="credential-store")

    monkeypatch.setattr(host_module, "detect_host", unsupported)

    code = client.run(
        repo=repo,
        argv=["status", "R1"],
        env=_client_env(tmp_path, unreachable_socket),
        stdio=stdio,
    )

    assert code == 2
    assert spawned_envs(stub_docker) == [], (
        "a container was spawned on an unsupported host — a blank credential "
        "surfaces later as a 401 rather than here as a named refusal"
    )


def test_the_agent_socket_is_forwarded_only_when_the_host_agent_is_live(
    rotating: RotatingHost,
    repo: Path,
) -> None:
    """The wrapper's ``SSH_AUTH_SOCK`` **and** ``ssh-add -l`` gate, preserved.

    A bare ``SSH_AUTH_SOCK`` is not evidence of a usable agent — the variable
    outlives the agent it names, so a stale one is common. Forwarding on the
    variable alone mounts a dead socket and adds ``--group-add 0``, and every
    ``git push`` over SSH then fails against an agent that holds nothing, instead
    of falling back to tokenized https.

    The inverse gate is the one that already cost a session: gating on the in-VM
    path ``/run/host-services/ssh-auth.sock`` ran host-side, was always false, and
    silently disabled forwarding on every close.
    """
    rotating.env["SSH_AUTH_SOCK"] = "/tmp/agent.sock"

    rotating.agent_is_live = False
    assert container_env.resolve_container_env(repo, host=rotating).ssh_agent is None, (
        "a socket whose agent holds no key was forwarded anyway"
    )

    rotating.agent_is_live = True
    forwarded = container_env.resolve_container_env(repo, host=rotating).ssh_agent
    assert forwarded is not None, "a live agent was not forwarded"
    assert forwarded.probed == "/tmp/agent.sock", (
        "the probed socket must be the host's own — it is the liveness signal"
    )


def test_no_agent_socket_is_forwarded_when_the_variable_is_unset(
    rotating: RotatingHost,
    repo: Path,
) -> None:
    """The control: with nothing to forward, liveness is never consulted."""
    rotating.env.pop("SSH_AUTH_SOCK", None)
    rotating.agent_is_live = True

    resolved = container_env.resolve_container_env(repo, host=rotating)

    assert resolved.ssh_agent is None
    assert rotating.liveness_probes == 0, (
        "an `ssh-add -l` subprocess ran with no socket to check — that is a "
        "per-request cost buying nothing"
    )


def test_the_resolved_git_identity_reaches_the_container(
    tmp_path: Path,
    repo: Path,
    rotating: RotatingHost,
    stub_docker: Path,
    unreachable_socket: Path,
    stdio: tuple[int, int, int],
) -> None:
    """The wrapper forwarded the operator's configured identity; so must this.

    Losing it is silent: commits still land, attributed to the ``Harness``
    fallback, and nothing fails.
    """
    from harness.hostenv import spawn

    argv = spawn.build_docker_argv(
        repo=repo,
        argv=["status"],
        image="harness:dev",
        env_names=(),
        home=tmp_path,
        git_identity={"GIT_AUTHOR_NAME": "Rotating Op", "GIT_AUTHOR_EMAIL": "op@example.test"},
    )

    assert "GIT_AUTHOR_NAME=Rotating Op" in argv
    assert "GIT_AUTHOR_EMAIL=op@example.test" in argv
    assert "GIT_COMMITTER_NAME=Harness" in argv, (
        "a field the caller did not supply must keep its default rather than "
        "vanishing — the wrapper defaulted per field, not all-or-nothing"
    )
