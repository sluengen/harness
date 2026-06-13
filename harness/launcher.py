"""Host launcher — the narrow control socket for verb-container launch (CAL-579).

The Hermes runtime drives the harness from inside its own container but must
**not** hold the docker socket. Mounting ``/var/run/docker.sock`` (DooD) is
root-equivalent on the host: anything that reaches it can ``docker run -v /:/host
--privileged …`` and read every secret on the machine. This module is the
host-side **launcher** ("shim") that exposes *only* the harness verb operations
over a unix domain socket and constructs each verb container's ``docker run``
itself.

See ``specs/hermes-orchestration.md`` §Runtime topology → "The launch capability
is narrow, not the docker socket" for the full decision. The load-bearing
property this module enforces:

    The caller never specifies the mount, the image, the privilege, or the env.

The caller says "run verb X on repo Y"; the launcher picks the image, the mount
(from the :data:`~harness.workspace.WORKSPACE_ROOTS_ENV` allowlist), and the
scoped credentials. That closes the host-escape vectors (``-v /:/host``,
``--privileged``, ``exec`` into siblings) at the source — they are simply not
expressible through the protocol.

Design choices (autonomous, recorded here as the as-built record):

* **Protocol** — newline-delimited JSON over a ``AF_UNIX`` ``SOCK_STREAM``
  socket. One request line ``{"op": …, "params": {…}}`` → one response line
  ``{"ok": true, …}`` or ``{"ok": false, "reason": …, "error": …}``. No HTTP
  dependency; trivially driveable from any language Hermes uses.
* **Operation surface** — exactly :data:`OPERATIONS`. There is no ``run`` /
  ``exec`` / ``build`` escape hatch; an unknown op is refused before any docker
  invocation (AC-5).
* **Params are an allowlist per op** — any key outside the op's
  required/optional set is rejected (``bad_params``). This is what makes
  ``{"privileged": true}`` / ``{"volumes": "/:/host"}`` / ``{"image": …}`` /
  ``{"env": …}`` inexpressible (AC-2): there is no param through which a mount,
  an image, a privilege flag, or an env var can be supplied.
* **Path equivalence** — the repo is bind-mounted at the *same* absolute path on
  the host and inside the verb container (``-v <repo>:<repo> -w <repo>``), per
  the spec's §Shared workspace constraint, so a path the caller references
  resolves identically across the boundary.
* **Scoped credentials** — the launcher injects per-run secrets by *name*
  (``-e NAME``), so docker reads the value from the launcher's own environment
  and the secret never lands in the argv (or in ``ps`` output).

Everything the caller controls (ticket id, run id) lands *after*
the image in the argv, i.e. as arguments to the harness verb — never as
``docker run`` options. A ticket literally named ``--privileged`` is an argument
to ``harness start``, not a docker flag.
"""

from __future__ import annotations

import json
import os
import socketserver
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from harness.workspace import (
    WORKSPACE_ROOTS_ENV,
    WorkspaceNotAllowed,
    allowed_roots,
    resolve_within_allowlist,
)

__all__ = [
    "OPERATIONS",
    "DEFAULT_IMAGE",
    "INJECTED_ENV",
    "HOST_SSH_AGENT_SOCKET",
    "GIT_SSH_COMMAND",
    "RunResult",
    "Runner",
    "LauncherError",
    "build_verb_argv",
    "ControlServer",
]

#: The complete operation surface exposed over the control socket. There is no
#: other path — an op outside this set is refused (AC-5). The three lifecycle
#: verbs (``start`` / ``review`` / ``close``) are all here so the agent runtime,
#: which holds the control socket but never the docker socket, can spawn *each*
#: verb as a one-shot sibling container outside itself (CAL-585 AC-1).
OPERATIONS: frozenset[str] = frozenset(
    {"start", "review", "close", "status", "events", "cancel"}
)

#: Default verb image; overridable via ``HARNESS_IMAGE`` by the CLI.
DEFAULT_IMAGE = "harness:dev"

#: Secrets the launcher injects per run, by name (value pulled from the
#: launcher's own environment by docker). The caller can set none of these.
INJECTED_ENV: tuple[str, ...] = ("LINEAR_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")

