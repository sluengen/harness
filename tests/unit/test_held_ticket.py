"""#338 — a held-ticket transition is recorded on the tracker, not in the ledger.

``defer`` and ``release`` each manufactured a synthetic terminal ``runs`` row
(``workflow_name='defer'`` / ``'release'``, ``status='closed'``, no worktree)
for the sole purpose of satisfying the ``events.run_id`` foreign key, then
appended an event to it. That made two small tracker actions look like build
lifecycle runs in every ledger-backed view, and the audit machinery was never
read by close gating or recovery. ADR 0009 had already named the pattern "a
workaround, not a pattern" and declined to extend it to run-less refusals; this
ticket stops extending it to held-ticket transitions too.

The tracker issue carries the durable evidence that matters — the comment or
resolution, the hold label, the assignment, and project membership — and that
is now the whole audit trail for these two verbs.

Contract under test (the ledger half; the transition bundles themselves are in
``test_cli_defer.py`` / ``test_cli_release.py``):

* A successful ``defer`` / ``release`` writes **no** ``runs`` row and **no**
  ``defer`` / ``release`` event.
* ``--json`` retains ``run_id`` as a deprecated compatibility field, always
  ``null``, so a caller parsing the envelope does not break on a missing key.
* A ledger already holding historical ``defer`` / ``release`` rows still opens
  and reads back unchanged — no migration, no deletion.

**Why every test seeds the ledger first.** After this change a held-ticket
transition never calls ``init_db``, so on a fresh repo the database may not
exist at all — and "no new ``runs`` row" would then pass against a *missing
table* rather than against the verb's behaviour. Seeding an unrelated run row
first makes the tables exist, so each assertion below is measuring the verb and
not the absence of a file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from harness._time import iso_z
from harness.cli import app
from harness.state import store
from harness.tracker_errors import TrackerRequestError
from harness.tracker_queue import QueueMembership
from tests._asyncutil import run_sync

cli_runner = CliRunner()

_BUILD_PROJECT = "Harness v3"

#: The unrelated run row every test seeds, so the ``runs``/``events`` tables
#: exist before the verb runs. Its id is asserted to be the *only* row left.
_SEEDED_RUN = "01SEEDEDRUNROWFORHOLDSTEST"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _write_context(repo_root: Path, *, project: str | None = _BUILD_PROJECT) -> None:
    """A minimal CONTEXT.md the verbs read for ``repo.project`` + the backend."""
    project_line = f"  project: {project}\n" if project is not None else ""
    (repo_root / "CONTEXT.md").write_text(
        "repo:\n"
        "  name: harness\n"
        "  linear: CAL\n"
        f"{project_line}"
        "layers:\n"
        "  linear: true\n"
    )


def _seed_ledger(db_path: Path) -> None:
    """Create the ledger with one unrelated run row and one historical event.

    The event is written with direct SQL rather than through ``EventEmitter``
    because what is under test is that a ledger *already on disk* keeps reading
    back — the shape a historical row has, independent of whether any live
    emitter would still accept that type today.
    """
    now = iso_z()

    async def _write() -> None:
        await store.init_db(db_path)
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs ("
                "run_id, workflow_name, workflow_version, status, "
                "state_json, inputs_json, ticket, started_at, completed_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_SEEDED_RUN, "defer", 0, "closed", "{}", "{}", "CAL-1", now, now),
            )
            await conn.execute(
                "INSERT INTO events (run_id, event_type, timestamp, data_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    _SEEDED_RUN,
                    "defer",
                    now,
                    json.dumps(
                        {
                            "run_id": _SEEDED_RUN,
                            "ticket": "CAL-1",
                            "reason": "a historical deferral",
                            "project": _BUILD_PROJECT,
                            "needs": "decision",
                            "deferred_at": now,
                        }
                    ),
                ),
            )
            await conn.commit()

    run_sync(_write())


def _run_ids(db_path: Path) -> list[str]:
    """Every ``runs.run_id`` currently on the ledger, in insertion order."""

    async def _select() -> list[str]:
        async with store.connect(db_path) as conn:
            cur = await conn.execute("SELECT run_id FROM runs ORDER BY rowid")
            rows = await cur.fetchall()
        return [r[0] for r in rows]

    return run_sync(_select())


def _events_of_type(db_path: Path, event_type: str) -> list[dict[str, Any]]:
    """Every event payload of ``event_type`` currently on the ledger."""

    async def _select() -> list[dict[str, Any]]:
        async with store.connect(db_path) as conn:
            cur = await conn.execute(
                "SELECT data_json FROM events WHERE event_type = ? ORDER BY id",
                (event_type,),
            )
            rows = await cur.fetchall()
        return [json.loads(r[0]) for r in rows]

    return run_sync(_select())


def _make_stub() -> MagicMock:
    """A tracker stub answering the queue question and no-op'ing every write.

    Deliberately built against the ``Tracker`` protocol's method names only —
    no GitHub or Linear implementation detail — so this file cannot couple the
    seam to one backend.
    """
    mock = MagicMock()
    mock.fetch_queue_membership = AsyncMock(
        return_value=QueueMembership(on_queue=True, project=_BUILD_PROJECT)
    )
    mock.post_comment = AsyncMock(return_value=None)
    mock.apply_label = AsyncMock(return_value=None)
    mock.assign_to_viewer = AsyncMock(return_value=None)
    mock.remove_label = AsyncMock(return_value=None)
    mock.unassign_viewer = AsyncMock(return_value=None)
    mock.fetch_issue = AsyncMock(return_value={"description": "## Context\n\nbody"})
    mock.update_issue_body = AsyncMock(return_value=None)
    return mock


def _invoke(args: list[str], repo_root: Path, stub: MagicMock, monkeypatch: Any) -> Any:
    monkeypatch.chdir(repo_root)
    with (
        patch("harness.tracker.LinearClient", return_value=stub),
        patch("harness.tracker.linear_api_key", return_value="test-key"),
    ):
        return cli_runner.invoke(app, args)


def _setup(tmp_path: Path) -> Path:
    """A repo with a CONTEXT.md and a seeded ledger; returns the db path."""
    _write_context(tmp_path)
    db_path = tmp_path / ".harness" / "harness.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _seed_ledger(db_path)
    return db_path


# ===========================================================================
# AC: a successful hold/release creates no runs row and no ledger event
# ===========================================================================


def test_defer_creates_no_runs_row(tmp_path: Path, monkeypatch: Any) -> None:
    """A successful defer leaves the ``runs`` table exactly as it found it.

    The seeded row is what makes this non-vacuous: the table demonstrably
    exists and is readable, so an empty *delta* is the verb's doing.
    """
    db = _setup(tmp_path)
    result = _invoke(
        ["defer", "CAL-999", "--reason", "needs a human call"],
        tmp_path,
        _make_stub(),
        monkeypatch,
    )
    assert result.exit_code == 0, result.output
    assert _run_ids(db) == [_SEEDED_RUN]


def test_defer_appends_no_defer_event(tmp_path: Path, monkeypatch: Any) -> None:
    """A successful defer appends no new ``defer`` event."""
    db = _setup(tmp_path)
    result = _invoke(
        ["defer", "CAL-999", "--reason", "needs a human call"],
        tmp_path,
        _make_stub(),
        monkeypatch,
    )
    assert result.exit_code == 0, result.output
    events = _events_of_type(db, "defer")
    assert [e["ticket"] for e in events] == ["CAL-1"]


def test_release_creates_no_runs_row(tmp_path: Path, monkeypatch: Any) -> None:
    """A successful release leaves the ``runs`` table exactly as it found it."""
    db = _setup(tmp_path)
    result = _invoke(
        ["release", "CAL-999", "--resolution", "ship it as specified"],
        tmp_path,
        _make_stub(),
        monkeypatch,
    )
    assert result.exit_code == 0, result.output
    assert _run_ids(db) == [_SEEDED_RUN]


def test_release_appends_no_release_event(tmp_path: Path, monkeypatch: Any) -> None:
    """A successful release appends no ``release`` event."""
    db = _setup(tmp_path)
    result = _invoke(
        ["release", "CAL-999", "--resolution", "ship it as specified"],
        tmp_path,
        _make_stub(),
        monkeypatch,
    )
    assert result.exit_code == 0, result.output
    assert _events_of_type(db, "release") == []


# ===========================================================================
# AC: --json retains run_id as a deprecated, always-null compatibility field
# ===========================================================================


def test_defer_json_retains_run_id_as_null(tmp_path: Path, monkeypatch: Any) -> None:
    """``run_id`` is still *present* — a caller reading it must not KeyError —
    and is ``null``, because a defer no longer creates a run."""
    _setup(tmp_path)
    result = _invoke(
        ["defer", "CAL-999", "--reason", "needs a human call", "--json"],
        tmp_path,
        _make_stub(),
        monkeypatch,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert "run_id" in payload
    assert payload["run_id"] is None


def test_release_json_retains_run_id_as_null(tmp_path: Path, monkeypatch: Any) -> None:
    """The release envelope keeps the same deprecated field, also ``null``."""
    _setup(tmp_path)
    result = _invoke(
        ["release", "CAL-999", "--resolution", "ship it", "--json"],
        tmp_path,
        _make_stub(),
        monkeypatch,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert "run_id" in payload
    assert payload["run_id"] is None


# ===========================================================================
# AC: an existing ledger holding historical rows stays readable, unmigrated
# ===========================================================================


def test_historical_defer_rows_survive_a_new_defer(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The historical row reads back byte-identical after a new defer runs.

    "Remains queryable without migration" is the claim; reading the payload
    back field-for-field is what measures it, rather than merely counting rows.
    """
    db = _setup(tmp_path)
    before = _events_of_type(db, "defer")
    result = _invoke(
        ["defer", "CAL-999", "--reason", "needs a human call"],
        tmp_path,
        _make_stub(),
        monkeypatch,
    )
    assert result.exit_code == 0, result.output
    assert _events_of_type(db, "defer") == before
    assert before[0]["needs"] == "decision"
    assert before[0]["reason"] == "a historical deferral"


