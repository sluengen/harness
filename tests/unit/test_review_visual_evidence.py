"""#361 — ``harness review --screenshot-dir``, wired through the verb.

What the pure resolver decides is proven in
``test_review_visual_resolution.py``; what this module measures is that the verb
is wired to that decision and to nothing else — and, for the two refusals, that
each fires **before an engine is spawned**. "Refuses" and "refuses without
spending an engine call" are different claims, and only the second is the one
this channel makes: a refusal that arrives after the engine ran has already paid
for the review it was supposed to prevent.

The engine seam is a recording stub, so "no engine was spawned" is asserted at
the seam rather than inferred from output shape (the precedent
``_default_probe_runner``'s docstring states).

**Placement.** The invocation check sits before the inherit short-circuit, which
is a deliberate deviation from ``--design-file``'s position at step 1b. The codex
refusal is decided from argv alone, and a refusal an unrelated short-circuit can
skip is one whose test is defeated by putting the caller into an inherit-eligible
state — reachable in normal operation, since a resumed WIP branch is exactly what
inheritance is for. ``test_codex_with_screenshots_is_refused_even_on_an_inheritable_run``
measures that, and its control
(``test_the_inheritable_setup_really_does_inherit_without_screenshots``) is what
stops it passing because the setup was never inheritable in the first place.
"""

from __future__ import annotations

import inspect
import json
import subprocess
import unittest.mock as mock
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.models import OptionInfo
from typer.testing import CliRunner

from harness.cli import app
from harness.cli import review as review_mod
from harness.cli.review_visual import MANIFEST_FILENAME, MAX_SCREENSHOTS
from harness.state import store
from tests._asyncutil import run_sync
from tests._ledger import seed_design_event

cli_runner = CliRunner()

_RUN_ID = "01JREVIEWVISUALXXXXXXXXX01"
_SOURCE_RUN_ID = "01JREVIEWVISUALSRCXXXXXX01"
_TICKET = "361"
_PASS_LINE = 'SUBMIT: {"verdict": "pass", "issues": []}'

#: The verify-gate evidence a green gate records — what a source run's review
#: wrote, and what an inherited event must carry or ``close`` refuses it.
_SOURCE_GATE_EVIDENCE: dict[str, Any] = {
    "gate_ran": True,
    "gate_command": "bash scripts/verify.sh",
    "gate_exit_code": 0,
    "gate_output_tail": "3145 passed",
}


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture(autouse=True)
def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path / "allowed"))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo whose capture directory and gate log are **gitignored**.

    That is load-bearing rather than tidiness: the inherit short-circuit declines
    on a dirty worktree, so captures written as untracked files would make every
    run in this module un-inheritable and the placement test below would pass for
    a reason that has nothing to do with placement. ``git status --porcelain``
    excludes ignored paths, so ignoring them keeps the tree genuinely clean while
    the captures stay inside the mount, where the channel requires them.
    """
    repo_root = tmp_path / "allowed" / "repo"
    repo_root.mkdir(parents=True)
    _git(repo_root, "init", "-b", "dev")
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    (repo_root / ".gitignore").write_text(
        ".harness/\n.worktrees/\ngate.log\ncaptures/\n"
    )
    (repo_root / "README.md").write_text("hello\n")
    _git(repo_root, "add", ".gitignore", "README.md")
    _git(repo_root, "commit", "-m", "initial")
    return repo_root


@pytest.fixture
def db_path(repo: Path) -> Path:
    return repo / ".harness" / "harness.db"


@pytest.fixture
def gate_log(repo: Path) -> Path:
    path = repo / "gate.log"
    path.write_text("=== pytest ===\n42 passed\n")
    return path


def _capture_dir(repo: Path, name: str) -> Path:
    path = repo / "captures" / name
    path.mkdir(parents=True)
    return path


@pytest.fixture
def captures(repo: Path) -> Path:
    """Three captures and a manifest, inside the workspace — the S1 shape."""
    shots = _capture_dir(repo, "shots")
    for name in ("index-1440.png", "index-390.png", "settings-1440.png"):
        (shots / name).write_bytes(b"\x89PNG\x00")
    (shots / "manifest.md").write_text("index @ 1440/390, settings @ 1440; sha HEAD\n")
    return shots


async def _insert_run(
    db_path: Path,
    run_id: str,
    worktree_path: str,
    *,
    status: str = "open",
    resumed_from: str | None = None,
) -> None:
    await store.init_db(db_path)
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO runs ("
            "run_id, workflow_name, workflow_version, status, state_json, "
            "inputs_json, base_branch, worktree_path, worktree_branch, ticket, "
            "started_at, resumed_from, assurance"
            ") VALUES (?, '', 0, ?, '{}', '{}', 'dev', ?, ?, ?, ?, ?, 'simple')",
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


def _seed_run(db_path: Path, repo: Path, *, resumed_from: str | None = None) -> None:
    run_sync(_insert_run(db_path, _RUN_ID, str(repo), resumed_from=resumed_from))


def _seed_source_pass(db_path: Path, reviewed_sha: str) -> None:
    """A closed predecessor whose gate-evidenced pass covers ``reviewed_sha``."""
    run_sync(_insert_run(db_path, _SOURCE_RUN_ID, "/gone", status="closed"))

    async def _insert() -> None:
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO events (run_id, event_type, timestamp, data_json) "
                "VALUES (?, 'review', ?, ?)",
                (
                    _SOURCE_RUN_ID,
                    datetime.now(UTC).isoformat(),
                    json.dumps(
                        {
                            "run_id": _SOURCE_RUN_ID,
                            "reviewed_sha": reviewed_sha,
                            "verdict": "pass",
                            "issues": [],
                            "engine": "claude",
                            "convergence_check_required": False,
                            "created_at": "2026-08-14T10:00:00Z",
                            "design_context": True,
                            **_SOURCE_GATE_EVIDENCE,
                        }
                    ),
                ),
            )
            await conn.commit()

    run_sync(_insert())


class _EngineSpy:
    """Records every invocation; the instrument for "no engine was spawned"."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def __call__(
        self,
        *,
        cmd: list[str],
        stdin: str,
        env: dict[str, str],
        cwd: Path | None,
        timeout: float | None = None,
    ) -> review_mod.RunResult:
        self.prompts.append(stdin)
        return review_mod.RunResult(stdout=_PASS_LINE, stderr="", returncode=0)


