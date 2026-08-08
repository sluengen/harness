"""Unit tests for the shared verb plumbing (CAL-1013).

Every verb command (``start``/``review``/``close``/``checkpoint``/``reclaim``,
plus the ``cancel`` abandon path) raises a single control-flow exception —
:class:`harness.cli._verb.VerbError` — and translates it through one epilogue
helper, :func:`harness.cli._verb.run_verb`. These tests pin the uniform
error-JSON shape (the *recorded decision* on the ``reason`` field) so it can no
longer drift between verbs, and pin that ``run_verb`` never swallows a
non-``VerbError`` exception.
"""

from __future__ import annotations

import json

import pytest
import typer

from harness.cli._verb import VerbError, run_verb


def test_verberror_carries_message_code_and_optional_reason() -> None:
    """The one base holds ``(message, code, reason)``; ``reason`` defaults None."""
    plain = VerbError("boom", 2)
    assert plain.message == "boom"
    assert plain.code == 2
    assert plain.reason is None
    assert str(plain) == "boom"

    tagged = VerbError("gate refused", 2, reason="no_run")
    assert tagged.reason == "no_run"


def test_run_verb_returns_work_result_on_success() -> None:
    """On success ``run_verb`` returns the callable's value untouched."""
    assert run_verb(lambda: 42, json_output=True) == 42


def test_run_verb_json_error_without_reason_is_bare_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A verb that sets no ``reason`` keeps the historical ``{"error"}`` shape."""

    def work() -> int:
        raise VerbError("nope", 2)

    with pytest.raises(typer.Exit) as excinfo:
        run_verb(work, json_output=True)
    assert excinfo.value.exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"error": "nope"}
    assert "reason" not in payload  # absent, not null — the decided shape


def test_run_verb_json_error_with_reason_includes_reason(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When a verb sets a ``reason`` it is emitted alongside ``error``."""

    def work() -> int:
        raise VerbError("gate refused", 2, reason="stale_review")

    with pytest.raises(typer.Exit) as excinfo:
        run_verb(work, json_output=True)
    assert excinfo.value.exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"error": "gate refused", "reason": "stale_review"}


def test_run_verb_human_error_writes_message_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    """With ``--no-json`` the human message goes to stderr, not stdout."""

    def work() -> int:
        raise VerbError("bad input", 2)

    with pytest.raises(typer.Exit) as excinfo:
        run_verb(work, json_output=False)
    assert excinfo.value.exit_code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "bad input" in captured.err


def test_run_verb_does_not_swallow_non_verberror() -> None:
    """A ``ClickException`` (e.g. ``typer.BadParameter``) propagates unchanged.

    Typer's own handler owns argument errors and their exit code 2. This is the
    negative control for the unexpected-exception payload below: that path must
    not annex the errors another handler already reports well.
    """

    def work() -> int:
        raise typer.BadParameter("not a duration")

    with pytest.raises(typer.BadParameter):
        run_verb(work, json_output=True)


# ---------------------------------------------------------------------------
# An unexpected exception under ``--json`` still owes the caller a payload (#370).
#
# Measured on the CI runner: ``start`` died on ``PermissionError: [Errno 13]
# Permission denied: '/workspace/.harness'`` raised inside ``store.init_db``.
# That is not a ``VerbError``, so the ``--json`` writer never ran — the verb
# exited 1 having written *nothing* to stdout, and the orchestrating loop that
# parses stdout for a reason had nothing to parse. The verb knew what went wrong
# and said so, on a stream its machine reader does not read.
# ---------------------------------------------------------------------------


