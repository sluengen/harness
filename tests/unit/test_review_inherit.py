"""``harness review`` inherits a prior pass on a resumed run — #259 (ADR 0008 D3).

``close``'s gate reads ``review`` events ``WHERE run_id = ?``. A resumed run is a
new run, so a predecessor's pass is invisible to it — even when the resumed
worktree's HEAD is the **exact commit** that passed, and the tree being merged is
byte-identical to the one that was reviewed. Today that costs a full re-review of
an unchanged tree.

ADR 0008's fix is not to widen the gate query. Certification crosses a run
boundary only as an event recorded on the *inheriting* run, naming its source and
the evidence it rests on — so gates stay run-scoped and nothing reads across runs.

AC-1: the inherited event carries ``verdict='pass'``, the source's
      ``reviewed_sha``, the source's verify-gate evidence, and
      ``inherited_from`` — asserted field by field.
AC-2: **no engine subprocess is spawned** — asserted at the runner seam.
AC-3: ``harness close`` opens on the inherited pass, end to end.
AC-4: the inherit path consumes no review cycle and evaluates no breaker.
AC-5: each of the five decline conditions runs the engine instead.
AC-7: exactly one implementation of the gate-evidence test.
AC-8: an engine-produced event still dumps *without* an ``inherited_from`` key.
AC-9: the inherit path reads the ledger through the payload-path constants.

The path is fail-safe toward the status quo: declining costs one review cycle,
wrongly inheriting opens the close gate on a tree nothing verified.
"""

from __future__ import annotations

import ast
import asyncio
import json
import subprocess
import unittest.mock as mock
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import _review_gate, app
from harness.cli import review as review_mod
from harness.cli import review_inherit as review_inherit_mod
from harness.loop_budget import REVIEW_CYCLE_CEILING_REASON
from harness.state import store
from tests._ledger import seed_design_event

cli_runner = CliRunner()

_TICKET = "259"
_RUN_ID = "01JRESUMEDREVIEWXXXXXXXX01"
_SOURCE_RUN_ID = "01JSOURCEREVIEWXXXXXXXXX01"
_WIP_BRANCH = f"harness/{_SOURCE_RUN_ID}"

_FRESH_PASS_LINE = 'SUBMIT: {"verdict": "pass", "issues": ["freshly reviewed"]}\n'

#: The verify-gate evidence a green gate records (CAL-1082) — what the source
#: run's ``review`` wrote, and what the inherited event must carry verbatim or
#: ``close`` refuses it ``no_gate_evidence``.
_SOURCE_GATE_EVIDENCE: dict[str, Any] = {
    "gate_ran": True,
    "gate_command": "bash scripts/verify.sh",
    "gate_exit_code": 0,
    "gate_output_tail": "3145 passed, 1 skipped",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture(autouse=True)
def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throw-away git repo with one commit on ``dev``.

    ``.harness/`` is gitignored exactly as in the real repo, so the ledger DB the
    verbs create under it never registers as a dirty worktree — the clean-tree
    condition keys off ``git status --porcelain``, which excludes ignored paths.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "dev")
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    (repo_root / ".gitignore").write_text(".harness/\n.worktrees/\n")
    (repo_root / "README.md").write_text("hello\n")
    _git(repo_root, "add", ".gitignore", "README.md")
    _git(repo_root, "commit", "-m", "initial")
    return repo_root


@pytest.fixture
def db_path(repo: Path) -> Path:
    return repo / ".harness" / "harness.db"


