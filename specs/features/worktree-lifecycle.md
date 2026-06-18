---
feature: worktree-lifecycle
status: implemented
last_updated: 2026-06-18
linear: [CAL-590, CAL-661, CAL-693, CAL-739, CAL-767]
---

# Worktree lifecycle — isolated branch per run

> Every run builds in its own git worktree on its own branch, so file mutations never escape to the main working tree; `close` advances the base by merging that branch, then reclaims the worktree and branch it no longer needs.

## Behaviour

`harness start` creates an isolated worktree off the base branch; the agent does all its work there; `harness close` merges the branch back into the base and then tears the worktree and branch down. Worktree creation is a verb helper (`harness/worktree.py`, `WorktreeNode.create`), re-homed from the retired engine — the engine-era node wrapper and load-time graph validation are gone (CAL-574). Removal is single-sourced in `harness.cli._git.teardown_worktree`, the best-effort reclaim primitive shared by `start` rollback, `close`, and the `harness worktrees cleanup` sweep — so a run no longer leaks its worktree directory or branch (CAL-767).

### Create — off the base branch

`harness start` calls `WorktreeNode.create(run_id, repo_root, base)`.

#### Scenario: `harness start` creates the worktree

- GIVEN `harness start <ticket>` with base branch `<base>` (default `dev`)
- WHEN the helper's `create` runs
- THEN it computes the canonical path `<repo_root>/.worktrees/harness/<run_id>/` and branch `harness/<run_id>`, creates the parent directory chain if needed, and runs `git worktree add -b harness/<run_id> <path> <base>`
- AND if the path already exists it raises rather than silently reuse; on a `git` failure it best-effort cleans up any half-baked directory before raising

### Resume — start the worktree from a preserved branch

`WorktreeNode.create` accepts an optional `start_point` that decouples the commit the new branch starts at from the recorded `base` (the merge target). `harness start --resume` uses it to **continue a reclaimed run from its checkpoint-pushed WIP branch** (CAL-739, proposal [`stale-run-reclamation`](../proposals/stale-run-reclamation.md) D4) instead of restarting cold.

#### Scenario: `harness start --resume` continues a reclaimed run

- GIVEN a `reclaimed` ticket whose dead run left a checkpoint-pushed branch `<wip>` on `origin` (the reclaim comment names it; [`reclaim`](run-ledger.md) preserved it)
- WHEN `harness start <ticket> --resume` runs
- THEN it reads `<wip>` from Linear (`LinearClient.fetch_resume_branch`), `git fetch origin <wip>`, and calls `create(..., base=<base>, start_point=<fetched SHA>)` — so the worktree's `harness/<run_id>` branch continues from the recovered WIP tip while `base_branch` stays `<base>`
- AND `close` therefore merges into `<base>` and its HEAD-bound gate keeps the resumed run safe from double-merge
- AND when no durable WIP exists — the reclaim preserved no branch, or `<wip>` no longer fetches — `start_point` is `None` and it falls back to a clean start off `<base>` (best-effort; resume never blocks the queue)

### Rollback — `start` removes its own worktree on a later failure

`start` creates the worktree as a **local** side effect before it touches the ledger or Linear, so any later failure rolls it back.

#### Scenario: a duplicate-run or DB failure after create

- GIVEN `start` has created the worktree but a later step fails (the partial unique index rejects a duplicate open run, or the ledger insert fails)
- THEN `start` removes the worktree directly via `_cleanup_worktree_sync`, which delegates to `teardown_worktree` (`git worktree remove --force`, `git worktree prune`, `git branch -D harness/<run_id>`; no remote delete — the branch was never pushed) — best-effort, so a failed rollback never masks the original error

### Merge back — `close` advances the base, then reclaims the worktree

From the main checkout `harness close` runs `git checkout <base>`, integrates the current `origin/<base>` (`git fetch origin <base>` then a `--ff-only` fast-forward of the local base to it, so a base that advanced during the run does not reject the push non-fast-forward — CAL-777), `git merge --no-ff <worktree_branch>`, and `git push origin <base>` (`harness/cli/close.py`). Once the merge has landed — and the ticket is Done and the ledger row closed — it calls `teardown_worktree(..., delete_remote=True)` to remove the worktree directory and delete the branch both locally and on `origin` (a checkpoint may have pushed it). The teardown is **best-effort and runs last**: the close has already succeeded, so a teardown failure never fails it or undoes the merge — the housekeeping sweep reclaims anything left behind.