def _invoke(
    repo: Path,
    db_path: Path,
    gate_log: Path,
    spy: _EngineSpy,
    *extra: str,
) -> Any:
    with mock.patch.object(review_mod, "_default_runner", spy):
        return cli_runner.invoke(
            app,
            [
                "review",
                "--repo", str(repo),
                "--db", str(db_path),
                "--run-id", _RUN_ID,
                "--gate-exit", "0",
                "--gate-log", str(gate_log),
                "--json",
                *extra,
            ],
        )


def _events(db_path: Path) -> list[dict[str, Any]]:
    async def _fetch() -> list[dict[str, Any]]:
        async with (
            store.connect(db_path) as conn,
            conn.execute(
                "SELECT data_json FROM events WHERE event_type = 'review' "
                "AND run_id = ? ORDER BY id",
                (_RUN_ID,),
            ) as cur,
        ):
            rows = await cur.fetchall()
        return [json.loads(r[0]) for r in rows]

    return run_sync(_fetch())


def _only_event(db_path: Path) -> dict[str, Any]:
    (event,) = _events(db_path)
    return event


# --- T5 / AC-2: the workspace refusal, before any spawn ----------------------


def test_a_screenshot_dir_outside_the_workspace_refuses_before_the_engine(
    repo: Path, db_path: Path, gate_log: Path, tmp_path: Path
) -> None:
    """AC-2. Killer: moving the check below ``_invoke_engine``.

    The directory is a perfectly real one holding a perfectly real capture — it
    is simply somewhere the container was never given, which is the host-only
    ``/tmp`` path this refusal exists for.
    """
    outside = tmp_path / "outside-the-workspace"
    outside.mkdir()
    (outside / "a.png").write_bytes(b"\x89PNG\x00")
    _seed_run(db_path, repo)
    spy = _EngineSpy()

    result = _invoke(repo, db_path, gate_log, spy, "--screenshot-dir", str(outside))

    assert result.exit_code == review_mod.EXIT_GATE_FAILED, result.output
    assert json.loads(result.stdout)["reason"] == (
        review_mod.SCREENSHOT_DIR_OUTSIDE_WORKSPACE_REASON
    )
    assert spy.prompts == [], "the refusal must precede any engine invocation"
    assert "verdict" not in _only_event(db_path)


