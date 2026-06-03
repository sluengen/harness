# Calibrate Harness — CLAUDE.md

## Project

A deterministic workflow execution harness in Python. Decouples orchestration (external) from execution (this).

**Design specs live in `specs/` — read the relevant file first. `SPEC.md` is now an index.**

For workflow authoring see `AUTHORING.md`. For the full feature surface see `README.md`.

## Current state

v1 shipped and production-ready for `ClaudeAgent`-based workflows. The harness
runs YAML workflows end-to-end: AI nodes (Claude), script nodes, check nodes,
decision nodes, worktree lifecycle, loop blocks with `until:` / `until_bash:`,
and Linear webhook intake.

## v1 supported surfaces

| Surface | Status |
|---------|--------|
| `ClaudeAgent` dispatch | ✅ Supported |
| Script nodes | ✅ Supported |
| Check / decision nodes | ✅ Supported |
| Worktree lifecycle (create / cleanup) | ✅ Supported |
| Loop blocks (`until:`, `until_bash:`) | ✅ Supported |
| `$state.<field>` / `$inputs.<key>` substitution | ✅ Supported |
| Linear webhook intake | ✅ Supported |
| `CodexAgent` dispatch | ❌ Not supported in v1 |
| `OpencodeAgent` dispatch | ❌ Not supported in v1 |

## Tech stack

| Layer | Choice |
|------|--------|
| Runtime | Python 3.11+ in Docker |
| Deps | `uv` |
| Contracts / state | Pydantic 2 |
| CLI | Typer |
| Templates | Jinja2 |
| Workflows | YAML |
| AI dispatch | `anthropic` SDK (Claude via `claude_agent_sdk`) |
| State + events | SQLite (via `aiosqlite`) |
| Test / lint | pytest, ruff, mypy |

## Verification gate

Run all three before merging — all must be clean:

```bash
uv run ruff check .
uv run mypy harness intake
uv run pytest
```

Notes:
- `mypy` scope is `harness intake` (production code). Tests are excluded; the 89
  test-file mypy errors are a known backlog.
- `pytest` uses per-test timeout of 120 s (`pytest-timeout`); job-level CI
  timeout is 10 min.

## Conventions

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

- `/start <CAL-NNN>` — kick off work on a Linear issue (branch + worktree + Linear status + work + PR).
- `/build-workflow <description>` — build a new harness workflow YAML from a description; activates `skills/workflow-authoring.md`.

## Linear

No Linear CLI is installed. All Linear interaction uses the GraphQL API directly — `curl` in shell, `urllib.request` in Python. The key is `LINEAR_API_KEY` in `.env`. Do not search for a binary or attempt `npx linear`.

## Invoking the harness CLI

Use `bin/harness` instead of `uv run harness` when running from a shell that already has `VIRTUAL_ENV` set (e.g. a Homebrew-managed Python or another project's activated venv).  The wrapper unsets `VIRTUAL_ENV` before delegating to `.venv/bin/python`, bypassing `uv` entirely:

```bash
source .env && PYTHONPATH=. bin/harness run build --linear=CAL-NNN
```

**Why**: `uv run` warns and may use the wrong interpreter when `VIRTUAL_ENV` points at a path that doesn't match the project's `.venv` — see CAL-508.  `bin/harness` is immune to this because it never calls `uv`.

The old pattern still works when `VIRTUAL_ENV` is clean:

```bash
source .env && PYTHONPATH=. uv run harness <args>   # safe only if VIRTUAL_ENV is unset
```

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

## Layout

```
SPEC.md              ← design index (specs/ has per-feature detail)
README.md            ← user-facing overview
AUTHORING.md         ← workflow YAML authoring guide
CLAUDE.md            ← this file
.claude/settings.json
harness/             ← Python package
workflows/           ← YAML workflow definitions
tests/
docker/
```

## Git safety

- Never force-push (denied in `.claude/settings.json`).
- Never `git reset --hard` without confirmation.
- Stashes are not assumed stale — confirm before dropping.
