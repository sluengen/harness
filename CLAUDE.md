# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. It defines the spec-driven development pipeline, agent coordination, and operational rules.

<!-- PROJECT: Your project's CLAUDE.md should define the tech stack, testing
     commands, conventions, and product-specific references. This harness
     CLAUDE.md covers only the pipeline and agent infrastructure. -->

## Project Overview

<!-- PROJECT: Replace this section with your project overview, tech stack,
     and repository references. -->

## Parallel Build Streams (Worktrees)

Use git worktrees to run multiple pipeline tasks simultaneously. Each stream gets an isolated working directory on its own branch.

### Rules

- Each stream targets a **different manifest task** — never work on the same task in two streams
- The **manifest** is the only shared file; read it at stream start, update only your own task
- Worktree directories live in `.worktrees/` (gitignored)
- Branch names match the task slug from the manifest
- **Manifest updates must be committed separately** from code/spec/design changes — keeps merge conflicts isolated from implementation history

### Git safety

- **All work must be on a branch.** Never leave implementation changes uncommitted on `main`.
- **Never assume uncommitted changes or stashes are stale.** Always show the user what's in them before dropping. Other sessions may be active.
- **If `git pull` is blocked**, stash to proceed but do NOT drop without user approval.
- **Sync regularly** — after merging a PR or before starting a new task, pull main and rebase active worktrees.

## Document Hierarchy

| Document | Purpose | Owner | Supports |
|----------|---------|-------|----------|
| `strategy/strategy.md` | Why we're building, what products, for whom | strategist | Business direction |
| `strategy/principles.md` | Overarching decision-making principles | strategist + architect | All decisions |
| `specs/products/*.md` | What to build — user stories, ACs, scope | product-manager | Product definition |
| `specs/arch/principles.md` | How we build — technical principles governing all design decisions | architect | Architecture decisions |
| `specs/arch/escalation-levels.md` | When to pause — L0–L3 autonomy scale for agent and orchestrator actions | architect | All agent behaviour |
| `specs/arch/pipeline.md` | Full pipeline reference — tiers, task types, bug tracking, reviewer/deploy rules | architect | Pipeline execution |
| `context/anti-patterns.md` | What failed and why — mistakes to avoid repeating | all agents | Preventing rework |
| `specs/decisions/ADR-*.md` | Why we built it this way — record of significant architectural decisions | architect | Future design work |
| `specs/designs/*.md` | How to build this task — schemas, models, test strategy | architect | Technical design |
| `manifest.yaml` | Task backlog — status, assignments, artifacts | all agents | Coordination |
| `bugs/BUG-NNN-*.md` | Bug reports — reproduction, root cause, fix, regression test, spec/ADR impact | dev + reviewer | Bug triage and regression prevention |

## Spec-Driven Development Pipeline

Full reference: `specs/arch/pipeline.md`. Summary below.

```
Backend:   strategist → PM → architect → backend-dev → reviewer → deploy
Frontend:  strategist → PM → marketing-comms → architect → frontend-dev → reviewer → deploy
Full-stack: both dev agents run in parallel worktrees after architect
```

**Tiers** (`tier` field in manifest, default `standard`):

| Tier | Pipeline | When |
|---|---|---|
| `standard` | Full pipeline | New features, schema changes, design judgment needed |
| `express` | `dev → reviewer → deploy` | Carry-forwards, unambiguous bug fixes |
| `discovery` | `dev` only | Spikes, proof-of-concept (output may not ship) |

**Task types:** `feature` and `chore` in `tasks:` section; `bug` and `refactor` in `maintenance:` section. Bugs tracked in `bugs/` files, not manifest.

### Agent Isolation — Worktrees Required

When the orchestrator launches any agent that modifies files (backend-dev, frontend-dev, reviewer, deployment-manager), it **must** use `isolation: "worktree"` on the Agent tool call. This gives the agent its own copy of the repo so it cannot conflict with the orchestrator's working directory or with other agents running in parallel on the same machine.

Branches alone are not sufficient — two sessions on the same working directory will still clobber each other's uncommitted files, stashes, and untracked artifacts. Worktrees provide true filesystem isolation.

Read-only agents (strategist, product-manager, architect, marketing-comms, system-steward, harness-reviewer) do not require worktree isolation since they do not write to the repo.

### Using Agents

All agents use the L0–L3 escalation scale (`specs/arch/escalation-levels.md`).

| Agent | Role | L2 checkpoints? |
|---|---|---|
| **strategist** | Product direction, principles, priorities | Yes — priorities, principles, personas, positioning |
| **product-manager** | Product specs, ACs, backlog | Yes — stories, ACs, scope, domain assumptions |
| **marketing-comms** | Brand, voice, copy, messaging | Yes — every direction + final copy sign-off |
| **architect** | Data models, schemas, test strategy | No |
| **backend-dev** | Python TDD, lint-clean before handoff | No |
| **frontend-dev** | React/TS TDD, design system enforcement | No |
| **reviewer** | Two-stage review: spec compliance then code quality | No |
| **system-steward** | Health checks, refactor recommendations | No |
| **harness-reviewer** | Harness coherence audits (MECE, Lean, Correct) | No |
| **deployment-manager** | PR creation after reviewer PASS only | No |

### Skills

Skills are behavioural knowledge that agents load and follow. Unlike commands (which you invoke explicitly), skills are referenced by agent definitions and applied automatically when relevant. They live in `.claude/skills/`.