#: Credential mounts the launcher adds to *every* verb container, server-side —
#: mirroring the documented ``~/bin/harness`` wrapper (``docker/README.md``).
#: ``review`` shells out to codex (needs the subscription auth in ``~/.codex``)
#: and ``close`` does ``git push`` over SSH (needs ``~/.ssh`` + the forwarded
#: agent). Like the mount and the image, these are the *launcher's* choice, not
#: the caller's — there is no param through which a caller can change or suppress
#: them, so they do not weaken the "caller never specifies the mount" property.
CODEX_AUTH_SUBDIR = ".codex"
SSH_SUBDIR = ".ssh"

#: Where Docker Desktop exposes the host ssh-agent to containers (macOS). The
#: wrapper forwards this so ``git push`` over SSH on ``close`` can authenticate;
#: the key itself is Keychain-backed and unusable from the mounted file, so the
#: agent socket is what actually authenticates.
HOST_SSH_AGENT_SOCKET = "/run/host-services/ssh-auth.sock"

#: ``GIT_SSH_COMMAND`` the verb container runs git with — identical to the
#: wrapper, so host-key handling matches between the two launch paths.
GIT_SSH_COMMAND = (
    "ssh -F /dev/null -o StrictHostKeyChecking=accept-new "
    "-o UserKnownHostsFile=/root/.ssh/known_hosts"
)

#: Env-var names a GitHub push token may arrive under, in preference order. On a
#: host without ssh-agent forwarding (no ``/run/host-services/ssh-auth.sock`` and
#: no usable on-disk key — e.g. a Keychain-backed signing key), ``close``'s push
#: over SSH cannot authenticate; the launcher forwards the first of these present
#: by *name* so the verb container can push github over tokenized https instead.
#: ``GH_TOKEN`` is the ``gh`` CLI's own var, so ``export GH_TOKEN=$(gh auth
#: token)`` in the wrapper is enough to engage the fallback. (CAL-622)
GITHUB_TOKEN_ENV_NAMES: tuple[str, ...] = ("GITHUB_TOKEN", "GH_TOKEN")


def _github_token_name(host_env: Mapping[str, str]) -> str | None:
    """The first GitHub-token env var present (non-empty) in ``host_env``, or None.

    Returns the variable *name*, never its value — the value is forwarded to the
    container by name (``-e NAME``) and so never enters argv.
    """
    for name in GITHUB_TOKEN_ENV_NAMES:
        if host_env.get(name, "").strip():
            return name
    return None


def _tokenized_https_argv(token_name: str) -> list[str]:
    """``GIT_CONFIG_*`` env making the verb container push github over tokenized
    https, plus the token forwarded by *name*.

    The close-push fallback when ssh-agent forwarding is unavailable (CAL-622):
    git reads these ``GIT_CONFIG_COUNT`` / ``GIT_CONFIG_KEY_n`` /
    ``GIT_CONFIG_VALUE_n`` vars on every invocation, so ``close``'s ``git push``
    is reconfigured with no verb-code change. Two ``insteadOf`` rules rewrite the
    github ssh remote (scp-form ``git@github.com:`` and ``ssh://git@github.com/``)
    to https, and a credential helper supplies ``x-access-token`` + the token
    read from ``$<token_name>`` at push time. The token *value* never enters argv
    — only its env-var name is forwarded (``-e <token_name>``), so it stays out of
    the process table exactly as the INJECTED_ENV secrets do; the helper runs
    inside the one-shot container and writes nothing to the host.
    """
    # A git credential helper: on `get`, emit the static username and the token
    # from the container env. `!`-prefixed → run as a shell command by git.
    helper = (
        f'!f() {{ test "$1" = get && '
        f"echo username=x-access-token && "
        f'echo "password=${token_name}"; }}; f'
    )
    configs: list[tuple[str, str]] = [
        ("url.https://github.com/.insteadOf", "git@github.com:"),
        ("url.https://github.com/.insteadOf", "ssh://git@github.com/"),
        ("credential.https://github.com.helper", helper),
    ]
    args: list[str] = ["-e", f"GIT_CONFIG_COUNT={len(configs)}"]
    for i, (key, value) in enumerate(configs):
        args += ["-e", f"GIT_CONFIG_KEY_{i}={key}", "-e", f"GIT_CONFIG_VALUE_{i}={value}"]
    # Forward the token by name — docker reads its value from the launcher's env.
    args += ["-e", token_name]
    return args


