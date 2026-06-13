"""Framework-defined state base — see ``specs/state-store.md`` ("BaseState").

:class:`BaseState` holds the framework-defined run fields. It predates the
verb model (CAL-574 retired the workflow engine that derived per-workflow
state subclasses on top of this base); the run-state shape is now this base
directly.

The framework-supplied fields populated when a run begins:

* ``run_id`` — opaque identifier for this run.
* ``workflow_name`` — :attr:`Workflow.name`.
* ``base_branch`` — branch the run was started against (for worktree
  isolation).
* ``worktree_path`` / ``worktree_branch`` — populated when the run's
  first ``worktree.create`` step executes; ``None`` until then.
* ``artifacts_dir`` — where the run writes prompt transcripts, review
  artifacts, etc.
* ``started_at`` — UTC timestamp the run was started.
* ``notes`` — auto-populated, framework-managed log line buffer (see
  ``specs/state-store.md`` for the ``BaseState`` field set). This module
  declares the field; the engine-era bounded-merge writer that appended to
  it was removed with the rest of the dead state surface in CAL-613.

``extra="forbid"`` is set so an agent that hallucinates an unknown
state field is rejected rather than silently persisted.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["BaseState", "RUN_STATUSES", "RunStatus"]


# Canonical run-status enum — see ``specs/state-store.md`` ("status values").
# The SQLite column is ``TEXT NOT
# NULL`` without a CHECK constraint, so this Literal is the type-safe seam:
# writers + CLI readers import :data:`RUN_STATUSES` to validate the string
# they read out of the DB.
#
# Two lifecycles are folded into one set:
#
# * Verb model (current) — ``harness start`` opens a run as ``open`` and
#   ``harness close`` finalizes it to ``closed`` (CAL-583). These are the
#   statuses live code writes today.
# * Retired deterministic engine — ``pending``/``running``/``completed``/
#   ``failed``/``cancelled``/``stalled``/``paused`` were the per-node engine
#   states (``paused``/``stalled`` were the v1.5/H-025 lifecycle additions).
#   CAL-574 retired the engine; these are kept so historical rows still
#   validate (removing them is out of scope).
RunStatus = Literal[
    # verb model
    "open",
    "closed",
    # retired deterministic engine
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
    "stalled",
    "paused",
]

RUN_STATUSES: frozenset[str] = frozenset(get_args(RunStatus))
"""Runtime view of the canonical run statuses — derived from
:data:`RunStatus` so the two cannot drift."""


class BaseState(BaseModel):
    """Framework-defined fields prepended to every derived state class.

    See module docstring and ``specs/state-store.md`` for the full rationale.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    workflow_name: str
    base_branch: str
    worktree_path: Path | None = None
    worktree_branch: str | None = None
    artifacts_dir: Path
    started_at: datetime
    notes: list[str] = Field(default_factory=list)
