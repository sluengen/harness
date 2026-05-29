# Start Task

Trigger the build workflow for a Linear issue. The harness handles everything — worktree, implementation, review, commit, push.

## Usage

- `/start-task <CAL-NNN>` — run the build workflow for the given Linear issue

## Prerequisites

Before running any commands, load the project environment:

```bash
source .env
```

`LINEAR_API_KEY` and other credentials live in `.env` at the repo root (gitignored). If the file is missing, create it:

```bash
# .env
LINEAR_API_KEY=lin_api_xxxxxxxxxxxxxxxx   # from linear.app → Settings → API → Personal API keys
```

`slate-harness` is not installed globally in development — invoke it via `uv run` from the repo root:

```bash
# dev invocation pattern (used throughout these instructions)
source .env && PYTHONPATH=. uv run slate-harness <args>
```

## Instructions

### Step 1 — Fetch the ticket

```bash
source .env && curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"query{issue(id:\"<CAL-NNN>\"){identifier title description state{name} labels{nodes{name}} url}}"}'
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
source .env && PYTHONPATH=. uv run slate-harness run build --linear=<CAL-NNN>
```

The workflow handles the rest: worktree, implement, review, gate, commit, push, merge.

### Step 3 — Report the outcome

Check the run result:

```bash
source .env && PYTHONPATH=. uv run slate-harness status <run-id>
source .env && PYTHONPATH=. uv run slate-harness logs   <run-id>
```

Report whether the run completed, was cancelled by the gate (review FAIL), or failed with an error. Surface the reviewer's findings if the gate fired.
