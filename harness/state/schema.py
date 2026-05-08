"""Framework-defined state base — see SPEC §6.

Every workflow produces a derived state class that subclasses
:class:`BaseState`. The derivation step (H-009,
:func:`harness.workflow.derive.derive_state_schema`) walks a
:class:`~harness.workflow.loader.LoadedWorkflow`, takes the union of
every step's ``writes:`` declarations, and adds one field per name on
top of the fields declared here.

The seven framework-supplied fields are populated by the engine when a
run begins:

* ``run_id`` — opaque identifier for this run.
* ``workflow_name`` — :attr:`Workflow.name`.
* ``base_branch`` — branch the run was started against (for worktree
  isolation).
* ``worktree_path`` / ``worktree_branch`` — populated when the run's
  first ``worktree.create`` step executes; ``None`` until then.
* ``artifacts_dir`` — where the run writes prompt transcripts, review
  artifacts, etc.
* ``started_at`` — UTC timestamp the run was started.
* ``notes`` — auto-populated, framework-managed log line buffer
  (SPEC §7 "Notes — framework-provided, auto-populated"). The bounded
  merge logic that appends to this list lives in H-010; H-009 only
  declares the field.

``extra="forbid"`` is set so an agent that hallucinates an unknown
state field is rejected rather than silently persisted.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["BaseState"]


class BaseState(BaseModel):
    """Framework-defined fields prepended to every derived state class.

    See module docstring and SPEC §6 for the full rationale.
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
