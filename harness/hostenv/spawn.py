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

The one exception is the resolved repo path, which must sit in the option region
(it is the mount source). That is why it is the one value validated by content:
a ``:`` in it would inject ``-v`` field structure, so it is refused outright.

**Stdlib only.** ``harness.hostenv`` runs on the host under a bare ``python3``
before any container exists — see the package docstring and
``tests/unit/test_hostenv_stdlib_only.py``.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping, Sequence
from pathlib import Path

__all__ = [
    "CONTAINER_HOME",
    "RepoMismatch",
    "UnsafeRepoPath",
    "WORKSPACE_MOUNT",
    "build_docker_argv",
    "rewrite_repo_argument",
]

#: Where the repo is bind-mounted inside every verb container.
#:
#: **Not the path-equivalent mount ADR 0012 describes** (``-v <repo>:<repo>``).
#: ``runs.worktree_path`` is recorded container-absolute as
#: ``/workspace/.worktrees/harness/<run_id>``, so changing the mount point
#: rewrites the meaning of every already-recorded path and strands every
#: in-flight run across the cutover. Path equivalence is #308's concern, with the
#: ledger migration that makes it safe; this ticket keeps today's mount.
WORKSPACE_MOUNT = "/workspace"

#: The unprivileged in-container user's home — the target of the credential mounts.
CONTAINER_HOME = "/home/harness"

#: Where a forwarded ssh-agent socket appears inside the container.
_AGENT_SOCKET = "/ssh-agent"

#: The **mount source** for the forwarded agent: Docker Desktop bridges the host's
#: agent into the VM at this fixed path. It exists only *inside* the VM — never on
#: the macOS host — so it must not be tested for host-side, and the host's own
#: ``SSH_AUTH_SOCK`` (a per-session launchd path on macOS) must not be used as the
#: source: bind-mounting it forwards nothing and every SSH push fails against a
#: healthy agent. The host socket is the liveness *signal*, not the source.
#:
#: A native Linux daemon would mount the host socket directly. Selecting the source
#: per platform is #308's *platform-specific spawn concerns*; this keeps the
#: wrapper's proven behaviour until that lands.
_HOST_SERVICES_AGENT_SOCKET = "/run/host-services/ssh-auth.sock"

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
    ssh_auth_sock: str | None = None,
    wrapper_status: str = "",
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
    """
    repo = Path(repo)
    if ":" in str(repo):
        raise UnsafeRepoPath(repo)

    out = ["docker", "run", "--rm"]
    if tty:
        out.append("-it")

    out += [
        "-v",
        f"{repo}:{WORKSPACE_MOUNT}",
        "-w",
        WORKSPACE_MOUNT,
        "-v",
        f"{home / '.ssh'}:{CONTAINER_HOME}/.ssh:ro",
        "-v",
        f"{home / '.codex'}:{CONTAINER_HOME}/.codex:ro",
    ]

    if ssh_auth_sock:
        # `ssh_auth_sock` is the *signal* that the host has a live agent (resolved
        # by HostPlatform.ssh_agent_is_live); the mount source is Docker's bridge —
        # see _HOST_SERVICES_AGENT_SOCKET. Forwarded so the container's git can use
        # the operator's agent without the private key ever being mounted.
        # --group-add 0 mirrors the wrapper: the forwarded socket is root-owned and
        # group-rw inside the container, and the image runs as uid 1000.
        out += [
            "-v",
            f"{_HOST_SERVICES_AGENT_SOCKET}:{_AGENT_SOCKET}",
            "-e",
            f"SSH_AUTH_SOCK={_AGENT_SOCKET}",
            "--group-add",
            "0",
        ]

    for name in env_names:
        out += ["-e", name]

    # Pinned by value, never forwarded by name. Both settings are disabled by an
    # *empty* value, so a host exporting them empty would silently switch off the
    # in-container allowlist (CAL-584) and the bytecode guard (#278).
    out += [
        "-e",
        f"HARNESS_WORKSPACE_ROOTS={WORKSPACE_MOUNT}",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-e",
        f"GIT_SSH_COMMAND={_GIT_SSH_COMMAND}",
    ]
    if wrapper_status:
        out += ["-e", f"HARNESS_WRAPPER_STATUS={wrapper_status}"]
    resolved_identity = dict(git_identity or {})
    for name, default in _GIT_IDENTITY_DEFAULTS.items():
        out += ["-e", f"{name}={resolved_identity.get(name) or default}"]

    out.append(image)
    out += list(argv)
    return out


def format_command(argv: Sequence[str]) -> str:
    """A shell-quoted rendering of ``argv``, for a log line or an error message."""
    return shlex.join(argv)