def _head_sha(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _sync(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _insert_run(
    db_path: Path,
    run_id: str,
    worktree_path: str,
    *,
    status: str,
    resumed_from: str | None,
    started_at: datetime | None = None,
) -> None:
    await store.init_db(db_path)
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO runs ("
            "run_id, workflow_name, workflow_version, status, state_json, "
            "inputs_json, base_branch, worktree_path, worktree_branch, ticket, "
            "started_at, resumed_from"
            ") VALUES (?, '', 0, ?, '{}', '{}', 'dev', ?, ?, ?, ?, ?)",
            (
                run_id,
                status,
                worktree_path,
                f"harness/{run_id}",
                _TICKET,
                (started_at or datetime.now(UTC)).isoformat(),
                resumed_from,
            ),
        )
        await conn.commit()


def _seed_resumed_run(
    db_path: Path,
    repo: Path,
    *,
    resumed_from: str | None = _WIP_BRANCH,
    started_at: datetime | None = None,
    design: bool = True,
) -> None:
    """The run under test: open, worktree == repo, resumed (or not) as given.

    A ``design`` event is seeded by default because a recorded design attempt is
    itself an inherit condition (the short-circuit may skip work, never a refusal
    about this run's own state) *and* the decline tests all reach the engine,
    which the same check gates. ``design=False`` drops it, for the test that
    asserts the ``no_design`` refusal still fires.
    """
    _sync(
        _insert_run(
            db_path,
            _RUN_ID,
            str(repo),
            status="open",
            resumed_from=resumed_from,
            started_at=started_at,
        )
    )
    if design:
        seed_design_event(db_path, _RUN_ID)


async def _insert_review_event(db_path: Path, run_id: str, data: dict[str, Any]) -> None:
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO events (run_id, event_type, timestamp, data_json) "
            "VALUES (?, 'review', ?, ?)",
            (run_id, datetime.now(UTC).isoformat(), json.dumps(data)),
        )
        await conn.commit()


def _seed_source_review(
    db_path: Path,
    reviewed_sha: str,
    *,
    verdict: str = "pass",
    gate: dict[str, Any] | None = None,
    run_id: str = _SOURCE_RUN_ID,
    seed_run_row: bool = True,
    inherited_from: str | None = None,
) -> None:
    """A closed predecessor run for the same ticket, carrying its review event.

    ``gate`` defaults to the green evidence a current ``harness review`` records;
    pass ``{}`` for the legacy payload with no ``gate_ran`` key, which is what an
    un-evidenced source pass looks like on the ledger.
    """
    if seed_run_row:
        _sync(_insert_run(db_path, run_id, "/gone", status="closed", resumed_from=None))
    _sync(
        _insert_review_event(
            db_path,
            run_id,
            {
                "run_id": run_id,
                "reviewed_sha": reviewed_sha,
                "verdict": verdict,
                "issues": ["a finding the source review recorded"],
                "engine": "codex",
                "convergence_check_required": False,
                "created_at": "2026-07-30T10:00:00Z",
                "design_context": True,
                **({"inherited_from": inherited_from} if inherited_from else {}),
                **(_SOURCE_GATE_EVIDENCE if gate is None else gate),
            },
        )
    )


async def _fetch_review_events(db_path: Path) -> list[dict[str, Any]]:
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT run_id, data_json FROM events WHERE event_type = 'review' ORDER BY id"
        ) as cur,
    ):
        rows = await cur.fetchall()
    return [{"run_id": r[0], "data": json.loads(r[1])} for r in rows]


def review_events(db_path: Path, run_id: str | None = None) -> list[dict[str, Any]]:
    events = _sync(_fetch_review_events(db_path))
    return [e for e in events if run_id is None or e["run_id"] == run_id]


def _assert_only_a_refusal(db_path: Path, reason: str) -> None:
    """The resumed run wrote a refusal (#262) and **nothing inherited**.

    Before #262 these sites asserted the run wrote no event at all, which proved
    the short-circuit had not fired only incidentally. Now that a refusal is
    recorded on purpose, the claim is made directly: the row has no ``verdict``
    (so ``close`` cannot open on it) and no ``inherited_from`` (so no prior pass
    was carried forward), and it names the refusal that was expected.
    """
    (event,) = review_events(db_path, _RUN_ID)
    assert "verdict" not in event["data"], event["data"]
    assert "inherited_from" not in event["data"], event["data"]
    assert event["data"]["reason"] == reason, event["data"]


