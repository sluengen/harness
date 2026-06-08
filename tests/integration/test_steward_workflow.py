"""End-to-end integration test for the steward workflow.

This test wires the shipped artefacts together exactly the way a real
run would:

1. Materialises a tmp project root with:
   - ``.harness/`` (DB schema initialised via ``init_db``)
   - ``workflows/steward.yaml`` (copied from the repo)
   - ``prompts/{analyze,review}.j2`` (copied)
   - ``scripts/write_steward_report.py`` (copied)
2. Constructs a ``MockAgent`` with one ``set_next(...)`` per AI step.
   The agent's per-call result must be a :class:`NodeResult` whose
   ``contract`` is an instance of the *exact* Pydantic class the
   loader compiled — otherwise AINode's ``isinstance`` guard fires.
   We solve that by hooking on top of ``MockAgent.execute`` to
   construct the contract from the type the AINode passes through.
3. Runs ``Runner(...).run(workflows/steward.yaml, inputs={"domain":
   "architecture"}, base_branch="dev")`` and asserts:
   - exit code 0,
   - the lifecycle events fired in canonical order,
   - state row carries ``summary``, ``findings``, ``systemic_insights``,
     ``report_path``,
   - the report file at the ``report_path`` exists and contains the
     domain name + every finding (severity / area / description) + the
     systemic insight.

Design judgment — **Option A** (ScriptNode ``contract_override``) was
chosen because it preserves SPEC §14 verbatim and keeps the
write-report step's contract aligned with the workflow author's
declaration. The seam mirrors what ``AINode`` / ``DecisionNode``
already expose. See the test docstring on
:func:`test_steward_workflow_end_to_end` for the full rationale.

No network calls. No real Claude calls. Runs as part of the normal
test suite — no env-var gating.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from pydantic import BaseModel

from harness.dispatch.mock import MockAgent
from harness.engine.runner import Runner
from harness.nodes.base import Attestation, NodeResult
from harness.state.store import init_db

pytestmark = pytest.mark.integration

# Resolve the worktree root so we can copy the shipped artefacts into
# tmp_path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_STEWARD_WORKFLOW_SRC = _REPO_ROOT / "workflows" / "steward.yaml"
_PROMPTS_SRC = _REPO_ROOT / "prompts"
_WRITE_REPORT_SRC = _REPO_ROOT / "scripts" / "write_steward_report.py"


# ---------------------------------------------------------------------------
# Reflecting MockAgent — queues per-step contract payloads, constructs the
# NodeResult against the exact compiled class AINode hands in.
# ---------------------------------------------------------------------------


class _ReflectingMockAgent(MockAgent):
    """A :class:`MockAgent` that builds the ``contract`` instance from the
    exact class supplied at call time.

    The base ``MockAgent.set_next`` queues a pre-built ``NodeResult``,
    but the runtime-compiled inline contracts mean every test instance
    has to build its result against the very class the runner passed in
    — otherwise AINode's ``isinstance`` defensive check rejects it. We
    instead queue *payload dicts* and build the result here. Mirrors the
    ``_ReflectingAgent`` pattern in ``tests/unit/test_engine_runner.py``.
    """

    def __init__(self) -> None:
        super().__init__()
        self._payload_queue: list[dict[str, Any]] = []

    def queue_payload(self, payload: dict[str, Any]) -> None:
        """Append a payload dict to the queue — one per AI step call."""
        self._payload_queue.append(payload)

    async def execute(  # type: ignore[override]
        self,
        prompt: str,
        contract: type[BaseModel],
        submit_tool_schema: dict[str, Any],
        *,
        allowed_tools: list[str],
        cwd: Path | None,
        timeout_s: int = 600,
        stall_timeout_s: int = 300,
        max_turns: int | None = None,
        session_key: str | None = None,
    ) -> NodeResult[BaseModel]:
        # Record the call so the test can assert dispatch order if needed.
        self.calls.append(object())  # type: ignore[arg-type]
        if not self._payload_queue:
            raise AssertionError(
                "ReflectingMockAgent payload queue is empty — every AI "
                "dispatch must be paired with a queue_payload(...) call"
            )
        payload = self._payload_queue.pop(0)
        return NodeResult[BaseModel](
            contract=contract.model_validate(payload),
            attestation=Attestation(status="complete"),
        )


# ---------------------------------------------------------------------------
# Fixture: project root materialised from shipped artefacts.
# ---------------------------------------------------------------------------


@pytest.fixture
def steward_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Materialise ``tmp_path`` with the shipped steward artefacts.

    Layout::

        tmp_path/
          .harness/harness.db
          workflows/steward.yaml
          prompts/{analyze,review}.j2
          scripts/write_steward_report.py

    The script's CWD when invoked by ScriptNode is the process cwd
    (the steward workflow doesn't declare ``step.cwd`` and doesn't
    create a worktree). We ``monkeypatch.chdir(tmp_path)`` so the
    script finds ``.harness/harness.db`` relative to CWD.
    """
    (tmp_path / "workflows").mkdir()
    shutil.copy(_STEWARD_WORKFLOW_SRC, tmp_path / "workflows" / "steward.yaml")

    (tmp_path / "prompts").mkdir(parents=True)
    for prompt in ("analyze.j2", "review.j2"):
        shutil.copy(_PROMPTS_SRC / prompt, tmp_path / "prompts" / prompt)

    (tmp_path / "scripts").mkdir()
    shutil.copy(_WRITE_REPORT_SRC, tmp_path / "scripts" / "write_steward_report.py")

    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# AC3 / AC4 — end-to-end run produces report + lifecycle events
