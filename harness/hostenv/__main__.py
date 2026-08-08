"""``python3 -m harness.hostenv env`` — the resolver's command-line surface (#305).

Everything the harness needs to resolve *before* a container exists — credentials
and commit identity — is resolved on the host, in tested Python rather than in
macOS-shaped bash. This module is the CLI over that resolution; the resolution
itself is :func:`harness.hostenv.container_env.resolve_container_env`, which is also what
both container-spawn paths call.

**The wrapper is no longer the caller (#307).** It shelled out to this once and
imported the ``KEY=value`` records back into bash; it now execs
``harness.hostenv.client``, which resolves in-process and hands the values to
docker through the subprocess environment. The record contract below is unchanged
and still exercised — an operator or a native install can call this directly — but
it no longer sits on the wrapper's path.

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

from harness.hostenv.container_env import resolve_container_env
from harness.hostenv.host import UnsupportedHost, detect_host

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

    resolved = resolve_container_env(args.workdir, host=host)

    _emit({**resolved.values, **resolved.git_identity})
    for note in resolved.diagnostics:
        _warn(note)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover — exercised as a subprocess
    sys.exit(main())
