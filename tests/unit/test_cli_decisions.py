"""Tests for the v2-reserved ``decisions`` / ``decision`` CLI surface — H-025.

SPEC §11 reserves these verbs for v2 (human-in-the-loop decision nodes).
In v1 they must:

* exist (so callers can plan for them and ``--help`` discovers them)
* error gracefully with the message ``"deferred to v2"``
* exit with code **2** (invocation error per SPEC §11 exit table)
* support ``--json`` where applicable, emitting ``{"error": "deferred to v2"}``
* surface "v2-reserved — not yet implemented" in their ``--help`` text

The v1 contract here is stability: the exit code and JSON shape must not
change once shipped, so v2 callers (and v1 wrappers around them) can rely
on detecting the deferred state.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from harness.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# slate-harness decisions list
# ---------------------------------------------------------------------------


def test_decisions_list_exits_2_with_deferred_message_on_stderr() -> None:
    """AC 1 (human form). Message lands on stderr; stdout is empty."""
    result = runner.invoke(app, ["decisions", "list"])
    assert result.exit_code == 2, result.stdout + result.stderr
    assert result.stdout == ""
    assert "deferred to v2" in result.stderr


def test_decisions_list_json_emits_error_payload_to_stdout() -> None:
    """AC 1 (JSON form). JSON branch routes the message to stdout."""
    result = runner.invoke(app, ["decisions", "list", "--json"])
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload == {"error": "deferred to v2"}


def test_decisions_list_help_calls_out_v2_reserved() -> None:
    """AC 7. ``--help`` mentions v2-reserved status."""
    result = runner.invoke(app, ["decisions", "list", "--help"])
    assert result.exit_code == 0
    assert "v2-reserved" in result.stdout
    assert "not yet implemented" in result.stdout


# ---------------------------------------------------------------------------
# slate-harness decision show <run-id>
# ---------------------------------------------------------------------------


def test_decision_show_exits_2_with_deferred_message() -> None:
    """AC 2 (human form)."""
    result = runner.invoke(app, ["decision", "show", "R1"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "deferred to v2" in result.stderr


def test_decision_show_json_emits_error_payload() -> None:
    """AC 2 (JSON form)."""
    result = runner.invoke(app, ["decision", "show", "R1", "--json"])
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload == {"error": "deferred to v2"}


def test_decision_show_help_calls_out_v2_reserved() -> None:
    result = runner.invoke(app, ["decision", "show", "--help"])
    assert result.exit_code == 0
    assert "v2-reserved" in result.stdout
    assert "not yet implemented" in result.stdout


# ---------------------------------------------------------------------------
# slate-harness decision approve <run-id>
# ---------------------------------------------------------------------------


def test_decision_approve_exits_2_with_deferred_message() -> None:
    """AC 3 — approve with no comment."""
    result = runner.invoke(app, ["decision", "approve", "R1"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "deferred to v2" in result.stderr


def test_decision_approve_with_comment_still_exits_2() -> None:
    """AC 3 — approve with --comment still defers."""
    result = runner.invoke(
        app, ["decision", "approve", "R1", "--comment", "looks good"]
    )
    assert result.exit_code == 2
    assert "deferred to v2" in result.stderr


def test_decision_approve_help_calls_out_v2_reserved() -> None:
    result = runner.invoke(app, ["decision", "approve", "--help"])
    assert result.exit_code == 0
    assert "v2-reserved" in result.stdout
    assert "not yet implemented" in result.stdout


# ---------------------------------------------------------------------------
# slate-harness decision reject <run-id>
# ---------------------------------------------------------------------------


def test_decision_reject_exits_2_with_deferred_message() -> None:
    """AC 4 — reject with no comment."""
    result = runner.invoke(app, ["decision", "reject", "R1"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "deferred to v2" in result.stderr


def test_decision_reject_with_comment_still_exits_2() -> None:
    """AC 4 — reject with --comment still defers."""
    result = runner.invoke(
        app, ["decision", "reject", "R1", "--comment", "rebrew"]
    )
    assert result.exit_code == 2
    assert "deferred to v2" in result.stderr


def test_decision_reject_help_calls_out_v2_reserved() -> None:
    result = runner.invoke(app, ["decision", "reject", "--help"])
    assert result.exit_code == 0
    assert "v2-reserved" in result.stdout
    assert "not yet implemented" in result.stdout


# ---------------------------------------------------------------------------
# AC 6 — exit code 2 is the stable contract across all four verbs.
# ---------------------------------------------------------------------------


def test_all_reserved_verbs_exit_code_2() -> None:
    """AC 6 — pin the exit code so v1 callers can detect 'deferred'."""
    invocations = [
        ["decisions", "list"],
        ["decisions", "list", "--json"],
        ["decision", "show", "R1"],
        ["decision", "show", "R1", "--json"],
        ["decision", "approve", "R1"],
        ["decision", "reject", "R1"],
    ]
    for argv in invocations:
        result = runner.invoke(app, argv)
        assert result.exit_code == 2, f"{argv!r} -> exit={result.exit_code}"


# ---------------------------------------------------------------------------
# AC 5 — runs.status enum recognises ``paused`` and ``stalled`` for type-safe
# reads. The Python-level Literal lives alongside the existing event Literal so
# callers can import and assert against it.
# ---------------------------------------------------------------------------


def test_run_status_literal_includes_paused_and_stalled() -> None:
    """AC 5 — the type-safe view of the status enum exposes both v1.5 values."""
    from harness.state.schema import RUN_STATUSES

    # Per SPEC §12 -- "pending | running | completed | failed | cancelled |
    # stalled | paused".
    assert "paused" in RUN_STATUSES
    assert "stalled" in RUN_STATUSES
    # Existing values must remain to avoid silent contract drift.
    for canonical in (
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
    ):
        assert canonical in RUN_STATUSES
