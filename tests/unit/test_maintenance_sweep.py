"""The maintenance sweep: which repos, which verbs, and what each cycle records (#310).

Three acceptance criteria land here, and each is written against the *same*
function the executing path calls — a guard that re-spelled the argv would be the
change agreeing with itself:

* **AC-1** — every cycle writes a row, including a no-op, including a failure,
  including a contended lock. Each test drives :meth:`MaintenanceScheduler.sweep_once`
  rather than :func:`record_sweep`: calling the writer directly proves the writer,
  not that the sweep writes.
* **AC-2** — no step a timer-driven sweep runs can remove a worktree. Derived from
  :func:`sweep_steps`, with a mandatory floor (the table is non-empty and names
  the verb it does run) because an empty table satisfies the property for every
  possible implementation.
* **AC-3** — the staleness threshold has no second copy. The sweep emits no
  ``--older-than`` at all, so the resolution stays in ``reclaim``'s one existing
  home (``loop.wall_clock_budget_minutes`` through ``load_loop_budget``).

The server is a real :class:`~harness.cli.serve.VerbServer` with only ``spawn``
overridden, so the repo lock under test is the production one and only docker is
stubbed out.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

import pytest

from harness.cli import serve
from harness.loop_budget import DEFAULT_WALL_CLOCK_BUDGET_MINUTES, load_loop_budget
from harness.maintenance.ledger import iso_from_ms, last_sweep, record_sweep
from harness.maintenance.schedule import SweepConfig, config_from_budget
from harness.maintenance.sweep import (
    MaintenanceScheduler,
    sweep_steps,
    sweepable_repos,
)
from tests._asyncutil import run_sync

_NOW_MS = 1_800_000_000_000
_INTERVAL_MS = 60 * 60 * 1000

#: Verbs that can remove a worktree directory or a branch, and the flags that
#: make a removal destructive. Named here rather than derived from the CLI
#: because the property AC-2 states is about *this* list: ``worktrees cleanup``
#: is the only verb that removes a directory, and ``--merged`` is the predicate
#: whose failure mode is deleting live work.
_REMOVING_VERBS = frozenset({"worktrees"})
_DESTRUCTIVE_FLAGS = frozenset({"--merged", "--force"})


def _managed_repo(parent: Path, name: str, *, context: str | None = None) -> Path:
    """A repo the harness manages: a real ``.git`` directory and a ``.harness``."""
    repo = parent / name
    (repo / ".git").mkdir(parents=True)
    (repo / ".harness").mkdir(parents=True)
    if context is not None:
        (repo / "CONTEXT.md").write_text(context, encoding="utf-8")
    return repo


def _db(repo: Path) -> Path:
    return repo / ".harness" / "harness.db"


class _RecordingServer(serve.VerbServer):
    """A real server — real ``_repo_locks``, real ``try_repo_lock`` — minus docker.

    Only :meth:`spawn` is replaced, so the reentrancy and contention behaviour
    under test is the production lock's rather than a stub's.
    """

    spawns: list[tuple[Path, list[str]]]
    exit_code: int = 0
    raises: BaseException | None = None

    def spawn(self, *, repo: Path, argv: list[str], fds: list[int]) -> int:
        self.spawns.append((repo, list(argv)))
        if self.raises is not None:
            raise self.raises
        return self.exit_code


@pytest.fixture
def server() -> Any:
    tmpdir = Path(tempfile.mkdtemp(prefix="hs", dir="/tmp"))
    made = _RecordingServer(
        socket_path=tmpdir / "c.sock",
        roots=[],
        image="harness:dev",
        env=dict(os.environ),
    )
    made.spawns = []
    try:
        yield made
    finally:
        made.server_close()
        shutil.rmtree(tmpdir, ignore_errors=True)


def _scheduler(server: Any, roots: list[Path], log: list[str]) -> MaintenanceScheduler:
    return MaintenanceScheduler(server=server, roots=roots, log=log.append)


# ---------------------------------------------------------------------------
# §4 — which repos get swept.
# ---------------------------------------------------------------------------


def test_a_root_that_is_itself_a_managed_repo_is_swept(tmp_path: Path) -> None:
    repo = _managed_repo(tmp_path, "repo")

    assert sweepable_repos(repo) == [repo.resolve()]


def test_the_managed_children_of_a_root_are_swept(tmp_path: Path) -> None:
    """The other real deployment shape: a root that *holds* repos."""
    first = _managed_repo(tmp_path, "alpha")
    second = _managed_repo(tmp_path, "beta")

    assert sweepable_repos(tmp_path) == sorted([first.resolve(), second.resolve()])


def test_a_git_checkout_the_harness_does_not_manage_is_not_swept(tmp_path: Path) -> None:
    """``.harness/`` is the discriminator, and it is load-bearing.

    ``store.connect`` creates its parent directory, so a sweep against an
    arbitrary checkout under a workspace root would *create* a ledger in a repo
    the operator never asked the harness to manage. Having a ledger is what
    makes a repo harness-managed, so having one is the entry condition.
    """
    _managed_repo(tmp_path, "managed")
    unmanaged = tmp_path / "unmanaged"
    (unmanaged / ".git").mkdir(parents=True)

    swept = sweepable_repos(tmp_path)

    assert unmanaged.resolve() not in swept
    assert swept == [(tmp_path / "managed").resolve()], (
        "the floor: the discriminator must still admit a managed repo, or it "
        "would exclude everything and pass this test for the wrong reason"
    )


def test_a_linked_worktree_is_not_identified_as_a_sweepable_repo(tmp_path: Path) -> None:
    """A ``.git`` **file** is a linked worktree, and sweeping a run's worktree as
    if it were a repo is the #214 defect on a timer.

    ``workspace.is_git_top_level`` accepts a ``.git`` file on purpose — verbs are
    routinely invoked with ``--repo`` pointing at a run's worktree — so it is the
    wrong discriminator here and is deliberately not reused. Built with real git
    so the fixture is the shape production produces, not one spelled to suit the
    check.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "commit", "--allow-empty", "-m", "root")
    (repo / ".harness").mkdir()
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "--detach", str(linked))
    (linked / ".harness").mkdir()

    assert (linked / ".git").is_file(), "fixture floor: this must be a linked worktree"
    assert sweepable_repos(tmp_path) == [repo.resolve()]
    assert sweepable_repos(linked) == []


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )


