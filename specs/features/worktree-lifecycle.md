---
feature: worktree-lifecycle
status: implemented
last_updated: 2026-07-04
linear: [CAL-590, CAL-661, CAL-693, CAL-739, CAL-767, CAL-935]
---

# Worktree lifecycle — isolated branch per run

> Every run builds in its own git worktree on its own branch, so file mutations never escape to the main working tree; `close` advances the base by merging that branch, then reclaims the worktree and branch it no longer needs.

## Behaviour

`harness start` creates an isolated worktree off the base branch; the agent does all its work there; `harness close` merges the branch back into the base and then tears the worktree and branch down. Worktree creation is a verb helper (`harness/worktree.py`, `WorktreeNode.create`), re-homed from the retired engine — the engine-era node wrapper and load-time graph validation are gone (CAL-574). Removal is single-sourced in `harness.cli._git.teardown_worktree`, the best-effort reclaim primitive shared by `start` rollback, `close`, and the `harness worktrees cleanup` sweep — so a run no longer leaks its worktree directory or branch (CAL-767).

### Create — off the base branch

`harness start` calls `WorktreeNode.create(run_id, repo_root, base)`.

The `base` is **resolved from the repo's branch model** rather than hardcoded (CAL-1106): an explicit `--base` wins, else `branches.integration` from the repo's CONTEXT.md, else the repo's origin default branch (`git symbolic-ref refs/remotes/origin/HEAD`), else `dev` as the back-compat fallback (`harness.cli._git.resolve_base_branch`). A repo configured `integration: dev` — like the harness itself — is unchanged; a `main`/`trunk` repo no longer has to pass `--base` on every call.

The worktree is **started from `origin/<base>`**, not the local `<base>` branch (CAL-1154, Option 1). Since `close` merges in a throwaway worktree and pushes `origin/<base>` without advancing the local branch (see *Merge back* below), the local branch lags the merged work; basing a new run off it would start every run on a stale tree. `start` resolves the clean-start commit-ish with `harness.cli._git.preferred_base_ref`: `origin/<base>` when it resolves, else the local `<base>` (offline / no-origin repos, or `origin` present but that branch never pushed) — so no-origin repos and much of the test suite behave exactly as before. The **recorded** `base_branch` (the merge target) is always the local name, unaffected.

#### Scenario: `harness start` creates the worktree

- GIVEN `harness start <ticket>` whose base branch `<base>` is resolved as above (default `dev`)
- WHEN the helper's `create` runs
- THEN it computes the canonical path `<repo_root>/.worktrees/harness/<run_id>/` and branch `harness/<run_id>`, creates the parent directory chain if needed, and runs `git -c worktree.useRelativePaths=true worktree add -b harness/<run_id> <path> <start_point>`, where `<start_point>` is `origin/<base>` when it resolves else the local `<base>`
- AND if the path already exists it raises rather than silently reuse; on a `git` failure it best-effort cleans up any half-baked directory before raising

#### Relative pointers — the worktree is usable from both the host and the container, with no flip

`create` writes the worktree's two pointer files — the worktree `.git` and the admin `<repo>/.git/worktrees/<run_id>/gitdir` — in **relative** form (`worktree.useRelativePaths=true`, git ≥ 2.48). This is load-bearing for the Docker wrapper: `harness start` runs *inside* the container, where the repo is mounted at `/workspace`, but the same worktree is also operated on from the host, where it lives at `/Users/...`. An **absolute** pointer baked at create time is valid in only one of those namespaces, so the operator previously had to hand-flip both files between container-form and host-form around every git operation — a fragile dance whose broken-worktree window let a concurrent `git worktree prune` delete the admin dir and its uncommitted work (CAL-866). A relative pointer resolves from the file's own location, so it is correct in *both* namespaces at once: no flip is ever needed, and `git worktree list` never marks the worktree spuriously `prunable` (CAL-935).

- GIVEN a worktree created in-container (repo mounted at `/workspace`)
- THEN both pointer files are relative, so host git (repo at `/Users/...`) and container git (repo at `/workspace`) each run `status` / `commit` / `worktree list` in the worktree with no restore step, and neither sees it as prunable
- AND because relative worktree pointers and the `extensions.relativeWorktrees` marker they stamp require git ≥ 2.48 — which the base image's Debian trixie does not ship (2.47.3) — the harness image compiles git 2.50.x from source (`docker/Dockerfile` `git-build` stage); a host using this worktree layout likewise needs git ≥ 2.48