def test_run_verb_reports_an_unexpected_exception_as_a_json_payload(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The defect, in the shape the runner produced it."""

    def work() -> int:
        raise PermissionError(13, "Permission denied", "/workspace/.harness")

    with pytest.raises(typer.Exit) as excinfo:
        run_verb(work, json_output=True)

    assert excinfo.value.exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == "unexpected_error"
    # The class *and* its own message: a generic "something went wrong" would
    # satisfy a check for the key alone while losing the only fact that
    # identifies the failure.
    assert "PermissionError" in payload["error"]
    assert "/workspace/.harness" in payload["error"]


def test_run_verb_keeps_an_unexpected_exceptions_traceback_on_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Adding the machine payload must not cost the human one.

    The two readers want different things — a reason to branch on, and the
    frames that name the line. Emitting one by discarding the other would be
    this ticket's own defect pointed the other way.
    """

    def work() -> int:
        raise PermissionError(13, "Permission denied", "/workspace/.harness")

    with pytest.raises(typer.Exit):
        run_verb(work, json_output=True)

    captured = capsys.readouterr()
    assert "Traceback" in captured.err
    assert "PermissionError" in captured.err
    # The floor: stdout still carries the payload, so this is not satisfied by a
    # version that merely reverted to printing a traceback and nothing else.
    assert json.loads(captured.out)["reason"] == "unexpected_error"


def test_run_verb_leaves_an_unexpected_exception_alone_without_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The human path is untouched.

    Nothing consumes stdout there, and Typer's own renderer shows the frames
    better than a hand-printed traceback would. The defect is the *machine*
    contract, so that is the only path that changes.
    """

    def work() -> int:
        raise PermissionError(13, "Permission denied", "/workspace/.harness")

    with pytest.raises(PermissionError):
        run_verb(work, json_output=False)
    assert capsys.readouterr().out == ""


def test_run_verb_does_not_intercept_typer_control_flow() -> None:
    """``typer.Exit`` and ``typer.Abort`` are control flow, not failures.

    Both subclass ``RuntimeError``, so a bare ``except Exception`` would swallow
    them and rewrite a verb's deliberate exit code to 1.
    """

    def exits() -> int:
        raise typer.Exit(code=3)

    with pytest.raises(typer.Exit) as excinfo:
        run_verb(exits, json_output=True)
    assert excinfo.value.exit_code == 3

    def aborts() -> int:
        raise typer.Abort()

    with pytest.raises(typer.Abort):
        run_verb(aborts, json_output=True)


# ---------------------------------------------------------------------------
# The AC, structurally: one error base + one epilogue helper used by every verb.
# ---------------------------------------------------------------------------


def test_every_verb_error_subclasses_the_one_base() -> None:
    """Each verb's control-flow exception is a :class:`VerbError` — so the one
    ``run_verb`` epilogue (which catches the base) handles them all uniformly."""
    from harness.cli._abandon import AbandonError
    from harness.cli.checkpoint import _CheckpointError
    from harness.cli.close import _CloseError
    from harness.cli.reclaim import _ReclaimError
    from harness.cli.review import _ReviewError
    from harness.cli.start import _StartError

    for cls in (
        _StartError,
        _ReviewError,
        _CloseError,
        _CheckpointError,
        _ReclaimError,
        AbandonError,
    ):
        assert issubclass(cls, VerbError), f"{cls.__name__} must subclass VerbError"
        # The carrier is inherited, not re-declared: no verb defines its own
        # ``__init__`` (that duplication is exactly what CAL-1013 removed).
        assert "__init__" not in cls.__dict__, (
            f"{cls.__name__} re-declares __init__; inherit it from VerbError"
        )


def test_every_command_module_routes_errors_through_run_verb() -> None:
    """Every verb command wires the shared epilogue — no bespoke ``except
    _XError`` / ``typer.Exit`` epilogue creeps back into a command."""
    from pathlib import Path

    cli_dir = Path(__file__).resolve().parents[2] / "harness" / "cli"
    for stem in ("start", "review", "close", "checkpoint", "reclaim", "cancel"):
        source = (cli_dir / f"{stem}.py").read_text()
        assert "run_verb(" in source, f"{stem}.py must route errors through run_verb"
