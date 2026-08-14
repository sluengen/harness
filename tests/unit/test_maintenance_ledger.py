"""The maintenance sweep record — a sibling table, and the reader that surfaces it.

Two properties are pinned here, each traced to the decision that requires it:

* **A sweep row is not a run row** (§1 of #310's design). ADR 0009 rejected a
  synthetic ``runs`` row for run-less telemetry and #338 then *deleted* the last
  one, on the ground that it made a triage write "indistinguishable from a build
  run in every ledger-backed view". A sweep fires every interval, per repo,
  forever — the volume ADR 0009 named. The measurable form of that decision is
  :func:`test_a_sweep_record_is_invisible_to_the_run_ledger_readers`: the two
  unfiltered readers over ``runs`` must produce byte-identical output across a
  sweep record being written. It is what would have failed for the rejected
  option, which is what makes the choice *checked* rather than asserted.
* **AC-4's predicate has a production reader.** ``harness doctor`` reports the
  lag against the configured interval, so a sweep that stopped happening is
  visible. The criterion is a duration, so the test moves a clock across the
  boundary against a **real recorded row** read back through the production
  function (``code-quality`` Part C).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.loop_budget import load_loop_budget
from harness.maintenance.ledger import (
    MaintenanceSweep,
    SweepStep,
    check_sweeps,
    iso_from_ms,
    last_sweep,
    record_sweep,
)
from harness.state import store
from tests._asyncutil import run_sync

runner = CliRunner()

_INTERVAL_MS = 60 * 60 * 1000
_NOW_MS = 1_800_000_000_000


def _sweep(
    repo: Path,
    *,
    swept_at_ms: int = _NOW_MS,
    outcome: str = "completed",
    detail: str = "",
    steps: list[SweepStep] | None = None,
) -> MaintenanceSweep:
    return MaintenanceSweep(
        repo=str(repo),
        swept_at=iso_from_ms(swept_at_ms),
        duration_ms=12,
        outcome=outcome,  # type: ignore[arg-type]
        steps=steps or [],
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Round-trip.
# ---------------------------------------------------------------------------


def test_a_recorded_sweep_reads_back_whole(tmp_path: Path) -> None:
    db_path = tmp_path / ".harness" / "harness.db"
    sweep = _sweep(
        tmp_path,
        steps=[
            SweepStep(
                verb="reclaim --stale",
                argv=["reclaim", "--stale"],
                exit_code=0,
                duration_ms=5,
            )
        ],
    )

    run_sync(record_sweep(sweep, db_path=db_path))

    assert run_sync(last_sweep(db_path)) == sweep


def test_the_newest_sweep_is_the_one_read_back(tmp_path: Path) -> None:
    """The schedule's only memory is this row, so "newest" has to mean newest."""
    db_path = tmp_path / ".harness" / "harness.db"
    older = _sweep(tmp_path, swept_at_ms=_NOW_MS - 10 * _INTERVAL_MS, detail="older")
    newer = _sweep(tmp_path, swept_at_ms=_NOW_MS, detail="newer")

    run_sync(record_sweep(newer, db_path=db_path))
    run_sync(record_sweep(older, db_path=db_path))

    read = run_sync(last_sweep(db_path))
    assert read is not None
    assert read.detail == "newer"


def test_last_sweep_degrades_on_an_absent_db_and_an_uninitialised_table(
    tmp_path: Path,
) -> None:
    """``None``, not a raise, for both "nothing written yet" cases — the contract
    ``read_promotion`` already keeps. A ``doctor`` that raised on a fresh repo
    would be worse than the gap it exists to report."""
    absent = tmp_path / ".harness" / "harness.db"
    assert run_sync(last_sweep(absent)) is None

    runs_only = tmp_path / "other" / "harness.db"
    run_sync(store.init_db(runs_only))
    assert run_sync(last_sweep(runs_only)) is None


# ---------------------------------------------------------------------------
# §1 — a sweep row is not a run row.
# ---------------------------------------------------------------------------


