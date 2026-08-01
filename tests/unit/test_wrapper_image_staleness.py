"""The versioned wrapper must not silently run a stale ``harness:dev`` image
(CAL-1144).

Nothing rebuilds the image after a merge to ``dev``, so a verb that ships is
invisible to the next unattended tick: the loop sees only ``No such command
'<verb>'`` and diagnoses missing code rather than a stale image. That happened
for real with the ``defer`` verb (CAL-1143), and three subsequent ticks each paid
a manual ``docker image inspect`` / ``git log`` comparison to work around it.

The guard lives in the **wrapper** because it is the one component every verb
already goes through (the ticket's approach 1; an eighth ``doctor`` check was
rejected because ``doctor`` is not run every tick, which is the failure mode
being fixed). When the source is newer than the image the wrapper rebuilds,
rather than refusing: the loop is unattended, and a hard error would trade a
silent stale image for a queue that wedges every hour until a human rebuilds.

These tests **execute** the wrapper against stubbed ``docker`` and ``git`` rather
than grepping its text, because the acceptance criteria turn on *behaviour* that
differs between a stale and a fresh image — a text guard cannot tell those apart.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
WRAPPER = PROJECT_ROOT / "docker" / "harness-wrapper.sh"

# One fixed instant, expressed the two ways the wrapper must reconcile: the
# nanosecond RFC3339 UTC that `docker image inspect` reports, and the epoch
# seconds that git's `%ct` reports. These must denote the SAME moment — the
# tests below place the source a hair either side of it.
IMAGE_INSTANT_RFC3339 = "2026-07-17T06:00:00.123456789Z"
IMAGE_INSTANT_EPOCH = 1_784_268_000  # == 2026-07-17T06:00:00Z
ONE_HOUR = 3600

_DOCKER_STUB = """#!/usr/bin/env bash
echo "docker $*" >> "$STUB_LOG"
if [[ "$1" == "image" && "$2" == "inspect" ]]; then
  if [[ -n "${STUB_IMAGE_CREATED:-}" ]]; then echo "$STUB_IMAGE_CREATED"; exit 0; fi
  exit 1
fi
if [[ "$1" == "build" ]]; then exit "${STUB_BUILD_EXIT:-0}"; fi
exit 0
"""

_GIT_STUB = """#!/usr/bin/env bash
echo "git $*" >> "$STUB_LOG"
for a in "$@"; do
  if [[ "$a" == "log" ]]; then echo "${STUB_SOURCE_EPOCH:-0}"; exit 0; fi
  if [[ "$a" == "config" ]]; then echo "Test User"; exit 0; fi
