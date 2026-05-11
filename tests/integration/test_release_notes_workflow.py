"""End-to-end integration test for the release-notes workflow (CAL-292 / H-028).

Mirrors the steward integration test pattern:

1. Materialises a tmp project root with:
   - ``.harness/`` (DB schema initialised via ``init_db``)
   - ``workflows/release-notes.yaml`` (copied from the repo)
   - ``prompts/standard/summarize.j2`` (copied)
   - ``scripts/fetch_recent_linear_tickets.py`` + ``scripts/write_release_notes.py`` (copied)
   - ``tests/fixtures/release_notes_tickets.json`` (copied — the fetch
     script reads from a path resolved from its own location)
2. Constructs a reflecting :class:`MockAgent` that queues one payload
   for the ``summarise`` AI step. The payload's ``release_notes`` field
   is a recognisable string the test will assert on.
3. Runs the workflow and asserts:
   - exit code 0,
   - the lifecycle events fired in order,
   - state row carries ``tickets``, ``release_notes``, ``output_path``,
   - the markdown file at ``output_path`` exists and contains the
     mocked release-notes payload.

No network. No real Claude calls. No env-var gating.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from pydantic import BaseModel

from harness.dispatch.mock import MockAgent
from harness.engine.runner import Runner
from harness.nodes.base import Attestation, NodeResult
from harness.state.store import init_db

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW_SRC = _REPO_ROOT / "workflows" / "release-notes.yaml"
_PROMPT_SRC = _REPO_ROOT / "prompts" / "standard" / "summarize.j2"
_FETCH_SCRIPT_SRC = _REPO_ROOT / "scripts" / "fetch_recent_linear_tickets.py"
_WRITE_SCRIPT_SRC = _REPO_ROOT / "scripts" / "write_release_notes.py"
_FIXTURE_SRC = _REPO_ROOT / "tests" / "fixtures" / "release_notes_tickets.json"


class _ReflectingMockAgent(MockAgent):
    """A :class:`MockAgent` that builds the ``contract`` instance from the
    exact class supplied at call time — same pattern as the steward test."""

    def __init__(self) -> None:
        super().__init__()
        self._payload_queue: list[dict[str, Any]] = []

    def queue_payload(self, payload: dict[str, Any]) -> None:
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
    ) -> NodeResult[BaseModel]:
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


@pytest.fixture
def release_notes_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Materialise ``tmp_path`` with the shipped release-notes artefacts."""
    (tmp_path / "workflows").mkdir()
    shutil.copy(_WORKFLOW_SRC, tmp_path / "workflows" / "release-notes.yaml")

    (tmp_path / "prompts" / "standard").mkdir(parents=True)
    shutil.copy(_PROMPT_SRC, tmp_path / "prompts" / "standard" / "summarize.j2")

    (tmp_path / "scripts").mkdir()
    shutil.copy(_FETCH_SCRIPT_SRC, tmp_path / "scripts" / "fetch_recent_linear_tickets.py")
    shutil.copy(_WRITE_SCRIPT_SRC, tmp_path / "scripts" / "write_release_notes.py")

    (tmp_path / "tests" / "fixtures").mkdir(parents=True)
    shutil.copy(
        _FIXTURE_SRC, tmp_path / "tests" / "fixtures" / "release_notes_tickets.json"
    )

    monkeypatch.chdir(tmp_path)
    return tmp_path


async def test_release_notes_workflow_end_to_end(
    release_notes_project: Path,
) -> None:
    """Drive the release-notes workflow end-to-end with a MockAgent."""
    db_path = release_notes_project / ".harness" / "harness.db"
    await init_db(db_path)

    agent = _ReflectingMockAgent()
    mocked_body = (
        "# Release Notes\n\n"
        "## Features\n- CAL-303: equipment_grinder field\n\n"
        "## Bug fixes\n- CAL-301: drum picker overshoot\n"
    )
    agent.queue_payload({"release_notes": mocked_body})

    output_path = release_notes_project / "release-notes-test.md"
    runner = Runner(
        agent=agent,
        db_path=db_path,
        prompts_dir=release_notes_project,
        repo_root=release_notes_project,
    )
    exit_code = await runner.run(
        release_notes_project / "workflows" / "release-notes.yaml",
        inputs={"since_days": 7, "output_path": str(output_path)},
        base_branch="main",
    )

    assert exit_code == 0, f"run failed; agent.calls={len(agent.calls)}"

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
        ("node_started", "fetch-tickets"),
        ("node_completed", "fetch-tickets"),
        ("node_started", "summarise"),
        ("node_completed", "summarise"),
        ("node_started", "write-file"),
        ("node_completed", "write-file"),
        ("workflow_completed", None),
    ]

    state = json.loads(run_row["state_json"])
    assert isinstance(state["tickets"], list)
    assert len(state["tickets"]) >= 3
    assert state["release_notes"] == mocked_body
    assert state["output_path"] == str(output_path.resolve())

    assert output_path.is_file(), f"release notes not at {output_path}"
    body = output_path.read_text()
    assert "Release Notes" in body
    assert "CAL-303" in body
    assert "CAL-301" in body
