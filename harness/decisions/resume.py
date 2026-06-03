"""State rehydration for paused-run resume (H-2-005).

Reads the most recent per-completion snapshot for a paused run and
writes it back to ``runs.state_json`` so the executor starts from the
correct state when the runner resumes execution.

Why snapshot-first? ``runs.state_json`` is a mutable column that
reflects the state after the last *write* node. Nodes without
``writes:`` (check nodes, decision nodes) do not update it, so
``runs.state_json`` always shows the state after the most recently
write-bearing step rather than the most recently executed step.

The ``run_snapshots`` table (H-2-001) captures a full state copy after
*every* successful node completion regardless of whether it wrote any
fields. Rehydrating from the latest snapshot therefore guarantees that
the executor starts with the complete paused-point state.

``runs.state_json`` and the latest snapshot are usually identical for
write-bearing workflows. The snapshot path is strictly more correct and
is the authoritative source for resume — ``runs.state_json`` is the
operational fallback for runs where the decision node was the very
first step (no predecessors produced a snapshot).
"""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

from harness.state.schema import BaseState
from harness.state.store import read_latest_snapshot, read_state, restore_state

__all__ = ["rehydrate_state"]

S = TypeVar("S", bound=BaseState)


async def rehydrate_state(
    run_id: str,
    schema: type[S],
    *,
    db_path: Path,
) -> S:
    """Rehydrate the canonical run state for resume.

    1. Reads the highest-``seq`` row from ``run_snapshots`` for this run.
    2. If a snapshot exists, writes it back to ``runs.state_json`` (so
       the executor's :func:`~harness.state.store.read_state` calls see
       the correct paused-point state) and returns it.
    3. Falls back to reading ``runs.state_json`` via
       :func:`~harness.state.store.read_state` when no snapshot exists
       (e.g., the decision node was the very first step).

    Args:
        run_id: The run being resumed.
        schema: The workflow-derived state class (produced by
            :func:`~harness.workflow.derive.derive_state_schema`).
        db_path: Path to the SQLite database.

    Returns:
        The rehydrated :class:`~harness.state.schema.BaseState` instance.
    """
    snapshot = await read_latest_snapshot(run_id, schema, db_path=db_path)
    if snapshot is not None:
        # Write snapshot state back to runs.state_json so the executor's
        # read_state() calls in resumed steps see the correct state.
        await restore_state(run_id, snapshot, db_path=db_path)
        return snapshot
    return await read_state(run_id, schema, db_path=db_path)
