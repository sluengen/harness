"""``harness design`` adopts a prior design on a resumed run — #258 (ADR 0008 D1).

A reclaimed ticket re-picked with ``start --resume`` mints a new ``run_id``, and
``review``'s design gate is run-scoped — so the resumed run had to re-pay for an
Opus call producing a design that was already on the ticket, and was handed
working code it was then forbidden to see. ADR 0008's fix is not to widen the
gate: the resumed run records its **own** ``design`` event, marked
``inherited_from``, recovering the design *text* from the ticket comment.

AC-1: an adopted event is ``status='ok'`` with ``inherited_from`` and the
      source's ``design_hash`` / ``grounded_sha``, asserted field by field.
AC-2: **no engine subprocess is spawned** — asserted at the runner seam.
AC-3: no comment is posted.
AC-5: each of the five decline conditions runs the engine instead.

The adopt path is fail-safe toward the status quo: declining costs one Opus
call, wrongly adopting hands the session a design for code that is not there.
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

from harness.cli import app, design_protocol
from harness.cli import design as design_mod
from harness.cli import design_tracker as design_tracker_mod
from harness.cli.design_protocol import design_content_hash
from harness.design_marker import format_design_comment
from harness.state import store
from tests._asyncutil import run_sync

cli_runner = CliRunner()

_TICKET = "258"
_RUN_ID = "01JRESUMEDRUNXXXXXXXXXXX01"
_SOURCE_RUN_ID = "01JSOURCERUNXXXXXXXXXXXX01"
_WIP_BRANCH = f"harness/{_SOURCE_RUN_ID}"

_PRIOR_DESIGN = "### Data model\n\nThe design the dead run produced.\n"
_PRIOR_HASH = design_content_hash(_PRIOR_DESIGN)
_PRIOR_GROUNDED_SHA = "a" * 40

# No trailing newline: a design collected from either channel is normalized
# (trimmed), so a fixture carrying one would not round-trip to its own hash.
_FRESH_DESIGN = "### Data model\n\nA freshly engineered design."


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


async def _insert_run(
    db_path: Path,
    run_id: str,
    worktree_path: str,
    *,
    status: str,
    resumed_from: str | None,
) -> None:
    await store.init_db(db_path)
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO runs ("
            "run_id, workflow_name, workflow_version, status, state_json, "
            "inputs_json, base_branch, worktree_path, worktree_branch, ticket, "
            "started_at, resumed_from, assurance"
            # #352: ``complex`` — adoption is a *design* path, so it only arises
            # on a run whose assurance requires the stage. A run that requires no
            # design has nothing to adopt, which is asserted in
            # ``test_design_assurance.py`` rather than by neutering this suite.
            ") VALUES (?, '', 0, ?, '{}', '{}', 'dev', ?, ?, ?, ?, ?, 'complex')",
            (
                run_id,
                status,
                worktree_path,
                f"harness/{run_id}",
                _TICKET,
                datetime.now(UTC).isoformat(),
                resumed_from,
            ),
        )
        await conn.commit()


def _seed_resumed_run(db_path: Path, repo: Path, *, resumed_from: str | None = _WIP_BRANCH) -> None:
    """The run under test: open, worktree == repo, resumed (or not) as given."""
    run_sync(_insert_run(db_path, _RUN_ID, str(repo), status="open", resumed_from=resumed_from))


async def _insert_design_event(db_path: Path, run_id: str, data: dict[str, Any]) -> None:
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO events (run_id, event_type, timestamp, data_json) "
            "VALUES (?, 'design', ?, ?)",
            (run_id, datetime.now(UTC).isoformat(), json.dumps(data)),
        )
        await conn.commit()


def _seed_source_design(
    db_path: Path,
    *,
    status: str = "ok",
    design_hash: str | None = _PRIOR_HASH,
) -> None:
    """A closed predecessor run for the same ticket, carrying its design event."""
    run_sync(
        _insert_run(
            db_path, _SOURCE_RUN_ID, "/gone", status="closed", resumed_from=None
        )
    )
    data: dict[str, Any] = {
        "run_id": _SOURCE_RUN_ID,
        "status": status,
        "engine": "claude",
        "model": "opus",
        "designed_at": "2026-07-29T10:00:00Z",
        # Carried on **both** shapes deliberately. A real ``failed`` event has no
        # ``design_hash`` — but seeding it that way makes the failed-source test
        # decline on the *hash* clause and prove nothing about the status one
        # (mutation-checked: dropping ``status='ok'`` from the query left the
        # suite green until this fixture supplied the hash on both shapes).
        "design_hash": design_hash,
        "grounded_sha": _PRIOR_GROUNDED_SHA,
    }
    if status != "ok":
        data["reason"] = "engine_timeout"
        data["detail"] = "killed"
    run_sync(_insert_design_event(db_path, _SOURCE_RUN_ID, data))


async def _fetch_design_events(db_path: Path) -> list[dict[str, Any]]:
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            "SELECT run_id, data_json, duration_ms FROM events "
            "WHERE event_type = 'design' ORDER BY id"
        ) as cur,
    ):
        rows = await cur.fetchall()
    return [
        # ``duration_ms`` is the event **column** (#264). Widening the dict is
        # non-breaking: every existing caller indexes ``["data"]`` / ``["run_id"]``.
        {
            "run_id": r[0],
            "data": json.loads(r[1]),
            "duration_ms": None if r[2] is None else int(r[2]),
        }
        for r in rows
    ]


def design_events(db_path: Path) -> list[dict[str, Any]]:
    return run_sync(_fetch_design_events(db_path))


def _prior_comment(design: str = _PRIOR_DESIGN, *, design_hash: str = _PRIOR_HASH) -> str:
    return format_design_comment(
        _SOURCE_RUN_ID,
        design,
        design_hash=design_hash,
        grounded_sha=_PRIOR_GROUNDED_SHA,
        when="2026-07-29T10:00:00Z",
    )


class _EngineSpy:
    """A runner that records every invocation — AC-2's measuring instrument.

    AC-2 requires zero engine invocations to be *asserted at the seam*, not
    inferred from timing or from the absence of engine-shaped output. This
    counts, and returns a design distinguishable from the prior one so a test
    can tell "adopted" from "re-designed" by content alone.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, *, cmd: list[str], **kwargs: Any) -> design_mod.RunResult:
        self.calls += 1
        # The design leaves on the file channel since #294; writing it is what
        # makes a *declined* adoption reach a normal ``ok`` event rather than
        # degrading, so this spy tells "adopted" from "re-designed" by content.
        out = (
            Path(cmd[cmd.index("--add-dir") + 1]) / design_protocol.DESIGN_OUT_FILENAME
        )
        out.write_text(_FRESH_DESIGN, encoding="utf-8")
        return design_mod.RunResult(stdout="", stderr="", returncode=0)


