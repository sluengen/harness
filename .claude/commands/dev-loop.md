# Dev Loop

Pull tasks from Linear, run them through the pipeline, deliver a single PR. Repeat until the backlog is empty or an escalation stops the loop.

## Instructions

### Step 0: Load context

Read the linear-sync skill (`.claude/skills/linear-sync.md`) for field mappings, status mappings, and MCP operations.

Read `manifest.yaml` to check for any in-progress tasks from a previous session. If a task has an active pipeline status and a `linear_id`, resume it before pulling new work.

### Step 0.5: Create session branch

Create a **single branch** for the entire loop run:

```bash
git checkout staging && git pull  # or main if no staging branch
git checkout -b dev-loop-YYYY-MM-DD
```

All tasks in this loop go on this one branch. Do NOT create per-task branches — that causes merge conflicts between parallel PRs and prevents the user from testing the full build locally before merging.

### Step 1: Pull next task from Linear

Query Linear for the next task to work on:

```
list_issues(
  team: "{your-team}",
  state: "Todo",
  limit: 10
)
```

From the results, select the highest-priority task using this heuristic:
1. **Priority first** — Urgent (1) > High (2) > Normal (3) > Low (4)
2. **Bugs before features** at same priority — stability first
3. **Smallest scope** at same priority + type — maximize delivery cadence

If no "Todo" issues exist, notify the user: "Linear backlog empty — add more tasks to proceed." Then stop.

### Step 2: Ingest into manifest

Read the full issue details (`get_issue`). Map Linear fields to manifest fields per the linear-sync skill.

Create a new manifest entry:

```yaml
- id: {prj-number}-{slugified-title}
  name: {Linear title}
  type: {from type label, default: feature}
  priority: {mapped priority}
  status: todo
  linear_id: {Linear identifier, e.g. PRJ-42}
  linear_url: {Linear issue URL}
  source: linear
  assigned_to: null
  description: >
    {Linear description, verbatim}
  depends_on: []
```

Add to the `tasks:` section (or `maintenance:` for bugs and refactors). Commit the manifest update separately: `manifest: ingest {PRJ-NNN} from Linear`.

### Step 3: Update Linear status

Move the Linear issue to "In Progress":

```
save_issue(id: {issue_id}, state: "In Progress")
```

### Step 4: Route through pipeline

Evaluate the artifact DAG (`specs/arch/pipeline-schema.yaml`) to determine what happens next. The DAG resolves routing — no tier classification needed.

**Typical flows by stack label:**
- **Backend:** PM → [delta + design in parallel] → architect (tasks) → backend-dev → reviewer
- **Frontend:** PM → [delta + brand_review + design in parallel] → architect (tasks) → frontend-dev → reviewer
- **Fullstack:** PM → [delta + brand_review + design in parallel] → architect (tasks) → [backend-dev + frontend-dev in parallel] → reviewer

When the PM waives recommended artifacts, the pipeline compresses naturally. A bug fix with delta/design/tasks waived flows: proposal → dev → reviewer.

**Run the full pipeline autonomously.** Do not pause between stages for user approval unless there is insufficient information to proceed. Sub-agents mitigate context window impact.

Key rules:
- Dev agents **must** use `isolation: "worktree"`
- Update manifest status at each handoff
- Update Linear status at stage transitions (per the status mapping in linear-sync skill)
- All work is committed to the session branch — no per-task branches

### Step 5: Handle insufficient information

If a PM or architect agent identifies missing information needed to proceed:

1. Add a comment to the Linear issue with the **specific questions** that need answering
2. Add the `needs-input` label
3. Update manifest status back to `backlog`
4. **Do not pause the loop** — move to the next task immediately
5. Log: `[dev-loop] {PRJ-N} parked — questions posted to Linear`

The user answers questions asynchronously in Linear. The task will be picked up in a future loop run.

### Step 5b: Handle reviewer FAILs

If the reviewer FAILs:
- First FAIL: send issues back to dev, re-review
- Second FAIL: add `review-failed` label, comment on Linear, park the task, move to next

### Step 6: Deliver (per task)

When a task's pipeline completes successfully:

1. Add a comment to the Linear issue with a summary of what was built
2. Move Linear issue to "Done"
3. Update manifest: `status: done`, `completed_date`
4. Commit manifest update: `manifest: complete {PRJ-NNN}`

Do NOT create per-task PRs. All work accumulates on the session branch.

### Step 7: Loop

Go back to Step 1. Continue until:
- Linear backlog is empty (no "Todo" issues)
- Context monitor fires at critical level → run `/pause-work`
- User interrupts

### Step 8: Session PR

When the loop ends (backlog empty, context critical, or user interrupt):

1. Push the session branch
2. Create a single PR targeting `staging` (or `main`) with a summary of all tasks delivered
3. Log the PR URL

The user tests the build locally, reviews, and merges on their own time.

### Loop state on pause

If the loop is interrupted, the current state is recoverable:
- **Manifest** has each task's current pipeline status
- **Linear** has the coarse status + any comments/questions
- **Git** has the session branch with all committed work
- Running `/dev-loop` again will resume from where it stopped (checks manifest for in-progress tasks first)

### Output format

At each task, print a brief status line:

```
[dev-loop] Pulling {PRJ-N}: {Task Name} ({priority}, {stack})
[dev-loop] Pipeline: PM → architect → {dev-agent} → reviewer
[dev-loop] Stage: proposing → running PM...
```

At loop end:

```
[dev-loop] Complete. {N} tasks delivered, {M} parked (needs-input), {K} in backlog.
[dev-loop] PR: {PR URL}
```
