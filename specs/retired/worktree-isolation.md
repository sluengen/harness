# Worktree Isolation — WorktreeNode, branch lifecycle, cleanup policies

> **Superseded 2026-06-14** — this is the engine-era `WorktreeNode` reference. The live worktree behaviour (create off base, `close` merges the branch, `harness worktrees` housekeeping) is the as-built record in [`specs/features/worktree-lifecycle.md`](../features/worktree-lifecycle.md). Only `WorktreeNode.create` survives as a verb helper; the `cleanup` `CleanupPolicy` machinery and the engine-era load-time validation / runner adapter described below were **retired in CAL-693** (no live caller). Kept for historical reference only.

The worktree node manages git worktree lifecycle for a run: create an isolated branch, optionally merge it back, then remove it.

---

## Purpose

Code-mutating workflows run in an isolated git worktree so file mutations never escape to the main working tree. Worktree handling is a node type, not an engine feature — workflows opt in by declaring `worktree.create` and `worktree.cleanup` steps. Read-only workflows skip them.

---

## Key data structures

### `WorktreeCreateOutput`

Contract produced by `action: create`:

```python
class WorktreeCreateOutput(BaseModel):
    worktree_path: Path
    worktree_branch: str
```

The executor applies these via the step's `writes: [worktree_path, worktree_branch]` directly onto `BaseState`.

### `WorktreeCleanupOutput`

Contract produced by `action: cleanup`. Not written to state; surfaced in the event log only:

```python
class WorktreeCleanupOutput(BaseModel):
    worktree_removed: bool
    branch_removed: bool
    base_advanced: bool
```

### `CleanupPolicy`

`Literal["merge_to_base", "leave_for_inspection", "delete_unconditionally"]`

---

## Behaviour (as-implemented)

### `action: create`

1. Computes the canonical path: `<repo_root>/.worktrees/harness/<run_id>/`.
2. Computes the canonical branch: `harness/<run_id>`.
3. Raises `WorktreeNodeError` if the path already exists (never silently reuses).
4. Creates the parent directory chain (`<repo_root>/.worktrees/harness/`) if it doesn't exist.
5. Runs `git worktree add -b harness/<run_id> <path> <base>`.
6. On failure, attempts best-effort cleanup of any half-baked directory before raising `WorktreeNodeError`.

### `action: cleanup` — `merge_to_base`

1. Resolves the branch tip (`git rev-parse <worktree_branch>`).
2. Resolves the base tip (`git rev-parse <base>`).
3. Checks fast-forward eligibility: `git merge-base --is-ancestor <base_sha> <branch_sha>`. Raises `WorktreeNodeError` if not an ancestor (non-FF merge not supported).
4. Advances the base branch atomically: `git update-ref refs/heads/<base> <branch_sha> <base_sha>`.
5. Syncs the main working tree: `git read-tree --reset -u HEAD` (re-reads index and updates working-tree files to the new HEAD; required after `update-ref` to prevent phantom staged deletions).
6. Removes the worktree directory: `git worktree remove <path>`.
7. Prunes git's worktree metadata: `git worktree prune`.
8. Deletes the branch: `git branch -d <branch>`.

### `action: cleanup` — `leave_for_inspection`

Removes the worktree directory and prunes metadata, but keeps the branch. Idempotent: if the path no longer exists, it prunes and returns `worktree_removed=False`.

### `action: cleanup` — `delete_unconditionally`

Runs `git worktree remove --force <path>` and `git branch -D <branch>`. Tolerates uncommitted changes and ahead-branches. Missing branch is tolerated on force-delete.

---

## Path and branch conventions

| Item | Pattern |
|---|---|
| Worktree path | `<repo_root>/.worktrees/harness/<run_id>/` |
| Branch name | `harness/<run_id>` |

Every run gets a unique branch derived from its ULID run-id. No collisions between concurrent runs.

The `.worktrees/harness` path root has a single source — `harness.identity.WORKTREES_SUBDIR`. `harness.worktree.worktree_path(repo_root, run_id)` and `harness.cli.worktrees` both derive their repo-rooted paths from it, so a layout change is one edit (CAL-590). `worktree_path` does not validate the run-id (the lifecycle helper takes whatever id the caller created); `identity.worktree_dir` does.

The worktree adapter in `harness/engine/runner.py` resolves `$inputs.<key>` and `$state.<field>` references in the `base:` field at runtime before calling `WorktreeNode.create`.

---

## Load-time validation

The loader validates that any step with `writes_files: true` has a `worktree.create` ancestor in the dependency graph. The check walks steps in declaration order using both implicit predecessor edges and explicit `depends_on` edges. Loop steps inherit the loop's ancestors. Workflows failing this check are rejected at load time with a clear error.

---

## Notable constraints

- `merge_to_base` requires the worktree branch to be a fast-forward of the base. Any divergent history raises immediately.
- `WorktreeStep` is excluded from the normal `contract: → writes:` path. The executor treats it specially: no entry in `ctx.contracts`, and `type(result.contract)` serves as the effective contract type for write validation.
- The worktree node's `cleanup` method requires `worktree_path` and `worktree_branch` to be set on state; the runner's adapter raises `RuntimeError` if they are `None` at cleanup time.
- The CLI `worktrees cleanup` command is a separate operator tool for housekeeping (age/merged filters) and deliberately decoupled from `WorktreeNode`.
