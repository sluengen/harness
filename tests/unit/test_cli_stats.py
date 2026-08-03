"""Tests for ``harness stats`` — the aggregate ledger reader (#265).

Breakdown item 5 of ``verb-telemetry`` (ADR 0009), and the last one, so it
computes over the honest denominator items 2–4 established: every verb records
its attempts, not only its successes.

The seeders below build a ledger by hand rather than driving the verbs, because
what is under test is the *reading* — which rows count, which are excluded, and
what the arithmetic over them is. A hand-computed expectation beside a seeded
population is the only way an aggregate can be asserted at all (AC-1).
"""

# size: the stats aggregate reader (#265) over the denominator items 2-4 established
# — cases that seed one ledger fixture and assert the aggregation over it. The
# fixture is the module; splitting duplicates the seed.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli.stats_aggregate import StatsReport
from harness.state import store
from tests._asyncutil import run_sync

runner = CliRunner()


# ---------------------------------------------------------------------------
# Seeders
# ---------------------------------------------------------------------------


async def _seed_run_async(
    db_path: Path,
    run_id: str,
    *,
    workflow_name: str = "",
    status: str = "closed",
    started_at: str = "2026-07-01T10:00:00+00:00",
    completed_at: str | None = "2026-07-01T10:30:00+00:00",
    duration_ms: int | None = 1_800_000,
) -> None:
    await store.init_db(db_path)
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, started_at, completed_at, duration_ms) "
            "VALUES (?, ?, 1, ?, '{}', '{}', ?, ?, ?)",
            (run_id, workflow_name, status, started_at, completed_at, duration_ms),
        )
        await conn.commit()


def seed_run(db_path: Path, run_id: str, **kw: Any) -> None:
    """One ``runs`` row. ``workflow_name=''`` is what ``harness start`` writes."""
    run_sync(_seed_run_async(db_path, run_id, **kw))


async def _seed_event_async(
    db_path: Path,
    run_id: str,
    event_type: str,
    *,
    data: dict[str, Any] | None = None,
    timestamp: str = "2026-07-01T10:15:00Z",
    duration_ms: int | None = None,
) -> None:
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO events (run_id, event_type, timestamp, duration_ms, "
            "data_json) VALUES (?, ?, ?, ?, ?)",
            (run_id, event_type, timestamp, duration_ms, json.dumps(data or {})),
        )
        await conn.commit()


def seed_event(db_path: Path, run_id: str, event_type: str, **kw: Any) -> None:
    """One ``events`` row, written straight to the table.

    Bypassing :class:`~harness.events.emitter.EventEmitter` is deliberate: the
    emitter validates ``event_type`` against the *writable* set, and several of
    these tests must seed the retired-engine types a real historical ledger
    carries (the legacy-rows allowance in ``harness.events.schema``).
    """
    run_sync(_seed_event_async(db_path, run_id, event_type, **kw))


def _stats(db_path: Path, *args: str) -> StatsReport:
    """Run ``harness stats --json`` and parse the declared model back (AC-7)."""
    result = runner.invoke(app, ["stats", "--db", str(db_path), "--json", *args])
    assert result.exit_code == 0, result.output
    return StatsReport.model_validate_json(result.stdout.strip())


def _verb(report: StatsReport, verb: str) -> Any:
    match = [v for v in report.verbs if v.verb == verb]
    assert match, f"no report for verb {verb!r}: {[v.verb for v in report.verbs]}"
    return match[0]


# ---------------------------------------------------------------------------
# AC-1 — per-verb success rate, refusals in the denominator
# ---------------------------------------------------------------------------


def test_success_rate_counts_refusals_in_the_denominator(tmp_path: Path) -> None:
    """3 ok + 1 refused + 1 failed over 5 attempts is a 0.6 success rate.

    The whole point of items 2–4 was to make this denominator honest: before
    them, ``close`` wrote an event only when it merged, so a rate computed from
    the ledger read 3/3 = 1.0 no matter how often the gate refused.
    """
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    for _ in range(3):
        seed_event(db, "run-1", "close", data={"outcome": "ok"})
    seed_event(db, "run-1", "close", data={"outcome": "refused", "reason": "stale_review"})
    seed_event(db, "run-1", "close", data={"outcome": "failed", "reason": "push_rejected"})

    close = _verb(_stats(db), "close")

    assert close.attempts == 5
    assert close.ok == 3
    assert close.success_rate == pytest.approx(0.6)


