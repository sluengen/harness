"""Progress reporter for terminal output during workflow execution.

Taps the EventEmitter's on_emit callback to stream one line per node/workflow
transition to stderr without any new persistence layer.

Format::

    [workflow_name] node_id         started
    [workflow_name] node_id         completed (0.1s)
    [workflow_name] node_id         failed
    [workflow_name] (workflow)      started
    [workflow_name] (workflow)      completed (12s)
    [workflow_name] (workflow)      failed
"""

from __future__ import annotations

import sys
from typing import IO

_EVENTS_TO_PRINT: frozenset[str] = frozenset(
    {
        "node_started",
        "node_completed",
        "node_failed",
        "workflow_started",
        "workflow_completed",
        "workflow_failed",
    }
)

_NODE_COL_WIDTH = 16


class ProgressReporter:
    """Callable sink: prints one formatted line per lifecycle event to a file.

    Designed to be passed as the ``on_emit`` callback of
    :class:`harness.events.emitter.EventEmitter`. Ignores events not in the
    lifecycle set (e.g. ``tool_called``, ``state_changed``).

    Args:
        workflow_name: Printed as ``[workflow_name]`` at the start of each line.
        file: Output stream. Defaults to ``sys.stderr``.
    """

    def __init__(self, workflow_name: str, *, file: IO[str] | None = None) -> None:
        self._workflow_name = workflow_name
        self._file: IO[str] = file if file is not None else sys.stderr

    def __call__(
        self,
        event_type: str,
        node_id: str | None,
        duration_ms: int | None,
    ) -> None:
        if event_type not in _EVENTS_TO_PRINT:
            return

        label = node_id if node_id is not None else "(workflow)"

        if "started" in event_type:
            status = "started"
        elif "completed" in event_type:
            s = (duration_ms / 1000.0) if duration_ms is not None else 0.0
            dur = f"{s:.1f}s" if s < 10 else f"{int(round(s))}s"
            status = f"completed ({dur})"
        else:
            status = "failed"

        print(
            f"[{self._workflow_name}] {label:<{_NODE_COL_WIDTH}} {status}",
            file=self._file,
            flush=True,
        )
