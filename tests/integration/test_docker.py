"""Docker image build + run integration test.

Asserts:

1. The Docker image at ``docker/Dockerfile`` builds successfully from the repo
   root (this also exercises the ``.dockerignore`` re-include that puts
   ``docker/entrypoint.sh`` in the build context).
2. The image's entrypoint runs a one-shot verb: a bare verb stays backward
   compatible (``docker run --rm <image> version`` prints a ``harness`` version
   string), and the explicit ``verb <args…>`` selector runs a one-shot verb.
   (The launcher-socket ``agent`` mode was the deferred Hermes-dispatch
   scaffolding, removed in CAL-712.)
3. The container runs as a **non-root** user (CAL-1008) — the runtime proof of
   the ``USER`` directive whose source invariant is locked in
   ``tests/unit/test_container_hardening.py``.

The build uses a dedicated ``harness:test`` tag, **not** ``harness:dev``, so a
host / CI run of this test never clobbers a developer's working ``harness:dev``
image mid-session (the runtime behaviour now differs — non-root — so a stray
rebuild of the live tag could break an in-flight verb loop).

The test is marked ``@pytest.mark.docker`` and SKIPS if ``docker info`` fails
(CI may not have docker available; macOS/Linux dev hosts typically do).

Build is cached across pytest invocations by Docker's layer cache — the
critical path stays small once ``pyproject.toml`` / ``uv.lock`` are stable.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"
IMAGE_TAG = "harness:test"


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
    """`verb <args…>` runs a single one-shot verb (the explicit selector)."""
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


def test_docker_runs_as_non_root(built_image: str) -> None:
    """The container's runtime user is non-root (uid != 0) — CAL-1008.

    Runtime proof of the ``USER`` directive: overriding the entrypoint with
    ``id -u`` reports the uid the container actually runs as.
    """
    result = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "id", built_image, "-u"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (
        f"`docker run --entrypoint id ... -u` failed (exit {result.returncode}).\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    uid = result.stdout.strip()
    assert uid and uid != "0", (
        f"container must run as a non-root user; got uid {uid!r}"
    )