def test_a_row_written_before_the_outcome_field_counts_as_a_success(
    tmp_path: Path,
) -> None:
    """A ``close`` payload carrying no ``outcome`` key reads as ``ok``.

    Every ``close`` event written before #263 was in fact a landed close, so
    ``COALESCE``-ing the missing key to ``ok`` is what stops the historical
    ledger from reading as a wall of unknowns.
    """
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "close", data={"merged_sha": "abc123"})

    close = _verb(_stats(db), "close")

    assert (close.attempts, close.ok, close.refused, close.failed) == (1, 1, 0, 0)


# ---------------------------------------------------------------------------
# AC-2 — retired-engine rows never contribute to verb-model rates
# ---------------------------------------------------------------------------


def test_retired_engine_runs_do_not_contribute_to_verb_rates(tmp_path: Path) -> None:
    """A ledger holding both kinds reports only the verb-model one.

    ``workflow_name`` is the discriminator: ``harness start`` writes ``''``,
    while the engine retired in CAL-574 wrote ``build`` / ``build-codex``.
    """
    db = tmp_path / "harness.db"
    seed_run(db, "verb-run", workflow_name="")
    seed_event(db, "verb-run", "close", data={"outcome": "ok"})
    seed_run(db, "engine-run", workflow_name="build-codex", status="failed")
    seed_event(db, "engine-run", "close", data={"outcome": "failed"})

    report = _stats(db)

    close = _verb(report, "close")
    assert (close.attempts, close.ok, close.failed) == (1, 1, 0)
    assert report.runs.total == 1
    assert report.excluded.retired_engine_runs == 1
    assert report.excluded.retired_engine_events == 1


def test_the_worktree_path_column_is_not_the_discriminator(tmp_path: Path) -> None:
    """A verb-model run with no worktree still counts.

    ``defer`` and ``release`` write their own terminal run rows and never create
    a worktree, so ``worktree_path IS NOT NULL`` — the discriminator the ticket
    floated — would drop 8 live rows from the denominator. It answers "did this
    run have a worktree", not "was this the verb model".
    """
    db = tmp_path / "harness.db"
    seed_run(db, "defer-run", workflow_name="defer")
    seed_event(db, "defer-run", "defer", data={"ticket": "265"})

    report = _stats(db)

    assert _verb(report, "defer").attempts == 1
    assert report.excluded.retired_engine_runs == 0


def test_retired_engine_event_types_are_excluded(tmp_path: Path) -> None:
    """``node_started`` and friends are not verb attempts, wherever they sit."""
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "close", data={"outcome": "ok"})
    for legacy in ("node_started", "node_completed", "state_changed"):
        seed_event(db, "run-1", legacy)

    report = _stats(db)

    assert {v.verb for v in report.verbs} == {"close"}
    assert _verb(report, "close").attempts == 1


def test_a_retired_event_type_does_not_widen_the_reported_window(
    tmp_path: Path,
) -> None:
    """The window must describe the rows actually counted.

    This is where the ``EVENT_TYPES`` allowlist does work no other filter does.
    Every *report* below re-checks the event type for itself — the verb table,
    the cycle count, the engines, the recovery breakdown — so dropping the
    allowlist changes none of them. The window span is the one consumer that
    reads the whole population, and a legacy row bleeding into it would state a
    covered range wider than anything the numbers describe.
    """
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "close", data={"outcome": "ok"}, timestamp="2026-07-02T00:00:00Z")
    seed_event(db, "run-1", "node_started", timestamp="2020-01-01T00:00:00Z")
    seed_event(db, "run-1", "node_completed", timestamp="2030-01-01T00:00:00Z")

    window = _stats(db).window

    assert window.earliest_event == "2026-07-02T00:00:00Z"
    assert window.latest_event == "2026-07-02T00:00:00Z"


def test_engine_era_failures_do_not_pollute_the_recovery_reasons(
    tmp_path: Path,
) -> None:
    """The recovery report counts ``cancel``/``reclaim``, not engine tracebacks.

    ``workflow_failed`` is a *live* event type — ``harness cancel`` writes it —
    so the event-type allowlist cannot see this one. The retired engine wrote 25
    rows of Python exception names under the same type, and without the run-kind
    filter they land straight in the recovery breakdown as if they were
    reclamations. This is the case that makes both filters load-bearing.
    """
    db = tmp_path / "harness.db"
    seed_run(db, "verb-run")
    seed_event(db, "verb-run", "workflow_failed", data={"reason": "reclaimed"})
    seed_run(db, "engine-run", workflow_name="build", status="failed")
    seed_event(db, "engine-run", "workflow_failed", data={"reason": "BrokenPipeError"})

    report = _stats(db)

    assert report.recovery.by_reason == {"reclaimed": 1}


