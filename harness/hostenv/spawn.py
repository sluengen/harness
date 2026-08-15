"""The one home for verb-container construction — ``docker run`` argv (#307, ADR 0012).

ADR 0012 rejected mounting the docker socket into callers and chose a **spawner**
instead. The property that distinguishes the two, quoted from the decision:

    The load-bearing property of a spawner is that the caller never specifies the
    mount, image, privilege, or env — it names a verb and a repo, and the host
    constructs the invocation.

This module *is* that construction. It is imported by both the ``serve`` socket
path and the client's direct-spawn fallback, deliberately: two copies would be two
security postures, and the fallback runs on exactly the days the socket is broken —
the worst time to discover they had drifted.

**How the property is enforced: position, not sanitization.** Every caller-derived
token is appended *after* the image, where docker has stopped parsing options and
is assembling the container's command line. So ``harness start --privileged`` is a
verb argument that ``start`` rejects as an unknown flag; it is never a docker flag.
A blocklist of dangerous option names would be defeated by the next docker release;
a positional rule cannot be, because it does not enumerate anything.

Two values are the exception, and both must sit in the option region because both
are mount sources: the resolved repo path, and — since ssh-agent forwarding moved
behind the provider seam (#308) — the forwarded agent socket, which ``LinuxHost``
and ``WslHost`` take verbatim from ``SSH_AUTH_SOCK``. That is why these are the
values validated by *content*: a ``:`` in either would inject ``-v`` field
structure, so each is refused outright — the repo path by
:meth:`WorkspaceMount.validate`, the socket by
:meth:`SshAgentForwarding.__post_init__`.

The container's uid, in the option region since #380, is a third value there but
not a third exception: it is a pair of **integers** the host read from
``os.getuid()``, so there is no text for a separator to hide in. It is refused
for what it *means* — uid 0 — rather than for what it could inject.

**Stdlib only.** ``harness.hostenv`` runs on the host under a bare ``python3``
before any container exists — see the package docstring and
``tests/unit/test_hostenv_stdlib_only.py``.
"""

# size: the option region and the values allowed into it are one subject. Each of
# the three provider-supplied objects here (the mount, the agent socket, the
# container user) is refused *at construction* precisely so a provider cannot
# carry a bad value to spawn time — which only works while the refusal and the
# emission are the same module. Splitting the value objects out would put the
# validation on one side of an import edge and the argv on the other, and the
# whole point of one home is that the two cannot drift. #380 pushed it ~48 lines
# over; the module docstring is the boundary that would have to move before the
# code does.

from __future__ import annotations

import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "AGENT_SOCKET_TARGET",
    "CONTAINER_HOME",
    "ContainerUser",
    "DOCKER_DESKTOP_AGENT_SOCKET",
    "RepoMismatch",
    "SshAgentForwarding",
    "UnsafeAgentSocket",
    "UnsafeContainerUser",
    "UnsafeRepoPath",
    "WORKSPACE_MOUNT",
    "WorkspaceMount",
    "WorkspaceNotEquivalent",
    "build_docker_argv",
    "rewrite_repo_argument",
]

#: Where the repo is bind-mounted inside every verb container.
#:
#: **Not the path-equivalent mount ADR 0012 describes** (``-v <repo>:<repo>``),
#: and #308 decided it stays that way. ``runs.worktree_path`` is recorded
#: container-absolute as ``/workspace/.worktrees/harness/<run_id>``, so changing
#: the mount point rewrites the meaning of every already-recorded path and
#: strands every in-flight run across the cutover — a ledger migration bundled
#: into a platform refactor. #308 delivers the property ADR 0012 wanted (a file
#: reference means the same thing on both sides) as *mapping* equivalence
#: instead: one :class:`WorkspaceMount` both sides compute with, asserted rather
#: than assumed. The identity mapping remains available as a later variant.
WORKSPACE_MOUNT = "/workspace"

#: The unprivileged in-container user's home — the target of the credential mounts.
CONTAINER_HOME = "/home/harness"

#: Where a forwarded ssh-agent socket appears inside the container.
AGENT_SOCKET_TARGET = "/ssh-agent"

#: The **mount source** for the forwarded agent *on macOS*: Docker Desktop bridges
#: the host's agent into the VM at this fixed path. It exists only *inside* the VM —
#: never on the macOS host — so it must not be tested for host-side, and the host's
#: own ``SSH_AUTH_SOCK`` (a per-session launchd path on macOS) must not be used as
#: the source: bind-mounting it forwards nothing and every SSH push fails against a
#: healthy agent. The host socket is the liveness *signal*, not the source.
#:
#: **Read by ``MacOSHost`` alone** (#308). A native Linux daemon shares the kernel
#: namespace and mounts the probed socket directly; under WSL this path bridges the
#: *Windows* agent while ``SSH_AUTH_SOCK`` names an agent inside the distro — two
#: different agents with two different key sets, which is why reusing this constant
#: there would probe one and forward the other.
DOCKER_DESKTOP_AGENT_SOCKET = "/run/host-services/ssh-auth.sock"