def _tracker_stub(design_comment: str | None) -> Any:
    stub = mock.MagicMock()
    stub.fetch_issue = mock.AsyncMock(
        return_value={"title": "t", "description": "d", "labels": []}
    )
    stub.post_comment = mock.AsyncMock(return_value=None)
    stub.fetch_design_comment = mock.AsyncMock(return_value=design_comment)
    return stub


def _invoke(repo: Path, db_path: Path, runner: Any, stub: Any) -> Any:
    argv = [
        "design", "--repo", str(repo), "--db", str(db_path),
        "--run-id", _RUN_ID, "--json",
    ]
    with (
        mock.patch.object(design_mod, "_default_runner", runner),
        mock.patch.object(design_tracker_mod, "tracker_client", return_value=stub),
    ):
        return cli_runner.invoke(app, argv)


# ---------------------------------------------------------------------------
# AC-1 / AC-2 / AC-3 — the adopt path
# ---------------------------------------------------------------------------


def test_adopts_the_prior_design_field_by_field(repo: Path, db_path: Path) -> None:
    """AC-1: the adopted event carries the source's provenance verbatim.

    ``grounded_sha`` is the source's, **not** the resumed HEAD: the design was
    grounded where it was grounded, and re-stamping it would record a study that
    never happened. ``status`` stays ``'ok'`` so ``resolve_design_gate`` reads it
    as a usable design rather than a failed attempt.
    """
    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path)
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine, _tracker_stub(_prior_comment()))

    assert result.exit_code == 0, result.output
    events = design_events(db_path)
    adopted = [e for e in events if e["run_id"] == _RUN_ID]
    assert len(adopted) == 1
    data = adopted[0]["data"]
    assert data["run_id"] == _RUN_ID
    assert data["status"] == "ok"
    assert data["inherited_from"] == _SOURCE_RUN_ID
    assert data["design_hash"] == _PRIOR_HASH
    assert data["grounded_sha"] == _PRIOR_GROUNDED_SHA
    assert data["grounded_sha"] != _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert data["engine"] == "claude"
    assert data["model"] == "opus"
    assert "reason" not in data


