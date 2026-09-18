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

**Ask first whether this host already holds the task, and ask it before anything writes the task down.** One `git worktree list` answers two questions, and this is the cheaper one: does an entry already carry *this* task? Match on the task segment of the directory name or the leading segment of the branch, as a delimited token rather than a substring — `<repo>-51` and `<repo>-512` differ by a delimiter, and a substring match refuses the wrong run. A match means a run on this host may be live in it, so **stop before the task is transitioned, assigned or commented on anywhere**, and report the path, the branch, and what that directory's run state last recorded. Do not remove it, do not reuse it, and do not judge from a timestamp whether the run behind it is still alive: no file on disk says that, and a clock that guessed would strand the work it guessed wrong about. Where the operator recognises the directory as their own ended run, the work is recovered from it rather than abandoned — a resume, not a fresh start.

**What that sees is bounded, and the bound is part of the answer.** It is the worktrees of **this clone**, wherever on disk they sit. A second clone of the repository on this host keeps its own list and is invisible here; so is a container, and so is another host. A directory and branch that both fall outside the naming convention are unmatchable and stay standing. A branch with no worktree is not a live run, and still collides natively when the branch is cut.

**Reclaim what earlier runs left, before cutting a new one.** *Cleanup* below belongs to a task that ships, so a task that never ships never reaches it: a ticket held at DEFER and never resumed, a run whose context ended mid-flight, a base that gated red. Each leaves a directory nobody returns to, and a sweep during #582 found six of seven worktrees on disk belonged to tickets already closed. Cutting a worktree is the moment every run passes through, so the reclaim happens here rather than in a scheduler the plugin does not own.

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

**The base may be red, and that is what the next section is for.** Nothing records for you whether the integration tip is certified, and ADR 0022 point 3 forbids a plugin-shipped executable reading whether something passed. What stands in its place is the gate you were going to run anyway — *Gating the base* below runs it before anything in the worktree changes, so a red base is caught by direct evidence rather than by a record of somebody else's run. The cost is one gate run per worktree, weighed and accepted — what that run costs, and what it proves, depend on the gate, which is *Gating the base*'s to state.

## Linking heavy local artifacts

A fresh worktree does not have your gitignored local state — dependencies, env files, build caches — so symlink those from the shared repo root rather than reinstalling. Anchor both ends of every link to the shared root computed from git, never to `$PWD`, which on resume may already be the worktree and would make the link point at itself.

```bash
SHARED_ROOT="$(git rev-parse --path-format=absolute --git-common-dir)"; SHARED_ROOT="${SHARED_ROOT%/.git}"
# Link what this repo needs — see harness.yaml (e.g. the env file, the deps dir):
ln -sfn "$SHARED_ROOT/<env-file>"  "<worktree>/<env-file>"
ln -sfn "$SHARED_ROOT/<deps-dir>"  "<worktree>/<deps-dir>"
```

Pass `-n` so re-running replaces a stale link instead of nesting a new one inside it.

**What you linked may not be portable, and the gate runs next.** A virtualenv records absolute paths in its config and its console-script shebangs, a compiled module under `node_modules` is built against one interpreter and one platform, and a build cache keys on the directory it was written at. Any of those fails where the dependency is first used, which is *Gating the base* one section below — so the failure arrives dressed as a red base, and every disposition that section reserves for a red base then names the wrong subject. Four independent runs in `sluengen/calibrate` filed it against the integration branch before finding the cause. Resolve the dependencies from inside the worktree before reading a red gate as the base's: run the repo's install or sync command there, and treat a failure that moves when the dependency state moves as this directory's rather than the branch's.

## Gating the base

Run the repo's verify command (`harness.yaml` → `commands.verify`) in the detached worktree, before the branch is cut and before anything in it changes. One run, against what a tick without it has cost: four gate runs and a full review cycle, ended by discovering the integration branch was red on its own, with the task's branch nowhere in the picture.

It runs at this point in the sequence because a gate needs two things a bare commit id cannot give it: a working tree, and the gitignored local state the previous section links in. The detached worktree standing at the base is both, at no extra cost — nothing is committed to it and no branch names it, so a red result costs only a directory.

**The run answers for two things, and a base command sized for one of them silently retires the other.** The first is attribution: a red gate after this point is this task's. The second is the integration branch's own health. Where CI does not run on every push to the integration branch, the next builder's base gate is the only routine detector of a red one, and the repo has made this run its watchdog without writing that down anywhere. `sluengen/calibrate` is such a repo: `.github/workflows/verify.yml` runs on pull requests and on pushes to `main`, while most work lands on `dev` by direct push. Size the base command against both jobs, or name the one you are giving up and where its detection moves to.

**A gate that derives its scope from a diff is being asked a question it is not shaped to answer.** At a base there is no diff: nothing has changed yet. What runs is whatever its author chose for the empty case, and that choice decides both what this run costs and what it proves. In calibrate the empty case widens rather than narrows — `scripts/verify.sh:1257-1258` prints `No scoped changes detected vs ${BASE_NAME}; running backend gate (default)` and sets `run_backend=1`, so every worktree cut there pays for Docker Compose, Postgres and the backend suite whatever the ticket will touch. A default that narrows instead costs nothing and proves nothing, which is the worse of the two.

**The repo resolves this, because the repo owns its gate script.** Nothing here adds a configuration key, an interface for passing a scope in, or a requirement that a repo run CI. A repo whose gate is change-aware decides what its empty case should do at a base and lives with the answer; the plugin's part is to say that the decision exists and is being made by default until somebody makes it. The costing above — one gate run per worktree, weighed and accepted — was weighed against a gate whose cost does not depend on what it is asked about. It does not carry to a gate that answers an empty diff with its widest arm, and a repo in that position should re-weigh it against its own numbers rather than inherit this one.

**Somebody else's green does not excuse the run.** A gate is not host-portable: one observed failure was a suite green in CI and red on the developer's machine, on a temp path one character over a 200-character cap. A record of a passing run does not travel between hosts; the run does.

- **Green.** Cut the branch now and start work — `git checkout -b <task-id>` inside the worktree, named after the task, its ticket id ideal. A red gate from here on is yours, which is what the run buys.
- **Red.** An andon pull (P4). **Rule this directory out before you file against the branch** — *Linking heavy local artifacts* above names the failure that reads as a red base and is not one. **Then search before you file.** A red base reproduces for every run that meets it, so two runs file one defect under two titles unless the search is keyed to the failure rather than to the wording; `tracker` owns that search and what a hit obliges, and an open P1 on this failure is already the cord — it gains your evidence instead of the board gaining a twin. Whether one exists changes what gets **written** and nothing else. Either way: remove the worktree, hold the task naming what would clear it — the cord, and the age `tracker` reads from the claim on it — and stop. **The hold takes the `operator` label**, because a red base is cleared by a repair rather than by an answer and the bullet below forbids this run making it, so what the task waits on is a hands-on session. Take `input` instead in the one case where the missing piece really is an answer: the run cannot tell a host-local failure from a defect in the base, and the operator's judgment decides what gets filed. No branch was cut, so the retry after somebody clears the red starts clean. Never build on a red base: every later gate run answers a question you already know the answer to, and a repair already in flight is somebody else's run rather than a licence to start yours on the same bytes.
- **Red for a reason this run did not cause**, which is the ordinary case — the base is somebody else's landing. Same disposition, and do not repair it here: a fix for another ticket's defect inside this ticket's tree is a second change nobody reviewed for this ticket. Put what you observed in the bug, not what you concluded about who caused it.

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
