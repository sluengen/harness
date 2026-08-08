"""#363 — `review`'s probe stage, driven through the verb.

The pure judgment is proven in `test_review_probe.py` and the git mechanics in
`test_probe_tree.py`. What is only provable *here* is the orchestration: that the
bounds are handed to the subprocess rather than merely written down, that every
degradation keeps the first pass's verdict, and that a run worktree changed under
the engine's control stops the review before anything else uses that engine's
output.

Two seams are stubbed and they are deliberately separate. The engine runner is
the existing one; the probe runner is new, and splitting them is what lets these
tests assert **"the probe was never spawned"** — an absence that is the actual
claim of AC-3, and one a single shared stub could not express.

AC-4 is the criterion that most easily degrades into decoration, so it is
measured on the argv and the timeout the verb actually passes, never on the
config it read: a budget nobody hands to the subprocess is a convention.
"""

from __future__ import annotations

import json
import subprocess
import tomllib
import unittest.mock as mock
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli import review as review_mod
from harness.cli._engine import EngineTimeoutError
from harness.loop_budget import DEFAULT_PROBE_BUDGET_SECONDS
from harness.state import store
from tests._asyncutil import run_sync
from tests._ledger import seed_design_event

cli_runner = CliRunner()

_RUN_ID = "01JRUNPROBEXXXXXXXXXXXXX01"
_TARGET = "pkg.py"
_TARGET_BODY = "LIMIT = 10\n\n\ndef under(n):\n    return n < LIMIT\n"
_NODE = "tests/test_pkg.py::test_under"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture(autouse=True)
def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    _git(root, "init", "-b", "dev")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / _TARGET).write_text(_TARGET_BODY, encoding="utf-8")
    # The instrument comes from the primary checkout, so it has to be there for
    # the stage to run at all. Its contents are irrelevant: the runner is stubbed.
    (root / "scripts" / "mutate.py").write_text("# stub\n", encoding="utf-8")
    # Production's shape, and load-bearing here rather than cosmetic: `.harness/`
    # and `.worktrees/` are the harness's own directories and are gitignored in a
    # real repo. This fixture resolves `--repo` to the run worktree itself — the
    # one arrangement in which the probe tree lands *inside* the tree under
    # review — so without this the identity check reads the harness's own scratch
    # directory as a write by the engine.
    (root / ".gitignore").write_text(".harness/\n.worktrees/\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    (root / "CONTEXT.md").write_text("```yaml\nrepo:\n  name: t\n```\n", encoding="utf-8")
    return root


@pytest.fixture
def db_path(repo: Path) -> Path:
    path = repo / ".harness" / "harness.db"
    _seed_run(path, repo)
    return path


def _seed_run(db_path: Path, repo: Path) -> None:
    async def _insert() -> None:
        await store.init_db(db_path)
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
                "state_json, inputs_json, base_branch, worktree_path, worktree_branch, "
                "ticket, started_at, pid) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _RUN_ID,
                    "",
                    0,
                    "open",
                    "{}",
                    '{"attended": true}',
                    "dev",
                    str(repo),
                    f"harness/{_RUN_ID}",
                    "363",
                    datetime.now(UTC).isoformat(),
                    1234,
                ),
            )
            await conn.commit()

    run_sync(_insert())
    seed_design_event(db_path, _RUN_ID)


def _set_loop(repo: Path, **keys: object) -> None:
    block = "".join(f"  {k}: {v}\n" for k, v in keys.items())
    (repo / "CONTEXT.md").write_text(
        f"```yaml\nrepo:\n  name: t\n```\n\nloop:\n{block}", encoding="utf-8"
    )


def _proposal(ident: str = "cap", **over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": ident,
        "file": _TARGET,
        "old": "LIMIT = 10",
        "new": f"LIMIT = 9999  # {ident}",
        "kills": [_NODE],
        "observe": ["-c", "import pkg; print(pkg.LIMIT)"],
    }
    base.update(over)
    return base