done
exit 0
"""


def _run_wrapper(tmp_path: Path, **stub_env: str) -> subprocess.CompletedProcess[str]:
    """Run the real wrapper with ``docker``/``git`` stubbed, and return the result.

    ``CLAUDE_CODE_OAUTH_TOKEN`` is preset so the wrapper skips its Keychain block
    (which would shell out to the real ``security``/``claude``), and
    ``SSH_AUTH_SOCK`` is cleared so the ssh-agent block stays out of the way.
    """
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir(parents=True, exist_ok=True)
    for name, body in (("docker", _DOCKER_STUB), ("git", _GIT_STUB)):
        path = stub_bin / name
        path.write_text(body)
        path.chmod(0o755)

    # Truncate: the stubs append, and a test may run the wrapper twice over one
    # tmp_path — a leaked call from the first run would satisfy the second's
    # assertions.
    log = tmp_path / "calls.log"
    log.write_text("")

    env = dict(os.environ)
    env.pop("SSH_AUTH_SOCK", None)
    env.update(
        {
            "PATH": f"{stub_bin}:{env['PATH']}",
            "STUB_LOG": str(log),
            "CLAUDE_CODE_OAUTH_TOKEN": "test-token",
            **stub_env,
        }
    )

    result = subprocess.run(
        [str(WRAPPER), "start", "CAL-1"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
    )
    result.calls = log.read_text()  # type: ignore[attr-defined]
    return result


def test_stale_image_is_rebuilt_before_the_verb_runs(tmp_path: Path) -> None:
    """AC1: source newer than the image → the wrapper does not silently run stale
    code. It rebuilds, and the rebuild precedes the verb."""
    result = _run_wrapper(
        tmp_path,
        STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339,
        STUB_SOURCE_EPOCH=str(IMAGE_INSTANT_EPOCH + ONE_HOUR),
    )
    calls = result.calls  # type: ignore[attr-defined]
    assert "docker build" in calls, (
        f"a stale image was not rebuilt; wrapper calls were:\n{calls}"
    )
    build_at = calls.index("docker build")
    run_at = calls.index("docker run")
    assert build_at < run_at, f"the rebuild must precede the verb:\n{calls}"
    assert result.returncode == 0


def test_stale_rebuild_is_announced_on_stderr_not_stdout(tmp_path: Path) -> None:
    """AC3: the staleness is diagnosable from the message alone. It goes to
    **stderr**: stdout carries the verbs' JSON contract, which the orchestrating
    loop parses, so a build log on stdout would corrupt it."""
    result = _run_wrapper(
        tmp_path,
        STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339,
        STUB_SOURCE_EPOCH=str(IMAGE_INSTANT_EPOCH + ONE_HOUR),
    )
    assert "stale" in result.stderr.lower()
    assert result.stdout.strip() == "", (
        f"the guard must not write to stdout (it carries JSON):\n{result.stdout}"
    )


def test_fresh_image_is_not_rebuilt_and_warns_nothing(tmp_path: Path) -> None:
    """AC2: a current image is not a false positive — no rebuild, no warning."""
    result = _run_wrapper(
        tmp_path,
        STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339,
        STUB_SOURCE_EPOCH=str(IMAGE_INSTANT_EPOCH - ONE_HOUR),
    )
    calls = result.calls  # type: ignore[attr-defined]
    assert "docker build" not in calls, (
        f"a fresh image must not be rebuilt; wrapper calls were:\n{calls}"
    )
    assert "docker run" in calls
    assert "stale" not in result.stderr.lower()
    assert result.returncode == 0


def test_failed_rebuild_fails_loudly_and_never_runs_the_stale_image(
    tmp_path: Path,
) -> None:
    """A rebuild that fails must not fall through to the stale image — that would
    reinstate the silent failure this guard exists to remove."""
    result = _run_wrapper(
        tmp_path,
        STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339,
        STUB_SOURCE_EPOCH=str(IMAGE_INSTANT_EPOCH + ONE_HOUR),
        STUB_BUILD_EXIT="1",
    )
    calls = result.calls  # type: ignore[attr-defined]
    assert result.returncode != 0, "a failed rebuild must not exit 0"
    assert "docker run" not in calls, (
        f"the stale image must not run after a failed rebuild:\n{calls}"
    )


def test_the_comparison_is_exact_to_the_second(tmp_path: Path) -> None:
    """The two clocks are reconciled exactly — no timezone skew.

    ``docker image inspect`` reports UTC while the host here is UTC+10, so a
    naive comparison is wrong by hours in a way that hourly-granularity fixtures
    would not catch: it would call a source committed 9 hours *after* the image
    fresh. Straddling the instant by one second pins that — an offset bug of any
    size flips at least one of these two assertions.
    """
    one_second_newer = _run_wrapper(
        tmp_path,
        STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339,
        STUB_SOURCE_EPOCH=str(IMAGE_INSTANT_EPOCH + 1),
    )
    assert "docker build" in one_second_newer.calls, (  # type: ignore[attr-defined]
        "a source one second newer than the image is stale and must rebuild"
    )

    one_second_older = _run_wrapper(
        tmp_path,
        STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339,
        STUB_SOURCE_EPOCH=str(IMAGE_INSTANT_EPOCH - 1),
    )
    assert "docker build" not in one_second_older.calls, (  # type: ignore[attr-defined]
        "a source one second older than the image is fresh and must not rebuild"
    )


def test_overridden_image_is_left_alone(tmp_path: Path) -> None:
    """A caller-supplied ``HARNESS_IMAGE`` is the caller's to manage: the guard
    compares this repo's source against the *default* image it builds, and would
    otherwise clobber a deliberately-pinned tag with a rebuild off this tree."""
    result = _run_wrapper(
        tmp_path,
        HARNESS_IMAGE="harness:pinned",
        STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339,
        STUB_SOURCE_EPOCH=str(IMAGE_INSTANT_EPOCH + ONE_HOUR),
    )
    calls = result.calls  # type: ignore[attr-defined]
    assert "docker build" not in calls, (
        f"an overridden image tag must not be rebuilt:\n{calls}"
    )
    assert "docker run" in calls
    assert result.returncode == 0


# --- The detached-copy deployment (CAL-1153) --------------------------------
#
# The guard resolves its source root from the wrapper's own location and asks
# git for ``harness/``'s last-commit time there. A wrapper **symlinked** onto
# PATH resolves to its real checkout, so the guard runs; a wrapper **copied**
# onto PATH resolves outside any checkout, git returns nothing, and the guard
# has no tree to compare against. That second deployment is the one in real use,
# and the tests above never exercise it — they run the wrapper straight from the
# checkout with a git stub that answers unconditionally.
#
# These tests reproduce the distinction faithfully with a **repo-aware** git
# stub: like real ``git -C <dir> log``, it answers only when ``<dir>`` is a
# checkout (has a ``.git``) and fails otherwise. So whether ``_source_committed``
# comes back populated turns on where the executed wrapper physically lives,
# exactly as it does in production — not on a stub flag.
_GIT_STUB_REPO_AWARE = """#!/usr/bin/env bash
echo "git $*" >> "$STUB_LOG"
_cdir="."
_prev=""
for a in "$@"; do
  if [[ "$_prev" == "-C" ]]; then _cdir="$a"; fi
  _prev="$a"