class _EngineSpy:
    """A runner that records every invocation — AC-2's measuring instrument.

    AC-2 requires zero engine invocations to be *asserted at the seam*, not
    inferred from timing or from the absence of engine-shaped output. This
    counts, and returns a verdict distinguishable from the source's by its
    ``issues``, so a test can tell "inherited" from "re-reviewed" by content.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, **kwargs: Any) -> review_mod.RunResult:
        self.calls += 1
        return review_mod.RunResult(stdout=_FRESH_PASS_LINE, stderr="", returncode=0)


class _FailingEngineSpy(_EngineSpy):
    """An engine whose verdict is a ``fail`` — the discriminating stub for AC-3.

    A pass-returning stub would let ``close`` open on the engine's own event,
    proving nothing about inheritance. With a fail, the only pass that can exist
    for this run is the inherited one.
    """

    async def __call__(self, **kwargs: Any) -> review_mod.RunResult:
        self.calls += 1
        return review_mod.RunResult(
            stdout='SUBMIT: {"verdict": "fail", "issues": ["engine ran"]}\n',
            stderr="",
            returncode=0,
        )


def _invoke(repo: Path, db_path: Path, runner: Any, *extra: str) -> Any:
    with mock.patch.object(review_mod, "_default_runner", runner):
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
                *extra,
            ],
        )


# ---------------------------------------------------------------------------
# AC-1 / AC-2 — the inherit path
# ---------------------------------------------------------------------------


def test_inherits_the_prior_pass_field_by_field(repo: Path, db_path: Path) -> None:
    """AC-1: the inherited event carries the source's certification verbatim.

    Every field describing *the review* is the source's — the SHA it was bound
    to, the gate evidence behind it, the engine that produced it. Only
    ``run_id``, ``created_at`` and ``inherited_from`` describe this inheritance.
    The gate-evidence fields are the load-bearing copy: without them ``close``
    refuses the inherited pass ``no_gate_evidence`` and the run is left neither
    reviewed nor closable.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, head)
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine)

    assert result.exit_code == 0, result.output
    inherited = review_events(db_path, _RUN_ID)
    assert len(inherited) == 1
    data = inherited[0]["data"]
    assert data["run_id"] == _RUN_ID
    assert data["verdict"] == "pass"
    assert data["reviewed_sha"] == head
    assert data["inherited_from"] == _SOURCE_RUN_ID
    assert data["gate_ran"] is True
    assert data["gate_command"] == _SOURCE_GATE_EVIDENCE["gate_command"]
    assert data["gate_exit_code"] == 0
    assert data["gate_output_tail"] == _SOURCE_GATE_EVIDENCE["gate_output_tail"]
    assert data["engine"] == "codex"
    assert data["issues"] == ["a finding the source review recorded"]
    # This run's own identity, not the source's.
    assert data["created_at"] != "2026-07-30T10:00:00Z"


def test_inherit_spawns_no_engine_subprocess(repo: Path, db_path: Path) -> None:
    """AC-2: zero engine invocations — the saving the whole ticket exists for."""
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, head)
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine)

    assert result.exit_code == 0, result.output
    assert engine.calls == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "pass"
    assert payload["reviewed_sha"] == head
    assert payload["run_id"] == _RUN_ID


def test_inherit_reaches_no_subprocess_driver(repo: Path, db_path: Path) -> None:
    """AC-2, one layer lower: the shared spawn driver is never entered.

    The runner seam is the layer a test can stub, but it is not the layer that
    spends money — :func:`harness.cli._engine.run_engine_subprocess` is. Guarding
    both means the assertion survives the verb ever calling the driver directly.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, head)
    spawn = mock.AsyncMock(side_effect=AssertionError("no subprocess may be spawned"))

    with mock.patch("harness.cli._engine.run_engine_subprocess", spawn):
        result = cli_runner.invoke(
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

    assert result.exit_code == 0, result.output
    spawn.assert_not_awaited()


def test_inherit_needs_no_gate_evidence_from_the_caller(repo: Path, db_path: Path) -> None:
    """The gate already ran, for this exact tree; its evidence is on the source.

    The short-circuit precedes the verify-gate check, so a caller that supplies no
    ``--gate-exit`` is not refused ``no_gate_evidence`` — re-running the gate over
    a byte-identical tree is the second cost this ticket removes, after the engine.
    """
    (repo / "CONTEXT.md").write_text(
        '```yaml\nrepo:\n  name: t\nverify: "bash scripts/verify.sh"\n```\n'
    )
    _git(repo, "add", "CONTEXT.md")
    _git(repo, "commit", "-m", "context")
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, head)

    result = _invoke(repo, db_path, _EngineSpy())

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["verdict"] == "pass"


def test_inherit_notes_the_source_run_on_stderr(repo: Path, db_path: Path) -> None:
    """The ledger records the inheritance; stderr says it out loud.

    An operator reading a tick log must be able to see that this pass was
    inherited rather than earned, and from where, without querying the ledger.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, head)

    result = _invoke(repo, db_path, _EngineSpy())

    assert result.exit_code == 0, result.output
    assert _SOURCE_RUN_ID in result.stderr


# ---------------------------------------------------------------------------
# AC-4 — no cycle consumed, no breaker evaluated
# ---------------------------------------------------------------------------


