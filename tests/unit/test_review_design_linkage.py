"""#212 — ``review`` enforces the design stage and reviews against the design.

ADR 0007 puts a ``design`` stage between ``start`` and implement, and gives
``review`` two jobs on top of it (proposal ``design-verb.md`` D3, breakdown
item 3):

* **Enforcement.** A run with no recorded design attempt is refused *before any
  engine runs*, with ``reason=no_design`` — the ``no_gate_evidence`` philosophy:
  silence is not a pass. Per D4 a ``status='failed'`` design event **satisfies**
  the check: the stage degrades and records, so an infra flake costs a run its
  design but never its ability to ship.
* **Context.** When a design was produced, it is passed to the review engine, so
  the ``(fix → review)*`` loop converges on conformance to the design instead of
  re-deriving intent every cycle.

**Where the design text comes from.** The ledger event carries the design's
``design_hash``, not its markdown (#211 deliberately kept the body out of the
ledger; the body lives on the ticket as a marked comment). The ticket for this
change named two ways to close that gap — re-fetch the comment, or have the
``DesignOutput`` consumer pass it — and this build takes the second: the
orchestrator that ran ``harness design`` already holds the design on stdout, so
it hands it back with ``--design-file`` and the verb **verifies it against the
recorded hash** before it reaches the prompt. That keeps the tracker seam out of
it (no comment-read method on two backends), keeps the ledger event the single
key for both behaviours, and matches #211's own as-built note that nothing reads
the design back out of the comment.

**Enforcement refuses; context degrades.** The presence check is ledger-keyed
and unbypassable, so it refuses. Supplying the design is enrichment: an absent,
unreadable, or hash-mismatched file drops the context with a warning rather than
failing the run, because dropping it already achieves the safe outcome (never
review against an unverified design) and refusing would only add a wedge.

These tests inject a fake engine runner and seed the ledger directly, exactly
like ``test_review_verify_gate.py``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import unittest.mock as mock
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli import review as review_mod
from harness.cli.design_protocol import design_content_hash
from harness.cli.review_protocol import build_review_prompt, resolve_design_gate
from harness.events.payloads import DESIGN_HASH_KEY, DESIGN_STATUS_KEY, DesignEventData
from harness.loop_budget import REVIEW_CYCLE_CEILING_REASON
from harness.state import store
from tests._ledger import seed_design_event

cli_runner = CliRunner()

_PASS_LINE = 'SUBMIT: {"verdict": "pass", "issues": []}\n'
_RUN_ID = "01JRUNDESIGNXXXXXXXXXXXXX01"
_DESIGN = "### Data model\n\nNo change.\n\n### Interface / contract\n\nOne flag.\n"


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


def _sync(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _seed_run(db_path: Path, repo: Path, *, started_at: datetime | None = None) -> str:
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
                    "212",
                    (started_at or datetime.now(UTC)).isoformat(),
                    1234,
                ),
            )
            await conn.commit()

    _sync(_insert())
    return _RUN_ID


def _seed_design(db_path: Path, **kwargs: Any) -> None:
    """Append one ``design`` event for this module's run, via the shared seeder."""
    seed_design_event(db_path, _RUN_ID, **kwargs)


def _seed_reviews(db_path: Path, count: int) -> None:
    async def _insert() -> None:
        async with store.connect(db_path) as conn:
            for _ in range(count):
                await conn.execute(
                    "INSERT INTO events (run_id, event_type, timestamp, data_json) "
                    "VALUES (?, 'review', ?, ?)",
                    (
                        _RUN_ID,
                        "2026-07-26T00:00:00Z",
                        json.dumps({"verdict": "fail", "reviewed_sha": "deadbeef"}),
                    ),
                )
            await conn.commit()

    _sync(_insert())


def _capturing_runner(stdout: str, prompts: list[str]) -> Any:
    async def _runner(
        *,
        cmd: list[str],
        stdin: str,
        env: dict[str, str],
        cwd: Path | None,
        timeout: float | None = None,
    ) -> review_mod.RunResult:
        prompts.append(stdin)
        return review_mod.RunResult(stdout=stdout, stderr="", returncode=0)

    return _runner


def _write_design_file(repo: Path, text: str) -> Path:
    path = repo / "design.md"
    path.write_text(text)
    return path


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


