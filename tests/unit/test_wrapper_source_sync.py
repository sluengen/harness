"""The staleness guard must measure the ref the loop actually ships to (#286).

``tests/unit/test_wrapper_image_staleness.py`` covers the freshness *comparison*
— given a source tip and an image, does the wrapper rebuild? This module covers
the question one level down, which that one cannot ask: **is the source tip it
measures the right one?**

It is not, by default. ``close`` merges and pushes ``origin/<base>`` from a
throwaway worktree and never touches the main checkout (CAL-1154 Option 1), and
``start`` bases each worktree off ``origin/<base>``. Nothing advances
``refs/heads/<base>`` — the ref the guard reads. So once the operator stops
pulling by hand, the measured value is frozen and non-increasing and the guard
can never fire again, failing open in exactly the scenario it was written for.
Observed: the checkout sat 37 commits behind ``origin/dev`` and #278's shipped,
reviewed, closed fix was not in effect on the machine running the loop, with no
signal of any kind.

**Why this is a separate module, and not more cases in the freshness one.** These
tests need a **real git repository** — a bare origin, a clone deliberately behind
it, real divergence. The freshness module stubs ``git`` wholesale, and that stub
is what makes its cases cheap and hermetic; a real repo cannot be expressed
through it, and mixing the two regimes in one file makes each test's fixture
ambiguous at a glance. Only a real repo can exercise a fetch and a fast-forward,
and only a real repo can be genuinely diverged rather than merely reported so.

The docker stub still stands in for the image, and records the **content of its
build context** at ``docker build`` time. That is what makes the acceptance
criterion measurable without a 165s build: *the image contains the newer source*
decomposes exactly into *the directory handed to ``docker build`` held the newer
source at build time*. Asserting merely that a rebuild was issued would be
satisfied by a rebuild off the stale tree — which is the defect, not the fix.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.unit.test_wrapper_image_staleness import (
    IMAGE_INSTANT_EPOCH,
    IMAGE_INSTANT_RFC3339,
    ONE_HOUR,
    WRAPPER,
)

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


def _checkout_behind_origin(
    tmp_path: Path, *, diverged: bool = False, docker_only_delta: bool = False
) -> Path:
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
    if docker_only_delta:
        # A change under docker/ never moves `git log -1 -- harness/`, so it can
        # never trigger the freshness rebuild. That blind spot is out of scope
        # here; the fixture exists so a test can pin it as deliberate.
        (other / "docker" / "Dockerfile").write_text("FROM scratch\nRUN true\n")
    else:
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


def test_a_dirty_tree_blocking_the_fast_forward_warns_and_continues(
    tmp_path: Path,
) -> None:
    """Uncommitted operator work outranks the sync.

    A fast-forward that would overwrite a modified file is refused by git itself.
    The wrapper must take that refusal as final — the operator's unsaved edits are
    worth more than a fresh image — say so, and still run the verb. Silently
    losing the edits would be far worse than the staleness being guarded against,
    and wedging the queue would be worse than both.
    """
    checkout = _checkout_behind_origin(tmp_path)
    # Dirty exactly the file origin advanced, so the fast-forward cannot apply.
    (checkout / _MARKER).write_text("operator's uncommitted work\n")
    head_before = _head(checkout)

    result = _run_from_checkout(
        checkout, tmp_path, STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339
    )
    calls = result.calls  # type: ignore[attr-defined]

    assert (checkout / _MARKER).read_text() == "operator's uncommitted work\n", (
        "the operator's uncommitted edit must survive — the sync may never "
        "discard local work to freshen an image"
    )
    assert _head(checkout) == head_before, "a refused fast-forward moves nothing"
    assert "could not fast-forward" in result.stderr.lower(), (
        f"a refused fast-forward must be visible, not silent:\n{result.stderr}"
    )
    assert "docker run" in calls, f"the verb must still run:\n{calls}"
    assert result.returncode == 0, "a refused fast-forward must not wedge the queue"


def test_a_docker_only_delta_fast_forwards_without_rebuilding(
    tmp_path: Path,
) -> None:
    """The ``docker/``-only blind spot is deliberate here, not accidental.

    The freshness comparison keys on ``harness/``, so a delta touching only
    ``docker/`` moves the checkout without triggering a rebuild. That gap is real
    and explicitly out of scope for #286 — this test pins the current behaviour so
    the gap stays a recorded decision, and so whoever closes it has to change a
    test that says what it is changing.

    What #286 *does* owe this case is the fast-forward itself: the checkout must
    still advance, because the wrapper script lives under ``docker/`` and that is
    precisely how a wrapper fix reaches the next invocation.
    """
    checkout = _checkout_behind_origin(tmp_path, docker_only_delta=True)
    result = _run_from_checkout(
        checkout, tmp_path, STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339
    )
    calls = result.calls  # type: ignore[attr-defined]

    assert "fast-forwarded" in result.stderr.lower(), (
        "the checkout must still advance — a docker/-only delta is how a wrapper "
        f"fix propagates:\n{result.stderr}"
    )
    assert "docker build" not in calls, (
        "a delta that never touched harness/ does not trigger the freshness "
        f"rebuild; that blind spot is out of scope for #286:\n{calls}"
    )
    assert "docker run" in calls, f"the verb must still run:\n{calls}"
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