def test_more_captures_than_the_cap_refuses_before_the_engine(
    repo: Path, db_path: Path, gate_log: Path
) -> None:
    """S9. The cap refuses rather than truncating, and it does so pre-engine."""
    shots = _capture_dir(repo, "many")
    for i in range(13):
        (shots / f"cap-{i:02d}.png").write_bytes(b"\x89PNG\x00")
    _seed_run(db_path, repo)
    spy = _EngineSpy()

    result = _invoke(repo, db_path, gate_log, spy, "--screenshot-dir", str(shots))

    assert result.exit_code == review_mod.EXIT_GATE_FAILED, result.output
    assert json.loads(result.stdout)["reason"] == review_mod.TOO_MANY_SCREENSHOTS_REASON
    assert spy.prompts == []


# --- T6 / AC-3: the codex refusal --------------------------------------------


def test_codex_with_screenshots_is_refused_rather_than_degraded(
    repo: Path, db_path: Path, gate_log: Path, captures: Path
) -> None:
    """AC-3. Killer A: deleting the check.

    With the check gone the stub returns a ``pass`` and this run records a
    verdict — which is the precise failure the refusal exists to prevent, a pass
    that reads as though the reviewer looked at a rendering codex cannot see. So
    the assertion is not merely the exit code: the recorded event must carry **no
    verdict**.
    """
    _seed_run(db_path, repo)
    spy = _EngineSpy()

    result = _invoke(
        repo, db_path, gate_log, spy,
        "--engine", "codex", "--screenshot-dir", str(captures),
    )

    assert result.exit_code == review_mod.EXIT_GATE_FAILED, result.output
    assert json.loads(result.stdout)["reason"] == (
        review_mod.SCREENSHOTS_UNSUPPORTED_ENGINE_REASON
    )
    assert spy.prompts == []
    event = _only_event(db_path)
    assert "verdict" not in event, "a refusal must not record a shippable pass"


def test_claude_with_the_same_captures_proceeds_to_a_verdict(
    repo: Path, db_path: Path, gate_log: Path, captures: Path
) -> None:
    """T6's control (killer C): a check that refuses on captures regardless of
    engine passes the test above for the wrong reason. The refusal is engine x
    flag, and this is the other side of the product."""
    _seed_run(db_path, repo)
    spy = _EngineSpy()

    result = _invoke(repo, db_path, gate_log, spy, "--screenshot-dir", str(captures))

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["verdict"] == "pass"
    assert len(spy.prompts) == 1
    assert str(captures / "index-1440.png") in spy.prompts[0]


def test_codex_without_screenshots_is_unaffected(
    repo: Path, db_path: Path, gate_log: Path
) -> None:
    """S10 — the refusal is not "codex reviews are refused"."""
    _seed_run(db_path, repo)
    spy = _EngineSpy()

    result = _invoke(repo, db_path, gate_log, spy, "--engine", "codex")

    assert result.exit_code == 0, result.output
    assert len(spy.prompts) == 1


# --- T6' : the placement, and its control ------------------------------------


def _seed_inheritable(db_path: Path, repo: Path) -> None:
    """A run that ``resolve_inheritance`` accepts: resumed, clean, SHA-matched."""
    _seed_run(db_path, repo, resumed_from=f"harness/{_SOURCE_RUN_ID}")
    seed_design_event(db_path, _RUN_ID)
    _seed_source_pass(db_path, _git(repo, "rev-parse", "HEAD").stdout.strip())


def test_the_inheritable_setup_really_does_inherit_without_screenshots(
    repo: Path, db_path: Path, gate_log: Path
) -> None:
    """T6's control (killer B, first half).

    Without this, the placement test below passes whenever the setup happens not
    to be inheritable — which is to say it would measure nothing at all. Here the
    short-circuit fires: no engine runs and the event names its source.
    """
    _seed_inheritable(db_path, repo)
    spy = _EngineSpy()

    result = _invoke(repo, db_path, gate_log, spy)

    assert result.exit_code == 0, result.output
    assert spy.prompts == [], "an inherited pass runs no engine"
    assert _only_event(db_path)["inherited_from"] == _SOURCE_RUN_ID


