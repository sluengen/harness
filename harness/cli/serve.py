"""``harness serve --local`` — run the host launcher control socket (CAL-579).

This is the thin, personal-machine form factor of the launcher described in
``specs/hermes-orchestration.md`` §Runtime topology: a single persistent host
process that listens on a unix domain socket and translates the narrow verb
operations into one-shot ``docker run`` sibling containers. It is **not** a
multi-tenant broker, and it is **not** the docker socket — it exposes only the
operations in :data:`harness.launcher.OPERATIONS`.

The launch logic lives in :mod:`harness.launcher`; this module is only the CLI
wiring (flags, default socket path, the blocking serve loop).

Exit codes (mirroring the other verbs):
* 0   — clean shutdown (SIGINT / Ctrl-C).
* 2   — invocation error (a mode other than ``--local`` was requested).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import typer

from harness.launcher import DEFAULT_IMAGE, ControlServer

__all__ = ["serve_command", "default_socket_path"]

#: Env var letting the operator override the control-socket path.
CONTROL_SOCKET_ENV = "HARNESS_CONTROL_SOCKET"


def default_socket_path(env: Mapping[str, str] | None = None) -> Path:
    """Resolve the default control-socket path.

    Precedence: explicit ``HARNESS_CONTROL_SOCKET`` → ``$XDG_RUNTIME_DIR/harness``
    (the standard per-user runtime dir, when present) → ``~/.harness``. Kept
    short because ``AF_UNIX`` bind paths are length-capped.
    """
    source = os.environ if env is None else env
    override = source.get(CONTROL_SOCKET_ENV, "").strip()
    if override:
        return Path(override)
    runtime_dir = source.get("XDG_RUNTIME_DIR", "").strip()
    base = Path(runtime_dir) if runtime_dir else Path.home() / ".harness"
    return base / "harness" / "control.sock" if runtime_dir else base / "control.sock"


def serve_command(
    local: bool = typer.Option(
        False,
        "--local",
        help="Run the personal-machine local launcher (the only supported mode).",
    ),
    socket: Path | None = typer.Option(
        None,
        "--socket",
        help="Control-socket path (default: $HARNESS_CONTROL_SOCKET / $XDG_RUNTIME_DIR / ~/.harness).",  # noqa: E501
    ),
    image: str | None = typer.Option(
        None,
        "--image",
        help=f"Verb image to launch (default: $HARNESS_IMAGE or {DEFAULT_IMAGE}).",
    ),
) -> None:
    """Serve the launcher control socket until interrupted.

    Only ``--local`` is supported: the single-machine launcher is a thin local
    helper, not the multi-tenant broker. Requesting any other mode is an
    invocation error (exit 2).
    """
    if not local:
        typer.echo(
            "harness serve currently supports only --local (the personal-machine launcher); "
            "pass --local to start it.",
            err=True,
        )
        raise typer.Exit(code=2)

    socket_path = socket if socket is not None else default_socket_path()
    resolved_image = image or os.environ.get("HARNESS_IMAGE") or DEFAULT_IMAGE

    server_config = ControlServer(image=resolved_image)
    server = server_config.create_server(socket_path)
    typer.echo(
        f"harness launcher listening on {socket_path} (image={resolved_image}); Ctrl-C to stop.",
        err=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("shutting down.", err=True)
    finally:
        server.server_close()
        if socket_path.exists() or socket_path.is_socket():
            socket_path.unlink()
