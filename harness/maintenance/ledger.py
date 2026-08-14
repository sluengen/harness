"""The durable record of every maintenance sweep — a sibling table (#310).

A sweep names no ticket, no run, no worktree, no branch and no verdict. It has
no ``start``, no gate and no ``close``; it survives no run and no run survives
it. So it cannot live in ``events``, whose ``run_id`` is
``TEXT NOT NULL REFERENCES runs(run_id)`` (:mod:`harness.state.store`), and it
must not live in ``runs``:

* ADR 0009 rejected *"a synthetic ``runs`` row to anchor a run-less refusal"*
  because it *"would put non-run rows in the ``runs`` table at volume"*, and a
  sweep fires every interval, per repo, forever — exactly that volume.
* #338 then **removed** the one that existed: it *"made a triage write
  indistinguishable from a build run in every ledger-backed view"*
  (``specs/features/run-ledger.md``). ``harness runs`` and ``harness stats``
  scan ``runs`` unfiltered, and they are the two an operator actually reads.

The home is therefore a **sibling table in the same per-project database**, on
the ``promotions`` precedent (:mod:`harness.state.promotions`) and by ADR 0009's
own criterion: the ``promotions`` table is not a precedent for observing a verb
more finely, because promotion *"is a genuinely separate lifecycle"*. Housekeeping
over a repo is on that side of the line. ``runs`` and ``events`` are untouched,
which ``test_maintenance_ledger.py`` measures — by capturing ``harness runs`` and
``harness stats`` across a sweep write — rather than assumes.

The row is the whole :class:`MaintenanceSweep` as a JSON blob, with ``swept_at``
and ``outcome`` denormalized for querying — the same shape ``promotions`` uses,
minus an id vocabulary this needs no part of: the row is never fetched by id,
only "newest for this repo", so there is no ULID to mint.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import aiosqlite
from pydantic import BaseModel, ConfigDict

from harness._time import iso_z, parse_iso_z
from harness.loop_budget import load_loop_budget
from harness.maintenance.schedule import (
    config_from_budget,
    sweep_lag_ms,
    sweep_overdue,
)
from harness.state import store

__all__ = [
    "MaintenanceSweep",
    "SweepOutcome",
    "SweepStep",
    "check_repo_sweeps",
    "check_sweeps",
    "init_sweeps",
    "iso_from_ms",
    "last_sweep",
    "ms_from_iso",
    "record_sweep",
]

#: What a cycle did, total by construction.
#:
#: ``completed`` — every step ran and exited 0. **This is the no-op case too**: a
#: sweep that reclaimed nothing still exits 0 and still writes a row, which is
#: what makes "a sweep stopped happening" distinguishable from "a sweep found
#: nothing to do" (AC-1's *including a no-op*).
#: ``skipped`` — the verbs did not run; ``detail`` names why.
#: ``failed`` — a step exited non-zero, or the cycle raised. Nothing is
#: swallowed: the row is written **and** the line is logged, the two-surface rule
#: :mod:`harness.hostenv.broker` follows.
SweepOutcome = Literal["completed", "skipped", "failed"]


def iso_from_ms(epoch_ms: int) -> str:
    """Epoch milliseconds as the ledger's trailing-``Z`` UTC stamp."""
    return iso_z(datetime.fromtimestamp(epoch_ms / 1000, tz=UTC))


def ms_from_iso(stamp: str) -> int:
    """The inverse of :func:`iso_from_ms` — the clock AC-4's predicate measures."""
    return int(parse_iso_z(stamp).timestamp() * 1000)


class SweepStep(BaseModel):
    """One verb a sweep ran, and what it cost.

    ``argv`` is recorded in full, which is deliberately weaker than the socket
    audit line's rule (that records the verb and nothing else, because a ticket
    title or a ``--reason`` body can reach it). Here the argv is **wholly
    host-constructed** from a resolved path — no caller, no ticket and no
    credential can reach it — so there is nothing to filter and recording it is
    what makes the record worth reading.
    """

    model_config = ConfigDict(extra="forbid")

    verb: str
    argv: list[str]
    exit_code: int
    duration_ms: int


class MaintenanceSweep(BaseModel):
    """One cycle against one repo — the row stored in ``maintenance_sweeps``.

    ``extra="forbid"`` so a writer that hallucinates a field is rejected rather
    than silently persisted, matching :class:`~harness.state.promotions.Promotion`.
    """

    model_config = ConfigDict(extra="forbid")

    repo: str
    swept_at: str
    duration_ms: int
    outcome: SweepOutcome
    steps: list[SweepStep] = []
    detail: str = ""


# ---------------------------------------------------------------------------
# Persistence — a sibling table in the run ledger's own database.
# ---------------------------------------------------------------------------