def test_historical_rows_still_parse_as_their_payload_model() -> None:
    """The retired-from-writing event types keep their payload readers.

    A reader deleted alongside the writer would make every historical row
    unreadable — the one outcome "do not migrate or delete" forbids.
    """
    from harness.events.payloads import DeferEventData, ReleaseEventData

    now = iso_z()
    defer = DeferEventData.model_validate(
        {
            "run_id": _SEEDED_RUN,
            "ticket": "CAL-1",
            "reason": "a historical deferral",
            "project": _BUILD_PROJECT,
            "needs": "decision",
            "deferred_at": now,
        }
    )
    release = ReleaseEventData.model_validate(
        {
            "run_id": _SEEDED_RUN,
            "ticket": "CAL-1",
            "project": _BUILD_PROJECT,
            "needs": "decision",
            "released_at": now,
        }
    )
    assert defer.needs == "decision"
    assert release.needs == "decision"


# ===========================================================================
# The seam itself, against a fake implementing the ``Tracker`` protocol
# ===========================================================================
#
# These exercise ``held_ticket.hold`` / ``.release`` directly rather than
# through Typer, because the ACs are about the *transition* — its order, its
# idempotency, and what it reports when a step fails part-way. The fake is
# built to the protocol, not to Linear or GitHub, which is what keeps the seam
# from acquiring a backend-specific assumption by way of its tests.


