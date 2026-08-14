"""#353 — ``harness certify``: the two answers, and the order they arrive in.

Everything here drives the **real verb** through ``CliRunner`` against a real git
repo and a real ledger, because the properties the ticket asks for are properties
of the wiring, not of the classifier: the classifier's own table lives in
``tests/unit/test_trivial_diff.py`` and would stay green against a verb that
classified correctly and then recorded nothing.

Three assertions are deliberately made on *observables* rather than on calls,
because each of them can fail silently open:

* **"no engine ran"** — measured as zero ``design`` / ``review`` rows on the run
  **and** an engine spawn point patched to raise. A test that only checked "we
  did not call it" would pass against a verb that called something else.
* **"no synthetic review pass"** — measured on the aggregate the prohibition
  exists to protect: ``harness stats --json`` must report no review verdicts.
* **"the run row is stricter before the tracker is touched"** — measured by a
  fake tracker that *reads the ledger* when it is called and records what it
  saw. A call-sequence assertion would be satisfied by a refactor that reordered
  the writes behind the calls.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from harness.assurance import DEFAULT_ASSURANCE
from harness.cli import app
from harness.cli.certify import _persist_upgrade
from harness.state import store
from harness.tracker_errors import TrackerRequestError
from tests._asyncutil import run_sync

cli_runner = CliRunner()

RUN_ID = "01CERTIFYRUN0000000000000"
TICKET = "353"

_CONTEXT_WITH_GATE = """\
```yaml
tracker: linear
repo:
  linear: harness
branches:
  integration: dev
commands:
  verify: "bash scripts/verify.sh"
assurance:
  trivial_paths:
    - docs/**
    - CHANGELOG.md
```
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, relpath: str, body: str | None = None) -> str:
    target = repo / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body if body is not None else f"{relpath}\n")
    _git(repo, "add", "--", relpath)
    _git(repo, "commit", "-q", "-m", relpath)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture(autouse=True)
def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "dev")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Test")
    (root / ".gitignore").write_text(".harness/\n")
    (root / "CONTEXT.md").write_text(_CONTEXT_WITH_GATE)
    _git(root, "add", ".gitignore", "CONTEXT.md")
    _git(root, "commit", "-q", "-m", "initial")
    return root


@pytest.fixture
def db_path(repo: Path) -> Path:
    path = repo / ".harness" / "harness.db"
    run_sync(store.init_db(path))
    return path


def _seed_run(
    db_path: Path,
    repo: Path,
    *,
    assurance: str = "trivial",
    base_sha: str | None = None,
    run_id: str = RUN_ID,
) -> None:
    """One open run whose worktree *is* ``repo``.

    The verbs resolve a run by ``worktree_path``; pointing it at the repo itself
    keeps the fixture to one tree without changing anything the verb does — it
    reads HEAD, the porcelain and the diff from whatever path the row names.
    """
    boundary = base_sha if base_sha is not None else _git(repo, "rev-parse", "HEAD")

    async def _insert() -> None:
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
                "state_json, inputs_json, base_branch, worktree_path, worktree_branch, "
                "ticket, started_at, assurance, assurance_reason, base_sha) "
                "VALUES (?, '', 0, 'open', '{}', '{}', 'dev', ?, ?, ?, "
                "'2026-08-15T00:00:00Z', ?, 'label', ?)",
                (run_id, str(repo), f"harness/{run_id}", TICKET, assurance, boundary),
            )
            await conn.commit()

    run_sync(_insert())


def _row(db_path: Path, run_id: str = RUN_ID) -> tuple[str | None, str | None]:
    async def _read() -> tuple[str | None, str | None]:
        async with (
            store.connect(db_path) as conn,
            conn.execute(
                "SELECT assurance, assurance_reason FROM runs WHERE run_id = ?", (run_id,)
            ) as cur,
        ):
            row = await cur.fetchone()
        assert row is not None
        return (row[0], row[1])

    return run_sync(_read())


