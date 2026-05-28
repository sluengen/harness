# Start Task

Trigger the build workflow for a Linear issue. The harness handles everything — worktree, implementation, review, commit, push.

## Usage

- `/start-task <CAL-NNN>` — run the build workflow for the given Linear issue

## Instructions

### Step 1 — Fetch the ticket

```bash
PYTHONPATH=. python scripts/fetch_linear_ticket.py <CAL-NNN>
```

Print a brief for the user:

```
Task:   <title>
Linear: <CAL-NNN>
URL:    <url>
State:  <current state>
```

If the issue is already Done or has unresolved dependencies listed in the description, stop and report.

### Step 2 — Run the build workflow

```bash
PYTHONPATH=. slate-harness run build --linear=<CAL-NNN>
```

The workflow handles the rest: worktree, implement, review, gate, commit, push, merge.

### Step 3 — Report the outcome

Check the run result:

```bash
slate-harness status <run-id>
slate-harness logs   <run-id>
```

Report whether the run completed, was cancelled by the gate (review FAIL), or failed with an error. Surface the reviewer's findings if the gate fired.
