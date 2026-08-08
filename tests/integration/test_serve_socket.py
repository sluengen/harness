"""``harness serve`` end-to-end over a real socket and real containers (#307).

The unit tests stub ``docker`` and assert the *argv* each path constructs. That
is the right level for the security properties, but it cannot answer AC-1, which
is a claim about **bytes on stdout**:

    AC-1: A verb requested over the socket produces stdout byte-identical to the
    same verb invoked directly, asserted for at least one read verb and one
    mutating verb.

"The same verb invoked directly" is not a hypothetical: it is the client's own
direct-spawn fallback, which is what ``~/bin/harness`` does today. So each verb
runs twice — once through the socket, once with the socket unreachable — and the
results are compared. A difference would mean the socket path is transforming
the JSON contract the orchestrating loop parses.

The two halves are compared differently, and deliberately so. A **read** verb
(``version``) is deterministic, so its stdout is compared byte for byte, which
is AC-1 read literally. A **mutating** verb (``start``, in a ``tracker: none``
fixture repo so it needs no network) emits a fresh ULID run id and two fields
derived from it, so byte-identity is *impossible* rather than merely unlikely —
asserting it would produce a test that had to be weakened until it meant
nothing. Its comparison is exact over every field of the contract and exempts
the three per-run ones by name, with a floor asserting those three still exist
so a stale exemption cannot silently excuse nothing.

Marked ``docker`` and skipped without a daemon, like ``test_docker.py``.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from harness.cli import serve
from harness.hostenv import client
from tests._capture import Capture

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_TAG = "harness:test"


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=15, check=False
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker,
    # Keep the global 120s cap — it exists to kill a *hung* test, and these six
    # take ~25s each — but measure it over the test body alone. Setup here is a
    # cold `docker build`, which is long by design rather than hung: it measured
    # 165s cold (CAL-1110), so under a cap covering setup the whole module ERRORs
    # on every cold cache and passes on every warm one (#357). The build gets its
    # own budget below instead; `tests/unit/test_timeout_budgets_coherent.py`
    # pins that the two stay distinct and correctly ordered.
    #
    # Deliberately NOT test_docker.py's fix. That module raises its whole cap to
    # 600s, which it can afford because its tests *are* the build; doing that
    # here would give a genuinely hung socket test ten minutes to burn.
    pytest.mark.timeout(func_only=True),
    pytest.mark.skipif(not _docker_available(), reason="docker daemon unavailable"),
]


@pytest.fixture(scope="module")
def image() -> str:
    """The verb image, built from this checkout under a test-only tag.

    ``harness:test``, never ``harness:dev``: a stray rebuild of the live tag
    could break an in-flight verb loop on a developer's host.
    """
    subprocess.run(
        ["docker", "build", "-f", "docker/Dockerfile", "-t", IMAGE_TAG, "."],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        # The build's own budget, and — with the pytest cap deferred to the test
        # body above — the only thing bounding it short of the CI job's wall
        # clock. 600s matches test_docker.py's identical build of the same
        # Dockerfile: ~3.6x the 165s cold measurement, leaving room for a CI
        # runner slower than the author's machine.
        timeout=600,
    )
    return IMAGE_TAG


#: The fixture's integration branch, written into its ``CONTEXT.md`` *and*
#: created by its ``git init`` — one constant, because the two drifting apart is
#: precisely the defect (#369). The fixture used to declare ``integration: main``
#: and then let ``git init`` take whatever the host's ``init.defaultBranch``
#: said. On a host defaulting to ``main`` it agreed with itself by luck; on the
#: CI runner it did not, and ``start`` — which resolves its base through
#: ``resolve_base_branch`` — got ``fatal: invalid reference: main``. That kept CI
#: red on every push to ``dev`` for two days while the local gate stayed green.
_INTEGRATION_BRANCH = "main"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A ``tracker: none`` git repo, so verbs run with no network and no tracker."""
    repo = tmp_path / "ws"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", _INTEGRATION_BRANCH], cwd=repo, check=True
    )
    (repo / "CONTEXT.md").write_text(
        "```yaml\nrepo:\n  name: ws\ntracker: none\nbranches:\n"
        f"  integration: {_INTEGRATION_BRANCH}\n```\n"
    )
    (repo / "README.md").write_text("fixture\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=repo,
        check=True,
    )
    return repo


