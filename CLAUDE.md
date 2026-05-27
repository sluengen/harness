# Calibrate Harness — CLAUDE.md

## Project

A deterministic workflow execution harness in Python. Decouples orchestration (external) from execution (this).

**The full design lives in `SPEC.md` — read it first.** This file is intentionally short and points at the spec.

## Current state

Pre-implementation. The deliverable for this phase is the SPEC. Code lands only after the SPEC is approved.

## Tech stack (planned)

| Layer | Choice |
|------|--------|
| Runtime | Python 3.11+ in Docker |
| Deps | `uv` |
| Contracts / state | Pydantic 2 |
| CLI | Typer |
| Templates | Jinja2 |
| Workflows | YAML |
| AI dispatch | `anthropic` SDK (Claude), `openai` SDK pointed at Ollama for local models |
| State + events | SQLite (via `aiosqlite`) |
| Test / lint | pytest, ruff, mypy |

## Conventions (when implementation starts)

- TDD — tests before implementation. See `skills/test-driven-development.md`.
- Atomic commits, each leaves the project working.
- All work on feature branches off `main`. Never commit implementation directly to `main`.
- Lint passes before tests run. Verification gate in `skills/verification-before-completion.md`.
- Worktrees per `skills/worktree-isolation.md` for any multi-commit flow.

## Agents

| Agent | When to dispatch |
|---|---|
| `python-dev` | Implementation work — features, modules, contracts, dispatch adapters |
| `reviewer` | Pre-merge review on a branch's diff |

Invoke via the Agent tool with the matching `subagent_type`.

## Commands

- `/start-task <CAL-NNN>` — kick off work on a Linear issue (branch + worktree + Linear status + work + PR).
- `/build-workflow <description>` — build a new slate-harness workflow YAML from a description; activates `skills/workflow-authoring.md`.

## Agent-agnostic layout

The canonical location for agent definitions, skills, and commands is the repo root: `agents/`, `skills/`, `commands/`. These are plain markdown — any agent harness (Claude Code, Codex, OpenCode, etc.) that can read markdown can consume them.

For Claude Code's discovery convention, `.claude/agents`, `.claude/skills`, `.claude/commands` are **symlinks** pointing at the canonical top-level directories. Edit at the canonical location; Claude Code sees the change via the symlink. New agent ecosystems can add their own symlink layer (or read top-level directly).

`.claude/settings.json` stays under `.claude/` — it's genuinely Claude-specific (permissions, hooks).

## Commit format

`type(scope): description`
Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `spec`.

## What this repo does NOT contain

This harness is decoupled from any one project. Specifically, it does **not**:

- Embed Calibrate-specific pipeline knowledge — workflows are YAML, called by reference.
- Carry business strategy, brand, or product specs.
- Store project-specific manifests or change folders.

Those live in their respective project repos.

## Layout (proposed in SPEC, not yet instantiated)

```
SPEC.md              ← source of truth for design
README.md
CLAUDE.md            ← this file
.claude/settings.json
harness/             ← Python package (created after SPEC approval)
workflows/           ← YAML workflows (created after SPEC approval)
tests/
docker/
```

## Git safety

- Never force-push (denied in `.claude/settings.json`).
- Never `git reset --hard` without confirmation.
- Stashes are not assumed stale — confirm before dropping.
