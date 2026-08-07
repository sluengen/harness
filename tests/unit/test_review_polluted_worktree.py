"""``review`` refuses a polluted run worktree before spawning the engine — #359.

The measurement is pinned in ``tests/unit/test_worktree_pollution.py``; this
module pins what the **verb** does with it. Built on
``test_review_verify_gate.py``'s fixtures, whose run row records the repo
directory as its ``worktree_path`` — so seeding pollution is writing files into
that repo.

The properties that matter to a caller, and why each is worth a test:

* the engine is never spawned (the whole point — the failure being prevented is
  a 720-second burn that reviews nothing);
* the refusal is machine-readable and **distinct from ``engine_timeout``**, which
  is what stops the cure being mistaken for the disease it treats (AC-1);
* the message carries the counts, the offenders and the remedy (AC-2);
* it costs no review cycle and does not park the ticket In Review (AC-5) — a
  refusal that spent budget would make cleaning up more expensive than the burn;
* a legitimately untracked-but-small worktree is **not** refused (AC-4), which is
  the assertion that fails first if the bound is ever tightened to where ordinary
  work trips it.
"""

from __future__ import annotations

import json
import subprocess
import unittest.mock as mock
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli import review as review_mod
from harness.cli.review_pollution import ROOT_SEGMENT, measure_worktree_pollution
from harness.loop_budget import DEFAULT_UNTRACKED_FILE_LIMIT
from harness.state import store
from tests._asyncutil import run_sync
from tests._ledger import seed_design_event

cli_runner = CliRunner()

_PASS_LINE = 'SUBMIT: {"verdict": "pass", "issues": []}\n'
_RUN_ID = "01JRUNPOLLUTEDXXXXXXXXXXX01"

#: Small enough to seed quickly, large enough that the positive control below
#: (a design file, five ``__pycache__`` directories, an uncommitted edit) sits
#: comfortably under it — which is the relationship the real 1000 has to the
#: ~390 a suite run in the worktree leaves behind.
_LIMIT = 50


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


@pytest.fixture(autouse=True)
def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "dev")
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    (repo_root / "README.md").write_text("hello\n")
    _git(repo_root, "add", "README.md")
    _git(repo_root, "commit", "-m", "initial")
    return repo_root


@pytest.fixture
def db_path(repo: Path) -> Path:
    return repo / ".harness" / "harness.db"


def _write_context(repo: Path, *, limit: int | None = _LIMIT) -> None:
    """A CONTEXT.md configuring the verify gate and (optionally) the bound."""
    body = "```yaml\nrepo:\n  name: t\nverify: \"true\"\nloop:\n"
    if limit is not None:
        body += f"  untracked_file_limit: {limit}\n"
    body += "```\n"
    (repo / "CONTEXT.md").write_text(body)
    _git(repo, "add", "CONTEXT.md")
    _git(repo, "commit", "-m", "context")


def _seed_run(db_path: Path, repo: Path) -> str:
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
                    _RUN_ID,
                    "",
                    0,
                    "open",
                    "{}",
                    "{}",
                    "dev",
                    str(repo),
                    f"harness/{_RUN_ID}",
                    "359",
                    datetime.now(UTC).isoformat(),
                    1234,
                ),
            )
            await conn.commit()

    run_sync(_insert())
    seed_design_event(db_path, _RUN_ID)
    return _RUN_ID


def _tracking_runner(calls: list[int]) -> Any:
    async def _runner(
        *,
        cmd: list[str],
        stdin: str,
        env: dict[str, str],
        cwd: Path | None,
        timeout: float | None = None,
    ) -> review_mod.RunResult:
        calls.append(1)
        return review_mod.RunResult(stdout=_PASS_LINE, stderr="", returncode=0)

    return _runner


def _invoke(repo: Path, db_path: Path, calls: list[int], gate_exit: str = "0") -> Any:
    """Drive the verb with the engine stubbed at ``review``'s own runner seam.

    Patching :data:`review_mod._default_runner` — rather than passing a runner in
    — is what ``test_review_verify_gate`` does, and it is load-bearing: without
    it the verb spawns a real ``claude -p`` and the test hangs instead of failing.
    """
    log = _gate_log(repo, ok=gate_exit == "0")
    with mock.patch.object(review_mod, "_default_runner", _tracking_runner(calls)):
        return cli_runner.invoke(
            app,
            [
                "review",
                "--run-id", _RUN_ID,
                "--repo", str(repo),
                "--db", str(db_path),
                "--gate-exit", gate_exit,
                "--gate-log", str(log),
                "--json",
            ],
        )


