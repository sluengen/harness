"""Tests for ``harness serve`` — the launcher CLI wiring (CAL-579).

The launch logic itself is covered in ``test_launcher.py`` /
``test_launcher_socket.py``; here we cover only the CLI surface: the ``--local``
requirement, the default socket-path resolution, and that the command is
registered on the app.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from harness.cli import app
from harness.cli.serve import CONTROL_SOCKET_ENV, default_socket_path

cli_runner = CliRunner()


def test_serve_requires_local_mode() -> None:
    # Without --local the command refuses with exit code 2 (invocation error).
    result = cli_runner.invoke(app, ["serve"])
    assert result.exit_code == 2
    assert "--local" in result.output


def test_serve_is_registered_on_the_app() -> None:
    result = cli_runner.invoke(app, ["--help"])
    assert "serve" in result.output


# ---------------------------------------------------------------------------
# default_socket_path — precedence
# ---------------------------------------------------------------------------


def test_explicit_override_wins() -> None:
    env = {CONTROL_SOCKET_ENV: "/tmp/custom.sock", "XDG_RUNTIME_DIR": "/run/user/1000"}
    assert default_socket_path(env) == Path("/tmp/custom.sock")


def test_xdg_runtime_dir_used_when_set() -> None:
    env = {"XDG_RUNTIME_DIR": "/run/user/1000"}
    assert default_socket_path(env) == Path("/run/user/1000/harness/control.sock")


def test_falls_back_to_home_harness(monkeypatch: object) -> None:
    # No override, no XDG_RUNTIME_DIR → ~/.harness/control.sock.
    path = default_socket_path({})
    assert path == Path.home() / ".harness" / "control.sock"