#: The canonical spelling of the repo option (#306). Matches ``--repo <v>`` and
#: ``--repo=<v>``; no other spelling is recognized, because no other is emitted.
_REPO_OPTION = "--repo"

#: Git identity defaults, carried over from the wrapper so a host with no
#: configured identity still produces attributable commits.
_GIT_IDENTITY_DEFAULTS = {
    "GIT_AUTHOR_NAME": "Harness",
    "GIT_AUTHOR_EMAIL": "harness@local",
    "GIT_COMMITTER_NAME": "Harness",
    "GIT_COMMITTER_EMAIL": "harness@local",
}

#: ssh invoked with a pinned config so a host's ``~/.ssh/config`` cannot redirect
#: the container's git traffic.
_GIT_SSH_COMMAND = (
    "ssh -F /dev/null -o StrictHostKeyChecking=accept-new "
    f"-o UserKnownHostsFile={CONTAINER_HOME}/.ssh/known_hosts"
)


class UnsafeRepoPath(Exception):  # noqa: N818 — mirrors WorkspaceNotAllowed
    """A repo path cannot be expressed safely in the docker-option region.

    Raised for a path containing ``:``, the separator ``-v host:container:opts``
    is parsed with. Such a path would let the caller append mount options — the
    one way a caller-derived value could still reach docker's parser despite the
    positional rule, since the repo path is the only one that sits there.
    """

    def __init__(self, repo: Path) -> None:
        self.repo = repo
        super().__init__(
            f"repo path {repo} contains ':', which is the field separator in a "
            f"docker -v specification — it cannot be mounted safely."
        )


class WorkspaceNotEquivalent(Exception):  # noqa: N818 — mirrors WorkspaceNotAllowed
    """The host↔container path mapping is not a bijection, so refuse to spawn.

    Distinct from :class:`UnsafeRepoPath` on purpose. That one is a *security*
    refusal — a ``:`` in the mount source injects docker ``-v`` field structure.
    This is a *portability* refusal: the mount is well-formed but a path would not
    mean the same thing on both sides of the boundary. Folding them would blur
    the two, and an operator reading the message needs to know which one they hit.

    Raised before any token is emitted, because the failure this exists to prevent
    is silent: a wrong mount produces no error at all — the verb simply operates on
    a directory the caller did not name (#308's problem statement).
    """

    def __init__(self, subject: object, reason: str, remedy: str = "") -> None:
        self.subject = subject
        self.reason = reason
        self.remedy = remedy
        message = f"{subject} cannot be mounted equivalently: {reason}"
        super().__init__(f"{message}. {remedy}" if remedy else message)


