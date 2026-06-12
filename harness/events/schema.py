"""Event type literals — see SPEC §4.7.

The canonical set of event types the engine emits. Defined here as a
``Literal`` so static type-checkers reject typos at call sites and the runtime
emitter can validate against ``EVENT_TYPES`` before writing to the append-only
log.
"""

from __future__ import annotations

from typing import Literal, get_args

EventType = Literal[
    # Workflow lifecycle.
    "workflow_started",
    "workflow_completed",
    "workflow_failed",
    "workflow_paused",
    # Node lifecycle.
    "node_started",
    "node_completed",
    "node_failed",
    # Tool calls.
    "tool_called",
    "tool_completed",
    # State + control flow.
    "state_changed",
    "loop_iteration",
    "retry_attempted",
    # Decisions (human-in-the-loop).
    "decision_requested",
    "decision_made",
    "decision_received",
    "decision_timeout",
    # Agent contract violations — see SPEC §4.4 (e.g. agent calls submit twice).
    "decision_violation",
    # Review verb (CAL-571) — codex review of HEAD, verdict bound to reviewed SHA.
    "review",
    # Close verb (CAL-572) — gate passed, run merged/closed, ticket Done.
    "close",
]

EVENT_TYPES: frozenset[str] = frozenset(get_args(EventType))
"""Runtime view of the canonical event types — derived from the Literal above
so the two cannot drift."""