@pytest.fixture
def server(workspace: Path, image: str) -> Iterator[serve.VerbServer]:
    tmpdir = Path(tempfile.mkdtemp(prefix="hs", dir="/tmp"))
    instance = serve.VerbServer(
        socket_path=tmpdir / "c.sock",
        roots=[workspace.resolve().parent],
        image=image,
        env=dict(os.environ),
    )
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        instance.shutdown()
        shutil.rmtree(tmpdir, ignore_errors=True)


def _verb_json(
    *, repo: Path, argv: list[str], socket_at: Path, image: str
) -> dict:
    """Run a verb and parse its JSON stdout."""
    import json

    captured = _capture(repo=repo, argv=argv, socket_at=socket_at, image=image)
    assert captured.code == 0, captured.diagnosis(argv)
    return json.loads(captured.stdout.decode())


def _capture(*, repo: Path, argv: list[str], socket_at: Path, image: str) -> Capture:
    """Run one verb through :mod:`harness.hostenv.client`, capturing both streams.

    Real file descriptors, because the whole point of the socket path is that
    the container writes to the caller's own fd — a pipe here is what makes the
    two paths comparable at all.

    **Both** streams get one (#370). stderr went to ``/dev/null`` until then, and
    that is where every failure route out of a verb other than ``run_verb``'s
    ``--json`` path writes: a non-``VerbError`` traceback, a failure under
    ``entrypoint.sh``'s ``set -euo pipefail``, ``uv run``'s own diagnostics. All
    of them produce (non-zero exit, empty stdout), so a capture reading stdout
    alone reported the CI failure as ``b''`` — indistinguishable from a verb that
    genuinely said nothing, and unattributable for two days because of it. The
    real-fd construction is unchanged; there is simply a second one now.
    """
    out = Path(tempfile.mkstemp(dir="/tmp")[1])
    err = Path(tempfile.mkstemp(dir="/tmp")[1])
    out_fd = os.open(out, os.O_WRONLY | os.O_TRUNC)
    err_fd = os.open(err, os.O_WRONLY | os.O_TRUNC)
    devnull = os.open(os.devnull, os.O_RDWR)
    try:
        code = client.run(
            repo=repo,
            argv=argv,
            env={
                **os.environ,
                "HARNESS_CONTROL_SOCKET": str(socket_at),
                "HARNESS_IMAGE": image,
            },
            stdio=(devnull, out_fd, err_fd),
        )
    finally:
        os.close(out_fd)
        os.close(err_fd)
        os.close(devnull)
    captured = Capture(code=code, stdout=out.read_bytes(), stderr=err.read_bytes())
    out.unlink(missing_ok=True)
    err.unlink(missing_ok=True)
    return captured


# ---------------------------------------------------------------------------
# AC-1 — the socket does not alter the verb's stdout.
# ---------------------------------------------------------------------------


def test_a_read_verbs_stdout_is_identical_over_the_socket_and_directly(
    server: serve.VerbServer, workspace: Path, image: str
) -> None:
    over_socket = _capture(
        repo=workspace, argv=["version"], socket_at=server.socket_path, image=image
    )
    directly = _capture(
        repo=workspace,
        argv=["version"],
        socket_at=Path("/tmp/definitely-not-a-socket"),
        image=image,
    )

    assert over_socket.stdout, (
        "no stdout captured — the comparison would be vacuous.\n"
        f"{over_socket.diagnosis(['version'])}"
    )
    assert over_socket.contract == directly.contract, (
        "the socket path altered a read verb's stdout or exit code:\n"
        f"  socket: {over_socket.diagnosis(['version'])}\n"
        f"  direct: {directly.diagnosis(['version'])}"
    )


