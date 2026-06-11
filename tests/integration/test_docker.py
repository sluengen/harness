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

import shutil
import subprocess
from pathlib import Path

import pytest

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
