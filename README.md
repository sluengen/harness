# harness

A deterministic workflow execution harness for bounded LLM tasks. Decouples *what* gets run (orchestration, external) from *how* it runs (this harness).

> Build a deterministic execution engine, not an agent framework.

**Status:** v1.0 — engine, CLI, Docker image, ergonomics validation, and authoring guide all shipped. See [CHANGELOG](#changelog) below.

## What it does

You describe a workflow as YAML — sequenced steps with declared input/output contracts. The harness:

- Parses + validates the workflow at load time (typed inputs, derived state schema, contract compilation).
- Walks the steps deterministically (no LLM-driven control flow).
- Dispatches AI steps to an agent harness (Claude via `claude_agent_sdk` in v1; Codex + OpenCode adapters are v1.5).
- Validates each step's output against its contract.
- Writes state + per-tool events to a SQLite log keyed by run ID.
- Manages isolated git worktrees per run when the workflow opts in.

The agent does what only an agent can do (judgment, code, summarisation). Everything else — sequencing, gating, retries, state, git operations — is deterministic engine code.

For the full architectural picture and "why" of every decision, read [`SPEC.md`](./SPEC.md). For authoring workflows, read [`AUTHORING.md`](./AUTHORING.md).

## Install

### Local (development)

```bash
git clone git@github.com:sluengen/harness.git harness
cd harness
uv sync --extra dev
.venv/bin/harness version
```

### As a dependency in another repo (current path)

PyPI publishing comes in v1.1. For now, install from git:

```bash
# In your consuming repo
uv add git+ssh://git@github.com/sluengen/harness.git@v1.0.0
# or
pip install git+ssh://git@github.com/sluengen/harness.git@v1.0.0
```

The console script `harness` lands on `PATH` (under your venv).

### Docker

```bash
docker build -t harness:v1.0.0 -f docker/Dockerfile .
docker run --rm \
  -v "$(pwd)":/workspace -w /workspace \
  -v "$HOME/.claude":/root/.claude:ro \
  harness:v1.0.0 run <workflow>
```

The image mounts your project at `/workspace` and runs the workflow against it. State + worktrees + events land in `/workspace/.harness/` (gitignored). The `~/.claude` mount carries your Claude Code OAuth credentials into the container so the run uses subscription pricing — see [Authentication](#authentication) below for alternatives. See [`docker/README.md`](./docker/README.md) for full container details.

## Authentication

harness wraps `claude_agent_sdk`, which itself wraps Claude Code. **Auth follows Claude Code's conventions, not the raw Anthropic API.** Three paths, in order of preference:

| Path | Pricing | When |
|---|---|---|
| `claude /login` on the host, then run locally | Subscription | Local development. The SDK reads OAuth from `~/.claude/` automatically — **no env var needed.** |
| Mount `~/.claude` into the container, or pass `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) | Subscription | Docker / CI / non-interactive contexts where you can ship the OAuth token. |
| `ANTHROPIC_API_KEY` env var | API rates (per-token) | Fallback when neither OAuth path is convenient. CI without OAuth access. |

The SDK picks them up in this order: in-memory OAuth > `CLAUDE_CODE_OAUTH_TOKEN` > `ANTHROPIC_API_KEY`. If you've run `claude /login` and you're invoking harness on the same machine, you don't need to set anything.

## First run

A workflow needs three things in your repo:

1. The workflow YAML at `workflows/<name>.yaml`
2. The contracts + prompts it references (inline or shared)
3. **One of the auth paths above.** Default: just `claude /login` once; nothing else to set.

Smallest possible run-once example:

```yaml
# workflows/hello.yaml
name: hello
version: 1

steps:
  - id: greet
    type: ai
    prompt: prompts/hello.j2
    contract:
      message: string
    writes: [message]
```

```jinja
{# prompts/hello.j2 #}
Say hi in five words or fewer.
```

```bash
harness run hello
harness status <run-id>          # what happened
harness logs   <run-id>          # full event log
harness events <run-id> --json   # machine-readable
```

## Authoring workflows

Read [`AUTHORING.md`](./AUTHORING.md) — it's the canonical guide. About 400 lines, action-oriented, covers:

- Step types (`ai`, `script`, `check`, `decision`, `worktree`, `loop`) with minimal examples
- Inline contract grammar + the `$contracts/<name>` shared-schema mechanism
- State and `writes:` (derivation, type-driven merge, variable substitution)
- Standard prompts (`prompts/{analyze,implement,review,summarize}.j2`)
- A worked release-notes example end-to-end
- Common pitfalls

Or use the `/build-workflow` slash command (Claude Code) — the agent reads `AUTHORING.md` for you and produces a validated workflow from a description.

## Repository layout

```
harness/
├── agents/             ← agent role definitions (python-dev, reviewer)
├── skills/             ← reusable skills (TDD, scope discipline, workflow authoring)
├── commands/           ← user-invocable slash commands (start, build-workflow)
├── workflows/          ← workflow YAML files
├── contracts/          ← shared YAML contract schemas (referenced via $contracts/<name>)
├── prompts/            ← reusable Jinja prompt templates
├── harness/            ← the Python engine
├── docker/             ← container build + entrypoint
├── lessons/            ← validation artifacts (ergonomics runs, etc.)
├── tests/              ← unit + integration tests
├── AUTHORING.md        ← workflow author reference
├── SPEC.md             ← design specification (the "why")
└── CLAUDE.md           ← project bootstrap for Claude Code
```

`agents/`, `skills/`, `commands/` are agent-agnostic (plain markdown). Claude Code sees them via symlinks at `.claude/{agents,skills,commands}` → `../{agents,skills,commands}`. Other agent ecosystems can read the top-level paths directly or add their own symlink layer.

## Using harness on harness (dog-fooding)

From v1.0 onward, harness's own follow-on work flows through harness:

- All work items (bugs, features, improvements) → `harness run build --linear=<ISSUE-ID>`
- Domain assessments → `harness run steward --domain=<area>`

The first dog-food runs validated engine loader/worktree contract reconciliation and a series of AUTHORING.md refinements. If those ship cleanly through the harness, self-hosting is validated empirically.

## Tech stack

Python 3.11+ · Pydantic 2 · Typer · Jinja2 · PyYAML · `anthropic` SDK · `claude_agent_sdk` · `aiosqlite` · pytest · ruff · mypy · uv · Docker

## Related

- **Design ancestry:** Inspired by [Archon](https://github.com/coleam00/Archon) (workflow concepts, worktree-per-run, event log) and Anthropic's "build skills, not agents" guidance. Greenfield Python rewrite, not a fork.

## Changelog

### v1.0.0 (2026-05-27)

- Engine: workflow loader, derived state, type-driven merge, dispatch protocol, six node types (`ai`, `script`, `check`, `decision`, `worktree`, `loop`), three-layer retry, executor, runner.
- Dispatch: `claude_agent_sdk` adapter (v1); `codex`/`opencode` subprocess adapters exist but are gated behind `proc_fn=` for testing (not production-ready).
- CLI: dynamic per-workflow subcommands, query commands (`status`/`logs`/`events`/`worktrees`/`validate`/`version`/`runs`/`doctor`), v2-reserved decision verbs.
- Docker image with reproducible build.
- AUTHORING.md author guide.
- Ergonomics validation skill + 4 documented validation runs.
- `/build-workflow` slash command + `workflow-authoring` skill.
- Agent-agnostic layout (top-level `agents/`, `skills/`, `commands/`).
- Dict-merge state semantics, per-write merge override (`merge: replace`).
- Per-node retry configuration (`retry.transient.attempts`).
- Linear webhook intake + reconciliation (`intake/` package).
- State snapshots (per-completion) written after every successful node.
- Workflow-level cancellation on SIGINT + SIGTERM.

### v1.1 (planned)

- PyPI publish + release pipeline
- `harness init <dir>` scaffold for consuming repos
- 7 minor AUTHORING.md refinements
- Loader/worktree contract reconciliation

**Migration notes (v1.0 → v1.1):** No breaking changes expected. PyPI install path will replace the git-URL install once published. The `harness init` scaffold is additive.

### v1.5 (planned)

- `CodexAgent` and `OpencodeAgent` production wiring (subprocess + tool injection)
- AI node multi-turn improvements

**Migration notes (v1.1 → v1.5):** `CodexAgent` and `OpencodeAgent` currently raise `RuntimeError` unless a `proc_fn=` is passed (test-only). Production wiring lands in v1.5. Workflows using only `ClaudeAgent` are unaffected.

### v2 (planned)

- Human-actor decision nodes with pause/resume
- Decision pause/resume via CLI (`harness decision approve/reject`)

**Migration notes (v1.5 → v2):** Decision nodes will gain a pause/resume lifecycle. Existing `decision` steps using synchronous `auto:` resolution are unaffected. Steps expecting immediate resolution will need to opt in to the new pause semantics.
