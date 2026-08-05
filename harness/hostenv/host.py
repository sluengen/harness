"""The host-platform seam: one provider per credential store, everything else shared.

ADR 0012 makes Windows-via-WSL a supported platform. The wrapper's bash could not
express that: it reaches straight for ``security find-generic-password``, which
exists only on macOS. This module puts an interface between the harness and the
host so the *store* can vary while the rest does not.

**Only ``agent_credential`` actually varies today.** Tracker-credential resolution,
git identity and bounded execution are identical on every host, so they live once
on the ABC rather than being duplicated per provider. Duplicating them against no
evidence of divergence would also let the WSL provider's unverified status
contaminate logic that is not platform-dependent at all.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from harness.hostenv.credentials import (
    _DEFAULT_GIT_EMAIL,
    _DEFAULT_GIT_NAME,
    AgentCredential,
    TrackerCredentials,
    parse_credential_store,
    read_dotenv_value,
)
from harness.hostenv.spawn import (
    DOCKER_DESKTOP_AGENT_SOCKET,
    SshAgentForwarding,
    WorkspaceMount,
    WorkspaceNotEquivalent,
)

#: The Keychain service name the Claude CLI stores its credentials under (macOS).
KEYCHAIN_SERVICE = "Claude Code-credentials"

#: Where the Claude CLI stores credentials on a file-store host, relative to home.
#:
#: **This constant is documentation-derived and has not been verified against an
#: installed Claude CLI under WSL** — the machine this was built on is macOS, where
#: the Keychain is used instead. ADR 0012 already records WSL as a claim until it is
#: exercised on a real Windows host (#313 is that ticket). It is a single named
#: constant rather than a search over candidate paths so that the blast radius of
#: being wrong is one line, and ``HARNESS_CLAUDE_CREDENTIALS_FILE`` is the
#: operator's correction seam in the meantime. Do not turn this into a probe.
LINUX_CREDENTIALS_RELPATH = Path(".claude/.credentials.json")

#: Env var an operator sets to point the file-store provider at the real path.
CREDENTIALS_FILE_ENV = "HARNESS_CLAUDE_CREDENTIALS_FILE"

#: Bound on the Claude CLI's own refresh, carried over from the wrapper's ``timeout 60``.
REFRESH_TIMEOUT_SECONDS = 60

#: Markers that identify WSL. ``sys.platform`` cannot: WSL reports ``linux``.
_WSL_MARKERS = re.compile(r"microsoft|wsl", re.IGNORECASE)
_WSL_ENV_MARKER = "WSL_DISTRO_NAME"

#: Filesystem types that reach the **Windows** side from inside a WSL distro.
#: ``drvfs`` is the automounted local drive, ``9p`` the WSL2 transport, ``cifs`` a
#: mapped network drive. A repo on any of them crosses a semantics boundary the
#: verbs depend on not crossing — see :meth:`WslHost.workspace_mount`.
_WINDOWS_FSTYPES = frozenset({"drvfs", "9p", "cifs"})


class UnsupportedHost(Exception):  # noqa: N818 — spec vocabulary, not an "…Error"
    """No credential provider exists for this platform.

    Raised at *detection* time, before any credential is emitted, so an unsupported
    host fails with a named, actionable message rather than producing an empty
    credential that surfaces much later as an in-container 401 (the ticket's
    scenario 3).
    """

    def __init__(self, platform: str, needed: str) -> None:
        self.platform = platform
        self.needed = needed
        super().__init__(
            f"unsupported host platform {platform!r}: no credential provider is "
            f"registered for it (a {needed} provider would be needed). "
            f"Set {CREDENTIALS_FILE_ENV} to a readable Claude credential store, "
            f"or run the harness natively on macOS, Linux or WSL."
        )


@dataclass(frozen=True)
class GitIdentity:
    """The commit identity forwarded into the container."""

    name: str
    email: str


class HostPlatform(ABC):
    """A host the harness can run its pre-container work on."""

    def __init__(self, name: str, env: Mapping[str, str] | None = None) -> None:
        self.name = name
        self.env: dict[str, str] = dict(os.environ if env is None else env)
        #: Human-readable notes about what was tried and what was not found. Never
        #: contains a credential *value* — only its source and the failure.
        self.diagnostics: list[str] = []

    # -- the one genuinely platform-specific operation -----------------------

    @abstractmethod
    def agent_credential(self) -> AgentCredential | None:
        """Read the Claude OAuth credential from this host's store."""

    # -- shared across every provider ---------------------------------------

    def bounded_run(
        self, argv: list[str], seconds: int, env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run ``argv`` with a hard time bound, never through a shell.

        This *replaces* the wrapper's ``timeout``/``gtimeout`` probe rather than
        porting it. That probe existed only because macOS ships neither binary and
        bash cannot bound its own child; Python can. Porting the prefix would leave
        a ``list[str]`` with no consumer.

        Bare command names are used so PATH resolution still binds — which is what
        lets the existing wrapper tests keep stubbing ``git`` and ``docker``.
        A missing binary or a blown bound is a non-zero result, not an exception.
        """
        run_env = dict(self.env if env is None else env)
        try:
            # S603: argv is a caller-supplied list and `shell=False` is explicit, so
            # nothing here is re-parsed by a shell. That is the property this method
            # exists to guarantee — see `test_bounded_run_never_uses_a_shell`.
            return subprocess.run(  # noqa: S603
                argv,
                capture_output=True,
                text=True,
                timeout=seconds,
                env=run_env,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as expired:
            self.diagnostics.append(f"{argv[0]}: exceeded its {seconds}s bound and was killed")
            return subprocess.CompletedProcess(
                argv, returncode=124, stdout=_as_text(expired.stdout), stderr=""
            )
        except OSError as error:
            self.diagnostics.append(f"{argv[0]}: could not be run ({error.strerror or error})")
            return subprocess.CompletedProcess(argv, returncode=127, stdout="", stderr=str(error))

    def refresh_agent_credential(self, timeout_seconds: int | None = None) -> None:
        """Trigger the Claude CLI's own token refresh, best-effort.

        ``claude -p ok`` makes the CLI exchange its stored refresh token and write a
        fresh access token back to whichever store it owns — so this is genuinely
        shared even though reading the store is not. Every failure is swallowed,
        exactly as the wrapper's ``|| true`` did: a refresh that cannot run leaves
        the stale-but-present token in play, and the container's own 401 reports it.
        Turning this into a hard failure would break a working deployment offline.

        ``timeout_seconds`` overrides the bound. It exists so a test can prove the
        hung-refresh path without spending the production bound on every gate run;
        production always takes the default.
        """
        bound = REFRESH_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
        self.bounded_run(["claude", "-p", "ok"], seconds=bound)

    def tracker_credentials(self, workdir: Path) -> TrackerCredentials:
        """Resolve the tracker credentials, precedence env → ``.env`` → ``gh``.

        A consuming repo's long-lived PAT in ``.env`` still beats ``gh``, which is
        why the order is not simply "freshest wins". ``gh`` is consulted only for
        ``GITHUB_TOKEN``, and only when it is still unset: a ``gh`` OAuth token
        rotates roughly every 8 hours and is auto-refreshed from the keyring, so a
        static snapshot goes stale and silently breaks the *unattended* loop, where
        no human is present to refresh it (issue #170).
        """
        dotenv = workdir / ".env"
        values: dict[str, str | None] = {}
        sources: dict[str, str] = {}

        for key in ("LINEAR_API_KEY", "GITHUB_TOKEN"):
            from_env = self.env.get(key)
            if from_env:
                values[key], sources[key] = from_env, "env"
                continue

            from_dotenv = read_dotenv_value(dotenv, key)
            if from_dotenv:
                values[key], sources[key] = from_dotenv, "dotenv"
                continue

            values[key] = None

        if not values.get("GITHUB_TOKEN"):
            result = self.bounded_run(["gh", "auth", "token"], seconds=30)
            token = result.stdout.strip() if result.returncode == 0 else ""
            if token:
                values["GITHUB_TOKEN"], sources["GITHUB_TOKEN"] = token, "gh"

        return TrackerCredentials(
            linear_api_key=values.get("LINEAR_API_KEY"),
            github_token=values.get("GITHUB_TOKEN"),
            sources=sources,
        )

    def ssh_agent_is_live(self) -> bool:
        """Does ``SSH_AUTH_SOCK`` name an agent that actually holds a key?

        The variable routinely outlives the agent it names, so its presence is not
        evidence. Forwarding a dead socket mounts it and joins group 0, and every
        ``git push`` over SSH then fails against an agent holding nothing rather
        than falling back to tokenized https.

        Gating on the *in-VM* path Docker Desktop provides
        (``/run/host-services/ssh-auth.sock``) is the inverse mistake: that path
        never exists host-side, so the test was always false and forwarding was
        silently off on every close. Gate on the host's own agent; let Docker
        supply the socket at mount time.
        """
        return self.bounded_run(["ssh-add", "-l"], seconds=10).returncode == 0

    # -- platform-specific spawn concerns (#308) -----------------------------

    def ssh_agent_forwarding(self) -> SshAgentForwarding | None:
        """How to forward this host's ssh-agent, or ``None`` when there is none.

        The default is the one that holds wherever the daemon shares the host's
        kernel namespace: mount the socket liveness was probed against. macOS is
        the single exception and overrides this.

        The probe runs only when there is a socket to check — it is a subprocess,
        and running it against nothing buys nothing per request.
        """
        socket_path = self.env.get("SSH_AUTH_SOCK") or None
        if socket_path is None or not self.ssh_agent_is_live():
            return None
        return SshAgentForwarding(source=socket_path, probed=socket_path)

    def workspace_mount(self, repo: Path) -> WorkspaceMount:
        """The bind mount for ``repo``, or a refusal when it cannot be equivalent.

        Every host but WSL accepts any resolvable path: one filesystem, one set of
        semantics on both sides of the bind mount.
        """
        return WorkspaceMount.default(repo)

    def git_identity(self) -> GitIdentity:
        """Resolve the commit identity from global git config, with defaults.

        Defaults are applied **per field**: an operator with a configured name but
        no email keeps their name. An all-or-nothing default would discard it.
        """
        name = self._git_config("user.name") or _DEFAULT_GIT_NAME
        email = self._git_config("user.email") or _DEFAULT_GIT_EMAIL
        return GitIdentity(name=name, email=email)

    def _git_config(self, key: str) -> str:
        result = self.bounded_run(["git", "config", "--global", key], seconds=10)
        return result.stdout.strip() if result.returncode == 0 else ""

    def now_ms(self) -> int:
        """Wall-clock milliseconds; overridable in a test that pins the clock."""
        return int(time.time() * 1000)


class MacOSHost(HostPlatform):
    """macOS: the credential lives in the login Keychain.

    A container cannot read the Keychain, which is the whole reason the wrapper
    extracts the token host-side and forwards it as an env var.
    """

    def agent_credential(self) -> AgentCredential | None:
        result = self.bounded_run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"], seconds=30
        )
        if result.returncode != 0:
            self.diagnostics.append(
                f"keychain: no usable item for service {KEYCHAIN_SERVICE!r} "
                f"(security exited {result.returncode})"
            )
            return None

        credential = parse_credential_store(result.stdout)
        if credential is None:
            self.diagnostics.append(
                f"keychain: item {KEYCHAIN_SERVICE!r} did not parse as a Claude credential store"
            )
        return credential

    def ssh_agent_forwarding(self) -> SshAgentForwarding | None:
        """The one platform where the probed socket is not the mountable one.

        macOS's ``SSH_AUTH_SOCK`` is a per-session launchd path that exists only
        host-side; bind-mounting it into the Linux VM forwards nothing and every
        push fails ``Permission denied (publickey)`` against a healthy agent.
        Docker Desktop bridges the agent into the VM at a fixed path instead — so
        the host socket is the liveness *signal* and the bridge is the source.

        ``--group-add 0`` comes with it: the bridged socket is root-owned and
        group-rw inside the container, and the image runs as uid 1000.
        """
        socket_path = self.env.get("SSH_AUTH_SOCK") or None
        if socket_path is None or not self.ssh_agent_is_live():
            return None
        return SshAgentForwarding(
            source=DOCKER_DESKTOP_AGENT_SOCKET,
            probed=socket_path,
            group_add=("0",),
        )


class LinuxHost(HostPlatform):
    """Linux and WSL: the credential lives in a JSON file the operator owns.

    One class serves both because the *store* is the same; the ``name`` differs
    (``wsl`` vs ``linux``) because ADR 0012's follow-on tickets need the
    distinction and because a diagnostic must be able to say which host it is on.
    """

    def credentials_path(self) -> Path:
        """Resolve the credential file, override first.

        Order: ``HARNESS_CLAUDE_CREDENTIALS_FILE`` → ``$CLAUDE_CONFIG_DIR`` →
        ``~/.claude``. The override is first because the default is the one thing
        this ticket could not verify (see :data:`LINUX_CREDENTIALS_RELPATH`).
        """
        override = self.env.get(CREDENTIALS_FILE_ENV)
        if override:
            return Path(override)

        config_dir = self.env.get("CLAUDE_CONFIG_DIR")
        if config_dir:
            return Path(config_dir) / LINUX_CREDENTIALS_RELPATH.name

        home = self.env.get("HOME") or os.path.expanduser("~")
        return Path(home) / LINUX_CREDENTIALS_RELPATH

    def agent_credential(self) -> AgentCredential | None:
        path = self.credentials_path()
        try:
            text = path.read_text()
        except OSError:
            # Name the path. It is the entire remediation for a wrong default:
            # an operator who can see what was tried can point the override at the
            # real store, whereas a bare "no credential" leaves them guessing.
            self.diagnostics.append(
                f"credential store: nothing readable at {path} "
                f"(set {CREDENTIALS_FILE_ENV} if the store lives elsewhere)"
            )
            return None

        credential = parse_credential_store(text)
        if credential is None:
            self.diagnostics.append(
                f"credential store: {path} did not parse as a Claude credential store"
            )
        return credential


class WslHost(LinuxHost):
    """Windows-via-WSL: the same credential store as Linux, a different geography.

    It overrides **only** the two spawn concerns, because they are the only things
    that actually differ. The credential store, tracker credentials, git identity
    and bounded execution are Linux's — duplicating them would let this provider's
    unverified status contaminate logic that is not platform-dependent at all.

    Both overrides exist for the same reason: under WSL there are *two* worlds
    reachable from one path namespace, and a path alone does not say which. The
    Docker Desktop bridge leads to the **Windows** ssh-agent while
    ``SSH_AUTH_SOCK`` names one inside the distro; ``/mnt/c`` leads to the Windows
    filesystem while ``/home`` is the distro's. Guessing either wrong fails
    silently, which is #308's whole problem statement.
    """

    def __init__(
        self,
        name: str,
        env: Mapping[str, str] | None = None,
        mounts_path: Path = Path("/proc/mounts"),
    ) -> None:
        super().__init__(name=name, env=env)
        #: Injected so the branch is exercisable on a macOS dev box, exactly as
        #: ``detect_host``'s ``osrelease_path`` is.
        self.mounts_path = mounts_path

    def workspace_mount(self, repo: Path) -> WorkspaceMount:
        """Refuse a repo on a Windows filesystem; accept one inside the distro.

        **The decided behaviour for the ``/mnt/c/...`` case is refuse** (#308 AC-4).
        A drvfs bind mount does not carry the distro's permission, symlink and case
        semantics, and the verbs depend on all three — mode bits on hooks, the
        ``.git`` *file* of a linked worktree whose ``gitdir:`` pointer must resolve,
        and case-sensitive path comparison in the workspace allowlist. Warning and
        proceeding would reproduce precisely the silent breakage this ticket exists
        to end; calling it supported would be a claim nobody has exercised. Moving
        the repo into the distro filesystem is a remedy the operator controls, so
        the refusal names it, and #313 is where "supported" gets earned.

        There is deliberately **no operator override** here. The
        ``HARNESS_CLAUDE_CREDENTIALS_FILE`` precedent does not transfer: that is a
        *value* an operator can know to be right, whereas whether drvfs preserves
        the semantics the verbs need is not something an env var can assert.
        """
        resolved = Path(repo).resolve()
        fstype = self._fstype_for(resolved)
        if fstype is not None and fstype in _WINDOWS_FSTYPES:
            raise WorkspaceNotEquivalent(
                resolved,
                f"it is on a Windows filesystem ({fstype}), whose in-container "
                f"permission, symlink and case semantics are not the distro's and "
                f"are unverified (#313)",
                "clone the repo inside the WSL filesystem instead, e.g. ~/src/<repo>.",
            )
        return WorkspaceMount.default(resolved)

    def _fstype_for(self, path: Path) -> str | None:
        """The fstype of the longest mount entry containing ``path``.

        Reading the mount table rather than matching ``/mnt/`` is what makes this
        correct on a distro whose ``wsl.conf`` sets a non-default automount
        ``root``, and what stops it condemning an ordinary ``/mnt/data`` on ext4.
        When the table is unreadable it falls back to the documented automount
        prefix — fail *safe*: with no evidence, treating a ``/mnt/<x>/`` repo as
        fine is the one answer that reproduces the silent failure.
        """
        try:
            table = self.mounts_path.read_text()
        except OSError:
            parts = path.parts
            if len(parts) >= 3 and parts[1] == "mnt" and len(parts[2]) == 1:
                return "drvfs"
            return None

        best: tuple[int, str] | None = None
        for line in table.splitlines():
            fields = line.split()
            if len(fields) < 3:
                continue
            mountpoint, fstype = fields[1], fields[2]
            if path == Path(mountpoint) or Path(mountpoint) in path.parents:
                depth = len(Path(mountpoint).parts)
                if best is None or depth > best[0]:
                    best = (depth, fstype)
        return None if best is None else best[1]


def detect_host(
    platform: str,
    osrelease_path: Path = Path("/proc/version"),
    env: Mapping[str, str] | None = None,
) -> HostPlatform:
    """Select the provider for this host.

    Every input is injected — the platform string, the os-release path, the
    environment — so each branch is exercised on any machine. A macOS dev box must
    be able to prove the WSL branch, and detection-by-ambient-state cannot be
    tested at all.

    WSL is deliberately distinguished from plain Linux even though both use the
    same provider today: ``sys.platform`` reports ``linux`` for both, and the
    follow-on ADR 0012 work (bind-mount path translation, ssh-agent forwarding)
    turns on exactly that difference.
    """
    resolved_env = dict(os.environ if env is None else env)

    if platform == "darwin":
        return MacOSHost(name="macos", env=resolved_env)

    if platform.startswith("linux"):
        flavour = _linux_flavour(osrelease_path, resolved_env)
        if flavour == "wsl":
            return WslHost(name=flavour, env=resolved_env)
        return LinuxHost(name=flavour, env=resolved_env)

    raise UnsupportedHost(platform=platform, needed="credential-store")


@dataclass(frozen=True)
class ContainerEnv:
    """Everything the host resolves for one verb container, for one request.

    ``values`` are credential and identity values destined for the spawned
    ``docker`` process's own environment, from which docker forwards the
    credentials **by name** (``-e NAME``) — so no value ever appears in an argv,
    and therefore never in ``ps``. ``git_identity`` is separated out because it is
    pinned *by value* on the docker command line rather than forwarded by name,
    exactly as the wrapper pinned it.
    """

    values: dict[str, str]
    git_identity: dict[str, str]
    diagnostics: tuple[str, ...]
    #: How this host forwards its agent, but **only** when one is actually live —
    #: ``None`` otherwise, so a stale ``SSH_AUTH_SOCK`` never mounts a dead socket.
    #: Provider-produced since #308: which socket is *mounted* is platform-specific
    #: even though which socket is *probed* is not.
    ssh_agent: SshAgentForwarding | None = None
    #: The repo bind mount the provider allows for this request. ``None`` only in
    #: the resolver's own tests; production callers always carry the provider's.
    workspace_mount: WorkspaceMount | None = None


def resolve_container_env(workdir: Path, *, host: HostPlatform | None = None) -> ContainerEnv:
    """Resolve one request's credentials and commit identity through the providers.

    **Called per request, never cached** (#307 design, *Interface / contract*).
    The caching version of this function is correct for an hour: a Claude OAuth
    token expires, and a persistent ``harness serve`` outlives many of them. It is
    also the reason resolution cannot be lifted to process start — a server binds
    once and serves for days, so bind time is the one moment whose environment is
    guaranteed to be stale later.

    ``workdir`` is the **requested repo**, not the caller's cwd: ``.env`` lives in
    the target repo, and a persistent server's cwd is whatever shell started it.

    Raises :class:`UnsupportedHost` — deliberately, rather than returning empty
    values. A blank credential does not fail where it is produced; it fails much
    later as an in-container 401 that reads as a review failure (CAL-941).
    """
    host = detect_host(platform=sys.platform) if host is None else host

    values: dict[str, str] = {}

    tracker = host.tracker_credentials(Path(workdir))
    if tracker.linear_api_key:
        values["LINEAR_API_KEY"] = tracker.linear_api_key
    if tracker.github_token:
        values["GITHUB_TOKEN"] = tracker.github_token

    # An already-exported token short-circuits the whole agent-credential path: no
    # store read, no `claude -p ok`. This is the wrapper's `if [[ -z ... ]]` guard
    # preserved, and it is what lets the wrapper's own tests run without touching a
    # real Keychain.
    if not host.env.get("CLAUDE_CODE_OAUTH_TOKEN"):
        credential = resolve_agent_credential(host)
        if credential is not None:
            values["CLAUDE_CODE_OAUTH_TOKEN"] = credential.token
            values["CLAUDE_CODE_OAUTH_EXPIRES_AT"] = str(credential.expires_at_ms)

    # Both spawn concerns are the provider's since #308. The liveness gate is
    # unchanged — it now lives inside `ssh_agent_forwarding`, so the gate and the
    # mount source are one decision rather than two that can disagree.
    #
    # `workspace_mount` can refuse (WorkspaceNotEquivalent), which propagates: a
    # repo that cannot be mounted equivalently must stop here, where the message
    # names the path and the remedy, rather than running against a directory that
    # does not mean what the caller thinks.
    identity = host.git_identity()
    return ContainerEnv(
        values=values,
        ssh_agent=host.ssh_agent_forwarding(),
        workspace_mount=host.workspace_mount(Path(workdir)),
        git_identity={
            "GIT_AUTHOR_NAME": identity.name,
            "GIT_AUTHOR_EMAIL": identity.email,
            "GIT_COMMITTER_NAME": identity.name,
            "GIT_COMMITTER_EMAIL": identity.email,
        },
        diagnostics=tuple(host.diagnostics),
    )


def resolve_agent_credential(host: HostPlatform) -> AgentCredential | None:
    """Read the credential, refreshing it first if it is at or inside the window.

    A refresh that fails leaves the stale-but-present token in play — the
    container's own 401 is where that belongs, and refusing to start would break a
    deployment whose token is merely close to expiry.
    """
    credential = host.agent_credential()
    if credential is None:
        return None
    if not credential.is_stale(host.now_ms()):
        return credential

    host.refresh_agent_credential()
    return host.agent_credential() or credential


def _linux_flavour(osrelease_path: Path, env: Mapping[str, str]) -> str:
    if env.get(_WSL_ENV_MARKER):
        return "wsl"
    try:
        text = osrelease_path.read_text()
    except OSError:
        return "linux"
    return "wsl" if _WSL_MARKERS.search(text) else "linux"


def _as_text(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return raw