def _gate_log(repo: Path, *, ok: bool = True) -> Path:
    """The gate-evidence log. Written eagerly so it is inside any baseline below."""
    log = repo / "gate.log"
    log.write_text("ok\n" if ok else "boom\n")
    return log


def _pollute_to_excess(repo: Path, segment: str, target: int) -> None:
    """Seed ``segment`` until the worktree's excess is exactly ``target``.

    Derived from the production measurement rather than from a literal count,
    because the fixture repo is not itself at zero excess — it carries the
    ledger and the gate log, and a run worktree in production likewise carries
    whatever the session has left in it. Counting up from a *measured* baseline
    is what lets the boundary cases below sit exactly on the bound instead of
    near it, which is the difference between measuring a bound and straddling it.
    """
    _gate_log(repo)
    baseline = measure_worktree_pollution(repo, limit=10**9)
    assert baseline is not None, "the fixture worktree must be measurable"
    needed = target - baseline.excess
    assert needed >= 0, (
        f"the fixture already carries {baseline.excess} excess, more than the "
        f"{target} this case wants to seed to"
    )
    directory = repo / segment
    directory.mkdir(parents=True, exist_ok=True)
    for i in range(needed):
        (directory / f"f{i}.bin").write_text("x")


def _review_events(db_path: Path) -> list[dict[str, Any]]:
    async def _read() -> list[dict[str, Any]]:
        async with store.connect(db_path) as conn:
            cur = await conn.execute(
                "SELECT data_json FROM events WHERE event_type = 'review' "
                "AND run_id = ? ORDER BY id",
                (_RUN_ID,),
            )
            return [json.loads(row[0]) for row in await cur.fetchall()]

    return run_sync(_read())


# --- AC-1: refuse before the engine, machine-readably --------------------------


def test_a_polluted_worktree_refuses_before_the_engine(
    repo: Path, db_path: Path
) -> None:
    """The load-bearing case: exit 5, ``polluted_worktree``, and no engine."""
    _write_context(repo)
    _seed_run(db_path, repo)
    _pollute_to_excess(repo, ".venv", _LIMIT + 1)
    calls: list[int] = []

    result = _invoke(repo, db_path, calls)

    assert result.exit_code == 5, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == "polluted_worktree"
    assert calls == [], "the engine must not be spawned"


def test_the_reason_is_distinct_from_the_timeout_it_prevents(
    repo: Path, db_path: Path
) -> None:
    """AC-1's ``distinct from engine_timeout``, asserted on both discriminators.

    The guard exists because a polluted tree *presents* as ``engine_timeout``. If
    the cure carried the disease's tag — or its exit code — an operator reading
    the ledger could not tell "the engine hung" from "we refused to let it".
    """
    _write_context(repo)
    _seed_run(db_path, repo)
    _pollute_to_excess(repo, ".venv", _LIMIT + 1)

    result = _invoke(repo, db_path, [])
    payload = json.loads(result.output)

    assert payload["reason"] != review_mod.ENGINE_TIMEOUT_REASON
    assert result.exit_code != review_mod.EXIT_INFRA_FAILURE
    assert result.exit_code == review_mod.EXIT_GATE_FAILED


# --- AC-2: the refusal states the counts, the offenders and the remedy ---------


def test_the_refusal_names_the_counts_offenders_and_remedy(
    repo: Path, db_path: Path
) -> None:
    """The operator must re-derive nothing."""
    _write_context(repo)
    _seed_run(db_path, repo)
    _pollute_to_excess(repo, ".venv", _LIMIT + 20)

    result = _invoke(repo, db_path, [])
    payload = json.loads(result.output)
    message = payload["error"]

    measured = payload["worktree_pollution"]

    # The counts, as numbers rather than an adjective.
    assert str(measured["excess"]) in message.replace(",", "")
    assert "limit" in message

    # The largest offender, named *with its size* — the binding matters. A bare
    # ``".venv" in message`` passes against a refusal that names no offender at
    # all, because the remedy sentence below already says "most often a
    # verify-gate `.venv`". Asserting the rendered clause is what makes this
    # measure the offenders list rather than boilerplate the mutation never
    # touches (the mutation harness caught exactly that).
    largest = measured["largest"][0]
    assert largest["segment"] == ".venv"
    assert f"`{largest['segment']}` ({largest['files']:,} files)" in message

    # The remedy, and the bound's own address.
    assert "UV_PROJECT_ENVIRONMENT" in message
    assert "untracked_file_limit" in message