def test_a_sweep_record_is_invisible_to_the_run_ledger_readers(tmp_path: Path) -> None:
    """``harness runs`` and ``harness stats`` must not see a sweep (AC-1, §1).

    The two unfiltered scans over ``runs`` are the ones an operator actually
    reads, and a synthetic ``runs`` row — the option ADR 0009 rejected and #338
    deleted — would displace a real run off the first and acquire a synthetic
    denominator in the second. Byte-identical output across the write is the
    measurable form of the choice.
    """
    db_path = tmp_path / ".harness" / "harness.db"
    run_sync(store.init_db(db_path))
    run_sync(_seed_run(db_path))

    def read() -> tuple[str, str]:
        runs = runner.invoke(app, ["runs", "--db", str(db_path)])
        stats = runner.invoke(app, ["stats", "--db", str(db_path), "--json"])
        assert runs.exit_code == 0, runs.output
        assert stats.exit_code == 0, stats.output
        return runs.output, stats.output

    before = read()
    # Non-vacuity floor: were both readers empty, "identical" would hold for
    # every possible record home, including the rejected one.
    assert "RUNSENTINEL" in before[0], before[0]
    assert '"total":1' in before[1], before[1]

    run_sync(record_sweep(_sweep(tmp_path), db_path=db_path))
    # …and the second floor: a writer that wrote *nothing* would leave both
    # readers identical for every possible record home, which is the vacuous
    # shape this whole assertion is exposed to.
    assert run_sync(last_sweep(db_path)) is not None

    assert read() == before


async def _seed_run(db_path: Path) -> None:
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, started_at, completed_at, duration_ms) "
            "VALUES ('RUNSENTINEL', '', 1, 'closed', '{}', '{}', "
            "'2026-07-01T10:00:00+00:00', '2026-07-01T10:30:00+00:00', 1800000)"
        )
        await conn.commit()


# ---------------------------------------------------------------------------
# AC-4 — the reader, measured.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lag_ms", "expected"),
    [(_INTERVAL_MS - 1, "PASS"), (_INTERVAL_MS, "PASS"), (_INTERVAL_MS + 1, "WARN")],
)
def test_doctor_reports_a_stale_sweep_from_a_real_recorded_row(
    tmp_path: Path, lag_ms: int, expected: str
) -> None:
    """A real row through ``record_sweep``, read by the production ``check_sweeps``.

    The clock moves across the boundary and the status transitions with it. A
    test asserting the word "sweep" appears in doctor's output would be the
    structural stand-in ``code-quality`` Part C forbids for a criterion stated
    as a quantity.
    """
    db_path = tmp_path / ".harness" / "harness.db"
    run_sync(record_sweep(_sweep(tmp_path, swept_at_ms=_NOW_MS - lag_ms), db_path=db_path))

    status, message = check_sweeps(db_path, interval_ms=_INTERVAL_MS, now_ms=_NOW_MS)

    assert status == expected
    assert str(lag_ms // 60_000) in message, (
        f"the message must carry the measured lag, not a constant: {message!r}"
    )


def test_doctor_reports_an_absent_sweep_distinctly_from_a_stale_one(
    tmp_path: Path,
) -> None:
    """Three different facts, three different messages.

    Without this, a ``check_sweeps`` returning one constant ``WARN`` string
    satisfies the boundary test above for every clock value.
    """
    fresh_db = tmp_path / "fresh" / "harness.db"
    stale_db = tmp_path / "stale" / "harness.db"
    absent_db = tmp_path / "absent" / "harness.db"
    run_sync(record_sweep(_sweep(tmp_path, swept_at_ms=_NOW_MS - 60_000), db_path=fresh_db))
    run_sync(
        record_sweep(_sweep(tmp_path, swept_at_ms=_NOW_MS - 9 * _INTERVAL_MS), db_path=stale_db)
    )

    fresh = check_sweeps(fresh_db, interval_ms=_INTERVAL_MS, now_ms=_NOW_MS)
    stale = check_sweeps(stale_db, interval_ms=_INTERVAL_MS, now_ms=_NOW_MS)
    absent = check_sweeps(absent_db, interval_ms=_INTERVAL_MS, now_ms=_NOW_MS)

    assert fresh[0] == "PASS"
    assert stale[0] == "WARN"
    assert absent[0] == "WARN"
    assert len({fresh[1], stale[1], absent[1]}) == 3, (
        f"the three states must be distinguishable: {fresh[1]!r} {stale[1]!r} {absent[1]!r}"
    )
    assert "serve" in absent[1], (
        "an absent record must name the remedy — the host process is not running"
    )


