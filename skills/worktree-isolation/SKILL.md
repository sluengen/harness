---
name: worktree-isolation
description: Sets a task up on its own branch in its own git worktree — choosing the base from the green pointer, linking gitignored local state into the new directory, giving each concurrent agent its own tree, and tearing the worktree and the resources it started down after merge. Use when starting any multi-commit task, when asked to "work on this in a worktree" or "branch off green", when several agents will run at once, or when cleaning up after a merged branch. Not for deciding what to build, running the gate, reviewing, or landing — the spine's lifecycle and `build` own those.
model: inherit
---
# Worktree Isolation

Any multi-commit task runs on its own branch in its own git worktree, so parallel work cannot collide, the default branch stays clean, and an interrupted task is resumable.

## The rule

**Never build on the default branch. One task, one branch, one worktree.**

## Creating the worktree

Branch off the **last integration commit known green**, not off the tip: concurrent runs land on the integration branch continuously, so its tip may carry a defect nobody has met yet, and starting there makes your first gate run red for somebody else's reason. The green pointer names that commit.

```bash
BASE="$(node <plugin-root>/scripts/harness-refs.js green-read)"; GREEN_STATUS=$?
git worktree add ../<repo>-<task-id> -b <task-id> "${BASE:-<integration-branch>}"
```

Keep the `$?` capture, because empty output has two unrelated causes and `${BASE:-…}` erases the difference between them:

- **Exit 0 with a commit id.** That is the pointer; you branched off green.
- **Exit 0 and empty.** No pointer has been published yet, so the fallback to the integration branch named in `harness.yaml` is the whole story.
- **Exit 2 and empty.** The pointer could not be read at all — an unreachable remote, or a repository whose integration branch could not be resolved — with the reason on stderr. The fallback still takes a safe base, so the run continues, but report that the pointer was not consulted: calling it "none published" describes a reachable remote holding no green commit, a different fault with a different fix.

**Report the base you took**: which commit, and whether it came from the pointer. A run that does not say where it started cannot tell a red base from a red change.

Work inside that directory for the whole task. Name the branch after the task; its ticket id is ideal.

## Linking heavy local artifacts

A fresh worktree does not have your gitignored local state — dependencies, env files, build caches — so symlink those from the shared repo root rather than reinstalling. Anchor both ends of every link to the shared root computed from git, never to `$PWD`, which on resume may already be the worktree and would make the link point at itself.

```bash
SHARED_ROOT="$(git rev-parse --path-format=absolute --git-common-dir)"; SHARED_ROOT="${SHARED_ROOT%/.git}"
# Link what this repo needs — see harness.yaml (e.g. the env file, the deps dir):
ln -sfn "$SHARED_ROOT/<env-file>"  "<worktree>/<env-file>"
ln -sfn "$SHARED_ROOT/<deps-dir>"  "<worktree>/<deps-dir>"
```

Pass `-n` so re-running replaces a stale link instead of nesting a new one inside it.

## Parallel sub-agents

Each concurrent agent gets its own worktree because two agents editing one working tree interleave their edits and corrupt each other's diffs, the single exception being a lone sub-agent sharing the orchestrator's worktree while the orchestrator is idle for the whole run.

## Cleanup

Cleanup is part of shipping a merged task; skip it and short-lived task artifacts accumulate on the host. Stop every temporary resource the task started before removing the files it runs from, then remove the worktree, prune git's administrative records, and delete the merged branch.

```bash
# Stop task-owned services before removing their files.
git worktree remove ../<repo>-<task-id>
git worktree prune
git branch -d <task-id>
```

Record each resource's identifier when you provision it, because that record is what makes ownership checkable at teardown. Remove only resources it owns: its own Docker Compose project's containers, images, networks and named volumes; its own iOS simulator app and build artifacts; the dev server process it started. Never select what to delete by a host-wide sweep or by another worktree's name, and never delete shared simulator devices, caches, volumes, or services. Skip resource teardown when the task started nothing, but always remove the merged worktree and branch. Delete a published remote task branch after merge when the hosting workflow permits it.

Commit or deliberately discard uncommitted work before cleanup: removing a worktree destroys it.

## Hygiene

- A file in `git status` you did not touch is a signal to investigate — a parallel worktree, a stash side-effect — not to commit (`engineering` → *Scope*).
- Do not assume another worktree's stash is stale; confirm before dropping it.
