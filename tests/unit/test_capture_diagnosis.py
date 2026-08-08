"""A failed capture must not drop the stream that carried the diagnosis (#370).

The defect this measures is not hypothetical and not local: on the CI runner a
failing ``start`` reported ``['start', '1', '--json'] exited 1: b''`` for two
days, and the empty bytes were read as "the verb said nothing" when they only
ever meant "one stream was read and it was empty". The other stream — where a
traceback, an entrypoint failure and every non-``--json`` refusal go — was never
read at all.

So the property asserted here is that a diagnosis **names both streams and their
exact bytes, including the empty ones**. That is what separates *no diagnostic
was produced* from *no diagnostic was read*, and it is the only thing that would
have made the CI failure attributable from its own log line.

Pure renderer, synthetic captures, no daemon: ``unit`` tier by construction.
"""

from __future__ import annotations

from tests._capture import Capture


def test_a_diagnosis_carries_the_stream_the_error_was_written_to() -> None:
    """The defect, stated directly.

    A verb that dies outside ``run_verb``'s ``--json`` path writes its traceback
    to stderr and exits non-zero, leaving stdout empty. A diagnosis rendering
    stdout alone reports that as ``b''`` and loses the only artifact naming the
    cause.
    """
    traceback = b'Traceback (most recent call last):\n  fatal: detected dubious ownership\n'
    capture = Capture(code=1, stdout=b"", stderr=traceback)

    message = capture.diagnosis(["start", "1", "--json"])

    assert repr(traceback) in message, (
        "the diagnosis dropped stderr — the one stream the error was written "
        f"to:\n{message}"
    )


def test_a_diagnosis_names_an_empty_stream_rather_than_omitting_it() -> None:
    """An omitted stream and an empty one must not read the same.

    Rendering only the streams that carried bytes would be the same blind spot
    wearing a tidier format: a reader could not tell whether stderr was empty or
    simply never read. Both are always named, with their exact bytes.
    """
    capture = Capture(code=1, stdout=b"", stderr=b"boom\n")

    message = capture.diagnosis(["start", "1"])

    assert "stdout" in message and repr(b"") in message, (
        f"the empty stream was omitted instead of shown as b'':\n{message}"
    )
    # The floor: the assertion above must not be satisfiable by a message that
    # dropped the *other* stream, which is the very defect being fixed.
    assert repr(b"boom\n") in message, (
        f"the stream that carried bytes is missing from the diagnosis:\n{message}"
    )


def test_a_diagnosis_names_the_invocation_and_its_exit_code() -> None:
    """What the existing message already carried, kept while the rest widened."""
    capture = Capture(code=7, stdout=b"", stderr=b"")

    message = capture.diagnosis(["worktrees", "cleanup"])

    assert "worktrees" in message and "cleanup" in message, message
    assert "7" in message, message


def test_a_diagnosis_renders_output_that_is_not_valid_utf8() -> None:
    """Rendered as ``repr``, never decoded.

    A verb whose output is truncated mid-multibyte — a container killed while
    writing — must still produce a readable failure message. A diagnosis that
    decoded its streams would raise ``UnicodeDecodeError`` from inside the
    assertion message and replace the cause with a second, unrelated error.
    """
    capture = Capture(code=1, stdout=b"\xff\xfe", stderr=b"\x80partial")

    message = capture.diagnosis(["version"])

    assert repr(b"\xff\xfe") in message, message
    assert repr(b"\x80partial") in message, message


def test_the_compared_contract_is_exit_code_and_stdout_alone() -> None:
    """The narrowing #370 must not silently undo.

    ``test_serve_socket.py`` compares two captures to assert #307's AC-1 —
    *stdout* byte-identity across the socket and direct-spawn paths. Reading
    stderr for diagnosis is not a licence to widen that claim: container stderr
    carries per-environment noise, so folding it in would make a passing test
    depend on the host it ran on.
    """
    over_socket = Capture(code=0, stdout=b'{"ok": true}', stderr=b"a docker warning\n")
    directly = Capture(code=0, stdout=b'{"ok": true}', stderr=b"")

    assert over_socket.contract == directly.contract
    assert over_socket.contract == (0, b'{"ok": true}')
    # The floor: `contract` must still be able to tell two captures apart, or the
    # comparison it feeds is vacuous.
    assert Capture(code=1, stdout=b"x", stderr=b"").contract != over_socket.contract
