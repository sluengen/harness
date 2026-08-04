<!-- guidance:start@0.4.0 -->

**Tracker operations go through the `tracker` skill.** Read `CONTEXT.md`'s `tracker:` field and use the matching provider recipe — `linear` → the `linear` skill, `github` → the `github-issues` skill, `none` → the degrade the `tracker` skill documents. Do not embed provider API calls here.
# /start — begin work on a ticket

Usage: `/start <TICKET-ID>`

Sets up an isolated workspace for a tracked ticket and drives it test-first through to a review-ready state. Implements the `spec-driven-development` flow.

## Steps

### 1. Open the ticket
Fetch the ticket and print a brief (title, id, state, link). Fetch it through the `tracker` skill's `open` operation. If the ticket is already Done, or names unmet dependencies, stop and report.

### 2. Mark it In Progress
Move the ticket to In Progress so the board reflects reality.

### 3. Branch and isolate
Create a feature branch off the repo's integration branch (named in `CONTEXT.md`) and a worktree for it (`worktree-isolation`). All work happens here, never on the default branch.

### 4. Ground the spec
Before writing the change spec, ground the facts it will rest on in current reality (`spec-driven-development` step 2; `spec-authoring` → Grounding). Where a sub-agent host is available, dispatch the read-only `researcher` agent (`agents/researcher.md`): it investigates in its own context and returns a distilled grounding brief — verified facts anchored to `path:line`, current versions/flags, decisions surfaced, open questions. Where none is available, self-ground inline (the fallback). Record the brief as the change spec's `Grounding` section. Verbs stay deterministic — dispatch lives in this agent-led flow, never in the `start` CLI verb; the extra agent counts against the loop spend breakers (`CONTEXT.md` `loop:`).

### 5. Write or confirm the change spec
Draft the change spec into the tracker issue following `spec-authoring` (`templates/change.md`): problem, approach, **design** (data model / interface / scenarios, scaled to size), acceptance criteria, out of scope. Keep it short; depth scales with size. Confirm it with the user if the scope is non-obvious. If the work turns out to be unconfirmed or too big for one change, stop and `/propose` it instead.

### 6. Build
Dispatch the `dev` agent (or build directly). **Before writing code, open and read `skills/test-driven-development/SKILL.md` and `skills/code-quality/SKILL.md`** — naming the method is not reading it. Then build one acceptance criterion at a time: RED, GREEN, REFACTOR, under the non-negotiable rules in `AGENTS.md` — test-first, a measurable criterion needs a test that measures it, and no completion claim without fresh evidence.

### 7. Verify and stop at review-ready
Run the repo's lint / type / test gate (`CONTEXT.md`), read the output, and confirm the change spec still matches what was built. Then hand to `/review`.

## Pause conditions
Stop and ask only when information is genuinely missing (`spec-driven-development` § blocked). Otherwise run through to review-ready without prompting at every step.
