"""#363 AC-1 — the probe stage, end to end, with nothing that matters stubbed.

AC-1 says a reviewer-proposed mutation that survives must be surfaced and
recorded as demonstrated, "proven end to end, not by unit-testing the plumbing".
That wording is the ticket anticipating the exact failure this repo keeps paying
for: every seam here can be green against a stage that never actually mutates
anything.

So one stub only — the review **engine**, which no test can spawn. Everything
downstream of its SUBMIT line is real: a real `git worktree add --detach` at the
reviewed SHA, the real `scripts/mutate.py` from the primary checkout, a real
pytest run of a real (deliberately weak) guard, the real `--json` report, and the
real ledger write.

The synthetic project is built so its outcomes are known **by construction**
rather than by observation, and it carries both directions of AC-2 in one run:

* `LIMIT = 10` → `LIMIT = 9999` — the guard asserts `under(5)` and never pins the
  constant, so the suite stays green and the observable moves. A live survivor: a
  real gap in a real guard.
* `n < LIMIT` → `LIMIT > n` — identical in meaning. It kills nothing *and* moves
  nothing, so it is `inert`: a defect in the entry, not a hole in the guard. This
  is #336's four no-ops reproduced deliberately, and the run must tell it apart
  from the one above rather than reporting both as SURVIVED.

Getting both from one probe run is the point. A test that only proved the live
case would pass against a stage that classified every survivor as demonstrated.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest.mock as mock
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli import review as review_mod
from harness.state import store
from tests._asyncutil import run_sync
from tests._ledger import seed_design_event

cli_runner = CliRunner()

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUN_ID = "01JRUNPROBEE2EXXXXXXXXXX01"
_NODE = "tests/test_pkg.py::test_under"

_PKG = '''LIMIT = 10


def under(n):
    return n < LIMIT
'''

# Deliberately weak: it exercises `under` without ever pinning `LIMIT`, so
# raising the constant leaves it green. That is the shape a builder's own
# mutation table is least likely to think of, which is the whole premise.
_TEST = '''import pytest

from pkg import under


@pytest.mark.unit
def test_under():
    assert under(5) is True
'''

_INI = """[pytest]
markers =
    unit: the tier the probe selection picks
    guard: the other half of that selection
"""

_LIVE = {
    "id": "limit-constant",
    "file": "pkg.py",
    "old": "LIMIT = 10",
    "new": "LIMIT = 9999",
    "kills": [_NODE],
    "note": "nothing pins the constant the guard depends on",
    "observe": ["-c", "import pkg; print(pkg.LIMIT)"],
}
_INERT = {
    "id": "comparison-flip",
    "file": "pkg.py",
    "old": "return n < LIMIT",
    "new": "return LIMIT > n",
    "kills": [_NODE],
    "note": "a rewrite that evaluates to the same thing — the #336 shape",
    "observe": ["-c", "import pkg; print(pkg.under(5), pkg.under(50))"],
}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture(autouse=True)
def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real repo holding a self-contained pytest project and the real instrument."""
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "pkg.py").write_text(_PKG, encoding="utf-8")
    (root / "tests" / "test_pkg.py").write_text(_TEST, encoding="utf-8")
    # Its own ini, so this repo's rootdir and addopts cannot leak into the child
    # run and decide the outcome instead of the mutation.
    (root / "pytest.ini").write_text(_INI, encoding="utf-8")
    # Production's shape, and load-bearing rather than cosmetic: the ledger and
    # the worktree root live *inside* the tree under review, so a fixture that
    # left them visible would make the identity check below assert something no
    # real run ever sees.
    (root / ".gitignore").write_text(".harness/\n.worktrees/\n", encoding="utf-8")
    (root / "conftest.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent))\n",
        encoding="utf-8",
    )
    for name in ("mutate.py", "_mutate_outcomes.py"):
        shutil.copy(_REPO_ROOT / "scripts" / name, root / "scripts" / name)
    (root / "CONTEXT.md").write_text(
        "```yaml\nrepo:\n  name: t\n```\n\nloop:\n  probe_max_entries: 3\n"
        "  probe_budget_seconds: 300\n",
        encoding="utf-8",
    )
    _git(root, "init", "-b", "dev")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "initial")
    return root


@pytest.fixture
def db_path(repo: Path) -> Path:
    path = repo / ".harness" / "harness.db"

    async def _insert() -> None:
        await store.init_db(path)
        async with store.connect(path) as conn:
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
    seed_design_event(path, _RUN_ID)
    return path


