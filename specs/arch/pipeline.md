# Spec-Driven Development Pipeline

Every task flows through an artifact dependency graph (DAG). This file is the prose reference — `CLAUDE.md` contains a summary. The machine-readable source of truth is `specs/arch/pipeline-schema.yaml`.

## Pipeline Model — Capability Graph

The pipeline is a DAG of artifacts, not a linear sequence of stages. The orchestrator asks **"what can happen next?"** — not "what stage are we at?"

```
proposal (required)
   ├── delta (recommended)  ──┐
   ├── design (recommended) ──┼── tasks (recommended) ── code (required) ── review (required) ── deploy (required)
   └── brand_review (recommended, frontend only)
                               │
   exploration (optional) ─────┘ (informational, never blocks)
```

**Parallel execution:** delta and design both require only proposal — they can run simultaneously. The orchestrator should exploit this.

### Requirement Levels

| Level | Rule | Who can waive |
|---|---|---|
| **required** | Must exist before downstream can proceed | Only user (L2 escalation) |
| **recommended** | Proposer can skip with justification in proposal.md | PM/architect in proposal |
| **optional** | Available when useful, never blocks | N/A — always skippable |

The guardrail against shortcutting is the **reviewer**, not pre-classification. The reviewer validates that every waived artifact was genuinely unnecessary given the actual diff. An unjustified waiver is a review FAIL.

### Pipeline Flows

```
# Backend / CLI tasks:
PM → [delta + design in parallel] → architect (tasks) → backend-dev → reviewer → deploy
  (what)                             (how)              (build+test)  (verify)    (ship)

# Frontend tasks (any React/TypeScript/UI work):
PM → [delta + brand_review + design in parallel] → architect (tasks) → frontend-dev → reviewer → deploy
                                                                       (build+test)    (verify)    (ship)

# Full-stack tasks (backend + frontend together):
PM → [delta + brand_review + design in parallel] → architect (tasks) → [backend-dev + frontend-dev] → reviewer → deploy
                                                                        (parallel worktrees)
```

When recommended artifacts are waived, the pipeline compresses naturally. A well-described bug fix flows: proposal → code → review → deploy. No separate "tier" classification needed — the DAG handles it.

## Artifacts and State

### Feature Specs (Source of Truth)

Canonical specs live in `specs/features/`. Each describes a feature domain's **current implemented behaviour** — not what was built in a specific iteration.

- One spec per feature domain (e.g., `brew-logging.md`, `auth.md`)
- Uses RFC 2119 keywords (MUST/SHALL/SHOULD/MAY)
- Scenarios use Given/When/Then format (each maps to a test case)
- See `specs/templates/feature-spec.md` for format

### Proposal Quality Gate

The proposal is the single point where intent becomes scope. Every distinct requirement in the source issue (ticket description, user message, or bug report) must appear as a scoped item in the proposal's **Changes** or **Fix** section. The title gives the area; the description gives the specifics — solve the description, not the title.

**Checklist before a proposal is complete:**
1. Re-read the full source description sentence by sentence
2. For each distinct behaviour, fix, or expectation mentioned: confirm it appears in the proposal scope
3. If any requirement is intentionally excluded, state why in the proposal (out of scope, separate task, etc.)

Failing this gate is how partial fixes ship and the same ticket gets re-filed.

### Change Folders (Per-Task Work Products)

Each task produces artifacts in `specs/changes/<task-id>/`:

```
specs/changes/<task-id>/
  proposal.md          # Why: problem, scope, approach, waivers
  delta/               # What changes: deltas against feature specs
    <feature>.md       #   ADDED / MODIFIED / REMOVED / RENAMED requirements
  design.md            # How: data model, components, test strategy
  tasks.md             # Steps: implementation checklist
  review.md            # Verdict: reviewer output (PASS/FAIL + findings)
  exploration.md       # Optional: investigation notes (any phase)
```

### Waivers