# ---------------------------------------------------------------------------


async def test_steward_workflow_end_to_end(steward_project: Path) -> None:
    """Drive the steward workflow end-to-end with a MockAgent.

    Implementation choice — **Option A** (ScriptNode ``contract_override``):
    the shipped ``write-report`` step declares
    ``writes: [report_path]`` against an inline
    ``contract: { report_path: string }``. The executor's
    ``_validate_writes_against_contract`` requires that field on the
    returned NodeResult's contract. ``ScriptOutput`` has no
    ``report_path`` — so without the override seam, the run would fail
    at write-report. Option A adds the seam to ScriptNode (mirrors the
    existing one on AINode/DecisionNode); Option B (rewrite the YAML to
    ``writes: [stdout]``) would diverge from SPEC §14; Option C
    (collapse write-report into the AI assess step) weakens this
    integration test. See the H-027 PR description for the trade-off.
    """
    db_path = steward_project / ".harness" / "harness.db"
    await init_db(db_path)

    agent = _ReflectingMockAgent()
    # read-context — produces summary + key_files + open_questions.
    agent.queue_payload(
        {
            "summary": (
                "The architecture domain spans the harness engine, "
                "dispatch agents, and workflow loader."
            ),
            "key_files": ["harness/engine/runner.py", "harness/dispatch/claude.py"],
            "open_questions": ["Is the loop evaluator on track for H-021?"],
        }
    )
    # assess — produces findings + systemic_insights.
    agent.queue_payload(
        {
            "findings": [
                {
                    "severity": "HIGH",
                    "area": "X",
                    "description": "Y",
                },
            ],
            "systemic_insights": ["Z"],
        }
    )

    runner = Runner(
        agent=agent,
        db_path=db_path,
        prompts_dir=steward_project,  # FileSystemLoader root
        repo_root=steward_project,
    )
    exit_code = await runner.run(
        steward_project / "workflows" / "steward.yaml",
        inputs={"domain": "architecture"},
        base_branch="dev",
    )

    assert exit_code == 0, f"run failed; agent.calls={len(agent.calls)}"

    # ---- inspect the runs row + events ----
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM runs") as cur:
            rows = await cur.fetchall()
        assert len(rows) == 1
        run_row = dict(rows[0])

        async with conn.execute(
            "SELECT event_type, node_id FROM events WHERE run_id = ? ORDER BY id",
            (run_row["run_id"],),
        ) as cur:
            event_rows = await cur.fetchall()

    assert run_row["status"] == "completed"
    assert run_row["exit_code"] == 0

    # Lifecycle events: SPEC §4.9 canonical sequence (state_changed events
    # are interleaved; we filter to the lifecycle-only events here).
    lifecycle = [
        (e["event_type"], e["node_id"])
        for e in event_rows
        if e["event_type"]
        in {
            "workflow_started",
            "workflow_completed",
            "node_started",
            "node_completed",
        }
    ]
    assert lifecycle == [
        ("workflow_started", None),
        ("node_started", "read-context"),
        ("node_completed", "read-context"),
        ("node_started", "assess"),
        ("node_completed", "assess"),
        ("node_started", "write-report"),
        ("node_completed", "write-report"),
        ("workflow_completed", None),
    ]

    # ---- inspect the state row ----
    state = json.loads(run_row["state_json"])
    assert state["summary"].startswith("The architecture domain")
    assert state["key_files"] == [
        "harness/engine/runner.py",
        "harness/dispatch/claude.py",
    ]
    assert state["findings"] == [
        {"severity": "HIGH", "area": "X", "description": "Y"},
    ]
    assert state["systemic_insights"] == ["Z"]
    assert state["report_path"] is not None

    # ---- inspect the generated report ----
    report_path = Path(state["report_path"])
    assert report_path.is_file(), f"report not found at {report_path}"
    # The path is under tmp_path/.harness/artifacts/<run_id>/.
    expected_dir = steward_project / ".harness" / "artifacts" / run_row["run_id"]
    assert report_path.resolve() == (expected_dir / "steward-report.md").resolve()

    body = report_path.read_text()
    # Domain header.
    assert "architecture" in body
    # Findings rendered with severity / area / description.
    assert "HIGH" in body
    assert "X" in body
    assert "Y" in body
    # Systemic insight rendered.
    assert "Z" in body
    # Run-id footer.
    assert run_row["run_id"] in body


