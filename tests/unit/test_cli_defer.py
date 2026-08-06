"""Tests for ``harness defer <ticket>`` — the triage write as an audited verb
(CAL-1143).

The unattended Build routine's triage step — ``work-discovery`` judging a picked
ticket not-yet-actionable and recording "comment + apply the ``decision`` label"
— was the one write the routine hand-rolled as raw GraphQL, because it is not a
build-lifecycle transition and had no verb. ``defer`` makes it a bounded, named
verb the routine calls the same way it calls ``start`` / ``review`` / ``close``.

Contract under test:

* ``harness defer <ticket> --reason <text>`` posts a comment, *additively*
  applies the ``decision`` label (``issueAddLabel``, never a full-set replace, so
  existing labels are preserved), and assigns the operator; exits 0. Since #338
  it writes **nothing** to the runs/events ledger — the tracker issue is the
  canonical record. The ledger half of that contract is in
  ``test_held_ticket.py``; what stays here is the CLI-level surface.
* It binds to a ticket on this repo's Build queue (``repo.project``): a ticket
  not found, or found but on another project, is refused (exit 2) with a
  structured ``reason`` — no comment, no label, no event.
* A tracker-less repo (``layers.linear: false``) degrades to a clean no-op,
  consistent with the other verbs.
* ``--reason-file`` supplies a long body; exactly one of ``--reason`` /
  ``--reason-file`` is required.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from harness.cli import app
from harness.state import store
from harness.tracker_queue import QueueMembership
from tests._asyncutil import run_sync

cli_runner = CliRunner()

_BUILD_PROJECT = "Harness v3"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _write_context(
    repo_root: Path, *, linear: bool = True, project: str | None = _BUILD_PROJECT
) -> None:
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
    on_queue: bool = True,
    not_found: bool = False,
) -> MagicMock:
    """A LinearClient mock: ``fetch_queue_membership`` answers the Build-queue
    question (or raises ``LinearNotFound``); the comment + label primitives are
    no-op AsyncMocks.

    Since #248 the *decision* lives in the backend, not the verb, so the stub
    states it directly: ``on_queue`` is the answer, ``ticket_project`` the
    container the backend reports. The real per-backend comparison is pinned at
    the backend level (``test_linear.py`` / ``test_github.py``), which is where it
    now belongs.
    """
    from harness.linear import LinearNotFound

    mock = MagicMock()
    if not_found:
        mock.fetch_queue_membership = AsyncMock(side_effect=LinearNotFound("nope"))
    else:
        mock.fetch_queue_membership = AsyncMock(
            return_value=QueueMembership(on_queue=on_queue, project=ticket_project)
        )
    mock.post_comment = AsyncMock(return_value=None)
    mock.apply_label = AsyncMock(return_value=None)
    mock.assign_to_viewer = AsyncMock(return_value=None)
    return mock


def test_defer_unscoped_refuses_a_ticket_off_the_queue(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Unset scope is not "accept anything" — the seam still bounds the write.

    The membership gate is the only thing between an operator-supplied ticket
    identifier and three tracker writes, so removing the `repo.project`
    precondition must not remove the bound: on Linear it moves from project to
    team. Nothing is written when the seam says off-queue.
    """
    _write_context(tmp_path, project=None)
    db = tmp_path / "harness.db"
    stub = _make_stub(on_queue=False, ticket_project=None)

    result = _invoke(
        ["defer", "OTHER-1", "--reason", "x", "--db", str(db), "--json"],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 2, result.output
    assert json.loads(result.stdout)["reason"] == "not_on_build_queue"
    stub.post_comment.assert_not_awaited()
    stub.apply_label.assert_not_awaited()
    stub.assign_to_viewer.assert_not_awaited()
    assert _fetch_defer_events(db) == []


def test_defer_unscoped_refusal_names_the_whole_tracker_queue(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The refusal says which queue was in force — `reclaim`'s phrasing."""
    _write_context(tmp_path, project=None)
    stub = _make_stub(on_queue=False, ticket_project=None)

    result = _invoke(
        ["defer", "OTHER-1", "--reason", "x", "--db", str(tmp_path / "h.db")],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 2
    assert "the whole tracker queue" in result.output


def test_defer_unscoped_human_output_never_prints_none(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The non-JSON line must not interpolate a bare `None` (#248)."""
    _write_context(tmp_path, project=None)
    stub = _make_stub(ticket_project=None)

    result = _invoke(
        ["defer", "ERP-221", "--reason", "x", "--db", str(tmp_path / "h.db")],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    assert "None" not in result.output
    assert "the whole tracker queue" in result.output


def test_defer_unscoped_reports_the_tickets_own_project(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """With no scope the effective project is the ticket's own, not `null`.

    Since #338 the effective project is observable on the JSON envelope only —
    there is no ledger row to read it back from.
    """
    _write_context(tmp_path, project=None)
    db = tmp_path / "harness.db"
    stub = _make_stub(ticket_project="Design System")

    result = _invoke(
        ["defer", "ERP-209", "--reason", "x", "--db", str(db), "--json"],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["project"] == "Design System"
    assert _fetch_defer_events(db) == []


def test_defer_scoped_reports_the_configured_project_not_the_tickets(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Scoped, the configured value wins — the rule #248 established, still
    observable on the envelope now that the ledger row is gone (#338)."""
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    # A GitHub-shaped case: the backend reports the board title, which need not
    # equal a descriptive `repo.project`.
    stub = _make_stub(ticket_project="Board Title")

    result = _invoke(
        ["defer", "CAL-1", "--reason", "x", "--db", str(db), "--json"],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["project"] == _BUILD_PROJECT
    assert _fetch_defer_events(db) == []


def _make_labelled_stub(existing_labels: list[str]) -> MagicMock:
    """A stub whose ``apply_label`` *appends* to a tracked label list, so a test
    can assert pre-existing labels survive a new label being additively applied
    — the CLI-level shape of "additive", not just the mutation name."""
    mock = MagicMock()
    mock.fetch_queue_membership = AsyncMock(
        return_value=QueueMembership(on_queue=True, project=_BUILD_PROJECT)
    )
    mock.post_comment = AsyncMock(return_value=None)
    mock.assign_to_viewer = AsyncMock(return_value=None)
    labels = list(existing_labels)

    async def _apply_label(_ticket: str, name: str) -> None:
        labels.append(name)

    mock.apply_label = AsyncMock(side_effect=_apply_label)
    mock.labels = labels  # inspected by the test after the call
    return mock


def _invoke(args: list[str], repo_root: Path, stub: MagicMock, monkeypatch: Any) -> Any:
    monkeypatch.chdir(repo_root)
    with (
        patch("harness.tracker.LinearClient", return_value=stub),
        patch("harness.tracker.linear_api_key", return_value="test-key"),
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

    return run_sync(_select())


# ===========================================================================
# AC: an unscoped repo (`repo.project` absent) can still triage (#248)
# ===========================================================================


def test_defer_succeeds_on_an_unscoped_repo(tmp_path: Path, monkeypatch: Any) -> None:
    """`repo.project` absent is the whole tracker queue, not a refusal (#248).

    The ticket's repro: #174/#175/#176 made scope nullable everywhere *except*
    the two triage verbs, so a repo that adopted the unscoped mode got a working
    build loop and simultaneously lost both halves of triage. Nothing could be
    deferred and nothing already held could be released — through the audited
    path — leaving the held pile drainable only by hand-rolled tracker writes,
    which is exactly what these verbs exist to replace.

    The seam answers membership for its own queue, so with no scope configured
    the verb writes normally and reports the *ticket's own* project — here
    ``None``, a Linear issue inside the team but attached to no project.
    """
    _write_context(tmp_path, project=None)
    db = tmp_path / "harness.db"
    stub = MagicMock()
    stub.fetch_queue_membership = AsyncMock(
        return_value=QueueMembership(on_queue=True, project=None)
    )
    stub.post_comment = AsyncMock(return_value=None)
    stub.apply_label = AsyncMock(return_value=None)
    stub.assign_to_viewer = AsyncMock(return_value=None)

    result = _invoke(
        ["defer", "ERP-221", "--reason", "needs a call", "--db", str(db), "--json"],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "deferred"
    assert payload["project"] is None
    stub.post_comment.assert_awaited_once()
    stub.apply_label.assert_awaited_once()
    stub.assign_to_viewer.assert_awaited_once()
    assert _fetch_defer_events(db) == []


# ===========================================================================
# AC: happy path — comment + additive label + assignment, and no ledger row
# ===========================================================================


def test_defer_posts_comment_and_applies_label(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """``defer`` posts the reason as a comment and additively applies
    ``decision``; exits 0, writing nothing to the ledger (#338)."""
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
    stub.apply_label.assert_awaited_once_with("CAL-999", "decision")
    assert _fetch_defer_events(db) == []


def test_defer_json_success_output(tmp_path: Path, monkeypatch: Any) -> None:
    """``--json`` on a successful defer emits the typed output — outcome
    ``deferred``, the bound Build queue, and a ``run_id`` that is now always
    ``null`` (the deprecated compatibility field, #338)."""
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub()

    result = _invoke(
        ["defer", "CAL-999", "--reason", "needs a call", "--db", str(db), "--json"],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ticket"] == "CAL-999"
    assert payload["outcome"] == "deferred"
    assert payload["project"] == _BUILD_PROJECT
    assert "run_id" in payload
    assert payload["run_id"] is None


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
# AC-1: --needs selects the label; default remains `decision`
# ===========================================================================


def test_defer_needs_operator_applies_operator_label(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """``--needs operator`` applies the ``operator`` label (a hands-on hold), not
    ``decision`` — the three triage kinds of the ticket protocol (CAL-1167,
    ADR 0006)."""
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub()

    result = _invoke(
        ["defer", "CAL-999", "--reason", "needs an interactive relink",
         "--needs", "operator", "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    stub.apply_label.assert_awaited_once()
    _, label_arg = stub.apply_label.await_args.args
    assert label_arg == "operator"


def test_defer_needs_input_applies_input_label(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """``--needs input`` applies the ``input`` label — the third hold kind (ADR
    0006, #191): the operator must supply something the run cannot, distinct
    from a judgment call (``decision``) and an interactive session (``operator``)."""
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub()

    result = _invoke(
        ["defer", "CAL-999", "--reason", "needs a credential provisioned",
         "--needs", "input", "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    stub.apply_label.assert_awaited_once()
    _, label_arg = stub.apply_label.await_args.args
    assert label_arg == "input"


def test_defer_needs_input_preserves_existing_labels(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The ``input`` label is applied additively — a pre-existing label on the
    ticket survives, proven at the CLI-invocation level (not just by which
    mutation primitive is called)."""
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_labelled_stub(["bug"])

    result = _invoke(
        ["defer", "CAL-999", "--reason", "needs infra stood up",
         "--needs", "input", "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    assert stub.labels == ["bug", "input"]


def test_defer_rejects_unknown_needs_kind(tmp_path: Path, monkeypatch: Any) -> None:
    """``--needs`` accepts only ``decision`` / ``input`` / ``operator``; anything
    else is an invocation error (exit 2), with no write."""
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub()

    result = _invoke(
        ["defer", "CAL-999", "--reason", "x", "--needs", "bogus", "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 2, result.output
    stub.post_comment.assert_not_awaited()
    stub.apply_label.assert_not_awaited()


# ===========================================================================
# AC-2: the verb assigns the ticket to the runtime-resolved viewer (operator)
# ===========================================================================


def test_defer_assigns_ticket_to_viewer(tmp_path: Path, monkeypatch: Any) -> None:
    """``defer`` assigns the ticket to the operator (Linear ``viewer``) — the
    machine-readable "a human holds this" signal the held-tickets skip rule reads."""
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub()

    result = _invoke(
        ["defer", "CAL-999", "--reason", "needs a call", "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    stub.assign_to_viewer.assert_awaited_once()
    (ticket_arg,) = stub.assign_to_viewer.await_args.args
    assert ticket_arg == "CAL-999"


# ===========================================================================
# AC-3: the hold label carries the needs kind (the ledger event that also did
# is retired — #338)
# ===========================================================================


def test_defer_default_needs_applies_the_decision_label(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """With no ``--needs`` the deferral holds for a ``decision``.

    Before #338 the hold kind was durably recorded twice — as the label on the
    ticket and as the ledger event's ``needs`` field. Only the label survives,
    and it is the better record: it is what ``work-discovery`` and ``/decision``
    actually read. The explicit ``--needs operator`` / ``--needs input`` cases
    are covered by ``test_defer_needs_*_applies_*_label`` above; this pins the
    default, which nothing else exercises.
    """
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub()

    result = _invoke(
        ["defer", "CAL-999", "--reason", "x", "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 0, result.output
    stub.apply_label.assert_awaited_once_with("CAL-999", "decision")
    assert _fetch_defer_events(db) == []


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
    payload = json.loads(result.stdout)
    assert payload["reason"] == "ticket_not_found"
    stub.post_comment.assert_not_awaited()
    stub.apply_label.assert_not_awaited()
    stub.assign_to_viewer.assert_not_awaited()
    assert _fetch_defer_events(db) == []


def test_defer_refuses_ticket_on_another_project(tmp_path: Path, monkeypatch: Any) -> None:
    """A ticket on a different project than ``repo.project`` is refused (exit 2)."""
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub(on_queue=False, ticket_project="Some Other Project")

    result = _invoke(
        ["defer", "CAL-777", "--reason", "x", "--db", str(db), "--json"],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 2, result.output
    payload = json.loads(result.stdout)
    assert payload["reason"] == "not_on_build_queue"
    stub.post_comment.assert_not_awaited()
    stub.apply_label.assert_not_awaited()
    stub.assign_to_viewer.assert_not_awaited()
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
    stub.fetch_queue_membership.assert_not_awaited()
    stub.post_comment.assert_not_awaited()
    stub.apply_label.assert_not_awaited()
    stub.assign_to_viewer.assert_not_awaited()
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
    assert comment_body == "A long\nmulti-line\ntriage rationale."
    assert _fetch_defer_events(db) == []


# ===========================================================================
# A refused defer writes nothing — and since #338, neither does a successful one
# ===========================================================================
#
# #264 gave the ``defer`` event a typed ``duration_ms`` column and this file
# pinned it. #338 retired the event, so that telemetry is **gone**, not moved:
# a held-ticket transition's latency is no longer measured anywhere. That is an
# accepted, recorded cost of making the tracker the sole record for these two
# verbs — the duration was only ever readable through the synthetic row the
# ticket set out to delete. The refusal case below survives on its own merit:
# it pins that the membership gate still stands before any write.


def test_defer_refusal_writes_nothing(tmp_path: Path, monkeypatch: Any) -> None:
    """A refused defer performs no tracker write and no ledger write.

    The membership gate is the only bound between an arbitrary identifier and
    three authenticated mutations, so "refused" has to mean nothing happened.
    """
    _write_context(tmp_path)
    db = tmp_path / "harness.db"
    stub = _make_stub()
    stub.fetch_queue_membership = AsyncMock(
        return_value=QueueMembership(on_queue=False, project="Some Other Project")
    )

    result = _invoke(
        ["defer", "CAL-999", "--reason", "needs a human call", "--db", str(db)],
        tmp_path, stub, monkeypatch,
    )

    assert result.exit_code == 2, result.output
    stub.post_comment.assert_not_awaited()
    stub.apply_label.assert_not_awaited()
    stub.assign_to_viewer.assert_not_awaited()
    assert _fetch_defer_events(db) == []
