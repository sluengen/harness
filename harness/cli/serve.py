"""``harness serve`` — the persistent runtime host (#307, ADR 0012).

A long-lived host-side process exposing the verb surface over a local unix
socket. It spawns each verb as a **one-shot container** and holds **no run
state**. Those two properties are the whole of ADR 0012's carve-out against
SPEC §16's "no long-running daemon" non-goal:

    It is a credential broker, a spawner, and a scheduler — nothing that
    outlives a request describes a run. […] if the host process ever holds run
    state, it has exceeded the carve-out.

The reason that constraint is load-bearing rather than stylistic: the close gate
rests on the ledger being the only memory of a run, so a verb that dies mid-flight
leaves no half-state anywhere. A host process caching run status would break that
property *while appearing to work*.

**Why a spawner and not a proxied docker socket.** The docker socket is
root-equivalent on the host — anything reaching it can ``docker run -v /:/host``.
Here the caller names a verb and a repo; the host chooses the image, the mount,
the privilege and the env. The construction itself lives in
:mod:`harness.hostenv.spawn`, shared with the client's fallback so the two paths
cannot drift.

**The operation surface is derived, not listed.** The retired launcher's
hardcoded ``OPERATIONS`` frozenset went stale as soon as a verb was added, and
six have been added since. Deriving it from the registered Typer app makes that
drift structurally impossible; #311's guard is then a floor rather than the
mechanism.

**Supervision is deliberately absent** (#307 Design). ``harness serve`` is a
foreground process an operator starts. Client-side autostart was rejected: a verb
call would spawn a long-lived credential broker as a side effect, inheriting that
call's environment and tty into a process outliving it, and it makes an outage
invisible — which is exactly what ADR 0012 warns against. The client's fallback
notice is the visibility mechanism instead. A launchd/systemd unit belongs to the
deployment ticket (#312).
"""

from __future__ import annotations

import contextlib
import os
import socket
import socketserver
import subprocess
import sys
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from harness.hostenv import container_env, host, protocol, spawn
from harness.workspace import (
    WorkspaceNotAllowed,
    resolve_within_allowlist,
)

__all__ = ["VerbServer", "operation_surface", "serve_command"]


def _leaves(command: Any, prefix: str = "") -> Iterator[str]:
    """Every leaf invocation reachable from ``command``, space-joined.

    Recurses through groups, so ``promote start`` and ``worktrees cleanup`` are
    enumerated as leaves rather than collapsed into their group name. A
    recursion that stopped at the top level would refuse every subcommand at
    runtime while looking correct in a smoke test.
    """
    commands = getattr(command, "commands", None)
    if commands:
        for name, child in commands.items():
            yield from _leaves(child, prefix=f"{prefix}{name} ")
    else:
        name = prefix.strip()
        if name:
            yield name


def operation_surface() -> set[str]:
    """The set of verb invocations this socket will accept.

    Derived from the registered Typer app on every call rather than cached: the
    app is fixed at import, and re-deriving costs a tree walk over a few dozen
    commands while removing any question of a stale snapshot.

    Imported inside the function body per the layering rule — ``harness.cli``
    must not be imported at module scope by anything the host runs early.
    """
    import typer as _typer

    from harness.cli import app

    return set(_leaves(_typer.main.get_command(app)))


def resolve_verb(argv: list[str], surface: set[str]) -> str | None:
    """The registered invocation ``argv`` names, by longest prefix, or ``None``.

    Longest-prefix first so ``worktrees cleanup`` resolves as itself rather than
    as the group ``worktrees`` with a stray argument.
    """
    for length in (2, 1):
        candidate = " ".join(argv[:length])
        if candidate in surface:
            return candidate
    return None