def test_adopt_spawns_no_engine_subprocess(repo: Path, db_path: Path) -> None:
    """AC-2: zero engine invocations — the saving the whole ticket exists for."""
    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path)
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine, _tracker_stub(_prior_comment()))

    assert result.exit_code == 0, result.output
    assert engine.calls == 0


def test_adopt_posts_no_comment(repo: Path, db_path: Path) -> None:
    """AC-3: the design is already on the ticket; a second copy would fork it."""
    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path)
    stub = _tracker_stub(_prior_comment())

    result = _invoke(repo, db_path, _EngineSpy(), stub)

    assert result.exit_code == 0, result.output
    stub.post_comment.assert_not_awaited()


def test_adopt_emits_the_recovered_design_as_normal_design_output(
    repo: Path, db_path: Path
) -> None:
    """The orchestrator's Step 1.5 handling is unchanged: same ``DesignOutput``
    shape, carrying the recovered text so the session builds against it."""
    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path)

    result = _invoke(repo, db_path, _EngineSpy(), _tracker_stub(_prior_comment()))

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["design_markdown"] == _PRIOR_DESIGN
    assert payload["design_hash"] == _PRIOR_HASH
    assert payload["grounded_sha"] == _PRIOR_GROUNDED_SHA
    assert payload["status"] == "ok"
    assert payload["run_id"] == _RUN_ID
    # No new key on the printed contract (#258 out of scope: stdout is unchanged).
    assert "inherited_from" not in payload


# ---------------------------------------------------------------------------
# AC-4 — end to end: an adopted design reaches the review engine
# ---------------------------------------------------------------------------


def test_an_adopted_design_satisfies_review_and_reaches_its_engine(
    repo: Path, db_path: Path
) -> None:
    """AC-4: adopt → ``review --design-file`` behaves exactly like a designed run.

    The whole chain in one test, because the halves are individually plausible
    and jointly the point: the gate must not refuse ``no_design`` (the event
    exists on *this* run, so no query was widened), and the review must record
    that it actually saw the design (``design_context`` true, no reason) — which
    it can only do if the adopted event carries a ``design_hash`` the recovered
    text authenticates against.
    """
    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path)

    designed = _invoke(repo, db_path, _EngineSpy(), _tracker_stub(_prior_comment()))
    assert designed.exit_code == 0, designed.output
    design_file = repo / "design.md"
    design_file.write_text(json.loads(designed.stdout)["design_markdown"])

    reviewed = _invoke_review(repo, db_path, design_file)

    assert reviewed.exit_code == 0, reviewed.stdout
    (event,) = _review_events(db_path)
    assert event["design_context"] is True
    assert "design_context_reason" not in event


def test_adoption_records_only_a_design_event_leaving_the_budget_untouched(
    repo: Path, db_path: Path
) -> None:
    """Budget is run-scoped even though certification is not (ADR 0008).

    A reader who took "carry the design forward" as "carry the run's state
    forward" would also carry the predecessor's burnt review cycles and its
    wall-clock window — precisely the wedge ``commands/harness.md`` warns about
    under *Recovering from a breaker trip*. Adoption inherits one design event
    and nothing else.
    """
    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path)
    run_sync(
        _insert_review_event(db_path, _SOURCE_RUN_ID)
    )  # the predecessor had burnt a cycle

    result = _invoke(repo, db_path, _EngineSpy(), _tracker_stub(_prior_comment()))

    assert result.exit_code == 0, result.output
    assert _event_types(db_path, _RUN_ID) == ["design"]


async def _insert_review_event(db_path: Path, run_id: str) -> None:
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO events (run_id, event_type, timestamp, data_json) "
            "VALUES (?, 'review', ?, ?)",
            (
                run_id,
                "2026-07-29T11:00:00Z",
                json.dumps({"verdict": "fail", "reviewed_sha": "deadbeef"}),
            ),
        )
        await conn.commit()


def _event_types(db_path: Path, run_id: str) -> list[str]:
    async def _fetch() -> list[str]:
        async with (
            store.connect(db_path) as conn,
            conn.execute(
                "SELECT event_type FROM events WHERE run_id = ? ORDER BY id", (run_id,)
            ) as cur,
        ):
            return [str(r[0]) for r in await cur.fetchall()]

    return run_sync(_fetch())


