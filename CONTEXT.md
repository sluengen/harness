<!-- guidance:template-context@0.1.4 -->
# CONTEXT.md

Agent-facing context for **harness**. This is the one file allowed to name this repo. The guidance files (skills, agents, commands) are universal and point here for everything repo-specific: stack, commands, paths, tools, and principles.

`README.md` is for humans. This is for agents. Read it first.

```yaml
profile: harness
visibility: committed
repo:
  name: harness
  linear: CAL   # team prefix — Calibrate-coffee (CAL); harness work lives in the "Harness v3" project
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
  verify:  "bash scripts/verify.sh"   # canonical gate: ruff → mypy → pytest → CLI smoke. Run before merge/tag.
  run:     "harness start <ISSUE-ID> → review → close"   # verb loop; drive via /harness run. ~/bin/harness Docker wrapper — see docker/README.md
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

A set of **deterministic, audited verbs an agent calls** to drive a Linear ticket end-to-end — not an engine that drives agents. A single Claude session orchestrates *and* implements (reads the ticket, writes the code and tests, decides how to fix a review finding, when to re-review); the harness owns only the **durable record and the gate**. It has no product UI and no end-users — it is infrastructure other repos self-host. (The earlier deterministic YAML workflow engine was retired in CAL-574; `README.md` and `SPEC.md` §1–2 describe the current verb model.)

## Architecture

The main package is `harness/` (Python): a `Typer` CLI exposes the verbs, backed by a SQLite ledger, git-worktree lifecycle, and Codex review dispatch. The Linear webhook intake lives in `intake/`.

Three verbs, one ledger, one gate:
- **`start`** — validate the ticket, transition it to *In Progress*, create an isolated git worktree off the base branch (default `dev`), and open a `runs` ledger row.
- **`review`** — run Codex against the worktree HEAD and record a verdict (`pass` / `fail` / `defer`) **bound to that git SHA**; the session sees only the bounded verdict, not Codex's full reasoning.
- **`close`** — enforce the gate (a `start` exists **and** a `verdict=pass` whose reviewed SHA equals the current HEAD), then commit / merge / push, transition the ticket to *Done*, and finalize the run.
- **Read / ops commands** — `status` / `logs` / `events` / `runs` / `worktrees` / `doctor` / `version` inspect a run without mutating state; `serve` runs the narrow host launcher control socket.
- **State store** — SQLite via `aiosqlite`; the `runs` / `events` ledger is the whole audit trail.

The ledger is a complete audit trail **only if nothing hand-rolls a `git merge` / `push` or a Linear mutation** for the run lifecycle — every git and ticket state transition goes through a verb, and `close` validates against the ledger as a backstop (D5). Design specs live in `specs/`; `SPEC.md` is the index. Read the relevant spec before changing a verb, the ledger schema, or the close gate.

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
- **The verb contract the agent drives** → `commands/harness.md`
- **User-facing feature surface** → `README.md`
- **Ideas not yet confirmed** → `specs/proposals/`
- **Linear (issues / in-flight work)** → linear.app (team: CAL / Calibrate-coffee, project "Harness v3")

## Gotchas

- **Primary invocation is `~/bin/harness` (Docker wrapper).** `cd` to any repo and call a verb — `harness start <ISSUE-ID>`, then `review` / `close`. The wrapper mounts CWD as `/workspace`, reads `LINEAR_API_KEY` from a local `.env`, extracts the Claude OAuth token from the macOS Keychain, and mounts `~/.codex` for Codex subscription auth. See `docker/README.md` for the full wrapper script and installation steps.
- **Drive the loop with `/harness run <ISSUE-ID>`.** The orchestrating Claude session calls each verb in turn (`start → implement → review → (fix → review)* → close`); the verbs own every git and ticket mutation. The contract and gate-refusal handling are in `commands/harness.md`. The agent never runs *inside* a verb container — each verb is a one-shot `docker run` spawned by the wrapper.
- **`bin/harness` is dev-time only.** It hard-codes `.venv/bin/python` relative to the harness repo root and only works inside the harness checkout. Use it when iterating on harness source itself; use `~/bin/harness` for everything else.
- **Cross-repo execution** — `cd` to the target repo and run the verbs there. No `--repo` flag needed with the Docker wrapper; CWD is mounted automatically. (`--repo` and `--base` are accepted when invoking the verbs directly outside the wrapper.)
- **Native install path** (alternative to Docker): `uv tool install .` from the repo root installs the `harness` console script on PATH. Use when Docker is not available. Credentials and env vars must be set manually.
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