When a PM or architect skips a recommended artifact, they include a **Waivers** section in `proposal.md`:

```markdown
## Waivers

- **delta**: No feature spec impact — this is a CSS-only fix to an existing component.
- **design**: No architecture decisions — single-file change to an existing pattern.
- **tasks**: Proposal describes the fix completely — no checklist needed.
```

The reviewer validates each waiver against the actual diff. If the diff contradicts the justification (e.g., "no design needed" but the diff adds a new API endpoint), the reviewer FAILs with "unjustified waiver."

### Derived Pipeline Position

The orchestrator evaluates the DAG — not a linear position list — to determine what happens next.

**Algorithm:**

1. Read change folder contents and proposal.md waivers
2. Mark each artifact as: **complete** | **waived** | **missing**
3. For each missing artifact, check if all dependencies are complete or waived
4. Unblocked + required + missing → **must happen next**
5. Unblocked + recommended + not waived + missing → **should happen next**
6. If no missing required/recommended artifacts upstream of code → **ready for dev**
7. If code complete → **ready for review**
8. If review PASS → **ready for deploy**

**Position labels** (for reporting):

| DAG state | Label |
|---|---|
| No change folder | `not_started` |
| Folder exists, no proposal | `proposing` |
| Proposal done, recommended artifacts in progress | `specifying` |
| All non-waived upstream complete | `ready_for_dev` |
| Dev working | `building` |
| Code committed, tests pass | `ready_for_review` |
| Reviewer working | `reviewing` |
| review.md with PASS | `ready_for_deploy` |
| review.md with FAIL | `review_failed` |

### Non-Linear Updates

Pipeline position does not regress when earlier artifacts are updated. The **high-water mark** (furthest required artifact completed) is preserved.

- Reviewer flags a spec gap → update proposal or delta, then re-review
- The fix path for a review FAIL citing a proposal issue is: update proposal → re-review (not: restart the entire pipeline)
- Updated artifacts trigger re-validation of downstream only
- The orchestrator never moves a task backwards in the manifest

### Manifest Role

The manifest (`manifest.yaml`) is a **release plan**, not a pipeline ledger.

- Tasks grouped by release version (or sprint/milestone)
- Three-state status: `todo` | `in_progress` | `done`
- Granular pipeline position derived from the DAG (above)

### Archive

When a task completes (PR merged):

1. Delta specs merge into canonical feature specs in `specs/features/`
2. Change folder moves to `specs/changes/archive/<release-version>/<task-id>/`
3. Full context preserved for audit trail

## Stage Details

1. **Strategy** — `strategist` defines principles, objectives, and which problems to solve next. This is an orchestrator responsibility at the release level, not a per-task artifact. Pauses for user input on priorities and positioning. (L2 checkpoints)
2. **Proposal** — `product-manager` writes `proposal.md` in the task's change folder. Defines problem, scope, approach, and any waivers for recommended artifacts. Pauses for user input on stories, ACs, and scope. (L2 checkpoints)
3. **Delta** — `product-manager` writes `delta/*.md` files. ADDED/MODIFIED/REMOVED/RENAMED requirements relative to canonical feature specs. Can be waived in proposal if no spec impact.
4. **Brand Review** — `marketing-comms` provides brand, voice, and copy direction. Frontend/fullstack only. Can be waived if no user-facing copy or visual impact. (L2 checkpoints)
5. **Design** — `architect` reads the proposal and delta specs, then writes `design.md`. Covers data models, API changes, component design, test strategy, security. Can be waived if no architecture decisions needed.
6. **Tasks** — `architect` writes `tasks.md` as an implementation checklist derived from design and delta specs. Can be waived if proposal provides sufficient direction.
7. **Build + Test** — `backend-dev` (Python) or `frontend-dev` (React/TypeScript) follows TDD: write tests for each scenario first, then implement. All code must be lint-clean and test-passing before signaling ready for review.
8. **Verify** — `reviewer` validates implementation against all non-waived artifacts, checks security, confirms TDD was followed, validates waivers against the actual diff. Writes `review.md`. For frontend: also runs design system checklist.
9. **Deploy** — `deployment-manager` runs only after a reviewer PASS. Creates a PR, updates manifest task status to `done`. Never deploys on a FAIL verdict.

