"""Integration test: container finds workflows via HARNESS_WORKFLOWS_DIR.

Acceptance criterion (Path A):
  Container invoked with ``--workflows-dir`` unset from a directory that
  contains no ``workflows/`` folder finds and loads ``build.yaml`` from
  the image (because the Dockerfile sets
  ``ENV HARNESS_WORKFLOWS_DIR=/opt/harness/workflows``).

Requires:
  - A running Docker daemon.
  - The ``harness:dev`` image already built (the ``built_image`` fixture
    in ``test_docker.py`` handles that; run the full integration suite or
    build manually with ``docker build -t harness:dev -f docker/Dockerfile .``).

Run with::

    pytest -m docker tests/integration/test_container_workflows_dir.py

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
        f"Expected Dockerfile at {DOCKERFILE}."
    )
    result = subprocess.run(
        ["docker", "build", "-t", IMAGE_TAG, "-f", str(DOCKERFILE), str(REPO_ROOT)],
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


def test_container_finds_build_workflow_without_workflows_dir_flag(
    built_image: str,
    tmp_path: Path,
) -> None:
    """Container invoked from a tmp dir (no local workflows/) finds build.yaml.

    The Dockerfile sets ``ENV HARNESS_WORKFLOWS_DIR=/opt/harness/workflows``.
    The CLI should resolve the workflows directory from that env var without
    any ``--workflows-dir`` flag, making ``harness run build --help`` work.
    """
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{tmp_path}:/workspace",
            "-w",
            "/workspace",
            built_image,
            "run",
            "build",
            "--help",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"`docker run ... run build --help` failed (exit {result.returncode}).\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    # The build workflow declares --linear as a required input; it must appear in help.
    assert "--linear" in combined, (
        f"Expected '--linear' in help output; got:\n{combined}"
    )