def _credential_mount_argv(
    home: Path, ssh_auth_sock: str | None, github_token_name: str | None
) -> list[str]:
    """The launcher-controlled credential mounts/env for a verb container.

    ``home`` is the launcher's home directory (its ``~/.codex`` / ``~/.ssh``).
    ``ssh_auth_sock`` is the host ssh-agent socket to forward (the preferred
    transport for ``close``'s push), or ``None`` when no agent is available.
    ``github_token_name`` is the env-var name of a GitHub token to fall back to
    when there is no agent — the launcher prefers the agent and only configures
    the tokenized-https push when ``ssh_auth_sock`` is absent. All values are
    launcher-trusted, never caller-derived.
    """
    args: list[str] = [
        "-v",
        f"{home / CODEX_AUTH_SUBDIR}:/root/.codex",
        "-v",
        f"{home / SSH_SUBDIR}:/root/.ssh:ro",
        "-e",
        f"GIT_SSH_COMMAND={GIT_SSH_COMMAND}",
    ]
    if ssh_auth_sock:
        args += ["-v", f"{ssh_auth_sock}:/ssh-agent", "-e", "SSH_AUTH_SOCK=/ssh-agent"]
    elif github_token_name:
        args += _tokenized_https_argv(github_token_name)
    return args


def _default_ssh_auth_sock(host_env: Mapping[str, str]) -> str | None:
    """Resolve the host ssh-agent socket to forward, mirroring the wrapper.

    Prefers Docker Desktop's fixed host-services path when it is a live socket,
    else the launcher's own ``SSH_AUTH_SOCK`` *when that too is a live socket*;
    ``None`` when neither is a live socket. Both candidates are verified with
    ``is_socket()`` so a stale/invalid ``SSH_AUTH_SOCK`` (a path that no longer
    points at a running agent) resolves to ``None`` rather than a dead path —
    otherwise it would both be mounted into the container and wrongly suppress
    the tokenized-https push fallback (CAL-622). When ``None``, agent forwarding
    is skipped and ``close``'s push falls back to https/token or key files.
    """
    if Path(HOST_SSH_AGENT_SOCKET).is_socket():
        return HOST_SSH_AGENT_SOCKET
    candidate = host_env.get("SSH_AUTH_SOCK", "").strip()
    if candidate and Path(candidate).is_socket():
        return candidate
    return None

#: Required params per operation. Every key here must be present.
_REQUIRED: dict[str, tuple[str, ...]] = {
    "start": ("repo", "ticket"),
    "review": ("repo", "run_id"),
    "close": ("repo", "run_id", "ticket"),
    "status": ("repo", "run_id"),
    "events": ("repo", "run_id"),
    "cancel": ("repo", "run_id"),
}

#: Optional params per operation. Anything outside required ∪ optional is rejected.
_OPTIONAL: dict[str, tuple[str, ...]] = {
    "start": ("base",),
    "review": (),
    "close": (),
    "status": (),
    "events": (),
    "cancel": (),
}


@dataclass(frozen=True)
class RunResult:
    """The bounded result of a verb-container launch.

    Only the exit code and stdout cross back to the caller — stderr / docker
    chatter stays on the host (the context-economy guarantee the verbs share).
    """

    exit_code: int
    stdout: str


#: A runner takes the constructed ``docker run`` argv and returns a
#: :class:`RunResult`. The default actually shells out; tests inject a fake.
Runner = Callable[[list[str]], RunResult]


class LauncherError(Exception):
    """A request was refused before (or instead of) launching a container.

    Carries a structured :attr:`reason` so the response names *why* — one of
    ``unknown_operation`` / ``bad_params`` / ``repo_not_allowed`` /
    ``bad_request``.
    """

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _docker_runner(argv: list[str]) -> RunResult:
    """Default runner: run the constructed ``docker run`` argv as a subprocess."""
    proc = subprocess.run(  # noqa: S603, S607
        argv, capture_output=True, text=True, check=False
    )
    return RunResult(exit_code=proc.returncode, stdout=proc.stdout)


