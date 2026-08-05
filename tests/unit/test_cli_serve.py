"""``harness serve`` — the persistent host process (#307, ADR 0012).

Three properties are asserted here, each traced to the decision that requires it:

* **The operation surface is derived, never listed** (ticket Design, *Operation
  surface*). The prior launcher's hardcoded ``OPERATIONS`` frozenset went stale
  within two tickets and is six verbs behind today. Deriving it from the
  registered Typer app makes that drift structurally impossible, which is what
  demotes #311's guard from *the mechanism* to *a floor*.
* **Validation happens before docker is ever invoked** (AC-4). The socket is the
  new security boundary: anyone who can ``connect()`` runs verbs with the host's
  credentials. Every refusal must therefore be observable as *no container was
  spawned*, not merely as a non-zero exit.
* **The server holds no run state** (AC-2). ADR 0012: "if the host process ever
  holds run state, it has exceeded the carve-out." The close gate rests on the
  ledger being the only memory of a run.

Docker is a stub script on ``PATH`` that records its argv and timing, so every
assertion is hermetic. The real thing is exercised by the docker-marked
integration tests.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from harness.cli import serve
from harness.hostenv import protocol


@pytest.fixture
def stub_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A ``docker`` that records ``start,end`` timestamps and its argv."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    record = tmp_path / "spawns.log"
    stub = bindir / "docker"
    # One atomic append *after* the sleep, not a start line and an end line:
    # concurrent invocations are the point of the AC-5 tests, and two separate
    # appends interleave into unparseable lines.
    stub.write_text(
        "#!/bin/sh\n"
        'started="$(date +%s.%N)"\n'
        f'sleep "${{HARNESS_STUB_SLEEP:-0}}"\n'
        f'printf "%s|%s|%s\\n" "$started" "$*" "$(date +%s.%N)" >> "{record}"\n'
        "exit 0\n"
    )
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return record


def _spawns(record: Path) -> list[tuple[float, str, float]]:
    if not record.exists():
        return []
    out = []
    for line in record.read_text().splitlines():
        start, argv, end = line.split("|")
        out.append((float(start), argv, float(end)))
    return out


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    (path / ".git").mkdir(parents=True)
    return path


@pytest.fixture
def other_repo(tmp_path: Path) -> Path:
    path = tmp_path / "other"
    (path / ".git").mkdir(parents=True)
    return path


@pytest.fixture
def running_server(tmp_path: Path, stub_docker: Path) -> Iterator[serve.VerbServer]:
    """A real ``VerbServer`` on a short-enough AF_UNIX path, in a thread.

    Depends on ``stub_docker`` so the stubbed ``PATH`` is in place *before* the
    server captures its environment — the server passes that env to every
    container it spawns, so capturing it first would run the real docker.
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="hs", dir="/tmp"))
    server = serve.VerbServer(
        socket_path=tmpdir / "c.sock",
        roots=[tmp_path.resolve()],
        image="harness:dev",
        env=dict(os.environ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        shutil.rmtree(tmpdir, ignore_errors=True)


def _request(server: serve.VerbServer, payload: str) -> protocol.Response:
    """Send a raw payload and read the response, passing three real fds."""
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.connect(str(server.socket_path))
    devnull = os.open(os.devnull, os.O_RDWR)
    try:
        socket.send_fds(conn, [payload.encode()], [devnull, devnull, devnull])
        chunks = []
        while chunk := conn.recv(65536):
            chunks.append(chunk)
        return protocol.decode_response(b"".join(chunks))
    finally:
        os.close(devnull)
        conn.close()


def _verb(server: serve.VerbServer, repo: Path, argv: list[str]) -> protocol.Response:
    return _request(server, protocol.encode_request(repo=repo, argv=argv))


# ---------------------------------------------------------------------------
# The derived operation surface
# ---------------------------------------------------------------------------


def test_the_derived_surface_is_non_empty_and_reads_the_registered_app() -> None:
    """Non-vacuity floor: an empty surface would refuse everything, and every
    ``unknown_verb`` assertion below would pass for the wrong reason."""
    surface = serve.operation_surface()

    assert len(surface) > 10, f"implausibly small derived surface: {sorted(surface)}"
    assert {"start", "review", "close", "design"} <= surface


def test_the_surface_enumerates_subcommands_not_just_their_group() -> None:
    """The anti-vacuity case that matters: a recursion stopping at the top level
    would still satisfy every assertion above, then refuse ``promote start`` in
    production."""
    surface = serve.operation_surface()

    assert "promote start" in surface
    assert "worktrees cleanup" in surface


def test_the_surface_is_derived_rather_than_listed() -> None:
    """Every leaf of the registered app is reachable — the property a hardcoded
    list cannot keep. Derived here from the app itself, so a verb added later is
    covered without editing this test."""
    import typer

    from harness.cli import app

    def leaves(command: object, prefix: str = "") -> Iterator[str]:
        commands = getattr(command, "commands", None)
        if commands:
            for name, child in commands.items():
                yield from leaves(child, f"{prefix}{name} ")
        else:
            yield prefix.strip()

    expected = {name for name in leaves(typer.main.get_command(app)) if name}

    assert serve.operation_surface() == expected


@pytest.mark.parametrize("argv", [["run"], ["exec", "sh"], ["build"], ["nonesuch"]])
def test_an_unregistered_operation_is_refused_before_docker(
    running_server: serve.VerbServer, repo: Path, stub_docker: Path, argv: list[str]
) -> None:
    """There is no ``run`` / ``exec`` / ``build`` escape hatch on this socket."""
    response = _verb(running_server, repo, argv)

    assert response.reason == protocol.Reason.UNKNOWN_VERB
    assert _spawns(stub_docker) == [], "an unknown verb reached docker"


def test_a_registered_verb_is_accepted_and_spawned(
    running_server: serve.VerbServer, repo: Path, stub_docker: Path
) -> None:
    response = _verb(running_server, repo, ["status", "R1"])

    assert response.ok, f"refused: {response.reason} {response.error}"
    assert len(_spawns(stub_docker)) == 1
    assert "status R1" in _spawns(stub_docker)[0][1]


def test_a_two_token_verb_resolves_by_longest_prefix(
    running_server: serve.VerbServer, repo: Path, stub_docker: Path
) -> None:
    response = _verb(running_server, repo, ["worktrees", "cleanup", "--merged"])

    assert response.ok, f"refused: {response.reason} {response.error}"
    assert "worktrees cleanup --merged" in _spawns(stub_docker)[0][1]


# ---------------------------------------------------------------------------
# AC-4 — the caller cannot choose a mount, image, privilege or env.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key, value",
    [
        ("image", "evil:latest"),
        ("volumes", "/:/host"),
        ("privileged", True),
        ("env", {"AWS_SECRET_ACCESS_KEY": "x"}),
    ],
)
def test_a_request_naming_a_docker_capability_is_refused(
    running_server: serve.VerbServer,
    repo: Path,
    stub_docker: Path,
    key: str,
    value: object,
) -> None:
    raw = json.dumps(
        {"protocol": 1, "repo": str(repo), "argv": ["status"], key: value}
    )

    response = _request(running_server, raw)

    assert response.reason == protocol.Reason.BAD_REQUEST
    assert _spawns(stub_docker) == []


def test_a_hostile_verb_argument_stays_a_verb_argument(
    running_server: serve.VerbServer, repo: Path, stub_docker: Path
) -> None:
    """``--privileged`` in argv reaches the container as an argument to the verb."""
    _verb(running_server, repo, ["start", "--privileged"])

    argv = _spawns(stub_docker)[0][1]
    assert argv.index("harness:dev") < argv.index("--privileged")


def test_a_repo_outside_the_allowlist_is_refused(
    running_server: serve.VerbServer, stub_docker: Path
) -> None:
    response = _verb(running_server, Path("/etc"), ["status"])

    assert response.reason == protocol.Reason.REPO_NOT_ALLOWED
    assert _spawns(stub_docker) == []


def test_a_repo_argument_naming_another_repo_is_refused(
    running_server: serve.VerbServer, repo: Path, other_repo: Path, stub_docker: Path
) -> None:
    response = _verb(running_server, repo, ["review", "--repo", str(other_repo)])

    assert response.reason == protocol.Reason.REPO_MISMATCH
    assert _spawns(stub_docker) == []


def test_a_matching_repo_argument_is_translated_to_the_mount(
    running_server: serve.VerbServer, repo: Path, stub_docker: Path
) -> None:
    response = _verb(running_server, repo, ["review", "--repo", str(repo)])

    assert response.ok
    assert "--repo /workspace" in _spawns(stub_docker)[0][1]


# ---------------------------------------------------------------------------
# AC-2 — the host process holds no run state.
# ---------------------------------------------------------------------------


def test_no_run_describing_state_survives_a_request(
    running_server: serve.VerbServer, repo: Path, other_repo: Path, stub_docker: Path
) -> None:
    """ADR 0012's carve-out, asserted as a before/after comparison.

    The claim is not "the server has no attributes" — it legitimately holds host
    configuration fixed at bind time (roots, image, the environment it spawns
    with). It is that **nothing a request touches outlives it**. So the whole of
    ``vars()`` is snapshotted before and compared after, which catches a cache
    added later without this test needing to know its name.

    ``_repo_locks`` is compared separately below: it is the one structure that
    legitimately grows, and it grows by *repo path*, never by run.

    The sentinels are synthetic. The obvious choice — a real run id — appears in
    this process's own PATH and PWD, because a run's worktree is named after it.
    """
    before = {
        name: repr(value)
        for name, value in vars(running_server).items()
        if name != "_repo_locks"
    }

    _verb(running_server, repo, ["start", "TICKETSENTINEL"])
    _verb(running_server, repo, ["review", "--run-id", "RUNIDSENTINEL"])
    _verb(running_server, other_repo, ["close", "TICKETSENTINEL"])

    after = {
        name: repr(value)
        for name, value in vars(running_server).items()
        if name != "_repo_locks"
    }

    assert after == before, (
        "the server's state changed across requests — anything a request leaves "
        "behind is run-describing state, which ADR 0012's carve-out forbids"
    )

    rendered = repr(vars(running_server))
    for sentinel in ("TICKETSENTINEL", "RUNIDSENTINEL"):
        assert sentinel not in rendered, (
            f"the server retained {sentinel!r} after the request completed"
        )


def test_the_only_per_repo_state_is_a_lock_registry(
    running_server: serve.VerbServer, repo: Path, other_repo: Path, stub_docker: Path
) -> None:
    """The one thing that legitimately accumulates: a mutex per repo path.

    It names no run, ticket, verb or argv, and an empty registry after a restart
    is a correct one.
    """
    _verb(running_server, repo, ["status"])
    _verb(running_server, other_repo, ["status"])

    keys = set(running_server._repo_locks)

    assert keys == {str(repo.resolve()), str(other_repo.resolve())}


def test_the_state_assertion_would_catch_a_planted_cache(
    running_server: serve.VerbServer, repo: Path, stub_docker: Path
) -> None:
    """Non-vacuity floor for AC-2: the check must fail on state that *is* there.

    Without this, a ``vars()`` that silently returned nothing would make the
    assertion above pass for every possible server.
    """
    running_server._planted = {"run_id": "RUNIDSENTINEL"}  # type: ignore[attr-defined]

    rendered = repr(vars(running_server))

    assert "RUNIDSENTINEL" in rendered, (
        "vars() does not observe the server's mutable state, so the AC-2 "
        "assertion above proves nothing"
    )
    del running_server._planted  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC-5 — requests against one repo are serialized until concurrency is measured.
# ---------------------------------------------------------------------------


def _concurrent(server: serve.VerbServer, targets: list[Path]) -> list[tuple[float, float]]:
    threads = [
        threading.Thread(target=lambda t=target: _verb(server, t, ["status"]))
        for target in targets
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return []


def test_requests_against_one_repo_do_not_overlap(
    running_server: serve.VerbServer,
    repo: Path,
    stub_docker: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-5's serialization, measured from the stub's own start/end timestamps."""
    monkeypatch.setenv("HARNESS_STUB_SLEEP", "0.15")
    running_server.env["HARNESS_STUB_SLEEP"] = "0.15"

    _concurrent(running_server, [repo] * 4)

    intervals = sorted((s, e) for s, _, e in _spawns(stub_docker))
    assert len(intervals) == 4, f"expected 4 spawns, got {len(intervals)}"
    for (_, end), (start, _) in zip(intervals, intervals[1:], strict=False):
        assert start >= end - 0.01, (
            f"two containers for the same repo overlapped ({start} < {end}) — "
            f"the per-repo lock is not held across the spawn"
        )


def test_requests_against_different_repos_do_overlap(
    running_server: serve.VerbServer,
    repo: Path,
    other_repo: Path,
    stub_docker: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The non-vacuity mirror of the test above.

    Without it, a server that simply never ran anything concurrently — a single
    global lock, or a serial accept loop — would satisfy the serialization
    assertion while making a ``status`` on one repo wait behind a twelve-minute
    ``review`` on another.
    """
    running_server.env["HARNESS_STUB_SLEEP"] = "0.3"

    _concurrent(running_server, [repo, other_repo])

    intervals = sorted((s, e) for s, _, e in _spawns(stub_docker))
    assert len(intervals) == 2
    (first_start, first_end), (second_start, _) = intervals
    assert second_start < first_end, (
        "two different repos were serialized against each other — the lock is "
        "global rather than per-repo"
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_serve_is_registered_on_the_cli() -> None:
    from harness.cli import app
    from tests._cliutil import registered_command_surface

    assert "serve" in registered_command_surface(app)


# ---------------------------------------------------------------------------
# The audit log (#307 design, Security; added after review cycle 1)
# ---------------------------------------------------------------------------


def test_each_request_is_logged_with_its_verb_repo_and_exit_code(
    running_server: serve.VerbServer, repo: Path, stub_docker: Path
) -> None:
    """The socket grants operator-equivalent authority and has no other audit
    trail, so one line per request is the whole of it."""
    records: list[str] = []
    running_server.log = records.append  # type: ignore[method-assign]

    _verb(running_server, repo, ["start", "307"])

    assert len(records) == 1, f"expected one log line, got {records}"
    line = records[0]
    assert "start" in line
    assert str(repo.resolve()) in line
    assert "exit=0" in line


def test_a_refused_request_is_logged_with_its_reason(
    running_server: serve.VerbServer, repo: Path, stub_docker: Path
) -> None:
    """A refusal is the security-interesting event, so it must not be the one
    thing that goes unrecorded."""
    records: list[str] = []
    running_server.log = records.append  # type: ignore[method-assign]

    _verb(running_server, repo, ["exec", "sh"])

    assert len(records) == 1
    assert "unknown_verb" in records[0]


def test_the_log_never_carries_argv_beyond_the_verb(
    running_server: serve.VerbServer, repo: Path, stub_docker: Path
) -> None:
    """A ticket title, a `--reason` body or a token-shaped argument must not be
    able to land in a log file the operator may paste elsewhere.

    The verb itself is logged; nothing after it is. Asserted with a sentinel that
    could only arrive via argv.
    """
    records: list[str] = []
    running_server.log = records.append  # type: ignore[method-assign]

    _verb(
        running_server,
        repo,
        ["defer", "307", "--reason", "SECRETSENTINEL-do-not-log"],
    )

    assert records, "nothing was logged, so the ban below is vacuous"
    assert "defer" in records[0], "the verb itself must be logged"
    assert "SECRETSENTINEL" not in records[0], (
        f"an argv value reached the audit log: {records[0]!r}"
    )
