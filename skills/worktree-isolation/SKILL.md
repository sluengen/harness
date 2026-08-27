---
name: worktree-isolation
description: Use when starting any multi-commit task — set it up on its own branch in its own git worktree, never on the default branch. Load before making changes, so work is isolated, resumable, and the default branch stays clean.
---
# Worktree Isolation

Any multi-commit task runs on its own branch in its own git worktree. This keeps parallel work from colliding, keeps the default branch clean, and makes an interrupted task resumable.

## The Rule

**Never build on the default branch. One task, one branch, one worktree.**

## Creating the worktree

From the repo root, branch off the integration branch named in `CLAUDE.md` (commonly `dev` or `main`):

```bash
git worktree add ../<repo>-<task-id> -b <task-id> <integration-branch>
```

Work inside that directory for the whole task. The branch name should identify the task (its ticket id is ideal).

## Linking heavy local artifacts

A fresh worktree does not have your gitignored local state (dependencies, env files, build caches). Symlink them from the shared repo root so tooling works, rather than reinstalling. Anchor both ends to the shared root computed from git, never to `$PWD` (on resume, `$PWD` may already be the worktree, which creates a self-pointing link):

```bash
SHARED_ROOT="$(git rev-parse --path-format=absolute --git-common-dir)"; SHARED_ROOT="${SHARED_ROOT%/.git}"
# Link what this repo needs — see CLAUDE.md (e.g. the env file, the deps dir):
ln -sfn "$SHARED_ROOT/<env-file>"  "<worktree>/<env-file>"
ln -sfn "$SHARED_ROOT/<deps-dir>"  "<worktree>/<deps-dir>"
```

Use `-n` so re-running replaces a stale link instead of nesting inside it.

## Parallel sub-agents

When two or more agents work at once, each must have its own worktree — mandatory, not optional. Two agents editing the same working tree corrupt each other's diffs. A lone sub-agent may share the orchestrator's worktree only if the orchestrator is idle during the run.

## Cleanup

When the task is merged, run cleanup as part of shipping. First stop and remove
every temporary resource the task created, then remove its worktree, prune Git's
administrative records, and delete the merged task branch:

```bash
# Stop task-owned services before removing their files.
git worktree remove ../<repo>-<task-id>
git worktree prune
git branch -d <task-id>
```

Name and retain the identifiers for each resource when provisioning it. Cleanup
only resources it owns: a per-worktree Compose project can remove its own
Docker containers, images, networks, and named volumes; a task can remove its
own iOS simulator app and build artifacts; a dev server can stop only the
process it started. Delete a published remote task branch after merge when the
hosting workflow permits it.

Never select by broad host-wide cleanup or another worktree's name. Do not
delete shared simulator devices, caches, volumes, or services. Skip resource
teardown when the task started nothing, but always remove a merged worktree and
branch. Without this lifecycle, short-lived task artifacts accumulate on the
host.

Uncommitted artifacts in a worktree are lost when it is removed. Commit (or deliberately discard) before cleanup.

## Hygiene

- A file appearing in `git status` that you did not touch is a signal to investigate (a parallel worktree, a stash side-effect), not to commit (`engineering` → *Scope*).
- Do not assume another worktree's stash is stale. Confirm before dropping it.
