"""Node protocol, NodeResult, Attestation, Artifacts — see SPEC §4.3.

The interface every node implements. Three node types in v1 (ai, script, check,
decision, worktree) all return a NodeResult; the engine reads `contract` for
state writes and `attestation` only for the event log — never for control flow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T", bound=BaseModel)


class Attestation(BaseModel):
    """The agent's self-report — informational only, never load-bearing.

    Engine rule (SPEC §4.3): control flow may read `state` and `check`-node
    results. It may NOT read `attestation`. This is for the event log and human
    debugging. If you find yourself wanting to branch on attestation.status,
    promote the field into the contract proper.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["complete", "partial", "blocked"]
    reasoning: str = ""


class Artifacts(BaseModel):
    """File-system mutations made during a node's execution.

    Populated by the executor by snapshotting `git diff` / `git status` before
    and after the agent call. The list of `files_changed` is validated to be
    inside `state.worktree_path` — anything escaping that boundary is a bug
    in the agent harness or the worktree node setup.
    """

    model_config = ConfigDict(extra="forbid")

    diff: str | None = None
    commit_sha: str | None = None
    files_changed: list[Path] = Field(default_factory=list)


class NodeResult(BaseModel, Generic[T]):
    """The standardised return shape from every node.

    `contract` is the typed deliverable the workflow asked for; `writes:` then
    extracts the requested fields and applies them to state. `attestation` is
    informational. `artifacts` records what changed on disk.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    contract: T
    attestation: Attestation
    artifacts: Artifacts = Field(default_factory=Artifacts)


class Node(Protocol):
    """Every node implements `execute` and declares its `type`.

    Implementations: AINode (H-014), ScriptNode (H-015), CheckNode (H-016),
    DecisionNode (H-017), WorktreeNode (H-018).
    """

    type: Literal["ai", "script", "check", "decision", "worktree"]

    async def execute(self, *args: object, **kwargs: object) -> NodeResult[BaseModel]:
        ...
