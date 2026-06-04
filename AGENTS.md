# Harness - AGENTS.md

## Project

Harness is a deterministic workflow execution harness in Python. It decouples
orchestration, which lives outside this repo, from execution, which this repo
owns.

Read the relevant design file in `specs/` before changing behavior. `SPEC.md`
is an index. Use `AUTHORING.md` for workflow authoring details and `README.md`
for the user-facing feature surface.

## Current State

v1 is shipped and production-ready for `ClaudeAgent`-based workflows. The
harness runs YAML workflows end to end: AI nodes, script nodes, check nodes,
decision nodes, worktree lifecycle, loop blocks with `until:` / `until_bash:`,
and Linear webhook intake.

## Supported Surfaces

| Surface | Status |
|---|---|
| `ClaudeAgent` dispatch | Supported |
| Script nodes | Supported |
| Check / decision nodes | Supported |
| Worktree lifecycle (`create` / `cleanup`) | Supported |
| Loop blocks (`until:`, `until_bash:`) | Supported |
| `$state.<field>` / `$inputs.<key>` substitution | Supported |
| Linear webhook intake | Supported |
| `CodexAgent` dispatch | Not supported in v1 |
| `OpencodeAgent` dispatch | Not supported in v1 |

## Tech Stack

| Layer | Choice |
|---|---|
| Runtime | Python 3.11+ in Docker |
| Dependencies | `uv` |
| Contracts / state | Pydantic 2 |
| CLI | Typer |
| Templates | Jinja2 |
| Workflows | YAML |
| AI dispatch | `anthropic` SDK through `claude_agent_sdk` |
| State + events | SQLite through `aiosqlite` |
| Test / lint | pytest, ruff, mypy |

## Verification Gate

Run the canonical script before merging or tagging:

```bash
bash scripts/verify.sh
```

This runs, in order: ruff, production mypy, pytest with durations, CLI smoke,
and workflow validation. The script uses `uv run --extra dev` so dev tools and
`pytest-timeout` are active.

Individual commands, if you need one step at a time:

```bash
uv run --extra dev ruff check .
uv run --extra dev mypy harness intake
uv run --extra dev pytest --durations=20
uv run --extra dev python -m harness.cli version
uv run --extra dev python -m harness.cli validate workflows/build.yaml
```

Notes:

- `mypy` scope is `harness intake` production code. Tests are excluded.
- `pytest` uses a per-test timeout of 120 seconds through `pytest-timeout`.
- Slow/integration tests use pytest markers; run `pytest -m 'not slow and not integration'` to skip them locally when appropriate.
- Prefer `python -m harness.cli` for smoke checks to avoid stale console-script shims.

## Conventions

- Use TDD for behavior changes. See `skills/test-driven-development.md`.
- Keep commits atomic and leave the project working after each one.
- Work on feature branches off `dev` for implementation work. Do not commit implementation directly to `main` unless the user explicitly asks.
- Run the verification gate before declaring work complete when feasible.
- Use worktree isolation for multi-commit or risky flows. See `skills/worktree-isolation.md`.
- Keep edits scoped to the requested behavior; do not rewrite nearby code just because it is imperfect.

## Repo Markdown Assets

The canonical agent, skill, and command definitions live at the repo root:

```text
agents/
skills/
commands/
```

These files are plain markdown. Read and apply them directly when relevant.
Claude Code also sees them through `.claude/` symlinks, but the top-level
directories are canonical.

### Agents

| File | Use |
|---|---|
| `agents/python-dev.md` | Implementation work: features, modules, contracts, dispatch adapters |
| `agents/reviewer.md` | Pre-merge review of a branch or diff |

When using Codex sub-agents, read the relevant `agents/*.md` file and pass its
content as the role instructions for a spawned worker or explorer. Do not assume
Claude's `/commands` or `subagent_type` mechanism is available in Codex.

### Skills

Use these repo skills as local workflow guidance when they match the task:

- `skills/test-driven-development.md`
- `skills/scope-discipline.md`
- `skills/verification-before-completion.md`
- `skills/worktree-isolation.md`
- `skills/workflow-authoring.md`
- `skills/workflow-author-ergonomics.md`
- `skills/code-review.md`

### Commands

Command files in `commands/` describe workflows that can be performed manually
by reading the markdown:

- `commands/start.md`
- `commands/build-workflow.md`
- `commands/ingest.md`

Codex does not natively execute slash commands from markdown. If asked to use
one, read the command file and perform the steps with available tools.

## Linear

No Linear CLI is installed. Use available Linear connector tools when present.
If falling back to local scripts, Linear access is through the GraphQL API
(`curl` or Python `urllib.request`) with `LINEAR_API_KEY` in `.env`. Do not
search for a Linear binary or attempt `npx linear`.

## Invoking the Harness CLI

When running from a shell that may already have `VIRTUAL_ENV` set, prefer the
wrapper:

```bash
source .env && PYTHONPATH=. bin/harness run build --linear=ISSUE-ID
```

The wrapper unsets `VIRTUAL_ENV` before delegating to `.venv/bin/python`.

For verification and smoke tests, prefer the module form used by
`scripts/verify.sh`:

```bash
uv run --extra dev python -m harness.cli version
```

## Commit Format

Use:

```text
type(scope): description
```

Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `spec`.

## What This Repo Does Not Contain

Harness is decoupled from any one project. It does not:

- Embed project-specific pipeline knowledge; workflows are YAML, called by reference.
- Carry business strategy, brand, or product specs.
- Store project-specific manifests or change folders.

Those live in their respective project repos.

## Layout

```text
SPEC.md              design index; specs/ has per-feature detail
README.md            user-facing overview
AUTHORING.md         workflow YAML authoring guide
CLAUDE.md            Claude-specific guidance
AGENTS.md            Codex/agent-agnostic guidance
.claude/settings.json
agents/              reusable role definitions
skills/              reusable workflow guidance
commands/            markdown command workflows
harness/             Python package
workflows/           YAML workflow definitions
tests/
docker/
```

## Git Safety

- Never force-push unless the user explicitly asks.
- Never run `git reset --hard` without confirmation.
- Do not assume stashes are stale; confirm before dropping them.
- Do not revert user changes. If the worktree is dirty, inspect and preserve unrelated edits.