def _review_events(db_path: Path) -> list[dict[str, Any]]:
    async def _fetch() -> list[dict[str, Any]]:
        async with (
            store.connect(db_path) as conn,
            conn.execute(
                "SELECT data_json FROM events WHERE event_type = 'review'"
            ) as cur,

        ):
            rows = await cur.fetchall()
        return [json.loads(r[0]) for r in rows]

    return run_sync(_fetch())


def _invoke_review(repo: Path, db_path: Path, design_file: Path) -> Any:
    from harness.cli import review as review_mod

    async def _runner(**kwargs: Any) -> Any:
        return review_mod.RunResult(
            stdout='SUBMIT: {"verdict": "pass", "issues": []}\n', stderr="", returncode=0
        )

    with mock.patch.object(review_mod, "_default_runner", _runner):
        return cli_runner.invoke(
            app,
            [
                "review", "--repo", str(repo), "--db", str(db_path),
                "--run-id", _RUN_ID, "--json", "--design-file", str(design_file),
            ],
        )


# ---------------------------------------------------------------------------
# AC-5 — the five decline conditions, each running the engine instead
# ---------------------------------------------------------------------------


def test_declines_when_the_run_did_not_resume(repo: Path, db_path: Path) -> None:
    """AC-5 (F2): a clean start re-designs even though the ticket carries a design.

    The tree that design described is gone, so inheriting it would hand the
    session a design for code that no longer exists.
    """
    _seed_resumed_run(db_path, repo, resumed_from=None)
    _seed_source_design(db_path)
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine, _tracker_stub(_prior_comment()))

    assert result.exit_code == 0, result.output
    assert engine.calls == 1
    data = [e for e in design_events(db_path) if e["run_id"] == _RUN_ID][0]["data"]
    assert "inherited_from" not in data
    assert data["design_hash"] == design_content_hash(_FRESH_DESIGN)


def test_an_adopted_event_records_no_output_channel(
    repo: Path, db_path: Path
) -> None:
    """No engine ran, so there is no channel to name (#294).

    ``channel`` exists to say how *this* invocation's engine delivered its
    design. An adoption ran none — it recovered the design from the ticket — so
    recording ``'file'`` would assert a write that never happened, and recording
    ``'stdout'`` would raise a permission alarm out of nothing.
    """
    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path)

    result = _invoke(repo, db_path, _EngineSpy(), _tracker_stub(_prior_comment()))

    assert result.exit_code == 0, result.output
    data = [e for e in design_events(db_path) if e["run_id"] == _RUN_ID][0]["data"]
    assert data["inherited_from"], "this test is only meaningful on the adopt path"
    assert "channel" not in data
    assert "design_chars" not in data


def test_declines_when_the_ticket_carries_no_design_comment(
    repo: Path, db_path: Path
) -> None:
    """AC-5: nothing to recover — the resumed run designs from scratch."""
    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path)
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine, _tracker_stub(None))

    assert result.exit_code == 0, result.output
    assert engine.calls == 1


def test_declines_when_the_comment_body_was_edited(repo: Path, db_path: Path) -> None:
    """AC-5: an edited design no longer hashes to what the comment claims.

    The authentication ADR 0008 requires of the writing verb: a comment is
    mutable, so the recovered text is re-hashed rather than trusted.
    """
    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path)
    tampered = _prior_comment("### Data model\n\nSomeone edited this.\n")
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine, _tracker_stub(tampered))

    assert result.exit_code == 0, result.output
    assert engine.calls == 1


def test_declines_when_no_ok_ledger_event_matches_the_hash(
    repo: Path, db_path: Path
) -> None:
    """AC-5: adoption rests on a **recorded** design, not on comment text alone.

    ADR 0008 clause (a): the assertion must be verifiable from another recorded
    event. A comment can be edited (hash and all); a ledger event cannot.
    """
    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path, design_hash="f" * 64)  # ledger records a different design
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine, _tracker_stub(_prior_comment()))

    assert result.exit_code == 0, result.output
    assert engine.calls == 1


def test_declines_when_the_source_design_attempt_failed(
    repo: Path, db_path: Path
) -> None:
    """AC-5: a ``failed`` attempt satisfies *enforcement*, but is not a design.

    ADR 0007 D4 lets a failed attempt open the ``no_design`` gate; that is a
    statement about enforcement, not about there being something to inherit.
    """
    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path, status="failed")
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine, _tracker_stub(_prior_comment()))

    assert result.exit_code == 0, result.output
    assert engine.calls == 1