def _verb_command(op: str, params: Mapping[str, str], repo: str) -> list[str]:
    """Map a validated operation to the harness verb argv (after the image).

    ``repo`` is the realpath-resolved, allowlist-checked path; it is used both
    as the mount target and as the verb's ``--repo`` so the two always agree.
    """
    if op == "start":
        cmd = ["start", params["ticket"], "--repo", repo]
        if "base" in params:
            cmd += ["--base", params["base"]]
        return cmd
    if op == "review":
        # Bound to the run by id; the verb reads the run's worktree HEAD from the
        # ledger. ``--repo`` locates the ledger DB (and is the allowlist mount).
        return ["review", "--run-id", params["run_id"], "--repo", repo]
    if op == "close":
        return ["close", params["ticket"], "--run-id", params["run_id"], "--repo", repo]
    if op == "status":
        return ["status", params["run_id"], "--json"]
    if op == "events":
        return ["events", params["run_id"], "--json"]
    if op == "cancel":
        return ["cancel", params["run_id"]]
    # Unreachable: callers validate op against OPERATIONS first.
    raise LauncherError("unknown_operation", f"unknown operation: {op!r}")


def build_verb_argv(
    request: Mapping[str, Any],
    *,
    image: str,
    roots: list[Path],
    host_env: Mapping[str, str],
    home: Path | None = None,
    ssh_auth_sock: str | None = None,
) -> list[str]:
    """Construct the full ``docker run`` argv for ``request``, server-side.

    Raises :class:`LauncherError` on any rejection — an unknown op, a param
    outside the op's allowlist, a missing/ill-typed param, or a repo outside
    ``roots``. On success the returned argv is a one-shot, unprivileged sibling
    launch: the allowlist-resolved repo bind-mounted at an identical
    host/container path, plus the *launcher-controlled* credential mounts every
    verb needs (``~/.codex`` for ``review``'s codex, ``~/.ssh`` + the forwarded
    ssh-agent for ``close``'s push) and the scoped secrets injected by name.
    ``home`` defaults to the launcher's home; ``ssh_auth_sock`` forwards the host
    ssh-agent when given. None of these are caller-derived.
    """
    home = Path.home() if home is None else home
    op = request.get("op")
    if not isinstance(op, str) or op not in OPERATIONS:
        raise LauncherError("unknown_operation", f"unknown operation: {op!r}")

    params_obj = request.get("params", {})
    if not isinstance(params_obj, Mapping):
        raise LauncherError("bad_params", "params must be a JSON object")

    allowed = set(_REQUIRED[op]) | set(_OPTIONAL[op])
    extra = sorted(set(params_obj) - allowed)
    if extra:
        raise LauncherError(
            "bad_params",
            f"unexpected params for {op!r}: {extra} (allowed: {sorted(allowed)})",
        )
    missing = [k for k in _REQUIRED[op] if k not in params_obj]
    if missing:
        raise LauncherError("bad_params", f"missing params for {op!r}: {missing}")

    params: dict[str, str] = {}
    for key, value in params_obj.items():
        if not isinstance(value, str):
            raise LauncherError("bad_params", f"param {key!r} must be a string")
        params[key] = value

    try:
        repo = str(resolve_within_allowlist(params["repo"], roots))
    except WorkspaceNotAllowed as exc:
        raise LauncherError("repo_not_allowed", str(exc)) from exc

    # The resolved repo path is the ONLY caller-derived value that enters the
    # docker-option region (``-v <repo>:<repo>``, ``-w <repo>``,
    # ``-e HARNESS_WORKSPACE_ROOTS=<repo>``). A ``:`` is a legal POSIX path
    # character that survives ``Path.resolve()`` and the allowlist check, but it
    # is *also* the ``-v src:dst[:opts]`` field separator — so a path like
    # ``/work/repo:/etc`` would let the caller dictate the mount destination,
    # defeating the "caller never specifies the mount" property. Reject it: a
    # real repo path never contains a colon.
    if ":" in repo:
        raise LauncherError(
            "repo_not_allowed",
            f"repo path {repo!r} contains ':', which would inject docker mount "
            "(-v/-e) option structure",
        )

    # Construct the launch server-side. The only caller-derived value that enters
    # the docker-option region is the *resolved*, colon-free repo path (validated
    # above); everything else the caller supplied lands after the image, as verb
    # args.
    argv: list[str] = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{repo}:{repo}",
        "-w",
        repo,
        "-e",
        f"{WORKSPACE_ROOTS_ENV}={repo}",
    ]
    # Launcher-controlled credential mounts (codex auth, ssh, ssh-agent) — the
    # same surface the ~/bin/harness wrapper supplies, so launcher-spawned
    # `review`/`close` containers can authenticate. Caller-uncontrollable.
    # Prefer the forwarded ssh-agent; only when it is absent does a GitHub token
    # engage the tokenized-https push fallback (CAL-622). The token is a bearer
    # push credential, so it is scoped to the only verb that pushes — `close`.
    # It is never injected into `review`, which runs codex unsandboxed and has no
    # need to push: keeping the push credential out of that container denies
    # reviewed repository content any path to exfiltrate it.
    github_token_name = (
        _github_token_name(host_env) if op == "close" and not ssh_auth_sock else None
    )
    argv += _credential_mount_argv(home, ssh_auth_sock, github_token_name)
    for name in INJECTED_ENV:
        if name in host_env:
            argv += ["-e", name]
    argv.append(image)
    argv += _verb_command(op, params, repo)
    return argv