class _FakeTracker:
    """An in-memory tracker recording call order and converging on retry.

    Deliberately a real class rather than a ``MagicMock``: ``isinstance``
    against the ``@runtime_checkable`` ``Tracker`` protocol then means
    something (a mock satisfies any protocol), and label/assignment state that
    actually converges is what makes the idempotency assertions real.
    """

    def __init__(self, *, labels: list[str] | None = None, body: str = "## Context") -> None:
        self.calls: list[str] = []
        self.labels: list[str] = list(labels or [])
        self.body = body
        self.comments: list[str] = []
        self.assignee: str | None = None
        self.fail_on: dict[str, Exception] = {}

    def _step(self, name: str) -> None:
        self.calls.append(name)
        exc = self.fail_on.get(name)
        if exc is not None:
            raise exc

    async def fetch_queue_membership(self, identifier: str, *, project: str | None = None) -> Any:
        self.calls.append("fetch_queue_membership")
        return QueueMembership(on_queue=True, project=project or _BUILD_PROJECT)

    async def post_comment(self, identifier: str, body: str) -> None:
        self._step("post_comment")
        self.comments.append(body)

    async def apply_label(self, identifier: str, name: str) -> None:
        self._step("apply_label")
        if name not in self.labels:  # additive, and converges on retry
            self.labels.append(name)

    async def assign_to_viewer(self, identifier: str) -> None:
        self._step("assign_to_viewer")
        self.assignee = "operator"

    async def remove_label(self, identifier: str, name: str) -> None:
        self._step("remove_label")
        if name in self.labels:
            self.labels.remove(name)

    async def unassign_viewer(self, identifier: str) -> None:
        self._step("unassign_viewer")
        self.assignee = None

    async def fetch_issue(self, identifier: str) -> dict[str, Any]:
        self._step("fetch_issue")
        return {"description": self.body}

    async def update_issue_body(self, identifier: str, body: str) -> None:
        self._step("update_issue_body")
        self.body = body

    # --- remainder of the protocol, unused by this seam ---------------------
    async def fetch_reclaimable_issues(self, *a: Any, **k: Any) -> Any: ...
    async def fetch_resume_branch(self, identifier: str) -> str | None: ...
    async def fetch_handoff_branch(self, identifier: str) -> str | None: ...
    async def fetch_design_comment(self, identifier: str) -> str | None: ...
    async def transition_to_in_progress(self, identifier: str) -> None: ...
    async def transition_to_in_review(self, identifier: str) -> None: ...
    async def transition_to_done(self, identifier: str) -> None: ...
    async def transition_to_unstarted(self, identifier: str) -> None: ...
    async def create_issue(self, *a: Any, **k: Any) -> Any: ...


