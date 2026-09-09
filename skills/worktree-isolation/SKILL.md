---
name: worktree-isolation
description: Sets a task up on its own branch in its own git worktree — choosing and gating the base before the branch is cut, linking gitignored local state into the new directory, giving each concurrent agent its own tree, and tearing the worktree and the resources it started down after merge. Use when starting any multi-commit task, when asked to "work on this in a worktree" or "branch off green", when several agents will run at once, or when cleaning up after a merged branch. Not for deciding what to build, gating a change, reviewing, or landing — the spine's lifecycle and `build` own those.
model: inherit
---
# Worktree Isolation

Any multi-commit task runs on its own branch in its own git worktree, so parallel work cannot collide, the default branch stays clean, and an interrupted task is resumable.

## The rule

**Never build on the default branch. One task, one branch, one worktree.**

## Creating the worktree

Branch off the integration branch, fetched first.

```bash
git fetch --quiet <remote>
git worktree add --detach ../<repo>-<task-id> <remote>/<integration-branch>
```

**Fetch before you branch**, so the base is the commit other sessions have landed on rather than the one this checkout last saw.

**The base may be red, and that is what the next section is for.** Nothing records for you whether the integration tip is certified, and ADR 0022 point 3 forbids a plugin-shipped executable reading whether something passed. What stands in its place is the gate you were going to run anyway — *Gating the base* below runs it before anything in the worktree changes, so a red base is caught by direct evidence rather than by a record of somebody else's run. The cost is one gate run per worktree, weighed and accepted.

## Linking heavy local artifacts

A fresh worktree does not have your gitignored local state — dependencies, env files, build caches — so symlink those from the shared repo root rather than reinstalling. Anchor both ends of every link to the shared root computed from git, never to `$PWD`, which on resume may already be the worktree and would make the link point at itself.

```bash
SHARED_ROOT="$(git rev-parse --path-format=absolute --git-common-dir)"; SHARED_ROOT="${SHARED_ROOT%/.git}"
# Link what this repo needs — see harness.yaml (e.g. the env file, the deps dir):
ln -sfn "$SHARED_ROOT/<env-file>"  "<worktree>/<env-file>"
ln -sfn "$SHARED_ROOT/<deps-dir>"  "<worktree>/<deps-dir>"
```

Pass `-n` so re-running replaces a stale link instead of nesting a new one inside it.

## Gating the base

Run the repo's verify command (`harness.yaml` → `commands.verify`) in the detached worktree, before the branch is cut and before anything in it changes. One run, against what a tick without it has cost: four gate runs and a full review cycle, ended by discovering the integration branch was red on its own, with the task's branch nowhere in the picture.

It runs at this point in the sequence because a gate needs two things a bare commit id cannot give it: a working tree, and the gitignored local state the previous section links in. The detached worktree standing at the base is both, at no extra cost — nothing is committed to it and no branch names it, so a red result costs only a directory.

**Somebody else's green does not excuse the run.** A gate is not host-portable: one observed failure was a suite green in CI and red on the developer's machine, on a temp path one character over a 200-character cap. A record of a passing run does not travel between hosts; the run does.

- **Green.** Cut the branch now and start work — `git checkout -b <task-id>` inside the worktree, named after the task, its ticket id ideal. A red gate from here on is yours, which is what the minute buys.
- **Red.** An andon pull (P4). File the failure as a bug against the integration branch, remove the worktree, hold the task, and stop. No branch was cut, so the retry after somebody clears the red starts clean. Never build on a red base: every later gate run answers a question you already know the answer to.
- **Red for a reason this run did not cause**, which is the ordinary case — the base is somebody else's landing. Same disposition, and do not repair it here: a fix for another ticket's defect inside this ticket's tree is a second change nobody reviewed for this ticket. Put what you observed in the bug, not what you concluded about who caused it.

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