#### Scenario: a successful `close` reclaims its worktree and branch

- GIVEN an open run whose worktree HEAD has a passing review and a clean tree
- WHEN `harness close` merges, transitions the ticket Done, and closes the ledger row
- THEN it removes `<repo_root>/.worktrees/harness/<run_id>/`, deletes the local branch `harness/<run_id>`, and (best-effort) deletes it from `origin`
- AND if the teardown raises, the close still returns success (merged, ticket Done, status closed) — teardown is best-effort housekeeping after an already-successful close
- AND a gate refusal (`stale_review` / `dirty_worktree` / `no_run`) exits before any teardown, so the worktree survives for the agent to fix and re-review

### Housekeeping — `harness worktrees`

`harness worktrees list` discovers the worktrees under `<repo_root>/.worktrees/harness/`. `harness worktrees cleanup [--age <duration>] [--merged]` is the safety-net sweep for worktrees `close` did not reclaim — a run whose container died before close's teardown step, or cruft from before self-cleaning close landed. It removes the worktree *directories* matching the filters via `teardown_worktree` (orphan-safe: an `rmtree` fallback reclaims a directory whose worktree registration is already pruned, which `git worktree remove` cannot touch). `--merged` additionally **deletes the merged branch** (local + on `origin`) — it is provably integrated, so dead weight; `--age` removes the directory but **retains the branch** (an aged worktree may still hold unmerged work). The Build routine (`/harness routine build`) runs `harness worktrees cleanup --merged --age 7d` in its pre-flight so the reclaim is automatic, not operator-only.

#### Scenario: `--merged` deletes the worktree and its branch

- GIVEN a worktree whose branch is merged into `dev` (or `main` / `master`), its branch pushed to `origin`
- WHEN `harness worktrees cleanup --merged` runs
- THEN it removes the directory and deletes the branch locally and on `origin`
- AND an orphaned directory (no live worktree registration) older than `--age` is still removed via the `rmtree` fallback

## Data model

The worktree feature has no persistent state of its own; `worktree_path` and `worktree_branch` are recorded on the [run ledger](run-ledger.md) `runs` row by `harness start`.

| Item | Pattern |
|---|---|
| Worktree path | `<repo_root>/.worktrees/harness/<run_id>/` |
| Branch name | `harness/<run_id>` |

Every run gets a unique branch derived from its ULID `run_id`, so concurrent runs never collide. The `.worktrees/harness` path root has a single source, `harness.identity.WORKTREES_SUBDIR`; both `harness.worktree.worktree_path(repo_root, run_id)` and the `harness worktrees` CLI derive their repo-rooted paths from it, so a layout change is one edit (CAL-590).

## Known limitations

- `close`'s teardown is best-effort: if it cannot reach `origin` to delete the remote branch (or its container dies first), the worktree or branch can survive that close. The `harness worktrees cleanup --merged --age 7d` sweep in the Build routine's pre-flight is the safety net that reclaims the remainder; it bounds the leak rather than eliminating every transient one.
- `WorktreeNode.create` does not validate the `run_id` it is handed; `harness.identity.worktree_dir` is the validating entry point.

> The engine-era `CleanupPolicy` machinery (`WorktreeNode.cleanup` — `merge_to_base` / `leave_for_inspection` / `delete_unconditionally`) was **retired in CAL-693**: it had no live caller (the live paths use direct git — `start` rollback, `close` merge, `worktrees cleanup`) and was exercised only by its own tests. Only `WorktreeNode.create` survives.

## Cross-references

- [`specs/retired/worktree-isolation.md`](../retired/worktree-isolation.md) — the engine-era `WorktreeNode` reference (historical; the `cleanup` machinery it documents is retired)
- [verb-model.md](verb-model.md) — `start` creates the worktree, `close` merges the branch
- [run-ledger.md](run-ledger.md) — where `worktree_path` / `worktree_branch` are recorded
- [cli-surface.md](cli-surface.md) — the `worktrees` housekeeping commands
