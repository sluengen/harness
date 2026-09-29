---
name: worktree-isolation
description: Sets a task up on its own branch in its own git worktree — choosing the base, giving the new directory its gitignored local state, giving each concurrent agent its own tree, telling a red base from the task's own failure, and tearing the worktree and the resources it started down after merge. Use when starting any multi-commit task, when asked to "work on this in a worktree", when several agents will run at once, when a test fails that the diff does not explain, or when cleaning up after a merged branch. Not for deciding what to build, gating a change, reviewing, or landing — the spine's lifecycle and `build` own those.
model: inherit
---
# Worktree Isolation

Any multi-commit task runs on its own branch in its own git worktree, so parallel work cannot collide, the default branch stays clean, and an interrupted task is resumable.

## The rule

**Never build on the default branch. One task, one branch, one worktree.**

## Creating the worktree

**Ask first whether this host already holds the task, and ask it before anything writes the task down.** One `git worktree list` answers two questions, and this is the cheaper one: does an entry already carry *this* task? Match on the task segment of the directory name or the leading segment of the branch, as a delimited token rather than a substring — `<repo>-51` and `<repo>-512` differ by a delimiter, and a substring match refuses the wrong run. A match means a run on this host may be live in it, so **stop before the task is transitioned, assigned or commented on anywhere**, and report the path, the branch, and what that directory's run state last recorded. Do not remove it, do not reuse it, and do not judge from a timestamp whether the run behind it is still alive: no file on disk says that, and a clock that guessed would strand the work it guessed wrong about. Where the operator recognises the directory as their own ended run, the work is recovered from it rather than abandoned — a resume, not a fresh start.

**What that sees is bounded, and the bound is part of the answer.** It is the worktrees of **this clone**, wherever on disk they sit. A second clone of the repository on this host keeps its own list and is invisible here; so is a container, and so is another host. A directory and branch that both fall outside the naming convention are unmatchable and stay standing. A branch with no worktree is not a live run, and still collides natively when the branch is cut.

**Reclaim what earlier runs left, before cutting a new one.** *Cleanup* below belongs to a task that ships, so a task that never ships never reaches it: a ticket held at DEFER and never resumed, a run whose context ended mid-flight. Each leaves a directory nobody returns to, and a sweep during #582 found six of seven worktrees on disk belonged to tickets already closed. Cutting a worktree is the moment every run passes through, so the reclaim happens here rather than in a scheduler the plugin does not own.

Run `git worktree list` and match each entry to its ticket, which the naming convention below puts in the directory name. Remove the ones whose ticket is closed, under three bounds:

- **Look for unsaved work first.** Removing a worktree destroys anything uncommitted in it, and a branch that was never pushed exists nowhere else. A closed ticket does not prove its tree was landed.
- **Stay on the git side**: the directory and git's own records, using *Cleanup*'s commands. Leave containers, simulators, volumes and services standing, because a sweeping run cannot prove it owns them, which is what *Cleanup* refuses. Report what you left behind.
- **Leave every worktree whose ticket is open**, and every one you cannot match to a ticket. Another run may be working in it right now.

Then branch off the integration branch, fetched first.

```bash
git fetch --quiet <remote>
git worktree add --detach ../<repo>-<task-id> <remote>/<integration-branch>
```

**Fetch before you branch**, so the base is the commit other sessions have landed on rather than the one this checkout last saw.

**Cut the task's branch in it** once its local state is in place (next section) — `git checkout -b <task-id>`, named after the task, its ticket id ideal. No gate runs over the base first: the tip is normally a tree a landing already gated, and a red one is attributed when it shows up rather than on every cut (*A red base*, below; #731).

## Giving the worktree its local state

A fresh worktree does not have your gitignored local state — env files, dependencies, build caches. How each piece gets there depends on what it is.

**Install dependencies and build trees in the worktree; do not link them.** Run the repo's install or sync command (`harness.yaml` → `commands.install`) inside the new directory, so `node_modules`, a virtualenv or a build cache belongs to this worktree alone. A linked dependency tree has failed three independent ways, and a per-worktree install closes all three:

