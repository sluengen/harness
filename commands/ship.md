<!-- guidance:ship@0.2.0 -->
# /ship — integrate and close

Usage: `/ship` (ships the current review-passed branch)

Integrates a branch the reviewer has PASSed, closes the ticket, and clears the in-flight spec. Runs after `/review` returns PASS.

## Preconditions

- `/review` returned PASS on this branch, and reported the `reviewed_sha` it bound to.
- **HEAD is still that tree.** The reviewer committed the as-built record into the candidate *before* certifying it (`review-discipline`'s *final-evidence ordering* rule), so the passing verdict already covers the record:

  ```bash
  git rev-parse HEAD    # must equal the reviewed_sha /review reported
  ```

  Mismatch means something landed after the verdict, so what you would ship was never reviewed or verified. **Stop and re-run `/review`** to bind a fresh pass to the current HEAD. This is the agent-led twin of the harness's `stale_review` refusal, and it has the same remedy — never a manual merge.
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
The record is already inside the certified tree — the HEAD check above is what confirms it, since the reviewer committed it before the verdict. Nothing further to add here: the tree you integrated is the tree that was reviewed, and its `specs/features/` content is the canonical record going forward.

### 5. Clean up the worktree
Remove the task worktree and prune (`worktree-isolation`). Commit or discard any stragglers first.

## Report
Print what shipped: the Linear issue, the integration target, the merge/PR link, and confirmation the worktree is cleaned up.
