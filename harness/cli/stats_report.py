"""The published shape of ``harness stats`` — the report models (#265).

Split from :mod:`harness.cli.stats_aggregate` so the *contract* and the
*computation* sit in separate files: these models are the machine-readable
output SPEC §11 calls part of the public surface ("flag names and JSON keys are
part of the public contract — no breaking changes without a major version
bump"), while the module that fills them is free to change how it counts.

The rationale for each field lives on the model it constrains, because the
shapes here encode decisions rather than merely holding numbers: ``refused`` and
``failed` stay distinct (ADR 0009), latency reports a median and a max rather
than a mean, and the window and the excluded rows are stated rather than
implied.
"""

from __future__ import annotations

from pydantic import BaseModel


class LatencyReport(BaseModel):
    """A duration distribution — a median **and** a max, never a mean alone.

    The max is load-bearing rather than decorative: raising
    ``engine_timeout_seconds`` from 600 to 720 turned entirely on the right tail
    (two design runs landing at 516s and 561s against a 277s median), and a mean
    would have hidden exactly the samples the decision rested on.

    ``count`` is the number of rows that carried a duration at all, not the
    number of attempts. Nothing backfills (ADR 0009), so most historical rows
    have none; counting those as zero would drag every median down and make the
    pre-telemetry era read as instantaneous.
    """

    count: int
    median_ms: int | None = None
    max_ms: int | None = None


class VerbReport(BaseModel):
    """One verb's attempts, split three ways.

    ``refused`` and ``failed`` stay **distinct** (ADR 0009): a gate that refuses
    correctly is doing its job, and a single "failure rate" folding the two
    together creates pressure toward weaker gates. There is deliberately no
    ``failure_rate`` field — ``success_rate`` is ``ok / attempts``, which puts
    refusals in the denominator without ever summing them with errors.

    A verb whose writer has no ``refused`` value reports a truthful ``0`` rather
    than omitting the field: ``review``'s exit-5 refusals are recorded as
    ``failed`` (#262 gave that payload two outcome values, not three), and the
    asymmetry with ``close`` is real.
    """

    verb: str
    attempts: int
    ok: int
    refused: int
    failed: int
    success_rate: float | None = None
    reasons: dict[str, int] = {}
    latency: LatencyReport


class RunReport(BaseModel):
    """Run rows and their wall clock (``runs.duration_ms``, #261) — the whole
    run, as distinct from any one verb's latency."""

    total: int
    by_status: dict[str, int] = {}
    wall_clock: LatencyReport


class ReviewCycleReport(BaseModel):
    """Review→fix cycles per run.

    Counted with the *same* predicate the cycle ceiling uses — an inherited pass
    (#259) and a refusal (#262) each run no engine and neither is a cycle — so
    this report and the breaker that bounds it cannot disagree about the number
    they are both describing.
    """

    runs_reviewed: int
    total: int
    median: int | None = None
    max: int | None = None


class EngineReport(BaseModel):
    """One review engine's verdicts."""

    engine: str
    verdicts: int
    by_verdict: dict[str, int] = {}


class EnginesReport(BaseModel):
    """Verdicts by review engine, and the ones no engine can be named for.

    Two distinct populations carry no engine, and both are counted in
    ``unattributed`` rather than dropped, so ``sum(by_engine) + unattributed``
    reconciles with the review verdicts above it:

    * **Refusals.** ``ReviewRefusalEventData`` has no ``engine`` field at all, so
      an ``engine_timeout`` — the failure most worth attributing — has none
      recorded against it. Those are in ``review``'s own ``reasons``.
    * **History.** Verdicts predating the field on the success payload. 103 of
      the live ledger's 399 reviews are these.

    Reporting the count is the point: an engine list that silently covered 296
    of 399 reviews would read as a complete breakdown of the review population,
    and the discrepancy would be invisible to anyone not re-deriving it in SQL.
    Inventing an attribution would be worse than naming the gap.
    """

    by_engine: list[EngineReport] = []
    unattributed: int = 0


class RecoveryReport(BaseModel):
    """How often a run needed recovering, by ``workflow_failed`` reason
    (``cancelled`` / ``reclaimed``), plus reversals of a false-positive
    reclamation (#254)."""

    by_reason: dict[str, int] = {}
    reclaims_undone: int = 0


class WindowReport(BaseModel):
    """The span the numbers describe.

    Stated, never implied: nothing backfills, so every rate has a discontinuity
    at the ship date of the item that started recording it, and the era before
    it reads as *zero refusals* — which is not the same as no refusals.
    ``earliest_event`` / ``latest_event`` are what the ledger actually holds, as
    opposed to what ``--since`` asked for.
    """

    since: str | None = None
    from_timestamp: str | None = None
    earliest_event: str | None = None
    latest_event: str | None = None


class ExclusionReport(BaseModel):
    """Rows excluded from every rate above, labelled rather than silently
    dropped — a reader who sees 253 runs where the ledger holds 298 should be
    able to find the other 45 named here."""

    retired_engine_runs: int = 0
    retired_engine_events: int = 0


class StatsReport(BaseModel):
    """The declared shape of ``harness stats --json``.

    Flag names and JSON keys are part of the public contract (SPEC §11) — no
    breaking changes without a major version bump.
    """

    window: WindowReport
    runs: RunReport
    verbs: list[VerbReport]
    review_cycles: ReviewCycleReport
    recovery: RecoveryReport
    engines: EnginesReport
    excluded: ExclusionReport


__all__ = [
    "EngineReport",
    "EnginesReport",
    "ExclusionReport",
    "LatencyReport",
    "RecoveryReport",
    "ReviewCycleReport",
    "RunReport",
    "StatsReport",
    "VerbReport",
    "WindowReport",
]