def test_a_root_holding_no_managed_repo_yields_nothing(tmp_path: Path) -> None:
    (tmp_path / "notes").mkdir()

    assert sweepable_repos(tmp_path) == []


def test_the_scan_is_one_level_deep_never_recursive(tmp_path: Path) -> None:
    """A walk would reach ``.worktrees/`` and every vendored submodule. A root
    that holds repos, and a root that is one, are the two real shapes; anything
    deeper is a configuration the operator expresses by naming the root."""
    nested = _managed_repo(tmp_path / "a" / "b", "deep")

    assert nested.resolve() not in sweepable_repos(tmp_path)


# ---------------------------------------------------------------------------
# AC-2 / AC-3 — the step table.
# ---------------------------------------------------------------------------


def test_no_step_the_timer_runs_can_remove_a_worktree(tmp_path: Path) -> None:
    """AC-2, derived from the table the executing path itself reads.

    ``reclaim --stale`` *preserves* the worktree and the branch by recorded
    design (D4), and its false positive is reversible by ``reclaim --undo``. No
    step names a verb that removes a directory, and no step carries a flag whose
    failure mode is deleting live work.
    """
    repo = _managed_repo(tmp_path, "repo")

    for verb, argv in sweep_steps(repo):
        assert argv[0] not in _REMOVING_VERBS, (
            f"the timer runs {verb!r}, which can remove a worktree directory"
        )
        assert not (_DESTRUCTIVE_FLAGS & set(argv)), (
            f"the timer runs {verb!r} with a destructive flag: {argv}"
        )


def test_the_step_table_is_non_empty_and_names_the_verb_it_runs(tmp_path: Path) -> None:
    """The mandatory non-vacuity floor for AC-2 and AC-3.

    A ``sweep_steps`` returning ``[]`` — or one emitting no flags at all —
    satisfies both properties above for every possible implementation, and would
    also mean the timer does nothing while every guard stays green.
    """
    repo = _managed_repo(tmp_path, "repo")

    steps = sweep_steps(repo)

    assert steps, "the timer must run at least one verb"
    assert {argv[0] for _verb, argv in steps} == {"reclaim"}
    assert any("--stale" in argv for _verb, argv in steps), (
        "the reclaim step must be the stale sweep, not some other reclaim mode"
    )