@dataclass(frozen=True)
class WorkspaceMount:
    """The repo bind mount, and the host↔container path mapping it defines.

    One object rather than three uses of a bare constant: ``target`` is emitted as
    the ``-v`` right field, as ``-w``, **and** as ``HARNESS_WORKSPACE_ROOTS``, so
    those three cannot disagree by construction. When they disagree a file
    reference means a different thing to each of the three parties ADR 0012 names
    — the host process, the client, and the verb container — which is exactly the
    silent failure #308 exists to make loud.

    ``source`` is a **fully resolved** absolute host path. The docker daemon
    resolves the source in its own namespace, so an unresolved ``..`` segment or
    symlink can mount a directory the caller never named.
    """

    source: str
    target: str

    @classmethod
    def default(cls, repo: Path) -> WorkspaceMount:
        """Today's mapping: the resolved repo at :data:`WORKSPACE_MOUNT`.

        Validated on construction, so a caller that only *builds* a mount — the
        socket path's pre-flight, which refuses before docker is touched — gets
        the same refusals as one that goes on to build an argv.
        """
        mount = cls(source=str(Path(repo).resolve()), target=WORKSPACE_MOUNT)
        mount.validate(repo)
        return mount

    def validate(self, repo: Path) -> None:
        """Refuse a mapping that is not a bijection *of the repo the caller named*.

        Checked against ``repo`` rather than in isolation: a mount can be
        perfectly well-formed and still be of the wrong directory, which is the
        failure with no symptom.
        """
        # Checked first, and on the *source* rather than on ``repo``, because the
        # source is what lands in the ``-v`` field. Ordering matters: a colon-
        # bearing path that is also a mismatch is a security refusal, and reporting
        # it as a portability one would send the operator to the wrong remedy.
        if ":" in self.source:
            raise UnsafeRepoPath(Path(self.source))
        resolved = str(Path(repo).resolve())
        if self.source != resolved:
            raise WorkspaceNotEquivalent(
                self.source,
                f"it is not the resolved path of the requested repo ({resolved})",
                "the docker daemon resolves the mount source in its own namespace, "
                "so an unresolved source can mount a directory you did not name.",
            )
        if not self.target.startswith("/") or self.target.rstrip("/") != self.target:
            raise WorkspaceNotEquivalent(
                self.target,
                "a mount target must be an absolute path with no trailing slash",
                "-w and HARNESS_WORKSPACE_ROOTS are absolute-path contracts; a "
                "relative target reads as outside every allowlisted root.",
            )

    def to_container(self, path: Path) -> str:
        """Spell a host path the way the verb container sees it."""
        try:
            relative = Path(path).resolve().relative_to(self.source)
        except ValueError as outside:
            raise WorkspaceNotEquivalent(
                path,
                f"it is not under the mounted repo ({self.source})",
                "only paths inside the workspace cross the container boundary.",
            ) from outside
        return str(Path(self.target) / relative) if str(relative) != "." else self.target

    def from_container(self, path: str) -> Path:
        """The inverse of :meth:`to_container` — a container path back to the host."""
        try:
            relative = Path(path).relative_to(self.target)
        except ValueError as outside:
            raise WorkspaceNotEquivalent(
                path,
                f"it is not under the mount target ({self.target})",
                "only paths inside the workspace cross the container boundary.",
            ) from outside
        return Path(self.source) / relative


@dataclass(frozen=True)
class SshAgentForwarding:
    """How this host forwards its ssh-agent into a verb container.

    ``probed`` is the socket the liveness check actually talked to; ``source`` is
    what gets mounted. They differ on **exactly one** platform — macOS, where the
    host's ``SSH_AUTH_SOCK`` is a per-session launchd path that exists only
    host-side and Docker Desktop bridges the agent into the VM at a fixed path.
    Keeping both on one object is what makes that pairing statable in one place,
    and testable: a provider that probes agent A and mounts agent B passes every
    liveness check and then fails every push against a healthy agent.
    """

    source: str
    probed: str
    target: str = AGENT_SOCKET_TARGET
    #: Supplementary groups the container needs to *reach* the socket. Docker
    #: Desktop's bridged socket is root-owned and group-rw while the image runs as
    #: uid 1000; a socket the invoking user owns needs no such grant, so this is
    #: empty everywhere but macOS rather than pinned globally.
    group_add: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Validated here rather than in ``build_docker_argv`` because this is the
        # one place every construction passes through — the three providers, the
        # tests' helpers, and any later platform. A check at the argv site would
        # leave a provider free to build the malformed object and carry it around
        # until spawn time, which is exactly the "fails far from its cause" shape
        # ``WorkspaceMount.validate`` exists to avoid.
        for label, value in (("source", self.source), ("target", self.target)):
            if ":" in value:
                raise UnsafeAgentSocket(label, value)


class UnsafeAgentSocket(Exception):  # noqa: N818 — mirrors UnsafeRepoPath
    """A forwarded agent socket cannot be expressed safely in the option region.

    The sibling of :class:`UnsafeRepoPath`, for the *second* value that sits in
    the docker-option region. The repo path was the only one until ssh-agent
    forwarding moved behind the provider seam (#308): ``LinuxHost`` and
    ``WslHost`` mount ``SSH_AUTH_SOCK`` verbatim, so the value is environment-
    derived rather than a fixed per-platform constant.
    """

    def __init__(self, label: str, value: str) -> None:
        self.label = label
        self.value = value
        super().__init__(
            f"ssh-agent {label} {value!r} contains ':', which is the field "
            f"separator in a -v host:container:opts mount — docker would parse it "
            f"as a different mount than the one intended"
        )


class UnsafeContainerUser(Exception):  # noqa: N818 — mirrors UnsafeAgentSocket
    """The container would run as root, or as an id that is not one at all.

    Dropping privilege is the property CAL-1008 bought and ADR 0013's threat
    model rests on: this container runs untrusted ticket and diff content through
    LLM agents. Taking the *invoking* uid gives that away the moment an operator
    runs the harness under ``sudo``, so uid 0 is refused rather than forwarded.
    """

    def __init__(self, label: str, value: object) -> None:
        self.label = label
        self.value = value
        super().__init__(
            f"container {label} {value!r} cannot be used: the verb container runs "
            f"untrusted content and must not run as root, and its ids must be "
            f"non-negative integers"
        )


