<!-- guidance:template-context@0.1.4 -->
# CONTEXT.md

Agent-facing context for **harness**. This is the one file allowed to name this repo. The guidance files (skills, agents, commands) are universal and point here for everything repo-specific: stack, commands, paths, tools, and principles.

`README.md` is for humans. This is for agents. Read it first.

```yaml
profile: harness
visibility: committed
repo:
  name: harness
  linear: CAL   # legacy Linear team prefix — read only when tracker: linear (this repo is now on github, below); kept for reference/rollback
  project: Harness   # the Build queue the /harness routine loops pull from (resolved at runtime): the "Harness" Projects v2 board title for github; was the "Harness v3" Linear project pre-CAL-1204
tracker: github   # single source of truth: linear | github | none. The switch the engine reads (harness/layers.py); none → verbs run tracker-less. This repo dogfoods the GitHub backend (CAL-1204).
github:   # the GitHub tracker backend config, read only when tracker: github (CAL-1105)
  repo: sluengen/harness        # the issues repo
  project: sluengen/2           # the "Harness" Projects v2 board (owner/number)
  # status_field omitted → defaults to the built-in "Status" field (Todo / In Progress /
  # In Review / Done), so transitions show on the board's default view (issue #172).
layers:
  design_system: false
  feature_specs: true   # on → as-built record lives in specs/features/ (templates/feature.md); the harness dogfoods the surface it publishes
stack:
  language: Python 3.11+
  framework: Pydantic 2 / Typer / aiosqlite
commands:
  install: "uv sync --extra dev"
  lint:    "uv run --extra dev ruff check ."
  typecheck: "uv run --extra dev mypy harness"
  test:    "uv run --extra dev pytest"
  test_one: "uv run --extra dev pytest <path/to/test_file.py::test_name>"
  verify:  "bash scripts/verify.sh"   # canonical gate: ruff → mypy → pytest → CLI smoke → landing-page drift guard. Run before merge/tag.
  run:     "harness start <ISSUE-ID> → review → close"   # verb loop; drive via /harness run. ~/bin/harness Docker wrapper — see docker/README.md
branches:
  integration: dev      # feature branches base from here and merge back here
  staging: staging      # first-class nightly stabilized release candidate; DERIVED — promotion gates a dev→staging candidate and, on green, advances staging directly (no PR; ADR 0003 as amended CAL-1158)
  release: main         # DECIDED — promotion only ever opens a PR staging → main; never a direct push (topology: dev → staging → main; ADR 0003)
loop:                   # ledger-backed spend breakers for the autonomous loop (CAL-906; read by harness/loop_budget.py)
  max_review_cycles: 6           # hard ceiling — the run stops + escalates on REACHING the 6th review→fix cycle (cycles 1–3 unconditional; 4–5 assess convergence). One coherent stop rule with agents/reviewer.md.
  wall_clock_budget_minutes: 90  # per-run wall-clock budget; deliberately mirrors the stale-run reclamation staleness threshold — if one moves, move both.
  engine_timeout_seconds: 600    # per-subprocess ceiling for the review engine (claude -p / codex exec); a hung engine is killed and surfaced as an infra failure (exit 3, reason=engine_timeout) instead of hanging the verb. Sit it at or below the ops kill so the clean exit wins (CAL-1004).
conventions:
  commit_format: "type(scope): description — feat / fix / chore / docs / refactor / test / spec"
tools:
  linear_cli: "GraphQL via curl (shell) or urllib.request (Python) — no linear binary, no npx linear"
paths:
  source: harness/
  tests: tests/
  proposals: specs/proposals/
  features: specs/features/   # as-built feature specs (feature_specs layer on): verb-model, run-ledger, worktree-lifecycle, cli-surface
  decisions: specs/decisions/   # ADRs (0001+); design docs still in specs/
architecture_watchlist:   # gravity wells — a change touching one carries a `Watchlist trigger` section (architecture skill)
  files:
    - harness/cli/review.py   # verb orchestration + usage-limit fallback + breaker/gate/tracker glue; the engine-protocol layer (prompt, SUBMIT parser, per-engine builder, failure detectors) split out to review_protocol.py in CAL-1107 (CAL-1014)
    - harness/cli/close.py   # the close gate (_evaluate_gate, _has_gate_evidence) + ledger finalization (_mark_run_closed); the git integrate/merge/push concern split out to close_merge.py in CAL-1154 (throwaway-worktree merge), retiring the # size: justification (now under 500); tied for the most churn in the package (CAL-1139)
env:
  file: .env
  linear_token: LINEAR_API_KEY
```