def test_every_step_states_the_repo_it_targets(tmp_path: Path) -> None:
    """ADR 0012: a verb's target repo is stated, never inferred from a cwd."""
    repo = _managed_repo(tmp_path, "repo")

    for _verb, argv in sweep_steps(repo):
        assert argv[argv.index("--repo") + 1] == str(repo)


def test_the_sweep_delegates_the_staleness_threshold_rather_than_forwarding_it(
    tmp_path: Path,
) -> None:
    """AC-3: the sweep never names the threshold, so there is no second copy.

    ``reclaim`` already single-sources it — an omitted ``--older-than`` resolves
    ``loop.wall_clock_budget_minutes`` through ``load_loop_budget``. Any
    implementation that read and forwarded the value would falsify this, which
    is precisely what "a second copy" means.
    """
    repo = _managed_repo(tmp_path, "repo")

    for _verb, argv in sweep_steps(repo):
        assert "--older-than" not in argv
        assert str(DEFAULT_WALL_CLOCK_BUDGET_MINUTES) not in " ".join(argv)


def test_a_repo_with_its_own_budget_still_yields_no_threshold_token(
    tmp_path: Path,
) -> None:
    """The absence is structural, not an accident of ``110`` not appearing.

    A repo configuring an unusual budget would still be forwarded by any
    implementation that read the value, so this is the case that separates
    "delegates" from "happens not to have matched the default".
    """
    repo = _managed_repo(
        tmp_path, "repo", context="```yaml\nloop:\n  wall_clock_budget_minutes: 7\n```\n"
    )
    assert load_loop_budget(repo).wall_clock_budget_minutes == 7, "fixture floor"

    rendered = " ".join(token for _verb, argv in sweep_steps(repo) for token in argv)

    assert "7m" not in rendered
    assert "--older-than" not in rendered


# ---------------------------------------------------------------------------
# AC-1 — every cycle records its outcome.
# ---------------------------------------------------------------------------


def test_a_sweep_that_changes_nothing_still_writes_a_record(
    tmp_path: Path, server: Any
) -> None:
    """AC-1's hard half: a writer that only recorded when something changed
    passes every other test here, and leaves a no-op indistinguishable from a
    sweep that never fired — which is the whole point of the ticket."""
    repo = _managed_repo(tmp_path, "repo")
    log: list[str] = []

    swept = _scheduler(server, [tmp_path], log).sweep_once(now_ms=_NOW_MS)

    assert [s.outcome for s in swept] == ["completed"]
    recorded = run_sync(last_sweep(_db(repo)))
    assert recorded is not None
    assert recorded.outcome == "completed"
    assert [step.exit_code for step in recorded.steps] == [0]
    assert len(server.spawns) == 1


def test_a_failing_step_is_recorded_and_not_swallowed(
    tmp_path: Path, server: Any
) -> None:
    """Both surfaces — the durable row and the log line — as the credential
    broker does for its own failures."""
    repo = _managed_repo(tmp_path, "repo")
    server.exit_code = 3
    log: list[str] = []

    _scheduler(server, [tmp_path], log).sweep_once(now_ms=_NOW_MS)

    recorded = run_sync(last_sweep(_db(repo)))
    assert recorded is not None
    assert recorded.outcome == "failed"
    assert [step.exit_code for step in recorded.steps] == [3]
    assert any("failed" in line for line in log), f"the failure was silent: {log}"


def test_a_raising_cycle_records_failed_and_the_sweep_survives_it(
    tmp_path: Path, server: Any
) -> None:
    """One bad repo must not kill the thread or the other repos' sweeps."""
    first = _managed_repo(tmp_path, "alpha")
    second = _managed_repo(tmp_path, "beta")
    server.raises = OSError("docker is not running")
    log: list[str] = []

    swept = _scheduler(server, [tmp_path], log).sweep_once(now_ms=_NOW_MS)

    assert {s.outcome for s in swept} == {"failed"}
    for repo in (first, second):
        recorded = run_sync(last_sweep(_db(repo)))
        assert recorded is not None
        assert recorded.outcome == "failed"
        assert "OSError" in recorded.detail
    assert len(server.spawns) == 2, "the second repo was swept despite the first raising"


