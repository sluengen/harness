"""Launcher-socket client — the agent runtime's handle to the verbs (CAL-585).

The per-session agent runtime (``claude -p "/harness run <ticket>"``) holds the
**launcher control socket**, never ``/var/run/docker.sock`` (decision #1,
``specs/hermes-orchestration.md`` §Runtime topology). So inside that container
``harness <verb> …`` must **not** ``docker run`` a sibling itself — it has no
docker authority. This module is the thin client that turns a verb CLI
invocation into one control-socket request: the launcher constructs and runs the
one-shot sibling container server-side and streams back the verb's stdout + exit
code.

It is the agent-side counterpart to :mod:`harness.launcher` (the server). The
agent-mode entrypoint (``docker/entrypoint.sh``) puts a ``harness`` shim on
``PATH`` that runs ``python -m harness.launcher_client``, so the unchanged
``/harness run`` loop — which shells out to ``harness start`` / ``review`` /
``close`` / ``status`` / ``events`` — transparently routes every verb through
the socket. The verb's JSON stdout crosses back verbatim, so the loop parses it
exactly as if it had run the verb locally.

Only the verbs the loop actually issues are mapped; anything else exits 2 rather
than silently doing nothing. The client never invents docker options — it sends
``{"op", "params"}`` and the launcher decides the mount/image/privilege/env.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from harness.cli.serve import default_socket_path

__all__ = [
    "UnsupportedVerb",
    "LauncherClientError",
    "verb_argv_to_request",
    "LauncherClient",
    "main",
]

#: Value-taking options the client understands (``--opt value``); every other
#: ``--flag`` is treated as a boolean and dropped. ``--repo`` / ``--db`` are
#: dropped deliberately: in the agent runtime the repo is the mounted workspace
#: (CWD), and the launcher sets ``--repo`` / the ledger path server-side.
_VALUE_OPTIONS: frozenset[str] = frozenset({"run-id", "base", "repo", "db"})


class UnsupportedVerb(Exception):  # noqa: N818 - reads as a condition, not an *Error
    """A verb outside the loop's surface was sent to the socket client."""


class LauncherClientError(Exception):
    """The launcher refused the request or the socket could not be reached."""


def _split_args(rest: Sequence[str]) -> tuple[dict[str, str], list[str]]:
    """Split ``rest`` into ``(options, positionals)``.

    ``--opt value`` pairs (for options in :data:`_VALUE_OPTIONS`) become entries
    in ``options`` keyed without the leading ``--``; bare ``--flag`` tokens are
    dropped; everything else is a positional.
    """
    options: dict[str, str] = {}
    positionals: list[str] = []
    i = 0
    while i < len(rest):
        token = rest[i]
        if token.startswith("--"):
            key = token[2:]
            if key in _VALUE_OPTIONS and i + 1 < len(rest):
                options[key] = rest[i + 1]
                i += 2
                continue
            # Boolean flag (e.g. --json / --no-json) — irrelevant to the request.
            i += 1
            continue
        positionals.append(token)
        i += 1
    return options, positionals


def verb_argv_to_request(argv: Sequence[str], *, repo: str) -> dict[str, Any]:
    """Map a harness verb CLI ``argv`` to a launcher ``{"op", "params"}`` request.

    ``repo`` is the workspace path the launcher mounts (the agent's CWD). Raises
    :class:`UnsupportedVerb` for any verb the agent loop does not issue.
    """
    if not argv:
        raise UnsupportedVerb("no verb given")
    verb, *rest = argv
    options, positionals = _split_args(rest)

    def _need_pos(index: int, what: str) -> str:
        if index >= len(positionals):
            raise UnsupportedVerb(f"{verb}: missing {what}")
        return positionals[index]

    def _need_opt(key: str) -> str:
        if key not in options:
            raise UnsupportedVerb(f"{verb}: missing --{key}")
        return options[key]

    if verb == "start":
        params: dict[str, str] = {"repo": repo, "ticket": _need_pos(0, "ticket")}
        if "base" in options:
            params["base"] = options["base"]
        return {"op": "start", "params": params}
    if verb == "review":
        return {"op": "review", "params": {"repo": repo, "run_id": _need_opt("run-id")}}
    if verb == "close":
        return {
            "op": "close",
            "params": {
                "repo": repo,
                "run_id": _need_opt("run-id"),
                "ticket": _need_pos(0, "ticket"),
            },
        }
    if verb in ("status", "events", "cancel"):
        return {"op": verb, "params": {"repo": repo, "run_id": _need_pos(0, "run-id")}}
    raise UnsupportedVerb(f"verb {verb!r} is not exposed over the launcher socket")


class LauncherClient:
    """One request per call over the launcher's ``AF_UNIX`` control socket."""

    def __init__(self, socket_path: Path | str) -> None:
        self.socket_path = str(socket_path)

    def request(self, op: str, params: Mapping[str, str]) -> dict[str, Any]:
        """Send one ``{"op", "params"}`` line; return the parsed response dict."""
        payload = json.dumps({"op": op, "params": dict(params)}) + "\n"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(self.socket_path)
                client.sendall(payload.encode())
                client.shutdown(socket.SHUT_WR)
                chunks: list[bytes] = []
                while True:
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
        except OSError as exc:
            raise LauncherClientError(
                f"cannot reach launcher control socket at {self.socket_path}: {exc}"
            ) from exc
        try:
            response: dict[str, Any] = json.loads(b"".join(chunks))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LauncherClientError("launcher returned a non-JSON response") from exc
        return response


def main(argv: Sequence[str] | None = None) -> int:
    """``harness <verb> …`` over the socket. Returns the process exit code.

    Prints the verb's stdout verbatim (so ``/harness run`` parses it unchanged)
    and exits with the verb's exit code. A launcher refusal or transport error
    is reported on stderr with exit code 2.
    """
    raw = list(sys.argv[1:] if argv is None else argv)
    repo = os.getcwd()
    socket_path = default_socket_path()
    try:
        request = verb_argv_to_request(raw, repo=repo)
    except UnsupportedVerb as exc:
        print(f"harness (launcher client): {exc}", file=sys.stderr)
        return 2

    client = LauncherClient(socket_path)
    try:
        response = client.request(str(request["op"]), request["params"])
    except LauncherClientError as exc:
        print(f"harness (launcher client): {exc}", file=sys.stderr)
        return 2

    if not response.get("ok", False):
        reason = response.get("reason", "error")
        print(f"harness (launcher client): launcher refused ({reason})", file=sys.stderr)
        return 2

    stdout = response.get("stdout", "")
    if stdout:
        sys.stdout.write(stdout if stdout.endswith("\n") else stdout + "\n")
    exit_code = response.get("exit_code", 0)
    return int(exit_code) if isinstance(exit_code, int) else 0


if __name__ == "__main__":  # pragma: no cover - module entry
    raise SystemExit(main())
