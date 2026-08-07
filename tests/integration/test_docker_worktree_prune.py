"""AC-1 (#371): a real container tears down a worktree without deregistering others.

The whole defect lives at the container/host filesystem boundary, so no argv
assertion can stand in for it. Inside the container the repo is mounted at
``/workspace`` and **nothing else on the host exists** — so a repo-wide ``git
worktree prune``, which teardown used to issue, reads every worktree registered
at a host path as missing and deletes its admin entry. A host-side prune does
not (the path is there), which is why this was twice recorded as a race between
concurrent sessions before the mechanism was found.

This module therefore runs the real thing: the harness image built from this
working tree, the repo bind-mounted at ``/workspace`` exactly as ``~/bin/harness``
mounts it, and :func:`harness._git.teardown_worktree` called inside it against a
run worktree. The bystander is registered at a path **outside** the mount, with
git's default absolute pointer — what an operator's own ``git worktree add``
produces, and the shape that was being lost.

**Both halves are asserted in one run, deliberately.** A container that never
reached teardown — a dubious-ownership refusal, a bad mount, a missing
interpreter — leaves the bystander untouched for the wrong reason and would read
as a pass. So the run must also show that the run worktree really was removed,
and stdout must carry the sentinel the in-container script prints.

``tests/unit/test_teardown_worktree.py`` carries the same mechanism host-side (by
renaming a bystander's directory away, which is the condition the mount creates)
so it is measured on machines with no Docker daemon, where this module skips —
and a skip proves nothing.

The module-scoped build fixture follows the precedent in ``test_docker.py`` and
``test_serve_socket.py``: each docker module builds the shared ``harness:test``
tag for itself, and the ``docker`` marker puts all three in the serialized stage
of ``scripts/verify.sh`` so they cannot race that one tag (#358).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"
IMAGE_TAG = "harness:test"

#: The run worktree the container is asked to tear down, and the bystander it
#: must not touch. The bystander's name is the ``gate-<sha>`` shape of the real
#: incident: a verify-gate worktree parked outside the repo.
_RUN_ID = "RUN1"
_BYSTANDER = "gate-wt"

#: Printed by the in-container script after teardown returns. Its absence means
#: the container failed before doing anything, which must not read as a pass.
_SENTINEL = "teardown-returned"

_IN_CONTAINER = f"""
from pathlib import Path
from harness._git import teardown_worktree

teardown_worktree(
    Path("/workspace"),
    worktree_path=Path("/workspace/.worktrees/harness/{_RUN_ID}"),
    branch="harness/{_RUN_ID}",
)
print("{_SENTINEL}")
"""


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
    # A cold build source-builds git and measured ~165s; the global 120s cap
    # exists to kill a hung test, not a long one (the CAL-1110 rationale in
    # test_docker.py). Scoped to this module.
    pytest.mark.timeout(600),
    pytest.mark.skipif(
        not _docker_available(),
        reason="docker daemon not available (skipping docker integration test)",
    ),
]


@pytest.fixture(scope="module")
def built_image() -> str:
    """Build the image from *this* working tree, once per module run.

    Built rather than assumed: the claim is that the teardown as shipped in the
    container spares the bystander, so the image has to carry the code under
    review. A stale image fails this test rather than passing it — it would
    still issue the repo-wide prune — so the failure direction is safe.
    """
    result = subprocess.run(
        ["docker", "build", "-t", IMAGE_TAG, "-f", str(DOCKERFILE), str(REPO_ROOT)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, (
        f"docker build failed (exit {result.returncode}).\n{result.stderr}"
    )
    return IMAGE_TAG


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


@pytest.fixture
def repo_with_an_outside_worktree(tmp_path: Path) -> Path:
    """A repo carrying one run worktree inside it and one bystander outside it.

    The run worktree gets **relative** pointers, as ``harness start`` writes them
    (they resolve identically at ``/Users/...`` and ``/workspace``); the
    bystander gets git's default absolute pointer, which cannot resolve inside
    the container — that is precisely what made it look prunable.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "dev")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "README.md").write_text("hi\n")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "init")
    _git(
        root,
        "-c",
        "worktree.useRelativePaths=true",
        "worktree",
        "add",
        "-b",
        f"harness/{_RUN_ID}",
        str(root / ".worktrees" / "harness" / _RUN_ID),
        "dev",
    )
    _git(root, "worktree", "add", "--detach", str(tmp_path / _BYSTANDER), "dev")
    return root


def _entries(root: Path) -> set[str]:
    registry = root / ".git" / "worktrees"
    return {p.name for p in registry.iterdir()} if registry.is_dir() else set()


def test_container_teardown_spares_a_worktree_outside_the_mount(
    built_image: str, repo_with_an_outside_worktree: Path, tmp_path: Path
) -> None:
    root = repo_with_an_outside_worktree
    assert _entries(root) == {_RUN_ID, _BYSTANDER}, "fixture precondition"

    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            # Match the host uid so git accepts the bind-mounted repo instead of
            # refusing it as dubiously owned before teardown is ever reached.
            "-u",
            f"{os.getuid()}:{os.getgid()}",
            "-v",
            f"{root}:/workspace",
            "-w",
            "/opt/harness",
            "--entrypoint",
            "/opt/harness/.venv/bin/python",
            built_image,
            "-c",
            _IN_CONTAINER,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, (
        f"the in-container teardown exited {result.returncode}.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert _SENTINEL in result.stdout, (
        "teardown never returned inside the container, so the bystander was "
        f"spared for the wrong reason.\n--- stderr ---\n{result.stderr}"
    )

    # It did the job it was asked to do (AC-2, in the same run).
    assert not (root / ".worktrees" / "harness" / _RUN_ID).exists()
    assert _RUN_ID not in _entries(root)

    # ...and nothing else (AC-1).
    assert _BYSTANDER in _entries(root), (
        "the container deregistered a worktree outside its mount — the failure "
        "this ticket is about (#371)"
    )
    # The ticket's actual signature: exit 128 from every tracked-tree read.
    _git(tmp_path / _BYSTANDER, "ls-files")