def test_inherit_evaluates_no_breaker_at_the_cycle_ceiling(repo: Path, db_path: Path) -> None:
    """AC-4: a run already at the ceiling still inherits.

    The short-circuit precedes the breakers deliberately. An inherited pass buys
    no engine time, so charging it against a spend budget would refuse a run for
    a cost it never incurred — and would leave a resumed run at the ceiling
    permanently unable to close a tree that already passed.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, head)
    for _ in range(6):
        _sync(
            _insert_review_event(
                db_path,
                _RUN_ID,
                {"verdict": "fail", "reviewed_sha": "deadbeef", "run_id": _RUN_ID},
            )
        )

    result = _invoke(repo, db_path, _EngineSpy())

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["verdict"] == "pass"


def test_inherit_consumes_no_review_cycle(repo: Path, db_path: Path) -> None:
    """AC-4: the cycle count the breaker measures is unchanged afterward.

    Counting an inherited pass as a cycle would spend budget on a review that
    never ran — and would let a resumed run's *first* action eat a cycle it did
    not use. The count is measured through the verb's own counter, not a
    hand-rolled query, so the two cannot drift.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, head)
    _sync(
        _insert_review_event(
            db_path,
            _RUN_ID,
            {"verdict": "fail", "reviewed_sha": "deadbeef", "run_id": _RUN_ID},
        )
    )
    before = _sync(review_mod._count_review_events(db_path, _RUN_ID))

    result = _invoke(repo, db_path, _EngineSpy())

    assert result.exit_code == 0, result.output
    after = _sync(review_mod._count_review_events(db_path, _RUN_ID))
    assert after == before == 1
    # The event itself *was* appended — it is the certification close reads.
    assert len(review_events(db_path, _RUN_ID)) == 2


# ---------------------------------------------------------------------------
# AC-5 — the five decline conditions
# ---------------------------------------------------------------------------


def test_declines_when_run_did_not_resume(repo: Path, db_path: Path) -> None:
    """AC-5(1): provenance is required, not merely a SHA match.

    A clean-start run's HEAD can only coincide with an old pass by accident of
    branch recreation. Gating on ``resumed_from`` removes that reasoning entirely
    rather than asking how likely the coincidence is.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo, resumed_from=None)
    _seed_source_review(db_path, head)
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine)

    assert result.exit_code == 0, result.output
    assert engine.calls == 1
    assert review_events(db_path, _RUN_ID)[-1]["data"]["issues"] == ["freshly reviewed"]


def test_declines_when_no_pass_covers_head(repo: Path, db_path: Path) -> None:
    """AC-5(2): a pass for another tree certifies nothing about this one."""
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, "b" * 40)
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine)

    assert result.exit_code == 0, result.output
    assert engine.calls == 1


@pytest.mark.parametrize(
    ("gate", "inheritable"),
    [
        pytest.param(
            {"gate_ran": True, "gate_command": "bash scripts/verify.sh", "gate_exit_code": 0},
            True,
            id="green-gate",
        ),
        pytest.param(
            {"gate_ran": False, "gate_reason": "not_configured"},
            True,
            id="no-gate-configured",
        ),
        pytest.param(
            {"gate_ran": False, "gate_reason": "some_other_reason"},
            False,
            id="false-with-another-reason",
        ),
        pytest.param({"gate_ran": False}, False, id="false-with-no-reason"),
        pytest.param({}, False, id="legacy-payload-with-no-gate-key"),
    ],
)
def test_inherit_decision_matches_the_gate_evidence_truth_table(
    repo: Path, db_path: Path, gate: dict[str, Any], inheritable: bool
) -> None:
    """AC-5(3) / AC-7: the decision tracks ``has_gate_evidence`` case for case.

    This is the behavioural half of "one implementation": a paraphrased second
    copy in the inherit path would pass the source-scan guard below and fail
    here, because the two rows that *do* qualify are exactly the two
    :func:`~harness.cli._review_gate.has_gate_evidence` accepts — a green gate,
    and a repo that honestly configures none.

    Declining matters as much as accepting: an un-evidenced pass carried forward
    is one ``close`` then refuses ``no_gate_evidence``, leaving the run neither
    reviewed nor closable — the exact wedge the shared predicate prevents.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, head, gate=gate)
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine)

    assert result.exit_code == 0, result.output
    assert engine.calls == (0 if inheritable else 1)
    data = review_events(db_path, _RUN_ID)[-1]["data"]
    assert ("inherited_from" in data) is inheritable


