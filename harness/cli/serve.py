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

**The operation surface is derived, not listed** — the derivation itself lives
in :mod:`harness.cli.serve_surface`, extracted in #310.

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
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from harness.cli.serve_surface import operation_surface, resolve_verb
from harness.hostenv import broker as broker_module
from harness.hostenv import container_env, protocol, spawn
from harness.hostenv import host as host_module
from harness.maintenance import sweep as sweep_module
from harness.workspace import (
    WorkspaceNotAllowed,
    resolve_within_allowlist,
)

__all__ = ["VerbServer", "build_server", "operation_surface", "serve_command"]


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
        #
        # The container user is asked for here too (#380), for the same reason and
        # not for its value: a server running as root cannot be given a container
        # to run as root, and the refusal belongs where every other pre-spawn
        # refusal is — before docker is touched, on the wire, with a reason.
        try:
            detected = host_module.detect_host(platform=sys.platform)
            detected.workspace_mount(repo)
            detected.container_user()
        except (
            spawn.WorkspaceNotEquivalent,
            spawn.UnsafeRepoPath,
            spawn.UnsafeContainerUser,
        ) as exc:
            refuse(protocol.Reason.REPO_NOT_ALLOWED, str(exc))
            return
        except host_module.UnsupportedHost as exc:
            refuse(protocol.Reason.REPO_NOT_ALLOWED, str(exc))
            return

        # 3b. The host must be able to supply a usable agent credential (#309).
        #     Only a *brokered* source ever answers here — the default source
        #     is structurally incapable of refusing (CAL-941); why the brokered
        #     one inverts that is on `broker.BrokeredSource.refusal`. Placed
        #     before `rewrite_repo_argument` so no argv work happens for a
        #     request that cannot run, and — like every refusal above — before
        #     docker is touched.
        refusal = container_env.credential_refusal(detected, self.server.credentials)
        if refusal is not None:
            refuse(protocol.Reason.CREDENTIAL_UNAVAILABLE, refusal)
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
        credentials: container_env.AgentCredentialSource | None = None,
    ) -> None:
        self.socket_path = Path(socket_path)
        self.roots = list(roots)
        self.image = image
        self.env = dict(os.environ if env is None else env)

        #: Where each request's agent credential comes from (#309). Public, like
        #: `roots` / `image` / `log`, because the handler consults it. The
        #: default is the request-refreshing source — today's behaviour — so a
        #: server constructed directly is unchanged; `build_server` is what
        #: substitutes the broker.
        self.credentials: container_env.AgentCredentialSource = (
            credentials if credentials is not None else container_env.RequestRefreshingSource()
        )

        #: Per-repo mutex. AC-5: requests against one repo are serialized until
        #: parallel-writer behaviour against the ledger over a bind mount has
        #: been measured. Deliberately *per repo* rather than global — a
        #: ``status`` on one repo must not queue behind a twelve-minute
        #: ``review`` on another.
        #:
        #: **Reentrant** since #310, for one specific caller: the maintenance
        #: sweep holds this lock for a cycle and then calls `spawn`, which takes
        #: the same lock across its subprocess — a plain `Lock` is that thread
        #: deadlocking against itself, wedging with no error anywhere.
        #: Reentrancy is **per thread**, so the cross-thread serialization AC-5
        #: asserts is unchanged; the two overlap tests are its floor and
        #: `test_a_repo_lock_held_by_one_thread_is_refused_to_another` pins that
        #: the widening did not become a global "always acquire".
        self._repo_locks: dict[str, threading.RLock] = {}
        self._registry_lock = threading.Lock()

        #: One line per request — the socket's only audit trail. It grants
        #: operator-equivalent authority to anyone who can connect, so a request
        #: that left no record would be unattributable after the fact. Overridable
        #: so a host can route it somewhere durable; the default is stderr, where
        #: a foreground process's operator already is. Annotated as the callable
        #: type rather than left to inference: `build_server` substitutes a sink
        #: it shares with the credential broker, so the two write one stream.
        self.log: Callable[[str], None] = _log_to_stderr

        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.socket_path.parent, 0o700)
        # A socket left by a killed server is a path nothing listens on; the
        # client treats it as unreachable and falls back, so removing it here is
        # recovery, not a race.
        with contextlib.suppress(FileNotFoundError):
            self.socket_path.unlink()

        super().__init__(str(self.socket_path), _Handler)
        os.chmod(self.socket_path, 0o600)

    def _lock_for(self, repo: Path) -> threading.RLock:
        key = str(repo)
        with self._registry_lock:
            return self._repo_locks.setdefault(key, threading.RLock())

    @contextlib.contextmanager
    def try_repo_lock(self, repo: Path) -> Iterator[bool]:
        """Take this repo's lock if it is free, yielding whether it was taken.

        **Non-blocking, deliberately** (#310). The maintenance sweep runs one
        thread across every repo, so blocking on a twelve-minute ``review`` in
        repo A would delay repo B's sweep by that long, and per-repo isolation
        is what the lock exists to preserve. It also makes contention
        *observable* — a recorded ``skipped`` row rather than silent lateness —
        and real work always wins, so a sweep never makes a verb wait.
        """
        lock = self._lock_for(repo)
        acquired = lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                lock.release()

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
            resolved = container_env.resolve_container_env(
                repo, credentials=self.credentials
            )
        except host_module.UnsupportedHost as unsupported:
            _log_to_stderr(f"credential resolution failed: {unsupported}")
            return 2
        except container_env.CredentialRenewalFailed as unrenewed:
            # The same backstop the two provider refusals get below, for the
            # same reason: the handler refuses this earlier and on the wire, so
            # reaching it here means a caller went straight to `spawn`, where an
            # escaping exception would kill the request thread with no answer.
            _log_to_stderr(f"spawn refused: {unrenewed}")
            return 2
        except (spawn.WorkspaceNotEquivalent, spawn.UnsafeContainerUser) as refused:
            # The provider refuses this request (#308, #380) — a Windows-filesystem
            # path under WSL, or a uid the container must not take. Refused here
            # for the same reason an unsupported host is: nothing is spawned, and
            # the message names the remedy. The handler refuses both earlier, on
            # the wire; this is the backstop for a caller reaching `spawn`
            # directly, where an escaping exception would kill the request thread
            # with no answer at all.
            _log_to_stderr(f"spawn refused: {refused}")
            return 2

        docker_argv = spawn.build_docker_argv(
            repo=repo,
            argv=argv,
            image=self.image,
            env_names=_forwarded_env_names(),
            home=Path(self.env.get("HOME", str(Path.home()))),
            ssh_agent=resolved.ssh_agent,
            mount=resolved.workspace_mount,
            container_user=resolved.container_user,
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


def build_server(
    *,
    socket_path: Path,
    roots: list[Path],
    image: str,
    log: Callable[[str], None] = _log_to_stderr,
    host: host_module.HostPlatform | None = None,
) -> tuple[
    VerbServer, broker_module.CredentialBroker | None, sweep_module.MaintenanceScheduler
]:
    """The production constructor: a server, the broker feeding it, and the sweeper.

    Priming happens **synchronously, before the socket serves**, so no request
    ever observes an unknown credential state and the first request cannot
    trigger a renewal. The renewal thread is started by the caller — ``serve``
    does it once the listener is announced — because a thread started here would
    outlive a caller that only wanted a server.

    A host that cannot be detected is **not** a new way for ``serve`` to fail.
    It falls back to the request-refreshing source with no broker, so the socket
    still binds and each request refuses at the existing per-request site with
    the existing message: a degradation to yesterday's behaviour, not an outage.

    The broker and the request audit trail share one ``log`` sink, so an
    operator watching ``serve`` sees renewal failures in the same stream as the
    refusals they explain.

    The maintenance scheduler (#310) is built on **both** paths, including the
    undetectable-host fallback: sweeping needs no agent credential, so a host
    that cannot broker one must still reclaim its stale runs. Like the broker's,
    its thread is started by the caller, not here — a thread started in a
    constructor would outlive a caller that only wanted a server.
    """
    detected = host
    if detected is None:
        try:
            detected = host_module.detect_host(platform=sys.platform)
        except host_module.UnsupportedHost as unsupported:
            log(
                f"harness serve: {unsupported} Credentials will be resolved per "
                f"request instead of brokered."
            )
            fallback = VerbServer(socket_path=socket_path, roots=roots, image=image)
            fallback.log = log
            return fallback, None, _sweeper(fallback, roots, log)

    broker = broker_module.CredentialBroker(detected, log=log)
    record = broker.prime()
    if record.outcome is broker_module.RenewalOutcome.ABSENT:
        log(
            "harness serve: no agent credential in the host store; verbs will "
            "run without one."
        )

    server = VerbServer(
        socket_path=socket_path,
        roots=roots,
        image=image,
        credentials=broker.source,
    )
    server.log = log
    return server, broker, _sweeper(server, roots, log)


def _sweeper(
    server: VerbServer, roots: list[Path], log: Callable[[str], None]
) -> sweep_module.MaintenanceScheduler:
    """The sweeper for this server, over the roots the server itself serves.

    One repo list, not two: the allowlist is where a repo becomes reachable at
    all, so deriving the swept set from anywhere else would let the timer touch
    a path a request cannot.
    """
    return sweep_module.MaintenanceScheduler(server=server, roots=roots, log=log)


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

    server, broker, sweeper = build_server(socket_path=path, roots=roots, image=image)
    typer.echo(f"harness serve: listening on {path}", err=True)
    if broker is not None:
        broker.start()
    # After the listener is announced, like the broker: the socket is what the
    # operator started this for, and a sweep must never sit in front of it.
    sweeper.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover — operator ^C
        typer.echo("harness serve: shutting down", err=True)
    finally:
        if broker is not None:
            broker.stop()
        sweeper.stop()
        server.server_close()
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
    sys.exit(0)
