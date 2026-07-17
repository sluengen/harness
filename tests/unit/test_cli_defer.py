"""Tests for ``harness defer <ticket>`` — the triage write as an audited verb
(CAL-1143).

The unattended Build routine's triage step — ``work-discovery`` judging a picked
ticket not-yet-actionable and recording "comment + apply the ``decision`` label"
— was the one write the routine hand-rolled as raw GraphQL, because it is not a
build-lifecycle transition and had no verb. ``defer`` makes it a bounded, named
verb the routine calls the same way it calls ``start`` / ``review`` / ``close``.

Contract under test:

* ``harness defer <ticket> --reason <text>`` posts a comment and *additively*
  applies the ``decision`` label (``issueAddLabel``, never a full-set replace, so
  existing labels are preserved), then records a ``defer`` event in the
  runs/events ledger; exits 0.
* It binds to a ticket on this repo's Build queue (``repo.project``): a ticket
  not found, or found but on another project, is refused (exit 2) with a
  structured ``reason`` — no comment, no label, no event.
* A tracker-less repo (``layers.linear: false``) degrades to a clean no-op,
  consistent with the other verbs.
* ``--reason-file`` supplies a long body; exactly one of ``--reason`` /
  ``--reason-file`` is required.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from harness.cli import app
from harness.state import store

cli_runner = CliRunner()

_BUILD_PROJECT = "Harness v3"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _run_sync(coro: object) -> object:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)  # type: ignore[arg-type]
    finally:
        loop.close()


def _write_context(repo_root: Path, *, linear: bool = True, project: str | None = _BUILD_PROJECT) -> None:
    """Write a minimal CONTEXT.md the verb reads for ``repo.project`` + the layer."""
    project_line = f"  project: {project}\n" if project is not None else ""
    text = (
        "repo:\n"
        "  name: harness\n"
        "  linear: CAL\n"
        f"{project_line}"
        "layers:\n"
        f"  linear: {'true' if linear else 'false'}\n"
    )
    (repo_root / "CONTEXT.md").write_text(text)


def _make_stub(
    *,
    ticket_project: str | None = _BUILD_PROJECT,
    not_found: bool = False,
) -> MagicMock:
    """A LinearClient mock: ``fetch_issue_project`` returns the ticket's project (or
    raises ``LinearNotFound``); the comment + label primitives are no-op AsyncMocks."""
    from harness.linear import LinearNotFound

    mock = MagicMock()
    if not_found:
        mock.fetch_issue_project = AsyncMock(side_effect=LinearNotFound("nope"))
    else:
        mock.fetch_issue_project = AsyncMock(return_value=ticket_project)
    mock.post_comment = AsyncMock(return_value=None)
    mock.apply_label = AsyncMock(return_value=None)
    return mock


def _invoke(args: list[str], repo_root: Path, stub: MagicMock, monkeypatch: Any) -> Any:
    monkeypatch.chdir(repo_root)
    with (
        patch("harness.cli.defer.LinearClient", return_value=stub),
        patch("harness.cli.defer.linear_api_key", return_value="test-key"),
    ):
        return cli_runner.invoke(app, args)


def _fetch_defer_events(db_path: Path) -> list[dict[str, Any]]:
    """The recorded ``defer`` events. A refusal / no-op never creates the ledger,
    so a missing DB or ``events`` table reads as "no events" — not an error."""
    if not db_path.exists():
        return []

    async def _select() -> list[dict[str, Any]]:
        async with store.connect(db_path) as conn:
            try:
                cur = await conn.execute(
                    "SELECT data_json FROM events WHERE event_type = 'defer'"
                )
            except Exception:
                return []
            rows = await cur.fetchall()
        return [json.loads(r[0]) for r in rows]

    return _run_sync(_select())  # type: ignore[return-value]


# ===========================================================================
# AC: happy path — comment + additive label + defer event
# ===========================================================================


def test_defer_posts_comment_applies_label_and_records_event(tmp_path: Path, monkeypatch: Any) -> None:
    """``defer`` posts the reason as a comment, additively applies ``decision``, and
    records a ``defer`` event; exits 0."""
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub()

    result = _invoke(
        ["defer", "CAL-999", "--reason", "needs a human call on scope", "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    stub.post_comment.assert_awaited_once()
    _, comment_body = stub.post_comment.await_args.args
    assert "needs a human call on scope" in comment_body

    events = _fetch_defer_events(db)
    assert len(events) == 1
    assert events[0]["ticket"] == "CAL-999"
    assert events[0]["reason"] == "needs a human call on scope"


def test_defer_applies_label_additively(tmp_path: Path, monkeypatch: Any) -> None:
    """The label is applied via the additive primitive (``apply_label`` →
    ``issueAddLabel``), not a full-set replacement that would clobber other labels."""
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub()

    result = _invoke(
        ["defer", "CAL-999", "--reason", "x", "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    # The additive primitive is called with the `decision` label name; no
    # full-set label replacement primitive is used.
    stub.apply_label.assert_awaited_once()
    ticket_arg, label_arg = stub.apply_label.await_args.args
    assert ticket_arg == "CAL-999"
    assert label_arg == "decision"


# ===========================================================================
# AC: refuse when the ticket is not on the Build queue
# ===========================================================================


def test_defer_refuses_ticket_not_found(tmp_path: Path, monkeypatch: Any) -> None:
    """A ticket that does not exist on Linear is refused (exit 2), with no write."""
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub(not_found=True)

    result = _invoke(
        ["defer", "CAL-404", "--reason", "x", "--db", str(db), "--json"],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == "ticket_not_found"
    stub.post_comment.assert_not_awaited()
    stub.apply_label.assert_not_awaited()
    assert _fetch_defer_events(db) == []


def test_defer_refuses_ticket_on_another_project(tmp_path: Path, monkeypatch: Any) -> None:
    """A ticket on a different project than ``repo.project`` is refused (exit 2)."""
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub(ticket_project="Some Other Project")

    result = _invoke(
        ["defer", "CAL-777", "--reason", "x", "--db", str(db), "--json"],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == "not_on_build_queue"
    stub.post_comment.assert_not_awaited()
    stub.apply_label.assert_not_awaited()
    assert _fetch_defer_events(db) == []


# ===========================================================================
# AC: tracker-less repo → clean no-op
# ===========================================================================


def test_defer_tracker_less_is_a_clean_noop(tmp_path: Path, monkeypatch: Any) -> None:
    """With ``layers.linear: false`` the verb is a clean no-op — no Linear call,
    no event, exit 0 — consistent with the other verbs."""
    _write_context(tmp_path, linear=False)
    db = tmp_path / "harness.db"
    stub = _make_stub()

    result = _invoke(
        ["defer", "CAL-999", "--reason", "x", "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    stub.fetch_issue_project.assert_not_awaited()
    stub.post_comment.assert_not_awaited()
    stub.apply_label.assert_not_awaited()
    assert _fetch_defer_events(db) == []


# ===========================================================================
# Invocation: --reason / --reason-file
# ===========================================================================


def test_defer_requires_a_reason(tmp_path: Path, monkeypatch: Any) -> None:
    """Neither ``--reason`` nor ``--reason-file`` → invocation refusal (exit 2)."""
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub()

    result = _invoke(
        ["defer", "CAL-999", "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 2, result.output
    stub.post_comment.assert_not_awaited()


def test_defer_reads_reason_file(tmp_path: Path, monkeypatch: Any) -> None:
    """``--reason-file`` supplies a long body, posted as the comment."""
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    reason_file = tmp_path / "reason.md"
    reason_file.write_text("A long\nmulti-line\ntriage rationale.")
    stub = _make_stub()

    result = _invoke(
        ["defer", "CAL-999", "--reason-file", str(reason_file), "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    _, comment_body = stub.post_comment.await_args.args
    assert "multi-line" in comment_body
    events = _fetch_defer_events(db)
    assert events[0]["reason"] == "A long\nmulti-line\ntriage rationale."