def test_declines_when_the_comment_states_no_hash(repo: Path, db_path: Path) -> None:
    """A design comment whose provenance header lost its ``design_hash`` clause
    cannot be authenticated, so it is not adopted — the parser reports the claim
    as absent rather than guessing one."""
    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path)
    header, sep, body = _prior_comment().partition("\n\n---\n\n")
    stripped = header.replace(f" (design_hash `{_PRIOR_HASH}`)", "") + sep + body
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine, _tracker_stub(stripped))

    assert result.exit_code == 0, result.output
    assert engine.calls == 1


def test_adoption_never_inherits_from_another_ticket(repo: Path, db_path: Path) -> None:
    """A design event matching the hash but recorded against a **different**
    ticket is not an adoption source — inheritance follows the change spec."""
    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path)
    run_sync(_reassign_ticket(db_path, _SOURCE_RUN_ID, "999"))
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine, _tracker_stub(_prior_comment()))

    assert result.exit_code == 0, result.output
    assert engine.calls == 1


async def _reassign_ticket(db_path: Path, run_id: str, ticket: str) -> None:
    async with store.connect(db_path) as conn:
        await conn.execute("UPDATE runs SET ticket = ? WHERE run_id = ?", (ticket, run_id))
        await conn.commit()


def test_a_re_run_does_not_inherit_from_its_own_adopted_event(
    repo: Path, db_path: Path
) -> None:
    """``design`` is idempotent by re-run, so the adopt path must be too.

    Without excluding this run from the source query, the second invocation
    would find the event the *first* one adopted and name this run as its own
    source — a self-referential provenance that says nothing. It re-adopts from
    the real predecessor instead.
    """
    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path)
    stub = _tracker_stub(_prior_comment())

    first = _invoke(repo, db_path, _EngineSpy(), stub)
    second = _invoke(repo, db_path, _EngineSpy(), stub)

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    adopted = [e["data"] for e in design_events(db_path) if e["run_id"] == _RUN_ID]
    assert len(adopted) == 2
    assert [e["inherited_from"] for e in adopted] == [_SOURCE_RUN_ID, _SOURCE_RUN_ID]


def test_a_tracker_failure_declines_rather_than_wedging_the_run(
    repo: Path, db_path: Path
) -> None:
    """Reading the prior design is best-effort: a tracker outage costs the
    adoption, never the run — the engine runs, exactly as before #258."""
    from harness.tracker_errors import TrackerRequestError

    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path)
    stub = _tracker_stub(None)
    stub.fetch_design_comment = mock.AsyncMock(side_effect=TrackerRequestError("502"))
    engine = _EngineSpy()

    result = _invoke(repo, db_path, engine, stub)

    assert result.exit_code == 0, result.output
    assert engine.calls == 1


# ---------------------------------------------------------------------------
# #264 — an adopted design records no duration, never a negative one
# ---------------------------------------------------------------------------


def test_adopted_design_records_no_duration(repo: Path, db_path: Path) -> None:
    """An adopted event's ``duration_ms`` is NULL — never a negative number.

    This is the one place the mechanical "duration = designed_at - invoked_at"
    rule goes wrong, and it goes wrong *silently*. On an adoption the two
    instants describe different runs: ``invoked_at`` is **this** run's, while
    ``designed_at`` is carried verbatim from the source (``design_adopt`` keeps
    every field describing the design as the source's). Subtracting them
    measures backwards from this invocation to a design produced earlier, so the
    value is negative — a latency no engine ever spent.

    Absence is the honest record: no design was produced here, and
    ``inherited_from`` already marks the row for a reader that wants to
    attribute it to its source.
    """
    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path)

    result = _invoke(repo, db_path, _EngineSpy(), _tracker_stub(_prior_comment()))

    assert result.exit_code == 0, result.output
    (adopted,) = [e for e in design_events(db_path) if e["run_id"] == _RUN_ID]
    assert adopted["data"]["inherited_from"] == _SOURCE_RUN_ID
    assert adopted["duration_ms"] is None


def test_no_design_event_records_a_negative_duration(
    repo: Path, db_path: Path
) -> None:
    """No recorded design latency is negative, whatever path wrote it.

    Stated as the property rather than as a special case, so a future refactor
    that drops the adoption guard fails here loudly instead of quietly writing a
    negative sample into the ledger item 5 aggregates.
    """
    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path)

    _invoke(repo, db_path, _EngineSpy(), _tracker_stub(_prior_comment()))

    durations = [e["duration_ms"] for e in design_events(db_path)]
    assert all(d is None or d >= 0 for d in durations), durations