class _Engine:
    """The one stub. Records every prompt it is handed."""

    def __init__(self, *stdouts: str) -> None:
        self.stdouts = list(stdouts)
        self.prompts: list[str] = []
        self.cwds: list[Path | None] = []

    async def __call__(self, **kwargs: Any) -> review_mod.RunResult:
        self.prompts.append(kwargs["stdin"])
        self.cwds.append(kwargs["cwd"])
        stdout = self.stdouts[min(len(self.prompts), len(self.stdouts)) - 1]
        return review_mod.RunResult(stdout=stdout, stderr="", returncode=0)


def _submit(verdict: str, issues: list[str], probes: list[dict[str, Any]] | None = None) -> str:
    payload: dict[str, Any] = {"verdict": verdict, "issues": issues}
    if probes is not None:
        payload["probes"] = probes
    return f"SUBMIT: {json.dumps(payload)}\n"


def _review_event(db_path: Path) -> dict[str, Any]:
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


@pytest.fixture
def outcome(repo: Path, db_path: Path) -> tuple[Any, _Engine, dict[str, Any]]:
    """One real probe run, shared by the assertions below.

    A single run rather than one per assertion because it is genuinely expensive
    — three real pytest invocations plus four observable spawns — and because
    every claim below is about the *same* run: the live entry and the inert one
    have to be separated by one report, not by two runs that could each have been
    right for the wrong reason.
    """
    engine = _Engine(
        _submit("pass", [], [_LIVE, _INERT]),
        _submit("fail", ["[probe:limit-constant] nothing pins LIMIT; the guard is weak"]),
    )
    with mock.patch.object(review_mod, "_default_runner", engine):
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
    return result, engine, _review_event(db_path)


def test_a_live_survivor_is_demonstrated_and_an_inert_entry_is_not(
    outcome: tuple[Any, _Engine, dict[str, Any]],
) -> None:
    """AC-1 and AC-2, from one real report.

    The inert entry is what makes this a discrimination rather than a detection:
    both entries survived the suite, and only one of them is evidence about the
    guard.
    """
    result, _engine, event = outcome

    assert result.exit_code == 0, result.stdout
    by_id = {e["id"]: e for e in event["probe_entries"]}
    assert by_id["limit-constant"]["outcome"] == "survived"
    assert by_id["limit-constant"]["live"] is True
    assert by_id["comparison-flip"]["outcome"] == "inert"
    assert event["probe_demonstrated"] == ["limit-constant"]


def test_the_demonstrated_survivor_becomes_a_recorded_finding(
    outcome: tuple[Any, _Engine, dict[str, Any]],
) -> None:
    """The whole point of the stage: argued becomes demonstrated, on the record."""
    result, engine, event = outcome

    assert len(engine.prompts) == 2, "a survivor must buy a second pass"
    assert "[probe:limit-constant]" in engine.prompts[1]
    assert "comparison-flip" not in engine.prompts[1], (
        "a failure of the entry may not be cited, so it is not offered"
    )
    printed = json.loads(result.stdout)
    assert printed["verdict"] == "fail"
    assert printed["issues"][0].startswith("[probe:limit-constant]")
    assert printed["probes_run"] == 2
    assert printed["probes_survived"] == 1
    assert event["probe_status"] == "ran"
    assert event["probe_duration_ms"] > 0


def test_the_run_worktree_is_untouched_and_the_probe_tree_is_gone(
    repo: Path, outcome: tuple[Any, _Engine, dict[str, Any]]
) -> None:
    """The invariant the execute grant rests on, checked against real git.

    `pkg.py` was mutated twice and restored twice during this run — in a
    different directory. If the stage had worked in place, the porcelain would
    say so.
    """
    _result, _engine, event = outcome

    assert _git(repo, "status", "--porcelain", "--untracked-files=all") == ""
    assert _git(repo, "rev-parse", "HEAD") == event["reviewed_sha"]
    assert (repo / "pkg.py").read_text(encoding="utf-8") == _PKG
    assert not list((repo / ".worktrees" / "harness").glob("*-probe"))
    assert "-probe" not in _git(repo, "worktree", "list")


def test_the_first_pass_was_asked_for_probes_and_the_second_was_not(
    outcome: tuple[Any, _Engine, dict[str, Any]],
) -> None:
    """One review spends the budget once."""
    _result, engine, _event = outcome

    assert "probes" in engine.prompts[0]
    assert "up to 3" in engine.prompts[0]
    assert "up to 3" not in engine.prompts[1]