class _Handler(socketserver.BaseRequestHandler):
    """One request per connection: receive, validate, spawn, answer."""

    server: VerbServer

    def handle(self) -> None:
        conn: socket.socket = self.request
        try:
            payload, fds, _flags, _addr = socket.recv_fds(
                conn, protocol.MAX_REQUEST_BYTES, 3
            )
        except OSError:
            return

        try:
            self._dispatch(conn, payload, fds)
        finally:
            for fd in fds:
                with contextlib.suppress(OSError):
                    os.close(fd)

    def _dispatch(self, conn: socket.socket, payload: bytes, fds: list[int]) -> None:
        # The verb and the repo are resolved progressively, so the log line is
        # built from whatever is known when the outcome is reached — a request
        # refused at the schema has no verb to name, and saying so is the honest
        # record.
        state: dict[str, str] = {"verb": "?", "repo": "?"}

        def record(outcome: str) -> None:
            # Deliberately NOT the argv: only the resolved verb. A ticket title,
            # a `--reason` body, or a token-shaped argument must not be able to
            # land in a log the operator may paste elsewhere.
            self.server.log(
                f"{_utc_now()} verb={state['verb']} repo={state['repo']} {outcome}"
            )

        def answer(frame: str) -> None:
            with contextlib.suppress(OSError):
                conn.sendall(frame.encode())

        def refuse(reason: protocol.Reason, message: str) -> None:
            record(f"refused={reason.value}")
            answer(protocol.encode_refusal(reason, message))

        # 1. Schema. Refusing an unknown key is what makes a mount, an image, a
        #    privilege or an env inexpressible rather than merely ignored.
        try:
            request = protocol.decode_request(payload)
        except protocol.BadRequest as exc:
            refuse(protocol.Reason.BAD_REQUEST, str(exc))
            return

        # 2. The verb must be one the CLI actually registers.
        state["repo"] = str(request.repo)
        verb = resolve_verb(request.argv, operation_surface())
        if verb is None:
            refuse(
                protocol.Reason.UNKNOWN_VERB,
                f"{' '.join(request.argv[:2]) or '(empty)'} is not a harness verb",
            )
            return
        state["verb"] = verb

        # 3. The repo must be inside the allowlist, and expressible as a mount.
        try:
            repo = resolve_within_allowlist(request.repo, self.server.roots)
        except WorkspaceNotAllowed as exc:
            refuse(protocol.Reason.REPO_NOT_ALLOWED, str(exc))
            return
        state["repo"] = str(repo)
        # The provider decides whether this repo can be mounted *equivalently*
        # (#308) — under WSL a Windows-filesystem path cannot — and the mount
        # object owns the ``:`` refusal that was hand-inlined here. One home, and
        # both land before docker is touched.
        try:
            host.detect_host(platform=sys.platform).workspace_mount(repo)
        except (spawn.WorkspaceNotEquivalent, spawn.UnsafeRepoPath) as exc:
            refuse(protocol.Reason.REPO_NOT_ALLOWED, str(exc))
            return
        except host.UnsupportedHost as exc:
            refuse(protocol.Reason.REPO_NOT_ALLOWED, str(exc))
            return

        # 4. An explicit --repo in argv must name the repo actually being mounted.
        try:
            argv = spawn.rewrite_repo_argument(request.argv, repo)
        except (spawn.RepoMismatch, spawn.UnsafeRepoPath) as exc:
            refuse(protocol.Reason.REPO_MISMATCH, str(exc))
            return

        # Only now is docker touched. Every refusal above spawned nothing.
        try:
            exit_code = self.server.spawn(repo=repo, argv=argv, fds=fds)
        except OSError as exc:
            refuse(protocol.Reason.SPAWN_FAILED, str(exc))
            return

        record(f"exit={exit_code}")
        answer(protocol.encode_success(exit_code=exit_code))


