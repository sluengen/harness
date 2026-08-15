"""The aggregation behind ``harness stats`` — the ledger reads (#265).

Breakdown item 5 of ``verb-telemetry`` (ADR 0009), and deliberately the last:
items 1–4 made every verb record its *attempts* rather than only its successes,
so a rate computed here has an honest denominator. Before them the ledger held
verdicts and merges — "how often does review succeed?" was unanswerable rather
than merely slow.

``status`` / ``logs`` / ``events`` / ``runs`` are all per-run readers. This is
the aggregate one, and it is a new noun rather than a ``--summary`` flag on
``runs`` because the read surface is already a set of nouns.

**Two discriminators, both load-bearing.** A verb-model rate must not be
computed over rows the deterministic engine retired in CAL-574 wrote:

* **Run kind** — :data:`~harness.state.schema.RETIRED_ENGINE_WORKFLOWS`.
* **Event type** — :data:`~harness.events.schema.EVENT_TYPES`, the *writable*
  set, so a new verb's type joins with no edit here.

Neither subsumes the other. ``workflow_failed`` is a live type (``harness
cancel`` writes it) that the retired engine also wrote, so the type allowlist
alone lets 25 rows of Python exception names — ``AgentStalled``,
``BrokenPipeError`` — into the recovery breakdown; the run filter is what keeps
them out. The run filter alone happens to suffice on today's ledger, but only
because no live-typed event currently sits on a retired run, which is a property
of the data rather than a guarantee.

**Aggregation happens in Python, not SQL.** Two queries fetch the rows and the
counting is done here, for one substantive reason beyond simplicity: the window
filter *cannot* be a SQL string comparison. ``runs.started_at`` carries both the
trailing-``Z`` and the ``+00:00`` shape in live rows (``harness._time``
documents the split as deliberate for the run columns), and comparing those two
spellings as text orders them by byte value rather than by instant. The window
is therefore resolved by parsing each timestamp.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from harness._time import iso_z, parse_iso_z
from harness.cli.stats_report import (
    EngineReport,
    EnginesReport,
    ExclusionReport,
    LatencyReport,
    RecoveryReport,
    ReviewCycleReport,
    RunReport,
    StatsReport,
    VerbReport,
    WindowReport,
)
from harness.events.payloads import (
    CLOSE_OUTCOME_OK,
    CLOSE_OUTCOME_PATH,
    CLOSE_OUTCOME_REFUSED,
    CLOSE_REASON_PATH,
    DESIGN_STATUS_PATH,
    REVIEW_INHERITED_FROM_PATH,
    REVIEW_OUTCOME_PATH,
    REVIEW_VERDICT_PATH,
    WORKFLOW_FAILED_REASON_KEY,
)
from harness.events.schema import EVENT_TYPES
from harness.state.schema import RETIRED_ENGINE_WORKFLOWS

#: The ``json_extract`` path carrying each verb's outcome, or ``None`` for a
#: verb that writes an event only on its success path.
#:
#: The keys are not uniform and that is not an oversight. ``design`` shipped its
#: two-shape split under ``$.status`` (ADR 0007 D4) before ADR 0009 named the
#: field ``outcome`` for ``review`` (#262) and ``close`` (#263); reading
#: ``$.outcome`` from a design row would score every one of them — successes
#: included — as an outcome this reader does not recognise.
#:
#: ``checkpoint`` / ``defer`` / ``release`` map to ``None``: #264 established by
#: analysis that every refusal and error on those three raises *before* the
#: emit, so there are no non-ok rows for a discriminator to discriminate, and
#: their payloads carry no such field. ``defer`` / ``release`` keep their keys
#: after #338 retired their emitters: the rows already on disk still need
#: scoring, and dropping the keys would score them as an unknown verb rather
#: than the successes they are.
VERB_OUTCOME_PATHS: dict[str, str | None] = {
    "review": REVIEW_OUTCOME_PATH,
    "close": CLOSE_OUTCOME_PATH,
    "design": DESIGN_STATUS_PATH,
    "checkpoint": None,
    "defer": None,
    "release": None,
    # ``certify`` (#353) writes an event only on its success path — the upgrade
    # path records its outcome on the run row and the ticket, not the ledger —
    # so there is no discriminator to read, exactly as for ``checkpoint``.
    # Without the key its rows would be scored as an unknown verb and vanish
    # from ``harness stats``; nothing raises, which is why this is guarded by
    # test rather than left to be noticed.
    "certify": None,
}

#: Event types that are verb *attempts*. ``workflow_failed`` and
#: ``reclaim_undone`` are live types but not attempts — they are recovery
#: signals, reported separately by :class:`RecoveryReport`.
VERB_EVENT_TYPES: frozenset[str] = frozenset(VERB_OUTCOME_PATHS)

assert VERB_EVENT_TYPES <= EVENT_TYPES, "every verb type must be a writable type"

#: The reason a non-``ok`` row carries. One path serves four payloads —
#: ``review``'s refusal shape, ``close``'s failure shape, ``design``'s failed
#: shape and ``workflow_failed`` all name the field ``reason``, which #263 notes
#: is deliberate ("one vocabulary across the telemetry family").
#:
#: The assertion is what makes that a checked claim rather than a coincidence
#: this reader silently depends on: if ``workflow_failed`` ever renamed its
#: field, a single path would quietly return NULL for every recovery row and the
#: breakdown would empty out with nothing failing.
_REASON_PATH = CLOSE_REASON_PATH

#: Each discriminating verb's ``SELECT`` alias in :func:`_fetch_events`. The
#: keys must be exactly the verbs whose :data:`VERB_OUTCOME_PATHS` entry is not
#: ``None`` — asserted below, because giving a verb a discriminator in one
#: mapping and forgetting the other would leave its outcomes silently unread and
#: every one of its rows scored ``ok``.
_OUTCOME_ALIASES: dict[str, str] = {
    "review": "review_outcome",
    "close": "close_outcome",
    "design": "design_status",
}

_DISCRIMINATING_VERBS = {v for v, path in VERB_OUTCOME_PATHS.items() if path is not None}
if set(_OUTCOME_ALIASES) != _DISCRIMINATING_VERBS:  # pragma: no cover - import guard
    raise ValueError(
        "every verb with an outcome path needs a column alias to read it back: "
        f"{sorted(_OUTCOME_ALIASES)} != {sorted(_DISCRIMINATING_VERBS)}"
    )

_WORKFLOW_FAILED_REASON_PATH = f"$.{WORKFLOW_FAILED_REASON_KEY}"
if _WORKFLOW_FAILED_REASON_PATH != _REASON_PATH:  # pragma: no cover - import guard
    raise ValueError(
        "the telemetry payloads must name their reason field alike: "
        f"{_REASON_PATH} != {_WORKFLOW_FAILED_REASON_PATH}"
    )


@asynccontextmanager
async def _connect_readonly(db_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """Open the ledger read-only.

    Not :func:`harness.state.store.connect` — it ``mkdir``s the parent and sets
    ``PRAGMA journal_mode = WAL``, both of which are writes — and not a bare
    ``aiosqlite.connect``, which *creates* the file when it is missing. The
    ``mode=ro`` URI is what makes "this command is read-only" a property of the
    connection rather than of care at each call site: a write added here later
    raises instead of landing.
    """
    conn = await aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.row_factory = aiosqlite.Row
        yield conn
    finally:
        await conn.close()


def _within(timestamp: str | None, cutoff: datetime | None) -> bool:
    """Is *timestamp* inside the window?

    With no ``--since`` every row is in scope, whatever its timestamp — an
    unparseable value is data the report should still count. With a window, a
    timestamp that cannot be parsed is treated as outside it: the command was
    asked for a bounded span and cannot honestly place that row inside one.
    """
    if cutoff is None:
        return True
    if timestamp is None:
        return False
    try:
        return parse_iso_z(timestamp) >= cutoff
    except (TypeError, ValueError):
        return False


def _latency(samples: Sequence[int]) -> LatencyReport:
    if not samples:
        return LatencyReport(count=0)
    return LatencyReport(
        count=len(samples),
        median_ms=int(statistics.median(samples)),
        max_ms=max(samples),
    )


def _bucket(outcome: str | None) -> str:
    """Which of the three buckets a row falls in.

    A missing value ``COALESCE``s to ``ok``, and that one rule covers two cases
    at once. Every row written before its verb gained the discriminator was in
    fact a success, which is what keeps the historical ledger from reading as a
    wall of unknowns — and a verb that writes an event *only* on success
    (``checkpoint`` / ``defer`` / ``release``, whose payloads carry no such
    field at all) reads ``None`` here for the same reason and lands in the same
    bucket. An explicit "this verb has no discriminator" branch was tried and
    removed: nothing could distinguish it from this line, which makes it a
    second copy of it rather than a second rule. The fact it was expressing is
    already carried by :data:`VERB_OUTCOME_PATHS`, where those three map to
    ``None``.

    Anything unrecognised reads as ``failed``, the conservative direction: a
    verb that recorded something this reader does not understand did not
    demonstrably succeed, and scoring it ``ok`` would inflate the very rate the
    command exists to report.
    """
    if outcome is None or outcome == CLOSE_OUTCOME_OK:
        return "ok"
    if outcome == CLOSE_OUTCOME_REFUSED:
        return "refused"
    return "failed"


async def _fetch_events(conn: aiosqlite.Connection) -> list[dict[str, Any]]:
    """Every event, carrying its run's ``workflow_name`` so the two
    discriminators can both be applied here."""
    async with conn.execute(
        "SELECT e.event_type, e.timestamp, e.run_id, r.workflow_name, "
        "       e.duration_ms AS column_ms, "
        "       json_extract(e.data_json, '$.duration_ms') AS payload_ms, "
        "       json_extract(e.data_json, ?) AS review_outcome, "
        "       json_extract(e.data_json, ?) AS close_outcome, "
        "       json_extract(e.data_json, ?) AS design_status, "
        "       json_extract(e.data_json, ?) AS reason, "
        "       json_extract(e.data_json, ?) AS verdict, "
        "       json_extract(e.data_json, '$.engine') AS engine, "
        "       json_extract(e.data_json, ?) AS inherited_from "
        "FROM events e JOIN runs r USING (run_id)",
        (
            REVIEW_OUTCOME_PATH,
            CLOSE_OUTCOME_PATH,
            DESIGN_STATUS_PATH,
            _REASON_PATH,
            REVIEW_VERDICT_PATH,
            REVIEW_INHERITED_FROM_PATH,
        ),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def _fetch_runs(conn: aiosqlite.Connection) -> list[dict[str, Any]]:
    async with conn.execute(
        "SELECT workflow_name, status, started_at, duration_ms FROM runs"
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


def _outcome_of(row: dict[str, Any]) -> str | None:
    """The row's own discriminator value, read from the column its verb uses.

    A verb absent from :data:`_OUTCOME_ALIASES` has no discriminator and answers
    ``None``, which :func:`_bucket` reads as ``ok``.
    """
    alias = _OUTCOME_ALIASES.get(str(row["event_type"]))
    return None if alias is None else row[alias]


def _duration_of(row: dict[str, Any]) -> int | None:
    """``COALESCE(column, payload)``.

    #262/#263 wrote ``review``'s and ``close``'s durations into the payload;
    #264 wrote the other four verbs' into the typed column. The split is real
    and documented, so this reads both homes rather than picking one and
    silently reporting half the samples. The column wins where a row has both —
    it is the preferred home, and converging the two is its own change.
    """
    if row["column_ms"] is not None:
        return int(row["column_ms"])
    if row["payload_ms"] is not None:
        try:
            return int(row["payload_ms"])
        except (TypeError, ValueError):
            return None
    return None


def _verb_reports(events: Iterable[dict[str, Any]]) -> list[VerbReport]:
    buckets: dict[str, Counter[str]] = defaultdict(Counter)
    reasons: dict[str, Counter[str]] = defaultdict(Counter)
    durations: dict[str, list[int]] = defaultdict(list)

    for row in events:
        verb = str(row["event_type"])
        if verb not in VERB_OUTCOME_PATHS:
            continue
        bucket = _bucket(_outcome_of(row))
        buckets[verb][bucket] += 1
        if bucket != "ok" and row["reason"] is not None:
            reasons[verb][str(row["reason"])] += 1
        duration = _duration_of(row)
        if duration is not None:
            durations[verb].append(duration)

    reports = []
    for verb in sorted(buckets):
        counts = buckets[verb]
        attempts = sum(counts.values())
        reports.append(
            VerbReport(
                verb=verb,
                attempts=attempts,
                ok=counts["ok"],
                refused=counts["refused"],
                failed=counts["failed"],
                success_rate=counts["ok"] / attempts if attempts else None,
                reasons=dict(reasons[verb]),
                latency=_latency(durations[verb]),
            )
        )
    return reports


def _review_cycles(events: Iterable[dict[str, Any]]) -> ReviewCycleReport:
    per_run: Counter[str] = Counter()
    for row in events:
        if row["event_type"] != "review":
            continue
        if row["inherited_from"] is not None:
            continue
        if _bucket(row["review_outcome"]) != "ok":
            continue
        per_run[str(row["run_id"])] += 1

    counts = list(per_run.values())
    return ReviewCycleReport(
        runs_reviewed=len(counts),
        total=sum(counts),
        median=int(statistics.median(counts)) if counts else None,
        max=max(counts) if counts else None,
    )


def _engine_reports(events: Iterable[dict[str, Any]]) -> EnginesReport:
    by_engine: dict[str, Counter[str]] = defaultdict(Counter)
    unattributed = 0
    for row in events:
        if row["event_type"] != "review":
            continue
        if row["engine"] is None:
            unattributed += 1
            continue
        if row["verdict"] is None:
            unattributed += 1
            continue
        by_engine[str(row["engine"])][str(row["verdict"])] += 1
    return EnginesReport(
        by_engine=[
            EngineReport(
                engine=engine,
                verdicts=sum(verdicts.values()),
                by_verdict=dict(verdicts),
            )
            for engine, verdicts in sorted(by_engine.items())
        ],
        unattributed=unattributed,
    )


def _recovery(events: Iterable[dict[str, Any]]) -> RecoveryReport:
    reasons: Counter[str] = Counter()
    undone = 0
    for row in events:
        if row["event_type"] == "reclaim_undone":
            undone += 1
        elif row["event_type"] == "workflow_failed" and row["reason"] is not None:
            reasons[str(row["reason"])] += 1
    return RecoveryReport(by_reason=dict(reasons), reclaims_undone=undone)


def build_report(
    runs: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    since: str | None,
    cutoff: datetime | None,
) -> StatsReport:
    """Aggregate already-fetched rows into the report.

    Kept separate from the fetch so the arithmetic is testable without a
    database, and so both discriminators are applied in one visible place.
    """
    windowed_runs = [r for r in runs if _within(r["started_at"], cutoff)]
    retired_runs = [
        r for r in windowed_runs if str(r["workflow_name"]) in RETIRED_ENGINE_WORKFLOWS
    ]
    live_runs = [
        r
        for r in windowed_runs
        if str(r["workflow_name"]) not in RETIRED_ENGINE_WORKFLOWS
    ]
    windowed = [e for e in events if _within(e["timestamp"], cutoff)]
    retired_events = [
        e for e in windowed if str(e["workflow_name"]) in RETIRED_ENGINE_WORKFLOWS
    ]
    live_events = [
        e
        for e in windowed
        if str(e["workflow_name"]) not in RETIRED_ENGINE_WORKFLOWS
        and str(e["event_type"]) in EVENT_TYPES
    ]

    timestamps = sorted(str(e["timestamp"]) for e in live_events if e["timestamp"])
    wall_clock = [int(r["duration_ms"]) for r in live_runs if r["duration_ms"] is not None]

    return StatsReport(
        window=WindowReport(
            since=since,
            from_timestamp=iso_z(cutoff) if cutoff else None,
            earliest_event=timestamps[0] if timestamps else None,
            latest_event=timestamps[-1] if timestamps else None,
        ),
        runs=RunReport(
            total=len(live_runs),
            by_status=dict(Counter(str(r["status"]) for r in live_runs)),
            wall_clock=_latency(wall_clock),
        ),
        verbs=_verb_reports(live_events),
        review_cycles=_review_cycles(live_events),
        recovery=_recovery(live_events),
        engines=_engine_reports(live_events),
        excluded=ExclusionReport(
            retired_engine_runs=len(retired_runs),
            retired_engine_events=len(retired_events),
        ),
    )


async def collect(
    db_path: Path, *, since: str | None, cutoff: datetime | None
) -> StatsReport:
    """Read the ledger and aggregate it. A missing DB is the empty report."""
    if not db_path.exists():
        return build_report([], [], since=since, cutoff=cutoff)
    async with _connect_readonly(db_path) as conn:
        runs = await _fetch_runs(conn)
        events = await _fetch_events(conn)
    return build_report(runs, events, since=since, cutoff=cutoff)


__all__ = [
    "VERB_EVENT_TYPES",
    "VERB_OUTCOME_PATHS",
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
    "build_report",
    "collect",
]