def test_codex_with_screenshots_is_refused_even_on_an_inheritable_run(
    repo: Path, db_path: Path, gate_log: Path, captures: Path
) -> None:
    """T6' — killer B: moving the check below the inherit short-circuit.

    On exactly the setup the control above proves inheritable, the combination
    still refuses. Without this test the placement is untested: T6 alone passes
    with the check anywhere before the engine, and a caller on a resumed WIP
    branch would then inherit a pass while claiming visual evidence codex could
    never have read.
    """
    _seed_inheritable(db_path, repo)
    spy = _EngineSpy()

    result = _invoke(
        repo, db_path, gate_log, spy,
        "--engine", "codex", "--screenshot-dir", str(captures),
    )

    assert result.exit_code == review_mod.EXIT_GATE_FAILED, result.output
    assert json.loads(result.stdout)["reason"] == (
        review_mod.SCREENSHOTS_UNSUPPORTED_ENGINE_REASON
    )
    assert spy.prompts == []
    event = _only_event(db_path)
    assert "verdict" not in event
    assert "inherited_from" not in event, "the refusal must precede the short-circuit"


# --- T9 / AC-1a: the four event fields, each with its own exclusive killer ----


def test_captures_and_a_manifest_record_all_four_fields(
    repo: Path, db_path: Path, gate_log: Path, captures: Path
) -> None:
    """The success row. ``visual_count`` is asserted at exactly 3 — a fixture size
    chosen so a hardcoded ``0``/``1`` and an off-by-one both die here."""
    _seed_run(db_path, repo)
    spy = _EngineSpy()

    result = _invoke(repo, db_path, gate_log, spy, "--screenshot-dir", str(captures))

    assert result.exit_code == 0, result.output
    event = _only_event(db_path)
    assert event["visual_context"] is True
    assert event["visual_count"] == 3
    assert event["visual_manifest"] is True
    assert "visual_context_reason" not in event, (
        "a success records no reason — the rule design_context_reason documents"
    )


def test_captures_without_a_manifest_record_visual_manifest_false(
    repo: Path, db_path: Path, gate_log: Path, captures: Path
) -> None:
    """The case that makes ``visual_manifest`` non-vacuous.

    Without it, an implementation hardcoding ``True`` survives every other
    assertion in this module. Killer: hardcoding ``True``, or dropping the
    ``manifest is not None`` test.
    """
    (captures / "manifest.md").unlink()
    _seed_run(db_path, repo)
    spy = _EngineSpy()

    result = _invoke(repo, db_path, gate_log, spy, "--screenshot-dir", str(captures))

    assert result.exit_code == 0, result.output
    event = _only_event(db_path)
    assert event["visual_context"] is True
    assert event["visual_count"] == 3
    assert event["visual_manifest"] is False


def test_no_screenshot_dir_records_not_supplied_and_omits_the_scoping_fields(
    repo: Path, db_path: Path, gate_log: Path
) -> None:
    """The absence row.

    ``visual_manifest`` and ``visual_count`` are **absent**, not ``False``/``0``:
    a value there would assert something about a channel that was not used — the
    argument ``probe_second_pass`` already makes. Killer: defaulting either onto
    every row; hardcoding ``visual_context=True``.
    """
    _seed_run(db_path, repo)
    spy = _EngineSpy()

    result = _invoke(repo, db_path, gate_log, spy)

    assert result.exit_code == 0, result.output
    event = _only_event(db_path)
    assert event["visual_context"] is False
    assert event["visual_context_reason"] == "not_supplied"
    assert "visual_count" not in event
    assert "visual_manifest" not in event


def test_an_empty_capture_directory_records_no_images(
    repo: Path, db_path: Path, gate_log: Path
) -> None:
    """Killer: hardcoding one reason value — this and ``not_supplied`` differ."""
    shots = _capture_dir(repo, "empty-shots")
    _seed_run(db_path, repo)
    spy = _EngineSpy()

    result = _invoke(repo, db_path, gate_log, spy, "--screenshot-dir", str(shots))

    assert result.exit_code == 0, result.output
    event = _only_event(db_path)
    assert event["visual_context"] is False
    assert event["visual_context_reason"] == "no_images"
    assert "visual_count" not in event
    assert len(spy.prompts) == 1, "an empty directory degrades; it does not refuse"


def test_a_missing_capture_directory_records_unreadable(
    repo: Path, db_path: Path, gate_log: Path
) -> None:
    """The third reason value, and the third distinct string this field must
    carry — a two-valued implementation dies here."""
    _seed_run(db_path, repo)
    spy = _EngineSpy()

    result = _invoke(
        repo, db_path, gate_log, spy, "--screenshot-dir", str(repo / "captures" / "never-captured")
    )

    assert result.exit_code == 0, result.output
    event = _only_event(db_path)
    assert event["visual_context"] is False
    assert event["visual_context_reason"] == "unreadable"
    assert len(spy.prompts) == 1