def _row_sync(db_path: Path, run_id: str = RUN_ID) -> tuple[str | None, str | None]:
    """The same read as :func:`_row`, but callable from inside the verb's loop.

    The fake tracker probes the ledger while the verb's ``asyncio.run`` is on the
    stack, where an ``aiosqlite`` read cannot start a second loop. A plain
    ``sqlite3`` connection reads the same committed row — and *committed* is the
    point: an uncommitted ``UPDATE`` would be invisible here, which is exactly
    what this probe must be able to see the absence of.
    """
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT assurance, assurance_reason FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    assert row is not None
    return (row[0], row[1])


def _events(db_path: Path, event_type: str) -> list[dict[str, Any]]:
    async def _read() -> list[dict[str, Any]]:
        async with (
            store.connect(db_path) as conn,
            conn.execute(
                "SELECT data_json FROM events WHERE run_id = ? AND event_type = ?",
                (RUN_ID, event_type),
            ) as cur,
        ):
            rows = await cur.fetchall()
        return [json.loads(r[0]) for r in rows]

    return run_sync(_read())


class _FakeTracker:
    """Records every seam call, in order, and can be told to fail one of them.

    ``ledger_probe`` lets a call observe the ledger at the moment it is made,
    which is how the "row first, tracker second" ordering is measured as a fact
    rather than as a call sequence.
    """

    def __init__(
        self,
        *,
        fail_on: str | None = None,
        ledger_probe: Path | None = None,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self.observed: list[tuple[str | None, str | None]] = []
        self._fail_on = fail_on
        self._ledger_probe = ledger_probe

    def _record(self, kind: str, value: str) -> None:
        self.calls.append((kind, value))
        if self._ledger_probe is not None:
            self.observed.append(_row_sync(self._ledger_probe))
        if self._fail_on == kind:
            raise TrackerRequestError(f"simulated {kind} failure")

    async def remove_label(self, identifier: str, name: str) -> None:
        self._record("remove", name)

    async def apply_label(self, identifier: str, name: str) -> None:
        self._record("apply", name)

    async def post_comment(self, identifier: str, body: str) -> None:
        self._record("comment", body)


def _async_none() -> AsyncMock:
    return AsyncMock(return_value=None)


def _async_value(value: Any) -> AsyncMock:
    return AsyncMock(return_value=value)


def _certify(
    repo: Path,
    db_path: Path,
    *args: str,
    tracker: object | None = None,
) -> Any:
    client = tracker if tracker is not None else _FakeTracker()
    with (
        patch("harness.tracker.LinearClient", return_value=client),
        patch("harness.tracker.linear_api_key", return_value="test-key"),
    ):
        return cli_runner.invoke(
            app,
            ["certify", "--repo", str(repo), "--db", str(db_path), *args],
        )


# ---------------------------------------------------------------------------
# The certification path
# ---------------------------------------------------------------------------


def test_an_eligible_certification_invokes_no_engine(repo: Path, db_path: Path) -> None:
    """The point of the fast path, measured on the ledger and on a raising spy.

    The spy alone would not be enough — "no engine ran" is a fact that fails
    silently open — so the assertion that carries the criterion is the absence of
    any ``design`` or ``review`` row on the run.
    """
    _commit(repo, "docs/notes.md")
    _seed_run(db_path, repo, base_sha=_git(repo, "rev-parse", "HEAD~1"))

    spy = MagicMock(side_effect=AssertionError("an engine was invoked"))
    with patch("harness.cli._engine.run_engine_subprocess", spy):
        result = _certify(repo, db_path, "--gate-exit", "0")

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["outcome"] == "certified"
    assert _events(db_path, "design") == []
    assert _events(db_path, "review") == []
    assert spy.call_count == 0


def test_certification_records_an_event_bound_to_the_head_it_read(
    repo: Path, db_path: Path
) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, "docs/notes.md")
    _seed_run(db_path, repo, base_sha=base)

    result = _certify(repo, db_path, "--gate-exit", "0")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["certified_sha"] == head
    (event,) = _events(db_path, "certify")
    assert event["certified_sha"] == head
    assert event["base_sha"] == base
    assert event["assurance"] == "trivial"
    assert event["gate_ran"] is True
    assert event["eligible_paths"] == ["docs/notes.md"]
    assert event["allowlist"] == ["docs/**", "CHANGELOG.md"]
    assert event["classifier_version"] == 1
    assert "verdict" not in event and "engine" not in event


