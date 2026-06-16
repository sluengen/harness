"""Worktree lifecycle — create an isolated worktree per run — see SPEC §4.5.

This module owns git worktree creation for a run. It was re-homed here from the
retired ``harness.nodes`` package (CAL-574): the verbs call it directly as a
standalone helper — there is no longer a workflow engine routing a step's
``action:`` to a node. One operation survives:

* ``create`` — make a new worktree at ``<repo>/.worktrees/harness/<run_id>/``
  on a fresh branch ``harness/<run_id>`` starting at ``base``. ``harness start``
  reads ``worktree_path`` / ``worktree_branch`` off the returned output.

The engine-era ``cleanup`` half (the ``CleanupPolicy`` node — ``merge_to_base``
/ ``leave_for_inspection`` / ``delete_unconditionally``) was retired in CAL-693:
it had no production caller after CAL-574. The live paths use direct git —
``harness start`` rolls a failed run back with ``_cleanup_worktree_sync``,
``harness close`` merges with ``git merge --no-ff``, and ``harness worktrees
cleanup`` removes stale directories (see
``specs/features/worktree-lifecycle.md``).

The helper never reaches into ``harness.state`` directly — its only output is
the Pydantic result model the caller consumes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from harness.identity import BRANCH_PREFIX, WORKTREES_SUBDIR

__all__ = [
    "BRANCH_PREFIX",
    "WORKTREES_SUBDIR",
    "WorktreeCreateOutput",
    "WorktreeNode",
    "WorktreeNodeError",
    "worktree_path",
]


class WorktreeNodeError(RuntimeError):
    """Raised when a git worktree operation fails or is misused."""


class WorktreeCreateOutput(BaseModel):
    """Result of ``create``.

    ``harness start`` reads ``worktree_path`` / ``worktree_branch`` directly off
    this output when recording the run.
    """

    model_config = ConfigDict(extra="forbid")

    worktree_path: Path
    worktree_branch: str


async def _git(repo: Path, *args: str) -> tuple[int, str, str]:
    """Run ``git <args>`` non-blockingly inside ``repo`` and return ``(rc, stdout, stderr)``."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(repo),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout.decode(), stderr.decode()


def worktree_path(repo_root: Path, run_id: str) -> Path:
    """The canonical worktree location for a run: ``<repo>/.worktrees/harness/<run_id>``.

    Derives from :data:`harness.identity.WORKTREES_SUBDIR` so the layout has one
    source. Unlike :func:`harness.identity.worktree_dir`, this does **not**
    validate ``run_id`` as a ULID — the lifecycle helper operates on whatever id
    the caller created.
    """
    return repo_root / WORKTREES_SUBDIR / run_id


def _branch_for(run_id: str, prefix: str = BRANCH_PREFIX) -> str:
    """The branch name for a run: the unvalidated, configurable-prefix lifecycle home.

    Defaults to :data:`harness.identity.BRANCH_PREFIX` so the namespace literal
    has one source. Unlike :func:`harness.identity.worktree_branch`, this does
    **not** validate ``run_id`` and accepts a caller-chosen ``prefix`` — the two
    share the literal but keep separate contracts by design (CAL-719). The
    configurable prefix is a tested feature (``test_create_custom_branch_prefix``
    asserts a ``slate/`` prefix).
    """
    return f"{prefix}/{run_id}"


class WorktreeNode:
    """Stateless wrapper around ``git worktree add`` for harness runs.

    Only ``create`` survives; the engine-era ``cleanup`` policy machinery was
    retired in CAL-693 (no live caller — the verbs use direct git).
    """

    async def create(
        self,
        *,
        run_id: str,
        repo_root: Path,
        base: str,
        branch_prefix: str = BRANCH_PREFIX,
        start_point: str | None = None,
    ) -> WorktreeCreateOutput:
        """Create a worktree at ``<repo>/.worktrees/harness/<run_id>/``.

        The new branch starts at ``start_point`` when given, else at ``base``.
        Decoupling the two lets a run **resume** from a preserved WIP branch while
        still merging back into ``base``: ``harness start --resume`` (CAL-739)
        passes the checkpoint-pushed branch (or its SHA) as ``start_point`` so the
        worktree continues the dead run's work, but records ``base`` as the merge
        target unchanged — so ``close`` merges into ``base`` and its HEAD-bound
        gate keeps the resumed run safe from double-merge. With ``start_point``
        omitted this is the ordinary clean start off ``base``.

        Raises
        ------
        WorktreeNodeError
            * if the destination path already exists (we never silently
              reuse an existing worktree — that would mask state bugs)
            * if ``git worktree add`` fails (e.g. unknown ``base``/``start_point``).
        """
        path = worktree_path(repo_root, run_id)
        branch = _branch_for(run_id, prefix=branch_prefix)
        commit_ish = start_point if start_point is not None else base

        if path.exists():
            raise WorktreeNodeError(
                f"worktree already exists at {path}; refusing to reuse — "
                f"clean it up first"
            )

        # Make sure the parent directory chain is present; `git worktree add`
        # will create the leaf, but it expects the .worktrees/harness/ prefix.
        path.parent.mkdir(parents=True, exist_ok=True)

        rc, _stdout, stderr = await _git(
            repo_root,
            "worktree",
            "add",
            "-b",
            branch,
            str(path),
            commit_ish,
        )
        if rc != 0:
            # Git refuses to create the worktree on a bad start point; ensure no
            # half-baked dir survives so AC7 is honoured.
            if path.exists():
                # Best-effort cleanup; if this fails the original error wins.
                await _git(repo_root, "worktree", "remove", "--force", str(path))
                await _git(repo_root, "worktree", "prune")
            raise WorktreeNodeError(
                f"git worktree add failed (start_point={commit_ish!r}): {stderr.strip()}"
            )

        return WorktreeCreateOutput(
            worktree_path=path,
            worktree_branch=branch,
        )