done
for a in "$@"; do
  if [[ "$a" == "log" ]]; then
    if [[ -e "$_cdir/.git" ]]; then echo "${STUB_SOURCE_EPOCH:-0}"; exit 0; fi
    echo "fatal: not a git repository" >&2; exit 128
  fi
  if [[ "$a" == "config" ]]; then echo "Test User"; exit 0; fi
done
exit 0
"""


def _run_exe(
    exe: Path, cwd: Path, tmp_path: Path, **stub_env: str
) -> subprocess.CompletedProcess[str]:
    """Run an arbitrary wrapper ``exe`` (a copy or a symlink) with a repo-aware
    git stub, from working directory ``cwd``. Mirrors ``_run_wrapper`` but lets
    the caller place the executed wrapper where it likes, so its resolved source
    root — checkout or not — is what the guard actually sees."""
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir(parents=True, exist_ok=True)
    for name, body in (("docker", _DOCKER_STUB), ("git", _GIT_STUB_REPO_AWARE)):
        path = stub_bin / name
        path.write_text(body)
        path.chmod(0o755)

    log = tmp_path / "calls.log"
    log.write_text("")

    env = dict(os.environ)
    env.pop("SSH_AUTH_SOCK", None)
    env.update(
        {
            "PATH": f"{stub_bin}:{env['PATH']}",
            "STUB_LOG": str(log),
            "CLAUDE_CODE_OAUTH_TOKEN": "test-token",
            **stub_env,
        }
    )
    result = subprocess.run(
        [str(exe), "start", "CAL-1"],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
    )
    result.calls = log.read_text()  # type: ignore[attr-defined]
    return result


def _detached_copy(tmp_path: Path) -> Path:
    """Copy the real wrapper to a path whose parent is not a git checkout, the
    way ``~/bin/harness`` is a copy under ``~`` rather than a symlink into the
    repo. ``tmp_path/detached/`` has no ``.git``, so the guard's source root
    resolves outside any checkout."""
    detached = tmp_path / "detached"
    detached.mkdir(parents=True, exist_ok=True)
    dest = detached / "harness"
    dest.write_bytes(WRAPPER.read_bytes())
    dest.chmod(0o755)
    return dest


def test_detached_copy_with_image_warns_and_still_runs_the_verb(
    tmp_path: Path,
) -> None:
    """AC1/AC3: a copied wrapper cannot compare the image against a source tree.
    With an image present it must not stay silent — it warns (naming the
    detached-copy cause and the symlink remedy) and still runs the verb, exit
    code unchanged. This is the deployment in real use, previously untested."""
    exe = _detached_copy(tmp_path)
    result = _run_exe(exe, tmp_path, tmp_path, STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339)

    calls = result.calls  # type: ignore[attr-defined]
    assert "docker run" in calls, (
        f"the verb must still run from a detached copy:\n{calls}"
    )
    assert "docker build" not in calls, (
        f"the guard cannot run without a source tree — it must not rebuild:\n{calls}"
    )
    assert result.returncode == 0, "a detached copy must not change the exit code"
    err = result.stderr.lower()
    assert "detached copy" in err, (
        f"the warning must name the detached-copy cause:\n{result.stderr}"
    )
    assert "symlink" in err, (
        f"the warning must point at the symlink remedy:\n{result.stderr}"
    )
    assert result.stdout.strip() == "", (
        f"the warning must not write to stdout (it carries JSON):\n{result.stdout}"
    )


def test_detached_copy_with_no_image_is_silent(tmp_path: Path) -> None:
    """AC2: with no image there is nothing to guard — a detached copy stays a
    silent no-op, exactly as before. The warning is about an *unguarded image*,
    not about being a copy per se."""
    exe = _detached_copy(tmp_path)
    result = _run_exe(exe, tmp_path, tmp_path)  # STUB_IMAGE_CREATED unset -> no image

    calls = result.calls  # type: ignore[attr-defined]
    assert "docker build" not in calls, f"no image -> no rebuild:\n{calls}"
    assert "docker run" in calls, f"the verb must still run:\n{calls}"
    assert "detached copy" not in result.stderr.lower(), (
        f"no image -> nothing to guard -> no warning:\n{result.stderr}"
    )
    assert result.returncode == 0


def test_symlinked_wrapper_still_arms_the_guard(tmp_path: Path) -> None:
    """AC4 (regression): the symlinked deployment must keep working. A symlink
    into the checkout resolves — via the wrapper's ``readlink`` chain — to the
    real source root, so the guard runs and a stale image is rebuilt. Proven by
    the rebuild firing where the detached copy above stayed silent."""
    link_dir = tmp_path / "link"
    link_dir.mkdir(parents=True, exist_ok=True)
    exe = link_dir / "harness"
    exe.symlink_to(WRAPPER)

    result = _run_exe(
        exe,
        tmp_path,
        tmp_path,
        STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339,
        STUB_SOURCE_EPOCH=str(IMAGE_INSTANT_EPOCH + ONE_HOUR),
    )
    calls = result.calls  # type: ignore[attr-defined]
    assert "docker build" in calls, (
        f"a symlinked wrapper resolves to its checkout and must arm the guard:\n{calls}"
    )
    assert "detached copy" not in result.stderr.lower(), (
        f"a symlinked wrapper is not a detached copy — no such warning:\n{result.stderr}"
    )


# --- The wrapper-drift status forwarded to doctor (CAL-1149) -----------------
#
# ``doctor`` runs in-container and cannot read the on-PATH ``~/bin/harness``
# (host-only, never mounted). The wrapper is the one place both the invoked
# wrapper and its versioned source are readable, so it computes the drift
# verdict host-side and forwards it as ``HARNESS_WRAPPER_STATUS`` on the
# ``docker run`` line; ``check_wrapper`` maps it to PASS/WARN/FAIL. These tests
# execute the real wrapper and assert the verdict it forwards for each
# deployment, the same repo-aware way the freshness tests above do.


def test_symlinked_wrapper_forwards_symlink_status(tmp_path: Path) -> None:
    """A symlink into the checkout resolves to the versioned source, so the
    wrapper forwards ``HARNESS_WRAPPER_STATUS=symlink`` — the PASS state."""
    link_dir = tmp_path / "link"
    link_dir.mkdir(parents=True, exist_ok=True)
    exe = link_dir / "harness"
    exe.symlink_to(WRAPPER)

    result = _run_exe(exe, tmp_path, tmp_path, STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339)
    calls = result.calls  # type: ignore[attr-defined]
    assert "HARNESS_WRAPPER_STATUS=symlink" in calls, (
        f"a symlinked wrapper must forward the symlink status:\n{calls}"
    )


def test_detached_copy_forwards_detached_status(tmp_path: Path) -> None:
    """A copy under a directory that is not a checkout has no versioned source to
    compare against, so the wrapper forwards ``HARNESS_WRAPPER_STATUS=detached``
    — the FAIL state doctor reports. This is the ~/bin/harness deployment the
    ticket exists to catch."""
    exe = _detached_copy(tmp_path)
    result = _run_exe(exe, tmp_path, tmp_path, STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339)
    calls = result.calls  # type: ignore[attr-defined]
    assert "HARNESS_WRAPPER_STATUS=detached" in calls, (
        f"a detached copy must forward the detached status:\n{calls}"
    )


def _copy_in_checkout(tmp_path: Path, *, drift: bool) -> Path:
    """A wrapper copied *into* a checkout's ``docker/`` dir (not a symlink). Its
    source root resolves to a directory that DOES contain a versioned
    ``harness-wrapper.sh``, so the status turns on ``cmp``: byte-identical →
    ``copy``, differing → ``drifted``. The invoked file is always the real
    wrapper (so it runs); only the versioned sibling is perturbed for the drift
    case, exercising the bash ``cmp -s`` / path-resolution logic itself."""
    docker_dir = tmp_path / "repo" / "docker"
    docker_dir.mkdir(parents=True, exist_ok=True)
    body = WRAPPER.read_bytes()
    # The versioned sibling the status compares against; a hair different for the
    # drift case so the invoked copy no longer matches it.
    (docker_dir / "harness-wrapper.sh").write_bytes(
        body + (b"\n# a change the on-PATH copy has not picked up\n" if drift else b"")
    )
    exe = docker_dir / "harness"
    exe.write_bytes(body)
    exe.chmod(0o755)
    return exe


def test_identical_copy_in_checkout_forwards_copy_status(tmp_path: Path) -> None:
    """A copy byte-identical to its versioned sibling forwards
    ``HARNESS_WRAPPER_STATUS=copy`` — the WARN state (not yet drifted, but it
    will). Exercises the wrapper's own ``cmp -s`` equal branch."""
    exe = _copy_in_checkout(tmp_path, drift=False)
    result = _run_exe(exe, tmp_path, tmp_path, STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339)
    calls = result.calls  # type: ignore[attr-defined]
    assert "HARNESS_WRAPPER_STATUS=copy" in calls, (
        f"a byte-identical copy must forward the copy status:\n{calls}"
    )


