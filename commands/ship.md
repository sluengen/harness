<!-- guidance:ship@0.1.3 -->
# /ship — integrate and close

Usage: `/ship` (ships the current review-passed branch)

Integrates a branch the reviewer has PASSed, closes the ticket, and clears the in-flight spec. Runs after `/review` returns PASS.

## Preconditions

- `/review` returned PASS on this branch.
- The reviewer has recorded the shipped behaviour to `specs/features/` (the last commit on the branch).
- The verification gate is green (`code-quality` Part C).

If any is missing, stop — do not ship unreviewed or unverified work.

## Steps

### 1. Confirm the branch model
Read `branches` in `CONTEXT.md`. Repos differ: some fast-forward feature branches straight to the integration branch with no PR; others require a PR into a protected branch. Follow what `CONTEXT.md` declares.

### 2. Integrate
Per the repo's model, either fast-forward the integration branch, or open the PR. Never force-push. Never push directly to a protected release branch unless `CONTEXT.md` says that is the path.

### 3. Close the Linear issue
Move it to Done (`linear` status mapping). Post the merge/PR link as a comment. The change spec stays on the issue as history; there is no `manifest.yaml` to clean.

### 4. Confirm the durable record
The reviewer recorded what shipped to `specs/features/` on PASS (the last commit before merge). Confirm that commit is present in what you are integrating — it is the canonical record going forward.

### 5. Clean up the worktree
Remove the task worktree and prune (`worktree-isolation`). Commit or discard any stragglers first.

## Report
Print what shipped: the Linear issue, the integration target, the merge/PR link, and confirmation the worktree is cleaned up.