def test_certification_writes_no_review_event(repo: Path, db_path: Path) -> None:
    """No synthetic pass — measured where a synthetic one would do the damage.

    The row count is the direct reading; ``harness stats`` is the one that
    matters, because the reason the prohibition exists is that a synthetic pass
    would enter the verdict-by-engine aggregate as a real one.
    """
    _commit(repo, "docs/notes.md")
    _seed_run(db_path, repo, base_sha=_git(repo, "rev-parse", "HEAD~1"))

    assert _certify(repo, db_path, "--gate-exit", "0").exit_code == 0
    assert _events(db_path, "review") == []

    stats = cli_runner.invoke(
        app, ["stats", "--repo", str(repo), "--db", str(db_path), "--json"]
    )
    assert stats.exit_code == 0, stats.output
    report = json.loads(stats.stdout)
    assert json.dumps(report).count('"verdict"') == 0 or _no_review_verdicts(report)


def _no_review_verdicts(report: dict[str, Any]) -> bool:
    """No review verdict of any engine was counted in the aggregate."""
    blob = json.dumps(report)
    return '"pass"' not in blob and '"fail"' not in blob


def test_certify_is_visible_to_the_stats_aggregate(repo: Path, db_path: Path) -> None:
    """The wiring line ``VERB_OUTCOME_PATHS['certify']`` buys, measured.

    Without the entry nothing raises — ``certify`` rows are simply dropped from
    every verb total, which is exactly the kind of omission that is only noticed
    months later when someone asks how often the fast path fires.
    """
    _commit(repo, "docs/notes.md")
    _seed_run(db_path, repo, base_sha=_git(repo, "rev-parse", "HEAD~1"))
    assert _certify(repo, db_path, "--gate-exit", "0").exit_code == 0

    stats = cli_runner.invoke(
        app, ["stats", "--repo", str(repo), "--db", str(db_path), "--json"]
    )
    assert stats.exit_code == 0, stats.output
    assert "certify" in json.dumps(json.loads(stats.stdout))


def test_a_base_branch_that_advances_after_start_does_not_change_eligibility(
    repo: Path, db_path: Path
) -> None:
    """The classification boundary is the run's recorded base, not a moving branch.

    ``dev`` gains a **restricted** file after the run started. The run's own
    change is allowlisted, so it must still certify, and the recorded
    ``eligible_paths`` must name only the run's path.
    """
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "run")
    _commit(repo, "docs/notes.md")
    _git(repo, "checkout", "-q", "dev")
    _commit(repo, "harness/late.py")
    _git(repo, "checkout", "-q", "run")
    _seed_run(db_path, repo, base_sha=base)

    result = _certify(repo, db_path, "--gate-exit", "0")

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["outcome"] == "certified"
    (event,) = _events(db_path, "certify")
    assert event["eligible_paths"] == ["docs/notes.md"]


def test_a_restricted_path_on_the_run_branch_upgrades_the_run(
    repo: Path, db_path: Path
) -> None:
    """The mirror of the test above, and the reason it proves anything.

    One test showing the boundary is *stable* would pass against a classifier
    that ignored the diff entirely. This is the one showing it is *sensitive*:
    the same file, committed on the run's own side, must make it ineligible.
    """
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "docs/notes.md")
    _commit(repo, "harness/late.py")
    _seed_run(db_path, repo, base_sha=base)

    result = _certify(repo, db_path, "--gate-exit", "0")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "assurance_upgraded"
    assert payload["reason"] == "restricted_path"
    assert _events(db_path, "certify") == []