def _review_events(db_path: Path) -> list[dict[str, Any]]:
    async def _fetch() -> list[dict[str, Any]]:
        async with (
            store.connect(db_path) as conn,
            conn.execute("SELECT data_json FROM events WHERE event_type = 'review'") as cur,
        ):
            rows = await cur.fetchall()
        return [json.loads(r[0]) for r in rows]

    return _sync(_fetch())


# ---------------------------------------------------------------------------
# AC-1: no design event → exit 5 no_design, before any engine, no event
# ---------------------------------------------------------------------------


def test_no_design_event_refuses_before_the_engine(repo: Path, db_path: Path) -> None:
    _seed_run(db_path, repo)
    prompts: list[str] = []

    result = _invoke(repo, db_path, _capturing_runner(_PASS_LINE, prompts))

    assert result.exit_code == review_mod.EXIT_GATE_FAILED
    payload = json.loads(result.stdout)
    assert payload["reason"] == review_mod.NO_DESIGN_REASON
    assert prompts == [], "an undesigned run must not reach an engine"
    assert _review_events(db_path) == [], "no event may be recorded on a refusal"


def test_no_design_refusal_names_the_verb_that_satisfies_it(
    repo: Path, db_path: Path
) -> None:
    """The refusal is actionable: it names ``harness design`` (ADR 0007)."""
    _seed_run(db_path, repo)

    result = _invoke(repo, db_path, _capturing_runner(_PASS_LINE, []))

    assert "harness design" in json.loads(result.stdout)["error"]


# ---------------------------------------------------------------------------
# AC-2: a FAILED design event satisfies the check (ADR 0007 D4)
# ---------------------------------------------------------------------------


def test_failed_design_event_satisfies_the_check(repo: Path, db_path: Path) -> None:
    """Attempted-and-recorded, not succeeded — an infra flake never wedges a run."""
    _seed_run(db_path, repo)
    _seed_design(db_path, status="failed")
    prompts: list[str] = []

    result = _invoke(repo, db_path, _capturing_runner(_PASS_LINE, prompts))

    assert result.exit_code == 0, result.stdout
    assert len(prompts) == 1, "a recorded failed attempt must let the review proceed"
    assert _DESIGN not in prompts[0], "there is no design to review against"


def test_failed_design_event_ignores_a_supplied_design_file(
    repo: Path, db_path: Path
) -> None:
    """No ``ok`` event means no recorded hash — so nothing authenticates the file."""
    _seed_run(db_path, repo)
    _seed_design(db_path, status="failed")
    prompts: list[str] = []

    result = _invoke(
        repo,
        db_path,
        _capturing_runner(_PASS_LINE, prompts),
        "--design-file",
        str(_write_design_file(repo, _DESIGN)),
    )

    assert result.exit_code == 0, result.stdout
    assert _DESIGN not in prompts[0]


# ---------------------------------------------------------------------------
# AC-3: an ok design event → the design is in the engine prompt
# ---------------------------------------------------------------------------


def test_ok_design_event_puts_the_design_in_the_engine_prompt(
    repo: Path, db_path: Path
) -> None:
    _seed_run(db_path, repo)
    _seed_design(db_path, design_hash=design_content_hash(_DESIGN))
    prompts: list[str] = []

    result = _invoke(
        repo,
        db_path,
        _capturing_runner(_PASS_LINE, prompts),
        "--design-file",
        str(_write_design_file(repo, _DESIGN)),
    )

    assert result.exit_code == 0, result.stdout
    assert _DESIGN in prompts[0], "the engine reviews the diff against the design"
    assert "SUBMIT:" in prompts[0], "the SUBMIT contract survives the added context"


def test_design_context_does_not_leak_into_the_printed_verdict(
    repo: Path, db_path: Path
) -> None:
    """Context economy: the design goes *in*, only the bounded verdict comes out."""
    _seed_run(db_path, repo)
    _seed_design(db_path, design_hash=design_content_hash(_DESIGN))

    result = _invoke(
        repo,
        db_path,
        _capturing_runner(_PASS_LINE, []),
        "--design-file",
        str(_write_design_file(repo, _DESIGN)),
    )

    assert result.exit_code == 0, result.stdout
    assert "Data model" not in result.stdout


