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

### Step 4: Determine tier

Read the `tier` field from the task (default: `standard` if absent). This controls which pipeline runs.

### Step 5: Report current position

Print a brief status block before starting:

```
Task:     [task name]
ID:       [task-id]
Tier:     [standard | express | discovery]
Status:   [current status]
Next:     [what will happen — which agent, which stage]
Worktree: [found at .worktrees/X | not found]
```

### Step 6: Execute the pipeline from current status

Pick up from the task's current status and run forward. Do not redo completed stages. Pipeline varies by tier.

**Standard tier** (default):

| Current status | Action |
|---|---|
| `ready_for_spec` | Run PM conversation loop (pause for user input on scope) |
| `ready_for_design` | Run `/self-review` on the product spec → invoke architect |
| `ready_for_dev` | Run `/self-review` on the design → invoke backend-dev |
| `ready_for_review` | Invoke reviewer |
| `ready_for_deploy` | Invoke deployment-manager |
| `specifying` / `designing` / `building` / `reviewing` | An agent is mid-task — check if it completed, then resume or hand off |

**Express tier** (`tier: express`):

| Current status | Action |
|---|---|
| `ready_for_dev` | Invoke backend-dev directly — no self-review, no spec/design |
| `ready_for_review` | Invoke reviewer |
| `ready_for_deploy` | Invoke deployment-manager |
| `building` / `reviewing` | An agent is mid-task — check if it completed, then resume or hand off |

Express reviewer scope: verify TDD was followed and all carry-forward items from the manifest description are addressed. Skip full spec-compliance check (there is no new spec).

**Discovery tier** (`tier: discovery`):

| Current status | Action |
|---|---|
| `ready_for_dev` | Invoke backend-dev — output may not ship |
| `building` | Agent is mid-task — check if it completed |

After backend-dev completes discovery work, pause and present findings to the user. Let them decide: promote to Standard (write a spec) or discard.

### Step 7: Update manifest at each handoff

After each agent completes, update the manifest status before invoking the next agent. The manifest is the source of truth — if the pipeline is interrupted, `/start-task` can be run again to resume from where it stopped.

### Orchestrator rules

**Pause only when:**
1. PM has produced a scope proposal — present to user, wait for input, relay back to PM
2. Reviewer fails a second time — present blocking issues to user, wait for direction
3. Any agent explicitly escalates a decision it cannot make autonomously

**Everything else runs through without interruption.**

**Reviewer FAIL logic:**
- First FAIL: send blocking issues back to backend-dev, re-run reviewer
- Second FAIL: stop, present issues to user, wait for direction