# ---------------------------------------------------------------------------
# The upgrade path
# ---------------------------------------------------------------------------


def test_an_invalid_allowlist_upgrades_the_run(repo: Path, db_path: Path) -> None:
    (repo / "CONTEXT.md").write_text(
        _CONTEXT_WITH_GATE.replace("    - docs/**\n", "    - docs/**\n    - /**\n")
    )
    _git(repo, "commit", "-qam", "widen")
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "docs/notes.md")
    _seed_run(db_path, repo, base_sha=base)

    result = _certify(repo, db_path, "--gate-exit", "0")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["reason"] == "no_allowlist"
    assert _row(db_path) == (DEFAULT_ASSURANCE, "diff_ineligible")


def test_a_repo_with_no_configured_gate_never_certifies(
    repo: Path, db_path: Path
) -> None:
    """The widening this design closes, measured.

    ``has_gate_evidence`` accepts ``gate_reason='not_configured'`` — right for a
    review, where an engine still read the diff, and wrong for a certification,
    whose entire safety argument *is* the gate. Such a repo upgrades and behaves
    exactly as it does today.
    """
    (repo / "CONTEXT.md").write_text(
        _CONTEXT_WITH_GATE.replace('  verify: "bash scripts/verify.sh"\n', "")
    )
    _git(repo, "commit", "-qam", "no gate")
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "docs/notes.md")
    _seed_run(db_path, repo, base_sha=base)

    result = _certify(repo, db_path)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["reason"] == "gate_not_configured"
    assert _events(db_path, "certify") == []


def test_a_run_with_no_recorded_boundary_upgrades(repo: Path, db_path: Path) -> None:
    _commit(repo, "docs/notes.md")
    _seed_run(db_path, repo)

    async def _clear() -> None:
        async with store.connect(db_path) as conn:
            await conn.execute("UPDATE runs SET base_sha = NULL")
            await conn.commit()

    run_sync(_clear())

    result = _certify(repo, db_path, "--gate-exit", "0")

    assert json.loads(result.stdout)["reason"] == "no_base_sha"


def test_a_run_that_changed_nothing_upgrades(repo: Path, db_path: Path) -> None:
    _seed_run(db_path, repo)
    result = _certify(repo, db_path, "--gate-exit", "0")
    assert json.loads(result.stdout)["reason"] == "empty_diff"


def test_the_run_row_is_upgraded_before_the_tracker_is_touched(
    repo: Path, db_path: Path
) -> None:
    """Measured as an observable, not as a call order.

    The fake reads the ledger at the moment each seam call is made. Asserting
    that the *first* call already saw ``simple`` is what makes this survive a
    refactor that keeps the calls in order while moving the write.
    """
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "harness/late.py")
    _seed_run(db_path, repo, base_sha=base)
    tracker = _FakeTracker(ledger_probe=db_path)

    result = _certify(repo, db_path, "--gate-exit", "0", tracker=tracker)

    assert result.exit_code == 0, result.output
    assert tracker.observed, "the tracker was never called, so nothing was measured"
    assert tracker.observed[0] == (DEFAULT_ASSURANCE, "diff_ineligible")


def test_only_the_assurance_label_is_replaced(repo: Path, db_path: Path) -> None:
    """The exact call log — which is what proves unrelated labels are untouched.

    Asserting a resulting label *set* would be satisfied by an implementation
    that enumerated the issue's labels and wrote them back, which is precisely
    the shape that drops a label the day the read races a human edit.
    """
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "harness/late.py")
    _seed_run(db_path, repo, base_sha=base)
    tracker = _FakeTracker()

    result = _certify(repo, db_path, "--gate-exit", "0", tracker=tracker)

    assert result.exit_code == 0, result.output
    assert [(kind, value) for kind, value in tracker.calls if kind != "comment"] == [
        ("remove", "assurance:trivial"),
        ("apply", "assurance:simple"),
    ]
    assert json.loads(result.stdout)["tracker_synced"] is True


