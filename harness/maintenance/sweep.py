"""The maintenance sweep: which repos, which verbs, and the thread that fires them.

ADR 0012's third host role. It names the host process *"a credential broker, a
spawner, and a scheduler"* and lists periodic maintenance in the decision
sentence itself; #307 shipped the spawner and #309 the broker. This is the
scheduler.

**The host decides *when*, never *what*.** Each step is a one-shot container
spawned through :meth:`~harness.cli.serve.VerbServer.spawn`, which is the second
half of ADR 0012's decision — *"Every verb remains a one-shot container"* — and
not decoration: calling ``reclaim`` in-process would run tracker network calls
and ledger mutations inside the long-lived host, where a bug cannot be bounded
by a container exit. Going through ``VerbServer.spawn`` rather than building a
second ``docker run`` is the same rule the client fallback follows: two
constructions would be two security postures.

So the scheduler never reads ``runs``, never reads ``events``, never resolves a
ticket and never holds a ``run_id``. Which run is stale, which is attended and
which is closable are decided *inside* the container by ``reclaim``, against the
ledger, exactly as when a human runs the verb.

**Nothing per repo and nothing per cycle survives a cycle.** The schedule is
re-derived from each repo's own recorded sweeps on every wake rather than
cached — a ``{repo -> last swept}`` dict would be the first thing here that
describes work rather than configuration, and it buys nothing a four-row SQLite
read does not already give.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from harness.hostenv import spawn as spawn_module
from harness.loop_budget import DEFAULT_MAINTENANCE_INTERVAL_MINUTES, load_loop_budget
from harness.maintenance import schedule
from harness.maintenance.ledger import (
    MaintenanceSweep,
    SweepOutcome,
    SweepStep,
    iso_from_ms,
    last_sweep,
    ms_from_iso,
    record_sweep,
)
from harness.maintenance.schedule import THREAD_NAME, config_from_budget

__all__ = ["MaintenanceScheduler", "VerbSpawner", "sweep_steps", "sweepable_repos"]


class VerbSpawner(Protocol):
    """The narrow seam the sweep needs from the host process.

    Structural rather than a :class:`~harness.cli.serve.VerbServer` annotation,
    and the layering guard is what makes that the only option: nothing under
    ``harness/`` outside ``harness/cli/`` may import from ``harness.cli``
    (#269), which is a rule about the import graph rather than about types — a
    ``TYPE_CHECKING`` import is the same edge and the guard reads the AST.

    It is the better contract anyway. The sweep depends on *spawning a verb
    against a repo, under that repo's lock*, not on a socket server; naming
    exactly that says which two methods a future host must provide, and no more.
    """

    def try_repo_lock(self, repo: Path) -> AbstractContextManager[bool]:
        """Take ``repo``'s lock if free; the context yields whether it was."""
        ...  # pragma: no cover — Protocol body

    def spawn(self, *, repo: Path, argv: list[str], fds: list[int]) -> int:
        """Run one verb as a one-shot container and return its exit code."""
        ...  # pragma: no cover — Protocol body

#: The fallback wake when no repo is due — no sweepable repo under any root, or
#: every one of them disabled. The thread keeps waking so a repo created under
#: an allowed root while ``serve`` is up is picked up without a restart.
_IDLE_INTERVAL_MS = DEFAULT_MAINTENANCE_INTERVAL_MINUTES * 60 * 1000


def _is_managed_repo(path: Path) -> bool:
    """Whether the timer may sweep ``path``: a git top level the harness manages.

    Two conditions, each closing a distinct hazard.

    ``.git`` must be a **directory**. ``workspace.is_git_top_level`` accepts a
    ``.git`` *file* on purpose — that is a linked worktree, and the verbs are
    routinely invoked with ``--repo`` pointing at a run's worktree — so it is the
    wrong discriminator here and is deliberately not reused. Sweeping a run's
    worktree as if it were a repo is the #214 defect, driven by a timer.

    ``.harness`` must exist. ``store.connect`` creates its parent, so sweeping
    every checkout under a workspace root would *create* a ledger in repos the
    operator never asked the harness to manage. Having a ledger is what makes a
    repo harness-managed, so having one is the entry condition.
    """
    return (path / ".git").is_dir() and (path / ".harness").is_dir()


def sweepable_repos(root: Path) -> list[Path]:
    """The managed repos under one allowed root — the root itself, or its children.

    One level deep, never a walk: a recursive descent reaches ``.worktrees/`` and
    every vendored submodule. Two shapes cover the real deployments — a root that
    *is* a repo, and a root that *holds* repos — and anything deeper is a
    configuration the operator expresses by naming the root directly.

    Every path is resolved, so the caller can dedupe overlapping roots by
    identity.
    """
    resolved = Path(root).resolve()
    if _is_managed_repo(resolved):
        return [resolved]
    try:
        children = sorted(resolved.iterdir())
    except OSError:
        return []
    return [child.resolve() for child in children if _is_managed_repo(child)]


def sweep_steps(repo: Path) -> list[tuple[str, list[str]]]:
    """The verbs a timer-driven sweep runs against one repo, in order.

    **The single home for what the timer does.** Both the executing path and the
    AC-2 / AC-3 guards derive from this one function; a guard that re-spelled the
    argv would be asserting about a list the scheduler does not run.

    Only ``reclaim --stale``, and that is the whole of it (#310's decision). It
    is designed for exactly this — its own docstring says the Build routine runs
    it every tick as a pre-flight — it is hardened by three independent clocks
    that must *all* be stale, its false positive is reversible by
    ``reclaim --undo``, and it **preserves** the worktree and the branch. That is
    the only profile a timer may drive: a sweep must not carry a predicate whose
    failure mode is deleting live work, so no worktree-removing verb appears
    here, and reclaiming the accumulated *directories* is filed separately
    because it carries a decision only the operator can make.

    No ``--older-than``: the threshold stays single-sourced where it already is.
    ``reclaim`` resolves ``loop.wall_clock_budget_minutes`` through
    ``load_loop_budget`` when the flag is omitted, and forwarding the value would
    be the second copy AC-3 forbids.

    ``--repo`` is stated rather than inferred from a cwd, per ADR 0012.
    """
    return [("reclaim --stale", ["reclaim", "--stale", "--repo", str(repo)])]


def _now_ms() -> int:
    return int(time.time() * 1000)


class MaintenanceScheduler:
    """Sweeps every managed repo under the host's allowed roots, on a timer.

    Shaped on :class:`~harness.hostenv.broker.CredentialBroker`: a daemon thread,
    an injected sleeper as the test seam, an idempotent :meth:`start` and a
    :meth:`stop` that never blocks shutdown.

    **One deviation from the broker, stated.** The broker primes *synchronously
    before the socket serves*, because no request may observe an unknown
    credential state. This must not: priming would put a ``docker run`` per repo
    in front of the socket bind, and no request depends on a sweep having
    happened. The first wake is derived from the ledger instead — a repo with a
    recorded sweep is due one interval after it, a repo never swept is due now,
    floored — so a fresh host sweeps shortly after start (which is what clears an
    accumulated backlog), a restarted host does not re-sweep a repo swept five
    minutes ago, and a crash-restart loop is bounded to one sweep per repo per
    minute.
    """

    def __init__(
        self,
        *,
        server: VerbSpawner,
        roots: list[Path],
        log: Callable[[str], None],
        sleeper: Callable[[float], bool] | None = None,
    ) -> None:
        self._server = server
        self._roots = list(roots)
        self._log = log
        self._stopping = threading.Event()
        #: ``(seconds) -> stop requested``. The injection point that makes the
        #: thread testable with no sleeping anywhere; the default is the stop
        #: event's own wait, which is what lets :meth:`stop` return the thread
        #: from an hour-long sleep immediately.
        self._sleeper = sleeper if sleeper is not None else self._stopping.wait
        self._thread: threading.Thread | None = None

    # -- the repo set and the schedule ---------------------------------------

    def repos(self) -> list[Path]:
        """Every managed repo under every allowed root, deduplicated.

        ``allowed_roots`` resolves but does not dedupe, so two roots may name
        overlapping trees; without this a repo under both would be swept — and
        recorded — twice per cycle.
        """
        seen: dict[str, Path] = {}
        for root in self._roots:
            for repo in sweepable_repos(root):
                seen.setdefault(str(repo), repo)
        return list(seen.values())

    def next_delay_ms(self, *, now_ms: int) -> int:
        """When the thread should next wake, derived from the ledger."""
        due = [due_at for _repo, due_at, _config in self._plan(now_ms)]
        return schedule.next_delay_ms(due, now_ms, interval_ms=_IDLE_INTERVAL_MS)

    def _plan(self, now_ms: int) -> list[tuple[Path, int, schedule.SweepConfig]]:
        """``(repo, due_at_ms, config)`` for every repo with sweeps enabled."""
        plan = []
        for repo in self.repos():
            config = config_from_budget(load_loop_budget(repo))
            if not config.enabled:
                continue
            last_ms = self._last_swept_ms(repo)
            due_at = now_ms if last_ms is None else last_ms + config.interval_ms
            plan.append((repo, due_at, config))
        return plan

    def _last_swept_ms(self, repo: Path) -> int | None:
        sweep = asyncio.run(last_sweep(_db_path(repo)))
        return None if sweep is None else ms_from_iso(sweep.swept_at)

    # -- one cycle ------------------------------------------------------------

    def sweep_once(self, *, now_ms: int | None = None) -> list[MaintenanceSweep]:
        """Sweep every due repo once, recording each outcome. Returns what ran."""
        now = _now_ms() if now_ms is None else now_ms
        swept: list[MaintenanceSweep] = []
        for repo, due_at, _config in self._plan(now):
            if due_at > now:
                continue
            sweep = self._cycle(repo, now)
            self._commit(repo, sweep)
            swept.append(sweep)
        return swept

    def _cycle(self, repo: Path, now_ms: int) -> MaintenanceSweep:
        """Run one repo's steps and describe what happened. Never raises.

        Three non-happy outcomes, and each is a **recorded row plus a log line**
        rather than a silence: a contended lock (``skipped``), a step that exited
        non-zero (``failed``), and a cycle that raised (``failed``, carrying the
        exception type). The loop must outlive one bad repo, and an error the
        operator cannot see is the failure this record exists to prevent.
        """
        started = time.monotonic()
        steps: list[SweepStep] = []

        def done(outcome: SweepOutcome, detail: str) -> MaintenanceSweep:
            return MaintenanceSweep(
                repo=str(repo),
                swept_at=iso_from_ms(now_ms),
                duration_ms=int((time.monotonic() - started) * 1000),
                outcome=outcome,
                steps=steps,
                detail=detail,
            )

        try:
            with self._server.try_repo_lock(repo) as acquired:
                if not acquired:
                    # Non-blocking on purpose: one thread serves every repo, so
                    # waiting out a twelve-minute `review` in repo A would make
                    # repo B late. Real work always wins, and the lateness is a
                    # row rather than a silence. The next wake retries.
                    return done("skipped", "lock_contended")
                for verb, argv in sweep_steps(repo):
                    step = self._run_step(repo, verb, argv)
                    steps.append(step)
                    if step.exit_code != 0:
                        return done("failed", f"{verb} exited {step.exit_code}")
        except Exception as exc:  # noqa: BLE001 — one bad repo must not stop the rest
            return done("failed", f"the sweep cycle raised {type(exc).__name__}: {exc}")
        # Reached with every step at 0 — including the no-op case, where nothing
        # was stale and nothing was reclaimed. Recording it is what makes "the
        # sweep found nothing" distinguishable from "the sweep stopped running".
        return done("completed", "")

    def _run_step(self, repo: Path, verb: str, argv: list[str]) -> SweepStep:
        """Spawn one verb container and record what it cost.

        The argv goes through the same ``rewrite_repo_argument`` the socket
        handler calls, not a copy: a *host* path handed to a verb running in the
        container resolves outside its pinned allowlist and is refused.
        """
        started = time.monotonic()
        container_argv = spawn_module.rewrite_repo_argument(argv, repo)
        exit_code = self._server.spawn(repo=repo, argv=container_argv, fds=[])
        return SweepStep(
            verb=verb,
            argv=container_argv,
            exit_code=exit_code,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def _commit(self, repo: Path, sweep: MaintenanceSweep) -> None:
        asyncio.run(record_sweep(sweep, db_path=_db_path(repo)))
        self._log(
            f"{sweep.swept_at} sweep repo={repo} outcome={sweep.outcome} "
            f"steps={len(sweep.steps)} {sweep.detail}".rstrip()
        )

    # -- the thread -----------------------------------------------------------

    def start(self) -> None:
        """Launch the sweep loop on a daemon thread. Idempotent."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name=THREAD_NAME, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Ask the thread to finish and wait briefly. Never blocks shutdown.

        Safe on a scheduler that was never started, and safe to call twice —
        ``serve`` calls it from a ``finally``.
        """
        self._stopping.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(schedule.SWEEP_JOIN_SECONDS)

    def _loop(self) -> None:
        """Sleep on the derived schedule, then sweep, until asked to stop.

        Sleep *first*: nothing has been primed, and firing a container per repo
        the instant ``serve`` starts would put the sweep in front of the work the
        operator started the host for.
        """
        while True:
            try:
                delay_ms = self.next_delay_ms(now_ms=_now_ms())
            except Exception as exc:  # noqa: BLE001 — an unreadable ledger is not fatal
                self._log(
                    f"harness serve: could not derive the sweep schedule "
                    f"({type(exc).__name__}: {exc}); retrying in one interval"
                )
                delay_ms = _IDLE_INTERVAL_MS
            if self._sleeper(delay_ms / 1000):
                return
            try:
                self.sweep_once()
            except Exception as exc:  # noqa: BLE001 — the loop outlives one bad cycle
                self._log(
                    f"harness serve: the maintenance sweep raised "
                    f"{type(exc).__name__}: {exc}"
                )


def _db_path(repo: Path) -> Path:
    return repo / ".harness" / "harness.db"
