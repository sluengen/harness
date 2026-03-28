# Anti-Patterns Log

Mistakes we've made and patterns that failed. Every agent should read this file before starting work. When you discover a new anti-pattern — something that cost time, caused a bug, or led to rework — add it here so it doesn't happen again.

## Format

Each entry: what happened, why it failed, and what to do instead. Keep entries short and actionable.

---

## Process

### Don't bundle manifest updates with code commits
**What happened:** Merged a worktree branch that included both code changes and a manifest status update in the same commit. Another worktree branch also touched the manifest — merge conflict tangled implementation history with coordination state.
**Do instead:** Commit manifest updates separately from code/spec/design changes. Always.

### Don't assume stashes are stale
**What happened:** Ran `git stash drop` on what looked like duplicate work from an earlier session. It was active work from a parallel Claude Code session.
**Do instead:** Never drop a stash without showing the user what's in it and getting explicit approval.

### Don't skip lint before tests
**What happened:** Tests passed but reviewer caught lint failures. Had to fix, re-test, re-review.
**Do instead:** Run the linter first. A lint failure is a blocker — fix it before running tests.

### Don't remove adjacent sections when trimming prose
**What happened:** While thinning CLAUDE.md, removed the "Using Agents" prose section (replaced with a compact table) but accidentally deleted the "Agent Isolation — Worktrees Required" section directly above it — a distinct, unrelated block with critical rules.
**Do instead:** When trimming or replacing a section, check the boundaries carefully. Adjacent headings may contain independent rules that aren't covered by the replacement. Diff your edit against the original before committing.

---

## Adding new entries

When you encounter a pattern that caused rework, wasted time, or introduced a bug:

1. Add it under the appropriate section (or create a new section)
2. Follow the format: what happened → why it failed → what to do instead
3. Keep it to 3-4 lines. If it needs more explanation, it's probably an ADR.
4. Commit with: `docs(context): add anti-pattern — <short description>`