- **It does not travel.** A tree can hold a relative symlink that resolves outside it — a workspace package under `node_modules`, for one — and resolves somewhere else once the tree is reached through a link from a second worktree (calibrate). A virtualenv records absolute paths in its config and its console-script shebangs, a compiled module is built against one interpreter and one platform, and a build cache keys on the directory it was written at.
- **A repo's own gate may refuse it.** A repo can require dependencies materialised per worktree, and its gate stops the first time it meets a link.
- **One writer breaks every reader.** An install into a shared tree from one worktree rewrites it under a gate running in another (nano-erp, ERP-432).

Each of these fails where the dependency is first used, so the failure arrives dressed as a red base, and every disposition *A red base* below reserves for one then names the wrong subject. Four independent runs in `sluengen/calibrate` filed one against the integration branch before finding the cause. A red gate that moves when the dependency state moves is this directory's rather than the branch's.

**Link small, read-only local state**, such as the env file. Anchor both ends of every link to the shared root computed from git, never to `$PWD`, which on resume may already be the worktree and would make the link point at itself.

```bash
SHARED_ROOT="$(git rev-parse --path-format=absolute --git-common-dir)"; SHARED_ROOT="${SHARED_ROOT%/.git}"
ln -sfn "$SHARED_ROOT/<env-file>" "<worktree>/<env-file>"   # e.g. harness.yaml → env.file
( cd "<worktree>" && <install-command> )                    # harness.yaml → commands.install
```

Pass `-n` so re-running replaces a stale link instead of nesting a new one inside it.

**Linking a heavy tree is an exception the repo opts into**, for an install too slow to repeat per worktree. It is safe only while both of these hold, and the repo that opts in owns checking them: nothing inside the tree is a relative symlink resolving outside it, and nothing — an install, a build, a cache write — writes into it from more than one worktree at a time. Where either stops holding, the default applies again.

## A red base

A red integration branch surfaces in the build that meets it — the builder's targeted tests, then the reviewer's complete gate — or at the release hop, which runs the complete gate over everything the integration branch carries. A repo whose CI runs on each integration push has an earlier detector of its own. This section governs a build; a red landing gate keeps its own posture (`skills/promote/SKILL.md` stage 3).

**Attribute a failure your diff does not explain before acting on it.** Rule this directory out first (*Giving the worktree its local state*, above). Then, with the work committed, fetch and run only the failing tests at the integration tip — `git fetch <remote>`, `git checkout --detach <remote>/<integration-branch>`, run them, `git checkout -` — rather than the whole gate. Green there, and the failure is this branch's: fix it, or take the tip in first where it already carries the fix (`skills/build/references/reconcile.md`). Red there is an andon pull (P4):

- **Search before you file.** `tracker` → *The andon cord* keys the search to the failing test rather than a title and says what a hit obliges; an open P1 on this failure is already the cord, and gains your evidence instead of the board gaining a twin.
- **Hold the task and stop**, naming what would clear it — the cord, and the age `tracker` reads from its claim — and return it to Todo, where held confirmed work waits. The hold takes `operator`, because a repair clears it rather than an answer; take `input` only where the run cannot tell a host-local failure from a defect in the base. A ticket's branch is already pushed, so remove nothing. A fix-lane change has no ticket to hold: push nothing, report what blocks it, and stop, leaving the worktree for the retry.
- **Do not repair it here**, unless this ticket is that repair. A fix for another ticket's defect inside this ticket's tree is a second change nobody reviewed for this ticket. Put what you observed in the bug, not what you concluded about who caused it.

A reviewer or a dispatched `dev` that meets one files nothing and holds nothing: it attributes, and returns the result — a reviewer as a FAIL finding, a `dev` in its hand-off — for the run that dispatched it to act on.

## Parallel sub-agents

Each concurrent agent gets its own worktree because two agents editing one working tree interleave their edits and corrupt each other's diffs, the single exception being a lone sub-agent sharing the orchestrator's worktree while the orchestrator is idle for the whole run.

## Cleanup

Cleanup is part of shipping a merged task; skip it and short-lived task artifacts accumulate on the host. It runs only on a task that ships, which is why *Creating the worktree* reclaims the ones that did not. Stop every temporary resource the task started before removing the files it runs from, then remove the worktree, prune git's administrative records, and delete the merged branch.

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