# ---------------------------------------------------------------------------
# AC-3 — refused and failed are distinct, never summed into one rate
# ---------------------------------------------------------------------------


def test_refused_and_failed_are_reported_separately(tmp_path: Path) -> None:
    """A gate that refuses correctly is doing its job (ADR 0009).

    Folding refusals into a single "failure rate" creates pressure toward
    weaker gates, so the two counts stay distinct.
    """
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "close", data={"outcome": "refused", "reason": "no_run"})
    seed_event(db, "run-1", "close", data={"outcome": "refused", "reason": "stale_review"})
    seed_event(db, "run-1", "close", data={"outcome": "failed", "reason": "merge_conflict"})

    close = _verb(_stats(db), "close")

    assert close.refused == 2
    assert close.failed == 1


def test_no_failure_rate_field_folds_the_two_together() -> None:
    """The model exposes a success rate and no failure rate.

    Asserted on the declared shape rather than on one report's values: a
    ``failure_rate`` field is exactly the summing AC-3 forbids, and it would
    arrive by a future edit, not by any seed written here.
    """
    from harness.cli.stats_aggregate import VerbReport

    fields = set(VerbReport.model_fields)

    assert "success_rate" in fields
    assert not [f for f in fields if "failure" in f]


def test_an_unrecognised_outcome_reads_as_failed(tmp_path: Path) -> None:
    """An outcome value this reader does not know is not a success.

    The conservative direction: a verb that recorded something unrecognised did
    not demonstrably succeed, and reading it as ``ok`` would inflate the very
    rate this command exists to report.
    """
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "close", data={"outcome": "banana"})

    close = _verb(_stats(db), "close")

    assert (close.ok, close.refused, close.failed) == (0, 0, 1)


# ---------------------------------------------------------------------------
# Per-verb outcome keys are not uniform
# ---------------------------------------------------------------------------


def test_design_discriminates_on_status_not_outcome(tmp_path: Path) -> None:
    """``design`` splits on ``$.status``, the other two on ``$.outcome``.

    ADR 0007 D4 shipped ``design``'s split before ADR 0009 named the field, so
    the key genuinely differs. Reading ``$.outcome`` here would score every
    design — including the failures — as an unrecognised outcome.
    """
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "design", data={"status": "ok"})
    seed_event(
        db, "run-1", "design", data={"status": "failed", "reason": "engine_timeout"}
    )

    design = _verb(_stats(db), "design")

    assert (design.attempts, design.ok, design.failed) == (2, 1, 1)
    assert design.reasons == {"engine_timeout": 1}


def test_review_records_its_refusals_as_failed_not_refused(tmp_path: Path) -> None:
    """``review`` has no ``refused`` bucket, and the report says so with a zero.

    #262 gave the review payload two outcome values, not three: its exit-5
    refusals (``no_design`` / ``no_gate_evidence`` / ``gate_failed``) are
    recorded as ``failed``. That asymmetry with ``close`` is real, and reporting
    a truthful zero is better than inventing a bucket the writer never fills.
    """
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(
        db, "run-1", "review", data={"outcome": "failed", "reason": "no_gate_evidence"}
    )

    review = _verb(_stats(db), "review")

    assert (review.failed, review.refused) == (1, 0)


def test_verbs_that_only_ever_record_success_report_no_failures(
    tmp_path: Path,
) -> None:
    """``checkpoint`` / ``defer`` / ``release`` write an event only when they win.

    #264 established this by analysis: every refusal and error on those three
    raises before the emit, so there are no non-ok rows to discriminate and the
    payloads carry no discriminator field at all.
    """
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "checkpoint", data={"pushed_sha": "abc"})
    seed_event(db, "run-1", "release", data={"ticket": "265"})

    report = _stats(db)

    for verb in ("checkpoint", "release"):
        assert (_verb(report, verb).ok, _verb(report, verb).failed) == (1, 0)


# ---------------------------------------------------------------------------
# AC-4 — latency reports a median and a max, never a mean alone
# ---------------------------------------------------------------------------


