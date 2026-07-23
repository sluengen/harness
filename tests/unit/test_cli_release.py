"""Tests for ``harness release <ticket>`` — the decision-sweep return write as
an audited verb (#193, the ``defer`` shape in reverse).

``/decision`` is the versioned return path that drains tickets held for a
judgment call (ADR 0006). Releasing a held ticket is the load-bearing step —
the proposal's own words: writing the resolution into the change spec,
removing the hold label, and unassigning the operator, because
``work-discovery`` treats assignment as the authoritative skip signal. A
release that records an answer without unassigning leaves the ticket held
forever, so this is a bounded, named verb (mirroring ``defer``) rather than a
hand-rolled tracker write.

Contract under test:

* ``harness release <ticket> --resolution <text>`` appends a ``## Resolution``
  section to the issue body (``update_issue_body``), removes the hold label
  (``remove_label``, default ``decision``), unassigns the operator
  (``unassign_viewer``), then records a ``release`` event; exits 0.
* It binds to a ticket on this repo's Build queue (``repo.project``): a ticket
  not found, or found but on another project, is refused (exit 2) with a
  structured ``reason`` — no body write, no label removal, no unassign, no
  event.
* A tracker-less repo (``layers.linear: false``) degrades to a clean no-op,
  consistent with the other verbs.
* ``--resolution-file`` supplies a long body; exactly one of ``--resolution`` /
  ``--resolution-file`` is required.
* Release order is body write, then label removal, then unassign — the
  resolution lands in the spec before the ticket is dropped off the held pile.
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
_EXISTING_BODY = "## Context\n\nSome context.\n\n## Goal\n\nDo the thing.\n"


def _run_sync(coro: object) -> object:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)  # type: ignore[arg-type]
    finally:
        loop.close()


def _write_context(
    repo_root: Path, *, linear: bool = True, project: str | None = _BUILD_PROJECT
) -> None:
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
    body: str = _EXISTING_BODY,
) -> MagicMock:
    from harness.linear import LinearNotFound

    mock = MagicMock()
    if not_found:
        mock.fetch_issue_project = AsyncMock(side_effect=LinearNotFound("nope"))
        mock.fetch_issue = AsyncMock(side_effect=LinearNotFound("nope"))
    else:
        mock.fetch_issue_project = AsyncMock(return_value=ticket_project)
        mock.fetch_issue = AsyncMock(return_value={"description": body})
    mock.update_issue_body = AsyncMock(return_value=None)
    mock.remove_label = AsyncMock(return_value=None)
    mock.unassign_viewer = AsyncMock(return_value=None)
    return mock


def _invoke(args: list[str], repo_root: Path, stub: MagicMock, monkeypatch: Any) -> Any:
    monkeypatch.chdir(repo_root)
    with (
        patch("harness.tracker.LinearClient", return_value=stub),
        patch("harness.tracker.linear_api_key", return_value="test-key"),
    ):
        return cli_runner.invoke(app, args)


def _fetch_release_events(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []

    async def _select() -> list[dict[str, Any]]:
        async with store.connect(db_path) as conn:
            try:
                cur = await conn.execute(
                    "SELECT data_json FROM events WHERE event_type = 'release'"
                )
            except Exception:
                return []
            rows = await cur.fetchall()
        return [json.loads(r[0]) for r in rows]

    return _run_sync(_select())  # type: ignore[return-value]


# ===========================================================================
# AC: happy path — body write + label removal + unassign + release event
# ===========================================================================


def test_release_writes_resolution_removes_label_unassigns_and_records_event(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub()

    result = _invoke(
        ["release", "CAL-193", "--resolution", "Go with option A.", "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    stub.update_issue_body.assert_awaited_once()
    _, new_body = stub.update_issue_body.await_args.args
    assert _EXISTING_BODY.strip() in new_body
    assert "## Resolution" in new_body
    assert "Go with option A." in new_body

    stub.remove_label.assert_awaited_once()
    ticket_arg, label_arg = stub.remove_label.await_args.args
    assert ticket_arg == "CAL-193"
    assert label_arg == "decision"

    stub.unassign_viewer.assert_awaited_once()
    (unassign_ticket,) = stub.unassign_viewer.await_args.args
    assert unassign_ticket == "CAL-193"

    events = _fetch_release_events(db)
    assert len(events) == 1
    assert events[0]["ticket"] == "CAL-193"
    assert events[0]["needs"] == "decision"


def test_release_json_success_output(tmp_path: Path, monkeypatch: Any) -> None:
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub()

    result = _invoke(
        ["release", "CAL-193", "--resolution", "Go with A.", "--db", str(db), "--json"],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ticket"] == "CAL-193"
    assert payload["outcome"] == "released"
    assert payload["project"] == _BUILD_PROJECT
    assert payload["run_id"]


def test_release_order_is_body_then_label_then_unassign(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The resolution lands in the spec before the hold is dropped — a crash
    between steps leaves the ticket still held, never silently released with
    no answer recorded."""
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub()
    order: list[str] = []
    stub.update_issue_body.side_effect = lambda *_a: order.append("body")
    stub.remove_label.side_effect = lambda *_a: order.append("label")
    stub.unassign_viewer.side_effect = lambda *_a: order.append("unassign")

    result = _invoke(
        ["release", "CAL-193", "--resolution", "x", "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    assert order == ["body", "label", "unassign"]


# ===========================================================================
# AC-1: --needs selects the label removed; default remains `decision`
# ===========================================================================


def test_release_needs_input_removes_input_label(tmp_path: Path, monkeypatch: Any) -> None:
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub()

    result = _invoke(
        ["release", "CAL-193", "--resolution", "x", "--needs", "input", "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    _, label_arg = stub.remove_label.await_args.args
    assert label_arg == "input"
    events = _fetch_release_events(db)
    assert events[0]["needs"] == "input"


def test_release_rejects_unknown_needs_kind(tmp_path: Path, monkeypatch: Any) -> None:
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub()

    result = _invoke(
        ["release", "CAL-193", "--resolution", "x", "--needs", "bogus", "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 2, result.output
    stub.update_issue_body.assert_not_awaited()
    stub.remove_label.assert_not_awaited()
    stub.unassign_viewer.assert_not_awaited()


# ===========================================================================
# AC: refuse when the ticket is not on the Build queue
# ===========================================================================


def test_release_refuses_ticket_not_found(tmp_path: Path, monkeypatch: Any) -> None:
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub(not_found=True)

    result = _invoke(
        ["release", "CAL-404", "--resolution", "x", "--db", str(db), "--json"],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == "ticket_not_found"
    stub.update_issue_body.assert_not_awaited()
    stub.remove_label.assert_not_awaited()
    stub.unassign_viewer.assert_not_awaited()
    assert _fetch_release_events(db) == []


def test_release_refuses_ticket_on_another_project(tmp_path: Path, monkeypatch: Any) -> None:
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub(ticket_project="Some Other Project")

    result = _invoke(
        ["release", "CAL-777", "--resolution", "x", "--db", str(db), "--json"],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == "not_on_build_queue"
    stub.update_issue_body.assert_not_awaited()
    stub.remove_label.assert_not_awaited()
    stub.unassign_viewer.assert_not_awaited()
    assert _fetch_release_events(db) == []


# ===========================================================================
# AC: tracker-less repo → clean no-op
# ===========================================================================


def test_release_tracker_less_is_a_clean_noop(tmp_path: Path, monkeypatch: Any) -> None:
    _write_context(tmp_path, linear=False)
    db = tmp_path / "harness.db"
    stub = _make_stub()

    result = _invoke(
        ["release", "CAL-193", "--resolution", "x", "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    stub.fetch_issue_project.assert_not_awaited()
    stub.update_issue_body.assert_not_awaited()
    stub.remove_label.assert_not_awaited()
    stub.unassign_viewer.assert_not_awaited()
    assert _fetch_release_events(db) == []


# ===========================================================================
# Invocation: --resolution / --resolution-file
# ===========================================================================


def test_release_requires_a_resolution(tmp_path: Path, monkeypatch: Any) -> None:
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub()

    result = _invoke(
        ["release", "CAL-193", "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 2, result.output
    stub.update_issue_body.assert_not_awaited()


def test_release_reads_resolution_file(tmp_path: Path, monkeypatch: Any) -> None:
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    resolution_file = tmp_path / "resolution.md"
    resolution_file.write_text("A long\nmulti-line\nresolution.")
    stub = _make_stub()

    result = _invoke(
        ["release", "CAL-193", "--resolution-file", str(resolution_file), "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    _, new_body = stub.update_issue_body.await_args.args
    assert "multi-line" in new_body


# ===========================================================================
# Idempotent re-release: an existing Resolution section is replaced, not
# duplicated
# ===========================================================================


def test_release_replaces_an_existing_resolution_section(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A re-run of ``release`` (e.g. after a crash between steps) replaces the
    prior ``## Resolution`` section rather than appending a second one."""
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    body_with_resolution = _EXISTING_BODY + "\n## Resolution\n\nOld answer.\n"
    stub = _make_stub(body=body_with_resolution)

    result = _invoke(
        ["release", "CAL-193", "--resolution", "New answer.", "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    _, new_body = stub.update_issue_body.await_args.args
    assert new_body.count("## Resolution") == 1
    assert "New answer." in new_body
    assert "Old answer." not in new_body