### Resume — start the worktree from a preserved branch

`WorktreeNode.create` accepts an optional `start_point` that decouples the commit the new branch starts at from the recorded `base` (the merge target). `harness start --resume` uses it to **continue a reclaimed run from its checkpoint-pushed WIP branch** (CAL-739, proposal [`stale-run-reclamation`](../proposals/stale-run-reclamation.md) D4) instead of restarting cold.

#### Scenario: `harness start --resume` continues a reclaimed run

- GIVEN a `reclaimed` ticket whose dead run left a checkpoint-pushed branch `<wip>` on `origin` (the reclaim comment names it; [`reclaim`](run-ledger.md) preserved it)
- WHEN `harness start <ticket> --resume` runs
- THEN it reads `<wip>` from Linear (`LinearClient.fetch_resume_branch`), `git fetch origin <wip>`, and calls `create(..., base=<base>, start_point=<fetched SHA>)` — so the worktree's `harness/<run_id>` branch continues from the recovered WIP tip while `base_branch` stays `<base>`
- AND `close` therefore merges into `<base>` and its HEAD-bound gate keeps the resumed run safe from double-merge
- AND when no durable WIP exists — the reclaim preserved no branch, or `<wip>` no longer fetches — the resume `start_point` is `None` and it falls back to the ordinary clean start (off `origin/<base>`, else local `<base>`, per *Create* above) — best-effort; resume never blocks the queue

**What `--resume` fetches after a rebase.** `--resume` fetches whatever tip the dead run last *checkpointed to `origin`* — so the freshness of the resume point is exactly the freshness of the last successful checkpoint. Because [`checkpoint`](run-ledger.md) force-with-lease-pushes (CAL-1162), a rebase-before-close that rewrote `<wip>` **re-checkpoints cleanly**, and `--resume` fetches the rebased tip — not the stale pre-rebase one. The tip can be stale only when the final checkpoint after that rebase did **not** land: either it was never attempted (the run died between the rebase and the next checkpoint), or the force-with-lease lease *refused* it because `origin` carried a commit the run had not seen (`reason='stale_remote'`) — and that refusal is a **named outcome the run sees**, not a silent lapse. In that lapsed case `--resume` fetches the pre-rebase tip and the resumed run re-encounters the conflict the rebase had resolved; the durability guarantee is best-effort, and a stale resume degrades to redoing the rebase, never a wrong merge (the HEAD-bound `close` gate still holds).

### Rollback — `start` removes its own worktree on a later failure

`start` creates the worktree as a **local** side effect before it touches the ledger or Linear, so any later failure rolls it back.

#### Scenario: a duplicate-run or DB failure after create

- GIVEN `start` has created the worktree but a later step fails (the partial unique index rejects a duplicate open run, or the ledger insert fails)
- THEN `start` removes the worktree directly via `_cleanup_worktree_sync`, which delegates to `teardown_worktree` (`git worktree remove --force`, `git worktree prune`, `git branch -D harness/<run_id>`; no remote delete — the branch was never pushed) — best-effort, so a failed rollback never masks the original error

### Merge back — `close` merges in a throwaway worktree, then reclaims the run worktree

`harness close` merges the run branch into `origin/<base>` **in a throwaway worktree, never the main checkout** (`harness/close_merge.py`, mirroring `harness/promotion.py` — CAL-1154). It fetches `origin/<base>` (so a base that advanced during the run is integrated — CAL-777), creates a **detached** worktree at `.worktrees/harness/<run_id>-close` based on that current tip, runs `git merge --no-ff <worktree_branch>` in it, pushes the merge commit with `git push origin HEAD:<base>`, and tears the throwaway worktree down wholesale. The main checkout's working tree is not mutated on any path (success, conflict, or a rejected push), so the merge cannot strand it and two concurrent closes cannot collide in a shared tree — each has its own throwaway worktree, and a loser's non-fast-forward push is rejected and retries. The push advances the local `refs/remotes/origin/<base>` tracking ref on the same machine with no fetch, which is what the `start` / `worktrees cleanup` readers base off (the local `<base>` branch is **not** advanced by a close).

