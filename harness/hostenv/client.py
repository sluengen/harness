"""The control-socket client — the wrapper's handle on the verbs (#307, ADR 0012).

``docker/harness-wrapper.sh`` ends in

    exec python3 -m harness.hostenv.client "$(pwd)" -- "$@"

which is the whole of the wrapper's remaining runtime work. This module connects
to :mod:`harness.hostenv.protocol`'s socket, hands the server its own
stdin/stdout/stderr, and adopts the container's exit code — or, when the socket
is unreachable, spawns the identical container itself.

**Two equal paths, one construction.** Both call
:func:`harness.hostenv.spawn.build_docker_argv`. ADR 0012 requires the fallback
"built in from the start rather than added after the first outage", and sharing
the construction is what makes that more than a promise: the fallback runs on the
days the socket is broken, so a divergence would surface at the worst moment.

**Falling back is a connect-time decision only.** Once the request is on the wire
the verb may already be running. A lost *response* therefore exits 1 and names
the ledger as the record, rather than re-spawning — running a ``close`` twice
(merging and pushing twice) is the worst failure available to this design, and it
is strictly worse than reporting an uncertain outcome.

Stdlib only — see the package docstring.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from harness.hostenv import container_env, host, protocol, spawn

__all__ = [
    "DEFAULT_IMAGE",
    "FORWARDED_ENV_NAMES",
    "parse_argv",
    "run",
]

#: The verb image. ``HARNESS_IMAGE`` overrides it for a local build.
DEFAULT_IMAGE = "harness:dev"

#: Secrets and identity forwarded **by name**, so their values are read from this
#: process's environment by docker and never appear in any argv (or in ``ps``).
FORWARDED_ENV_NAMES = (
    "LINEAR_API_KEY",
    "GITHUB_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_EXPIRES_AT",
)


@dataclass(frozen=True)
class Invocation:
    repo: Path
    argv: list[str]


def parse_argv(raw: list[str]) -> Invocation:
    """Split ``<repo> -- <verb argv…>``.

    The separator is required rather than inferred. The repo is a positional and
    verb argv is arbitrary, so without an explicit ``--`` a verb argument that
    happened to look like a path would be ambiguous — and guessing wrong would
    point a mutating verb at the wrong repo.
    """
    if "--" not in raw:
        sys.stderr.write(
            "usage: python3 -m harness.hostenv.client <repo> -- <verb> [args…]\n"
        )
        raise SystemExit(2)

    split = raw.index("--")
    if split != 1:
        sys.stderr.write("harness: exactly one repo must precede '--'\n")
        raise SystemExit(2)

    return Invocation(repo=Path(raw[0]), argv=list(raw[split + 1 :]))


def _resolve_stdio(stdio: tuple[int, int, int] | None) -> tuple[int, int, int]:
    """The three file descriptors the verb container inherits.

    An explicit parameter rather than an ambient read of ``sys.std*``: these fds
    are handed to another process, so which ones they are is part of the call,
    not of the interpreter's global state. It is also the only way to exercise
    the fd-passing path under a test runner that replaces ``sys.stdin`` with a
    pseudofile having no ``fileno()``.
    """
    if stdio is not None:
        return stdio
    return (sys.stdin.fileno(), sys.stdout.fileno(), sys.stderr.fileno())


def _is_a_tty(fd: int) -> bool:
    try:
        return os.isatty(fd)
    except OSError:
        return False


def _spawn_directly(
    *, repo: Path, argv: list[str], env: dict[str, str], stdio: tuple[int, int, int]
) -> int:
    """Run the verb container in this process's stead. The AC-3 path.

    Credentials are resolved here, for this request, exactly as the socket path
    resolves them for its own — one resolver, so the fallback cannot ship a
    credential-less container on the days the socket is broken.
    """
    try:
        resolved = container_env.resolve_container_env(repo)
    except host.UnsupportedHost as unsupported:
        # Exit 2 before anything is spawned, inheriting `python3 -m harness.hostenv
        # env`'s contract: an unsupported host must stop here, where the message
        # names the cause, rather than shipping a blank credential that surfaces
        # much later as an in-container 401.
        sys.stderr.write(f"harness: {unsupported}\n")
        return 2
    except spawn.WorkspaceNotEquivalent as not_equivalent:
        # The same contract for the same reason (#308): a repo the provider cannot
        # mount equivalently stops here rather than running against a path that
        # means something else inside the container. Refusing on both paths with
        # the same code is what stops the fallback being the lenient one.
        sys.stderr.write(f"harness: {not_equivalent}\n")
        return 2

    docker_argv = spawn.build_docker_argv(
        repo=repo,
        argv=argv,
        image=env.get("HARNESS_IMAGE") or DEFAULT_IMAGE,
        env_names=FORWARDED_ENV_NAMES,
        home=Path(env.get("HOME", str(Path.home()))),
        tty=_is_a_tty(stdio[0]),
        ssh_agent=resolved.ssh_agent,
        mount=resolved.workspace_mount,
        wrapper_status=env.get("HARNESS_WRAPPER_STATUS", ""),
        git_identity=resolved.git_identity,
    )
    for note in resolved.diagnostics:
        sys.stderr.write(f"harness: {note}\n")
    completed = subprocess.run(  # noqa: S603 — argv is host-constructed; see spawn.py
        docker_argv,
        env={**os.environ, **env, **resolved.values},
        stdin=stdio[0],
        stdout=stdio[1],
        stderr=stdio[2],
        check=False,
    )
    return completed.returncode


def run(
    *,
    repo: Path,
    argv: list[str],
    env: dict[str, str] | None = None,
    stdio: tuple[int, int, int] | None = None,
) -> int:
    """Run one verb, over the socket when it answers and directly when it does not.

    Returns the exit code this process should adopt.
    """
    env = dict(os.environ if env is None else env)
    resolved = Path(repo).resolve()
    fds = _resolve_stdio(stdio)

    # The argv translation happens once, here, before either path — so the socket
    # and the fallback send byte-identical verb argv, and a mismatch is refused
    # before anything is spawned.
    try:
        translated = spawn.rewrite_repo_argument(argv, resolved)
    except spawn.RepoMismatch as exc:
        sys.stderr.write(f"harness: {exc}\n")
        return 2
    except spawn.UnsafeRepoPath as exc:
        sys.stderr.write(f"harness: {exc}\n")
        return 2

    path = protocol.socket_path(env)
    conn = _connect(path)
    if conn is None:
        sys.stderr.write(
            f"harness: control socket {path} unreachable — "
            f"spawning the verb container directly\n"
        )
        return _spawn_directly(repo=resolved, argv=translated, env=env, stdio=fds)

    with conn:
        request = protocol.encode_request(repo=resolved, argv=translated).encode()
        try:
            socket.send_fds(conn, [request], list(fds))
        except OSError as exc:
            # Nothing was delivered, so the verb cannot have started: this is
            # still a connect-time failure and falling back is safe.
            sys.stderr.write(
                f"harness: control socket {path} failed mid-send ({exc}) — "
                f"spawning the verb container directly\n"
            )
            return _spawn_directly(repo=resolved, argv=translated, env=env, stdio=fds)

        raw = _read_response(conn)

    if not raw:
        # The request was delivered. The verb may be running or finished; only
        # the ledger knows. Re-spawning here is the one thing we must not do.
        sys.stderr.write(
            f"harness: control socket {path} closed before answering — the verb "
            f"may have run. The ledger is the record: check `harness runs` / "
            f"`harness events` before retrying.\n"
        )
        return 1

    try:
        response = protocol.decode_response(raw)
    except protocol.BadRequest as exc:
        sys.stderr.write(
            f"harness: unintelligible response from {path} ({exc}) — the verb "
            f"may have run. The ledger is the record.\n"
        )
        return 1

    if not response.ok:
        sys.stderr.write(f"harness: {response.reason.value if response.reason else '?'}: "
                         f"{response.error}\n")
    return protocol.exit_code_for(response)


def _connect(path: Path) -> socket.socket | None:
    """Connect to the control socket, or ``None`` if it is unreachable.

    Every way it can be unreachable collapses to one answer — absent, a stale
    file nothing listens on, a plain file at that path, or permission denied.
    Distinguishing them would only change the wording of a message whose action
    is identical in all four cases.
    """
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        conn.connect(str(path))
    except OSError:
        conn.close()
        return None
    return conn


def _read_response(conn: socket.socket) -> bytes:
    """Read until the server closes. The verb runs first, so this blocks for its
    whole duration — deliberately unbounded: a ``review`` legitimately takes
    twelve minutes, and a timeout here would abandon a live run."""
    chunks: list[bytes] = []
    while True:
        try:
            chunk = conn.recv(65536)
        except OSError:
            break
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def main(raw: list[str] | None = None) -> int:
    invocation = parse_argv(list(sys.argv[1:] if raw is None else raw))
    return run(repo=invocation.repo, argv=invocation.argv)


if __name__ == "__main__":  # pragma: no cover — exercised as a subprocess
    raise SystemExit(main())