@dataclass(frozen=True)
class ContainerUser:
    """The uid/gid the verb container runs as, or the image's baked user if absent.

    Held as ``int``s, never as text. That is what makes this value safe in the
    docker-option region without content validation: the two *string* values that
    sit there — the mount source and the agent socket — are checked for ``:``
    because they are host-derived text, whereas :meth:`spec` renders integers the
    host read from ``os.getuid()``, a token that cannot carry a space, a flag, or
    a second field. Nothing caller-derived reaches here.
    """

    uid: int
    gid: int

    def __post_init__(self) -> None:
        # Validated at construction, exactly as ``SshAgentForwarding`` is: a
        # provider must not be able to build an unusable object and carry it as
        # far as spawn time, where the failure is one step from docker and many
        # steps from whatever chose the value.
        for label, value in (("uid", self.uid), ("gid", self.gid)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise UnsafeContainerUser(label, value)
        # ``gid == 0`` is deliberately allowed: on a host whose operator's primary
        # group is 0 that is a privilege they already hold, and refusing it would
        # hard-fail an account nobody configured wrongly. uid 0 is the security
        # property; group 0 is not.
        if self.uid == 0:
            raise UnsafeContainerUser("uid", self.uid)

    def spec(self) -> str:
        """The ``--user`` value: both fields, always.

        A bare uid leaves the container's *group* at the image's baked one, which
        owns nothing on the host — half the mismatch this exists to end.
        """
        return f"{self.uid}:{self.gid}"


class RepoMismatch(Exception):  # noqa: N818 — mirrors WorkspaceNotAllowed
    """``argv`` names a ``--repo`` other than the one being mounted.

    Only one repo is mounted per container, so a second one cannot be translated
    into the container's namespace — there is no mount for it to name. Refusing
    is the only honest answer; rewriting it to ``/workspace`` would silently act
    on a different repo than the caller named.
    """

    def __init__(self, requested: str, mounted: Path) -> None:
        self.requested = requested
        self.mounted = mounted
        super().__init__(
            f"--repo {requested} does not name the mounted repo {mounted}; only "
            f"one repo is mounted per verb container."
        )


def rewrite_repo_argument(argv: Sequence[str], repo: Path) -> list[str]:
    """Translate an explicit ``--repo`` from a host path to the container mount.

    #306 put ``--repo <path>`` on every verb, but a *host* path handed to a verb
    running in the container resolves outside its pinned
    ``HARNESS_WORKSPACE_ROOTS=/workspace`` allowlist and is refused. This is the
    translation that makes the flag reachable through the container boundary
    (the argv half of #351).

    Three cases:

    * ``--repo <v>`` / ``--repo=<v>`` naming the mounted repo → rewritten to
      :data:`WORKSPACE_MOUNT`.
    * naming a *different* repo → :class:`RepoMismatch`.
    * absent → forwarded untouched, and the verb emits its own deprecation
      warning exactly as it does today. Appending the flag here would require
      knowing which leaf commands accept it, which this stdlib-only module
      cannot derive from the Typer app it may not import.

    Comparison is by resolved path, not by string: ``/work/repo-evil`` must not
    match ``/work/repo``, which a ``startswith`` check would accept.
    """
    mounted = Path(repo).resolve()
    out = list(argv)

    for index, token in enumerate(out):
        value: str | None = None
        if token == _REPO_OPTION and index + 1 < len(out):
            value = out[index + 1]
            target = index + 1
        elif token.startswith(f"{_REPO_OPTION}="):
            value = token.split("=", 1)[1]
            target = index
        else:
            continue

        if Path(value).resolve() != mounted:
            raise RepoMismatch(value, mounted)
        out[target] = (
            WORKSPACE_MOUNT
            if target == index + 1
            else f"{_REPO_OPTION}={WORKSPACE_MOUNT}"
        )

    return out


def build_docker_argv(
    *,
    repo: Path,
    argv: Sequence[str],
    image: str,
    env_names: Sequence[str],
    home: Path,
    tty: bool = False,
    ssh_agent: SshAgentForwarding | None = None,
    mount: WorkspaceMount | None = None,
    container_user: ContainerUser | None = None,
    wrapper_status: str = "",
    client_version: str = "",
    git_identity: Mapping[str, str] | None = None,
) -> list[str]:
    """Construct the one-shot verb container's ``docker run`` argv.

    ``env_names`` are forwarded **by name** (``-e NAME``), so docker reads each
    value from the spawning process's own environment. A value in the argv would
    be visible in ``ps`` output to every user on the host.

    ``git_identity`` is the one env group pinned **by value** instead, mirroring
    the wrapper's ``-e "GIT_AUTHOR_NAME=${GIT_AUTHOR_NAME:-Harness}"``: it is not a
    secret, and pinning it means a host that exports it empty cannot blank the
    commit attribution. Missing fields fall back to the defaults **per field**, so
    an operator with a configured name but no email keeps their name.

    ``argv`` — the caller's verb and its arguments — is appended last, after the
    image. That position is the whole of AC-4's enforcement; see the module
    docstring.

    ``ssh_agent``, ``mount`` and — since #380 — ``container_user`` are
    **provider-supplied**: each was a macOS constant inlined here, and each is a
    platform-specific half of the spawn. ``None`` means, respectively, *this host
    has no live agent to forward*, *use today's default mapping*, and *this
    host's daemon remaps bind-mount ownership, so the image's baked uid is
    already the owner*. The mount is validated unconditionally before a token is
    emitted — that assertion is the backstop under the client's direct-spawn
    fallback, which has no earlier check.
    """
    repo = Path(repo)
    # Both refusals now live on the mount object — the one place that knows what a
    # ``-v`` field may contain — so the socket path can reach them before it
    # touches docker instead of re-implementing the colon check inline (#308).
    mount = WorkspaceMount.default(repo) if mount is None else mount
    mount.validate(repo)

    out = ["docker", "run", "--rm"]
    if tty:
        out.append("-it")

    if container_user is not None:
        # In the option region, and therefore *before* the image: the caller's own
        # `--user` lands after it, where it is an argument to a harness verb. Two
        # `--user` tokens can appear in one argv and only their position separates
        # the privilege the host chose from the one a ticket asked for.
        out += ["--user", container_user.spec()]

    out += [
        "-v",
        f"{mount.source}:{mount.target}",
        "-w",
        mount.target,
        "-v",
        f"{home / '.ssh'}:{CONTAINER_HOME}/.ssh:ro",
        "-v",
        f"{home / '.codex'}:{CONTAINER_HOME}/.codex:ro",
    ]

    if ssh_agent is not None:
        # Forwarded so the container's git can use the operator's agent without the
        # private key ever being mounted. `probed` is the socket liveness was
        # checked against and `source` is what is mounted; the provider pairs them
        # (see SshAgentForwarding), because on macOS alone they differ.
        out += [
            "-v",
            f"{ssh_agent.source}:{ssh_agent.target}",
            "-e",
            f"SSH_AUTH_SOCK={ssh_agent.target}",
        ]
        for group in ssh_agent.group_add:
            out += ["--group-add", group]

    for name in env_names:
        out += ["-e", name]

    # Pinned by value, never forwarded by name. Both settings are disabled by an
    # *empty* value, so a host exporting them empty would silently switch off the
    # in-container allowlist (CAL-584) and the bytecode guard (#278).
    out += [
        "-e",
        f"HARNESS_WORKSPACE_ROOTS={mount.target}",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-e",
        f"GIT_SSH_COMMAND={_GIT_SSH_COMMAND}",
        # Docker resolves HOME from /etc/passwd, and a numeric `--user` with no
        # entry there gets `HOME=/` — so `uv run` dies initialising its cache at
        # `/.cache/uv` before the verb starts. Pinned on **every** platform, not
        # only where a user is pinned: emitting it conditionally would make "the
        # container's home is CONTAINER_HOME" true by a passwd lookup on macOS
        # and by an env var elsewhere, and two mechanisms for one property is how
        # this drifts from the credential mounts that target the same directory.
        "-e",
        f"HOME={CONTAINER_HOME}",
    ]
    if wrapper_status:
        out += ["-e", f"HARNESS_WRAPPER_STATUS={wrapper_status}"]
    # Only an image install carries a version, and emitting an empty one would be
    # worse than emitting none: `doctor` would report a client "installed from the
    # image, version " for a deployment that has no version at all. Same shape as
    # the wrapper status above, for the same reason (#312).
    if client_version:
        out += ["-e", f"HARNESS_CLIENT_VERSION={client_version}"]
    resolved_identity = dict(git_identity or {})
    for name, default in _GIT_IDENTITY_DEFAULTS.items():
        out += ["-e", f"{name}={resolved_identity.get(name) or default}"]

    out.append(image)
    out += list(argv)
    return out


def format_command(argv: Sequence[str]) -> str:
    """A shell-quoted rendering of ``argv``, for a log line or an error message."""
    return shlex.join(argv)
