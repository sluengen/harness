"""Tests for the shared open-run resolver ``harness.cli._runs.resolve_open_run``
(CAL-631).

``review`` and ``close`` both answer the same question — "which ``runs`` row is
the active run for this invocation?" — with the identical dispatch rule: an
explicit ``run_id`` matches ``WHERE run_id = ? AND status = 'open'``, otherwise
the run is the one whose ``worktree_path`` equals the resolved repo. The
``status = 'open'`` filter is load-bearing — the close gate trusts that a verb
only ever acts on a live run. These tests lock the one shared implementation
directly, so the rule cannot drift between the two verbs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.cli._runs import LedgerNotFoundError, resolve_open_run
from harness.state import store
from tests._asyncutil import run_sync

RUN_ID = "01JRUNRESOLVEXXXXXXXXXXX01"


def _seed_run(
    db_path: Path,
    repo: Path,
    *,
    status: str = "open",
    run_id: str = RUN_ID,
) -> str:
    """Insert a ``runs`` row whose ``worktree_path == repo`` with ``status``."""

    async def _insert() -> None:
        await store.init_db(db_path)
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs ("
                "run_id, workflow_name, workflow_version, status, state_json, "
                "inputs_json, base_branch, worktree_path, worktree_branch, "
                "ticket, started_at, pid"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    "",
                    0,
                    status,
                    "{}",
                    "{}",
                    "dev",
                    str(repo),
                    f"harness/{run_id}",
                    "CAL-631",
                    "2026-06-12T00:00:00Z",
                    1234,
                ),
            )
            await conn.commit()

    run_sync(_insert())
    return run_id


def test_resolves_open_run_by_explicit_run_id(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    repo = tmp_path / "repo"
    repo.mkdir()
    run_id = _seed_run(db_path, repo)

    resolved = run_sync(resolve_open_run(db_path, repo, run_id))

    assert resolved == (run_id, str(repo), "dev", f"harness/{run_id}")


def test_resolves_open_run_by_worktree_path_when_no_run_id(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    repo = tmp_path / "repo"
    repo.mkdir()
    run_id = _seed_run(db_path, repo)

    resolved = run_sync(resolve_open_run(db_path, repo, None))

    assert resolved == (run_id, str(repo), "dev", f"harness/{run_id}")


def test_closed_run_is_not_resolved(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    repo = tmp_path / "repo"
    repo.mkdir()
    run_id = _seed_run(db_path, repo, status="closed")

    # Neither dispatch path may return a non-open run: the gate trusts this filter.
    assert run_sync(resolve_open_run(db_path, repo, run_id)) is None
    assert run_sync(resolve_open_run(db_path, repo, None)) is None


def test_no_matching_run_returns_none(tmp_path: Path) -> None:
    db_path = tmp_path / "harness.db"
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_run(db_path, repo)

    assert run_sync(resolve_open_run(db_path, repo, "01JOTHERRUNIDXXXXXXXXXXX99")) is None
    other_repo = tmp_path / "elsewhere"
    other_repo.mkdir()
    assert run_sync(resolve_open_run(db_path, other_repo, None)) is None


def test_missing_ledger_raises_ledger_not_found(tmp_path: Path) -> None:
    """#244: no ledger file at all is a distinct outcome from "no open run" —
    the lookup never happened, so it must not be conflated with ``None``."""
    db_path = tmp_path / "does-not-exist.db"
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(LedgerNotFoundError) as exc:
        run_sync(resolve_open_run(db_path, repo, None))

    assert exc.value.reason == "no_ledger"
    assert exc.value.code == 2
    assert str(db_path) in exc.value.message
    assert exc.value.extra == {"ledger_path": str(db_path)}


def test_missing_ledger_creates_no_files(tmp_path: Path) -> None:
    """The refusal must not plant a ``.harness/`` directory as a side effect —
    the guard runs before ``store.connect`` would create one."""
    db_path = tmp_path / ".harness" / "harness.db"
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(LedgerNotFoundError):
        run_sync(resolve_open_run(db_path, repo, None))

    assert not (tmp_path / ".harness").exists()


# ---------------------------------------------------------------------------
# Declared attendance — the shared run-row rule (#295, ADR 0011)
#
# ``attendance_inputs_json`` (start's only writer) and ``resolve_attended``
# (every reader) sit together in ``_runs`` for the reason its module docstring
# already gives for ``read_run_resumed_from``: "a second copy is how two paths
# start disagreeing". The two future readers are #296 (``review``'s wall-clock
# breaker) and #297 (``reclaim --stale``'s threshold selection).
#
# The asymmetry these tests lock: declaring attendance opts a run out of the
# only ceiling on autonomous spend, so ONLY the literal JSON ``true`` declares
# it. Every other value — including a truthy-looking one — resolves unattended,
# because the bounded mode is both the default and the failure default.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # The one declaring value.
        ('{"attended": true}', True),
        ('{"attended": true, "other": 1}', True),
        # Today's stored value, on every row ever written (AC-3).
        ("{}", False),
        # Absent key.
        ('{"other": 1}', False),
        # Explicit opt-out.
        ('{"attended": false}', False),
        # Truthy-but-not-the-boolean: a string, an int, a list. None of these
        # may buy an exemption from the spend ceiling.
        ('{"attended": "true"}', False),
        ('{"attended": 1}', False),
        ('{"attended": ["yes"]}', False),
        # Unparseable (AC-3).
        ("not json", False),
        ("{oops", False),
        # Valid JSON that is not an object.
        ("[]", False),
        ("null", False),
        ('"attended"', False),
        # Empty / absent column.
        ("", False),
        (None, False),
    ],
)
def test_resolve_attended_only_the_literal_true_declares_attendance(
    raw: str | None, expected: bool
) -> None:
    """AC-3: the reader is total and fails safe toward the bounded mode.

    One assertion per case rather than a single compound one, so a regression
    names the exact value that started resolving the wrong way.
    """
    from harness.cli._runs import resolve_attended

    assert resolve_attended(raw) is expected


@pytest.mark.parametrize("declared", [True, False])
def test_attendance_round_trips_through_the_writer(declared: bool) -> None:
    """The writer/reader contract in one line — what ``start`` stores is what
    ``review`` / ``reclaim`` will read back. Locks the pair against a rename or
    a re-spelling of the key on either side."""
    from harness.cli._runs import attendance_inputs_json, resolve_attended

    assert resolve_attended(attendance_inputs_json(declared)) is declared


def test_unattended_writes_todays_exact_value() -> None:
    """AC-2 at the source: the undeclared mode is byte-identical to the literal
    ``start`` has always inserted, so no existing row changes meaning and no
    backfill is needed."""
    from harness.cli._runs import attendance_inputs_json

    assert attendance_inputs_json(False) == "{}"


def test_attended_writes_a_parseable_object_carrying_the_key() -> None:
    """The declared value is real JSON (not a sentinel string) — ``harness
    status --json`` already parses this column and surfaces it as ``inputs``."""
    import json

    from harness.cli._runs import ATTENDED_KEY, attendance_inputs_json

    assert json.loads(attendance_inputs_json(True)) == {ATTENDED_KEY: True}