def test_the_structured_payload_carries_the_measurement(
    repo: Path, db_path: Path
) -> None:
    """The same facts machine-readably, so a caller need not parse the prose."""
    _write_context(repo)
    _seed_run(db_path, repo)
    _pollute_to_excess(repo, ".venv", _LIMIT + 3)

    payload = json.loads(_invoke(repo, db_path, []).output)
    measured = payload["worktree_pollution"]

    assert measured["excess"] == _LIMIT + 3
    assert measured["limit"] == _LIMIT
    assert measured["largest"][0]["segment"] == ".venv"
    assert measured["truncated"] is False


def test_a_root_level_filename_is_never_named_in_the_refusal(
    repo: Path, db_path: Path
) -> None:
    """Depth-1 only — a secret at the worktree root is aggregated, not disclosed.

    What escapes to the ledger and the orchestrator's context is integers plus at
    most three top-level segment names, and this is the case that would leak.
    """
    _write_context(repo)
    _seed_run(db_path, repo)
    for i in range(_LIMIT + 1):
        (repo / f".env.secret{i}").write_text("TOKEN=hunter2\n")

    result = _invoke(repo, db_path, [])

    assert result.exit_code == 5
    assert ".env.secret0" not in result.output
    assert "hunter2" not in result.output
    assert ROOT_SEGMENT in result.output


# --- AC-5: the refusal spends nothing -----------------------------------------


