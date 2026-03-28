# Spec-Driven Development Pipeline

Every task flows through the agent team in order. This file is the full reference — `CLAUDE.md` contains only a summary.

## Pipeline Flows

```
# Backend / CLI tasks:
strategist → product-manager → architect → backend-dev → reviewer → deployment-manager
   (why)         (what)          (how)     (build + test)  (verify)      (ship it)

# Frontend tasks (any React/TypeScript/UI work):
strategist → product-manager → marketing-comms → architect → frontend-dev → reviewer → deployment-manager
                                  (brand + copy)    (how)     (build + test)  (verify)      (ship it)

# Full-stack tasks (backend + frontend together):
strategist → product-manager → marketing-comms → architect → backend-dev + frontend-dev → reviewer → deployment-manager
                                                              (run in parallel worktrees)
```

## Stage Details

1. **Strategy** — `strategist` defines principles, objectives, and which problems to solve next. Pauses for user input on priorities and positioning. (L2 checkpoints)
2. **Spec** — `product-manager` writes a product spec in `specs/products/` using the template. Defines user stories, acceptance criteria, scope, and security requirements. Pauses for user input on stories, ACs, and scope. (L2 checkpoints)
3. **Design** — `architect` reads the product spec and produces data models, CLI interface design, schema definitions, test strategy, and security considerations.
4. **Build + Test** — `backend-dev` (Python) or `frontend-dev` (React/TypeScript) follows TDD: write tests for each acceptance criterion first, then implement to make tests pass. Backend: run `ruff check .` alongside tests. Frontend: run `vitest run` alongside tests. All code must be lint-clean and test-passing before signaling ready for review.
5. **Verify** — `reviewer` validates the implementation against the spec, checks security, confirms TDD was followed, and runs the test suite. For frontend tasks, also runs the design system checklist (no hardcoded hex, all primitives from `components/ui/`, icons from `components/icons/`). Any non-blocking issues found during review are recorded as `review_carry_forward` items on the **next** version's backlog task in `manifest.yaml` — not on the completed task.
6. **Deploy** — `deployment-manager` runs only after a reviewer PASS. Stages the right content for the target repo, commits with a structured message, creates a version tag, and pushes. Updates the manifest to `done`. Never deploys on a FAIL verdict — surfaces the issue and stops.

## Pipeline Tiers

Every task runs one of three pipelines. The `tier` field in `manifest.yaml` controls routing; it defaults to `standard` if absent.

**Express** — carry-forward fixes and fully-specified patches
- **Eligible:** items where every step is already described in `review_carry_forward`, or single-behaviour bug fixes with no design ambiguity
- **Gate:** *Could a dev implement this from the manifest description alone, with zero ambiguity?* If yes, Express. If no, Standard.
- **Pipeline:** `backend-dev → reviewer → deploy` — no spec, no design, no self-reviews
- **Manifest:** set `tier: express` when moving the task to active status

**Standard** — new features, schema changes, anything requiring design judgment
- **Eligible:** everything not clearly Express
- **Pipeline:** full `strategist → product-manager → architect → backend-dev → reviewer → deploy`
- **Manifest:** `tier: standard` (or absent — this is the default)

**Discovery** — exploratory spikes, proof-of-concept work
- **Eligible:** work to validate a direction before committing to building it
- **Pipeline:** `backend-dev` only — output may not ship
- **Manifest:** set `tier: discovery`; add a description of what's being validated
- **Exit:** promote to Standard (write a spec from what was learned) or discard

## Task Types

The `type` field classifies tasks in `manifest.yaml`. Feature and chore tasks live in the `tasks:` section; bugs and refactors live in the `maintenance:` section.

| Type | Section | Default tier | Pipeline |
|---|---|---|---|
| `feature` (default) | `tasks:` | standard | Full pipeline or as specified by `tier` |
| `bug` | `maintenance:` | express | dev → reviewer → deploy |
| `refactor` | `maintenance:` | steward-sourced | steward → dev → reviewer (or + architect) |
| `chore` | `tasks:` | n/a | Human-driven, no agent pipeline |

**When to create a `type: bug` maintenance item:**
- A reviewer records a non-blocking finding and there is no upcoming feature version to bundle it into
- A defect or usability issue is found during real use that can be fixed independently
- A carry-forward item on a completed task was not absorbed into the next scheduled version

