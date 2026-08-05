"""``python3 -m harness.hostenv env`` — the wrapper's delegation target (#305).

The wrapper shells out to this once and imports the ``KEY=value`` records it
prints. Everything the harness needs to resolve *before* a container exists —
credentials and commit identity — is resolved here, on the host, in tested Python
rather than in macOS-shaped bash.

**Contract.** stdout carries NUL-terminated ``KEY=value`` records and nothing
else; every diagnostic goes to stderr. NUL-termination rather than newlines
because a credential is opaque bytes: a token containing a newline would
otherwise be read back as two records, and the second would be exported as
whatever it happened to spell.

Exit codes: ``0`` normal (including "no credential found" — an absent credential
is the container's problem to report, not a reason to refuse to start); ``2``
:class:`UnsupportedHost`, with no credential records emitted; ``3`` the
interpreter is too old.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness.hostenv.credentials import AgentCredential
from harness.hostenv.host import HostPlatform, UnsupportedHost, detect_host

MINIMUM_PYTHON = (3, 11)

EXIT_OK = 0
EXIT_UNSUPPORTED_HOST = 2
EXIT_INTERPRETER_TOO_OLD = 3


def _emit(records: dict[str, str]) -> None:
    """Write NUL-terminated ``KEY=value`` records to stdout."""
    out = sys.stdout
    for key, value in records.items():
        out.write(f"{key}={value}\0")
    out.flush()


def _warn(message: str) -> None:
    print(f"harness: {message}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < MINIMUM_PYTHON:
        running = ".".join(str(part) for part in sys.version_info[:3])
        _warn(
            f"host interpreter {sys.executable} is Python {running}, but "
            f"{'.'.join(str(p) for p in MINIMUM_PYTHON)}+ is required. "
            "Set HARNESS_HOST_PYTHON to a newer interpreter."
        )
        return EXIT_INTERPRETER_TOO_OLD

    parser = argparse.ArgumentParser(prog="harness.hostenv")
    subparsers = parser.add_subparsers(dest="command", required=True)
    env_parser = subparsers.add_parser("env", help="resolve host env for the container")
    env_parser.add_argument(
        "--workdir",
        type=Path,
        default=Path.cwd(),
        help="the target repo whose .env is consulted (default: CWD)",
    )
    args = parser.parse_args(argv)

    try:
        host = detect_host(platform=sys.platform)
    except UnsupportedHost as unsupported:
        _warn(str(unsupported))
        return EXIT_UNSUPPORTED_HOST

    records: dict[str, str] = {}

    tracker = host.tracker_credentials(args.workdir)
    if tracker.linear_api_key:
        records["LINEAR_API_KEY"] = tracker.linear_api_key
    if tracker.github_token:
        records["GITHUB_TOKEN"] = tracker.github_token

    # An already-exported token short-circuits the whole agent-credential path:
    # no store read, no `claude -p ok`. This is the wrapper's `if [[ -z ... ]]`
    # guard preserved, and it is what lets the wrapper's own tests run without
    # touching a real Keychain.
    if not host.env.get("CLAUDE_CODE_OAUTH_TOKEN"):
        credential = _resolve_agent_credential(host)
        if credential is not None:
            records["CLAUDE_CODE_OAUTH_TOKEN"] = credential.token
            records["CLAUDE_CODE_OAUTH_EXPIRES_AT"] = str(credential.expires_at_ms)

    identity = host.git_identity()
    records["GIT_AUTHOR_NAME"] = identity.name
    records["GIT_AUTHOR_EMAIL"] = identity.email
    records["GIT_COMMITTER_NAME"] = identity.name
    records["GIT_COMMITTER_EMAIL"] = identity.email

    _emit(records)
    for note in host.diagnostics:
        _warn(note)
    return EXIT_OK


def _resolve_agent_credential(host: HostPlatform) -> AgentCredential | None:
    """Read the credential, refreshing it first if it is at or inside the window.

    A refresh that fails leaves the stale-but-present token in play — the
    container's own 401 is where that belongs, and refusing to start would break
    a deployment whose token is merely close to expiry.
    """
    credential = host.agent_credential()
    if credential is None:
        return None
    if not credential.is_stale(host.now_ms()):
        return credential

    host.refresh_agent_credential()
    return host.agent_credential() or credential


if __name__ == "__main__":  # pragma: no cover — exercised as a subprocess
    sys.exit(main())