def test_latency_reports_a_median_and_a_max(tmp_path: Path) -> None:
    """The engine-timeout decision turned on the right tail, so the max is
    load-bearing — a mean would have hidden the two runs that were being
    clipped."""
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    for ms in (100, 200, 900):
        seed_event(db, "run-1", "design", data={"status": "ok"}, duration_ms=ms)

    latency = _verb(_stats(db), "design").latency

    assert latency.count == 3
    assert latency.median_ms == 200
    assert latency.max_ms == 900


def test_the_latency_model_declares_no_mean(tmp_path: Path) -> None:
    """AC-4 asserted on the shape: a mean alone is what it rules out."""
    from harness.cli.stats_aggregate import LatencyReport

    fields = set(LatencyReport.model_fields)

    assert {"median_ms", "max_ms"} <= fields
    assert not [f for f in fields if "mean" in f or "avg" in f]


def test_a_duration_is_read_from_the_column_or_the_payload(tmp_path: Path) -> None:
    """#262/#263 put theirs in the payload; #264 put four verbs' in the column.

    The split is real, deliberate and documented, so this reader coalesces the
    two homes rather than picking one and silently reporting half the samples.
    """
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "review", data={"outcome": "ok", "duration_ms": 500})
    seed_event(db, "run-1", "review", data={"outcome": "ok"}, duration_ms=1_500)

    latency = _verb(_stats(db), "review").latency

    assert latency.count == 2
    assert latency.max_ms == 1_500


def test_the_column_wins_when_a_row_carries_both(tmp_path: Path) -> None:
    """``COALESCE(column, payload)`` — the typed column is the preferred home."""
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "review", data={"outcome": "ok", "duration_ms": 9}, duration_ms=7)

    assert _verb(_stats(db), "review").latency.max_ms == 7


def test_rows_with_no_duration_are_absent_from_the_sample_not_zero(
    tmp_path: Path,
) -> None:
    """Nothing backfills (ADR 0009), so most historical rows carry no duration.

    Counting them as zero would drag every median toward zero and make the
    pre-telemetry era look instantaneous.
    """
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "review", data={"outcome": "ok"})
    seed_event(db, "run-1", "review", data={"outcome": "ok"}, duration_ms=400)

    review = _verb(_stats(db), "review")

    assert review.attempts == 2
    assert review.latency.count == 1
    assert review.latency.median_ms == 400


def test_run_wall_clock_is_reported_from_the_run_row(tmp_path: Path) -> None:
    """``runs.duration_ms`` (#261) is the run's wall clock — not a verb's."""
    db = tmp_path / "harness.db"
    seed_run(db, "run-1", duration_ms=1_000)
    seed_run(db, "run-2", duration_ms=3_000)
    seed_run(db, "run-3", duration_ms=2_000)

    wall = _stats(db).runs.wall_clock

    assert (wall.count, wall.median_ms, wall.max_ms) == (3, 2_000, 3_000)


# ---------------------------------------------------------------------------
# AC-5 — the output names the window it covers
# ---------------------------------------------------------------------------


def test_the_output_names_the_window_it_covers(tmp_path: Path) -> None:
    """Pre-telemetry history reads as zero refusals, which is not the same as
    no refusals — so the span the numbers describe is stated, not implied."""
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "close", data={"outcome": "ok"}, timestamp="2026-07-01T10:00:00Z")
    seed_event(db, "run-1", "close", data={"outcome": "ok"}, timestamp="2026-07-03T10:00:00Z")

    window = _stats(db).window

    assert window.since is None
    assert window.earliest_event == "2026-07-01T10:00:00Z"
    assert window.latest_event == "2026-07-03T10:00:00Z"


def test_since_narrows_the_window_and_is_echoed(tmp_path: Path) -> None:
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "close", data={"outcome": "ok"}, timestamp="2020-01-01T00:00:00Z")

    report = _stats(db, "--since", "7d")

    assert report.window.since == "7d"
    assert report.window.from_timestamp is not None
    assert _verb_or_none(report, "close") is None


def _verb_or_none(report: StatsReport, verb: str) -> Any:
    match = [v for v in report.verbs if v.verb == verb]
    return match[0] if match else None


def test_the_since_window_handles_both_timestamp_shapes(tmp_path: Path) -> None:
    """``runs.started_at`` is written both ways in the live ledger.

    ``harness._time`` documents the run columns as plain ``.isoformat()``
    (``+00:00``) against the events' trailing ``Z`` — but real rows carry *both*
    shapes in the same column. A SQL string comparison would therefore order
    ``…+00:00`` and ``…Z`` against each other by byte value rather than by
    instant, so the window is resolved by parsing, not by comparing text.
    """
    db = tmp_path / "harness.db"
    seed_run(db, "z-run", started_at="2020-01-01T00:00:00Z")
    seed_run(db, "offset-run", started_at="2020-01-01T00:00:00+00:00")

    assert _stats(db, "--since", "7d").runs.total == 0
    assert _stats(db).runs.total == 2


