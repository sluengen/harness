"""Worktree lifecycle — create/cleanup with three policies — see SPEC §4.5.

This module owns the git worktree lifecycle for a run. It was re-homed here
from the retired ``harness.nodes`` package (CAL-574): the verbs call it
directly as a standalone helper — there is no longer a workflow engine routing
a step's ``action:`` to a node. Two operations:

* ``create`` — make a new worktree at ``<repo>/.worktrees/harness/<run_id>/``
  on a fresh branch ``harness/<run_id>`` starting at ``base``. ``harness start``
  reads ``worktree_path`` / ``worktree_branch`` off the returned output.
* ``cleanup`` — apply one of three policies:
    - ``merge_to_base``: fast-forward ``base`` to the worktree branch's tip,
      then delete the worktree directory and the branch. Anything other
      than a clean ff is a real failure (raised), not partial success.
    - ``leave_for_inspection``: remove the worktree dir, keep the branch.
      Idempotent — calling again with the dir already removed is a no-op
      that returns ``worktree_removed=False``.
    - ``delete_unconditionally``: ``git worktree remove --force`` and
      ``git branch -D``; tolerates uncommitted changes and ahead-branches.

The helper never reaches into ``harness.state`` directly — its only outputs are
the two Pydantic result models the caller consumes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from harness.identity import WORKTREES_SUBDIR

__all__ = [
    "WORKTREES_SUBDIR",
    "CleanupPolicy",
    "WorktreeCleanupOutput",
    "WorktreeCreateOutput",
    "WorktreeNode",
    "WorktreeNodeError",
    "worktree_path",
]


CleanupPolicy = Literal[
    "merge_to_base",
    "leave_for_inspection",
    "delete_unconditionally",
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


class WorktreeCleanupOutput(BaseModel):
    """Result of ``cleanup`` — reports what the policy actually did."""

    model_config = ConfigDict(extra="forbid")

    worktree_removed: bool
    branch_removed: bool
    base_advanced: bool


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


def _branch_for(run_id: str, prefix: str = "harness") -> str:
    """The canonical branch name for a given run id."""
    return f"{prefix}/{run_id}"


class WorktreeNode:
    """Stateless wrapper around ``git worktree`` for harness runs.

    The class is split into ``create`` and ``cleanup`` rather than a single
    dispatch method so callers (and tests) can pick the right shape directly.
    """

    async def create(
        self,
        *,
        run_id: str,
        repo_root: Path,
        base: str,
        branch_prefix: str = "harness",
    ) -> WorktreeCreateOutput:
        """Create a worktree at ``<repo>/.worktrees/harness/<run_id>/`` from ``base``.

        Raises
        ------
        WorktreeNodeError
            * if the destination path already exists (we never silently
              reuse an existing worktree — that would mask state bugs)
            * if ``git worktree add`` fails (e.g. unknown ``base``).
        """
        path = worktree_path(repo_root, run_id)
        branch = _branch_for(run_id, prefix=branch_prefix)

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
            base,
        )
        if rc != 0:
            # Git refuses to create the worktree on a bad base; ensure no
            # half-baked dir survives so AC7 is honoured.
            if path.exists():
                # Best-effort cleanup; if this fails the original error wins.
                await _git(repo_root, "worktree", "remove", "--force", str(path))
                await _git(repo_root, "worktree", "prune")
            raise WorktreeNodeError(
                f"git worktree add failed (base={base!r}): {stderr.strip()}"
            )

        return WorktreeCreateOutput(
            worktree_path=path,
            worktree_branch=branch,
        )

    async def cleanup(
        self,
        *,
        run_id: str,
        repo_root: Path,
        worktree_path: Path,
        worktree_branch: str,
        base: str | None,
        policy: CleanupPolicy,
    ) -> WorktreeCleanupOutput:
        """Apply the cleanup ``policy``. ``base`` is required for ``merge_to_base``."""
        if policy == "merge_to_base":
            return await self._cleanup_merge_to_base(
                repo_root=repo_root,
                worktree_path=worktree_path,
                worktree_branch=worktree_branch,
                base=base,
            )
        if policy == "leave_for_inspection":
            return await self._cleanup_leave(
                repo_root=repo_root,
                worktree_path=worktree_path,
            )
        if policy == "delete_unconditionally":
            return await self._cleanup_delete(
                repo_root=repo_root,
                worktree_path=worktree_path,
                worktree_branch=worktree_branch,
            )
        # Defensive: callers pass a fixed literal, but stay strict.
        raise WorktreeNodeError(f"unknown cleanup policy: {policy!r}")

    # ------------------------------------------------------------------
    # Policy implementations
    # ------------------------------------------------------------------

    async def _cleanup_merge_to_base(
        self,
        *,
        repo_root: Path,
        worktree_path: Path,
        worktree_branch: str,
        base: str | None,
    ) -> WorktreeCleanupOutput:
        if base is None:
            raise WorktreeNodeError("merge_to_base requires `base`")

        # Refuse if the base working tree or index is dirty. The
        # ``git read-tree --reset -u HEAD`` call that syncs the index
        # after the ref update would overwrite local modifications —
        # refuse early with a clear message so no work is lost.
        rc, porcelain_out, _ = await _git(repo_root, "status", "--porcelain")
        dirty_lines = [
            line for line in porcelain_out.splitlines()
            if line and not line.startswith("??") and not line.startswith("!!")
        ]
        if dirty_lines:
            raise WorktreeNodeError(
                f"merge_to_base refused: base repo working tree or index is dirty — "
                f"commit or stash changes before merging, or run in a clean CI checkout. "
                f"Dirty files: {', '.join(line[3:].strip() for line in dirty_lines)}"
            )

        # Resolve the worktree branch tip and the base tip up front. If either
        # fails, the worktree is missing or the run state is corrupt.
        rc, branch_tip, stderr = await _git(repo_root, "rev-parse", worktree_branch)
        if rc != 0:
            raise WorktreeNodeError(
                f"cannot resolve worktree branch {worktree_branch!r}: {stderr.strip()}"
            )
        branch_sha = branch_tip.strip()

        rc, base_head, stderr = await _git(repo_root, "rev-parse", base)
        if rc != 0:
            raise WorktreeNodeError(
                f"cannot resolve base branch {base!r}: {stderr.strip()}"
            )
        base_sha = base_head.strip()

        # FF-merge condition: base_sha must be an ancestor of branch_sha.
        rc, _stdout, _stderr = await _git(
            repo_root, "merge-base", "--is-ancestor", base_sha, branch_sha
        )
        if rc != 0:
            raise WorktreeNodeError(
                f"merge_to_base refused: {base!r} is not an ancestor of "
                f"{worktree_branch!r} — fast-forward impossible"
            )

        # Atomically advance base → branch_sha (no checkout disturbance).
        rc, _stdout, stderr = await _git(
            repo_root,
            "update-ref",
            f"refs/heads/{base}",
            branch_sha,
            base_sha,
        )
        if rc != 0:
            raise WorktreeNodeError(
                f"update-ref refs/heads/{base} failed: {stderr.strip()}"
            )

        # Sync the main working tree's index and files to the new HEAD.
        #
        # ``git update-ref`` moved the ref but left the index pointing at the
        # old tree, so ``git status`` would show every new/changed file as
        # staged for reversal — phantom deletions ready to be committed.
        # ``read-tree --reset -u HEAD`` re-reads the index from the new commit
        # and updates working-tree files that differ between old and new index
        # (all work happened in the isolated worktree so there are no local
        # modifications to lose). ``--reset`` is required; bare ``-u`` is
        # invalid without -m/--reset/--prefix.
        rc, _stdout, stderr = await _git(repo_root, "read-tree", "--reset", "-u", "HEAD")
        if rc != 0:
            raise WorktreeNodeError(
                f"read-tree HEAD failed after advancing {base}: {stderr.strip()}"
            )

        # Remove the worktree dir + branch. If the worktree dir is already
        # gone (a previous half-cleanup), `worktree remove` will fail; treat
        # that as the dir being already removed and continue with prune.
        worktree_removed = await self._git_worktree_remove(
            repo_root, worktree_path, force=False
        )
        await _git(repo_root, "worktree", "prune")
        branch_removed = await self._git_branch_delete(
            repo_root, worktree_branch, force=False
        )

        return WorktreeCleanupOutput(
            worktree_removed=worktree_removed,
            branch_removed=branch_removed,
            base_advanced=True,
        )

    async def _cleanup_leave(
        self,
        *,
        repo_root: Path,
        worktree_path: Path,
    ) -> WorktreeCleanupOutput:
        if not worktree_path.exists():
            # Idempotent re-cleanup: nothing to remove. We still prune so any
            # stale metadata from a prior partial removal is cleared.
            await _git(repo_root, "worktree", "prune")
            return WorktreeCleanupOutput(
                worktree_removed=False,
                branch_removed=False,
                base_advanced=False,
            )

        worktree_removed = await self._git_worktree_remove(
            repo_root, worktree_path, force=False
        )
        await _git(repo_root, "worktree", "prune")

        return WorktreeCleanupOutput(
            worktree_removed=worktree_removed,
            branch_removed=False,
            base_advanced=False,
        )

    async def _cleanup_delete(
        self,
        *,
        repo_root: Path,
        worktree_path: Path,
        worktree_branch: str,
    ) -> WorktreeCleanupOutput:
        worktree_removed = await self._git_worktree_remove(
            repo_root, worktree_path, force=True
        )
        await _git(repo_root, "worktree", "prune")
        branch_removed = await self._git_branch_delete(
            repo_root, worktree_branch, force=True
        )

        return WorktreeCleanupOutput(
            worktree_removed=worktree_removed,
            branch_removed=branch_removed,
            base_advanced=False,
        )

    # ------------------------------------------------------------------
    # Low-level git wrappers
    # ------------------------------------------------------------------

    async def _git_worktree_remove(
        self,
        repo_root: Path,
        worktree_path: Path,
        *,
        force: bool,
    ) -> bool:
        """Remove a worktree.

        Returns True iff the worktree was actually removed by this call.
        Raises WorktreeNodeError when the call fails for a non-missing
        reason (e.g. dirty worktree without ``--force``).
        """
        if not worktree_path.exists():
            # A path that never existed at all is a strict failure under
            # ``merge_to_base``; the merge step already validated the branch,
            # so reaching this branch with a missing worktree means the
            # caller asked us to clean up something we never made.
            raise WorktreeNodeError(
                f"worktree path does not exist: {worktree_path}"
            )

        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(worktree_path))
        rc, _stdout, stderr = await _git(repo_root, *args)
        if rc != 0:
            raise WorktreeNodeError(
                f"git worktree remove failed for {worktree_path}: {stderr.strip()}"
            )
        return True

    async def _git_branch_delete(
        self,
        repo_root: Path,
        branch: str,
        *,
        force: bool,
    ) -> bool:
        """Delete a local branch. Returns True iff actually deleted."""
        flag = "-D" if force else "-d"
        rc, _stdout, stderr = await _git(repo_root, "branch", flag, branch)
        if rc != 0:
            # Tolerate missing branch on force-delete; raise otherwise so
            # merge_to_base catches a real inconsistency.
            stderr_low = stderr.lower()
            if force and ("not found" in stderr_low or "no such" in stderr_low):
                return False
            raise WorktreeNodeError(
                f"git branch {flag} {branch} failed: {stderr.strip()}"
            )
        return True
