---
name: worktree-isolation
description: Use when starting any multi-commit task — set it up on its own branch in its own git worktree, never on the default branch. Load before making changes, so work is isolated, resumable, and the default branch stays clean.
---
<!-- guidance:worktree-isolation@0.2.1 -->
# Worktree Isolation

Any multi-commit task runs on its own branch in its own git worktree. This keeps parallel work from colliding, keeps the default branch clean, and makes an interrupted task resumable.

## The Rule

**Never build on the default branch. One task, one branch, one worktree.**

## Creating the worktree

From the repo root, branch off the integration branch named in `CONTEXT.md` (commonly `dev` or `main`):

```bash
git worktree add ../<repo>-<task-id> -b <task-id> <integration-branch>
```

Work inside that directory for the whole task. The branch name should identify the task (its ticket id is ideal).

## Linking heavy local artifacts

A fresh worktree does not have your gitignored local state (dependencies, env files, build caches). Symlink them from the shared repo root so tooling works, rather than reinstalling. Anchor both ends to the shared root computed from git, never to `$PWD` (on resume, `$PWD` may already be the worktree, which creates a self-pointing link):

```bash
SHARED_ROOT="$(git rev-parse --path-format=absolute --git-common-dir)"; SHARED_ROOT="${SHARED_ROOT%/.git}"
# Link what this repo needs — see CONTEXT.md (e.g. the env file, the deps dir):
ln -sfn "$SHARED_ROOT/<env-file>"  "<worktree>/<env-file>"
ln -sfn "$SHARED_ROOT/<deps-dir>"  "<worktree>/<deps-dir>"
```

Use `-n` so re-running replaces a stale link instead of nesting inside it.

## Parallel sub-agents

When two or more agents work at once, each must have its own worktree — mandatory, not optional. Two agents editing the same working tree corrupt each other's diffs. A lone sub-agent may share the orchestrator's worktree only if the orchestrator is idle during the run.

## Cleanup

When the task is merged, tear down the worktree's Docker stack (if any), then remove the worktree and prune:

```bash
# From inside the worktree — scoped to THIS project only, safe while other
# worktrees' stacks run. Skip silently if the worktree has no compose stack.
docker compose down --rmi local -v --remove-orphans 2>/dev/null || true

git worktree remove ../<repo>-<task-id>
git worktree prune
```

`--rmi local` drops the image this project built (`<project>-backend`), `-v` its named volumes (`<project>_pgdata`); it targets only the current directory's project, never another worktree's. Without this, each per-worktree Compose stack orphans its tagged image and `pgdata` volume on the host.

Uncommitted artifacts in a worktree are lost when it is removed. Commit (or deliberately discard) before cleanup.

## Hygiene

- A file appearing in `git status` that you did not touch is a signal to investigate (a parallel worktree, a stash side-effect), not to commit (`code-quality` Part A).
- Do not assume another worktree's stash is stale. Confirm before dropping it.
