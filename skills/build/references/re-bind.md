# Post-verdict drift — the mechanically licensed re-bind

Load this when the integration branch moves again after PASS and the push
loses the race. Spending this path costs one of reconciliation's two attempts.

> **The T3 seam.** This file is the single home of the procedure below, and
> `skills/build/SKILL.md` reaches it by path without summarising a step. T3
> (#539) replaces this body with an invocation of its landing script and leaves
> the pointer in the SKILL untouched. No other file may restate a step, so
> there is exactly one place for that replacement to land.

A re-bind may skip delta review and a new final verdict **only** through this
conservative path. It exists because git alone can prove the merge added
nothing a reviewer has not already seen; the moment a human or an agent
resolves, edits or stages one byte, that proof is gone and so is the licence.

1. Keep the commit whose tree received PASS as `passed_commit`, fetch and pin the new integration tip as `incoming_tip`, and require `git merge-base --all <passed_commit> <incoming_tip>` to return exactly one `merge_base`. From that base, calculate the candidate and incoming changed-path sets with `git diff --no-ext-diff --no-renames --name-only -z <merge_base> <passed_commit>` and the same command ending in `<incoming_tip>`. Require the sets to be disjoint; compare the NUL-delimited paths without parsing human-readable diff output.
2. From a clean candidate, run `git merge --no-edit --no-ff <incoming_tip>` and let Git create the merge commit. Accept only a zero exit without a conflict or pause for resolution, an empty `git status --porcelain=v1 -z`, and exactly `passed_commit` then `incoming_tip` as the merge commit's parents. An agent or human must not resolve, edit, or stage any byte for this path.
3. Stage the complete result and capture it with `git add -A && git write-tree` as `merged_tree`. Run the repo's complete configured gate, read its full output, and require fresh gate evidence whose marker names exactly `merged_tree`.
4. Only then re-bind PASS to `merged_tree` and immediately resume the existing `HEAD^{tree}` equality check and push sequence. Record `<merge_base>..<incoming_tip>`, both parent commits, and the exact passed, incoming, merged, and marker trees in the run report.

Any ambiguity, conflict, resolution or edit, shared path, parent mismatch,
dirty index or worktree, unavailable or failed complete gate, missing or
wrong-tree marker, or tree mismatch returns to the normal reconciliation,
delta-review, complete-gate, and final-verdict path. No evidence or verdict
follows the old tree into that path.
