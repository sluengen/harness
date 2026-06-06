<!-- guidance:start@0.1.1 -->
# /start — begin work on a ticket

Usage: `/start <TICKET-ID>`

Sets up an isolated workspace for a tracked ticket and drives it test-first through to a review-ready state. Implements the `spec-driven-development` flow.

## Steps

### 1. Open the ticket
Fetch the ticket and print a brief (title, id, state, link). The invocation is repo-specific — see `CONTEXT.md` and the `linear-sync` skill. If the ticket is already Done, or names unmet dependencies, stop and report.

### 2. Mark it In Progress
Move the ticket to In Progress so the board reflects reality.

### 3. Branch and isolate
Create a feature branch off the repo's integration branch (named in `CONTEXT.md`) and a worktree for it (`worktree-isolation`). All work happens here, never on the default branch.

### 4. Write or confirm the change spec
Draft the change spec into the Linear issue following `spec-authoring` (`templates/change.md`): problem, approach, **design** (data model / interface / scenarios, scaled to size), acceptance criteria, out of scope. Keep it short; depth scales with size. Confirm it with the user if the scope is non-obvious. If the work turns out to be unconfirmed or too big for one change, stop and `/propose` it instead.

### 5. Build
Dispatch the `dev` agent (or build directly) following `test-driven-development` and `code-quality`. One acceptance criterion at a time: RED, GREEN, REFACTOR.

### 6. Verify and stop at review-ready
Run the repo's lint / type / test gate (`CONTEXT.md`), read the output, and confirm the change spec still matches what was built. Then hand to `/review`.

## Pause conditions
Stop and ask only when information is genuinely missing (`spec-driven-development` § blocked). Otherwise run through to review-ready without prompting at every step.
