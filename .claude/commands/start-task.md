# Start Task

Kick off the pipeline for a task from wherever it currently sits in the manifest.

Usage: `/start-task <task-id>`

## Instructions

### Step 1: Read the manifest

Read `manifest.yaml`. Find the task matching `$ARGUMENTS` (the task-id). If no match is found, report the error and list available task IDs.

### Step 2: Validate prerequisites

Check that the task is ready to proceed:

**Dependency check** — for every task listed in `depends_on`, confirm its status is `done`. If any dependency is not done, stop and report:
```
Cannot start [task-id]: depends on [dependency-id] which is [status].
```

**Blocker check** — if the task has a `blocked_by` field, stop and report:
```
Cannot start [task-id]: blocked — [blocked_by reason].
```

**Status check** — if the task is `done`, report that it's already complete. If it's `backlog`, report that it needs strategist prioritisation first.

### Step 3: Check for a worktree

Check whether a worktree exists for this task in `.worktrees/` (e.g. `.worktrees/my-task-id`). Report what you find — present but do not create or delete worktrees automatically.

### Step 4: Report current position

Evaluate the artifact DAG in the change folder (see `specs/arch/pipeline-schema.yaml`). Print a brief status block before starting:

```
Task:     [task name]
ID:       [task-id]
Status:   [current manifest status]
DAG:      [which artifacts exist, which are waived, which are needed next]
Next:     [what will happen — which agent, which artifact]
Worktree: [found at .worktrees/X | not found]
```

### Step 5: Execute the pipeline from DAG state

Evaluate the artifact DAG to determine what's needed next. Do not redo completed artifacts. The DAG resolves routing — no tier classification needed.

| DAG state | Action |
|---|---|
| No change folder | Create `specs/changes/<task-id>/`, invoke product-manager |
| `proposal.md` exists, recommended artifacts not started | Run `/self-review` on proposal → invoke agents for unblocked artifacts (delta, design, brand_review can run in parallel) |
| All non-waived upstream artifacts complete | Run `/self-review` on design (if exists) → invoke dev |
| Code committed, tests pass | Invoke reviewer |
| `review.md` with PASS | Invoke deployment-manager |
| `review.md` with FAIL | Send issues to dev (first FAIL) or escalate to user (second FAIL) |
| `specifying` / `designing` / `building` / `reviewing` | An agent is mid-task — check if it completed, then resume or hand off |

**Waivers compress the pipeline naturally.** If the PM waives delta, design, and tasks in the proposal, the orchestrator proceeds directly from proposal to dev. No separate routing needed.

### Step 6: Update manifest at each handoff

After each agent completes, update the manifest status before invoking the next agent. The manifest is the source of truth — if the pipeline is interrupted, `/start-task` can be run again to resume from where it stopped.

### Orchestrator rules

**Pause only when:**
1. PM has produced a scope proposal — present to user, wait for input, relay back to PM
2. Reviewer fails a second time — present blocking issues to user, wait for direction
3. Any agent explicitly escalates a decision it cannot make autonomously

**Everything else runs through without interruption.**

**Reviewer FAIL logic:**
- First FAIL: send blocking issues back to dev, re-run reviewer
- Second FAIL: stop, present issues to user, wait for direction