def test_the_upgrade_comment_names_the_reason_and_the_offending_paths(
    repo: Path, db_path: Path
) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "harness/late.py")
    _seed_run(db_path, repo, base_sha=base)
    tracker = _FakeTracker()

    _certify(repo, db_path, "--gate-exit", "0", tracker=tracker)

    (body,) = [value for kind, value in tracker.calls if kind == "comment"]
    assert "restricted_path" in body
    assert "harness/late.py" in body


def test_a_tracker_failure_leaves_the_stricter_state_authoritative(
    repo: Path, db_path: Path
) -> None:
    """A partial sync names the artifact and never rolls the row back."""
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "harness/late.py")
    _seed_run(db_path, repo, base_sha=base)
    tracker = _FakeTracker(fail_on="apply")

    result = _certify(repo, db_path, "--gate-exit", "0", tracker=tracker)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "assurance_upgraded"
    assert payload["tracker_synced"] is False
    assert payload["tracker_error"] == "label"
    assert _row(db_path) == (DEFAULT_ASSURANCE, "diff_ineligible")


def test_a_tracker_less_repo_reports_a_complete_sync(repo: Path, db_path: Path) -> None:
    (repo / "CONTEXT.md").write_text(
        _CONTEXT_WITH_GATE.replace("tracker: linear", "tracker: none").replace(
            "  linear: harness\n", ""
        )
    )
    _git(repo, "commit", "-qam", "tracker-less")
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "harness/late.py")
    _seed_run(db_path, repo, base_sha=base)

    result = _certify(repo, db_path, "--gate-exit", "0")

    payload = json.loads(result.stdout)
    assert payload["outcome"] == "assurance_upgraded"
    assert payload["tracker_synced"] is True
    assert payload["tracker_error"] is None


def test_the_upgrade_statement_cannot_downgrade_a_run(repo: Path, db_path: Path) -> None:
    """Monotonicity is a property of the WHERE clause, tested where it lives.

    The verb refuses a non-``trivial`` run before it could ever reach this
    statement, so the guard is unreachable through the CLI — which is exactly why
    it needs its own test: a future caller could reach it, and the statement must
    still be incapable of expressing a downgrade.
    """
    _seed_run(db_path, repo, assurance="complex", run_id="01COMPLEXRUN000000000000")
    run_sync(_persist_upgrade(db_path, "01COMPLEXRUN000000000000"))
    assert _row(db_path, "01COMPLEXRUN000000000000") == ("complex", "label")


# ---------------------------------------------------------------------------
# The refusals — none of them mutates anything
# ---------------------------------------------------------------------------


def test_certify_refuses_without_gate_evidence(repo: Path, db_path: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "docs/notes.md")
    _seed_run(db_path, repo, base_sha=base)

    result = _certify(repo, db_path)

    assert result.exit_code == 5, result.output
    assert json.loads(result.stdout)["reason"] == "no_gate_evidence"
    assert _events(db_path, "certify") == []
    assert _row(db_path) == ("trivial", "label")


def test_certify_refuses_a_red_gate(repo: Path, db_path: Path, tmp_path: Path) -> None:
    """A red gate is a refusal, never an upgrade.

    The run row must still read ``trivial`` afterwards: upgrading here would let
    a red tree buy the run a review it had not earned the right to ask for, and
    the operator's remedy is to fix the gate, not to spend an engine.
    """
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "docs/notes.md")
    _seed_run(db_path, repo, base_sha=base)
    log = tmp_path / "gate.log"
    log.write_text("E   assert 1 == 2\n")

    result = _certify(repo, db_path, "--gate-exit", "1", "--gate-log", str(log))

    assert result.exit_code == 5, result.output
    payload = json.loads(result.stdout)
    assert payload["reason"] == "gate_failed"
    assert "assert 1 == 2" in payload["gate_output_tail"]
    assert _events(db_path, "certify") == []
    assert _row(db_path) == ("trivial", "label")