## What this repo is

A set of **deterministic, audited verbs an agent calls** to drive a Linear ticket end-to-end — not an engine that drives agents. A single Claude session orchestrates *and* implements (reads the ticket, writes the code and tests, decides how to fix a review finding, when to re-review); the harness owns only the **durable record and the gate**. It has no product UI and no end-users — it is infrastructure other repos self-host. (The earlier deterministic YAML workflow engine was retired in CAL-574; `README.md` and `SPEC.md` §1–2 describe the current verb model.)

## Architecture

The main package is `harness/` (Python): a `Typer` CLI exposes the verbs, backed by a SQLite ledger, git-worktree lifecycle, and review-engine dispatch (Claude by default; `--engine codex` host-only).

Three verbs, one ledger, one gate:
- **`start`** — validate the ticket, transition it to *In Progress*, create an isolated git worktree off the base branch (default `dev`), and open a `runs` ledger row.
- **`review`** — run the review engine (**Claude by default**; `--engine codex` is a host-only option, ADR 0002) against the worktree HEAD and record a verdict (`pass` / `fail` / `defer`) **bound to that git SHA**; the session sees only the bounded verdict, not the engine's full reasoning.
- **`close`** — enforce the gate (a `start` exists **and** a `verdict=pass` whose reviewed SHA equals the current HEAD), then commit / merge / push, transition the ticket to *Done*, and finalize the run.
- **Read / ops commands** — `status` / `logs` / `events` / `runs` / `worktrees` / `doctor` / `version` inspect a run without mutating state.
- **State store** — SQLite via `aiosqlite`; the `runs` / `events` ledger is the whole audit trail.

The ledger is a complete audit trail **only if nothing hand-rolls a `git merge` / `push` or a Linear mutation** for the run lifecycle — every git and ticket state transition goes through a verb, and `close` validates against the ledger as a backstop (D5). Design specs live in `specs/`; `SPEC.md` is the index. Read the relevant spec before changing a verb, the ledger schema, or the close gate.

## Repo-specific principles

- **TDD is mandatory** — no production code without a failing test first. No exceptions.
- **Atomic commits** — each commit leaves the project working and passes the verification gate.
- **Spec before code** — read the relevant `specs/` section before changing behaviour; update the spec when what ships diverges from what is written.
- **Scope discipline** — do not rewrite nearby code "while you're there". Every changed file must trace to the task.
- **`uv.lock` is committed** — required for reproducible `uv sync --frozen` in Docker builds. Never gitignore it.

## Decisions index

Architecture decisions live in `specs/decisions/` (ADRs, `0001`+); older design decisions remain in `specs/` and inline in `SPEC.md`.

