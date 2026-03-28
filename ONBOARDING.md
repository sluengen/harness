# Workspace Setup

Everything you need to get a working local environment for a project using this harness.

---

## Prerequisites

- **Git**
- **Python 3.11+** (for manifest scripts)
- **Node.js 20+** (if your project has a frontend)
- Project-specific dependencies (see your project's CLAUDE.md)

---

## First-time setup

<!-- PROJECT: Replace or extend with your project's setup script -->

1. Clone the project repo
2. Install dependencies per the project's requirements
3. Install the git hook for manifest view generation:

```bash
cp scripts/hooks/post-commit .git/hooks/post-commit
chmod +x .git/hooks/post-commit
```

---

## Key scripts

| Script | Purpose |
|--------|---------|
| `scripts/manifest.py` | CLI for reading and updating `manifest.yaml` |
| `scripts/pipeline_status.py` | Prints the current pipeline state |
| `scripts/hooks/post-commit` | Regenerates `views/*.md` when `manifest.yaml` changes |

---

## Git workflow

```
feature/* → staging → main
               ↓         ↓
          staging env  production
```

- Create feature branches from `main`
- PR to `staging` for integration verification
- PR from `staging` to `main` for production promotion
- Hotfixes can PR directly to `main`

---

## Git hook — Markdown views

The repo includes a post-commit hook that regenerates `views/*.md` whenever
`manifest.yaml` changes. The setup instructions above install it.

To regenerate views manually at any time:

```bash
python3 scripts/manifest_to_md.py
```

---

## Repo structure (harness files)

```
.claude/
  agents/              Agent definitions (10 agents)
  commands/            Slash commands (9 commands)
  skills/              Behavioural skills (8 skills)
  settings.json        Permissions + hook registration
  review-scorecard.yaml  Scoring rubric
hooks/                 Claude Code hooks (context monitor, prompt guard, workflow guard)
specs/
  arch/                Pipeline, escalation levels, architecture principles
  templates/           Templates for ADRs, specs, designs, reviews, bugs
  decisions/           Architecture Decision Records
context/
  anti-patterns.md     Failure log — what went wrong and how to avoid it
scripts/
  manifest.py          Manifest CLI
  pipeline_status.py   Pipeline viewer
  hooks/post-commit    Git hook for view generation
manifest.yaml          Task backlog and pipeline state
CLAUDE.md              Orchestrator instructions
```

---

## Pipeline overview

Full reference: `specs/arch/pipeline.md`

```
strategist → PM → [marketing-comms →] architect → dev → reviewer → deploy
```

Each task flows through these stages. The manifest tracks where each task is. Run `/start-task <task-id>` to kick off work from wherever a task currently sits.
