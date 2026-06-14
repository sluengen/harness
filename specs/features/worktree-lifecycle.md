---
feature: worktree-lifecycle
status: implemented
last_updated: 2026-06-14
linear: [CAL-590, CAL-661, CAL-693]
---

# Worktree lifecycle — isolated branch per run

> Every run builds in its own git worktree on its own branch, so file mutations never escape to the main working tree; `close` advances the base by merging that branch.

## Behaviour

`harness start` creates an isolated worktree off the base branch; the agent does all its work there; `harness close` merges the branch back into the base. Worktree creation is a verb helper (`harness/worktree.py`, `WorktreeNode.create`), re-homed from the retired engine — the engine-era node wrapper and load-time graph validation are gone (CAL-574). The worktree directory itself outlives `close`; the `harness worktrees` command is a separate operator tool that removes stale worktrees later.

### Create — off the base branch

`harness start` calls `WorktreeNode.create(run_id, repo_root, base)`.

#### Scenario: `harness start` creates the worktree

- GIVEN `harness start <ticket>` with base branch `<base>` (default `dev`)
- WHEN the helper's `create` runs
- THEN it computes the canonical path `<repo_root>/.worktrees/harness/<run_id>/` and branch `harness/<run_id>`, creates the parent directory chain if needed, and runs `git worktree add -b harness/<run_id> <path> <base>`
- AND if the path already exists it raises rather than silently reuse; on a `git` failure it best-effort cleans up any half-baked directory before raising

### Rollback — `start` removes its own worktree on a later failure

`start` creates the worktree as a **local** side effect before it touches the ledger or Linear, so any later failure rolls it back.

#### Scenario: a duplicate-run or DB failure after create

- GIVEN `start` has created the worktree but a later step fails (the partial unique index rejects a duplicate open run, or the ledger insert fails)
- THEN `start` removes the worktree directly — `git worktree remove --force`, `git worktree prune`, `git branch -D harness/<run_id>` (`_cleanup_worktree_sync`) — best-effort, so a failed rollback never masks the original error

### Merge back — `close` advances the base

`harness close` does **not** use the worktree helper or remove the worktree. From the main checkout it runs `git checkout <base>`, `git merge --no-ff <worktree_branch>`, and `git push origin <base>` (`harness/cli/close.py`). The worktree directory and branch remain on disk after a successful close; they are reclaimed later by the housekeeping command.

### Housekeeping — `harness worktrees`

`harness worktrees list` discovers the worktrees under `<repo_root>/.worktrees/harness/`. `harness worktrees cleanup [--age <duration>] [--merged]` removes the worktree *directories* matching the filters with `git worktree remove --force` (then surfaces what it removed); it **retains the branch**. It is an operator tool, decoupled from the per-run lifecycle, and uses direct git.

## Data model

The worktree feature has no persistent state of its own; `worktree_path` and `worktree_branch` are recorded on the [run ledger](run-ledger.md) `runs` row by `harness start`.

| Item | Pattern |
|---|---|
| Worktree path | `<repo_root>/.worktrees/harness/<run_id>/` |
| Branch name | `harness/<run_id>` |

Every run gets a unique branch derived from its ULID `run_id`, so concurrent runs never collide. The `.worktrees/harness` path root has a single source, `harness.identity.WORKTREES_SUBDIR`; both `harness.worktree.worktree_path(repo_root, run_id)` and the `harness worktrees` CLI derive their repo-rooted paths from it, so a layout change is one edit (CAL-590).

## Known limitations

- `close` leaves the worktree on disk; reclaiming it is the operator's `harness worktrees cleanup`, not an automatic step.
- `WorktreeNode.create` does not validate the `run_id` it is handed; `harness.identity.worktree_dir` is the validating entry point.

> The engine-era `CleanupPolicy` machinery (`WorktreeNode.cleanup` — `merge_to_base` / `leave_for_inspection` / `delete_unconditionally`) was **retired in CAL-693**: it had no live caller (the live paths use direct git — `start` rollback, `close` merge, `worktrees cleanup`) and was exercised only by its own tests. Only `WorktreeNode.create` survives.

## Cross-references

- [`specs/retired/worktree-isolation.md`](../retired/worktree-isolation.md) — the engine-era `WorktreeNode` reference (historical; the `cleanup` machinery it documents is retired)
- [verb-model.md](verb-model.md) — `start` creates the worktree, `close` merges the branch
- [run-ledger.md](run-ledger.md) — where `worktree_path` / `worktree_branch` are recorded
- [cli-surface.md](cli-surface.md) — the `worktrees` housekeeping commands