def _seam(tmp_path: Path, fake: _FakeTracker) -> Any:
    """Patch the seam's client factory to hand back ``fake``."""
    _write_context(tmp_path)
    return patch("harness.cli.held_ticket.tracker_client", return_value=fake)


def test_the_fake_satisfies_the_tracker_protocol() -> None:
    """A floor: without this, every assertion below could be exercising a fake
    that has drifted from the seam the verbs actually call."""
    from harness.tracker import Tracker

    assert isinstance(_FakeTracker(), Tracker)


def test_hold_calls_comment_then_label_then_assign(tmp_path: Path) -> None:
    """The explanation lands on the ticket before it is marked held."""
    from harness.cli.held_ticket import HoldKind, hold

    fake = _FakeTracker()
    with _seam(tmp_path, fake):
        run_sync(hold(tmp_path, "CAL-1", reason="why", kind=HoldKind.decision))

    assert fake.calls == [
        "fetch_queue_membership",
        "post_comment",
        "apply_label",
        "assign_to_viewer",
    ]


def test_release_calls_resolution_then_label_then_unassign(tmp_path: Path) -> None:
    """The resolution is durable before the ticket stops being held."""
    from harness.cli.held_ticket import HoldKind, release

    fake = _FakeTracker(labels=["decision"])
    with _seam(tmp_path, fake):
        run_sync(release(tmp_path, "CAL-1", resolution="go with A", kind=HoldKind.decision))

    assert fake.calls == [
        "fetch_queue_membership",
        "fetch_issue",
        "update_issue_body",
        "remove_label",
        "unassign_viewer",
    ]


def test_hold_preserves_unrelated_labels(tmp_path: Path) -> None:
    """Additive: a hold adds its kind and disturbs nothing already there."""
    from harness.cli.held_ticket import HoldKind, hold

    fake = _FakeTracker(labels=["bug", "p2"])
    with _seam(tmp_path, fake):
        run_sync(hold(tmp_path, "CAL-1", reason="why", kind=HoldKind.input))

    assert fake.labels == ["bug", "p2", "input"]


def test_release_removes_only_the_selected_hold_label(tmp_path: Path) -> None:
    """A release drops its own kind's label and leaves every other alone —
    including a *different* hold kind, which is not this release's to clear."""
    from harness.cli.held_ticket import HoldKind, release

    fake = _FakeTracker(labels=["bug", "decision", "operator"])
    with _seam(tmp_path, fake):
        run_sync(release(tmp_path, "CAL-1", resolution="A", kind=HoldKind.decision))

    assert fake.labels == ["bug", "operator"]