def test_an_invalid_since_is_refused(tmp_path: Path) -> None:
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")

    result = runner.invoke(app, ["stats", "--db", str(db), "--since", "soon"])

    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# Review cycles per run
# ---------------------------------------------------------------------------


def test_review_cycles_per_run_counts_engine_runs(tmp_path: Path) -> None:
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    for _ in range(3):
        seed_event(db, "run-1", "review", data={"outcome": "ok", "verdict": "fail"})

    cycles = _stats(db).review_cycles

    assert (cycles.runs_reviewed, cycles.total, cycles.max) == (1, 3, 3)


def test_review_cycles_exclude_what_the_ceiling_excludes(tmp_path: Path) -> None:
    """An inherited pass (#259) and a refusal (#262) each run no engine.

    The cycle count here means the same thing it means to the breaker that
    bounds it — otherwise the report and the ceiling would disagree about the
    number they are both describing.
    """
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "review", data={"outcome": "ok", "verdict": "pass"})
    seed_event(db, "run-1", "review", data={"outcome": "ok", "inherited_from": "other"})
    seed_event(db, "run-1", "review", data={"outcome": "failed", "reason": "no_design"})

    assert _stats(db).review_cycles.total == 1


def test_a_run_with_no_reviews_is_not_in_the_cycle_denominator(
    tmp_path: Path,
) -> None:
    db = tmp_path / "harness.db"
    seed_run(db, "reviewed")
    seed_event(db, "reviewed", "review", data={"outcome": "ok", "verdict": "pass"})
    seed_run(db, "unreviewed")

    assert _stats(db).review_cycles.runs_reviewed == 1


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------


def test_verdicts_are_broken_down_by_engine(tmp_path: Path) -> None:
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "review", data={"outcome": "ok", "verdict": "pass", "engine": "claude"})
    seed_event(db, "run-1", "review", data={"outcome": "ok", "verdict": "fail", "engine": "claude"})
    seed_event(db, "run-1", "review", data={"outcome": "ok", "verdict": "pass", "engine": "codex"})

    engines = {e.engine: e for e in _stats(db).engines.by_engine}

    assert engines["claude"].by_verdict == {"pass": 1, "fail": 1}
    assert engines["codex"].verdicts == 1


def test_a_review_refusal_is_attributed_to_no_engine(tmp_path: Path) -> None:
    """``ReviewRefusalEventData`` carries no ``engine`` field.

    Which means an ``engine_timeout`` — the failure most worth attributing — has
    no engine recorded against it. The honest report is a per-engine breakdown
    of the verdicts that were *produced*, with the unattributable failures
    counted in the verb's own ``reasons``; inventing an attribution would be
    worse than naming the gap.
    """
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(
        db, "run-1", "review", data={"outcome": "failed", "reason": "engine_timeout"}
    )

    report = _stats(db)

    assert report.engines.by_engine == []
    assert report.engines.unattributed == 1
    assert _verb(report, "review").reasons == {"engine_timeout": 1}


def test_the_engine_breakdown_reconciles_with_the_review_count(
    tmp_path: Path,
) -> None:
    """Attributed verdicts plus unattributed equals the review attempts.

    Found by running the command against the live ledger: it reported 296
    verdicts across two engines over a population of 399 reviews, and nothing in
    the output explained the other 103 — which are pre-``engine``-field history.
    An engine list that silently covers three quarters of the reviews reads as a
    complete breakdown, so the remainder is counted rather than dropped.
    """
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "review", data={"outcome": "ok", "verdict": "pass", "engine": "claude"})
    seed_event(db, "run-1", "review", data={"outcome": "ok", "verdict": "pass"})
    seed_event(db, "run-1", "review", data={"outcome": "failed", "reason": "no_design"})

    report = _stats(db)
    engines = report.engines

    attributed = sum(e.verdicts for e in engines.by_engine)
    assert attributed + engines.unattributed == _verb(report, "review").attempts


def test_the_human_form_names_the_unattributed_reviews(tmp_path: Path) -> None:
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "review", data={"outcome": "ok", "verdict": "pass"})

    result = runner.invoke(app, ["stats", "--db", str(db)])

    assert "recorded no engine" in result.stdout