| Skill | File | Used by | Purpose |
|-------|------|---------|---------|
| Design System | `.claude/skills/design-system.md` | frontend-dev, reviewer | Brand tokens, visual craft, component specs, animation, elevation, responsive, dark mode, reviewer checklist |
| UX Design | `.claude/skills/ux-design.md` | frontend-dev, reviewer, architect | User psychology, flow design, information architecture, cognitive load, accessibility, UX verification |
| TDD | `.claude/skills/test-driven-development.md` | backend-dev, frontend-dev | Red-green-refactor methodology, rationalisation rejection, restart triggers |
| Systematic Debugging | `.claude/skills/systematic-debugging.md` | backend-dev, frontend-dev | 4-phase root cause analysis, 3-strikes escalation rule |
| Verification Before Completion | `.claude/skills/verification-before-completion.md` | All agents | Fresh verification evidence required before any completion claim |
| Code Review | `.claude/skills/code-review.md` | reviewer, self-review | Two-stage review methodology, severity levels, verdict criteria |
| Writing Quality | `.claude/skills/writing-quality.md` | marketing-comms, product-manager, strategist, architect | AI slop elimination — banned phrases, structural anti-patterns, sentence-level rules |
| Notion Sync | `.claude/skills/notion-sync.md` | frontend-dev, reviewer, marketing-comms, orchestrator | Bidirectional Notion ↔ code sync for app copy and rich docs |

Dev agents read these at the start of every task. The reviewer enforces compliance — skipping TDD or claiming "done" without verification evidence is a FAIL.

## Permissions and Safety Model

**Permissions posture:** `Bash(*)` allowed, with a deny list for destructive operations (force push, hard reset, PR merge, direct merge to main). The safety boundary is **branch and worktree isolation**, not permission prompts. See ADR-009.

**Deny list** (in `.claude/settings.json`): force push, force-with-lease, hard reset, merge to main, PR merge. These are never auto-allowed.

**Agent secret access:** Agents must not access, store, or transmit secrets (API keys, tokens, credentials). If a task requires secret access, escalate to L3. Secrets are injected at deploy time, not during development.

### Hooks

Three hooks run automatically (registered in `.claude/settings.json`):

| Hook | Type | Trigger | Purpose |
|------|------|---------|---------|
| `hooks/context-monitor.js` | PostToolUse | Every tool call | Warns at 35% (warning) and 25% (critical) remaining context. Debounced to every 5 tool uses. |
| `hooks/prompt-guard.js` | PreToolUse | Write, Edit | Scans content for prompt injection patterns (instruction override, role play, system markers, invisible Unicode). Advisory only. |
| `hooks/workflow-guard.js` | PreToolUse | Write, Edit | Warns when editing source code on main outside a pipeline task. Advisory only. |

All hooks are advisory — they inject context messages but never block execution. If the context monitor fires at critical level, run `/pause-work` before the session ends.

## Orchestrator (Claude Code Main)

Claude Code (the main session) is the orchestrator. It manages the pipeline, mediates the PM conversation, tracks state via the manifest, and decides when to pause for user input. These rules govern how it runs.

### Escalation levels

All agents and the orchestrator use a shared 4-level scale defined in `specs/arch/escalation-levels.md`. Read that file for the full table of actions per level.

| Level | Rule | Orchestrator behaviour |
|---|---|---|
| **L0 — Autonomous** | Read-only, reversible, or pipeline-authorised | Proceed without notification |
| **L1 — Inform** | Safe, localised changes | Proceed, mention in handoff summary |
| **L2 — Propose** | API/schema/scope/brand changes, 5+ files, new deps | Present options, wait for "go ahead" |
| **L3 — Stop** | Deploys, security, irreversible ops, reviewer FAIL ×2 | Halt, explain, wait for explicit instruction |

The orchestrator pauses for user input **only** at L2+ moments:
1. **PM scoping (L2)** — the product-manager has produced a scope proposal. Present it, relay user feedback, repeat until agreed. Then proceed autonomously.
2. **Brand/copy sign-off (L2)** — marketing-comms requires explicit approval at each checkpoint before handing off to architect.
3. **Repeated reviewer FAIL (L3)** — reviewer fails a second time after a dev fix attempt. Stop and present the full list of blocking issues.
4. **Agent escalation (L2/L3)** — any agent explicitly flags a decision it cannot make autonomously, stating the level.

Everything at L0–L1 runs through without interruption. Do not ask for approval between pipeline stages unless an agent raises an L2+ escalation.

### Pipeline execution

Read `manifest.yaml` to determine where a task is and where to start. Never redo a completed stage — resume from the current status. Full pipeline tables and rules are in `specs/arch/pipeline.md`.

**Quick reference:** manifest status → next action:
- `backlog` → wait | `ready_for_spec` → PM | `ready_for_design` → self-review + architect | `ready_for_dev` → self-review + dev | `ready_for_review` → reviewer | `ready_for_deploy` → deployment-manager | `done` → nothing
- Express tier skips spec/design/self-review. Discovery tier is dev-only.
- Check both `tasks:` and `maintenance:` sections when scanning for work.

**Reviewer FAIL:** first FAIL → send issues back to dev, re-review. Second FAIL → L3 stop, present to user.

**Deployment:** branch + PR only. PRs require user review before merge.

## Conventions

- Test-driven development: tests first, then implementation
- Atomic commits: each commit leaves the project in a working state
- Lint clean: all code must pass linting before handoff to reviewer

**Commit message format:** `type(scope): description`
- Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`
- Manifest-only commits use: `manifest: <description>` (no scope, no type prefix)

**Pull request format:**
- Title: `type(scope): description` — same as commit format, under 70 characters
- Body: summary bullets + test plan checklist
- PRs require user review before merge — deployment-manager creates the PR but does not merge it