def test_a_mutating_verbs_contract_is_unaltered_by_the_socket(
    server: serve.VerbServer, workspace: Path, image: str
) -> None:
    """The mutating half of AC-1, stated in the only way that can be true.

    ``start`` mutates: it opens a ledger row and creates a worktree. Its stdout
    therefore carries a fresh ULID run id, an ``started_at``-derived worktree
    path, and a branch named after that id — so two invocations *cannot* be
    byte-identical, and a test asserting they are would either be deleted or
    quietly weakened into meaninglessness.

    What AC-1 is actually protecting is the JSON contract the orchestrating loop
    parses: that the transport adds no field, drops no field, and changes no
    value that is not inherently per-run. So the comparison is exact over every
    key, and exempts exactly three by name — each exempted because it embeds the
    run id, which is the one thing that must differ.
    """
    per_run = {"run_id", "worktree_path", "worktree_branch"}

    over_socket = _verb_json(
        repo=workspace, argv=["start", "1", "--json"],
        socket_at=server.socket_path, image=image,
    )
    directly = _verb_json(
        repo=workspace, argv=["start", "2", "--json"],
        socket_at=Path("/tmp/definitely-not-a-socket"), image=image,
    )

    assert over_socket.keys() == directly.keys(), (
        "the socket path added or dropped a top-level field of the JSON "
        f"contract:\n  socket: {sorted(over_socket)}\n  direct: {sorted(directly)}"
    )
    assert per_run <= over_socket.keys(), (
        f"the per-run exemptions name fields StartOutput does not have "
        f"({sorted(per_run - over_socket.keys())}) — the exemption list is stale "
        f"and is now excusing nothing, making the comparison below weaker than "
        f"it reads"
    )
    for key in over_socket.keys() - per_run - {"ticket"}:
        assert over_socket[key] == directly[key], (
            f"the socket path changed {key!r}: "
            f"{over_socket[key]!r} != {directly[key]!r}"
        )
    # The run id must differ — otherwise the two paths shared a run and the
    # comparison above is between one invocation and itself.
    assert over_socket["run_id"] != directly["run_id"]


# ---------------------------------------------------------------------------
# AC-2 — killing the host process loses nothing the ledger did not already hold.
# ---------------------------------------------------------------------------


def test_a_verb_still_runs_after_the_host_process_is_restarted(
    server: serve.VerbServer, workspace: Path, image: str
) -> None:
    """The kill-and-continue half of AC-2, needing two real processes.

    The host holds no run state, so a restart between two verbs of the same run
    is unobservable to the verbs themselves — they consult the ledger, which the
    restart never touched.
    """
    first = _capture(
        repo=workspace, argv=["runs"], socket_at=server.socket_path, image=image
    )
    assert first.code == 0, first.diagnosis(["runs"])

    server.shutdown()
    server.server_close()

    restarted = serve.VerbServer(
        socket_path=server.socket_path,
        roots=server.roots,
        image=image,
        env=dict(os.environ),
    )
    thread = threading.Thread(target=restarted.serve_forever, daemon=True)
    thread.start()
    try:
        second = _capture(
            repo=workspace,
            argv=["runs"],
            socket_at=restarted.socket_path,
            image=image,
        )
    finally:
        restarted.shutdown()

    assert second.contract == first.contract, (
        "a verb behaved differently after the host process was restarted — the "
        "host is carrying state a restart destroyed:\n"
        f"  before: {first.diagnosis(['runs'])}\n"
        f"  after:  {second.diagnosis(['runs'])}"
    )


def test_the_socket_is_not_world_accessible(
    server: serve.VerbServer,
) -> None:
    """The socket's only authentication is filesystem permissions, so they are
    the security boundary and are asserted rather than assumed."""
    assert (server.socket_path.stat().st_mode & 0o077) == 0
    assert (server.socket_path.parent.stat().st_mode & 0o077) == 0


def test_an_unreachable_socket_still_runs_every_verb(
    workspace: Path, image: str
) -> None:
    """AC-3 against real containers rather than a stub."""
    captured = _capture(
        repo=workspace,
        argv=["version"],
        socket_at=Path("/tmp/definitely-not-a-socket"),
        image=image,
    )

    assert captured.code == 0, captured.diagnosis(["version"])
    assert b"harness" in captured.stdout.lower(), captured.diagnosis(["version"])


def test_the_socket_refuses_a_repo_outside_the_allowlist(
    server: serve.VerbServer, image: str
) -> None:
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.connect(str(server.socket_path))
    devnull = os.open(os.devnull, os.O_RDWR)
    try:
        from harness.hostenv import protocol

        socket.send_fds(
            conn,
            [protocol.encode_request(repo=Path("/etc"), argv=["version"]).encode()],
            [devnull, devnull, devnull],
        )
        chunks = []
        while chunk := conn.recv(65536):
            chunks.append(chunk)
        response = protocol.decode_response(b"".join(chunks))
    finally:
        os.close(devnull)
        conn.close()

    assert response.reason == protocol.Reason.REPO_NOT_ALLOWED
