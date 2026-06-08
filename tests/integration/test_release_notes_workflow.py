"""End-to-end integration test for the release-notes workflow.

Mirrors the steward integration test pattern:

1. Materialises a tmp project root with:
   - ``.harness/`` (DB schema initialised via ``init_db``)
   - ``workflows/release.yaml`` (copied from the repo)
   - ``prompts/summarize.j2`` (copied)
   - ``scripts/write_release_notes.py`` (copied)
   - A fake ``curl`` on PATH that returns ``tests/fixtures/release_notes_tickets.json``
     in the Linear API response format (no network required).
2. Constructs a reflecting :class:`MockAgent` that queues one payload
   for the ``summarise`` AI step. The payload's ``release_notes`` field
   is a recognisable string the test will assert on.
3. Runs the workflow and asserts:
   - exit code 0,
   - the lifecycle events fired in order,
   - state row carries ``tickets``, ``release_notes``, ``output_path``,
     ``pr_url``,
   - the markdown file at ``output_path`` exists and contains the
     mocked release-notes payload.

No network. No real Claude calls. No env-var gating.
"""

from __future__ import annotations

import json
import os
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

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW_SRC = _REPO_ROOT / "workflows" / "release.yaml"
_PROMPT_SRC = _REPO_ROOT / "prompts" / "summarize.j2"
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
        max_turns: int | None = None,
        session_key: str | None = None,
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
    shutil.copy(_WORKFLOW_SRC, tmp_path / "workflows" / "release.yaml")

    (tmp_path / "prompts").mkdir(parents=True)
    shutil.copy(_PROMPT_SRC, tmp_path / "prompts" / "summarize.j2")

    (tmp_path / "scripts").mkdir()
    shutil.copy(_WRITE_SCRIPT_SRC, tmp_path / "scripts" / "write_release_notes.py")

    # Fake curl returns the Linear API fixture and fake gh returns a PR URL —
    # no network or GitHub auth needed.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(f"#!/bin/bash\ncat {_FIXTURE_SRC}\n")
    fake_curl.chmod(0o755)
    fake_gh = fake_bin / "gh"
    fake_gh.write_text("#!/bin/bash\necho https://github.test/example/pull/123\n")
    fake_gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + ":" + os.environ.get("PATH", ""))

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
        "## Features\n- PROJ-303: equipment_type field\n\n"
        "## Bug fixes\n- PROJ-301: dropdown overshoot\n"
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
        release_notes_project / "workflows" / "release.yaml",
        inputs={
            "since_days": 7,
            "output_path": str(output_path),
            "repo": "owner/repo",
        },
        base_branch="dev",
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
        ("node_started", "raise-pr"),
        ("node_completed", "raise-pr"),
        ("workflow_completed", None),
    ]

    state = json.loads(run_row["state_json"])
    assert isinstance(state["tickets"], list)
    assert len(state["tickets"]) >= 3
    assert state["release_notes"] == mocked_body
    assert state["output_path"] == str(output_path.resolve())
    assert state["pr_url"] == "https://github.test/example/pull/123"

    assert output_path.is_file(), f"release notes not at {output_path}"
    body = output_path.read_text()
    assert "Release Notes" in body
    assert "PROJ-303" in body
    assert "PROJ-301" in body
