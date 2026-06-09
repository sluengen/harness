<!-- guidance:template-context@0.1.4 -->
# CONTEXT.md

Agent-facing context for **harness**. This is the one file allowed to name this repo. The guidance files (skills, agents, commands) are universal and point here for everything repo-specific: stack, commands, paths, tools, and principles.

`README.md` is for humans. This is for agents. Read it first.

```yaml
profile: harness
visibility: committed
repo:
  name: harness
  linear: HAR   # team prefix — workspace/team UUID unknown; run /harness ingest or check Linear settings to confirm
layers:
  linear: true
  design_system: false
  feature_specs: false
stack:
  language: Python 3.11+
  framework: Pydantic 2 / Typer / aiosqlite
commands:
  install: "uv sync --extra dev"
  lint:    "uv run ruff check ."
  typecheck: "uv run mypy harness intake"
  test:    "uv run pytest"
  test_one: "uv run pytest <path/to/test_file.py::test_name>"
  verify:  "bash scripts/verify.sh"   # canonical gate: ruff → mypy → pytest → CLI smoke → workflow validation. Run before merge/tag.
  run:     "harness run build --linear=ISSUE-ID"   # ~/bin/harness Docker wrapper — see docker/README.md
branches:
  integration: dev      # feature branches base from here and merge back here
  release: main         # PRs from dev → main for releases
conventions:
  commit_format: "type(scope): description — feat / fix / chore / docs / refactor / test / spec"
tools:
  linear_cli: "GraphQL via curl (shell) or urllib.request (Python) — no linear binary, no npx linear"
paths:
  source: harness/
  tests: tests/
  proposals: specs/proposals/
  decisions: specs/   # ADRs not yet separated into decisions/; design docs in specs/
env:
  file: .env
  linear_token: LINEAR_API_KEY
```

## What this repo is

A deterministic workflow execution harness in Python. It decouples orchestration (external: Linear issues, webhook triggers) from execution (this repo). Other repos run it as their CI pipeline; the harness clones a worktree, dispatches agents, gates on review, and handles the git lifecycle. It has no product UI and no end-users — it is infrastructure.

## Architecture

The main package is `harness/` (Python). Workflows are YAML files in `workflows/` — the harness loads and executes them. The Linear webhook intake lives in `intake/`.

Key layers:
- **Workflow engine** — parses YAML, resolves `$state.<field>` / `$inputs.<key>` substitutions, runs loop blocks (`until:` / `until_bash:`), dispatches node types
- **Node types** — `ClaudeAgent` (via `anthropic` SDK / `claude_agent_sdk`), `CodexAgent` (subprocess/text-submit), `script` (shell), `check` / `decision`, `worktree` lifecycle
- **State store** — SQLite via `aiosqlite`; all run state and events persisted here
- **CLI** — `Typer`; entry point `harness.cli`; `bin/harness` wrapper script bypasses VIRTUAL_ENV conflicts
- **Intake** — Linear webhook receiver; routes to workflow runs

Design specs live in `specs/`; `SPEC.md` is the index. Read the relevant spec before changing any node type, state model, or workflow schema.

## Repo-specific principles

- **TDD is mandatory** — no production code without a failing test first. No exceptions.
- **Atomic commits** — each commit leaves the project working and passes the verification gate.
- **Spec before code** — read the relevant `specs/` section before changing behaviour; update the spec when what ships diverges from what is written.
- **Scope discipline** — do not rewrite nearby code "while you're there". Every changed file must trace to the task.
- **`uv.lock` is committed** — required for reproducible `uv sync --frozen` in Docker builds. Never gitignore it.

## Decisions index

No formal `decisions/` directory exists yet. Major design decisions are in `specs/` and inline in `SPEC.md`. ADRs should go in `specs/decisions/` when first created.

## Where deeper truth lives

- **How the system is built** → `specs/` (design docs; `SPEC.md` is the index)
- **Workflow YAML grammar** → `AUTHORING.md`
- **User-facing feature surface** → `README.md`
- **Ideas not yet confirmed** → `specs/proposals/`
- **Linear (issues / in-flight work)** → linear.app (team: HAR)

## Gotchas

- **Primary invocation is `~/bin/harness` (Docker wrapper).** `cd` to any repo, run `harness run build --linear=ID`. The wrapper mounts CWD as `/workspace`, reads `LINEAR_API_KEY` from a local `.env`, and extracts the Claude OAuth token from the macOS Keychain automatically. See `docker/README.md` for the full wrapper script and installation steps.
- **`bin/harness` is dev-time only.** It hard-codes `.venv/bin/python` relative to the harness repo root and only works inside the harness checkout. Use it when iterating on harness source itself; use `~/bin/harness` for everything else.
- **Cross-repo execution** — `cd` to the target repo and run `harness run build --linear=ID`. No `--repo` flag needed with the Docker wrapper; CWD is mounted automatically. `--verify-command` and `--branch-prefix` are still accepted for custom gates and branch naming.
- **Native install path** (alternative to Docker): `uv tool install .` from the repo root installs the `harness` console script on PATH and bundles workflow YAMLs as package data. Use when Docker is not available. Credentials and env vars must be set manually.
- **No Linear CLI is installed.** All Linear interaction is via the GraphQL API (`curl` / `urllib.request`). Do not search for a `linear` binary or `npx linear`.
- **`mypy` scope is `harness intake`** — tests are excluded from the type check. The 89 test-file mypy errors are a known backlog, not a gate failure.
- **Slow/integration tests have markers** — run `pytest -m 'not slow and not integration'` locally to skip them. CI runs all.
- **Verification output can come back empty** in the Claude Code Bash tool (it auto-backgrounds long commands). Redirect to `/tmp/<file>.txt` and `tail` it.

## Python conventions

The `dev` agent builds here in Python 3.11+ with mypy strict. Beyond the universal `code-quality`:

- **`@asynccontextmanager` for resource handles, not `async def`.** A helper that `return`s a resource from `async def` yields an awaitable you cannot `async with` over — and `aiosqlite` raises `RuntimeError: threads can only be started once` if you await-then-enter it. Wrap with `@asynccontextmanager` and `yield` the resource inside `try/finally`. `harness/state/store.py` is the reference; copy it for any managed resource (DB connection, HTTP session, subprocess).
- **Exception names mirror SPEC vocabulary, not the PEP 8 `Error` suffix.** The spec's "contract violation" → `ContractViolation`, "stalled agent" → `AgentStalled` (so type names grep against the spec). Suppress N818 with a scoped `# noqa: N818` per class.
- **Validate at boundaries (Pydantic), trust within.** Async by default for I/O. No `eval`/`exec`/`pickle` on untrusted data; no string-formatted SQL.
- **Security:** validate untrusted paths are inside the expected prefix; never `shell=True` with user input (list-form args); secrets from env only, never logged or committed.