class ControlServer:
    """Dispatches control-socket requests to server-side verb launches.

    Holds the launch configuration (runner, image, allowlist roots, host env)
    and turns one request into one response. The transport (a unix domain
    socket) is created by :meth:`create_server`; the request handling itself is
    pure and unit-testable via :meth:`dispatch` / :meth:`process_line`.
    """

    def __init__(
        self,
        *,
        runner: Runner | None = None,
        image: str = DEFAULT_IMAGE,
        roots: list[Path] | None = None,
        host_env: Mapping[str, str] | None = None,
        home: Path | None = None,
        ssh_auth_sock: str | None = None,
    ) -> None:
        self.host_env: Mapping[str, str] = os.environ if host_env is None else host_env
        self.runner: Runner = _docker_runner if runner is None else runner
        self.image = image
        self.roots = allowed_roots(self.host_env) if roots is None else roots
        self.home = Path.home() if home is None else home
        self.ssh_auth_sock = (
            _default_ssh_auth_sock(self.host_env) if ssh_auth_sock is None else ssh_auth_sock
        )

    def dispatch(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Validate + launch ``request``; return the structured response dict."""
        try:
            argv = build_verb_argv(
                request,
                image=self.image,
                roots=self.roots,
                host_env=self.host_env,
                home=self.home,
                ssh_auth_sock=self.ssh_auth_sock,
            )
        except LauncherError as exc:
            return {"ok": False, "reason": exc.reason, "error": str(exc)}
        result = self.runner(argv)
        return {
            "ok": True,
            "operation": request["op"],
            "exit_code": result.exit_code,
            "stdout": result.stdout,
        }

    def process_line(self, raw: bytes) -> bytes:
        """Parse one NDJSON request line and return one NDJSON response line."""
        try:
            request = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            response: dict[str, Any] = {
                "ok": False,
                "reason": "bad_request",
                "error": "request is not valid JSON",
            }
        else:
            if not isinstance(request, dict):
                response = {
                    "ok": False,
                    "reason": "bad_request",
                    "error": "request must be a JSON object",
                }
            else:
                response = self.dispatch(request)
        return (json.dumps(response) + "\n").encode()

    def create_server(self, socket_path: Path | str) -> _ControlSocketServer:
        """Bind a unix-domain control socket and return the (unstarted) server.

        The caller runs :meth:`~socketserver.BaseServer.serve_forever` (the CLI)
        or drives it from a thread (tests). A stale socket file at
        ``socket_path`` is removed first; the parent directory is created.

        The socket (and any directory we create for it) is restricted to the
        owner. On Linux the ``$XDG_RUNTIME_DIR`` home is ``0700`` for free; on
        macOS (the documented target) the ``~/.harness`` fallback is not, and
        ``AF_UNIX`` honours mode bits there — so a world-connectable socket
        would let another local account drive verb launches (CAL-617).
        """
        path = Path(socket_path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.exists() or path.is_socket():
            path.unlink()
        server = _ControlSocketServer(str(path), self)
        os.chmod(path, 0o600)
        return server


class _ControlSocketServer(socketserver.ThreadingUnixStreamServer):
    """A threaded ``AF_UNIX`` server bound to a :class:`ControlServer`."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, socket_path: str, control: ControlServer) -> None:
        self.control = control
        super().__init__(socket_path, _ControlRequestHandler)


class _ControlRequestHandler(socketserver.StreamRequestHandler):
    """Reads one request line, writes one response line, closes the connection."""

    def handle(self) -> None:
        line = self.rfile.readline()
        if not line:
            return
        control = cast(_ControlSocketServer, self.server).control
        self.wfile.write(control.process_line(line))
