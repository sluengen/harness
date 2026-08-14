"""When the maintenance sweep wakes, and when a missing sweep becomes visible.

Pure — two integers in, one out; no clock, no I/O, no ledger. That is the same
split :mod:`harness.hostenv.broker` already draws between its ``next_delay_ms``
and the thread that obeys it, and it is what makes AC-4's criterion *measurable*:
"sweep absence is detectable" is a statement about a duration, so the predicate
that decides it takes the duration as an argument and a test walks it across the
boundary (``code-quality`` Part C).

The schedule has **no memory of its own**. Every wake re-derives the due time of
every repo from that repo's own recorded sweeps, so the scheduler holds nothing
per repo (ADR 0012's "nothing that outlives a request describes a run"), a
restarted host does not re-sweep a repo swept five minutes ago, and a repo
created under an allowed root while ``serve`` is up is picked up without a
restart.
"""

from __future__ import annotations

from dataclasses import dataclass

from harness.loop_budget import LoopBudget

__all__ = [
    "MIN_SWEEP_INTERVAL_MS",
    "SWEEP_JOIN_SECONDS",
    "THREAD_NAME",
    "SweepConfig",
    "config_from_budget",
    "next_delay_ms",
    "sweep_lag_ms",
    "sweep_overdue",
]

#: The floor on any wake. A repo that has never been swept is due *now*, so
#: without a floor the first cycle after start — and every cycle of a
#: crash-restart loop — would fire immediately and spawn a container per repo as
#: fast as the thread can loop. One minute bounds that to one sweep per repo per
#: minute while still clearing a backlog promptly after ``serve`` starts.
MIN_SWEEP_INTERVAL_MS = 60 * 1000

#: How long :meth:`~harness.maintenance.sweep.MaintenanceScheduler.stop` waits
#: for the thread. Matches ``broker.RENEWAL_JOIN_SECONDS`` and for the same
#: reason: a thread mid-``docker run`` must never block shutdown, and the daemon
#: thread dies with the process.
SWEEP_JOIN_SECONDS = 1.0

#: The sweep thread's name, so a test — and an operator reading a traceback —
#: can identify it without matching on a target function.
THREAD_NAME = "harness-maintenance-sweeper"


@dataclass(frozen=True)
class SweepConfig:
    """One repo's sweep cadence, read from its own ``CONTEXT.md`` ``loop:`` block."""

    interval_minutes: int

    @property
    def enabled(self) -> bool:
        """Whether this repo is swept at all.

        ``0`` is the documented off switch, on ``untracked_file_limit`` /
        ``probe_max_entries``' convention: a repo that runs ``serve`` but drives
        maintenance from its own scheduler otherwise has no escape hatch short
        of not running the host process. A negative value cannot be configured
        (the loader's reader is digits-only, so it reads as absent) but is
        treated as off here rather than as a spin.
        """
        return self.interval_minutes > 0

    @property
    def interval_ms(self) -> int:
        return self.interval_minutes * 60 * 1000


def config_from_budget(budget: LoopBudget) -> SweepConfig:
    """The sweep cadence carried by an already-loaded :class:`LoopBudget`.

    The interval rides in the same ``loop:`` block as every other bound and is
    read on the same path, so the scheduler resolves one object rather than two —
    the reason ``review_model`` rides there too (#321).
    """
    return SweepConfig(interval_minutes=budget.maintenance_interval_minutes)


def next_delay_ms(due_at_ms: list[int], now_ms: int, *, interval_ms: int) -> int:
    """When to wake next, in milliseconds. Pure — the whole schedule, no clock.

    ``due_at_ms`` carries one entry per sweepable repo with sweeps enabled: its
    last recorded sweep plus one interval, or ``now_ms`` for a repo never swept.
    The earliest governs, floored at :data:`MIN_SWEEP_INTERVAL_MS`.

    An **empty** list — no repo under any allowed root, or every one of them
    disabled — falls back to ``interval_ms`` rather than stopping the thread.
    Nothing to sweep is not a reason to spin and not a reason to exit: the repo
    set is re-derived from disk on the next wake, so a repo created while
    ``serve`` is running is picked up without a restart.
    """
    if not due_at_ms:
        return interval_ms
    return max(min(due_at_ms) - now_ms, MIN_SWEEP_INTERVAL_MS)


def sweep_lag_ms(last_swept_at_ms: int | None, now_ms: int) -> int | None:
    """Milliseconds since the newest recorded sweep; ``None`` when none is recorded.

    ``None`` rather than ``0``: zero renders as "last sweep 0m ago", which reads
    as the healthiest state a host can be in and is precisely the reading a
    never-swept host must not produce.
    """
    if last_swept_at_ms is None:
        return None
    return now_ms - last_swept_at_ms


def sweep_overdue(last_swept_at_ms: int | None, now_ms: int, *, interval_ms: int) -> bool:
    """True when no sweep is recorded, or the newest is older than one interval.

    ``None`` is **overdue, not unknown**: the scheduler writes a row for every
    cycle including a no-op, so an empty table means no cycle has completed — a
    host that has been up for a day with nothing recorded is exactly the
    condition this exists to surface.

    The comparison is strict, so a sweep that fired exactly one interval ago is
    due rather than late. A non-strict bound would make every healthy host WARN
    once per interval, which trains an operator to ignore the check.
    """
    if last_swept_at_ms is None:
        return True
    return now_ms - last_swept_at_ms > interval_ms