def _submit(verdict: str, issues: list[str], probes: list[dict[str, object]] | None = None) -> str:
    payload: dict[str, object] = {"verdict": verdict, "issues": issues}
    if probes is not None:
        payload["probes"] = probes
    return f"SUBMIT: {json.dumps(payload)}\n"


class _Engine:
    """A stub engine whose successive invocations return successive stdouts."""

    def __init__(self, *stdouts: str, side_effect: Any = None) -> None:
        self.stdouts = list(stdouts)
        self.calls: list[dict[str, Any]] = []
        self.side_effect = side_effect

    async def __call__(self, **kwargs: Any) -> review_mod.RunResult:
        self.calls.append(kwargs)
        if self.side_effect is not None:
            self.side_effect(len(self.calls))
        stdout = self.stdouts[min(len(self.calls), len(self.stdouts)) - 1]
        return review_mod.RunResult(stdout=stdout, stderr="", returncode=0)


class _Probe:
    """A stub mutation harness: records its argv, writes the report it is told to."""

    def __init__(
        self,
        *,
        returncode: int = 0,
        results: list[dict[str, Any]] | None = None,
        raises: BaseException | None = None,
        stderr: str = "",
    ) -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.results = results or []
        self.raises = raises
        self.calls: list[dict[str, Any]] = []
        #: Captured *during* the call. The verb writes the table into a
        #: `TemporaryDirectory` it removes on the way out — reading it afterwards
        #: measures nothing, which is the trap this stub exists to avoid.
        self.tables: list[str] = []

    async def __call__(self, **kwargs: Any) -> review_mod.RunResult:
        self.calls.append(kwargs)
        cmd = kwargs["cmd"]
        self.tables.append(
            Path(cmd[cmd.index("--table") + 1]).read_text(encoding="utf-8")
        )
        if self.raises is not None:
            raise self.raises
        Path(cmd[cmd.index("--json") + 1]).write_text(
            json.dumps({"select": [], "baseline": {}, "results": self.results}),
            encoding="utf-8",
        )
        return review_mod.RunResult(
            stdout="", stderr=self.stderr, returncode=self.returncode
        )

    @property
    def table(self) -> dict[str, Any]:
        return tomllib.loads(self.tables[0])


def _row(ident: str, outcome: str, *, live: bool = False) -> dict[str, Any]:
    return {
        "id": ident,
        "outcome": outcome,
        "predicted": [_NODE],
        "observed": [_NODE] if outcome == "killed" else [],
        "missing": [],
        "unexpected": [],
        "collected": 1,
        "duration_s": 2.0,
        "detail": "",
        "pristine_digest": "aaa" if live else "",
        "mutated_digest": "bbb" if live else "",
    }


def _invoke(repo: Path, db_path: Path, engine: Any, probe: Any) -> Any:
    with (
        mock.patch.object(review_mod, "_default_runner", engine),
        mock.patch.object(review_mod, "_default_probe_runner", probe),
    ):
        return cli_runner.invoke(
            app,
            [
                "review",
                "--repo",
                str(repo),
                "--db",
                str(db_path),
                "--run-id",
                _RUN_ID,
                "--json",
            ],
        )


def _event(db_path: Path) -> dict[str, Any]:
    async def _fetch() -> list[dict[str, Any]]:
        async with (
            store.connect(db_path) as conn,
            conn.execute(
                "SELECT data_json FROM events WHERE event_type = 'review' ORDER BY id"
            ) as cur,
        ):
            return [json.loads(r[0]) for r in await cur.fetchall()]

    rows = run_sync(_fetch())
    assert rows, "no review event was recorded"
    return rows[-1]