- **[0001 — The harness's own loop runs always-on local by default; cloud is optional and per-target-repo](specs/decisions/0001-cloud-runnable-harness-loop.md)** (CAL-908, corrected by CAL-930). The Build/Quality loop runs **always-on local** by default — the `harness-work-pull` trigger driving `/harness routine build`, at zero marginal cost. A cloud substrate is optional and deferred: if ever needed it is a **Claude cloud routine** (billed as Claude usage), **not** GitHub Actions (rejected — a private repo meters Actions minutes and the loop is a long agent run, not a cheap CI gate). Off-machine viability is set by the *target repo's* gate, so a self-hosting Xcode/macOS target stays local or on a macOS runner.
- **[0002 — The in-container review engine is Claude; `--engine codex` is a host-only option](specs/decisions/0002-in-container-review-engine.md)** (CAL-925). Codex's `bwrap` sandbox cannot open a user namespace in the unprivileged `harness:dev` container (CAL-866), so `--engine codex` degrades in-container. Rather than loosen container privileges — it reviews untrusted diffs — the in-container engine is **Claude**, and `--engine codex` is a **host-only** cross-model option. No image privilege change.
- **[0003 — Promotion is an audited harness lifecycle over a universal `dev → staging → main` topology](specs/decisions/0003-promotion-lifecycle.md)** (CAL-1112). `staging` becomes a first-class stabilized release candidate; promotion follows the verb model (an external orchestrator triggers, the harness owns every state transition). The harness pushes only the promotion branch and creates the PR — no direct target pushes, no auto-merge — with one bounded, escalation-first repair attempt. Policy/docs record only; the mechanics land in CAL-1113–1118.
- **[0005 — Per-ticket model tiering: two independent, label-carried dimensions](specs/decisions/0005-per-ticket-model-tiering.md)** (#177). `build:<tier>` / `review:<tier>` GitHub labels (default `sonnet`) replace indiscriminate top-tier spend on every automated tick. `review` is a deterministic seam — `harness review` resolves the `review` tier and appends `--model <alias>` to the claude engine command; `build` is a recorded judgement only, since the orchestrating session is the builder and has no deterministic per-ticket model seam.

## Where deeper truth lives

- **How the system is built** → `specs/` (design docs; `SPEC.md` is the index)
- **The verb contract the agent drives** → `commands/harness.md`
- **Operating the loops (re-syncing the local scheduled-task triggers)** → `RUNBOOK.md`
- **Loop substrate (always-on local default; optional Claude-routine cloud; per-target-repo rule)** → `specs/decisions/0001-cloud-runnable-harness-loop.md`
- **In-container review engine (Claude in-container; `--engine codex` host-only)** → `specs/decisions/0002-in-container-review-engine.md`
- **Promotion lifecycle + branch policy (`dev → staging → main`; harness-owned, agent-agnostic)** → `specs/decisions/0003-promotion-lifecycle.md`
- **User-facing feature surface** → `README.md`
- **Ideas not yet confirmed** → `specs/proposals/`
- **Linear (issues / in-flight work)** → linear.app (team: CAL, project "Harness v3")

## Gotchas

- **Primary invocation is `~/bin/harness` (Docker wrapper).** `cd` to any repo and call a verb — `harness start <ISSUE-ID>`, then `review` / `close`. The wrapper mounts CWD as `/workspace`, reads `LINEAR_API_KEY` from a local `.env`, extracts the Claude OAuth token from the macOS Keychain, and mounts `~/.codex` for Codex subscription auth. See `docker/README.md` for the full wrapper script and installation steps.
- **Drive the loop with `/harness run <ISSUE-ID>`.** The orchestrating Claude session calls each verb in turn (`start → implement → review → (fix → review)* → close`); the verbs own every git and ticket mutation. The contract and gate-refusal handling are in `commands/harness.md`. The agent never runs *inside* a verb container — each verb is a one-shot `docker run` spawned by the wrapper.
- **`bin/harness` is dev-time only.** It hard-codes `.venv/bin/python` relative to the harness repo root and only works inside the harness checkout. Use it when iterating on harness source itself; use `~/bin/harness` for everything else.
- **Cross-repo execution** — `cd` to the target repo and run the verbs there. No `--repo` flag needed with the Docker wrapper; CWD is mounted automatically. (`--repo` and `--base` are accepted when invoking the verbs directly outside the wrapper.)
- **Native install path** (alternative to Docker): `uv tool install .` from the repo root installs the `harness` console script on PATH. Use when Docker is not available. Credentials and env vars must be set manually.
- **No Linear CLI is installed.** All Linear interaction is via the GraphQL API (`curl` / `urllib.request`). Do not search for a `linear` binary or `npx linear`.
- **`mypy` scope is `harness`** — tests are excluded from the type check. Test-file mypy errors are a known backlog, not a gate failure.
- **Slow/integration tests have markers** — run `pytest -m 'not slow and not integration'` locally to skip them. CI runs all.
- **Verification output can come back empty** in the Claude Code Bash tool (it auto-backgrounds long commands). Redirect to `/tmp/<file>.txt` and `tail` it.

## Python conventions

The `dev` agent builds here in Python 3.11+ with mypy strict. Beyond the universal `code-quality`:

- **`@asynccontextmanager` for resource handles, not `async def`.** A helper that `return`s a resource from `async def` yields an awaitable you cannot `async with` over — and `aiosqlite` raises `RuntimeError: threads can only be started once` if you await-then-enter it. Wrap with `@asynccontextmanager` and `yield` the resource inside `try/finally`. `harness/state/store.py` is the reference; copy it for any managed resource (DB connection, HTTP session, subprocess).
- **Exception names mirror SPEC vocabulary, not the PEP 8 `Error` suffix.** The spec's "contract violation" → `ContractViolation`, "stalled agent" → `AgentStalled` (so type names grep against the spec). Suppress N818 with a scoped `# noqa: N818` per class.
- **Validate at boundaries (Pydantic), trust within.** Async by default for I/O. No `eval`/`exec`/`pickle` on untrusted data; no string-formatted SQL.
- **Security:** validate untrusted paths are inside the expected prefix; never `shell=True` with user input (list-form args); secrets from env only, never logged or committed.
