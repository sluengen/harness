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


# ---------------------------------------------------------------------------
# The guard must measure the ref the loop actually ships to (#286)
# ---------------------------------------------------------------------------
#
# Every test above stubs ``git``, so ``_source_committed`` is whatever
# ``STUB_SOURCE_EPOCH`` says — which silently assumes the checkout tracks the ref
# the loop ships to. It does not. ``close`` merges and pushes ``origin/<base>`` in
# a throwaway worktree and never touches the main checkout (CAL-1154 Option 1),
# and ``start`` bases each worktree off ``origin/<base>``. Nothing advances
# ``refs/heads/<base>``, so once the operator stops pulling by hand,
# ``_source_committed`` is frozen and non-increasing and the guard can never fire
# again — failing open in exactly the scenario it was written for. Observed for
# real: the checkout sat 37 commits behind ``origin/dev`` and #278's shipped fix
# was not in effect on the machine running the loop.
#
# These tests therefore use a **real git repository** rather than a stub: a bare
# origin, a checkout deliberately behind it, and commit timestamps placed either
# side of the image's. Only a real repo can exercise the fetch/fast-forward the
# fix turns on, and only a real repo can be genuinely *diverged*.
#
# The docker stub records the **content of the build context** at ``docker build``
# time. That is what makes AC1 an assertion about the image rather than about the
# command: "a rebuild was issued" is satisfied by a rebuild off the stale tree,
# which is the bug. "The context held the newer source" is not.

_MARKER = "harness/marker.txt"

_DOCKER_STUB_RECORDING_CONTEXT = """#!/usr/bin/env bash
echo "docker $*" >> "$STUB_LOG"
if [[ "$1" == "image" && "$2" == "inspect" ]]; then
  if [[ -n "${STUB_IMAGE_CREATED:-}" ]]; then echo "$STUB_IMAGE_CREATED"; exit 0; fi
  exit 1
fi
if [[ "$1" == "build" ]]; then
  _ctx="${@: -1}"
  echo "build-context-source=$(cat "$_ctx/harness/marker.txt" 2>/dev/null || echo ABSENT)" \
    >> "$STUB_LOG"
  exit "${STUB_BUILD_EXIT:-0}"
fi
exit 0
"""

# The stale local commit sits an hour BEFORE the image, the origin-only commit an
# hour AFTER it. So the guard fires if and only if it is looking at origin's tip:
# against the local tip the image is newer and nothing is stale.
_STALE_COMMIT_EPOCH = IMAGE_INSTANT_EPOCH - ONE_HOUR
_ORIGIN_COMMIT_EPOCH = IMAGE_INSTANT_EPOCH + ONE_HOUR


def _git(*args: str, cwd: Path, epoch: int | None = None) -> None:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t"})
    env.update({"GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t"})
    if epoch is not None:
        env["GIT_AUTHOR_DATE"] = f"@{epoch}"
        env["GIT_COMMITTER_DATE"] = f"@{epoch}"
    subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    )


def _checkout_behind_origin(tmp_path: Path, *, diverged: bool = False) -> Path:
    """Build a real checkout that is behind ``origin/dev``, the way the operator
    machine is after a tick ships.

    The checkout carries a real copy of the wrapper under test at its versioned
    path, so the guard resolves this tree as its source root — the same resolution
    production uses, not a stub flag. ``diverged`` additionally lands a local-only
    commit, making the checkout ahead **and** behind, which is what a stray
    interactive commit on local ``dev`` produces and what ``--ff-only`` must refuse.
    """
    origin = tmp_path / "origin.git"
    origin.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", "--bare", "--initial-branch=dev", str(origin), cwd=tmp_path)

    checkout = tmp_path / "checkout"
    _git("clone", "-q", str(origin), str(checkout), cwd=tmp_path)

    (checkout / "harness").mkdir(parents=True, exist_ok=True)
    (checkout / "docker").mkdir(parents=True, exist_ok=True)
    (checkout / _MARKER).write_text("stale-local-tip\n")
    (checkout / "docker" / "Dockerfile").write_text("FROM scratch\n")
    _git("add", "-A", cwd=checkout)
    _git("commit", "-qm", "stale tip", cwd=checkout, epoch=_STALE_COMMIT_EPOCH)

    # The wrapper under test is placed UNTRACKED, so it resolves this clone as its
    # source root while no fast-forward can swap the script out from under the
    # running process.
    wrapper_copy = checkout / "docker" / "harness-wrapper.sh"
    wrapper_copy.write_bytes(WRAPPER.read_bytes())
    wrapper_copy.chmod(0o755)
    _git("push", "-q", "origin", "HEAD:refs/heads/dev", cwd=checkout)
    _git("branch", "-q", "--set-upstream-to=origin/dev", cwd=checkout)

    # Advance origin from a second clone: this is the merge a `close` pushes, which
    # the main checkout never sees.
    other = tmp_path / "other"
    _git("clone", "-q", str(origin), str(other), cwd=tmp_path)
    (other / _MARKER).write_text("origin-tip-shipped\n")
    _git("add", "-A", cwd=other)
    _git("commit", "-qm", "shipped", cwd=other, epoch=_ORIGIN_COMMIT_EPOCH)
    _git("push", "-q", "origin", "HEAD:refs/heads/dev", cwd=other)

    if diverged:
        (checkout / "local-only.txt").write_text("a stray interactive commit\n")
        _git("add", "-A", cwd=checkout)
        _git("commit", "-qm", "local only", cwd=checkout, epoch=_STALE_COMMIT_EPOCH)

    return checkout