# ---------------------------------------------------------------------------
# AC-3 — the run worktree is byte-identical after the engine exits.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "write",
    [
        lambda r: (r / "scratch.txt").write_text("the engine wrote this\n", encoding="utf-8"),
        lambda r: (r / _TARGET).write_text("LIMIT = 0\n", encoding="utf-8"),
    ],
    ids=["untracked-addition", "tracked-edit"],
)
def test_an_engine_that_writes_into_the_run_worktree_stops_the_review(
    repo: Path, db_path: Path, write: Any
) -> None:
    """AC-3. Infra, not a `fail`: the diff was never the problem.

    The strongest half of this is the *absence* — the probe subprocess is never
    spawned. An engine that has just broken the contract its execute grant rests
    on must not then be handed the thing that grant was for.
    """
    engine = _Engine(_submit("pass", [], [_proposal()]), side_effect=lambda _n: write(repo))
    probe = _Probe()

    result = _invoke(repo, db_path, engine, probe)

    assert result.exit_code == review_mod.EXIT_INFRA_FAILURE
    assert json.loads(result.stdout)["reason"] == review_mod.RUN_WORKTREE_MUTATED_REASON
    assert probe.calls == []
    assert "verdict" not in _event(db_path)


def test_a_commit_made_under_the_engine_stops_the_review(repo: Path, db_path: Path) -> None:
    """The porcelain alone cannot see this — a clean commit leaves it empty."""

    def _commit(_n: int) -> None:
        (repo / "extra.py").write_text("x = 1\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "moved")

    engine = _Engine(_submit("pass", [], [_proposal()]), side_effect=_commit)
    probe = _Probe()

    result = _invoke(repo, db_path, engine, probe)

    assert result.exit_code == review_mod.EXIT_INFRA_FAILURE
    assert json.loads(result.stdout)["reason"] == review_mod.RUN_WORKTREE_MUTATED_REASON
    # The *placement* claim, not only the detection one: the check has to sit
    # before the probe stage, so an engine that just broke the contract its
    # execute grant rests on is never handed the thing that grant was for.
    # Mutation-proved: without this the test stays green against a check made
    # only after the probe stage, where the same write is still detected.
    assert probe.calls == []


def test_an_untouched_worktree_reviews_normally(repo: Path, db_path: Path) -> None:
    """The control. Without it the refusal above could be firing on everything."""
    result = _invoke(repo, db_path, _Engine(_submit("pass", [])), _Probe())

    assert result.exit_code == 0
    assert json.loads(result.stdout)["verdict"] == "pass"


# ---------------------------------------------------------------------------
# AC-4 — the budget is a bound, measured on what reaches the subprocess.
# ---------------------------------------------------------------------------


def test_the_count_cap_truncates_the_table_the_harness_is_handed(
    repo: Path, db_path: Path
) -> None:
    """AC-4, count half — asserted on the rendered table, not on the config.

    Seven proposals against a cap of three. What the mutation harness receives is
    the measurement; `probe_dropped` on the event is what makes the truncation
    auditable rather than silent.
    """
    _set_loop(repo, probe_max_entries=3)
    proposals = [_proposal(f"e{n}") for n in range(7)]
    probe = _Probe(results=[_row(f"e{n}", "killed") for n in range(3)])

    result = _invoke(repo, db_path, _Engine(_submit("pass", [], proposals)), probe)

    assert result.exit_code == 0
    assert [m["id"] for m in probe.table["mutation"]] == ["e0", "e1", "e2"]
    event = _event(db_path)
    assert event["probe_proposed"] == 7
    assert event["probe_dropped"] == 4


def test_the_select_is_verb_owned_and_not_taken_from_the_proposal(
    repo: Path, db_path: Path
) -> None:
    """A reviewer that could choose the selection could spend the budget N+1
    times over the whole suite, which is the cost this stage is bounded against."""
    probe = _Probe(results=[_row("cap", "killed")])

    _invoke(
        repo,
        db_path,
        _Engine(_submit("pass", [], [_proposal(select=["tests"], sentinel_file="x")])),
        probe,
    )

    assert probe.table["select"] == ["-m", "unit or guard"]
    assert probe.table["sentinel_file"] == ".harness-probe"


def test_the_configured_time_ceiling_reaches_the_subprocess(
    repo: Path, db_path: Path
) -> None:
    """AC-4, wall-clock half. A ceiling nobody passes is a convention."""
    _set_loop(repo, probe_budget_seconds=90)
    probe = _Probe(results=[_row("cap", "killed")])

    _invoke(repo, db_path, _Engine(_submit("pass", [], [_proposal()])), probe)

    assert probe.calls[0]["timeout"] == 90.0
    cmd = probe.calls[0]["cmd"]
    assert cmd[cmd.index("--timeout") + 1] == "90"


def test_a_probe_budget_above_the_engine_ceiling_reaches_it_clamped(
    repo: Path, db_path: Path
) -> None:
    """The clamp measured end to end, not only in the loader.

    Raising `engine_timeout_seconds` to buy a probe more time is the standing
    "the ceiling is not the fix" mistake, so the relationship has to hold at the
    one place it can be violated: the argv.
    """
    _set_loop(repo, engine_timeout_seconds=120, probe_budget_seconds=9000)
    probe = _Probe(results=[_row("cap", "killed")])

    _invoke(repo, db_path, _Engine(_submit("pass", [], [_proposal()])), probe)

    assert probe.calls[0]["timeout"] == 120.0


def test_the_default_budget_is_what_reaches_an_unconfigured_repo(
    repo: Path, db_path: Path
) -> None:
    probe = _Probe(results=[_row("cap", "killed")])

    _invoke(repo, db_path, _Engine(_submit("pass", [], [_proposal()])), probe)

    assert probe.calls[0]["timeout"] == float(DEFAULT_PROBE_BUDGET_SECONDS)


def test_a_probe_that_outlives_its_ceiling_is_killed_and_the_verdict_survives(
    repo: Path, db_path: Path
) -> None:
    """The bound has to be enforced *and* survivable. A mutation can induce an
    infinite loop, so an unbounded stage would be a new way to hang a run — and
    a stage that failed the review on its own timeout would be worse than none."""
    probe = _Probe(raises=EngineTimeoutError(timeout=720.0))

    result = _invoke(
        repo, db_path, _Engine(_submit("fail", ["a real finding"], [_proposal()])), probe
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["verdict"] == "fail"
    event = _event(db_path)
    assert event["probe_status"] == "timeout"
    assert event["issues"] == ["a real finding"]


def test_a_disabled_budget_spawns_nothing_and_creates_no_tree(
    repo: Path, db_path: Path
) -> None:
    """`probe_max_entries: 0` restores the pre-#363 behaviour exactly."""
    _set_loop(repo, probe_max_entries=0)
    probe = _Probe()

    result = _invoke(repo, db_path, _Engine(_submit("pass", [], [_proposal()])), probe)

    assert result.exit_code == 0
    assert probe.calls == []
    assert _event(db_path)["probe_status"] == "disabled"
    assert not list((repo / ".worktrees" / "harness").glob("*-probe"))


# ---------------------------------------------------------------------------
# The second pass, and the combination.
# ---------------------------------------------------------------------------


def test_a_live_survivor_reaches_a_second_pass_and_becomes_a_finding(
    repo: Path, db_path: Path
) -> None:
    engine = _Engine(
        _submit("pass", [], [_proposal()]),
        _submit("fail", ["[probe:cap] the cap constant is unguarded"]),
    )
    probe = _Probe(returncode=1, results=[_row("cap", "survived", live=True)])

    result = _invoke(repo, db_path, engine, probe)

    assert len(engine.calls) == 2
    printed = json.loads(result.stdout)
    assert printed["verdict"] == "fail"
    assert printed["issues"] == ["[probe:cap] the cap constant is unguarded"]
    assert printed["probes_run"] == 1
    assert printed["probes_survived"] == 1
    event = _event(db_path)
    assert event["probe_demonstrated"] == ["cap"]
    assert event["probe_second_pass"] is True
    assert event["probe_entries"][0]["live"] is True


@pytest.mark.parametrize(
    "outcome", ["killed", "mispredicted", "inert", "errored"], ids=lambda o: str(o)
)
def test_an_entry_that_is_not_a_survivor_buys_no_second_pass(
    repo: Path, db_path: Path, outcome: str
) -> None:
    """AC-2 at the verb: a failure of the entry costs an engine invocation nobody
    should pay for, and it is absent from the demonstrated set."""
    engine = _Engine(_submit("pass", [], [_proposal()]))
    probe = _Probe(returncode=1, results=[_row("cap", outcome)])

    result = _invoke(repo, db_path, engine, probe)

    assert len(engine.calls) == 1
    assert json.loads(result.stdout)["verdict"] == "pass"
    event = _event(db_path)
    assert "probe_demonstrated" not in event
    assert event["probe_entries"][0]["outcome"] == outcome


def test_a_second_pass_cannot_withdraw_the_first_passs_rejection(
    repo: Path, db_path: Path
) -> None:
    """The monotone combination, at the one place it matters.

    The second pass is asked about the probe outcomes, not re-asked about the
    diff — and it is an engine that has just been told its own proposals mostly
    failed, which is exactly the one most likely to soften.
    """
    engine = _Engine(
        _submit("fail", ["the original finding"], [_proposal()]),
        _submit("pass", []),
    )
    probe = _Probe(returncode=1, results=[_row("cap", "survived", live=True)])

    result = _invoke(repo, db_path, engine, probe)

    # The second pass must actually have run and said `pass`, or this asserts
    # nothing about the combination — it would hold identically against a stage
    # that never reached a second pass at all. Mutation-proved.
    assert len(engine.calls) == 2
    printed = json.loads(result.stdout)
    assert printed["verdict"] == "fail"
    assert printed["issues"] == ["the original finding"]


def test_a_second_pass_that_produces_no_verdict_leaves_the_first_standing(
    repo: Path, db_path: Path
) -> None:
    engine = _Engine(_submit("fail", ["a finding"], [_proposal()]), "no submit line here\n")
    probe = _Probe(returncode=1, results=[_row("cap", "survived", live=True)])

    result = _invoke(repo, db_path, engine, probe)

    assert result.exit_code == 0
    assert json.loads(result.stdout)["verdict"] == "fail"
    assert _event(db_path)["probe_second_pass"] is False


def test_the_second_pass_is_told_what_the_first_pass_concluded(
    repo: Path, db_path: Path
) -> None:
    """A fresh subprocess with no memory of the first would otherwise re-review
    the diff from nothing while holding outcomes it never proposed."""
    engine = _Engine(
        _submit("fail", ["the original finding"], [_proposal()]),
        _submit("fail", ["the original finding", "[probe:cap] a gap"]),
    )
    probe = _Probe(returncode=1, results=[_row("cap", "survived", live=True)])

    _invoke(repo, db_path, engine, probe)

    second_prompt = engine.calls[1]["stdin"]
    assert "the original finding" in second_prompt
    assert "[probe:cap]" in second_prompt
    # It must not be invited to spend the budget a second time.
    assert "up to" not in second_prompt


# ---------------------------------------------------------------------------
# Degradation — every path keeps the verdict.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("returncode", "status"),
    [(2, "refused:unknown"), (3, "unavailable"), (99, "error")],
    ids=["table-refused", "runner-unavailable", "unexpected"],
)
def test_every_non_report_exit_degrades_and_records_which(
    repo: Path, db_path: Path, returncode: int, status: str
) -> None:
    """`unavailable` is the expected in-container outcome — the image is built
    `--no-dev` and carries no pytest — so it is named rather than folded into
    `error`, where it would read like a defect in the diff."""
    probe = _Probe(returncode=returncode)

    result = _invoke(
        repo, db_path, _Engine(_submit("pass", [], [_proposal()])), probe
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["verdict"] == "pass"
    assert _event(db_path)["probe_status"] == status


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        ("refused (prediction): node id not in the baseline\n", "refused:prediction"),
        ("refused (baseline): the tree is already red\n", "refused:baseline"),
        ("something went wrong\n", "refused:unknown"),
    ],
    ids=["prediction", "baseline", "unparseable"],
)
def test_a_refused_table_records_which_rule_refused(
    repo: Path, db_path: Path, stderr: str, expected: str
) -> None:
    """`refused` alone answers the wrong question.

    `refused:prediction` says the reviewer named a node id outside the selection
    — a defect in its proposal, and exactly the measurement that decides whether
    a probing reviewer earns its cost. `refused:baseline` says the tree was
    already red and says nothing about the reviewer at all. Folding the two into
    one status would make the follow-up's central question unanswerable from the
    ledger.

    The unparseable case is the third: a status is an observation, so it degrades
    to `unknown` rather than failing the review that produced it.
    """
    probe = _Probe(returncode=2, stderr=stderr)

    result = _invoke(repo, db_path, _Engine(_submit("pass", [], [_proposal()])), probe)

    assert result.exit_code == 0
    assert _event(db_path)["probe_status"] == expected