def test_a_repo_with_sweeps_disabled_is_not_reported_as_overdue(tmp_path: Path) -> None:
    """``maintenance_interval_minutes: 0`` is a configured choice, not a fault.

    Reporting it as WARN would make the escape hatch cost a permanent warning,
    which is the same as not having one.
    """
    status, message = check_sweeps(
        tmp_path / ".harness" / "harness.db", interval_ms=0, now_ms=_NOW_MS
    )

    assert status == "PASS"
    assert "disabled" in message


def test_the_check_never_fails_the_doctor_exit_code(tmp_path: Path) -> None:
    """``WARN``, never ``FAIL``: ``doctor`` exits 1 on any FAIL, and a repo whose
    host has never run ``serve`` is not broken. This mirrors ``check_db``'s
    treatment of an absent ledger."""
    statuses = {
        check_sweeps(tmp_path / "a" / "harness.db", interval_ms=_INTERVAL_MS, now_ms=_NOW_MS)[0],
        check_sweeps(tmp_path / "b" / "harness.db", interval_ms=0, now_ms=_NOW_MS)[0],
    }

    assert statuses <= {"PASS", "WARN"}


def _doctor_sweep_line(db_path: Path) -> str:
    result = runner.invoke(
        app, ["doctor", "--db", str(db_path)], env={"ANTHROPIC_API_KEY": "sk-test"}
    )
    lines = [line for line in result.stdout.splitlines() if " sweeps " in line]
    assert len(lines) == 1, (
        f"`harness doctor` must carry exactly one sweeps check: {result.stdout}"
    )
    return lines[0]


def test_doctor_wires_the_sweep_check_and_measures_the_lag(tmp_path: Path) -> None:
    """AC-4 end-to-end: the predicate has a production reader, and it measures.

    A predicate nothing reads is inert, so the check is asserted through the real
    aggregated command — and asserted as a *transition across the configured
    interval*, not as the word "sweep" appearing somewhere in the output, which
    is the structural stand-in ``code-quality`` Part C forbids.

    The interval is derived from this repo's own ``CONTEXT.md`` rather than
    written out, so the test cannot drift from the value ``doctor`` reads.
    """
    repo_root = Path(__file__).resolve().parents[2]
    interval_ms = load_loop_budget(repo_root).maintenance_interval_minutes * 60_000
    assert interval_ms > 0, "fixture floor: this repo must have sweeps enabled"
    now_ms = int(time.time() * 1000)

    fresh_db = tmp_path / "fresh" / "harness.db"
    run_sync(record_sweep(_sweep(tmp_path, swept_at_ms=now_ms - 60_000), db_path=fresh_db))
    fresh_line = _doctor_sweep_line(fresh_db)

    overdue_ms = interval_ms + 120_000
    stale_db = tmp_path / "stale" / "harness.db"
    run_sync(record_sweep(_sweep(tmp_path, swept_at_ms=now_ms - overdue_ms), db_path=stale_db))
    stale_line = _doctor_sweep_line(stale_db)

    assert fresh_line.startswith("[PASS]"), fresh_line
    assert stale_line.startswith("[WARN]"), stale_line
    assert str(overdue_ms // 60_000) in stale_line, (
        f"the line must carry the measured lag, not a constant: {stale_line!r}"
    )


def test_doctor_never_fails_on_an_unswept_repo(tmp_path: Path) -> None:
    """A repo whose host has never run ``serve`` is not broken, so the check must
    not be the reason ``doctor`` exits 1 — the treatment ``check_db`` gives an
    absent ledger."""
    line = _doctor_sweep_line(tmp_path / "never" / "harness.db")

    assert line.startswith("[WARN]"), line