def test_a_repeated_hold_converges_and_appends_a_second_comment(tmp_path: Path) -> None:
    """Retry is safe: the label and assignment do not duplicate.

    The comment deliberately *does* repeat — a restated reason is new
    information and the tracker's comment stream is append-only history. Pinned
    rather than left unstated, so a future "dedupe the comment" change has to
    argue with a test instead of silently discarding an operator's note.
    """
    from harness.cli.held_ticket import HoldKind, hold

    fake = _FakeTracker()
    with _seam(tmp_path, fake):
        run_sync(hold(tmp_path, "CAL-1", reason="why", kind=HoldKind.decision))
        run_sync(hold(tmp_path, "CAL-1", reason="why", kind=HoldKind.decision))

    assert fake.labels == ["decision"]
    assert fake.assignee == "operator"
    assert len(fake.comments) == 2


def test_a_repeated_release_converges(tmp_path: Path) -> None:
    """Releasing an already-released ticket is a no-op that still exits clean."""
    from harness.cli.held_ticket import HoldKind, release

    fake = _FakeTracker(labels=["decision"])
    with _seam(tmp_path, fake):
        first = run_sync(release(tmp_path, "CAL-1", resolution="A", kind=HoldKind.decision))
        second = run_sync(release(tmp_path, "CAL-1", resolution="A", kind=HoldKind.decision))

    assert first.outcome == second.outcome == "released"
    assert fake.labels == []
    assert fake.assignee is None
    # One ``## Resolution`` section, not two — the body converged rather than accreted.
    assert fake.body.count("## Resolution") == 1


@pytest.mark.parametrize(
    ("failing_call", "expected_step", "never_called"),
    [
        ("post_comment", "comment", ["apply_label", "assign_to_viewer"]),
        ("apply_label", "label", ["assign_to_viewer"]),
        ("assign_to_viewer", "assign", []),
    ],
)
def test_hold_partial_failure_names_the_step_and_stops(
    tmp_path: Path, failing_call: str, expected_step: str, never_called: list[str]
) -> None:
    """A bundle that fails part-way names the failed step and goes no further.

    The tracker APIs are not transactional, so the operator's only route back
    to a consistent ticket is knowing which step did not happen.
    """
    from harness.cli._verb import VerbError
    from harness.cli.held_ticket import HoldKind, hold

    fake = _FakeTracker()
    fake.fail_on[failing_call] = TrackerRequestError("boom")

    with _seam(tmp_path, fake), pytest.raises(VerbError) as excinfo:
        run_sync(hold(tmp_path, "CAL-1", reason="why", kind=HoldKind.decision))

    assert excinfo.value.code == 2
    assert excinfo.value.reason == "tracker_error"
    assert excinfo.value.extra == {"step": expected_step}
    for call in never_called:
        assert call not in fake.calls


@pytest.mark.parametrize(
    ("failing_call", "expected_step", "never_called"),
    [
        ("update_issue_body", "resolution", ["remove_label", "unassign_viewer"]),
        ("remove_label", "label", ["unassign_viewer"]),
        ("unassign_viewer", "unassign", []),
    ],
)
def test_release_partial_failure_names_the_step_and_stops(
    tmp_path: Path, failing_call: str, expected_step: str, never_called: list[str]
) -> None:
    """The release mirror — and the ``resolution`` case is the load-bearing one:
    a body write that fails must leave the ticket visibly held."""
    from harness.cli._verb import VerbError
    from harness.cli.held_ticket import HoldKind, release

    fake = _FakeTracker(labels=["decision"])
    fake.fail_on[failing_call] = TrackerRequestError("boom")

    with _seam(tmp_path, fake), pytest.raises(VerbError) as excinfo:
        run_sync(release(tmp_path, "CAL-1", resolution="A", kind=HoldKind.decision))

    assert excinfo.value.code == 2
    assert excinfo.value.reason == "tracker_error"
    assert excinfo.value.extra == {"step": expected_step}
    for call in never_called:
        assert call not in fake.calls


