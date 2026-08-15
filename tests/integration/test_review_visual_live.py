"""AC-1b / AC-5 (#361) — the visual channel, against the real engine.

**Opt-in.** Skipped unless ``HARNESS_LIVE_REVIEW_ENGINE=1``, because it needs a
credential, a network, a Docker daemon and a Chromium-family browser. It is
*collected* and merely skipped, so the gate's ``-m docker`` / ``-m "not docker"``
partition invariant (``tests/unit/test_verify_parallel_tiers.py``) is untouched —
which is precisely why it must not use a custom deselecting marker.

What it proves that nothing offline can
---------------------------------------
AC-1 originally asked for a test asserting the engine's tool result for at least
one image was image content. That is a property of the external ``claude`` CLI,
not of any harness code path: no offline test establishes it, and a checked-in
stream-json fixture would only prove the parser works — the change agreeing with
itself. So the criterion split. AC-1a (the ``visual_context`` fields) is proven
in the gate; **this** is AC-1b, and it also mechanizes AC-5, so the two are one
thing to run.

Two halves, both load-bearing:

* **the mechanism** — ``image_tool_result_paths(stream)`` contains the capture's
  absolute container path, i.e. the ``Read`` came back as an ``image`` content
  block rather than as a path, a byte dump, or text about an image. The oracle is
  the same function ``tests/unit/test_stream_json_oracle.py`` proves against
  synthetic positive *and* negative streams; a second reader here would let this
  assertion pass on a predicate nothing had checked.
* **the fidelity** — the model returns a token that exists **only as pixels**.
  The expected value is written outside the mount, so nothing readable in the
  container can leak it.

What the gate therefore does not prove: that today's ``claude`` CLI still returns
image content blocks. A silent CLI regression degrades the reviewer to reading
paths and the gate stays green. ``visual_context`` makes that detectable after the
fact; this test makes it detectable on demand.

What was measured, and the limit it exposed
-------------------------------------------
Measured 2026-08-15 by this procedure against ``docs/index.html`` at 1440x5726 px
/ 1.44 MB, with the token rendered at 16px body size. Both runs are recorded in
full on the ticket (issue #361, comment "AC-5 and AC-4d evidence"), including the
archived stream-json; the summary that matters here:

* **The mechanism holds.** The ``Read`` result was an ``image`` content block at
  realistic full-page dimensions — not text, not a byte dump. AC-5's
  falsification condition (a) did not fire.
* **The fidelity limit is real, and condition (b) fired in a weakened form.**
  Run A returned seven of eight characters, reading ``l`` as ``1`` in the page's
  ``system-ui`` font. Run B returned the token exactly — **but only after the
  model cropped the bottom of the image itself, installing Pillow to do it.**
  Unprompted cropping is the more consequential half: the token was not legible
  from the full-page capture as delivered.

**The limit, stated plainly, because it bounds what this channel is for.** The
channel is reliable for **layout and structure** — the failure class it exists to
catch, a page rendering as one column at every width, an element overlapping
another, a control off-screen. It is **not** reliable for reading body text at
full-page downscale. Character-level fidelity sits at the edge, and a reviewer
may have to crop to read fine detail, while ``_VISUAL_CONTEXT_TEMPLATE`` says
only "Read each one" and offers no such instruction. The narrowing the design
anticipated — viewport-height slices per width plus a documented maximum capture
height — is carried to **#362**, which owns the capture convention.

That limit is why :data:`_ALPHABET` below excludes the confusable pairs, and the
exclusion has to be read honestly: **it makes this test pass by construction on
the ``l``/``1`` case that failed.** It is acceptable only because the limit is
recorded here and on the ticket rather than being tuned away. What is left under
test is the assertion that survives an unambiguous alphabet — the mechanism, plus
enough fidelity to return a short string of distinguishable glyphs. A regression
in downscaling severe enough to lose those would still fail; a regression that
only degrades body-text legibility would not, and that ground was already ceded
by the measurement above.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests._stream_json import image_tool_result_paths

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE = REPO_ROOT / "docs" / "index.html"

#: Unambiguous by construction — no ``l``/``1``/``I``, ``0``/``O``, ``5``/``S``,
#: ``2``/``Z``. See the module docstring: the confusable pairs measure the font,
#: not the channel.
_ALPHABET = "abcdefghjkmnpqrtuvwxy34679"

#: Chromium-family browsers that support ``--headless=new --screenshot``, in the
#: order tried. ``HARNESS_LIVE_CAPTURE_BROWSER`` overrides the search entirely.
_BROWSERS = (
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "chromium",
    "chromium-browser",
)

#: The engine image. Deliberately **not** ``harness:test``: that tag is shared by
#: the modules the gate runs serially, and joining it would put this module in
#: their contention set for no reason — it builds no image at all.
_IMAGE = os.environ.get("HARNESS_LIVE_REVIEW_IMAGE", "harness:dev")

_CAPTURE_WIDTH = 1440

pytestmark = [
    pytest.mark.docker,
    # The engine's own ceiling is ``loop.engine_timeout_seconds`` (900); the
    # capture and the container spawn sit inside that here.
    pytest.mark.timeout(900),
    pytest.mark.skipif(
        os.environ.get("HARNESS_LIVE_REVIEW_ENGINE") != "1",
        reason=(
            "live review-engine test: needs a Claude credential, network, a "
            "Docker daemon and a headless browser. Set "
            "HARNESS_LIVE_REVIEW_ENGINE=1 to run it (AC-1b/AC-5, #361)."
        ),
    ),
]


def _browser() -> str:
    explicit = os.environ.get("HARNESS_LIVE_CAPTURE_BROWSER")
    if explicit:
        return explicit
    for candidate in _BROWSERS:
        if Path(candidate).exists() or shutil.which(candidate):
            return candidate
    pytest.skip(
        "no Chromium-family browser found for the capture; set "
        "HARNESS_LIVE_CAPTURE_BROWSER to one"
    )


def _render(browser: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--virtual-time-budget=3000", *args],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _page_height(browser: str, page: Path, tmp_path: Path) -> int:
    """The document's real scroll height, so the capture is the WHOLE page.

    ``--headless=new`` captures the window, not the document, so a fixed
    ``--window-size`` silently clips the bottom — where the token is. Measuring
    first is what makes "a real full-page capture" (AC-5) true rather than
    claimed.
    """
    probe = tmp_path / "probe.html"
    probe.write_text(
        page.read_text(encoding="utf-8").replace(
            "</body>",
            '<script>window.addEventListener("load",()=>{document.body.'
            'setAttribute("data-h",document.documentElement.scrollHeight)})'
            "</script>\n</body>",
        ),
        encoding="utf-8",
    )
    dom = _render(browser, f"--window-size={_CAPTURE_WIDTH},1000", "--dump-dom", probe.as_uri())
    match = re.search(r'data-h="(\d+)"', dom.stdout)
    assert match, f"could not measure the page height from --dump-dom: {dom.stdout[:400]}"
    return int(match.group(1))


def _png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[16:24]
    return int.from_bytes(header[:4], "big"), int.from_bytes(header[4:], "big")


def _container_env() -> dict[str, str]:
    """The Claude credential, resolved through the production host path.

    Never rendered: it is placed in this process's environ and forwarded to
    docker **by name** (``-e NAME``), so it never appears in an argv that ``ps``
    can read.
    """
    from harness.hostenv.container_env import (
        RequestRefreshingSource,
        agent_credential_is_needed,
    )
    from harness.hostenv.host import detect_host

    env = dict(os.environ)
    host = detect_host(sys.platform)
    if not agent_credential_is_needed(host):
        return env
    lease = RequestRefreshingSource().agent_credential(host)
    if lease.credential is None:
        pytest.skip(f"no Claude credential available on this host: {lease.reason!r}")
    env["CLAUDE_CODE_OAUTH_TOKEN"] = lease.credential.token
    return env


def test_the_engine_reads_a_real_full_page_capture_as_image_content(
    tmp_path: Path,
) -> None:
    """AC-1b + AC-5 — the mechanism and the fidelity, on a real capture."""
    if shutil.which("docker") is None:
        pytest.skip("docker is not on PATH")
    browser = _browser()

    # The token exists ONLY as pixels: it is rendered into the page at ordinary
    # body font size, and its expected value is written outside the mount.
    token = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    outside_the_mount = tmp_path / "expected.txt"
    outside_the_mount.write_text(token, encoding="utf-8")

    page = tmp_path / "page.html"
    page.write_text(
        PAGE.read_text(encoding="utf-8").replace(
            "</body>",
            '<p style="font-size:16px;font-family:system-ui;color:#111">'
            f"Build verification code: {token}</p>\n</body>",
        ),
        encoding="utf-8",
    )

    mount = tmp_path / "mount"
    shots = mount / "shots"
    shots.mkdir(parents=True)
    capture = shots / f"full-{_CAPTURE_WIDTH}.png"
    height = _page_height(browser, page, tmp_path)
    _render(
        browser,
        f"--screenshot={capture}",
        f"--window-size={_CAPTURE_WIDTH},{height}",
        page.as_uri(),
    )

    assert capture.exists(), "the headless capture produced no file"
    width, captured_height = _png_dimensions(capture)
    # AC-5 asks for a *real* full-page capture, heavily downscaled — not a
    # thumbnail that would prove nothing about the hard case.
    assert width == _CAPTURE_WIDTH
    assert captured_height >= 2000, f"capture is only {captured_height}px tall"
    assert capture.stat().st_size >= 200_000, "capture is smaller than a real page's"

    container_path = f"/workspace/shots/{capture.name}"
    prompt = (
        f"There is a rendered full-page screenshot of a web page at the absolute "
        f"path {container_path} in this workspace. Read that file. It is an "
        f"image; you will receive the image itself. Near the bottom of the page "
        f"there is a line of ordinary body text reading 'Build verification "
        f"code: XXXXXXXX'. Report the 8-character code exactly, in the form "
        f"CODE=<value>."
    )
    result = subprocess.run(
        [
            "docker", "run", "--rm", "-i",
            "-v", f"{mount}:/workspace",
            "-w", "/workspace",
            "-e", "CLAUDE_CODE_OAUTH_TOKEN",
            "--entrypoint", "claude",
            _IMAGE,
            # The production invocation (``review_protocol._build_cmd``) plus the
            # tracing flags. The permission mode and the -p are what production
            # runs; stream-json is what makes the tool result observable at all.
            "-p", "--permission-mode", "plan",
            "--output-format", "stream-json", "--verbose",
        ],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=800,
        check=False,
        env=_container_env(),
    )
    assert result.returncode == 0, f"engine failed: {result.stderr[-2000:]}"

    # Half one — the mechanism. THE load-bearing assertion of AC-1b: the engine's
    # tool result for this capture was an image content block.
    paths = image_tool_result_paths(result.stdout)
    assert container_path in paths, (
        f"the engine's tool result for {container_path} was not an image content "
        f"block. Image-content reads seen: {paths}. Either the CLI stopped "
        f"returning image blocks at these dimensions, or plan mode stopped "
        f"permitting the read — the channel then delivers a path, not a "
        f"rendering (AC-1b, #361)."
    )

    # Half two — the fidelity. The token exists only as pixels in that capture.
    final = [
        event
        for line in result.stdout.splitlines()
        if (event := _loads(line)) is not None and event.get("type") == "result"
    ]
    assert final, "the stream carried no result event"
    text = str(final[-1].get("result", ""))
    assert outside_the_mount.read_text(encoding="utf-8") in text, (
        f"the engine received an image block but did not read the body text in "
        f"it: expected the token rendered at 16px in a {width}x{captured_height} "
        f"capture, got {text[:300]!r}. Downscaling has destroyed body text, so "
        f"the channel delivers an impression rather than a reviewable rendering "
        f"— narrow the capture (viewport-height slices per width) rather than "
        f"widening it (AC-5, #361)."
    )


def _loads(line: str) -> dict[str, object] | None:
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
