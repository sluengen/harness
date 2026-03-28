# Harness — Spec-Driven Development Pipeline for Claude Code

A reusable system of work for autonomous, agent-driven product delivery using Claude Code.

## What this is

This repo contains the pipeline infrastructure, agent definitions, skills, hooks, and operational rules that enable a team of Claude Code agents to deliver software through a structured, spec-driven pipeline. It is project-agnostic — the agents, skills, and pipeline work the same way regardless of what you're building.

## What's included

| Component | Path | Purpose |
|-----------|------|---------|
| **Agent definitions** | `.claude/agents/` | 10 agents: strategist, PM, marketing-comms, architect, backend-dev, frontend-dev, reviewer, deployment-manager, system-steward, harness-reviewer |
| **Skills** | `.claude/skills/` | 8 behavioural skills: TDD, code review, design system, UX design, debugging, verification, writing quality, Notion sync |
| **Commands** | `.claude/commands/` | 9 slash commands: /start-task, /bug, /self-review, /pause-work, /forensics, /pipeline-status, /system-health, /harness-review, /release-notes |
| **Hooks** | `hooks/` | Context monitor, prompt injection scanner, workflow guard |
| **Pipeline spec** | `specs/arch/` | Pipeline definition, escalation levels, architecture principles |
| **Templates** | `specs/templates/` | Templates for ADRs, product specs, designs, reviews, bugs, brand guidelines |
| **Scripts** | `scripts/` | Manifest CLI, pipeline status viewer, git hooks |
| **Settings** | `.claude/settings.json` | Permission model (deny-list based) and hook registration |

## How to use

### For a new project

1. Copy the contents of this repo into your project repo (or use it as a template)
2. Customise `CLAUDE.md` — add your project overview, tech stack, testing commands, and conventions
3. Customise `manifest.yaml` — add your project details and initial tasks
4. Customise `specs/arch/principles.md` — add project-specific architecture principles
5. Customise `.claude/skills/design-system.md` — add your colour tokens, fonts, and spacing
6. Customise `.claude/skills/notion-sync.md` — add your Notion database IDs and file mappings (or remove if not using Notion)
7. Launch Claude Code and run `/start-task <task-id>`

### Syncing improvements back

When you improve a harness file during project work:

1. Identify which changes are generic (harness) vs project-specific
2. Copy the generic changes back to this repo
3. Commit with the project context that motivated the change

## Pipeline overview

```
strategist → PM → [marketing-comms →] architect → dev → reviewer → deploy
```

Three tiers: `standard` (full pipeline), `express` (dev → reviewer → deploy), `discovery` (dev only).

See `specs/arch/pipeline.md` for the full reference and `CLAUDE.md` for the orchestrator rules.

## Key design decisions

- **Branch isolation as safety boundary** — agents operate freely within worktrees; humans review at the PR gate (ADR-009)
- **Deny-list permissions** — `Bash(*)` allowed, dangerous operations explicitly denied
- **Skills over inline rules** — behavioural knowledge lives in skill files, not duplicated in agent definitions
- **Escalation levels** — L0 (autonomous) through L3 (stop), shared across all agents
- **Advisory hooks** — hooks inject context but never block execution
