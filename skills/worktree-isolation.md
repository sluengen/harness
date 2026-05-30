# Worktree Isolation

Canonical rule for git-worktree use in this repo.

## The rule

**When making changes that involve multiple commits or sub-agent dispatch, work inside a git worktree — not the shared repo root.**

The shared repo root has one `.git/HEAD`. Any other Claude Code session (or accidental command) can `git checkout` and silently move HEAD under your feet. A worktree gives you your own HEAD and index while sharing the object database.

For one-off edits to a single file in the main repo, the discipline is optional. For anything multi-step, use a worktree.

## When sub-agents need their own worktree

Sub-agents that write code (`python-dev`, `reviewer` if it ever fixes issues, etc.) need `isolation: "worktree"` when:

- The orchestrator is still in the shared repo root, **OR**
- Multiple sub-agents are dispatched in the same turn and would otherwise collide on the same tree, **OR**
- The orchestrator may edit files in parallel with the sub-agent's run.

A single sub-agent dispatched while the orchestrator is in its own worktree and idle during the dispatch can share the orchestrator's worktree — but when in doubt, use isolation. Overhead is small, collision cost is lost work.

## Procedure — orchestrator entry

At the top of any multi-commit flow (`/start`, manual long sessions, etc.):

```bash
cd ~/Documents/1_Projects/harness

# Pick a worktree name. For /start, use the issue ID (H-NNN); it's already unique.
# For ad-hoc sessions, use a timestamp so parallel sessions don't collide.
WORKTREE=".worktrees/<H-NNN>"          # or: ".worktrees/session-$(date +%Y-%m-%d-%H%M%S)"
BRANCH="harness/<H-NNN>-<short-slug>"  # or: "session/<timestamp>"

git fetch origin
git worktree add "$WORKTREE" -b "$BRANCH" main
cd "$WORKTREE"
```

All subsequent commits and sub-agent dispatches happen from inside the worktree.

## Procedure — fresh dependencies in the worktree

The worktree starts with no `.venv/`. `uv sync --extra dev` from inside the worktree creates a fresh venv there. This is fast (uv is fast) and means the worktree is fully self-contained.

If you want to share the venv with the main repo to skip reinstall:

```bash
ln -sfn ../../.venv .venv   # from inside the worktree
```

Trade-off: a `uv sync` in either tree affects both. For solo dev that's usually fine. If you hit lockfile drift, recreate the worktree's venv.

## Commit safety

From inside a worktree:

- Stage specific paths: `git add path/to/file` or `git add path/to/dir/`.
- **Avoid** `git add -A`, `git add .`, `git add --all` — these can sweep symlinks or untracked files from parallel sessions.
- Before committing, `git diff --cached --stat` should not list anything you didn't intend to change.

## Exit — orchestrator

When the session ends:

1. Push the branch from inside the worktree: `git push -u origin <branch>`.
2. Open the PR (or wait for the user to do it).
3. `cd` back to the shared repo root.
4. Leave the worktree in place until the PR merges. Removing it prematurely loses the branch's reflog.

After merge, prune:

```bash
cd ~/Documents/1_Projects/harness
git worktree remove .worktrees/<H-NNN>
git branch -d harness/<H-NNN>-<short-slug>   # local
git push origin --delete harness/<H-NNN>-<short-slug>   # remote
```

## What this skill does NOT cover

- Branch strategy (we branch off `main`, PR back to `main` — see CLAUDE.md).
- Sub-agent worktree internals — those are managed by the Agent runtime when `isolation: "worktree"` is set.
- The harness project's own worktree-node design (`harness/nodes/worktree.py`). That's the implementation; this skill is the *development discipline*. They're related but distinct.