# --- the operator-facing halves: the warning, and the help text --------------


@pytest.mark.parametrize(
    ("case", "reason"),
    [("empty-shots", "no_images"), ("never-captured", "unreadable")],
)
def test_a_degraded_channel_warns_the_operator_on_stderr(
    repo: Path, db_path: Path, gate_log: Path, case: str, reason: str
) -> None:
    """The degrade must be *visible*, not only recorded.

    Both halves of the posture matter: the event answers "did the reviewer see
    the captures" after the fact, and the warning tells the operator *now* that
    the ones they passed did not arrive. Nothing asserted the second until this
    test — deleting the ``typer.echo`` left the whole suite green, which is the
    untested-wiring-line shape this repo keeps paying for.
    """
    shots = repo / "captures" / case
    if case == "empty-shots":
        shots.mkdir(parents=True)
    _seed_run(db_path, repo)
    spy = _EngineSpy()

    result = _invoke(repo, db_path, gate_log, spy, "--screenshot-dir", str(shots))

    assert result.exit_code == 0, result.output
    assert "warning:" in result.stderr, result.stderr
    assert str(shots) in result.stderr
    assert _only_event(db_path)["visual_context_reason"] == reason


def test_captures_with_no_manifest_warn_but_still_proceed(
    repo: Path, db_path: Path, gate_log: Path, captures: Path
) -> None:
    """The third warning, and the one that must NOT read as a failure: the
    manifest is optional, so the captures still reach the engine."""
    (captures / "manifest.md").unlink()
    _seed_run(db_path, repo)
    spy = _EngineSpy()

    result = _invoke(repo, db_path, gate_log, spy, "--screenshot-dir", str(captures))

    assert result.exit_code == 0, result.output
    assert "manifest.md" in result.stderr
    assert len(spy.prompts) == 1
    assert str(captures / "index-1440.png") in spy.prompts[0]


def test_a_run_that_supplies_captures_and_a_manifest_warns_about_nothing(
    repo: Path, db_path: Path, gate_log: Path, captures: Path
) -> None:
    """The control on all three above.

    Without it, a verb that warned on *every* review would satisfy them — and a
    warning that appears on every run is one readers learn to ignore, which is
    the argument ``resolve_design_gate`` already records for warning only when
    something is wrong.
    """
    _seed_run(db_path, repo)
    spy = _EngineSpy()

    result = _invoke(repo, db_path, gate_log, spy, "--screenshot-dir", str(captures))

    assert result.exit_code == 0, result.output
    assert "warning:" not in result.stderr, result.stderr


def test_the_flag_help_states_the_cap_the_code_enforces() -> None:
    """The help text is derived from the constant, not retyped beside it.

    ``MAX_SCREENSHOTS`` is the single home for the cap and every test derives its
    fixture from it (``range(MAX_SCREENSHOTS + 1)``), so a hand-written "12" in
    the operator-facing help would go silently wrong the moment the cap moved —
    the one reader who cannot check the source is the one being told.
    """
    help_text = _screenshot_dir_help()

    assert str(MAX_SCREENSHOTS) in help_text
    assert MANIFEST_FILENAME in help_text


def _screenshot_dir_help() -> str:
    for parameter in inspect.signature(review_mod.review_command).parameters.values():
        if isinstance(parameter.default, OptionInfo) and "--screenshot-dir" in (
            parameter.default.param_decls or ()
        ):
            return str(parameter.default.help)
    raise AssertionError("review_command declares no --screenshot-dir option")


def test_the_prompt_names_every_capture_and_the_manifest(
    repo: Path, db_path: Path, gate_log: Path, captures: Path
) -> None:
    """The wiring the event fields only *describe*: the paths actually reach the
    engine's stdin, and the manifest with them."""
    _seed_run(db_path, repo)
    spy = _EngineSpy()

    result = _invoke(repo, db_path, gate_log, spy, "--screenshot-dir", str(captures))

    assert result.exit_code == 0, result.output
    (prompt,) = spy.prompts
    for name in ("index-1440.png", "index-390.png", "settings-1440.png"):
        assert str(captures / name) in prompt
    assert "index @ 1440/390, settings @ 1440; sha HEAD" in prompt
    assert json.loads(result.stdout)["reviewed_sha"] in prompt
