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

- TDD — tests before implementation.
- Atomic commits, each leaves the project working.
- All work on feature branches off `main`. Never commit implementation directly to `main`.
- Lint passes before tests run.

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