# Idempotent — ``CREATE ... IF NOT EXISTS``. Re-running is a no-op.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS maintenance_sweeps (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  swept_at   TEXT NOT NULL,
  outcome    TEXT NOT NULL,
  data_json  TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_maintenance_sweeps_swept_at
  ON maintenance_sweeps(swept_at);
"""


async def init_sweeps(db_path: Path) -> None:
    """Create the ``maintenance_sweeps`` table + index if absent. Idempotent.

    Reuses :func:`harness.state.store.connect` so the sibling table inherits the
    same WAL and foreign-key PRAGMAs as the run ledger, exactly as
    ``init_promotions`` does.
    """
    async with store.connect(db_path) as conn:
        await conn.executescript(_SCHEMA)
        await conn.commit()


async def record_sweep(sweep: MaintenanceSweep, *, db_path: Path) -> None:
    """Append one sweep, creating the table on first write."""
    await init_sweeps(db_path)
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO maintenance_sweeps (swept_at, outcome, data_json) "
            "VALUES (?, ?, ?)",
            (sweep.swept_at, sweep.outcome, sweep.model_dump_json()),
        )
        await conn.commit()


async def last_sweep(db_path: Path) -> MaintenanceSweep | None:
    """The newest recorded sweep for this repo, or ``None`` if none is recorded.

    Ordered by ``swept_at`` rather than by ``id``, because it is the clock AC-4
    measures against and a row inserted late for an earlier cycle must not read
    as the newest.

    Degrades to ``None`` — never raises — for the two legitimate "nothing
    written yet" cases, verbatim from ``read_promotion``: an absent DB file, and
    a DB initialised for runs but carrying no sweeps table. Every other read
    failure propagates. ``doctor`` calls this on repos that have never run the
    host process, and a health check that raised on a fresh repo would be worse
    than the gap it reports.
    """
    if not db_path.exists():
        return None
    try:
        async with (
            store.connect(db_path) as conn,
            conn.execute(
                "SELECT data_json FROM maintenance_sweeps "
                "ORDER BY swept_at DESC, id DESC LIMIT 1"
            ) as cur,
        ):
            row = await cur.fetchone()
    except aiosqlite.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return None
        raise
    if row is None:
        return None
    return MaintenanceSweep.model_validate_json(row[0])


# ---------------------------------------------------------------------------
# AC-4's reader — the predicate ``harness doctor`` surfaces.
# ---------------------------------------------------------------------------


def check_sweeps(db_path: Path, *, interval_ms: int, now_ms: int) -> tuple[str, str]:
    """Report this repo's sweep freshness as a ``doctor`` ``(status, message)``.

    ``WARN``, never ``FAIL``: ``doctor`` exits 1 on any FAIL, and a repo whose
    host has never run ``serve`` is not broken — the treatment ``check_db``
    already gives an absent ledger.

    Three states, three distinguishable messages, because they are three
    different facts and the remedy differs: nothing recorded means the host
    process is probably not running, an overdue record means the thread is not
    getting there, and a fresh one is the healthy case. A single constant
    warning would satisfy the boundary test while telling an operator nothing.

    ``interval_ms == 0`` is the configured off switch, not a fault. Reporting a
    deliberately disabled repo as overdue would make the escape hatch cost a
    permanent warning, which is the same as not having one.
    """
    if interval_ms == 0:
        return ("PASS", "maintenance sweeps disabled (maintenance_interval_minutes: 0)")

    sweep = asyncio.run(last_sweep(db_path))
    last_ms = None if sweep is None else ms_from_iso(sweep.swept_at)
    lag_ms = sweep_lag_ms(last_ms, now_ms)

    if lag_ms is None:
        return (
            "WARN",
            "no maintenance sweep recorded — is `harness serve` running on this host?",
        )
    if sweep_overdue(last_ms, now_ms, interval_ms=interval_ms):
        return (
            "WARN",
            f"last sweep {lag_ms // 60_000}m ago, past the "
            f"{interval_ms // 60_000}m maintenance_interval_minutes",
        )
    return ("PASS", f"last sweep {lag_ms // 60_000}m ago")


def check_repo_sweeps(repo_root: Path, db_path: Path) -> tuple[str, str]:
    """:func:`check_sweeps` for one repo — its own interval, against the wall clock.

    The seam ``harness doctor`` calls, so wiring the check costs that module an
    import and one entry in its ``checks`` list rather than a clock read and a
    budget load it would then own.
    """
    config = config_from_budget(load_loop_budget(repo_root))
    return check_sweeps(
        db_path, interval_ms=config.interval_ms, now_ms=int(time.time() * 1000)
    )