def test_declines_when_run_recorded_no_design(repo: Path, db_path: Path) -> None:
    """A skipped stage is not a skipped refusal: ``no_design`` still fires.

    The short-circuit precedes the design gate, so without condition 2 a resumed
    run that never recorded a design attempt would reach ``close`` with
    ADR 0007 D3 silently bypassed — the one lifecycle stage ``review`` exists to
    enforce.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo, design=False)
    _seed_source_review(db_path, head)
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine)

    assert result.exit_code == review_mod.EXIT_GATE_FAILED, result.output
    assert json.loads(result.stdout)["reason"] == review_mod.NO_DESIGN_REASON
    assert engine.calls == 0
    # #262 records the refusal, but nothing *inherited* was written: the row
    # carries neither a verdict nor an ``inherited_from``, so the short-circuit
    # provably did not fire.
    _assert_only_a_refusal(db_path, review_mod.NO_DESIGN_REASON)


def test_declines_when_the_caller_reports_a_red_gate(repo: Path, db_path: Path) -> None:
    """An inherited pass never overrides the caller's own red evidence.

    HEAD being byte-identical to a green-passed tree makes a red result a flake
    or an environment difference — but ``close`` reads only the ledger, so
    certifying it would land a merge on a tree whose gate is red *now*.
    """
    (repo / "CONTEXT.md").write_text(
        '```yaml\nrepo:\n  name: t\nverify: "bash scripts/verify.sh"\n```\n'
    )
    _git(repo, "add", "CONTEXT.md")
    _git(repo, "commit", "-m", "context")
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, head)
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine, "--gate-exit", "1")

    assert result.exit_code == review_mod.EXIT_GATE_FAILED, result.output
    assert json.loads(result.stdout)["reason"] == review_mod.GATE_FAILED_REASON
    assert engine.calls == 0
    _assert_only_a_refusal(db_path, review_mod.GATE_FAILED_REASON)


def test_declines_when_the_only_covering_pass_is_itself_inherited(
    repo: Path, db_path: Path
) -> None:
    """One-hop provenance: ``inherited_from`` always names an engine-run pass.

    A chain would still be sound — the SHA and the evidence carry through — but
    it makes provenance a walk instead of a read. Excluding it costs nothing:
    the original event stays in the same ledger under the same ticket and SHA,
    so a second-generation resumed run inherits from it directly.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, head, inherited_from="01JGRANDPARENTXXXXXXXXXX01")
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine)

    assert result.exit_code == 0, result.output
    assert engine.calls == 1


def test_declines_when_the_source_payload_will_not_parse(repo: Path, db_path: Path) -> None:
    """An unreadable source has no opinion — it must not half-build a pass.

    Validating the payload as a :class:`ReviewEventData` rather than indexing a
    dict is what makes the field-by-field copy safe: a payload missing a field
    the copy assumes declines here instead of producing a certification with a
    hole in it.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    # Selected by the SQL (verdict + SHA match) but not constructible: no
    # ``gate_ran``, no ``engine``, no ``created_at``.
    _sync(_insert_run(db_path, _SOURCE_RUN_ID, "/gone", status="closed", resumed_from=None))
    _sync(
        _insert_review_event(
            db_path,
            _SOURCE_RUN_ID,
            {"verdict": "pass", "reviewed_sha": head},
        )
    )
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine)

    assert result.exit_code == 0, result.output
    assert engine.calls == 1


def test_declines_when_the_source_engine_is_outside_the_printed_literal(
    repo: Path, db_path: Path
) -> None:
    """The printed ``engine`` is the source's, so it must be a value that contract allows.

    ``ReviewOutput.engine`` is a two-value literal every downstream reader
    branches on; a ledger row is untyped data and could carry anything. Declining
    keeps the contract narrow rather than widening it to ``str`` — and an
    engine nobody recognises is not a certification worth inheriting anyway.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _sync(_insert_run(db_path, _SOURCE_RUN_ID, "/gone", status="closed", resumed_from=None))
    _sync(
        _insert_review_event(
            db_path,
            _SOURCE_RUN_ID,
            {
                "run_id": _SOURCE_RUN_ID,
                "reviewed_sha": head,
                "verdict": "pass",
                "issues": [],
                "engine": "some-engine-from-the-future",
                "convergence_check_required": False,
                "created_at": "2026-07-30T10:00:00Z",
                **_SOURCE_GATE_EVIDENCE,
            },
        )
    )
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine)

    assert result.exit_code == 0, result.output
    assert engine.calls == 1


