"""``harness stats`` — the aggregate ledger reader (#265).

``status`` / ``logs`` / ``events`` / ``runs`` all read **one** run. This reads
across them: per-verb attempt counts with their success / refused / failed
split, verb and run latency distributions, review cycles per run, recovery
counts, and the review engines' verdicts.

The aggregation itself lives in :mod:`harness.cli.stats_aggregate` — this module
owns the flags, the window resolution and the human rendering. Async DB access
is wrapped in :func:`asyncio.run` at the command boundary because Typer
dispatches synchronously, as the rest of the read family does.

Exit codes:
* 0 — succeeded. A missing or empty DB is the empty case, not an error: this
  command reads by query rather than by run id, so it reports zeros and exits 0
  exactly as ``runs`` does.
* 2 — invocation error: a bad ``--since``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import typer

from harness.cli._duration import _parse_duration
from harness.cli._query_common import _resolve_db_path
from harness.cli.stats_aggregate import LatencyReport, StatsReport, collect


def _render_latency(latency: LatencyReport) -> str:
    if latency.count == 0:
        return "no durations recorded"
    return f"median {latency.median_ms}ms  max {latency.max_ms}ms  (n={latency.count})"


def _render(report: StatsReport) -> list[str]:
    """The human form.

    It states the covered window first because that is the caveat every number
    below it depends on: nothing backfills, so an era before a verb recorded its
    refusals reads as zero refusals rather than as unmeasured.
    """
    window = report.window
    span = (
        f"{window.earliest_event} .. {window.latest_event}"
        if window.earliest_event
        else "no events in window"
    )
    lines = [
        f"window   {window.since or 'all time'}  [{span}]",
        f"runs     {report.runs.total}  "
        + "  ".join(f"{k}={v}" for k, v in sorted(report.runs.by_status.items())),
        f"         wall clock: {_render_latency(report.runs.wall_clock)}",
        "",
        f"{'verb':<12}{'attempts':>9}{'ok':>6}{'refused':>9}{'failed':>8}{'success':>9}"
        "   latency",
    ]
    for verb in report.verbs:
        rate = "-" if verb.success_rate is None else f"{verb.success_rate:.0%}"
        lines.append(
            f"{verb.verb:<12}{verb.attempts:>9}{verb.ok:>6}{verb.refused:>9}"
            f"{verb.failed:>8}{rate:>9}   {_render_latency(verb.latency)}"
        )
        if verb.reasons:
            reasons = ", ".join(
                f"{r}={n}" for r, n in sorted(verb.reasons.items(), key=lambda p: -p[1])
            )
            lines.append(f"{'':<12}  reasons: {reasons}")

    cycles = report.review_cycles
    lines += [
        "",
        f"review cycles  {cycles.total} over {cycles.runs_reviewed} runs  "
        f"(median {cycles.median}, max {cycles.max})",
    ]
    for engine in report.engines.by_engine:
        verdicts = ", ".join(f"{k}={v}" for k, v in sorted(engine.by_verdict.items()))
        lines.append(f"engine {engine.engine:<8} {engine.verdicts} verdicts  {verdicts}")
    if report.engines.unattributed:
        lines.append(
            f"engine (none)   {report.engines.unattributed} reviews recorded no engine"
        )
    if report.recovery.by_reason or report.recovery.reclaims_undone:
        recovered = ", ".join(
            f"{k}={v}" for k, v in sorted(report.recovery.by_reason.items())
        )
        lines.append(
            f"recovery       {recovered}  undone={report.recovery.reclaims_undone}"
        )
    lines.append(
        f"excluded       {report.excluded.retired_engine_runs} retired-engine runs, "
        f"{report.excluded.retired_engine_events} of their events"
    )
    return lines


def stats_command(
    since: str | None = typer.Option(
        None,
        "--since",
        help="Only count rows newer than this (e.g. 30m, 12h, 7d). Default: all time.",
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db)."
    ),
    json_output: bool = typer.Option(
        False, "--json/--no-json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Aggregate statistics over the run ledger."""
    db_path = _resolve_db_path(db)
    cutoff = datetime.now(UTC) - _parse_duration(since) if since is not None else None

    report = asyncio.run(collect(db_path, since=since, cutoff=cutoff))

    if json_output:
        typer.echo(report.model_dump_json())
        return
    for line in _render(report):
        typer.echo(line)


__all__ = ["stats_command"]