def test_supplied_design_whose_hash_does_not_match_is_dropped_with_a_warning(
    repo: Path, db_path: Path
) -> None:
    """An unverifiable design is never reviewed against — but it does not wedge."""
    _seed_run(db_path, repo)
    _seed_design(db_path, design_hash=design_content_hash(_DESIGN))
    tampered = _DESIGN + "\n\ntampered\n"
    prompts: list[str] = []

    result = _invoke(
        repo,
        db_path,
        _capturing_runner(_PASS_LINE, prompts),
        "--design-file",
        str(_write_design_file(repo, tampered)),
    )

    assert result.exit_code == 0, result.stdout
    assert len(prompts) == 1, "a mismatch degrades the context, it does not refuse"
    assert "tampered" not in prompts[0], "unverified text must not reach the engine"
    assert "does not match" in result.stderr
    assert len(_review_events(db_path)) == 1


def test_ok_design_without_a_design_file_proceeds_and_is_recorded(
    repo: Path, db_path: Path
) -> None:
    """Not supplying one is a normal state — recorded on the event, not warned."""
    _seed_run(db_path, repo)
    _seed_design(db_path, design_hash=design_content_hash(_DESIGN))
    prompts: list[str] = []

    result = _invoke(repo, db_path, _capturing_runner(_PASS_LINE, prompts))

    assert result.exit_code == 0, result.stdout
    assert len(prompts) == 1
    assert _DESIGN not in prompts[0]
    assert result.stderr == "", "the common case must not put noise on every review"
    (event,) = _review_events(db_path)
    assert event["design_context"] is False


def test_a_design_backed_review_records_that_it_saw_the_design(
    repo: Path, db_path: Path
) -> None:
    """Whether the linkage worked is a ledger question, not a console one."""
    _seed_run(db_path, repo)
    _seed_design(db_path, design_hash=design_content_hash(_DESIGN))

    result = _invoke(
        repo,
        db_path,
        _capturing_runner(_PASS_LINE, []),
        "--design-file",
        str(_write_design_file(repo, _DESIGN)),
    )

    assert result.exit_code == 0, result.stdout
    (event,) = _review_events(db_path)
    assert event["design_context"] is True


def test_a_failed_design_records_no_design_context(repo: Path, db_path: Path) -> None:
    _seed_run(db_path, repo)
    _seed_design(db_path, status="failed")

    result = _invoke(repo, db_path, _capturing_runner(_PASS_LINE, []))

    assert result.exit_code == 0, result.stdout
    (event,) = _review_events(db_path)
    assert event["design_context"] is False


def test_an_unreadable_design_file_degrades_loudly(repo: Path, db_path: Path) -> None:
    """An OS error is data, not an exception that costs the run its review."""
    _seed_run(db_path, repo)
    _seed_design(db_path, design_hash=design_content_hash(_DESIGN))
    prompts: list[str] = []

    result = _invoke(
        repo,
        db_path,
        _capturing_runner(_PASS_LINE, prompts),
        "--design-file",
        str(repo / "absent.md"),
    )

    assert result.exit_code == 0, result.stdout
    assert len(prompts) == 1
    assert _DESIGN not in prompts[0]
    assert "does not match" in result.stderr, "a path that was passed but failed is wrong"


def test_the_latest_design_event_is_authoritative(repo: Path, db_path: Path) -> None:
    """``design`` is idempotent-by-append: a re-run's event supersedes the prior one."""
    _seed_run(db_path, repo)
    _seed_design(db_path, design_hash=design_content_hash("stale design"),
                 timestamp="2026-07-26T00:00:00Z")
    _seed_design(db_path, design_hash=design_content_hash(_DESIGN),
                 timestamp="2026-07-26T01:00:00Z")
    prompts: list[str] = []

    result = _invoke(
        repo,
        db_path,
        _capturing_runner(_PASS_LINE, prompts),
        "--design-file",
        str(_write_design_file(repo, _DESIGN)),
    )

    assert result.exit_code == 0, result.stdout
    assert _DESIGN in prompts[0]


