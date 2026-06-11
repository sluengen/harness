"""Docker image build + run integration test.

Asserts:

1. The Docker image at ``docker/Dockerfile`` builds successfully from the repo
   root using the tag ``harness:dev`` (this also exercises the ``.dockerignore``
   re-include that puts ``docker/entrypoint.sh`` in the build context).
2. The image's entrypoint is the two-entrypoint dispatch script (decision #3,
   CAL-585): a bare verb stays backward compatible
   (``docker run --rm harness:dev version`` prints a ``harness`` version string),
   ``verb <args…>`` runs a one-shot verb, and ``agent`` without a ticket is an
   invocation error (exit 2).

The test is marked ``@pytest.mark.docker`` and SKIPS if ``docker info`` fails
(CI may not have docker available; macOS/Linux dev hosts typically do).

Build is cached across pytest invocations by Docker's layer cache — the
critical path stays small once ``pyproject.toml`` / ``uv.lock`` are stable.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

import pytest

from harness.launcher import ControlServer
from harness.launcher_client import LauncherClient, verb_argv_to_request
from harness.state import store

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"
IMAGE_TAG = "harness:dev"


def _docker_available() -> bool:
    """Return True iff `docker info` exits cleanly."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker,
    pytest.mark.skipif(
        not _docker_available(),
        reason="docker daemon not available (skipping docker integration test)",
    ),
]


@pytest.fixture(scope="module")
def built_image() -> str:
    """Build the docker image once per test module run."""
    assert DOCKERFILE.exists(), (
        f"Expected Dockerfile at {DOCKERFILE} — H-029 must create it."
    )
    result = subprocess.run(
        [
            "docker",
            "build",
            "-t",
            IMAGE_TAG,
            "-f",
            str(DOCKERFILE),
            str(REPO_ROOT),
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, (
        f"docker build failed (exit {result.returncode}).\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    return IMAGE_TAG


def test_docker_image_builds(built_image: str) -> None:
    """The image exists in the local docker daemon after the build."""
    result = subprocess.run(
        ["docker", "image", "inspect", built_image],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (
        f"docker image inspect failed for {built_image}:\n{result.stderr}"
    )


def test_docker_run_harness_version(built_image: str) -> None:
    """`docker run --rm <image> version` prints the harness version string."""
    result = subprocess.run(
        ["docker", "run", "--rm", built_image, "version"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (
        f"`docker run ... version` failed (exit {result.returncode}).\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    assert "harness" in result.stdout, (
        f"Expected 'harness' in version output, got: {result.stdout!r}"
    )


def test_docker_verb_mode_runs_a_verb(built_image: str) -> None:
    """`verb <args…>` runs a single one-shot verb (two-entrypoint dispatch)."""
    result = subprocess.run(
        ["docker", "run", "--rm", built_image, "verb", "version"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (
        f"`docker run ... verb version` failed (exit {result.returncode}).\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert "harness" in result.stdout, result.stdout


def test_docker_agent_mode_requires_a_ticket(built_image: str) -> None:
    """`agent` with no ticket is an invocation error (exit 2) — proves the image
    ships the two-entrypoint switch, not the old bare `uv run harness`."""
    result = subprocess.run(
        ["docker", "run", "--rm", built_image, "agent"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 2, (
        f"expected exit 2 for agent-without-ticket, got {result.returncode}.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert "agent mode requires a ticket" in result.stderr, result.stderr


# ---------------------------------------------------------------------------
# AC-1, real container boundary: the launcher spawns a genuine one-shot verb
# container in response to a control-socket request. Unlike the hermetic demo
# (tests/integration/test_hermes_demo.py), this uses the REAL docker runner and
# the REAL image — proving the socket → `docker run --rm <image> <verb>` →
# bounded-result path the agent runtime relies on, without a live LLM/Linear.
# ---------------------------------------------------------------------------


def _sync(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _seed_open_run(db_path: Path, repo: Path, run_id: str) -> None:
    async def _insert() -> None:
        await store.init_db(db_path)
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs ("
                "run_id, workflow_name, workflow_version, status, state_json, "
                "inputs_json, base_branch, worktree_path, worktree_branch, "
                "ticket, started_at, pid"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id, "", 0, "open", "{}", "{}", "dev", str(repo),
                    f"harness/{run_id}", "CAL-585", "2026-06-11T00:00:00Z", 1234,
                ),
            )
            await conn.commit()

    _sync(_insert())


def test_launcher_spawns_real_verb_container_over_socket(
    built_image: str, tmp_path: Path
) -> None:
    """A `status` request over the launcher socket runs a REAL one-shot
    `docker run --rm harness:dev status …` container that reads the mounted
    ledger and returns the run row — the actual container boundary, end to end."""
    workdir = tmp_path / "work"
    repo = workdir / "repo"
    repo.mkdir(parents=True)
    run_id = "01JRUNDOCKERXXXXXXXXXXXX01"
    _seed_open_run(repo / ".harness" / "harness.db", repo, run_id)

    # Real ControlServer: the default docker runner actually shells out.
    server_obj = ControlServer(
        image=built_image,
        roots=[workdir.resolve()],
        host_env={},
        home=tmp_path / "home",
    )
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="hns-") as sd:
        socket_path = Path(sd) / "control.sock"
        server = server_obj.create_server(socket_path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            req = verb_argv_to_request(["status", run_id, "--json"], repo=str(repo))
            resp = LauncherClient(socket_path).request(str(req["op"]), req["params"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    assert resp["ok"] is True, resp
    assert resp["exit_code"] == 0, resp
    row = json.loads(resp["stdout"])
    assert row["run_id"] == run_id
    assert row["status"] == "open"