# ---------------------------------------------------------------------------
# AC-6 — an empty ledger reports zero cleanly
# ---------------------------------------------------------------------------


def test_an_empty_ledger_reports_zero_without_dividing_by_zero(
    tmp_path: Path,
) -> None:
    db = tmp_path / "harness.db"
    run_sync(store.init_db(db))

    report = _stats(db)

    assert report.runs.total == 0
    assert report.verbs == []
    assert report.review_cycles.total == 0
    assert report.runs.wall_clock.median_ms is None


def test_a_missing_ledger_reports_zero_rather_than_failing(tmp_path: Path) -> None:
    """``runs`` already treats a missing DB as the empty case, not an error."""
    report = _stats(tmp_path / "absent.db")

    assert report.runs.total == 0


def test_a_verb_with_no_durations_reports_a_null_median(tmp_path: Path) -> None:
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "close", data={"outcome": "ok"})

    latency = _verb(_stats(db), "close").latency

    assert (latency.count, latency.median_ms, latency.max_ms) == (0, None, None)


# ---------------------------------------------------------------------------
# AC-7 — the JSON shape is declared and stable
# ---------------------------------------------------------------------------


def test_json_output_validates_against_the_declared_model(tmp_path: Path) -> None:
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "close", data={"outcome": "ok"})

    result = runner.invoke(app, ["stats", "--db", str(db), "--json"])

    assert result.exit_code == 0
    StatsReport.model_validate_json(result.stdout.strip())


def test_the_json_top_level_keys_are_pinned(tmp_path: Path) -> None:
    """Flag names and JSON keys are part of the public contract."""
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")

    payload = json.loads(
        runner.invoke(app, ["stats", "--db", str(db), "--json"]).stdout.strip()
    )

    assert set(payload) == {
        "window",
        "runs",
        "verbs",
        "review_cycles",
        "recovery",
        "engines",
        "excluded",
    }


def test_the_human_form_is_not_json(tmp_path: Path) -> None:
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "close", data={"outcome": "ok"})

    result = runner.invoke(app, ["stats", "--db", str(db)])

    assert result.exit_code == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)
    assert "close" in result.stdout


def test_the_human_form_states_the_window(tmp_path: Path) -> None:
    """AC-5 holds for the form a human actually reads, not only for ``--json``."""
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "close", data={"outcome": "ok"}, timestamp="2026-07-01T10:00:00Z")

    result = runner.invoke(app, ["stats", "--db", str(db)])

    assert "2026-07-01T10:00:00Z" in result.stdout


# ---------------------------------------------------------------------------
# AC-8 — the command is read-only
# ---------------------------------------------------------------------------


def test_the_command_does_not_write_to_the_ledger(tmp_path: Path) -> None:
    """The DB file is byte-identical before and after."""
    db = tmp_path / "harness.db"
    seed_run(db, "run-1")
    seed_event(db, "run-1", "close", data={"outcome": "ok"})
    before = db.read_bytes()

    assert runner.invoke(app, ["stats", "--db", str(db), "--json"]).exit_code == 0

    assert db.read_bytes() == before


def test_the_connection_itself_refuses_writes(tmp_path: Path) -> None:
    """Read-only is enforced by the connection, not by care at the call sites.

    A byte-comparison proves this command does not write today; opening the
    database ``mode=ro`` is what stops a future edit here from writing at all.
    """
    import aiosqlite

    from harness.cli.stats_aggregate import _connect_readonly

    db = tmp_path / "harness.db"
    seed_run(db, "run-1")

    async def _try_write() -> None:
        async with _connect_readonly(db) as conn:
            await conn.execute("INSERT INTO runs (run_id, workflow_name, "
                               "workflow_version, status, state_json, inputs_json, "
                               "started_at) VALUES ('x', '', 1, 'open', '{}', '{}', 'now')")

    with pytest.raises(aiosqlite.OperationalError):
        run_sync(_try_write())


def test_stats_does_not_create_a_missing_ledger(tmp_path: Path) -> None:
    """A read command must not bring a database into existence."""
    db = tmp_path / "absent.db"

    runner.invoke(app, ["stats", "--db", str(db), "--json"])

    assert not db.exists()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_stats_is_registered_on_the_cli(tmp_path: Path) -> None:
    result = runner.invoke(app, ["stats", "--help"])

    assert result.exit_code == 0
