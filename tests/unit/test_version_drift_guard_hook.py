"""The session-start drift warning: a loaded plugin behind the published one says so (#723).

A cloud session runs whatever plugin version its environment snapshot holds,
and a local session keeps the version it loaded after an on-disk update. Nothing
told either one. ``hooks/version-drift-guard.js`` compares the loaded manifest
with the one published on the marketplace's default branch and, when the loaded
version is behind, hands the session both versions and the remedy.

**Admitted under ADR 0017 D5 class (a), behaviour of executable code.** Every
assertion runs the hook as a node subprocess against a real HTTP server on
loopback and reads the JSON it writes, so the network path under test is the
shipped one; only the URL is redirected, through the hook's own
``HARNESS_PUBLISHED_MANIFEST_URL``. The loaded version is a manifest written
beside a copy of the hook, which is where the hook reads it from when installed.

**The quiet cases are controls, not afterthoughts.** A hook that warned
unconditionally would pass every "behind" assertion, so equal, ahead, unreadable
and unreachable are each asserted to deliver no context at all.
"""

from __future__ import annotations

import http.server
import json
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.unit._prose import REPO_ROOT

HOOK = "version-drift-guard.js"
MANIFEST_PATH = "hooks/hooks.json"
URL_VAR = "HARNESS_PUBLISHED_MANIFEST_URL"
#: The hook's own bound on the published read, plus room for node to start.
TIMEOUT_BOUND_S = 3.0 + 2.5


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _plugin_root(tmp_path: Path, loaded: str) -> Path:
    """A plugin install: the real hook, its module-type pin, and a manifest."""
    root = tmp_path / "plugin"
    (root / "hooks").mkdir(parents=True)
    (root / ".claude-plugin").mkdir()
    for name in (HOOK, "package.json"):
        shutil.copy(REPO_ROOT / "hooks" / name, root / "hooks" / name)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "harness", "version": loaded}) + "\n", encoding="utf-8"
    )
    return root


class _Server:
    """A loopback server answering every GET with a fixed body, or never."""

    def __init__(self, body: bytes | None, status: int = 200) -> None:
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 — the stdlib's spelling
                outer.hits += 1
                if outer.body is None:
                    outer.release.wait(10)
                    return
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(outer.body)

            def log_message(self, *args: object) -> None:
                pass

        self.body = body
        self.status = status
        self.hits = 0
        self.release = threading.Event()
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/.claude-plugin/plugin.json"

    def close(self) -> None:
        self.release.set()
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def serve() -> Iterator[object]:
    servers: list[_Server] = []

    def start(body: bytes | None, status: int = 200) -> _Server:
        server = _Server(body, status)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


def _published(version: str) -> bytes:
    return json.dumps({"name": "harness", "version": version}).encode()


def _run(
    root: Path, url: str, payload: object | None = None
) -> tuple[subprocess.CompletedProcess[str], float]:
    stdin = json.dumps(
        payload
        if payload is not None
        else {"session_id": "s", "hook_event_name": "SessionStart", "source": "startup"}
    )
    started = time.monotonic()
    proc = subprocess.run(
        [_node(), str(root / "hooks" / HOOK)],
        input=stdin,
        text=True,
        capture_output=True,
        timeout=30,
        cwd=root,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", URL_VAR: url},
    )
    return proc, time.monotonic() - started


def _delivered(stdout: str) -> dict[str, object]:
    return json.loads(stdout) if stdout.strip() else {}


def _context(stdout: str) -> str:
    nested = _delivered(stdout).get("hookSpecificOutput") or {}
    assert isinstance(nested, dict)
    return str(nested.get("additionalContext") or "")


def _assert_quiet(proc: subprocess.CompletedProcess[str]) -> None:
    assert proc.returncode == 0, proc.stderr
    delivered = _delivered(proc.stdout)
    assert delivered == {"continue": True}, (
        f"expected the bare pass-through and no warning, got {proc.stdout!r}"
    )


# --- AC-1: behind warns, naming both versions and the remedy ------------------


def test_a_loaded_version_behind_the_published_one_is_delivered_to_the_session(
    tmp_path: Path, serve
) -> None:
    server = serve(_published("21.3.0"))
    proc, _ = _run(_plugin_root(tmp_path, "20.0.0"), server.url)
    assert proc.returncode == 0, proc.stderr
    delivered = _delivered(proc.stdout)
    nested = delivered.get("hookSpecificOutput")
    assert isinstance(nested, dict) and nested.get("hookEventName") == "SessionStart", (
        f"the warning is not in the SessionStart envelope the host reads: {proc.stdout!r}"
    )
    context = _context(proc.stdout)
    assert "20.0.0" in context and "21.3.0" in context, context
    assert "setup script" in context, (
        f"the context does not name the cloud remedy (edit the setup script): {context!r}"
    )
    assert server.hits == 1