def test_a_sweep_does_not_run_while_a_verb_holds_the_repo_lock(
    tmp_path: Path, server: Any
) -> None:
    """Contention is recorded, never waited out: one thread serves every repo, so
    blocking on a twelve-minute ``review`` would delay every other repo."""
    repo = _managed_repo(tmp_path, "repo")
    log: list[str] = []
    held = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with server.try_repo_lock(repo.resolve()) as acquired:
            assert acquired
            held.set()
            release.wait(10)

    thread = threading.Thread(target=holder, daemon=True)
    thread.start()
    held.wait(10)
    try:
        _scheduler(server, [tmp_path], log).sweep_once(now_ms=_NOW_MS)
    finally:
        release.set()
        thread.join(10)

    assert server.spawns == [], "a sweep ran on top of a live verb"
    recorded = run_sync(last_sweep(_db(repo)))
    assert recorded is not None
    assert (recorded.outcome, recorded.detail) == ("skipped", "lock_contended")
    assert any("lock_contended" in line for line in log)


def test_a_sweep_runs_when_the_lock_is_free(tmp_path: Path, server: Any) -> None:
    """The non-vacuity mirror of the test above: without it, a scheduler that
    never spawned anything would satisfy the contention assertion."""
    _managed_repo(tmp_path, "repo")
    log: list[str] = []

    _scheduler(server, [tmp_path], log).sweep_once(now_ms=_NOW_MS)

    assert len(server.spawns) == 1


# ---------------------------------------------------------------------------
# The schedule, driven from the record rather than from memory.
# ---------------------------------------------------------------------------


def test_a_repo_swept_inside_its_interval_is_not_swept_again(
    tmp_path: Path, server: Any
) -> None:
    """The record is the schedule's only memory, so a restarted host does not
    re-sweep a repo swept five minutes ago."""
    _managed_repo(tmp_path, "repo")
    scheduler = _scheduler(server, [tmp_path], [])
    scheduler.sweep_once(now_ms=_NOW_MS)

    swept = scheduler.sweep_once(now_ms=_NOW_MS + _INTERVAL_MS - 1)

    assert swept == []
    assert len(server.spawns) == 1


def test_a_repo_past_its_interval_is_swept_again(tmp_path: Path, server: Any) -> None:
    _managed_repo(tmp_path, "repo")
    scheduler = _scheduler(server, [tmp_path], [])
    scheduler.sweep_once(now_ms=_NOW_MS)

    scheduler.sweep_once(now_ms=_NOW_MS + _INTERVAL_MS + 1)

    assert len(server.spawns) == 2


def test_a_repo_with_sweeps_disabled_is_never_swept(tmp_path: Path, server: Any) -> None:
    """``maintenance_interval_minutes: 0`` disables sweeps for that repo, on
    ``untracked_file_limit`` / ``probe_max_entries``' convention."""
    repo = _managed_repo(
        tmp_path, "repo", context="```yaml\nloop:\n  maintenance_interval_minutes: 0\n```\n"
    )
    assert config_from_budget(load_loop_budget(repo)) == SweepConfig(0), "fixture floor"

    swept = _scheduler(server, [tmp_path], []).sweep_once(now_ms=_NOW_MS)

    assert swept == []
    assert server.spawns == []
    assert run_sync(last_sweep(_db(repo))) is None, (
        "a disabled repo must not accumulate rows either — the record is what "
        "`doctor` reads, and a disabled repo has nothing to report"
    )


def test_two_roots_naming_the_same_repo_sweep_it_once(
    tmp_path: Path, server: Any
) -> None:
    """``allowed_roots`` resolves but does not dedupe, so overlapping roots would
    otherwise sweep — and record — the same repo twice per cycle."""
    repo = _managed_repo(tmp_path, "repo")

    swept = _scheduler(server, [tmp_path, repo], []).sweep_once(now_ms=_NOW_MS)

    assert len(swept) == 1
    assert len(server.spawns) == 1


