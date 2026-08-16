<!-- guidance:ship@0.5.0 -->

**Tracker operations go through the `tracker` skill.** Read `CONTEXT.md`'s `tracker:` field and use the matching provider recipe — `linear` → the `linear` skill, `github` → the `github-issues` skill, `none` → the degrade the `tracker` skill documents. Do not embed provider API calls here.
# /ship — integrate and close

Usage: `/ship` (ships the current review-passed branch)

Integrates a branch the reviewer has PASSed, closes the ticket, and clears the in-flight spec. Runs after `/review` returns PASS.

## Preconditions

- `/review` returned PASS on this branch, and reported the `reviewed_tree` it bound to. A FAIL or a DEFER never reaches this command (`review-discipline` → *The verdict vocabulary*).
- **HEAD is still that tree.** The reviewer committed the as-built record into the candidate *before* certifying it (`review-discipline`'s *final-evidence ordering* rule), so the passing verdict already covers the record:

  ```bash
  git rev-parse HEAD^{tree}    # must equal the reviewed_tree /review reported
  ```

  The comparison is tree to tree, and `review-discipline` owns why — the same object the gate's evidence is named after, so a commit that rewrites no bytes voids nothing. Mismatch means content landed after the verdict, so what you would ship was never reviewed or verified. **Stop and re-run `/review`** to bind a fresh pass to the current tree — never a manual merge.
- The verification gate is green (`code-quality` Part C).

If any is missing, stop — do not ship unreviewed or unverified work.

## Steps

### 1. Confirm the branch model
Read `branches` in `CONTEXT.md`. Repos differ: some fast-forward feature branches straight to the integration branch with no PR; others require a PR into a protected branch. Follow what `CONTEXT.md` declares.

### 2. Integrate
Per the repo's model, either fast-forward the integration branch, or open the PR. Never force-push. Never push directly to a protected release branch unless `CONTEXT.md` says that is the path.

**The base moving is not a stop — the base-drift rule (ADR 0015).** Finding the integration branch ahead of where this branch forked is normal concurrency, never a reason to halt or ask the operator. Pull the latest integration branch, reconcile (merge it into the candidate, resolving textual conflicts on their plain meaning), re-run the verification gate on the reconciled tree, and — because the reconciled tree is no longer the `reviewed_tree` — re-run `/review` to bind a fresh pass before integrating (the preconditions above still hold; reconciliation does not bypass them). **Reconciliation is bounded here, and this is the bound's only home: two attempts.** Spend both, and the ticket is preserved and pushed, held through the `tracker` skill (`input` label, assigned to the operator) with a comment naming what would not reconcile, and the run stops rather than trying a third time. One trap inside that reconciliation: a monotonic field both sides advanced independently — a version number, a migration ordinal, a sequence id — converges on identical text, so the merge raises no conflict marker and the merged tree is a third state shipping under a value each side already claimed. Identical text is not agreement, so treat a same-valued monotonic field as a collision to detect rather than an agreement to accept, and advance past both sides. The **only** escalation is a genuine functional conflict: both changes are individually correct but want incompatible behaviour, so resolving it is a design call. That one case goes to the operator — hold the ticket per the `tracker` skill (`input` label, assigned) with a comment naming the two behaviours in tension. A textual overlap with an evident resolution is not that case.

### 3. Close the issue
Move it to Done and post the merge/PR link as a comment, both through the `tracker` skill. Under `tracker: none` this step is a no-op — report it as skipped and carry on; a missing tracker never suppresses steps 4–5. The change spec stays on the issue as history; there is no `manifest.yaml` to clean.

### 4. Confirm the durable record
The record is already inside the certified tree — the HEAD check above is what confirms it, since the reviewer committed it before the verdict. Nothing further to add here: the tree you integrated is the tree that was reviewed, and its `specs/features/` content is the canonical record going forward.

### 5. Clean up the worktree
Remove the task worktree and prune (`worktree-isolation`). Commit or discard any stragglers first.

## Report
Print what shipped: the issue, the integration target, the merge/PR link, and confirmation the worktree is cleaned up.
