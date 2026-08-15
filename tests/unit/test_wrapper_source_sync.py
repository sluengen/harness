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

#: The line ``_checkout_behind_origin(docker_only_delta=True)`` adds to the
#: origin-side ``docker/Dockerfile``. Named once and substituted into the stub
#: below, so the fixture and the observation of it cannot drift apart.
_DOCKER_DELTA_MARKER = "RUN true"

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
  if grep -q '@DOCKER_DELTA_MARKER@' "$_ctx/docker/Dockerfile" 2>/dev/null; then
    echo "build-context-docker=advanced" >> "$STUB_LOG"
  else
    echo "build-context-docker=stale" >> "$STUB_LOG"
  fi
  exit "${STUB_BUILD_EXIT:-0}"
fi
exit 0
""".replace("@DOCKER_DELTA_MARKER@", _DOCKER_DELTA_MARKER)

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
        (other / "docker" / "Dockerfile").write_text(
            f"FROM scratch\n{_DOCKER_DELTA_MARKER}\n"
        )
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
    return _run_client(
        checkout / "docker" / "harness-wrapper.sh", checkout, tmp_path, **stub_env
    )


def _run_client(
    exe: Path, cwd: Path, tmp_path: Path, **stub_env: str
) -> subprocess.CompletedProcess[str]:
    """Run an arbitrary client ``exe`` from ``cwd``, with real git and the
    recording docker stub.

    Split out of ``_run_from_checkout`` so an **image-installed** client — which
    by construction lives outside the checkout it speaks for — can be run through
    the identical harness. One runner, so a difference between the two cases can
    only come from the client, never from how it was invoked.
    """
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
        [str(exe), "start", "CAL-1"],
        capture_output=True,
        text=True,
        cwd=cwd,
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


def test_a_docker_only_delta_rebuilds_the_image_from_the_advanced_tree(
    tmp_path: Path,
) -> None:
    """#286 left a ``docker/``-blind spot; #312 is the change that must close it.

    The freshness comparison used to key on ``harness/`` alone, so a delta
    touching only ``docker/`` advanced the checkout and left the image alone.
    That gap was a recorded decision until this ticket, and this ticket is the one
    it breaks: the image now *carries* the client (``harness-wrapper.sh`` and
    ``install-client.sh``), so a shim fix that never marks the image stale means
    ``install`` keeps emitting the old client. The delivery mechanism would fail
    to deliver itself.

    Asserting on the build context's **content**, per this module's standard: a
    rebuild issued off the un-advanced tree would satisfy "docker build was
    called" while shipping exactly the defect.
    """
    checkout = _checkout_behind_origin(tmp_path, docker_only_delta=True)
    result = _run_from_checkout(
        checkout, tmp_path, STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339
    )
    calls = result.calls  # type: ignore[attr-defined]

    assert "fast-forwarded" in result.stderr.lower(), (
        "the checkout must still advance — a docker/-only delta is how a client "
        f"fix propagates:\n{result.stderr}"
    )
    assert "docker build" in calls, (
        "a delta under docker/ must now mark the image stale: the image ships the "
        f"client, so a shim fix that skips the rebuild never reaches anyone:\n{calls}"
    )
    assert "build-context-docker=advanced" in calls, (
        "the rebuild must be off the fast-forwarded tree — rebuilding from the "
        f"pre-merge docker/ is the defect, not the fix:\n{calls}"
    )
    assert "docker run" in calls, f"the verb must still run:\n{calls}"
    assert result.returncode == 0


# The two rebuild triggers are separately load-bearing, and it took a mutation
# table to show it. Narrowing EITHER pathspec back to `harness/` alone left the
# docker-only test above green, because the other trigger still fired for that
# one shape. So each gets a case the other cannot answer — the #393 rule: when a
# mutation survives, find the input the two mechanisms treat differently rather
# than concluding one is redundant.


def test_a_docker_only_fast_forward_rebuilds_when_the_timestamp_cannot(
    tmp_path: Path,
) -> None:
    """Only the fast-forward trigger can fire here.

    The image is stamped after every commit in the repository, so the ``%ct``
    comparison is false by construction — the same construction
    ``test_the_fast_forward_alone_forces_the_rebuild`` uses for ``harness/``, and
    for the same reason: ``git log -1 --format=%ct`` is not monotonic across a
    fast-forward, so a merge can move the tree while the timestamp goes backwards.
    """
    checkout = _checkout_behind_origin(tmp_path, docker_only_delta=True)
    image_newer_than_every_commit = "2026-07-17T09:00:00.000000000Z"
    result = _run_from_checkout(
        checkout, tmp_path, STUB_IMAGE_CREATED=image_newer_than_every_commit
    )
    calls = result.calls  # type: ignore[attr-defined]

    assert "docker build" in calls, (
        "a fast-forward that moved docker/ must trigger the rebuild on its own; "
        "the timestamp comparison cannot be relied on across a merge, and the "
        f"image now ships the client:\n{calls}"
    )
    assert "build-context-docker=advanced" in calls, (
        f"and the rebuild must carry the advanced docker/ tree:\n{calls}"
    )


def test_a_docker_commit_already_in_the_checkout_marks_the_image_stale(
    tmp_path: Path,
) -> None:
    """Only the timestamp trigger can fire here.

    The checkout is already at origin's tip, so no fast-forward happens and the
    ``_ff_touched_sources`` flag stays 0. What remains is an image older than a
    ``docker/`` commit that is already present — the ordinary case of "someone
    pulled yesterday and never rebuilt", which is how a client fix goes stale in
    the image without anything moving.
    """
    checkout = _checkout_behind_origin(tmp_path, docker_only_delta=True)
    _git("pull", "--ff-only", "-q", cwd=checkout)
    head_before = _head(checkout)

    result = _run_from_checkout(
        checkout, tmp_path, STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339
    )
    calls = result.calls  # type: ignore[attr-defined]

    assert _head(checkout) == head_before, (
        "the fixture must not fast-forward here, or the other trigger answers "
        "this case and the test stops discriminating"
    )
    assert "fast-forwarded" not in result.stderr.lower(), result.stderr
    assert "docker build" in calls, (
        "a docker/ commit newer than the image must mark it stale even with "
        f"nothing to sync:\n{calls}"
    )


# ---------------------------------------------------------------------------
# The image-installed client (#312, AC-3-b)
# ---------------------------------------------------------------------------
#
# The single most expensive failure available in #312, and a silent one. An
# image-installed client at ~/bin/harness is outside every checkout, so without
# the root baked in at install time it resolves its source root to $HOME: the
# freshness guard disables itself, the sync becomes a no-op against a directory
# with no upstream, and the client degrades to PYTHONPATH=$HOME. Nothing reports
# any of that — the verb simply runs against whatever image happens to exist.
#
# Only a real repository can show the difference, which is why the test is here
# rather than beside the stub-driven freshness cases.

PRODUCER = WRAPPER.parent / "install-client.sh"


def _install_client(tmp_path: Path, *, source_root: Path) -> Path:
    """Install a real client, from the real producer, stamped for ``source_root``.

    Deliberately **outside** that checkout, at a path shaped like ``~/bin/harness``
    — the deployment the whole ticket is about.
    """
    produced = subprocess.run(
        [str(PRODUCER), "--source-root", str(source_root)],
        capture_output=True,
        check=True,
    )
    exe = tmp_path / "opt" / "harness"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(produced.stdout)
    exe.chmod(0o755)
    return exe


def test_an_image_installed_client_still_syncs_and_rebuilds_from_its_baked_root(
    tmp_path: Path,
) -> None:
    """AC-3-b: the migration is a lateral move, not a regression.

    The client is installed outside the checkout it speaks for and run from a
    third directory that is not a checkout either — so nothing about where it sits
    can tell it which tree to guard. Only the baked root can. Both guards must
    still fire: the checkout fast-forwards, and the image is rebuilt with origin's
    source in its context.
    """
    checkout = _checkout_behind_origin(tmp_path)
    exe = _install_client(tmp_path, source_root=checkout)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    head_before = _head(checkout)

    result = _run_client(
        exe, elsewhere, tmp_path, STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339
    )
    calls = result.calls  # type: ignore[attr-defined]

    assert "fast-forwarded" in result.stderr.lower(), (
        "the source sync did not reach the baked checkout — an installed client "
        f"that syncs nothing silently freezes the engine:\n{result.stderr}"
    )
    assert _head(checkout) != head_before, "the baked checkout did not advance"
    assert "docker build" in calls, (
        "the freshness guard is disarmed under an image install — this is the "
        f"silent failure the baked source root exists to prevent:\n{calls}"
    )
    assert "build-context-source=origin-tip-shipped" in calls, (
        f"the rebuild must carry origin's source, not a stale tree:\n{calls}"
    )
    assert "docker run" in calls, f"the verb must still run:\n{calls}"
    assert result.returncode == 0
    assert result.stdout.strip() == "", (
        f"the guard must not write to stdout (it carries JSON):\n{result.stdout}"
    )


def test_an_image_installed_client_ignores_an_ambient_source_root(
    tmp_path: Path,
) -> None:
    """The baked root is not an environment variable, and this is the difference.

    A client whose checkout could be redirected by whatever the calling shell
    exported would let any parent process choose which tree supplies its package
    and which tree gets rebuilt. Here a second, decoy checkout is exported through
    every plausible variable name; the client must still guard the one it was
    built for.
    """
    checkout = _checkout_behind_origin(tmp_path)
    exe = _install_client(tmp_path, source_root=checkout)

    decoy = tmp_path / "decoy"
    (decoy / "docker").mkdir(parents=True)
    decoy_head = _head(checkout)

    result = _run_client(
        exe,
        tmp_path,
        tmp_path,
        STUB_IMAGE_CREATED=IMAGE_INSTANT_RFC3339,
        HARNESS_SOURCE_ROOT=str(decoy),
    )
    calls = result.calls  # type: ignore[attr-defined]

    assert _head(checkout) != decoy_head, (
        "an ambient HARNESS_SOURCE_ROOT redirected the client away from the "
        "checkout it was installed for"
    )
    assert "build-context-source=origin-tip-shipped" in calls, (
        f"the rebuild was taken from the ambient root, not the baked one:\n{calls}"
    )


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
