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

Everything the caller controls (ticket id, run id, decision value) lands *after*
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
    "RunResult",
    "Runner",
    "LauncherError",
    "build_verb_argv",
    "ControlServer",
]

#: The complete operation surface exposed over the control socket. There is no
#: other path — an op outside this set is refused (AC-5).
OPERATIONS: frozenset[str] = frozenset({"start", "status", "events", "cancel", "decision"})

#: Default verb image; overridable via ``HARNESS_IMAGE`` by the CLI.
DEFAULT_IMAGE = "harness:dev"

#: Secrets the launcher injects per run, by name (value pulled from the
#: launcher's own environment by docker). The caller can set none of these.
INJECTED_ENV: tuple[str, ...] = ("LINEAR_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")

#: Required params per operation. Every key here must be present.
_REQUIRED: dict[str, tuple[str, ...]] = {
    "start": ("repo", "ticket"),
    "status": ("repo", "run_id"),
    "events": ("repo", "run_id"),
    "cancel": ("repo", "run_id"),
    "decision": ("repo", "run_id", "value"),
}

#: Optional params per operation. Anything outside required ∪ optional is rejected.
_OPTIONAL: dict[str, tuple[str, ...]] = {
    "start": ("base",),
    "status": (),
    "events": (),
    "cancel": (),
    "decision": (),
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
    if op == "status":
        return ["status", params["run_id"], "--json"]
    if op == "events":
        return ["events", params["run_id"], "--json"]
    if op == "cancel":
        return ["cancel", params["run_id"]]
    if op == "decision":
        return ["decision", params["run_id"], params["value"]]
    # Unreachable: callers validate op against OPERATIONS first.
    raise LauncherError("unknown_operation", f"unknown operation: {op!r}")


def build_verb_argv(
    request: Mapping[str, Any],
    *,
    image: str,
    roots: list[Path],
    host_env: Mapping[str, str],
) -> list[str]:
    """Construct the full ``docker run`` argv for ``request``, server-side.

    Raises :class:`LauncherError` on any rejection — an unknown op, a param
    outside the op's allowlist, a missing/ill-typed param, or a repo outside
    ``roots``. On success the returned argv is a one-shot, unprivileged sibling
    launch whose only bind mount is the allowlist-resolved repo at an identical
    host/container path, with scoped credentials injected by name.
    """
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
    ) -> None:
        self.host_env: Mapping[str, str] = os.environ if host_env is None else host_env
        self.runner: Runner = _docker_runner if runner is None else runner
        self.image = image
        self.roots = allowed_roots(self.host_env) if roots is None else roots

    def dispatch(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Validate + launch ``request``; return the structured response dict."""
        try:
            argv = build_verb_argv(
                request,
                image=self.image,
                roots=self.roots,
                host_env=self.host_env,
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
        """
        path = Path(socket_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_socket():
            path.unlink()
        return _ControlSocketServer(str(path), self)


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