def test_certify_refuses_a_dirty_worktree(repo: Path, db_path: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "docs/notes.md")
    _seed_run(db_path, repo, base_sha=base)
    (repo / "docs" / "notes.md").write_text("uncommitted\n")

    result = _certify(repo, db_path, "--gate-exit", "0")

    assert result.exit_code == 2, result.output
    assert json.loads(result.stdout)["reason"] == "dirty_worktree"
    assert _events(db_path, "certify") == []


def test_certify_refuses_a_run_that_requires_a_review(repo: Path, db_path: Path) -> None:
    """Decided through the required-stages table, not by comparing to a string."""
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "docs/notes.md")
    _seed_run(db_path, repo, assurance="simple", base_sha=base)

    result = _certify(repo, db_path, "--gate-exit", "0")

    assert result.exit_code == 2, result.output
    assert json.loads(result.stdout)["reason"] == "assurance_not_trivial"
    assert _events(db_path, "certify") == []


def test_certify_refuses_when_no_open_run_resolves(repo: Path, db_path: Path) -> None:
    result = _certify(repo, db_path)
    assert result.exit_code == 2, result.output
    assert json.loads(result.stdout)["reason"] == "no_run"


# ---------------------------------------------------------------------------
# The gate the certification exists to open
# ---------------------------------------------------------------------------


def test_close_accepts_the_certification_and_names_the_evidence_kind(
    repo: Path, db_path: Path
) -> None:
    """The whole vertical slice, end to end: certify, then close, with no review.

    This is the only test that spans both verbs, and it is what makes
    ``CloseOutput.evidence_kind`` a wired field rather than a defaulted one — a
    close driven by a certification must *say* what opened its gate, or a
    consumer reading the kind learns nothing it could not have assumed.
    """
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, "docs/notes.md")
    _seed_run(db_path, repo, base_sha=base)
    assert _certify(repo, db_path, "--gate-exit", "0").exit_code == 0

    tracker = MagicMock()
    tracker.transition_to_done = _async_none()
    tracker.fetch_issue = _async_value({"identifier": TICKET, "state": {"name": "Done"}})
    with (
        patch("harness.tracker.LinearClient", return_value=tracker),
        patch("harness.tracker.linear_api_key", return_value="test-key"),
        patch("harness.close_merge.merge_run_branch", MagicMock(return_value=None)),
    ):
        result = cli_runner.invoke(
            app,
            [
                "close",
                TICKET,
                "--repo",
                str(repo),
                "--db",
                str(db_path),
                "--run-id",
                RUN_ID,
                "--json",
            ],
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["merged"] is True
    assert payload["reviewed_sha"] == head
    assert payload["evidence_kind"] == "trivial_certification"
    assert _events(db_path, "review") == []


def test_close_refuses_a_certification_the_tree_has_moved_past(
    repo: Path, db_path: Path
) -> None:
    """The binding is only real if a moved HEAD is refused.

    Certify, then commit. ``close`` must report ``stale_review`` and name the
    certified SHA among the evidenced ones — a certification that still opened
    the gate here would cover a tree nobody classified.
    """
    base = _git(repo, "rev-parse", "HEAD")
    certified = _commit(repo, "docs/notes.md")
    _seed_run(db_path, repo, base_sha=base)
    assert _certify(repo, db_path, "--gate-exit", "0").exit_code == 0
    _commit(repo, "docs/more.md")

    with (
        patch("harness.tracker.LinearClient", return_value=MagicMock()),
        patch("harness.tracker.linear_api_key", return_value="test-key"),
        patch("harness.close_merge.merge_run_branch", MagicMock(return_value=None)),
    ):
        result = cli_runner.invoke(
            app,
            ["close", TICKET, "--repo", str(repo), "--db", str(db_path),
             "--run-id", RUN_ID, "--json"],
        )

    assert result.exit_code == 2, result.output
    payload = json.loads(result.stdout)
    assert payload["reason"] == "stale_review"
    assert certified in payload["error"]