Once the merge has landed — and the ticket is Done and the ledger row closed — `close` calls `teardown_worktree(..., delete_remote=True)` to remove the **run** worktree directory and delete the branch both locally and on `origin` (a checkpoint may have pushed it). This teardown is **best-effort and runs last**: the close has already succeeded, so a teardown failure never fails it or undoes the merge — the housekeeping sweep reclaims anything left behind.

#### Scenario: a successful `close` reclaims its worktree and branch

- GIVEN an open run whose worktree HEAD has a passing review and a clean tree
- WHEN `harness close` merges, transitions the ticket Done, and closes the ledger row
- THEN it removes `<repo_root>/.worktrees/harness/<run_id>/`, deletes the local branch `harness/<run_id>`, and (best-effort) deletes it from `origin`
- AND if the teardown raises, the close still returns success (merged, ticket Done, status closed) — teardown is best-effort housekeeping after an already-successful close
- AND a gate refusal (`stale_review` / `dirty_worktree` / `no_run`) exits before any teardown, so the worktree survives for the agent to fix and re-review

### Housekeeping — `harness worktrees`

`harness worktrees list` discovers the worktrees under `<repo_root>/.worktrees/harness/`. `harness worktrees cleanup [--age <duration>] [--merged] [--force] [--db <p>]` is the safety-net sweep for worktrees `close` did not reclaim — a run whose container died before close's teardown step, or cruft from before self-cleaning close landed. It removes the worktree *directories* matching the filters via `teardown_worktree` (orphan-safe: an `rmtree` fallback reclaims a directory whose worktree registration is already pruned, which `git worktree remove` cannot touch). `--merged` additionally **deletes the merged branch** (local + on `origin`) — it is provably integrated, so dead weight; `--age` removes the directory but **retains the branch** (an aged worktree may still hold unmerged work).

**`--merged` is a merge-ancestry test, not a liveness test (#235).** `git merge-base --is-ancestor <branch> <base>` is true both for a branch that genuinely landed *and* for a fresh run branch that has made zero commits yet — its tip trivially equals the base. A run whose WIP is `git stash`'d rather than committed looks exactly like the second case, so ancestry alone is not sufficient to call a worktree safe to delete. Before honouring an ancestry-true match, `--merged` runs three vetoes and takes the first hit: (1) **ledger** — the run's `runs` row (matched by `worktree_path`, falling back to `run_id`) has a non-terminal status (`harness.state.schema.IN_FLIGHT_STATUSES`); (2) **stash** — `git stash list`, anchored in the worktree, has an entry naming this branch; (3) **dirty tree** — the worktree has uncommitted changes (`worktree_porcelain`). A vetoed worktree is kept (with the reason printed) unless `--force` is given, which removes it anyway and names what it overrode. The veto applies only to the `--merged` arm — an `--age`-driven removal of the same (old, vetoed) worktree still proceeds, retaining the branch, exactly as before. The Build routine (`/harness routine build`) runs `harness worktrees cleanup --merged --age 7d` in its pre-flight so the reclaim is automatic, not operator-only.

#### Scenario: `--merged` deletes the worktree and its branch

- GIVEN a worktree whose branch is merged into the repo's configured integration base (`branches.integration`, else the origin default, else `dev` — the same `resolve_base_branch` resolution `start` uses, CAL-1106), its branch pushed to `origin`, its run terminal (or unrecorded) in the ledger, no stash naming the branch, and a clean tree
- WHEN `harness worktrees cleanup --merged` runs
- THEN it checks ancestry against `origin/<base>` when it resolves — else the local base (`preferred_base_ref`, CAL-1154) — so a run merged into `origin/<base>` by a throwaway-worktree close (which never advances the local branch) is still recognised as merged; it removes the directory and deletes the branch locally and on `origin`
- AND an orphaned directory (no live worktree registration) older than `--age` is still removed via the `rmtree` fallback

#### Scenario: `--merged` skips an in-flight run whose WIP is only stashed (#235)

- GIVEN a worktree whose branch is a trivial ancestor of the base (no commits yet) because its run's WIP is `git stash`'d rather than committed, and its ledger row is still non-terminal (or, with no ledger DB, the stash alone stands as evidence)
- WHEN `harness worktrees cleanup --merged` runs
- THEN the worktree and its branch survive, and the kept line names the vetoing reason (the in-flight run, or the stash)
- AND `harness worktrees cleanup --merged --force` removes it anyway and names what it overrode

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
