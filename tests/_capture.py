"""What a spawned verb actually emitted, and how a failed one is reported (#370).

A test that runs a real verb container reads its output through file
descriptors it opens itself. Which descriptors it opens is therefore part of
what the test can *see*, and until #370 the socket end-to-end module opened one:
stdout on a real file, stderr on ``/dev/null``.

That is the whole of the observation #370 exists to fix. On the CI runner a
failing ``start`` reported::

    ['start', '1', '--json'] exited 1: b''

and two people read the empty bytes as "the verb produced nothing", which is not
what they mean. ``harness/cli/_verb.py:run_verb`` writes ``{"error": …}`` to
**stdout** only under ``--json``; a non-``VerbError`` traceback, a failure inside
``docker/entrypoint.sh``'s ``set -euo pipefail``, and ``uv run``'s own
diagnostics all write to **stderr** and exit non-zero. Every one of those
produces exactly (exit 1, empty stdout), and a capture that never reads stderr
cannot tell them apart from a payload that was written and lost. #369 cost two
days to that ambiguity.

So the property this module owns is narrow and stated once, rather than restated
at each assertion site:

    a failed capture names every stream it read — including the ones that were
    empty — and says so explicitly when both were empty, so that "no diagnostic"
    is never confused with "no diagnostic was read".

:meth:`Capture.diagnosis` is a pure renderer: it takes the argv and returns
text. Keeping it pure is what lets it be tested at the ``unit`` tier against
synthetic captures, and mutation-proven, without a docker daemon anywhere near
it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["Capture"]


@dataclass(frozen=True)
class Capture:
    """One spawned verb's exit code and both of its output streams."""

    code: int
    stdout: bytes
    stderr: bytes

    @property
    def contract(self) -> tuple[int, bytes]:
        """The half two captures are compared on: exit code and **stdout**.

        Named rather than left implicit because the comparison it feeds is
        #307's AC-1 — *stdout* byte-identity between the socket and direct-spawn
        paths — and #370 must not widen that claim as a side effect of reading a
        second stream. Container stderr carries per-environment noise (a
        credential-resolution note, a docker warning), so folding it into the
        identity comparison would make a passing test depend on the host.
        """
        return (self.code, self.stdout)

    def diagnosis(self, argv: Sequence[str]) -> str:
        """Render this capture as an assertion message.

        Both streams, always, with their exact bytes — including the empty ones.
        Rendering only what carried bytes would be the same blind spot in a
        tidier format: a reader could not tell an empty stream from an unread
        one, which is precisely the distinction #369 needed and did not have.

        ``repr`` rather than ``decode``: a container killed mid-write leaves
        truncated multibyte output, and a decoding renderer would raise from
        inside the assertion message, replacing the cause with an unrelated
        error. Untruncated for the same reason — the tail of a traceback is
        usually the part that names the cause.
        """
        return (
            f"{list(argv)} exited {self.code}\n"
            f"  stdout: {self.stdout!r}\n"
            f"  stderr: {self.stderr!r}"
        )
