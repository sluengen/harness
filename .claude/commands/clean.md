# Clean

Post-merge cleanup: mark tasks done, update Linear, clean up local branches and worktrees.

## When to use

After a PR has been merged and the source branch pruned at origin. The user will typically say something like "merged, branch pruned at source" or just run `/clean`.

## Instructions

1. **Identify what was merged.** Check `git log` on the current branch (or staging/main) to find the recent merge commit(s). Identify which manifest tasks and Linear issues were part of the merged PR. If the PR URL is known from the manifest or conversation context, use it.

2. **Update the manifest.** For each task that was part of the merged PR:
   - Set `status: done`
   - Add `completed_date: '{YYYY-MM-DD}'` (today)
   - Add `pr:` with the PR URL if not already present
   - Read the manifest before editing.

3. **Update Linear** (if project uses Linear). Set each corresponding Linear issue to `Done` (use `linear_id` from the manifest entry). Also mark any parent issues as Done if all sub-tasks are now complete.

4. **Clean up locally.**
   - Switch to `staging` (or `main` if that's the base) and pull latest
   - Delete the local feature branch: `git branch -d {branch}`
   - Prune stale remote refs: `git remote prune origin`
   - Remove any leftover worktree directories: `rm -rf .worktrees/agent-*` and `git worktree prune`

5. **Commit the manifest update.** Stage and commit the manifest change with message: `manifest: mark {task list} done`

6. **Push.** Push the manifest update to the remote.

7. **Report.** Confirm what was cleaned up: tasks marked done, Linear issues closed (if applicable), branches deleted, worktrees removed.

## Rules

- Never delete branches that have unmerged commits without asking the user first
- If `git branch -d` fails (unmerged), warn the user instead of force-deleting
- If there are uncommitted changes on the current branch, stash them and warn the user before switching branches
- If the manifest task is already marked `done`, skip it
- If Linear is not configured for this project, skip Linear update steps silently