def test_the_argv_reaching_the_container_names_the_mount_not_the_host_path(
    tmp_path: Path, server: Any
) -> None:
    """The same ``rewrite_repo_argument`` the socket handler calls, not a copy —
    a host path handed to a verb inside the container resolves outside its pinned
    allowlist and is refused."""
    _managed_repo(tmp_path, "repo")

    _scheduler(server, [tmp_path], []).sweep_once(now_ms=_NOW_MS)

    _repo, argv = server.spawns[0]
    assert argv[argv.index("--repo") + 1] == "/workspace"


# ---------------------------------------------------------------------------
# ADR 0012 — the scheduler holds no run-describing state.
# ---------------------------------------------------------------------------


def test_the_scheduler_holds_no_state_across_a_cycle(
    tmp_path: Path, server: Any
) -> None:
    """The schedule is re-derived from disk every wake. A ``{repo -> last swept}``
    cache would be the first thing here that describes work rather than
    configuration, and it buys nothing a four-row SQLite read does not."""
    _managed_repo(tmp_path, "repo")
    scheduler = _scheduler(server, [tmp_path], [])
    before = {name: repr(value) for name, value in vars(scheduler).items()}

    scheduler.sweep_once(now_ms=_NOW_MS)

    assert {name: repr(value) for name, value in vars(scheduler).items()} == before


def test_the_state_assertion_would_catch_a_planted_cache(
    tmp_path: Path, server: Any
) -> None:
    """Non-vacuity floor: the check must fail on state that *is* there."""
    scheduler = _scheduler(server, [tmp_path], [])
    scheduler._planted = {"/repo": _NOW_MS}  # type: ignore[attr-defined]

    assert "_planted" in repr(vars(scheduler))


# ---------------------------------------------------------------------------
# The thread.
# ---------------------------------------------------------------------------


def test_the_loop_sleeps_before_it_works_and_stops_on_request(
    tmp_path: Path, server: Any
) -> None:
    """Sleep first, so starting ``serve`` does not put a ``docker run`` per repo
    in front of the socket bind; and a stop request returns the thread from a
    one-hour sleep immediately."""
    _managed_repo(tmp_path, "repo")
    delays: list[float] = []
    finished = threading.Event()

    def sleeper(seconds: float) -> bool:
        delays.append(seconds)
        if len(delays) > 1:
            finished.set()
            return True
        return False

    scheduler = MaintenanceScheduler(
        server=server, roots=[tmp_path], log=lambda _line: None, sleeper=sleeper
    )

    scheduler.start()
    assert finished.wait(10), "the sweep thread never reached its second wake"
    scheduler.stop()

    assert len(delays) == 2
    assert len(server.spawns) == 1, (
        "the loop must sleep before it works — exactly one cycle ran between the "
        "two wakes"
    )


def test_start_is_idempotent_and_stop_is_safe_twice(tmp_path: Path, server: Any) -> None:
    """``serve`` calls ``stop`` from a ``finally`` that also runs on the path
    where the thread was never started."""
    scheduler = MaintenanceScheduler(
        server=server, roots=[tmp_path], log=lambda _line: None, sleeper=lambda _s: True
    )

    scheduler.stop()
    scheduler.start()
    scheduler.start()
    scheduler.stop()
    scheduler.stop()


def test_a_never_swept_repo_is_due_now(tmp_path: Path, server: Any) -> None:
    """The first wake is derived from the ledger rather than from a synchronous
    prime: a repo with no recorded sweep is due immediately (floored), which is
    what clears an accumulated backlog shortly after ``serve`` starts."""
    repo = _managed_repo(tmp_path, "repo")
    scheduler = _scheduler(server, [tmp_path], [])

    assert scheduler.next_delay_ms(now_ms=_NOW_MS) == 60 * 1000

    run_sync(
        record_sweep(
            _completed(repo, _NOW_MS), db_path=_db(repo)
        )
    )
    assert scheduler.next_delay_ms(now_ms=_NOW_MS) == _INTERVAL_MS


def _completed(repo: Path, at_ms: int) -> Any:
    from harness.maintenance.ledger import MaintenanceSweep

    return MaintenanceSweep(
        repo=str(repo), swept_at=iso_from_ms(at_ms), duration_ms=1, outcome="completed"
    )