class VerbServer(socketserver.ThreadingUnixStreamServer):
    """The control socket. Threaded, so one repo's long verb does not block another.

    Its entire mutable state after a request is :attr:`_repo_locks` — a mutex per
    resolved repo path. That is host configuration, not run state: it names no
    run, ticket, verb or argv, and an empty registry after a restart is a correct
    one. AC-2 asserts exactly that.
    """

    daemon_threads = True
    allow_reuse_address = True

    #: Explicitly off, and it is not merely a tidy-up. Left at its default,
    #: ``socketserver`` lazily installs a ``_threads`` list on the instance at
    #: the first request — state created by a request, which is what AC-2
    #: forbids — and makes shutdown *wait* for in-flight handlers. Waiting is
    #: also wrong here: a verb's container is owned by the docker daemon and runs
    #: to completion whether or not this process is alive (the ledger is the only
    #: record), so blocking close on a twelve-minute ``review`` buys nothing.
    block_on_close = False

    def __init__(
        self,
        *,
        socket_path: Path,
        roots: list[Path],
        image: str,
        env: dict[str, str] | None = None,
    ) -> None:
        self.socket_path = Path(socket_path)
        self.roots = list(roots)
        self.image = image
        self.env = dict(os.environ if env is None else env)

        #: Per-repo mutex. AC-5: requests against one repo are serialized until
        #: parallel-writer behaviour against the ledger over a bind mount has
        #: been measured. Deliberately *per repo* rather than global — a
        #: ``status`` on one repo must not queue behind a twelve-minute
        #: ``review`` on another.
        self._repo_locks: dict[str, threading.Lock] = {}
        self._registry_lock = threading.Lock()

        #: One line per request — the socket's only audit trail. It grants
        #: operator-equivalent authority to anyone who can connect, so a request
        #: that left no record would be unattributable after the fact. Overridable
        #: so a host can route it somewhere durable; the default is stderr, where
        #: a foreground process's operator already is.
        self.log = _log_to_stderr

        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.socket_path.parent, 0o700)
        # A socket left by a killed server is a path nothing listens on; the
        # client treats it as unreachable and falls back, so removing it here is
        # recovery, not a race.
        with contextlib.suppress(FileNotFoundError):
            self.socket_path.unlink()

        super().__init__(str(self.socket_path), _Handler)
        os.chmod(self.socket_path, 0o600)

    def _lock_for(self, repo: Path) -> threading.Lock:
        key = str(repo)
        with self._registry_lock:
            return self._repo_locks.setdefault(key, threading.Lock())

    def spawn(self, *, repo: Path, argv: list[str], fds: list[int]) -> int:
        """Run one verb container against the caller's own file descriptors.

        The container writes straight to the caller's stdout/stderr, so a long
        ``review`` streams live and no run output is ever buffered here — which
        would be run-describing state.
        """
        # Per request, never at bind time. This process is designed to outlive many
        # verbs, so bind time is the one moment whose credentials are guaranteed to
        # be stale later — and the repo it resolves `.env` against is the one *this
        # request* named, not the shell's cwd. Nothing resolved here is retained:
        # `resolved` dies with the call, which is what keeps ADR 0012's "no run
        # state" true of credentials too.
        try:
            resolved = container_env.resolve_container_env(repo)
        except host.UnsupportedHost as unsupported:
            _log_to_stderr(f"credential resolution failed: {unsupported}")
            return 2
        except spawn.WorkspaceNotEquivalent as not_equivalent:
            # The provider refuses this repo (#308) — a Windows-filesystem path
            # under WSL, today. Refused here for the same reason an unsupported
            # host is: nothing is spawned, and the message names the remedy.
            _log_to_stderr(f"workspace refused: {not_equivalent}")
            return 2

        docker_argv = spawn.build_docker_argv(
            repo=repo,
            argv=argv,
            image=self.image,
            env_names=_forwarded_env_names(),
            home=Path(self.env.get("HOME", str(Path.home()))),
            ssh_agent=resolved.ssh_agent,
            mount=resolved.workspace_mount,
            git_identity=resolved.git_identity,
        )
        stdin, stdout, stderr = (fds + [0, 1, 2])[:3]

        with self._lock_for(repo):
            completed = subprocess.run(  # noqa: S603 — argv is host-constructed
                docker_argv,
                env={**os.environ, **self.env, **resolved.values},
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                check=False,
            )
        return completed.returncode


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _log_to_stderr(line: str) -> None:
    sys.stderr.write(f"{line}\n")
    sys.stderr.flush()


def _forwarded_env_names() -> tuple[str, ...]:
    from harness.hostenv.client import FORWARDED_ENV_NAMES

    return FORWARDED_ENV_NAMES


def serve_command(
    socket_path: Annotated[
        Path | None,
        typer.Option("--socket", help="Control socket path (default: per protocol)."),
    ] = None,
    image: Annotated[
        str, typer.Option("--image", help="Verb container image.")
    ] = "harness:dev",
) -> None:
    """Run the persistent runtime host in the foreground.

    Foreground by design: "not running" is then an operator-visible fact rather
    than a silent condition. The client falls back to a direct spawn and says so
    on stderr, so an outage degrades performance, never availability.
    """
    from harness.workspace import allowed_roots

    path = Path(socket_path) if socket_path else protocol.socket_path()
    roots = allowed_roots()
    if not roots:
        typer.echo(
            "harness serve: HARNESS_WORKSPACE_ROOTS is unset — every request "
            "will be refused (fail-closed). Set it to the roots this host serves.",
            err=True,
        )

    server = VerbServer(socket_path=path, roots=roots, image=image)
    typer.echo(f"harness serve: listening on {path}", err=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover — operator ^C
        typer.echo("harness serve: shutting down", err=True)
    finally:
        server.server_close()
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
    sys.exit(0)
