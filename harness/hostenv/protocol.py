"""The control-socket wire contract (#307, ADR 0012).

One request per connection: the client sends a single JSON object with its own
stdin/stdout/stderr file descriptors attached, the server spawns the verb
container against those fds, and writes one JSON response after it exits.

**The strict schema is a security control, not tidiness.** Exactly three keys are
accepted; anything else is refused. That is what makes ``image``, ``volumes``,
``privileged`` and ``env`` *inexpressible* rather than merely ignored — there is
no field through which a mount, an image, a privilege flag, or an environment
variable can be supplied, so ADR 0012's spawner property holds at the wire as
well as in the argv (see :mod:`harness.hostenv.spawn`). Ignoring unknown keys
would behave identically today and fail open the day one of those names acquires
a meaning.

The response deliberately carries **no verb output**. Output crosses on the
caller's own file descriptors, so a 12-minute ``review`` streams live rather than
arriving at the end — and, decisively, the server never accumulates a run's
output in memory, which would be run-describing state living outside the ledger.

Stdlib only — see the package docstring.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

__all__ = [
    "BadRequest",
    "MAX_REQUEST_BYTES",
    "PROTOCOL_VERSION",
    "Reason",
    "Request",
    "Response",
    "decode_request",
    "decode_response",
    "encode_refusal",
    "encode_request",
    "encode_success",
    "exit_code_for",
    "socket_path",
]

#: Bumped only on a breaking frame change. A client and server that disagree
#: refuse rather than guess.
PROTOCOL_VERSION = 1

#: Hard cap on a single request. The peer is unauthenticated (the socket's only
#: authentication is filesystem permissions), so the bound on what it can make
#: the server allocate is stated rather than left to available memory. Comfortably
#: above the largest real argv — a ``defer --reason`` body.
MAX_REQUEST_BYTES = 64 * 1024

#: Environment variable naming the socket explicitly.
SOCKET_ENV = "HARNESS_CONTROL_SOCKET"

_SOCKET_NAME = "control.sock"

#: Exactly the keys a request may carry.
_REQUEST_KEYS = frozenset({"protocol", "repo", "argv"})


class Reason(StrEnum):
    """Why a request was refused. Stable strings — the client maps them to exits."""

    BAD_REQUEST = "bad_request"
    UNKNOWN_VERB = "unknown_verb"
    REPO_NOT_ALLOWED = "repo_not_allowed"
    REPO_MISMATCH = "repo_mismatch"
    SPAWN_FAILED = "spawn_failed"
    #: The host cannot supply a usable agent credential (#309). A *named*
    #: reason rather than a reuse of ``repo_not_allowed``: that string stretches
    #: over "this host/repo combination cannot be served" and not over a
    #: credential outage, and it is the audit line's only word for what happened
    #: — attributing a credential event to the repo allowlist would mislead the
    #: one record the socket keeps.
    CREDENTIAL_UNAVAILABLE = "credential_unavailable"


#: ``spawn_failed`` is the one refusal that is not the caller's fault — docker
#: itself failed — so it maps to 1 (unexpected error) rather than 2 (invocation
#: refusal), per the CLI's exit contract in SPEC §11.
_EXIT_FOR_REASON = {
    Reason.BAD_REQUEST: 2,
    Reason.UNKNOWN_VERB: 2,
    Reason.REPO_NOT_ALLOWED: 2,
    Reason.REPO_MISMATCH: 2,
    Reason.SPAWN_FAILED: 1,
    Reason.CREDENTIAL_UNAVAILABLE: 2,
}


class BadRequest(Exception):  # noqa: N818 — a protocol refusal, mirrors the wire vocabulary
    """A request is malformed, oversized, or carries a key outside the schema."""


@dataclass(frozen=True)
class Request:
    """A decoded, schema-valid request. ``repo`` is absolute but not yet resolved
    against the allowlist — that is the server's next check, not the frame's."""

    repo: Path
    argv: list[str]


@dataclass(frozen=True)
class Response:
    ok: bool
    exit_code: int | None = None
    reason: Reason | None = None
    error: str | None = None


def socket_path(env: Mapping[str, str] | None = None) -> Path:
    """Where the control socket lives, by precedence.

    ``HARNESS_CONTROL_SOCKET`` → ``$XDG_RUNTIME_DIR/harness/`` → ``~/.harness/``.
    The XDG runtime dir is preferred over ``$HOME`` because it is a per-session
    tmpfs the OS clears on logout, so a stale socket cannot outlive the boot that
    created it; ``$HOME`` is the portable fallback for hosts without one (macOS
    sets no ``XDG_RUNTIME_DIR``).
    """
    source = os.environ if env is None else env

    explicit = source.get(SOCKET_ENV, "").strip()
    if explicit:
        return Path(explicit)

    runtime_dir = source.get("XDG_RUNTIME_DIR", "").strip()
    if runtime_dir:
        return Path(runtime_dir) / "harness" / _SOCKET_NAME

    return Path(source.get("HOME", ".")) / ".harness" / _SOCKET_NAME


def encode_request(*, repo: Path, argv: list[str]) -> str:
    return json.dumps(
        {"protocol": PROTOCOL_VERSION, "repo": str(repo), "argv": list(argv)}
    )


def decode_request(raw: str | bytes) -> Request:
    """Parse and validate one request frame, or raise :class:`BadRequest`.

    Validation order is deliberate: size before parse, so an oversized frame is
    rejected without being handed to the JSON parser at all.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if len(raw.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise BadRequest(
            f"request exceeds {MAX_REQUEST_BYTES} bytes"
        )

    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise BadRequest(f"request is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise BadRequest("request must be a JSON object")

    keys = set(payload)
    if keys != _REQUEST_KEYS:
        unexpected = sorted(keys - _REQUEST_KEYS)
        missing = sorted(_REQUEST_KEYS - keys)
        raise BadRequest(
            f"request schema is exactly {sorted(_REQUEST_KEYS)}; "
            f"unexpected={unexpected} missing={missing}. A mount, image, "
            f"privilege or env cannot be requested — the host chooses them."
        )

    if payload["protocol"] != PROTOCOL_VERSION:
        raise BadRequest(
            f"unsupported protocol {payload['protocol']!r} "
            f"(this host speaks {PROTOCOL_VERSION})"
        )

    repo = payload["repo"]
    if not isinstance(repo, str) or not repo.startswith("/"):
        raise BadRequest("repo must be an absolute path string")

    argv = payload["argv"]
    if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        raise BadRequest("argv must be a list of strings")

    return Request(repo=Path(repo), argv=list(argv))


def encode_success(*, exit_code: int) -> str:
    return json.dumps(
        {"protocol": PROTOCOL_VERSION, "ok": True, "exit_code": int(exit_code)}
    )


def encode_refusal(reason: Reason, error: str) -> str:
    return json.dumps(
        {
            "protocol": PROTOCOL_VERSION,
            "ok": False,
            "reason": Reason(reason).value,
            "error": error,
        }
    )


def decode_response(raw: str | bytes) -> Response:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise BadRequest(f"response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise BadRequest("response must be a JSON object")

    # Every failure to make sense of a response must surface as BadRequest: the
    # client guards this call with `except BadRequest`, and a bare KeyError or
    # ValueError escaping here would crash it with a traceback *after* the
    # request was delivered — precisely the case where it must instead report
    # that the verb may have run and name the ledger as the record.
    try:
        if payload.get("ok"):
            return Response(ok=True, exit_code=int(payload["exit_code"]))
        raw_reason = payload["reason"]
        message = payload.get("error")
        try:
            reason = Reason(raw_reason)
        except ValueError:
            # A reason this client does not know is **not** a malformed frame:
            # it is a well-formed refusal from a server whose vocabulary is
            # newer (#309 added one). Raising BadRequest here would send the
            # client down its "the verb may have run — the ledger is the
            # record" path, which is the worst available answer for a refusal
            # that spawned nothing. `reason=None` already maps to exit 1 in
            # `exit_code_for`, and the server's own message is preserved with
            # the unrecognised reason prefixed so the operator can still see
            # what was refused.
            return Response(ok=False, reason=None, error=f"{raw_reason}: {message}")
        return Response(ok=False, reason=reason, error=message)
    except (KeyError, TypeError, ValueError) as exc:
        raise BadRequest(f"malformed response frame: {exc}") from exc


def exit_code_for(response: Response) -> int:
    """The process exit code the client should adopt for ``response``."""
    if response.ok:
        return int(response.exit_code or 0)
    if response.reason is None:
        # A refusal with no reason is itself malformed; report it as an
        # unexpected error rather than as a well-formed invocation refusal.
        return 1
    return _EXIT_FOR_REASON[response.reason]