def test_a_failed_redesign_supersedes_an_earlier_ok(repo: Path, db_path: Path) -> None:
    """The newest event wins in both directions, so the check cannot be stale."""
    _seed_run(db_path, repo)
    _seed_design(db_path, design_hash=design_content_hash(_DESIGN),
                 timestamp="2026-07-26T00:00:00Z")
    _seed_design(db_path, status="failed", timestamp="2026-07-26T01:00:00Z")
    prompts: list[str] = []

    result = _invoke(
        repo,
        db_path,
        _capturing_runner(_PASS_LINE, prompts),
        "--design-file",
        str(_write_design_file(repo, _DESIGN)),
    )

    assert result.exit_code == 0, result.stdout
    assert _DESIGN not in prompts[0], "the latest attempt produced no design"


# ---------------------------------------------------------------------------
# Refusal ordering — the existing pre-engine refusals still come first
# ---------------------------------------------------------------------------


def test_tripped_breaker_refuses_before_the_design_check(
    repo: Path, db_path: Path
) -> None:
    _seed_run(db_path, repo)
    _seed_reviews(db_path, 5)
    prompts: list[str] = []

    result = _invoke(repo, db_path, _capturing_runner(_PASS_LINE, prompts))

    assert result.exit_code == review_mod.EXIT_BREAKER_TRIPPED
    assert json.loads(result.stdout)["reason"] == REVIEW_CYCLE_CEILING_REASON
    assert prompts == []


def test_the_design_check_precedes_the_gate_evidence_check(
    repo: Path, db_path: Path
) -> None:
    """Root cause first: a missing lifecycle stage outranks a transient tree state.

    Were the order reversed, a red or unreported gate would mask a run that
    skipped the design stage entirely — the orchestrator would fix its gate,
    review again, and only then learn the real problem.
    """
    (repo / "CONTEXT.md").write_text('```yaml\nrepo:\n  name: t\nverify: "true"\n```\n')
    _seed_run(db_path, repo)
    prompts: list[str] = []

    result = _invoke(repo, db_path, _capturing_runner(_PASS_LINE, prompts))

    assert result.exit_code == review_mod.EXIT_GATE_FAILED
    assert json.loads(result.stdout)["reason"] == review_mod.NO_DESIGN_REASON
    assert prompts == []


def test_gate_evidence_still_refuses_once_a_design_is_recorded(
    repo: Path, db_path: Path
) -> None:
    """The design check does not swallow the gate refusal behind it."""
    (repo / "CONTEXT.md").write_text('```yaml\nrepo:\n  name: t\nverify: "true"\n```\n')
    _seed_run(db_path, repo)
    _seed_design(db_path, status="failed")
    prompts: list[str] = []

    result = _invoke(repo, db_path, _capturing_runner(_PASS_LINE, prompts))

    assert result.exit_code == review_mod.EXIT_GATE_FAILED
    assert json.loads(result.stdout)["reason"] == review_mod.NO_GATE_EVIDENCE_REASON
    assert prompts == []


def test_a_wall_clock_trip_also_precedes_the_design_check(
    repo: Path, db_path: Path
) -> None:
    _seed_run(db_path, repo, started_at=datetime.now(UTC) - timedelta(minutes=120))
    prompts: list[str] = []

    result = _invoke(repo, db_path, _capturing_runner(_PASS_LINE, prompts))

    assert result.exit_code == review_mod.EXIT_BREAKER_TRIPPED
    assert prompts == []


# ---------------------------------------------------------------------------
# The pure layer — prompt assembly, hash, and the gate decision
# ---------------------------------------------------------------------------


def test_build_review_prompt_without_a_design_is_the_bare_prompt() -> None:
    assert build_review_prompt(None) == build_review_prompt()
    assert "Design" not in build_review_prompt(None).split("SUBMIT")[0].split("\n")[0]


def test_build_review_prompt_embeds_the_design_verbatim() -> None:
    prompt = build_review_prompt(_DESIGN)
    assert _DESIGN in prompt
    assert prompt.rstrip().endswith(build_review_prompt(None).rstrip()[-40:]), (
        "the SUBMIT contract must stay the last instruction the engine reads"
    )


def test_build_review_prompt_tells_the_engine_the_design_is_a_criterion() -> None:
    prompt = build_review_prompt(_DESIGN).lower()
    assert "design" in prompt
    assert "acceptance criteria" in prompt


def test_design_content_hash_is_sha256_of_the_utf8_text() -> None:
    assert design_content_hash(_DESIGN) == hashlib.sha256(_DESIGN.encode("utf-8")).hexdigest()


