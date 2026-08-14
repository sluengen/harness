"""Docker image build + run integration test.

Asserts:

1. The Docker image at ``docker/Dockerfile`` builds successfully from the repo
   root (this also exercises the ``.dockerignore`` re-include that puts
   ``docker/entrypoint.sh`` in the build context).
2. The image's entrypoint dispatches both its roles. The verb role: a bare verb
   stays backward compatible (``docker run --rm <image> version`` prints a
   ``harness`` version string), and the explicit ``verb <args…>`` selector runs a
   one-shot verb. The ``install`` role (#312) emits the ``~/bin/harness`` client
   on stdout — proven **against the built image**, because a producer that is
   right in the checkout and absent from the image is exactly the failure the
   ``.dockerignore`` re-include exists to prevent.
   (The launcher-socket ``agent`` mode was the deferred Hermes-dispatch
   scaffolding, removed in CAL-712.)
3. The container runs as a **non-root** user (CAL-1008) — the runtime proof of
   the ``USER`` directive whose source invariant is locked in
   ``tests/unit/test_container_hardening.py``.
4. The image runs a verb as an **arbitrary** uid, and a mutating verb writes a
   bind-mounted repo the *invoking* user owns (#380). Both build their argv
   through :func:`harness.hostenv.spawn.build_docker_argv` — the production
   construction, never a hand-rolled ``docker run`` — because what is under test
   is the pairing of the host's ``--user`` with an image that has a home an
   arbitrary uid can use. Either half alone was measured failing.

Items 3 and 4 are two halves of one property and belong in one module: the image
must drop root *and* be usable by whoever the host pins it to. A container that
can only run as its own baked uid 1000 satisfies the first and breaks every
mutating verb on a native daemon, which is the defect #380 exists for.

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

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from harness.hostenv import spawn
from harness.hostenv.host import LinuxHost
from tests._gitutil import init_repo

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
    # The global pytest-timeout cap is 120s, which exists to kill a *hung* test.
    # This build is not hung, it is genuinely long: with no layer cache it
    # source-builds git (CAL-935 / CAL-1008) and measured 165s cold on the
    # author's machine, with a CI runner slower still. Without this override the
    # fixture's own 600s build budget is unreachable — pytest kills the test at
    # 120s first — so the module failed on every cold cache and passed on every
    # warm one (CAL-1110). Scoped to this module: the global default stays 120s
    # for the other ~1500 tests.
    pytest.mark.timeout(600),
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


def test_the_image_install_role_emits_a_client(built_image: str) -> None:
    """``install`` emits a working client **from the built artifact** (#312).

    Every other test of this role runs the producer out of the checkout, which
    proves the script is right and says nothing about whether it is *in the
    image*. The two ways this fails are both invisible to those tests: the
    ``.dockerignore`` re-include missing, so the producer or its template never
    enters the build context, and the ``COPY`` missing, so the entrypoint's branch
    dispatches to a path that does not exist.

    The body is compared byte-for-byte against ``docker/harness-wrapper.sh``,
    which is also what proves the image is not carrying a second, stale copy of
    the shim — the drift this whole design exists to remove.
    """
    result = _run(
        ["docker", "run", "--rm", built_image, "install", "--source-root", "/srv/harness"],
        timeout=60,
    )

    assert result.returncode == 0, _diagnosis(result)
    assert result.stdout.startswith("#!/usr/bin/env bash\n"), _diagnosis(result)
    assert "_harness_baked_source_root='/srv/harness'" in result.stdout, _diagnosis(result)
    assert re.search(r"_harness_baked_client_version='[^']+\+\d{8}T\d{6}Z'", result.stdout), (
        _diagnosis(result)
    )

    versioned = (REPO_ROOT / "docker" / "harness-wrapper.sh").read_text()
    assert result.stdout.endswith(versioned), (
        "the client emitted by the image is not the versioned shim verbatim — the "
        "image is carrying a second shim source"
    )


def test_the_image_install_role_refuses_rather_than_emitting_a_broken_client(
    built_image: str,
) -> None:
    """A refusal inside the container reaches the operator as exit 2 with an empty
    stdout, so ``… install > ~/bin/harness`` cannot truncate a working client into
    nothing on a bad argument."""
    result = _run(
        ["docker", "run", "--rm", built_image, "install", "--source-root", "relative"],
        timeout=60,
    )

    assert result.returncode == 2, _diagnosis(result)
    assert result.stdout == "", _diagnosis(result)


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


# ---------------------------------------------------------------------------
# #380 — the image is usable by whatever uid the host pins it to.
# ---------------------------------------------------------------------------

#: The branch ``init_repo`` creates. Stated in the fixture's ``CONTEXT.md`` too,
#: from this one constant: a fixture declaring one branch and initialising
#: another agreed with itself only on hosts whose ``init.defaultBranch`` matched,
#: and kept CI red for two days when the runner's did not (#369).
_FIXTURE_BRANCH = "dev"

#: A uid that exists in no image and on no host here, so a container running as
#: it has no passwd entry and no pre-made home — the condition every pinned host
#: uid meets on a native daemon, reproduced on a machine whose own uid happens to
#: be usable.
_ARBITRARY_UID = 4242


@pytest.fixture
def host_home(tmp_path: Path) -> Path:
    """A stand-in for the operator's home, with the two credential dirs present.

    ``build_docker_argv`` mounts ``~/.ssh`` and ``~/.codex`` unconditionally. Left
    absent, the daemon creates them itself as root-owned directories, which is a
    second, unrelated permission problem inside an assertion about the first.
    """
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".codex").mkdir(parents=True)
    return home


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A committed ``tracker: none`` repo, so a mutating verb needs no network."""
    repo = init_repo(tmp_path / "ws")
    (repo / "CONTEXT.md").write_text(
        "```yaml\nrepo:\n  name: ws\ntracker: none\nbranches:\n"
        f"  integration: {_FIXTURE_BRANCH}\n```\n"
    )
    (repo / "README.md").write_text("fixture\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=repo,
        check=True,
    )
    return repo


def _run(argv: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout, check=False
    )


def _diagnosis(result: subprocess.CompletedProcess[str]) -> str:
    return (
        f"exit {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


def test_the_image_runs_a_verb_as_an_arbitrary_uid(
    built_image: str, workspace: Path, host_home: Path
) -> None:
    """A verb runs under a uid the image never heard of (#380).

    Nothing here is hypothetical: pinning ``--user`` is what every native daemon
    now does, and the uid it pins is the operator's, which has no ``/etc/passwd``
    entry inside this image. Docker then resolves ``HOME`` to ``/`` and ``uv``
    dies initialising its cache before the verb starts — measured as exit 2,
    ``Failed to initialize cache at /.cache/uv``. The two halves that fix it (the
    pinned ``HOME``, and a home directory an arbitrary uid can write) were each
    measured *insufficient alone*, which is why this asserts the verb's own
    output rather than the container merely starting.
    """
    argv = spawn.build_docker_argv(
        repo=workspace,
        argv=["version"],
        image=built_image,
        env_names=[],
        home=host_home,
        container_user=spawn.ContainerUser(uid=_ARBITRARY_UID, gid=_ARBITRARY_UID),
    )

    result = _run(argv)

    assert result.returncode == 0, _diagnosis(result)
    assert "harness" in result.stdout, _diagnosis(result)


def test_a_mutating_verb_writes_a_repo_owned_by_the_invoking_uid(
    built_image: str, workspace: Path, host_home: Path
) -> None:
    """The ticket's own scenario: ``start`` against a repo this user owns.

    The container user comes from a real ``LinuxHost`` rather than a literal —
    that provider is the one CI and every Linux operator gets, and constructing
    it directly is how a macOS box exercises it at all. ``start`` is the cheapest
    verb that writes: it opens the ledger at ``.harness/harness.db`` and adds a
    worktree, which is exactly what failed with ``PermissionError`` on the runner.
    """
    if os.getuid() == 1000:
        pytest.skip(
            "this host's uid is the image's baked 1000, so a container ignoring "
            "--user entirely would write the repo just as successfully — the "
            "assertion cannot tell the fix from the coincidence here"
        )

    argv = spawn.build_docker_argv(
        repo=workspace,
        argv=["start", "1", "--json"],
        image=built_image,
        env_names=[],
        home=host_home,
        container_user=LinuxHost(name="linux", env={}).container_user(),
    )

    result = _run(argv)

    assert result.returncode == 0, _diagnosis(result)
    assert json.loads(result.stdout)["run_id"], _diagnosis(result)

    ledger = workspace / ".harness" / "harness.db"
    assert ledger.exists(), (
        f"the verb reported success but wrote no ledger:\n{_diagnosis(result)}"
    )
    assert ledger.stat().st_uid == os.getuid(), (
        f"the ledger is owned by uid {ledger.stat().st_uid}, not the invoking "
        f"{os.getuid()} — the container wrote as somebody else, and the operator "
        f"cannot read their own run without root"
    )