def test_declines_when_the_git_probe_fails(repo: Path, db_path: Path) -> None:
    """A git call that cannot answer declines rather than erroring the verb.

    Every uncertainty resolves toward reviewing: the inherit path is an
    optimisation, and an optimisation that can fail a run is worse than no
    optimisation.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, head)
    engine = _EngineSpy()

    with mock.patch.object(
        review_inherit_mod, "worktree_porcelain", side_effect=RuntimeError("wedged")
    ):
        result = _invoke(repo, db_path, engine)

    assert result.exit_code == 0, result.output
    assert engine.calls == 1


def test_the_git_probes_are_bounded_by_a_timeout(repo: Path, db_path: Path) -> None:
    """A *wedged* probe — one that hangs rather than fails — must also decline.

    The synchronous-raise test above never reaches the missing-ceiling path: an
    unresponsive mount or a stale ``index.lock`` does not raise, it blocks. Both
    probes therefore pass the same bounded ceiling ``reclaim --stale``'s closable
    predicate uses, and a fired :class:`subprocess.TimeoutExpired` is caught here
    exactly like any other probe failure.

    Simulated by having the probe raise what a fired timeout raises, and pinned
    by asserting the ceiling was actually passed — a test that only stubbed the
    exception would stay green if the ``timeout=`` argument were dropped.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, head)
    engine = _EngineSpy()
    seen: dict[str, Any] = {}

    def _hang(worktree: Path, *, timeout: float | None = None) -> str:
        seen["timeout"] = timeout
        raise subprocess.TimeoutExpired(cmd=["git", "status"], timeout=timeout or 0)

    with mock.patch.object(review_inherit_mod, "worktree_porcelain", _hang):
        result = _invoke(repo, db_path, engine)

    assert result.exit_code == 0, result.output
    assert engine.calls == 1
    assert seen["timeout"] == review_inherit_mod._PROBE_TIMEOUT_SECONDS


def test_head_probe_is_bounded_by_the_same_timeout(
    repo: Path, db_path: Path
) -> None:
    """The ceiling covers **both** probes — a clean tree still has to read HEAD.

    ``worktree_porcelain`` runs first, so a test that only wedges it would leave
    ``rev_parse_head`` unbounded and green.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, head)
    engine = _EngineSpy()
    seen: dict[str, Any] = {}

    def _hang(worktree: Path, *, timeout: float | None = None) -> str:
        seen["timeout"] = timeout
        raise subprocess.TimeoutExpired(cmd=["git", "rev-parse"], timeout=timeout or 0)

    with mock.patch.object(review_inherit_mod, "rev_parse_head", _hang):
        result = _invoke(repo, db_path, engine)

    assert result.exit_code == 0, result.output
    assert engine.calls == 1
    assert seen["timeout"] == review_inherit_mod._PROBE_TIMEOUT_SECONDS


def test_declines_when_source_event_at_head_is_a_fail(repo: Path, db_path: Path) -> None:
    """AC-5(4): only a ``pass`` certifies; a fail at the same SHA is not one."""
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, head, verdict="fail")
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine)

    assert result.exit_code == 0, result.output
    assert engine.calls == 1


def test_declines_when_worktree_is_dirty(repo: Path, db_path: Path) -> None:
    """AC-5(5): HEAD does not describe a tree with uncommitted edits.

    The whole safety argument is that the tree being certified is byte-identical
    to the one that passed. Uncommitted edits break that without moving HEAD, so
    the SHA match alone would be a lie.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, head)
    (repo / "README.md").write_text("edited after the pass\n")
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine)

    assert result.exit_code == 0, result.output
    assert engine.calls == 1


def test_declines_when_the_matching_pass_is_this_runs_own(repo: Path, db_path: Path) -> None:
    """A run cannot inherit from itself — that is a re-review, not an inheritance.

    Without the exclusion, a second ``harness review`` on a resumed run that had
    already passed normally would short-circuit on its *own* event and stop
    reviewing the tree at all.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, head, run_id=_RUN_ID, seed_run_row=False)
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine)

    assert result.exit_code == 0, result.output
    assert engine.calls == 1


def test_declines_when_the_pass_belongs_to_another_ticket(repo: Path, db_path: Path) -> None:
    """Inheritance follows the change spec, as design adoption does (ADR 0007 D2).

    A pass recorded against a different ticket says nothing about this ticket's
    acceptance criteria, however well its SHA matches.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _sync(_insert_run(db_path, _SOURCE_RUN_ID, "/gone", status="closed", resumed_from=None))
    _retarget_run_ticket(db_path, _SOURCE_RUN_ID, "999")
    _seed_source_review(db_path, head, seed_run_row=False)
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine)

    assert result.exit_code == 0, result.output
    assert engine.calls == 1


