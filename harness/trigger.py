"""Hermes trigger — the local stand-in for the launch handle (CAL-585).

The trigger is whoever occupies the *trigger slot*: a human (``/harness run``)
or [Nous Research's Hermes](https://hermes-agent.nousresearch.com) on the
autonomous path. Its job is deliberately tiny (``specs/hermes-orchestration.md``
§Runtime topology → *Launch handle and decision record*):

1. **Launch** a *per-session* agent runtime headless — ``claude -p "/harness run
   <ticket>"`` (decision #2). That one Claude session drives the whole
   ``start → implement → review* → close`` loop, calling each verb as a one-shot
   sibling container *outside* itself through the narrow launcher control socket
   (decision #1; :mod:`harness.launcher`). Context is retained across verbs
   because it is **one** session, not one-per-verb (AC-2).
2. **Read the outcome solely from the ledger** — ``harness status`` /
   ``harness events --json``, read-only. The trigger never implements, manages
   worktrees, runs codex, does gitops, or writes the harness DB (AC-3).

This module is the *local stand-in* used to demonstrate that handle end-to-end
without changing Hermes itself (changes to Nous' agent are out of scope): the
launch and the ledger readers are injected, so a test can substitute an
in-process agent-runtime that drives the real verbs and assert AC-1/2/3. The
module-level command builders (:func:`agent_run_command`,
:func:`status_read_command`, :func:`events_read_command`) are the real handles
the deployed trigger issues.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "READ_ONLY_COMMANDS",
    "AgentLaunch",
    "TriggerOutcome",
    "agent_run_command",
    "status_read_command",
    "events_read_command",
    "HermesTrigger",
]

#: The only harness commands the trigger ever issues against a run it launched.
#: Both are read-only: the trigger derives the outcome from the ledger and never
#: mutates state (AC-3 — "no harness DB writes"). A writing verb (start / review
#: / close) is issued only by the *agent runtime*, never by the trigger.
READ_ONLY_COMMANDS: frozenset[str] = frozenset({"status", "events"})


def agent_run_command(ticket: str) -> list[str]:
    """The headless launch handle for the per-session agent runtime (decision #2).

    One session drives ``start → implement → review* → close`` non-interactively;
    the trigger launches exactly this, once per ticket (AC-2 — context is
    retained because there is a single session, not one per verb).
    """
    return ["claude", "-p", f"/harness run {ticket}"]


def status_read_command(run_id: str) -> list[str]:
    """Read-only ledger command: a run's terminal-state summary as JSON."""
    return ["status", run_id, "--json"]


def events_read_command(run_id: str) -> list[str]:
    """Read-only ledger command: a run's events, one JSON object per line."""
    return ["events", run_id, "--json"]


@dataclass(frozen=True)
class AgentLaunch:
    """What the trigger can observe about a launched agent runtime.

    The agent runtime opens exactly one run (via ``harness start``); the trigger
    learns its ``run_id`` so it can read the ledger back. ``run_id`` is ``None``
    when the session never opened a run (e.g. the launch itself failed) — the
    trigger then has nothing to read and reports an indeterminate outcome.
    """

    run_id: str | None
    exit_code: int


@dataclass(frozen=True)
class TriggerOutcome:
    """The run outcome the trigger derived *solely* from the ledger.

    No field here comes from the agent runtime's stdout or any side channel —
    every one is read from ``status`` / ``events`` after the session exits, so
    the trigger's verdict and the audited ledger can never disagree (AC-3).
    """

    ticket: str
    run_id: str | None
    status: str | None
    closed: bool
    review_passed: bool
    launch_exit_code: int


#: Launches the per-session agent runtime for a ticket and returns what the
#: trigger can observe. The real implementation shells out to
#: :func:`agent_run_command`; tests inject an in-process agent that drives the
#: real verbs through the launcher socket.
AgentLauncher = Callable[[str], AgentLaunch]

#: Reads one run's ledger and returns the parsed JSON. ``read_status`` returns
#: the single status object; ``read_events`` returns the list of event objects.
StatusReader = Callable[[str], Mapping[str, Any]]
EventsReader = Callable[[str], Sequence[Mapping[str, Any]]]


class HermesTrigger:
    """Local stand-in for the Hermes (or human) trigger (CAL-585).

    Holds the injected launch + read-back collaborators and turns one ticket
    into one :class:`TriggerOutcome`. The class itself issues **no** writing
    command — it launches the agent runtime and reads the ledger; that is the
    whole contract.
    """

    def __init__(
        self,
        *,
        launch_agent: AgentLauncher,
        read_status: StatusReader,
        read_events: EventsReader,
    ) -> None:
        self._launch_agent = launch_agent
        self._read_status = read_status
        self._read_events = read_events

    def run(self, ticket: str) -> TriggerOutcome:
        """Launch the agent runtime for ``ticket``; report the ledger outcome."""
        launch = self._launch_agent(ticket)
        run_id = launch.run_id
        if run_id is None:
            # The session never opened a run — nothing to read; outcome unknown.
            return TriggerOutcome(
                ticket=ticket,
                run_id=None,
                status=None,
                closed=False,
                review_passed=False,
                launch_exit_code=launch.exit_code,
            )

        status = self._read_status(run_id)
        events = self._read_events(run_id)
        status_value = status.get("status")
        review_passed = any(
            event.get("event_type") == "review"
            and _event_data(event).get("verdict") == "pass"
            for event in events
        )
        return TriggerOutcome(
            ticket=ticket,
            run_id=run_id,
            status=status_value if status_value is None else str(status_value),
            closed=status_value == "closed",
            review_passed=review_passed,
            launch_exit_code=launch.exit_code,
        )


def _event_data(event: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return an event's ``data`` payload as a mapping (empty if absent/garbled)."""
    data = event.get("data")
    return data if isinstance(data, Mapping) else {}