Use `source_task` to link a maintenance item back to the task where it was originally surfaced. Maintenance items use the same status flow as tasks (`backlog → ready_for_dev → ready_for_review → ready_for_deploy → done`).

## Bug Tracking

Bugs are tracked in `bugs/` as individual files — **not** in `manifest.yaml`. The manifest is for features and chores; bugs are high-volume and need their own space.

**Creating a bug:**
1. Copy `specs/templates/bug-report.md` to `bugs/BUG-NNN-short-slug.md` (next sequential number)
2. Fill in description, steps to reproduce, expected/actual behaviour, environment, and affected spec
3. Add a row to the index table in `bugs/README.md`

**When a bug enters the dev pipeline**, update its status to `in_progress` in the bug file. No manifest entry is needed — the bug file is the source of truth.

**Fix requirements — a bug fix PR is not complete unless all four are done:**
1. **Regression test** — a test that would have caught this bug. Mandatory; if genuinely untestable, explain why in the bug file.
2. **Spec / AC updated** — if the bug revealed a missing or wrong acceptance criterion, update `specs/products/` to reflect the correct behaviour.
3. **ADR updated** — if the bug revealed a design decision, constraint, or pattern that should be standardised, amend an existing ADR or create a new one in `specs/decisions/`.
4. **Bug file Resolution section filled in** — root cause, fix summary (commit/PR ref), and confirmation of the three items above.

**Reviewer checklist for bug fix PRs:**
- Regression test exists and is named in the bug file
- `spec_gap` field: if populated, the referenced spec file has been updated
- `adr_impact` field: if set, the referenced ADR has been amended or created
- Bug file status is `fixed` and Resolution section is complete
- Update the index table in `bugs/README.md` to reflect the new status

## Security Throughout

Security is embedded in every stage, even for local tools:
- **Product Manager**: Includes data sensitivity and validation requirements in specs
- **Architect**: Designs input validation rules and data integrity constraints
- **Dev**: Validates all inputs via Pydantic, parameterizes queries, no secrets in code
- **Reviewer**: Checks for injection, data exposure, and validates security requirements

## Orchestrator Pipeline Execution

Read `manifest.yaml` to determine where a task is and where to start. Never redo a completed stage — resume from the current status. Check the `tier` field (default: `standard`) to select the right pipeline.

**Standard tier:**

| Manifest status | Orchestrator action |
|---|---|
| `backlog` | Not ready — wait for strategist to prioritise |
| `ready_for_spec` | Invoke product-manager (with PM conversation loop) |
| `ready_for_design` | Run `/self-review` on the product spec → invoke architect |
| `ready_for_dev` | Run `/self-review` on the design doc → invoke backend-dev |
| `ready_for_review` | Invoke reviewer |
| `ready_for_deploy` | Invoke deployment-manager |
| `done` | Nothing to do |

**Express tier** (`tier: express` in manifest):

| Manifest status | Orchestrator action |
|---|---|
| `ready_for_dev` | Invoke backend-dev directly — no self-review, no spec/design required |
| `ready_for_review` | Invoke reviewer |
| `ready_for_deploy` | Invoke deployment-manager |

**Discovery tier** (`tier: discovery` in manifest):

| Manifest status | Orchestrator action |
|---|---|
| `ready_for_dev` | Invoke backend-dev — output may not ship |
| `done` or discarded | Close out the task; promote to Standard if continuing |

**Maintenance items** (`maintenance:` section in manifest):

Check both `tasks:` and `maintenance:` when scanning for work. Maintenance items follow the same status flow but skip spec and design stages. `type: bug` defaults to `tier: express`; `type: refactor` follows the steward → dev → reviewer pipeline. Maintenance items can be run independently or held and bundled into the next feature version — orchestrator uses judgement based on priority and whether a related feature task is already in flight.

Update the manifest status at each handoff. The manifest is the source of truth — if a pipeline breaks and restarts, read it and continue from where it stopped.

### Reviewer FAIL logic

1. **First FAIL** — send the full list of blocking issues back to backend-dev or frontend-dev (whichever built the task). Re-run the reviewer. (L1 — automated)
2. **Second FAIL** — stop. Present the blocking issues to the user and wait for direction. Do not loop again without user input. (L3 — stop)

### Deployment rules

All work deploys via branch + PR. PRs require user review before merge. No direct merges to main for feature work.