def test_the_user_sees_a_line_as_well_as_the_model(tmp_path: Path, serve) -> None:
    server = serve(_published("21.3.0"))
    proc, _ = _run(_plugin_root(tmp_path, "21.2.9"), server.url)
    message = str(_delivered(proc.stdout).get("systemMessage") or "")
    assert "21.2.9" in message and "21.3.0" in message, proc.stdout


@pytest.mark.parametrize(
    ("loaded", "published"),
    [("1.9.9", "2.0.0"), ("2.0.9", "2.1.0"), ("2.1.0", "2.1.1"), ("9.0.0", "10.0.0")],
)
def test_behind_is_decided_numerically_per_part(
    loaded: str, published: str, tmp_path: Path, serve
) -> None:
    """``9.0.0`` < ``10.0.0``: a string comparison would read it the other way."""
    server = serve(_published(published))
    proc, _ = _run(_plugin_root(tmp_path, loaded), server.url)
    assert loaded in _context(proc.stdout), proc.stdout


# --- AC-2: equal (and ahead) say nothing -------------------------------------


@pytest.mark.parametrize(
    ("loaded", "published"),
    [("21.3.0", "21.3.0"), ("21.4.0", "21.3.0"), ("10.0.0", "9.9.9")],
)
def test_a_loaded_version_not_behind_says_nothing(
    loaded: str, published: str, tmp_path: Path, serve
) -> None:
    server = serve(_published(published))
    proc, _ = _run(_plugin_root(tmp_path, loaded), server.url)
    _assert_quiet(proc)
    assert server.hits == 1, "the control never reached the published read"


# --- AC-3: an unreadable published version is quiet and bounded --------------


def test_an_unreachable_host_is_quiet(tmp_path: Path) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    proc, _ = _run(_plugin_root(tmp_path, "1.0.0"), f"http://127.0.0.1:{port}/plugin.json")
    _assert_quiet(proc)


def test_a_host_that_never_answers_is_cut_off_by_the_timeout(tmp_path: Path, serve) -> None:
    server = serve(None)
    proc, elapsed = _run(_plugin_root(tmp_path, "1.0.0"), server.url)
    _assert_quiet(proc)
    assert server.hits == 1
    assert elapsed < TIMEOUT_BOUND_S, (
        f"the hook took {elapsed:.1f}s against a silent host; session start waits on it"
    )


@pytest.mark.parametrize(
    ("body", "status"),
    [
        (_published("99.0.0"), 404),
        (b"<html>not json</html>", 200),
        (json.dumps({"name": "harness"}).encode(), 200),
        (_published("not-a-version"), 200),
    ],
)
def test_an_unusable_published_answer_is_quiet(
    body: bytes, status: int, tmp_path: Path, serve
) -> None:
    server = serve(body, status)
    proc, _ = _run(_plugin_root(tmp_path, "1.0.0"), server.url)
    _assert_quiet(proc)
    assert server.hits == 1


def test_an_unreadable_loaded_version_is_quiet(tmp_path: Path, serve) -> None:
    server = serve(_published("99.0.0"))
    root = _plugin_root(tmp_path, "1.0.0")
    (root / ".claude-plugin" / "plugin.json").unlink()
    proc, _ = _run(root, server.url)
    _assert_quiet(proc)


def test_a_codex_session_hears_nothing_when_there_is_nothing_to_say(
    tmp_path: Path, serve
) -> None:
    """Codex's native empty answer is silence, as for the sibling advisories."""
    server = serve(_published("1.0.0"))
    proc, _ = _run(
        _plugin_root(tmp_path, "1.0.0"),
        server.url,
        {"session_id": "s", "turn_id": "t", "hook_event_name": "SessionStart"},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


# --- AC-4: registered under SessionStart --------------------------------------


def test_the_manifest_registers_the_hook_under_session_start() -> None:
    staged = subprocess.run(
        ["git", "show", f":{MANIFEST_PATH}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    groups = json.loads(staged)["hooks"].get("SessionStart") or []
    commands = [entry["command"] for group in groups for entry in group["hooks"]]
    assert f"node ${{CLAUDE_PLUGIN_ROOT}}/hooks/{HOOK}" in commands, commands