def test_drifted_copy_in_checkout_forwards_drifted_status(tmp_path: Path) -> None:
    """A copy whose content has fallen behind its versioned sibling forwards
    ``HARNESS_WRAPPER_STATUS=drifted`` — the FAIL state doctor reports, and the
    case AC-4 names. Exercises the wrapper's own ``cmp -s`` differing branch."""
    exe = _copy_in_checkout(tmp_path, drift=True)
    result = _run_exe(exe, tmp_path, tmp_path, STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339)
    calls = result.calls  # type: ignore[attr-defined]
    assert "HARNESS_WRAPPER_STATUS=drifted" in calls, (
        f"a drifted copy must forward the drifted status:\n{calls}"
    )


# ---------------------------------------------------------------------------
# The flag reaches the real `docker run` argv (#278)
# ---------------------------------------------------------------------------
#
# `tests/unit/test_container_hardening.py` locks PYTHONDONTWRITEBYTECODE=1 in the
# wrapper's *text*. That guard is satisfiable by a flag that never reaches the
# invocation — sitting in a dead branch, or lost to one of the array expansions
# on the `exec docker run` line. This module is the one that *executes* the real
# wrapper against stubs, so the argv proof belongs here alongside the other
# forwarded-env assertions.


def test_wrapper_passes_bytecode_suppression_on_the_docker_run_line(
    tmp_path: Path,
) -> None:
    """The pinned flag survives to the actual container invocation.

    Without it, Python in the container writes ``__pycache__`` carrying container
    paths into the mounted host tree, and the next host gate run false-reddens
    with ``OSError: could not get source code`` (#278).
    """
    result = _run_wrapper(tmp_path, STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339)
    calls = result.calls  # type: ignore[attr-defined]
    run_lines = [ln for ln in calls.splitlines() if ln.startswith("docker run")]
    assert run_lines, f"the wrapper never reached `docker run`:\n{calls}"
    for line in run_lines:
        assert "-e PYTHONDONTWRITEBYTECODE=1" in line, (
            "the docker run argv must pin PYTHONDONTWRITEBYTECODE=1 so the "
            f"container writes no bytecode into the mount (#278):\n{line}"
        )
