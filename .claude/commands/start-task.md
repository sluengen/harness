# Start Task

Kick off work on a Linear issue. Solo-dev flow: branch + worktree, status update, work, PR.

## Usage

- `/start-task <CAL-NNN>` — start work on a specific Linear issue
- `/start-task` — pick up the highest-priority In Progress or Todo issue from the Harness initiative

## Instructions

### Step 1: Resolve the task

If a `<CAL-NNN>` argument was provided:
1. Fetch the issue via the sync CLI (in calibrate-coffee):
   ```bash
   cd /Users/scottluengen/Documents/1_Projects/calibrate-coffee && \
     set -a && source .env.development && set +a && \
     PYTHONPATH=. python -m harness.tools.sync linear get <CAL-NNN>
   ```
2. Confirm the issue is in the Harness v1, v1.5, or v2 project. If not, abort and report.
3. Note the title (e.g., `[H-001] Project bootstrap + CI`), the description (acceptance + dependencies), and the priority.

If no argument provided:
1. List unblocked Todo or In Progress issues in the Harness v1 project, ordered by priority.
2. Pick the highest-priority unblocked one.
3. Confirm with the user before proceeding.

### Step 2: Validate prerequisites

- **Dependencies:** if the issue's description lists `Depends on: H-XXX`, check that those issues are Done in Linear. If any aren't, stop and report.
- **Status:** if the issue is already Done, report and stop. If it's already In Progress (and not by you), confirm before continuing — could be a parallel session.

### Step 3: Move the task to In Progress

Update Linear status with a starting comment:

```bash
cd /Users/scottluengen/Documents/1_Projects/calibrate-coffee && \
  set -a && source .env.development && set +a && \
  PYTHONPATH=. python -m harness.tools.sync linear push <CAL-NNN> in_progress \
    --comment "Starting <H-NNN>: <one-line summary>"
```

### Step 4: Enter a worktree

Per `.claude/skills/worktree-isolation.md`. Branch name follows `harness/<H-NNN>-<short-slug>`:

```bash
cd ~/Documents/1_Projects/harness && \
  git fetch origin && \
  git worktree add .worktrees/<H-NNN> -b harness/<H-NNN>-<short-slug> main && \
  cd .worktrees/<H-NNN>
```

If the worktree already exists (resuming), `cd` into it and continue.

### Step 5: Print a status block

Before starting work:

```
Task:     <issue title>
Linear:   <CAL-NNN>
Roadmap:  <H-NNN>
Branch:   harness/<H-NNN>-<short-slug>
Worktree: .worktrees/<H-NNN>
Acceptance:
  - <AC1>
  - <AC2>
  ...
```

### Step 6: Implement

Dispatch the python-dev agent with the task, OR work directly if the change is small and contained (rule of thumb: under 100 LOC, single file). Either way, the dev work follows TDD per `.claude/skills/test-driven-development.md`.

If dispatching python-dev as a sub-agent and other sub-agents may run in parallel, use `isolation: "worktree"`.

### Step 7: Verify

Per `.claude/skills/verification-before-completion.md`:

```bash
uv run ruff check .
uv run mypy harness
uv run pytest
```

All three must run clean before proceeding to review.

### Step 8: Review

Dispatch the reviewer agent on the diff. Address any HIGH/MEDIUM findings on touched files (fix-now rule). Re-run verification after fixes.

If the reviewer issues FAIL twice on the same review, stop and surface the blocking issues to the user.

### Step 9: Ship

```bash
git push -u origin harness/<H-NNN>-<short-slug>
gh pr create --base main --title "[<H-NNN>] <title> (<CAL-NNN>)" --body "<test plan + summary, references the Linear issue>"
```

Then move the Linear issue to In Review with the PR link:

```bash
cd /Users/scottluengen/Documents/1_Projects/calibrate-coffee && \
  set -a && source .env.development && set +a && \
  PYTHONPATH=. python -m harness.tools.sync linear push <CAL-NNN> in_review \
    --comment "PR: <pr-url>"
```

The user reviews and merges the PR. After merge, manually move Linear to Done (or extend the sync flow later).

## Pause points

The orchestrator pauses for user input only when:
1. The reviewer fails twice on the same task — present blocking issues.
2. A sub-agent escalates a decision it cannot make autonomously.
3. The task's acceptance criteria are ambiguous — surface, don't guess.

Everything else runs through.