### Exploration

Any task can include an **exploration phase**. Any agent creates `exploration.md` in the change folder documenting what they investigated and learned. This is informational — it doesn't gate anything, but is preserved in the archive.

## Task Types

| Type | Typical waivers | Pipeline |
|---|---|---|
| `feature` (default) | None — full pipeline recommended | proposal → delta → design → tasks → code → review → deploy |
| `bug` | Delta, design, tasks often waived | proposal → code → review → deploy |
| `refactor` | Delta often waived | proposal → design → code → review → deploy |
| `chore` | Depends on scope | proposal → whatever is needed → code → review → deploy |

These are guidelines, not rigid rules. The DAG handles the actual routing based on what's waived.

## Bug Tracking

Bugs are tracked in `bugs/` as individual files — not in `manifest.yaml`. The manifest's `maintenance:` section references open bugs for visibility.

**Creating a bug:**
1. Copy `specs/templates/bug-report.md` to `bugs/BUG-NNN-short-slug.md` (next sequential number)
2. Fill in description, steps to reproduce, expected/actual behaviour, environment, and affected spec
3. Add a row to the index table in `bugs/README.md`

**Fix requirements — a bug fix PR is not complete unless all four are done:**
1. **Regression test** — a test that would have caught this bug
2. **Feature spec updated** — if the bug revealed a missing or wrong requirement, update `specs/features/`
3. **ADR updated** — if the bug revealed a design decision that should be standardised
4. **Bug file Resolution section filled in** — root cause, fix summary, confirmation of above

## Security Throughout

Security is embedded in every artifact:
- **Product Manager**: Includes data sensitivity and validation requirements in proposals
- **Architect**: Designs input validation rules and data integrity constraints in design docs
- **Dev**: Validates all inputs via validation models, parameterizes queries, no secrets in code
- **Reviewer**: Checks for injection, data exposure, validates security requirements, validates waivers

## Orchestrator Pipeline Execution

Read the manifest to identify release scope and task status. Evaluate the DAG to determine what artifacts are needed next. Never redo a completed artifact — resume from where the DAG indicates.

**DAG-based execution:**

| DAG state | Orchestrator action |
|---|---|
| No change folder | Create `specs/changes/<task-id>/`, invoke product-manager |
| `proposal.md` exists, recommended artifacts not yet started | Run `/self-review` on proposal → invoke agents for unblocked artifacts (delta, design, brand_review can run in parallel) |
| All non-waived upstream artifacts complete | Run `/self-review` on design (if it exists) → invoke dev |
| Code committed, tests pass | Invoke reviewer |
| `review.md` with PASS | Invoke deployment-manager |
| `review.md` with FAIL | Send issues to dev (first FAIL) or escalate to user (second FAIL) |
| Task `done` in manifest | Archive change folder, merge deltas into feature specs |

**Compressed pipeline (when waivers apply):** If the PM waives delta, design, and tasks in the proposal, the orchestrator proceeds directly from proposal to dev. No separate routing — the DAG resolves naturally.

### Reviewer FAIL logic

1. **First FAIL** — send the full list of blocking issues back to dev. Re-run the reviewer. (L1 — automated)
2. **Second FAIL** — stop. Present the blocking issues to the user and wait for direction. Do not loop again without user input. (L3 — stop)

**Waiver FAIL** — if the reviewer flags an unjustified waiver, it's treated as a blocking issue. The fix path is: update the artifact that was wrongly waived (not restart the pipeline). The high-water mark is preserved.

### Deployment rules

All work deploys via branch + PR. PRs target `staging` by default when a staging branch exists, otherwise `main`. PRs require user review before merge. No direct merges to main for feature work.
