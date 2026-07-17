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