def test_a_repo_with_no_mutation_harness_records_no_instrument(
    repo: Path, db_path: Path
) -> None:
    """A consuming repo has no `scripts/mutate.py`. The harness cannot mutate
    what a repo has no instrument for, exactly as it cannot run a gate it has no
    toolchain for."""
    (repo / "scripts" / "mutate.py").unlink()
    probe = _Probe()

    result = _invoke(repo, db_path, _Engine(_submit("pass", [], [_proposal()])), probe)

    assert result.exit_code == 0
    assert probe.calls == []
    assert _event(db_path)["probe_status"] == "no_instrument"


def test_proposals_that_all_fail_screening_spawn_nothing(
    repo: Path, db_path: Path
) -> None:
    """The screen is cheap and the suite run is not; an unrunnable table must
    not cost one."""
    probe = _Probe()

    _invoke(
        repo,
        db_path,
        _Engine(_submit("pass", [], [_proposal("bad", old="NOT IN THE FILE")])),
        probe,
    )

    assert probe.calls == []
    event = _event(db_path)
    assert event["probe_status"] == "none_proposed"
    assert event["probe_proposed"] == 1
    assert event["probe_dropped"] == 1


def test_an_engine_that_proposes_nothing_costs_no_suite_run(
    repo: Path, db_path: Path
) -> None:
    probe = _Probe()

    _invoke(repo, db_path, _Engine(_submit("pass", [])), probe)

    assert probe.calls == []
    assert _event(db_path)["probe_status"] == "none_proposed"


def test_the_probe_tree_is_torn_down_on_every_path(repo: Path, db_path: Path) -> None:
    """It is a *throwaway* tree; leaving one behind accumulates the cruft
    `worktrees cleanup --age` exists to sweep, and the next review reclaims it
    rather than refusing — but only because teardown is not relied upon."""
    probe = _Probe(returncode=2)

    _invoke(repo, db_path, _Engine(_submit("pass", [], [_proposal()])), probe)

    assert not list((repo / ".worktrees" / "harness").glob("*-probe"))


def test_the_instrument_comes_from_the_primary_checkout_not_the_probe_tree(
    repo: Path, db_path: Path
) -> None:
    """Only the *tree* comes from the reviewed SHA. A branch that could swap
    `scripts/mutate.py` would be choosing the instrument that judges it."""
    probe = _Probe(results=[_row("cap", "killed")])

    _invoke(repo, db_path, _Engine(_submit("pass", [], [_proposal()])), probe)

    script = probe.calls[0]["cmd"][1]
    assert script == str(repo / "scripts" / "mutate.py")
    assert "-probe" not in script