def test_the_design_verb_hashes_through_the_shared_helper() -> None:
    """One hash rule, one home — the writer and the verifier cannot drift apart."""
    source = (Path(review_mod.__file__).parent / "design.py").read_text()
    assert "design_content_hash" in source
    assert "hashlib" not in source, "the verb must not re-implement the hash"


def test_resolve_design_gate_refuses_when_no_event_exists() -> None:
    gate = resolve_design_gate(None, None)
    assert gate.refusal_reason == review_mod.NO_DESIGN_REASON
    assert gate.design_markdown is None


def test_resolve_design_gate_passes_a_failed_attempt_without_context() -> None:
    gate = resolve_design_gate({"status": "failed", "reason": "engine_timeout"}, _DESIGN)
    assert gate.refusal_reason is None
    assert gate.design_markdown is None
    assert gate.warning is None


def test_resolve_design_gate_matches_the_recorded_hash() -> None:
    event = {"status": "ok", "design_hash": design_content_hash(_DESIGN)}
    gate = resolve_design_gate(event, _DESIGN)
    assert gate.refusal_reason is None
    assert gate.design_markdown == _DESIGN


def test_resolve_design_gate_drops_context_on_a_hash_mismatch() -> None:
    event = {"status": "ok", "design_hash": design_content_hash(_DESIGN)}
    gate = resolve_design_gate(event, "something else")
    assert gate.refusal_reason is None
    assert gate.design_markdown is None
    assert gate.warning is not None


def test_resolve_design_gate_ignores_the_concurrency_detection_fields() -> None:
    """#236 adds ``invoked_at``/``concurrent_prior_at`` to the payload; the gate
    must resolve exactly as before — added keys never drop design context."""
    event = {
        "status": "ok",
        "design_hash": design_content_hash(_DESIGN),
        "invoked_at": "2026-07-28T00:00:00Z",
        "concurrent_prior_at": "2026-07-28T00:00:02Z",
    }
    gate = resolve_design_gate(event, _DESIGN)
    assert gate.refusal_reason is None
    assert gate.design_markdown == _DESIGN


def test_no_design_is_the_only_refusal_the_design_gate_produces() -> None:
    """Enforcement refuses; context degrades — one refusal, not two."""
    ok = {"status": "ok", "design_hash": design_content_hash(_DESIGN)}
    for event, supplied in (
        (ok, None),
        (ok, "wrong"),
        ({"status": "ok"}, _DESIGN),
        ({"status": "failed"}, _DESIGN),
    ):
        assert resolve_design_gate(event, supplied).refusal_reason is None


def test_resolve_design_gate_is_quiet_when_no_design_was_supplied() -> None:
    """Not supplying one is normal; only a supplied-but-unusable design warns."""
    event = {"status": "ok", "design_hash": design_content_hash(_DESIGN)}
    gate = resolve_design_gate(event, None)
    assert gate.refusal_reason is None
    assert gate.design_markdown is None
    assert gate.warning is None


def test_resolve_design_gate_distrusts_an_ok_event_with_no_recorded_hash() -> None:
    """Fail-safe: an ``ok`` event that cannot authenticate a design is not trusted."""
    gate = resolve_design_gate({"status": "ok"}, _DESIGN)
    assert gate.design_markdown is None
    assert gate.warning is not None


# ---------------------------------------------------------------------------
# The payload contract this verb now reads back out
# ---------------------------------------------------------------------------


def test_the_design_gate_reads_the_keys_the_model_writes() -> None:
    """Writer → reader, end to end: the payload the emitter dumps is readable by
    the gate through the shared key constants.

    Asserts the *consumer* rather than a constant's spelling — the property the
    constants exist for is that one module names the field for both ends, which
    a ``== "$.status"`` assertion never touched (#217).
    """
    payload = DesignEventData(
        run_id="R1",
        status="ok",
        engine="claude",
        model="opus",
        designed_at="2026-07-26T00:00:00Z",
        design_hash=design_content_hash(_DESIGN),
    ).model_dump(exclude_none=True)

    assert DESIGN_STATUS_KEY in payload
    assert DESIGN_HASH_KEY in payload
    assert resolve_design_gate(payload, _DESIGN).design_markdown == _DESIGN
