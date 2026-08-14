"""#352 — ``harness start`` resolves the run's assurance once and snapshots it.

The parent proposal (``specs/proposals/assurance-led-lifecycle.md``) makes the
*issue* the durable intent and the *run* the stable execution snapshot. ``start``
is the seam between them: it already fetches the issue — labels included — so it
resolves the level there, writes it onto the run row, and reports it. No later
verb re-reads a label, which is what makes the stages a run must pay for stable
for the life of the run.

These tests drive the real CLI with a stubbed tracker, so they measure the wiring
(``fetch_issue``'s labels → :func:`harness.assurance.resolve_assurance` → the row
→ ``StartOutput``) rather than the policy, which
``tests/unit/test_assurance_policy.py`` owns as a pure table. Both halves are
needed: the policy suite would stay green against a ``start`` that resolved
correctly and then persisted nothing.

AC-2's other half — that existing ledger rows stay readable as ``simple`` without
being rewritten — is in ``tests/unit/test_state_store.py`` (the migration) and
``tests/unit/test_runs_resolver.py`` (the read), because neither needs a CLI.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.state import store
from tests._asyncutil import run_sync
from tests._ledger import seed_premigration_ledger

cli_runner = CliRunner()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


@pytest.fixture(autouse=True)
def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "dev")
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    (repo_root / ".gitignore").write_text(".harness/\n.worktrees/\n")
    (repo_root / "README.md").write_text("hello\n")
    _git(repo_root, "add", ".gitignore", "README.md")
    _git(repo_root, "commit", "-m", "initial")
    return repo_root


@pytest.fixture
def db_path(repo: Path) -> Path:
    return repo / ".harness" / "harness.db"


def _stub(labels: list[str] | None) -> MagicMock:
    """A tracker stub whose ``fetch_issue`` returns ``labels``.

    ``None`` omits the key entirely — the shape a provider returns for an issue
    payload that carries no labels at all, which must not be an error.
    """
    ticket: dict[str, Any] = {
        "id": "abc-123-uuid",
        "identifier": "352",
        "title": "assurance: snapshot required stages",
        "description": "Body.",
        "url": "https://github.com/sluengen/harness/issues/352",
    }
    if labels is not None:
        ticket["labels"] = labels
    mock = MagicMock()
    mock.fetch_issue = AsyncMock(return_value=ticket)
    mock.transition_to_in_progress = AsyncMock(return_value=None)
    return mock


def _start(repo: Path, db_path: Path, stub: MagicMock, *args: str) -> Any:
    with (
        patch("harness.tracker.LinearClient", return_value=stub),
        patch("harness.tracker.linear_api_key", return_value="test-key"),
    ):
        return cli_runner.invoke(
            app,
            ["start", "352", "--repo", str(repo), "--db", str(db_path), *args],
        )


def _row(db_path: Path) -> dict[str, Any]:
    async def _read() -> dict[str, Any]:
        async with (
            store.connect(db_path) as conn,
            conn.execute("SELECT assurance, assurance_reason FROM runs") as cur,
        ):
            rows = await cur.fetchall()
        assert len(rows) == 1, f"expected exactly one run row, got {rows!r}"
        return {"assurance": rows[0][0], "assurance_reason": rows[0][1]}

    return run_sync(_read())


#: Every label shape an issue can arrive with, and the pair the run must
#: snapshot. The fixture repo declares **no** ``assurance.trivial_paths``
#: allowlist, so the ``trivial`` row still reads ``fast_path_unavailable`` — the
#: pre-#353 answer, now for the reason the tag names rather than unconditionally.
#: The other direction (a repo that *can* certify) is
#: :func:`test_trivial_is_honoured_where_the_repo_declares_an_allowlist`, and
#: without that pair this table would keep passing against a ``start`` that had
#: silently gone back to rewriting every ``trivial``.
_CASES: list[tuple[str, list[str] | None, str, str]] = [
    ("no-labels-key", None, "simple", "no_label"),
    ("empty-labels", [], "simple", "no_label"),
    ("unrelated-only", ["bug", "p1"], "simple", "no_label"),
    ("complex", ["assurance:complex"], "complex", "label"),
    ("simple", ["assurance:simple", "bug"], "simple", "label"),
    ("mixed-case", ["Assurance:Complex"], "complex", "label"),
    ("trivial", ["assurance:trivial"], "simple", "fast_path_unavailable"),
    ("conflicting", ["assurance:complex", "assurance:simple"], "simple", "conflicting_labels"),
    ("unknown", ["assurance:banana"], "simple", "unknown_label"),
    ("unknown-beside-known", ["assurance:complex", "assurance:x"], "simple", "unknown_label"),
]


@pytest.mark.parametrize(
    ("labels", "assurance", "reason"),
    [(labels, a, r) for _, labels, a, r in _CASES],
    ids=[name for name, _, _, _ in _CASES],
)
def test_start_snapshots_the_resolved_assurance_on_the_run(
    repo: Path,
    db_path: Path,
    labels: list[str] | None,
    assurance: str,
    reason: str,
) -> None:
    """AC-1/AC-2/AC-6 through the real CLI: the row records level *and* reason.

    The reason is persisted beside the level rather than derived later because
    ``simple`` means five different things — nobody stated an intent, two
    conflicting ones were stated, an uninterpretable one was, or ``trivial`` was
    requested and rewritten — and a run that silently lost its operator's stated
    intent is exactly what an audit needs to be able to see.
    """
    result = _start(repo, db_path, _stub(labels))

    assert result.exit_code == 0, result.output
    assert _row(db_path) == {"assurance": assurance, "assurance_reason": reason}


@pytest.mark.parametrize(
    ("labels", "assurance", "reason"),
    [(labels, a, r) for _, labels, a, r in _CASES],
    ids=[name for name, _, _, _ in _CASES],
)
def test_start_reports_the_snapshot_it_wrote(
    repo: Path,
    db_path: Path,
    labels: list[str] | None,
    assurance: str,
    reason: str,
) -> None:
    """The orchestrator follows the recorded plan without re-reading the issue.

    Asserted against the same corpus as the row, so the two cannot diverge: a
    ``start`` that persisted one level and printed another would pass either
    test alone.
    """
    result = _start(repo, db_path, _stub(labels), "--json")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["assurance"] == assurance
    assert payload["assurance_reason"] == reason


def test_resolution_adds_no_tracker_round_trip(repo: Path, db_path: Path) -> None:
    """Assurance is read off the issue payload ``start`` already fetched.

    A measuring test, not a structural one: the criterion is a *count*. Resolving
    labels through a second ``fetch_issue`` — or a dedicated label query — would
    leave every other assertion in this module green while doubling the tracker
    cost of every run.
    """
    stub = _stub(["assurance:complex"])

    result = _start(repo, db_path, stub)

    assert result.exit_code == 0, result.output
    assert stub.fetch_issue.await_count == 1


def test_an_existing_run_reports_its_recorded_snapshot_not_a_fresh_resolution(
    repo: Path, db_path: Path
) -> None:
    """A repeat ``start`` reports what the run was opened under, never today's labels.

    The snapshot is what makes the required stages stable, so this is the
    TOCTOU property stated as a test: the issue's labels change to ``simple``
    between the two calls, and the second call must still report ``complex``.
    The recorded pair is authoritative exactly as ``attended`` is — a repeat
    ``start`` reports the run, it does not re-open it.
    """
    first = _start(repo, db_path, _stub(["assurance:complex"]), "--json")
    assert first.exit_code == 0, first.output
    assert json.loads(first.stdout)["assurance"] == "complex"

    second = _start(repo, db_path, _stub(["assurance:simple"]), "--json")

    assert second.exit_code == 0, second.output
    payload = json.loads(second.stdout)
    assert payload["run_id"] == json.loads(first.stdout)["run_id"]
    assert payload["assurance"] == "complex"
    assert payload["assurance_reason"] == "label"
    assert _row(db_path) == {"assurance": "complex", "assurance_reason": "label"}


@pytest.mark.parametrize(
    "labels",
    [
        ["assurance:trivial"],
        ["assurance:complex", "assurance:simple"],
        ["assurance:banana"],
    ],
    ids=["trivial", "conflicting", "unknown"],
)
def test_an_unhonoured_intent_warns_on_stderr(
    repo: Path, db_path: Path, labels: list[str]
) -> None:
    """The three reasons that mean "you stated something and we did not do it".

    A bad label is never a refusal — it is a downgrade to the safe level — but it
    is not silent either, because the operator's stated intent was discarded.
    """
    result = _start(repo, db_path, _stub(labels))

    assert result.exit_code == 0, result.output
    assert "assurance" in (result.stderr or "").lower()


@pytest.mark.parametrize(
    "labels", [None, [], ["bug"], ["assurance:complex"]], ids=["none", "empty", "other", "complex"]
)
def test_an_honoured_or_absent_intent_is_silent(
    repo: Path, db_path: Path, labels: list[str] | None
) -> None:
    """No warning for the common case, or for a label that *was* honoured.

    The negative control on the warning above. Warning on "no label" would put a
    line on every run in every repo that has not adopted the labels, which trains
    readers to ignore the warning that matters.
    """
    result = _start(repo, db_path, _stub(labels))

    assert result.exit_code == 0, result.output
    assert "assurance" not in (result.stderr or "").lower()


def test_start_works_against_a_ledger_that_predates_the_migration(
    repo: Path, db_path: Path
) -> None:
    """The upgrade path: an existing checkout's ledger has no assurance columns.

    ``_find_open_run`` projects them, and it runs *before* the insert that calls
    ``store.init_db`` — so nothing has migrated the ledger by the time they are
    first read. A test that calls ``init_db`` itself cannot see this: it heals
    the ledger before the verb runs, which is exactly why this one seeds the old
    schema directly and drives the CLI.

    What must hold is that the first verb invocation after an upgrade still
    self-heals the ledger, as every previous migration did. Here the run is a
    *different* ticket, so ``start`` opens a new one over the migrated schema.
    """
    seed_premigration_ledger(
        db_path,
        run_id="01JLEGACYRUNXXXXXXXXXXXXX1",
        worktree_path="/gone",
        ticket="OLD-1",
        started_at="2026-07-01T00:00:00Z",
    )

    result = _start(repo, db_path, _stub(["assurance:complex"]), "--json")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["assurance"] == "complex"
    assert payload["assurance_reason"] == "label"


def test_start_reports_a_legacy_open_run_as_unrecorded(repo: Path, db_path: Path) -> None:
    """...and an open run written by the older harness reads as ``simple``.

    The existing-run path returns that row without ever reaching the insert, so
    this is the projection reading columns a pre-migration ledger does not have.
    ``unrecorded`` is the reason reserved for exactly this: the run predates the
    snapshot, so nothing was resolved for it.
    """
    seed_premigration_ledger(
        db_path,
        run_id="01JLEGACYRUNXXXXXXXXXXXXX2",
        worktree_path="/gone",
        ticket="352",
        started_at="2026-07-01T00:00:00Z",
    )

    result = _start(repo, db_path, _stub(["assurance:complex"]), "--json")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["run_id"] == "01JLEGACYRUNXXXXXXXXXXXXX2"
    assert payload["assurance"] == "simple"
    assert payload["assurance_reason"] == "unrecorded"


def test_a_repeat_start_does_not_re_warn(repo: Path, db_path: Path) -> None:
    """The warning belongs to the resolution, and a repeat ``start`` makes none.

    ``start`` returns the recorded run before it acts on anything it resolved,
    so a second call against an issue whose labels are now unhonourable must be
    silent: the run's level was fixed when it opened, and warning about a
    resolution that changed nothing would tell an operator their edit had an
    effect it did not have.

    The first call uses an honoured label precisely so the *only* thing that
    could produce a warning on the second call is the second call's own
    resolution — which is the placement under test.
    """
    first = _start(repo, db_path, _stub(["assurance:complex"]), "--json")
    assert first.exit_code == 0, first.output
    assert "assurance" not in (first.stderr or "").lower()

    second = _start(repo, db_path, _stub(["assurance:trivial"]), "--json")

    assert second.exit_code == 0, second.output
    assert json.loads(second.stdout)["assurance_reason"] == "label"
    assert "assurance" not in (second.stderr or "").lower(), (
        "a repeat start re-warned about a resolution it did not act on"
    )


def test_trivial_is_honoured_where_the_repo_declares_an_allowlist(
    repo: Path, db_path: Path
) -> None:
    """#353: the run snapshots the level the issue stated.

    The half of the pair that fails if the availability check is removed in the
    "always downgrade" direction — which is the direction that silently disables
    the whole fast path while every other test in this module stays green.
    """
    (repo / "CONTEXT.md").write_text(
        "```yaml\nassurance:\n  trivial_paths:\n    - docs/**\n```\n"
    )
    _git(repo, "add", "CONTEXT.md")
    _git(repo, "commit", "-m", "declare a trivial allowlist")

    result = _start(repo, db_path, _stub(["assurance:trivial"]))

    assert result.exit_code == 0, result.output
    assert _row(db_path) == {"assurance": "trivial", "assurance_reason": "label"}


def test_trivial_is_downgraded_where_the_repo_declares_none(
    repo: Path, db_path: Path
) -> None:
    """The other half, stated explicitly rather than only as a table row.

    The fixture repo has no ``assurance:`` block at all, so there is nothing the
    fast path could certify and opening a ``trivial`` run would charge every run
    an extra verb call forever. The operator's stated intent was not honoured,
    which is what ``fast_path_unavailable`` means — and ``start`` warns about it.
    """
    result = _start(repo, db_path, _stub(["assurance:trivial"]))

    assert result.exit_code == 0, result.output
    assert _row(db_path) == {
        "assurance": "simple",
        "assurance_reason": "fast_path_unavailable",
    }
    assert "fast_path_unavailable" in result.stderr
