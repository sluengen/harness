"""Unit tests for :mod:`harness.trigger` — the Hermes trigger stand-in (CAL-585).

These cover the trigger contract in isolation (launch + ledger readback) with
injected collaborators. The end-to-end demo that drives the real verbs through
the launcher socket lives in ``tests/integration/test_hermes_demo.py``.

Coverage maps to the ticket's acceptance criteria:

* AC-2 — the trigger launches the per-session agent runtime exactly once with
  the headless ``/harness run`` handle (``test_launches_*``).
* AC-3 — the outcome is derived *solely* from the ledger, never from the launch
  (``test_outcome_comes_from_ledger_not_launch``); the trigger's command surface
  is read-only (``test_read_only_command_surface``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from harness.trigger import (
    READ_ONLY_COMMANDS,
    AgentLaunch,
    HermesTrigger,
    agent_run_command,
    events_read_command,
    status_read_command,
)


def _trigger(
    *,
    launch: AgentLaunch,
    status: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    launches: list[str] | None = None,
) -> HermesTrigger:
    def launch_agent(ticket: str) -> AgentLaunch:
        if launches is not None:
            launches.append(ticket)
        return launch

    return HermesTrigger(
        launch_agent=launch_agent,
        read_status=lambda _run_id: status,
        read_events=lambda _run_id: events,
    )


# ---------------------------------------------------------------------------
# Command surface (AC-2 launch handle, AC-3 read-only)
# ---------------------------------------------------------------------------


def test_agent_run_command_is_headless_harness_run() -> None:
    # Decision #2: the autonomous path launches the runtime headless and lets it
    # drive the whole verb loop from a single /harness run invocation.
    assert agent_run_command("CAL-585") == ["claude", "-p", "/harness run CAL-585"]


def test_read_only_command_surface() -> None:
    # The trigger only ever reads the ledger — status / events, both read-only.
    assert set(READ_ONLY_COMMANDS) == {"status", "events"}
    assert status_read_command("R1") == ["status", "R1", "--json"]
    assert events_read_command("R1") == ["events", "R1", "--json"]
    # No writing verb (start / review / close) is in the trigger's surface.
    assert not (READ_ONLY_COMMANDS & {"start", "review", "close", "cancel"})


# ---------------------------------------------------------------------------
# AC-2: exactly one per-session launch
# ---------------------------------------------------------------------------


def test_launches_agent_runtime_exactly_once_per_ticket() -> None:
    launches: list[str] = []
    trigger = _trigger(
        launch=AgentLaunch(run_id="R1", exit_code=0),
        status={"status": "closed"},
        events=[{"event_type": "review", "data": {"verdict": "pass"}}],
        launches=launches,
    )
    trigger.run("CAL-585")
    # One session drives all verbs (AC-2) — not one launch per verb.
    assert launches == ["CAL-585"]


# ---------------------------------------------------------------------------
# AC-3: the outcome is read from the ledger, not the launch
# ---------------------------------------------------------------------------


def test_closed_run_with_passing_review_is_reported_closed() -> None:
    trigger = _trigger(
        launch=AgentLaunch(run_id="R1", exit_code=0),
        status={"status": "closed"},
        events=[
            {"event_type": "start", "data": {}},
            {"event_type": "review", "data": {"verdict": "pass", "reviewed_sha": "abc"}},
            {"event_type": "close", "data": {}},
        ],
    )
    outcome = trigger.run("CAL-585")
    assert outcome.run_id == "R1"
    assert outcome.status == "closed"
    assert outcome.closed is True
    assert outcome.review_passed is True


def test_outcome_comes_from_ledger_not_launch() -> None:
    # The agent runtime exited 0, but the ledger says the run is still open with
    # only a failing review — the trigger trusts the ledger, not the exit code.
    trigger = _trigger(
        launch=AgentLaunch(run_id="R1", exit_code=0),
        status={"status": "open"},
        events=[{"event_type": "review", "data": {"verdict": "fail"}}],
    )
    outcome = trigger.run("CAL-585")
    assert outcome.closed is False
    assert outcome.review_passed is False
    assert outcome.status == "open"


def test_no_run_opened_is_indeterminate() -> None:
    # The launch failed before opening a run — nothing to read; never claim closed.
    trigger = _trigger(
        launch=AgentLaunch(run_id=None, exit_code=1),
        status={"status": "closed"},  # should be ignored — no run_id to read
        events=[],
    )
    outcome = trigger.run("CAL-585")
    assert outcome.run_id is None
    assert outcome.closed is False
    assert outcome.review_passed is False
    assert outcome.launch_exit_code == 1
