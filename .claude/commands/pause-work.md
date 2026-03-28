# Pause Work

Capture the current session state so the next session can resume exactly where you left off.

## When to use

- Context window running low (context-monitor warning)
- Session interrupted or ending
- Switching to a different task mid-work
- Before any forced session termination

## Instructions

1. **Identify current state.** Read the manifest and determine which task you're working on, its current status, and what branch/worktree you're in.

2. **Survey completed work.** Check `git log` for commits on this branch, `git diff` for uncommitted changes, and `git status` for untracked files.

3. **Write the handoff file.** Create `.continue-here.md` in the repo root (or worktree root) with this structure:

```markdown
# Session Handoff — {task name}

**Date:** {timestamp}
**Branch:** {branch name}
**Task:** {manifest task slug}
**Manifest status:** {current status}

## Completed
- {bullet list of what was done this session}

## In Progress
- {what was being worked on when paused, with specifics}

## Remaining
- {what still needs to be done to finish the task}

## Key Decisions
- {any decisions made during this session that the next session needs to know}

## Blockers
- {anything preventing progress, or "None"}

## Files Changed
- {list of files modified, added, or deleted}
```

4. **Commit everything.** Stage all changes including `.continue-here.md` and commit with message: `wip({scope}): pause — {brief description of state}`

5. **Push the branch.** Ensure the WIP state is on the remote so another session can pick it up.

6. **Report.** Tell the user what was saved and how to resume: "To resume, start a new session on branch `{branch}` — the handoff file at `.continue-here.md` has full context."

## Rules

- Never skip the handoff file — even if "nothing important" was done, document that
- Include specific file paths and line numbers when describing in-progress work
- If there are uncommitted changes that can't be committed (broken state), note that explicitly in the Blockers section
- The handoff file is ephemeral — the next session should delete it after reading