def test_the_refusal_costs_no_review_cycle_and_parks_no_ticket(
    repo: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It is an infra refusal in the shape of ``no_gate_evidence``, never a verdict.

    Three separable claims: the recorded row carries no ``verdict`` (so the close
    gate cannot see it and ``_count_review_events`` excludes it), the cycle count
    is genuinely unchanged, and the ticket is left where it stopped.
    """
    _write_context(repo)
    _seed_run(db_path, repo)
    _pollute_to_excess(repo, ".venv", _LIMIT + 1)

    parked: list[str] = []

    async def _spy_park(*args: Any, **kwargs: Any) -> None:
        parked.append(kwargs.get("to", "?"))

    monkeypatch.setattr(review_mod, "_park_ticket", _spy_park)

    before = run_sync(review_mod._count_review_events(db_path, _RUN_ID))
    result = _invoke(repo, db_path, [])
    after = run_sync(review_mod._count_review_events(db_path, _RUN_ID))

    assert result.exit_code == 5
    assert after == before, "a refusal must not consume a review cycle"
    assert parked == [], "the ticket must stay where it stopped"

    events = _review_events(db_path)
    assert len(events) == 1
    assert events[0]["reason"] == "polluted_worktree"
    assert events[0]["outcome"] == "failed"
    assert "verdict" not in events[0]


def test_the_refusal_records_the_sha_it_measured(repo: Path, db_path: Path) -> None:
    """Bound to HEAD, so the ledger correlates it with the timeouts at that SHA.

    That correlation is the #208 story made legible: an operator reading the run
    sees ``engine_timeout`` and ``polluted_worktree`` against the same tree.
    """
    _write_context(repo)
    _seed_run(db_path, repo)
    _pollute_to_excess(repo, ".venv", _LIMIT + 1)
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()

    _invoke(repo, db_path, [])

    recorded = _review_events(db_path)[0]
    # Bound to the *refusal* row, not merely to "some review event carries HEAD"
    # — a successful review records the same SHA, so asserting the SHA alone
    # would pass against the very behaviour this guard replaces.
    assert recorded["reason"] == "polluted_worktree"
    assert recorded["reviewed_sha"] == head


# --- AC-3/AC-4: the bound, and what must survive it ----------------------------


def test_a_worktree_at_the_bound_still_reviews(repo: Path, db_path: Path) -> None:
    """The measuring test's other half — equal is spent, not exceeded.

    Paired with ``test_a_polluted_worktree_refuses_before_the_engine`` (seeded at
    ``limit + 1``), this is what makes the pair measure the boundary rather than
    merely straddling it.
    """
    _write_context(repo)
    _seed_run(db_path, repo)
    _pollute_to_excess(repo, "junk", _LIMIT)
    calls: list[int] = []

    result = _invoke(repo, db_path, calls)

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["verdict"] == "pass"
    assert calls == [1], "the engine must run at the bound"


def test_a_legitimately_untracked_small_worktree_is_not_refused(
    repo: Path, db_path: Path
) -> None:
    """AC-4's positive control, built from the three things the ticket names.

    A design file under ``.harness/``, a handful of ``__pycache__`` directories,
    and an uncommitted edit to a tracked file — the ordinary residue of a run.
    This is the assertion that fails first if the bound is ever tightened to
    where real work trips it.
    """
    _write_context(repo)
    _seed_run(db_path, repo)

    (repo / ".harness").mkdir(exist_ok=True)
    (repo / ".harness" / "design-359.md").write_text("### Data model\n")
    for pkg in ("a", "b", "c", "d", "e"):
        cache = repo / pkg / "__pycache__"
        cache.mkdir(parents=True)
        for i in range(4):
            (cache / f"m{i}.cpython-311.pyc").write_bytes(b"\x00")
    (repo / "README.md").write_text("edited, uncommitted\n")

    calls: list[int] = []
    result = _invoke(repo, db_path, calls)

    assert result.exit_code == 0, result.output
    assert calls == [1]


def test_the_default_bound_clears_the_positive_control_by_a_wide_margin() -> None:
    """The shipped default is not merely *a* number above the control's size.

    The control above runs against a deliberately small ``_LIMIT``; this pins the
    relationship that matters in production, where the ordinary residue of a run
    that executed the suite in place is ~390 files (``__pycache__`` plus the tool
    caches) against an observed pollution of ~2,977.
    """
    ordinary_residue = 390
    observed_pollution = 2977
    assert ordinary_residue < DEFAULT_UNTRACKED_FILE_LIMIT < observed_pollution


# --- Fail-open and the off switch, through the verb ---------------------------


def test_a_disabled_bound_reviews_a_polluted_worktree(
    repo: Path, db_path: Path
) -> None:
    """``0`` is the escape hatch for a repo whose gate needs a large untracked tree."""
    _write_context(repo, limit=0)
    _seed_run(db_path, repo)
    _pollute_to_excess(repo, "node_modules", 500)
    calls: list[int] = []

    result = _invoke(repo, db_path, calls)

    assert result.exit_code == 0, result.output
    assert calls == [1]


def test_a_degraded_probe_reviews_rather_than_refusing(
    repo: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail-open through the verb: a wedged git must not stop a run.

    The failure this guard prevents is expensive but recoverable; refusing a
    legitimate review is not, so every unanswerable case proceeds.
    """
    from harness import _git as git_mod

    _write_context(repo)
    _seed_run(db_path, repo)
    # Seed *before* wedging git: the seeding helper measures its own baseline
    # through the same probe, so patching first would break the arrangement
    # rather than the behaviour under test.
    _pollute_to_excess(repo, ".venv", _LIMIT + 500)

    real = git_mod.run_git

    def _wedged(cwd: Path, *args: str, **kwargs: object) -> object:
        if args[:1] == ("ls-files",):
            raise subprocess.TimeoutExpired(["git", "ls-files"], 15)
        return real(cwd, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(git_mod, "run_git", _wedged)
    calls: list[int] = []

    result = _invoke(repo, db_path, calls)

    assert result.exit_code == 0, result.output
    assert calls == [1]


# --- Ordering against the refusals either side of it --------------------------


def test_a_red_gate_still_refuses_first_on_the_gate(
    repo: Path, db_path: Path
) -> None:
    """The cheaper, more specific refusal wins — this change reorders nothing.

    A red gate is about what the *caller* just measured; the tree walk is the
    most expensive of the pre-engine checks and stays behind all of them.
    """
    _write_context(repo)
    _seed_run(db_path, repo)
    _pollute_to_excess(repo, ".venv", _LIMIT + 1)
    result = _invoke(repo, db_path, [], gate_exit="1")

    assert result.exit_code == 5
    assert json.loads(result.output)["reason"] == "gate_failed"