def test_a_failed_resolution_write_leaves_the_ticket_held(tmp_path: Path) -> None:
    """The ordering rule's whole point, asserted on the resulting state rather
    than on the call list: the hold label and the assignment both survive."""
    from harness.cli._verb import VerbError
    from harness.cli.held_ticket import HoldKind, release

    fake = _FakeTracker(labels=["decision"])
    fake.assignee = "operator"
    fake.fail_on["update_issue_body"] = TrackerRequestError("boom")

    with _seam(tmp_path, fake), pytest.raises(VerbError):
        run_sync(release(tmp_path, "CAL-1", resolution="A", kind=HoldKind.decision))

    assert fake.labels == ["decision"]
    assert fake.assignee == "operator"


# ===========================================================================
# compose_resolution_body
# ===========================================================================


def test_compose_appends_a_resolution_to_a_body_without_one() -> None:
    from harness.cli.held_ticket import compose_resolution_body

    out = compose_resolution_body("## Context\n\nsome context", "Go with A.")
    assert "## Context" in out
    assert out.rstrip().endswith("Go with A.")
    assert out.count("## Resolution") == 1


def test_compose_replaces_a_prior_resolution() -> None:
    """A repeated release replaces rather than accretes."""
    from harness.cli.held_ticket import compose_resolution_body

    first = compose_resolution_body("## Context\n\nctx", "Old answer.")
    second = compose_resolution_body(first, "New answer.")
    assert second.count("## Resolution") == 1
    assert "Old answer." not in second
    assert "New answer." in second
    assert "## Context" in second


def test_compose_handles_an_empty_body() -> None:
    """An issue with no body still gets exactly one well-formed section.

    The result is leading-newline padded (``\\n\\n## Resolution…``) because the
    composer joins onto a stripped base unconditionally. That is pre-#338
    behaviour, preserved verbatim and invisible once rendered, so it is pinned
    as-is rather than tidied — this ticket changes where the transition lives,
    not what it writes.
    """
    from harness.cli.held_ticket import compose_resolution_body

    out = compose_resolution_body("", "Go with A.")
    assert out.count("## Resolution") == 1
    assert out.strip() == "## Resolution\n\nGo with A."
    assert out.endswith("\n")


# ===========================================================================
# Structural guards — the mechanised form of "no new ledger writes"
# ===========================================================================


def _imported_modules(path: Path) -> set[str]:
    """Every module name ``path`` imports, by AST rather than by grep.

    A regex over the source would be fooled by the word appearing in a
    docstring — and both modules below discuss the ledger they no longer write
    to at length.
    """
    import ast

    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


_HARNESS_ROOT = Path(__file__).parent.parent.parent / "harness"


@pytest.mark.parametrize("module", ["defer.py", "release.py"])
def test_the_verb_modules_import_no_ledger_writer(module: str) -> None:
    """Neither verb can write the ledger, because neither can reach a writer.

    This is what stops the synthetic ``runs`` row coming back by accident: a
    re-added ``EventEmitter`` / ``store`` / ``generate_run_id`` import fails
    here before it can grow a caller.
    """
    imported = _imported_modules(_HARNESS_ROOT / "cli" / module)
    banned = {"harness.events.emitter", "harness.state.store", "harness.identity"}
    assert imported & banned == set()


def test_the_guard_catches_a_reintroduced_ledger_writer(tmp_path: Path) -> None:
    """Negative control: the guard must actually fire on the thing it bans.

    Without this, a scanner that silently returned an empty set would pass the
    test above against a module that imports every writer there is.
    """
    offender = tmp_path / "regressed.py"
    offender.write_text(
        "from harness.events.emitter import EventEmitter\nx = EventEmitter\n"
    )
    assert "harness.events.emitter" in _imported_modules(offender)


def test_the_seam_imports_no_backend_client() -> None:
    """The seam talks to the ``Tracker`` protocol, never to a named backend —
    the same invariant ``test_promote_no_direct_tracker_client`` pins for
    ``promote``, applied where held-ticket state is now decided."""
    imported = _imported_modules(_HARNESS_ROOT / "cli" / "held_ticket.py")
    assert "harness.linear" not in imported
    assert "harness.github" not in imported