# ---------------------------------------------------------------------------
# AC6 — write_steward_report.py is invocable as a standalone tool
# ---------------------------------------------------------------------------


async def test_write_steward_report_runs_standalone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invoke ``python scripts/write_steward_report.py`` as a subprocess
    against a hand-rolled ``runs`` row. Confirms the script is usable
    outside the harness — e.g. for debugging or re-rendering a report
    from a stored state.

    This sidesteps the harness entirely: build the DB row by hand, then
    run the script with python and parse its stdout JSON.
    """
    # Copy the script into the tmp dir so its relative path matches what
    # the steward workflow expects.
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    target = scripts_dir / "write_steward_report.py"
    shutil.copy(_WRITE_REPORT_SRC, target)

    # Create .harness/harness.db with one runs row.
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    db_path = harness_dir / "harness.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE runs (
              run_id              TEXT PRIMARY KEY,
              workflow_name       TEXT NOT NULL,
              workflow_version    INTEGER NOT NULL,
              status              TEXT NOT NULL,
              state_json          TEXT NOT NULL,
              inputs_json         TEXT NOT NULL,
              base_branch         TEXT,
              worktree_branch     TEXT,
              exit_code           INTEGER,
              started_at          TEXT NOT NULL,
              completed_at        TEXT,
              duration_ms         INTEGER
            )
            """
        )
        state_payload = {
            "findings": [
                {"severity": "LOW", "area": "AREA", "description": "DESC"},
            ],
            "systemic_insights": ["INSIGHT"],
        }
        conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "01HXXXXXXXXXXXXXXXXXXXXXX0",
                "steward",
                1,
                "running",
                json.dumps(state_payload),
                json.dumps({"domain": "harness"}),
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.chdir(tmp_path)
    proc = subprocess.run(
        [sys.executable, "scripts/write_steward_report.py",
         "--run-id", "01HXXXXXXXXXXXXXXXXXXXXXX0",
         "--domain", "harness"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    payload = json.loads(proc.stdout)
    assert "report_path" in payload
    report = Path(payload["report_path"])
    assert report.is_file()

    body = report.read_text()
    assert "# Steward Report: harness" in body
    assert "LOW" in body
    assert "AREA" in body
    assert "DESC" in body
    assert "INSIGHT" in body