def _head(checkout: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _run_from_checkout(
    checkout: Path, tmp_path: Path, **stub_env: str
) -> subprocess.CompletedProcess[str]:
    """Run the checkout's own copy of the wrapper with **real git** and a docker
    stub that records its build context."""
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir(parents=True, exist_ok=True)
    docker = stub_bin / "docker"
    docker.write_text(_DOCKER_STUB_RECORDING_CONTEXT)
    docker.chmod(0o755)

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
        [str(checkout / "docker" / "harness-wrapper.sh"), "start", "CAL-1"],
        capture_output=True,
        text=True,
        cwd=checkout,
        env=env,
    )
    result.calls = log.read_text()  # type: ignore[attr-defined]
    return result


def test_a_checkout_behind_origin_runs_an_engine_built_from_origins_tip(
    tmp_path: Path,
) -> None:
    """AC1: the engine a tick runs is built from the tip the loop ships to.

    The local tip is older than the image and origin's tip is newer, so a guard
    reading ``refs/heads/dev`` sees nothing stale and runs on. Asserting on the
    **build context's content** is what makes this a claim about the image: a
    rebuild off the stale tree would satisfy "docker build was called" while
    shipping exactly the defect.
    """
    checkout = _checkout_behind_origin(tmp_path)
    result = _run_from_checkout(
        checkout, tmp_path, STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339
    )
    calls = result.calls  # type: ignore[attr-defined]

    assert "docker build" in calls, (
        "a checkout behind origin must not run an engine compiled from the stale "
        f"tip — the guard has to consult the ref the loop ships to:\n{calls}"
    )
    assert "build-context-source=origin-tip-shipped" in calls, (
        "the rebuilt image must contain origin's source, not the stale local tree; "
        f"rebuilding off the stale tip is the defect, not the fix:\n{calls}"
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "", (
        f"the guard must not write to stdout (it carries JSON):\n{result.stdout}"
    )


def test_the_fast_forward_alone_forces_the_rebuild(tmp_path: Path) -> None:
    """AC1 must not rest on ``%ct`` ordering, because that ordering is not
    guaranteed.

    ``git log -1 --format=%ct -- harness/`` is **not monotonic across a
    fast-forward**: history simplification resolves a merge to the feature
    commit's own committer date, which can predate the image. So advancing the
    checkout is not by itself enough — the timestamp comparison can stay false
    while the tree really did move, silently reinstating the stale engine.

    Here the image is stamped *after* every commit in the repository, so the
    timestamp comparison is false by construction. Only the fast-forward having
    touched ``harness/`` can trigger the rebuild.
    """
    checkout = _checkout_behind_origin(tmp_path)
    # Newer than _ORIGIN_COMMIT_EPOCH, so `_source_committed -gt _image_epoch`
    # cannot be what fires.
    image_newer_than_every_commit = "2026-07-17T09:00:00.000000000Z"
    result = _run_from_checkout(
        checkout, tmp_path, STUB_IMAGE_CREATED=image_newer_than_every_commit
    )
    calls = result.calls  # type: ignore[attr-defined]

    assert "docker build" in calls, (
        "a fast-forward that moved harness/ must trigger the rebuild on its own; "
        "relying on the commit timestamp being newer than the image leaves the "
        f"merge case silently stale:\n{calls}"
    )
    assert "build-context-source=origin-tip-shipped" in calls, (
        f"and the rebuilt image must still contain origin's source:\n{calls}"
    )


def test_a_diverged_checkout_warns_visibly_and_does_not_run_a_stale_image(
    tmp_path: Path,
) -> None:
    """AC2: divergence is surfaced, not absorbed.

    A stray local commit makes the checkout ahead **and** behind, which no
    fast-forward can heal. The loop cannot repair that itself, so the one thing it
    must not do is proceed silently — a silent stale engine is the failure mode
    the whole ticket is about. It warns and still runs the verb: wedging the queue
    every hour until a human intervenes trades one failure for a worse one.
    """
    checkout = _checkout_behind_origin(tmp_path, diverged=True)
    head_before = _head(checkout)
    result = _run_from_checkout(
        checkout, tmp_path, STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339
    )

    assert result.stderr.strip(), (
        "a diverged checkout must not be silent — the operator has to learn the "
        "engine may not match what shipped"
    )
    err = result.stderr.lower()
    assert "diverged" in err, (
        "the warning must name the divergence as the cause, so the remedy (rebase "
        f"or drop the local commit) is derivable from it:\n{result.stderr}"
    )
    assert "1 ahead" in err and "1 behind" in err, (
        "both counts belong in the message: which side is which is exactly what "
        f"tells the operator whether they have unpushed work:\n{result.stderr}"
    )
    assert _head(checkout) == head_before, (
        "divergence is reported, never repaired — the operator's local commit "
        "must survive untouched"
    )
    assert result.returncode == 0, (
        "a diverged checkout must not wedge the queue — warn and continue"
    )
    assert result.stdout.strip() == "", (
        f"the warning must not write to stdout (it carries JSON):\n{result.stdout}"
    )


def test_an_up_to_date_checkout_is_left_alone(tmp_path: Path) -> None:
    """AC3: no false positives. A checkout already at origin's tip, with an image
    newer than it, must produce no warning and no rebuild — otherwise the fix
    trades a silent stale image for a rebuild on every single verb invocation."""
    checkout = _checkout_behind_origin(tmp_path)
    _git("pull", "--ff-only", "-q", cwd=checkout)
    # Image newer than origin's tip: nothing is stale by any reading.
    fresh_image = "2026-07-17T08:00:00.000000000Z"  # IMAGE_INSTANT + 2h
    result = _run_from_checkout(checkout, tmp_path, STUB_IMAGE_CREATED=fresh_image)
    calls = result.calls  # type: ignore[attr-defined]

    assert "docker build" not in calls, (
        f"an up-to-date checkout with a current image must not rebuild:\n{calls}"
    )
    assert "docker run" in calls, f"the verb must still run:\n{calls}"
    assert "stale" not in result.stderr.lower(), (
        f"nothing is stale here — no warning:\n{result.stderr}"
    )
    assert result.returncode == 0


def test_an_overridden_image_never_touches_the_operators_checkout(
    tmp_path: Path,
) -> None:
    """A pinned ``HARNESS_IMAGE`` is the caller's to manage, and the sync is a
    write to the operator's tree. Mutating it to freshen a build that will not
    happen is a side effect with no benefit — so the override must suppress the
    sync, not merely the rebuild."""
    checkout = _checkout_behind_origin(tmp_path)
    head_before = _head(checkout)
    result = _run_from_checkout(
        checkout,
        tmp_path,
        HARNESS_IMAGE="harness:pinned",
        STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339,
    )
    calls = result.calls  # type: ignore[attr-defined]

    assert _head(checkout) == head_before, (
        "an overridden image tag must leave the operator's checkout exactly as it "
        "was — the guard is opted out of wholesale, writes included"
    )
    assert "docker build" not in calls, (
        f"an overridden image tag must not be rebuilt:\n{calls}"
    )
    assert result.returncode == 0


def test_an_unreachable_remote_warns_and_still_runs_the_verb(
    tmp_path: Path,
) -> None:
    """The loop is unattended: a fetch that cannot reach its remote must degrade,
    not wedge. It proceeds against the last-known remote-tracking ref and says so,
    because a silent failure here is indistinguishable from a healthy sync and
    would put the engine right back out of step with what shipped."""
    checkout = _checkout_behind_origin(tmp_path)
    _git("remote", "set-url", "origin", str(tmp_path / "no-such-repo.git"), cwd=checkout)
    result = _run_from_checkout(
        checkout, tmp_path, STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339
    )
    calls = result.calls  # type: ignore[attr-defined]

    assert "docker run" in calls, (
        f"an unreachable remote must not stop the verb from running:\n{calls}"
    )
    assert result.returncode == 0, "an unreachable remote must not wedge the queue"
    assert "could not fetch" in result.stderr.lower(), (
        f"the degraded fetch must be visible, not silent:\n{result.stderr}"
    )
    assert result.stdout.strip() == "", (
        f"the warning must not write to stdout (it carries JSON):\n{result.stdout}"
    )
