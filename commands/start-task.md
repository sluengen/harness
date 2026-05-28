# Start Task

Kick off work on a Linear issue in the harness repo. Fetches the ticket, creates a worktree, and sets up for implementation.

> **Note:** For automated end-to-end implementation, use `slate-harness run build --linear=<CAL-NNN>` instead — the build workflow manages its own worktree. Use `start-task` for human-driven development where you want an agent to assist step-by-step.

## Usage

- `/start-task <CAL-NNN>` — start work on a specific Linear issue
- `/start-task` — list open issues and pick one with the user

## Instructions

### Step 1: Resolve the task

Fetch the issue:

```bash
PYTHONPATH=. python scripts/fetch_linear_ticket.py <CAL-NNN>
```

Note the title, description, and acceptance criteria.

If no argument provided: ask the user which ticket to work on, then fetch it.

### Step 2: Validate prerequisites

- **Dependencies:** if the description lists `Depends on: CAL-XXX`, verify those are Done in Linear. If not, stop and report.
- **Status:** if the issue is already Done, report and stop.

### Step 3: Print a task brief

```
Task:     <issue title>
Linear:   <CAL-NNN>
URL:      <issue url>
State:    <current state>
Acceptance:
  - <AC1>
  - <AC2>
  ...
```

### Step 4: Create a worktree

Branch name follows `harness/<CAL-NNN>-<short-slug>`:

```bash
git fetch origin
git worktree add .worktrees/<CAL-NNN> -b harness/<CAL-NNN>-<short-slug> main
```

If a worktree already exists for this ticket (resuming), just enter it.

### Step 5: Implement

Follow `skills/test-driven-development.md`. Work in the worktree at `.worktrees/<CAL-NNN>/`.

For larger tasks, dispatch the `python-dev` sub-agent with `isolation: "worktree"`.

### Step 6: Verify

Per `skills/verification-before-completion.md` — all three must pass:

```bash
cd .worktrees/<CAL-NNN>
uv run ruff check .
uv run mypy harness
uv run pytest
```

### Step 7: Review

Dispatch the `reviewer` sub-agent when any of these apply:
- Runtime semantics (async, I/O ordering, resource cleanup)
- Subprocess invocation, path handling, or secret handling
- A contract or state mutation downstream nodes depend on
- Uncertain test coverage of acceptance criteria

Address all HIGH/MEDIUM findings. Re-run verification after fixes.

### Step 8: Ship

```bash
cd .worktrees/<CAL-NNN>
git push -u origin harness/<CAL-NNN>-<short-slug>
gh pr create --base main \
  --title "<CAL-NNN>: <title>" \
  --body "<summary + test plan>"
```

Move the issue to **In Review** in Linear and paste the PR link as a comment.

## Pause points

Pause only when:
1. The reviewer fails twice on the same task.
2. A sub-agent escalates a decision it can't make autonomously.
3. Acceptance criteria are ambiguous — surface, don't guess.

Everything else runs through.