def _retarget_run_ticket(db_path: Path, run_id: str, ticket: str) -> None:
    async def _update() -> None:
        async with store.connect(db_path) as conn:
            await conn.execute("UPDATE runs SET ticket = ? WHERE run_id = ?", (ticket, run_id))
            await conn.commit()

    _sync(_update())


# ---------------------------------------------------------------------------
# AC-8 — the engine path is unchanged
# ---------------------------------------------------------------------------


def test_engine_produced_event_omits_inherited_from(repo: Path, db_path: Path) -> None:
    """AC-8: the key is absent, not ``null``.

    ``exclude_none=True`` is what keeps an additive optional off every event that
    does not use it, so an existing reader cannot start seeing a new key.
    """
    _seed_resumed_run(db_path, repo, resumed_from=None)
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine)

    assert result.exit_code == 0, result.output
    assert engine.calls == 1
    data = review_events(db_path, _RUN_ID)[-1]["data"]
    assert "inherited_from" not in data


# ---------------------------------------------------------------------------
# AC-3 — the close gate opens on an inherited pass
# ---------------------------------------------------------------------------


def test_close_opens_on_an_inherited_pass(repo: Path, db_path: Path) -> None:
    """AC-3: end to end — resumed run, inherited pass, completed close.

    This is the whole point: ``close``'s gate is **unchanged** and still
    run-scoped, and the inherited event satisfies it as written — no
    ``no_passing_review``, no ``stale_review``, no ``no_gate_evidence``. If any of
    the three fired, the copy of the source's fields was wrong.

    The stubbed engine returns a **fail**, so the close can only open on the
    inherited pass: were the short-circuit absent, the engine's verdict would be
    the run's only review event and ``close`` would refuse ``no_passing_review``.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, head)

    review_result = _invoke(repo, db_path, _FailingEngineSpy())
    assert review_result.exit_code == 0, review_result.output
    assert json.loads(review_result.stdout)["verdict"] == "pass"

    tracker = mock.MagicMock()
    tracker.transition_to_done = mock.AsyncMock(return_value=None)
    merge = mock.MagicMock(return_value=None)
    with (
        mock.patch("harness.tracker.LinearClient", return_value=tracker),
        mock.patch("harness.tracker.linear_api_key", return_value="test-key"),
        mock.patch("harness.close_merge.merge_run_branch", merge),
    ):
        close_result = cli_runner.invoke(
            app,
            [
                "close",
                _TICKET,
                "--repo",
                str(repo),
                "--db",
                str(db_path),
                "--run-id",
                _RUN_ID,
                "--json",
            ],
        )

    assert close_result.exit_code == 0, close_result.output
    payload = json.loads(close_result.stdout)
    assert payload["merged"] is True
    assert payload["reviewed_sha"] == head
    assert payload["status"] == "closed"
    merge.assert_called_once()


# ---------------------------------------------------------------------------
# AC-7 / AC-9 — boundary checks on the inherit path's source
# ---------------------------------------------------------------------------


def _harness_sources() -> list[Path]:
    package = Path(review_mod.__file__).resolve().parent.parent
    return sorted(package.rglob("*.py"))


def test_gate_evidence_test_has_exactly_one_implementation() -> None:
    """AC-7: one definition of the gate-evidence rule, in its shared home.

    Two implementations of the close gate's evidence test is exactly how the gate
    stops meaning one thing — a sweep, a review and a close each answering "was
    this verified?" slightly differently. The predicate was already extracted to
    :mod:`harness.cli._review_gate` (#255); this pins that the inherit path
    *reuses* it rather than adding the second copy.

    Parsed rather than grepped, so a definition split across lines or renamed by
    a decorator still counts. Its companion is the truth-table test above, which
    is what catches a *paraphrased* copy this scan would not see.
    """
    definitions = [
        path
        for path in _harness_sources()
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
        and node.name in ("has_gate_evidence", "_has_gate_evidence")
    ]
    assert [p.name for p in definitions] == ["_review_gate.py"]
    assert review_inherit_mod.has_gate_evidence is _review_gate.has_gate_evidence


def test_inherit_path_holds_no_literal_json_path() -> None:
    """AC-9: the ledger is read through the payload-path constants (run-ledger.md:53).

    A literal ``$.verdict`` in a second module is a rename waiting to break one
    reader silently; the derived constants fail at import instead — ``_field_path``
    verifies each against the model at import time.
    """
    source = Path(review_inherit_mod.__file__).read_text()
    assert "$." not in source
    for constant in (
        "REVIEW_VERDICT_PATH",
        "REVIEW_REVIEWED_SHA_PATH",
        "REVIEW_INHERITED_FROM_PATH",
    ):
        assert constant in source


# ---------------------------------------------------------------------------
# The cycle-count filter, and the ordering the hoisted reads must not disturb
# ---------------------------------------------------------------------------


def test_cycle_count_excludes_inherited_events_only(repo: Path, db_path: Path) -> None:
    """The filter itself, over a mixed set — the breaker's input.

    Pinned directly rather than only through the verb, because this is what the
    review-cycle ceiling and the wall-clock breaker both measure: an off-by-one
    here silently shortens every resumed run's fix budget.
    """
    _seed_resumed_run(db_path, repo)
    for verdict in ("fail", "fail", "pass"):
        _sync(
            _insert_review_event(
                db_path,
                _RUN_ID,
                {"verdict": verdict, "reviewed_sha": "deadbeef", "run_id": _RUN_ID},
            )
        )
    for source in ("01JA", "01JB"):
        _sync(
            _insert_review_event(
                db_path,
                _RUN_ID,
                {
                    "verdict": "pass",
                    "reviewed_sha": "deadbeef",
                    "run_id": _RUN_ID,
                    "inherited_from": source,
                },
            )
        )

    assert _sync(review_mod._count_review_events(db_path, _RUN_ID)) == 3


def test_second_review_at_the_same_head_inherits_again(repo: Path, db_path: Path) -> None:
    """Idempotent by append, as the adopt path is — and still cycle-free.

    Re-running ``review`` is legitimate (the ledger is append-only and nothing is
    mutated). The second inherited event must not become a source for itself, and
    must not start costing cycles.
    """
    head = _head_sha(repo)
    _seed_resumed_run(db_path, repo)
    _seed_source_review(db_path, head)

    first = _invoke(repo, db_path, _EngineSpy())
    second = _invoke(repo, db_path, _EngineSpy())

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    events = review_events(db_path, _RUN_ID)
    assert len(events) == 2
    assert {e["data"]["inherited_from"] for e in events} == {_SOURCE_RUN_ID}
    assert _sync(review_mod._count_review_events(db_path, _RUN_ID)) == 0


def test_a_non_inheriting_run_keeps_todays_refusal_order(repo: Path, db_path: Path) -> None:
    """Regression: hoisting two ledger reads must not move a refusal.

    ``_read_ticket`` and ``_read_latest_design_event`` now run above the
    short-circuit. Moving a *read* is behaviour-preserving only if the refusals
    that consume them keep their order — the breaker before the design gate,
    the design gate before the verify-gate evidence — which is what ``review``'s
    own comments promise and what a caller branching on ``reason`` relies on.
    """
    (repo / "CONTEXT.md").write_text(
        '```yaml\nrepo:\n  name: t\nverify: "bash scripts/verify.sh"\n```\n'
    )
    # A clean-start run with no design event and no gate evidence supplied: all
    # three refusals are armed at once, so whichever fires names the order.
    _seed_resumed_run(db_path, repo, resumed_from=None, design=False)

    design_first = _invoke(repo, db_path, _EngineSpy())
    assert design_first.exit_code == review_mod.EXIT_GATE_FAILED
    assert json.loads(design_first.stdout)["reason"] == review_mod.NO_DESIGN_REASON

    # With a design on record, the gate-evidence refusal is next.
    seed_design_event(db_path, _RUN_ID)
    gate_next = _invoke(repo, db_path, _EngineSpy())
    assert gate_next.exit_code == review_mod.EXIT_GATE_FAILED
    assert json.loads(gate_next.stdout)["reason"] == review_mod.NO_GATE_EVIDENCE_REASON

    # And the breaker outranks both.
    for _ in range(6):
        _sync(
            _insert_review_event(
                db_path,
                _RUN_ID,
                {"verdict": "fail", "reviewed_sha": "deadbeef", "run_id": _RUN_ID},
            )
        )
    breaker = _invoke(repo, db_path, _EngineSpy())
    assert breaker.exit_code == review_mod.EXIT_BREAKER_TRIPPED
    assert json.loads(breaker.stdout)["reason"] == REVIEW_CYCLE_CEILING_REASON
