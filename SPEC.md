# Harness — Design Specification

**Version:** 0.7
**Status:** Current for §1–2 (the verb model), §4 (core module design), and §11 (CLI design). §3, §5–§10, and §12–§14 describe the **retired** deterministic workflow engine and are superseded — see the banner at §3.
**Guiding principle:** *The harness is a set of deterministic, audited verbs an agent calls — not a pipeline that drives agents.*

> **Execution model (2026-06).** The harness no longer orchestrates the build. Per proposal [`harness-as-tool`](specs/proposals/harness-as-tool.md) (accepted 2026-06-09; decision recorded in [`specs/architecture-principles.md`](specs/architecture-principles.md)), a single Claude session orchestrates **and** implements, calling three deterministic verbs — `start` / `review` / `close` — over the SQLite ledger, with process enforcement as a gate inside `close`. §1–2 describe this model; §4 (modules) and §11 (CLI) describe its as-built surface. The deterministic workflow engine (§3, §5–§10, §12–§14) was retired in CAL-574.

---

## Spec index

Subsystem and integration specs live in `specs/`. Read the relevant file before touching a module.

**Current — as-built record (verb model):**

The `feature_specs` layer is on (`CONTEXT.md`), so the canonical as-built record of each current subsystem is a feature spec in `specs/features/` (`templates/feature.md` shape). Read the relevant feature spec before touching its subsystem.

| Feature spec | Covers |
|------|--------|
| [`specs/features/verb-model.md`](specs/features/verb-model.md) | The `start` / `review` / `close` lifecycle and the close gate (the central feature) |
| [`specs/features/run-ledger.md`](specs/features/run-ledger.md) | The SQLite ledger: `runs` / `events`, the open/closed lifecycle, the reviewed-SHA gate datum |
| [`specs/features/worktree-lifecycle.md`](specs/features/worktree-lifecycle.md) | The isolated worktree per run: create off base, cleanup policies, path/branch conventions |
| [`specs/features/cli-surface.md`](specs/features/cli-surface.md) | The fixed command surface: verbs, read/inspection, ops, exit codes, JSON |

**Design references (the model and deeper module detail the feature specs build on):**

The pure deterministic-engine docs (`workflow-schema`, `engine-executor`, `engine-loop`, `ai-node`, `script-node`) were re-homed to [`specs/retired/`](specs/retired/) in CAL-661; CAL-693 completed the relocation — `state-store.md` was **folded into** [`run-ledger.md`](specs/features/run-ledger.md) (the feature spec now carries the full schema reference); `build-workflow.md` / `cli.md` / `worktree-isolation.md` were re-homed to `specs/retired/`; and `hermes-orchestration.md` was **split** — its live launcher/trigger/allowlist/observability half stays as the live reference below (still cited by live `harness/` modules), while its superseded control half was extracted to [`specs/retired/hermes-control-model.md`](specs/retired/hermes-control-model.md). All docstring cites were repointed.

| Spec | Covers |
|------|--------|
| [`specs/proposals/harness-as-tool.md`](specs/proposals/harness-as-tool.md) | The accepted model: invert the orchestration boundary; verbs + ledger + gate. **Read first.** |
| [`specs/architecture-principles.md`](specs/architecture-principles.md) | Architecture principles + the orchestration-inversion decision (cross-cutting decision record) |
| [`specs/hermes-orchestration.md`](specs/hermes-orchestration.md) | Live launcher / trigger runtime topology, the narrow control socket, the launch handle, the `--repo` allowlist, and the read-only ledger observability Hermes consumes (SPEC §4.9) |

The SQLite schema reference (full DDL, migrations, `BaseState`) now lives in [`run-ledger.md`](specs/features/run-ledger.md) § Schema reference; the worktree helper reference is the feature spec [`worktree-lifecycle.md`](specs/features/worktree-lifecycle.md) (the engine-era `WorktreeNode` detail is the retired doc below).

**Superseded (retired deterministic engine — historical):**

| Spec | Covers | Status |
|------|--------|--------|
| [`specs/retired/hermes-control-model.md`](specs/retired/hermes-control-model.md) | Engine-era Hermes control model: responsibility boundary, Option A/B/C deployment decision, the Hermes→harness bridge interface | Control half superseded by `harness-as-tool` (CAL-693); the live half is `hermes-orchestration.md` above |
| [`specs/retired/build-workflow.md`](specs/retired/build-workflow.md) | Build workflow end-to-end (implement → review loop → merge phase) | Replaced by the `/harness run` verb loop; re-homed to `specs/retired/` (CAL-693) |
| [`specs/retired/cli.md`](specs/retired/cli.md) | Command surface, dynamic subcommands, exit codes, JSON output | Verb surface is now the contract (`commands/harness.md`); re-homed to `specs/retired/` (CAL-693) |
| [`specs/retired/worktree-isolation.md`](specs/retired/worktree-isolation.md) | Engine-era `WorktreeNode` reference: create + the retired cleanup policies | Live behaviour is `worktree-lifecycle.md`; `cleanup` machinery retired (CAL-693) |
| [`specs/retired/workflow-schema.md`](specs/retired/workflow-schema.md) | YAML workflow format, step keys, contracts, inputs | Engine retired (CAL-574); re-homed to `specs/retired/` (CAL-661) |
| [`specs/retired/engine-executor.md`](specs/retired/engine-executor.md) | Per-node execution, contract validation, state writes, snapshots | Engine retired (CAL-574); re-homed to `specs/retired/` (CAL-661) |
| [`specs/retired/engine-loop.md`](specs/retired/engine-loop.md) | Loop blocks, `until:` / `until_bash:`, retry rewind | Engine retired (CAL-574); re-homed to `specs/retired/` (CAL-661) |
| [`specs/retired/ai-node.md`](specs/retired/ai-node.md) | AI node dispatch, structured output, failure modes | Engine retired (CAL-574); re-homed to `specs/retired/` (CAL-661) |
| [`specs/retired/script-node.md`](specs/retired/script-node.md) | Script node subprocess, env, contract | Engine retired (CAL-574); re-homed to `specs/retired/` (CAL-661) |

---

## 1. Mission

Give an agent a small set of **deterministic, audited verbs** to drive a ticket end-to-end, and **enforce that review happened** before anything merges. The agent owns *what work gets done and how* (orchestration + implementation); the harness owns *the durable record and the gate*.

Decouple judgement (the agent's: read the ticket, write the code, decide how to fix a finding, when to re-review) from the **audit trail and enforcement** (the harness's: a `runs` ledger, a review verdict bound to a git SHA, a `close` gate that refuses an unreviewed merge).

### Core principles

1. **The agent orchestrates; the harness records and gates.** There is **one execution model** — a Claude session runs `start → implement → review → (fix → review)* → close`, calling the verbs and doing the implementation itself — with **two triggers**: a human (`/harness run <ticket>`) or Hermes. The harness does not own the build loop and does not spawn its own implementing/reviewing agents.
2. **Determinism lives in the verbs, not the journey.** Each verb (`start`, `review`, `close`) is a one-shot, audited, reproducible operation over the ledger. The orchestration *between* verbs varies with the agent and is deliberately not reproducible — that trade buys full context retention (the agent that reads the ticket is the one that writes the code) and graceful degradation (a verb failure drops to manual driving).
3. **Enforcement is a gate inside `close`, bound to the reviewed tree.** `review` records the git SHA it reviewed; `close` refuses unless the ledger holds a `start` for the ticket **and** a `verdict=pass` whose reviewed SHA equals the worktree's current HEAD. This closes the stale-pass hole and makes unattended (Hermes-triggered) dispatch trustworthy — when no human is watching, the gate *is* the guarantee that nothing merges unreviewed.
4. **Routing discipline — every git/ticket mutation goes through a verb.** The ledger is a complete audit trail only if nothing hand-rolls a `git merge`/`push` or a Linear mutation for the run lifecycle. The `/harness run` skill forbids it; `close` validates against the ledger as a backstop.
5. **The verb surface is a public contract.** The harness is invoked by humans and by Hermes through the same verbs (`start` / `review` / `close` / `status` / `events` / `cancel`). Stable flags, stable exit codes, stable JSON output, structured refusals. Each verb runs as a one-shot container exactly as the human's `~/bin/harness` does.
6. **Reproducibility applies to the verbs, not the end-to-end run.** We deliberately give up same-inputs→same-journey reproducibility (the original §2 goal). Autonomy is not a separate deterministic engine — it is Hermes occupying the trigger slot a human would. The container still provides a consistent runtime for each verb.

---

## 2. High-Level Architecture

One execution model, two triggers. A trigger launches a per-session Claude runtime; that session orchestrates and implements, shelling out to one-shot verb containers; the verbs are the only thing that touches the ledger and git/ticket state.

```
┌─────────────────────────────────────────────────────────────────────┐
│  TRIGGER                                                            │
│   • a human  ( /harness run CAL-42 )                                │
│   • Hermes   ( Nous' persistent agent: built-in cron dispatcher )   │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ launch a session for a ticket
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Claude session — orchestrator + implementer  (per-session)         │
│   start → [implement] → review → (fix → review)* → close            │
│   context retained; the agent that reads the ticket writes the code │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ shells out to verbs (one-shot `docker run`)
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Harness — the tool:  start / review / close  +  ledger  +  gate    │
│   • each verb a one-shot container over the host-mounted worktree   │
│   • SQLite ledger (runs/events) at /workspace/.harness/             │
│   • close gate: refuse unless a HEAD-bound passing review exists    │
└─────────────────────────────────────────────────────────────────────┘
```

A human typing `/harness run CAL-42` and Hermes dispatching CAL-42 produce the **identical** execution path. The agent runtime is *per-session* (one Claude per ticket, where context lives); each verb is *per-call* — a one-shot container spawned **outside** the runtime, exactly as `~/bin/harness` is already a `docker run`. The agent must not run inside a verb container; that would make it per-call and reintroduce the lost-context problem.

### Verb lifecycle per run

1. A trigger launches a Claude session for `<ticket>` and issues `/harness run <ticket>`.
2. **`start <ticket>`** — validate the ticket, transition it to In Progress, create a worktree off the base branch (default `dev`), open a `runs` ledger row (`status=open`, ULID `run_id`). Emits `StartOutput` (run_id, ticket context, worktree path/branch).
3. **implement** — the session writes code + tests in the worktree, test-first, in scope. No verb is involved; the agent uses its own tools.
4. **`review --run-id <id>`** — run codex against the worktree HEAD; record a `review` event carrying `{ verdict, issues, reviewed_sha }` bound to that SHA. The session sees only the bounded verdict; codex's full reasoning stays inside the verb.
   - `fail` → fix the root cause, commit, re-run `review` (the `(fix → review)*` loop). Each review binds to the new HEAD.
   - `defer` → file a follow-up for the out-of-scope finding, then close.
   - `pass` → proceed to close.
5. **`close <ticket> --run-id <id>`** — enforce the gate (a `start` exists **and** a `verdict=pass` whose reviewed SHA == current HEAD), then commit/merge/push, transition the ticket to Done, flip the run to `status=closed`. A gate refusal is structured (`no_run` / `dirty_worktree` / `no_passing_review` / `stale_review`) and is the gate doing its job — never worked around.

The harness never decides what to build or how. The session does; the verbs record it and gate the merge.

---

---

> **§3 and §5–§10, §12–§14 below describe the retired deterministic workflow engine.** (Exceptions: **§4 *Core Module Design*** and **§11 *CLI Design*** have been rewritten to the as-built verb system — read them as current.) They are kept for historical reference and for the mechanics that were **re-homed as verb helpers** (worktree lifecycle, codex dispatch, the SQLite store, git/Linear helpers). The YAML-walking orchestration — `engine/runner|executor|loop|retry`, the node protocol, the workflow schema, contract/derive machinery, and `build*.yaml` — was deleted in CAL-574 (proposal [`harness-as-tool`](specs/proposals/harness-as-tool.md), decision D1). Treat any "the engine walks the workflow / the YAML decides the route" statement below as superseded by §1–2. The current schema reference is [`specs/features/run-ledger.md`](specs/features/run-ledger.md) § Schema reference; the current command contract is [`commands/harness.md`](commands/harness.md).

---

## 3. Repository Structure

```
harness/
├── pyproject.toml
├── README.md
├── CLAUDE.md
├── SPEC.md                    ← this file
├── .gitignore
├── .claude/
│   └── settings.json
├── docker/
│   ├── Dockerfile
│   └── entrypoint.sh
├── harness/                   ← Python package
│   ├── __init__.py
│   ├── cli.py                 ← Typer entrypoint
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── runner.py          ← top-level: load workflow, walk steps, emit events
│   │   ├── executor.py        ← per-node execution + contract validation
│   │   ├── loop.py            ← `until:` block evaluator
│   │   └── retry.py           ← three-layer retry policies
│   ├── nodes/
│   │   ├── __init__.py
│   │   ├── base.py            ← Node protocol, NodeResult, Attestation, Artifacts
│   │   ├── ai.py              ← AI node (Claude / Ollama / Pi via dispatch)
│   │   ├── script.py          ← shell / python script via subprocess
│   │   ├── check.py           ← deterministic state evaluator
│   │   ├── decision.py        ← LLM or human approval gate (human flavor: v2)
│   │   └── worktree.py        ← create / merge / cleanup worktree
│   ├── decisions/             ← human-decision resume machinery (v2)
│   │   ├── __init__.py
│   │   ├── pause.py           ← persist paused state, emit prompt
│   │   └── resume.py          ← rehydrate state, jump to next node
│   ├── dispatch/
│   │   ├── __init__.py
│   │   ├── base.py            ← Agent protocol — wraps an agent harness (v1)
│   │   ├── claude_agent.py    ← claude_agent_sdk in-process (v1)
│   │   ├── codex.py           ← OpenAI codex CLI subprocess (v1.5)
│   │   └── opencode.py        ← opencode CLI subprocess (v1.5) — local + multi-vendor
│   ├── state/
│   │   ├── __init__.py
│   │   ├── schema.py          ← BaseState, run_id, worktree fields, helpers
│   │   └── store.py           ← SQLite read/write of state row
│   ├── events/
│   │   ├── __init__.py
│   │   ├── emitter.py         ← append-only event log writer
│   │   └── schema.py          ← event Pydantic models
│   ├── workflow/
│   │   ├── __init__.py
│   │   ├── loader.py          ← parse YAML, resolve $contracts refs, compile to Pydantic
│   │   ├── schema.py          ← Workflow / Step Pydantic models (engine-side)
│   │   ├── derive.py          ← derive workflow state schema from collected writes/contracts
│   │   └── prompt.py          ← Jinja2 prompt rendering
│   └── identity.py            ← run_id generation, propagation
├── workflows/                 ← YAML workflow definitions (yours go here)
│   ├── release-notes.yaml     ← shipped: pull Linear, summarise, write file
│   └── steward.yaml           ← shipped: domain steward review
├── contracts/                 ← shared YAML contract schemas (referenced via $contracts/<name>)
├── prompts/
│   └── standard/              ← shared library: analyze.j2, implement.j2, review.j2, summarize.j2
│                              ← workflow-specific prompts go in prompts/<workflow-name>/
└── tests/
    ├── unit/                  ← per-module unit tests
    └── integration/           ← end-to-end with mocked AI dispatch
```

Placeholder dirs (`prompts/{feature,bugfix,review,steward}/`, `examples/`, `tests/fixtures/synthetic_repo/`) were removed once shipping reality drifted from the spec. The diagram shows what exists today; create subdirectories under `workflows/`, `contracts/`, or `prompts/<workflow-name>/` as new workflows demand them.

**Conventions:**
- One Python module = one responsibility.
- No cyclic imports between top-level packages.
- Workflows are pure YAML. Adding a workflow does not require adding a Python file.

---

## 4. Core Module Design

The harness is a small set of modules behind the verb CLI: the verbs, the
worktree lifecycle, the SQLite ledger, the event log, and the Linear and
identity helpers. The deterministic-engine internals this section once
described — the YAML runner and executor, the node protocol, the agent-dispatch
layer, and the workflow loader — were deleted in CAL-574 (see §3's banner and
`tests/unit/test_engine_retired.py`).

### 4.1 `harness.cli` — the verb surface

The Typer app (`harness/cli/__init__.py`) is the public contract. It registers
the three audited verbs (`start` / `review` / `close`) plus the read/inspection
and ops commands (`status` / `logs` / `events` / `runs` / `worktrees` /
`cancel` / `doctor` / `serve` / `version`). Subcommands are split per concern
across `harness/cli/*.py` for readability. Stable flags, stable exit codes,
stable JSON output — see §11.

### 4.2 `harness.cli.start`

Opens a run. Validates the ticket (fetch from Linear, canonicalise the
identifier, refuse a duplicate open run), generates a ULID `run_id` and creates
an isolated git worktree off the base branch (via `harness.worktree`, default
`dev`), inserts the `open` `runs` ledger row, and **transitions the ticket to
*In Progress* last** — it is the only non-local side effect, so if the worktree
or the ledger insert fails nothing has touched Linear (rollback ordering locked
by `test_cli_start.py::test_worktree_failure_leaves_no_db_row_and_no_transition`
and `::test_db_failure_removes_worktree_and_no_transition`). Emits a
`StartOutput` JSON object (`run_id`, ticket, worktree path/branch); the open run
is recorded as the `runs` row, not as an event.

### 4.3 `harness.cli.review`

Reviews the worktree's current HEAD with the configured reviewer (codex).
Captures `git rev-parse HEAD` as `reviewed_sha`, runs codex against the
worktree, scans stdout for the single `SUBMIT: <json>` line, and appends a
`review` event whose verdict (`pass` / `fail` / `defer`) is **bound to that
SHA** — the load-bearing detail behind decision D2 (the close gate refuses a
pass whose SHA ≠ HEAD). Prints only the bounded verdict; the reviewer's full
reasoning stays inside the verb.

### 4.4 `harness.cli.close`

Enforces the gate, then merges the **already-committed** HEAD to the base
branch, pushes, transitions the ticket to *Done*, and finalizes the run. It does
**not** auto-commit: a dirty worktree is refused outright, because uncommitted
edits are not in HEAD and so were never reviewed (`stale_review` catches a
commit *after* review; only the clean-tree check catches an edit *without*
committing — CAL-586). The gate refuses unless a `start` row exists, the
worktree is clean, and a `verdict=pass` reviewed-SHA equals HEAD; a refusal
exits 2 with exactly one structured `reason` — `no_run` / `dirty_worktree` /
`no_passing_review` / `stale_review` (locked by
`test_cli_close.py::test_dirty_worktree_refused_when_uncommitted_edits` and
the gate tests). The verb never works around its own gate.

### 4.5 `harness.worktree`

Git worktree creation off a base branch. Re-homed from the retired engine as a
verb helper; only `create` survives — the engine-era `cleanup` `CleanupPolicy`
machinery was retired in CAL-693 (no live caller — `start` rollback / `close`
merge / `worktrees cleanup` use direct git). See
[`specs/features/worktree-lifecycle.md`](specs/features/worktree-lifecycle.md)
(the engine-era `WorktreeNode` detail is [`specs/retired/worktree-isolation.md`](specs/retired/worktree-isolation.md)).

### 4.6 `harness.state.store`

The SQLite ledger via `aiosqlite`. The `runs` / `events` tables are the whole
audit trail; the connection is a managed resource (`@asynccontextmanager`, see
CONTEXT.md). All run-lifecycle state goes through the store so the ledger
reflects reality and the close gate can validate against it (D5). The schema and
the open/closed run lifecycle live in
[`specs/features/run-ledger.md`](specs/features/run-ledger.md) § Schema reference
(the current schema reference).

### 4.7 `harness.events.emitter`

Append-only event-log writer over the `events` table. `review` appends a
`review` event (carrying `reviewed_sha` + verdict) and `close` appends a `close`
event; `start` emits **no** event — the open run is recorded as the `runs` row
itself. So the audit trail is the `runs` row **plus** its events, not the events
alone. Event types live in `harness.events.schema`.

### 4.8 `harness.linear`, `harness.identity`

`harness.linear` is the Linear GraphQL client `start` and `close` use to fetch a
ticket and transition its state. `harness.identity` generates the run ID (a
ULID) and propagates it across the verbs.

### 4.9 `harness.launcher`, `harness.workspace`, `harness.trigger`

`harness serve` runs a narrow host control socket (`harness.launcher` /
`harness.launcher_client`) that spawns verb containers on request.
`harness.workspace` enforces the `--repo` allowlist (`HARNESS_WORKSPACE_ROOTS`,
CAL-584), failing closed when unset so a verb cannot operate outside the mounted
workspace.

`harness.trigger` is the local stand-in for the launch handle (CAL-585): the
*trigger slot* occupant — a human (`/harness run`) or Hermes on the autonomous
path. Its job is deliberately tiny: **launch** the per-session agent runtime
headless (`claude -p "/harness run <ticket>"`, `agent_run_command`), then **read
the outcome solely from the ledger** (`harness status` / `harness events`,
read-only). The trigger never implements, manages worktrees, runs codex, does
gitops, or writes the harness DB; the writing verbs (`start` / `review` /
`close`) are issued by the agent runtime, not the trigger. The launch and ledger
readers are injected (`HermesTrigger`) so a test can substitute an in-process
runtime and demonstrate the handle end-to-end. See
[`specs/hermes-orchestration.md`](specs/hermes-orchestration.md).
---

## 5. YAML Workflow Schema

A workflow is **pure YAML**. No Python state classes, no Python contract classes, no per-workflow Python files. Every node declares its contract inline (or references a shared YAML schema). State is derived from those declarations.

### Full example: bugfix

```yaml
name: bugfix                              # required, snake-case
version: 1                                # schema version, integer
description: Fix a Linear-tracked bug, verify with tests, merge to base

# Inputs the caller provides via CLI — generates flags / positional args dynamically
inputs:
  linear_id:
    type: string
    pattern: "^[A-Z]+-[0-9]+$"
    flag: --linear
    required: true
  base_branch:
    type: string
    default: staging

steps:
  - id: setup-worktree
    type: worktree
    action: create
    base: $inputs.base_branch
    writes: [worktree_path, worktree_branch]

  - id: fetch-issue
    type: script
    command: |
      curl -s -X POST https://api.linear.app/graphql \
        -H "Authorization: $LINEAR_API_KEY" \
        -H "Content-Type: application/json" \
        -d '{"query":"query{issue(id:\"$1\"){id identifier title description state{name} labels{nodes{name}} url}}"}'
    args: ["$inputs.linear_id"]
    contract: $contracts/linear-issue              # shared YAML schema
    writes: [issue]

  - id: investigate
    type: ai
    agent: claude
    model: sonnet
    prompt: prompts/bugfix/investigate.j2
    allowed_tools: [Read, Grep, Glob, Bash]
    contract:                                       # inline
      root_cause: string
      plan:
        type: list
        of: string
    cwd: $state.worktree_path
    writes: [root_cause, plan]

  - id: implement-and-test
    type: loop
    loop:
      max_iterations: 5
      until: state.tests_pass
      steps:
        - id: implement
          type: ai
          agent: claude
          prompt: prompts/standard/implement.j2
          template_vars:
            task: "Apply the fix at $state.root_cause following the plan in $state.plan"
          allowed_tools: [Read, Write, Edit, Bash, Grep, Glob]
          cwd: $state.worktree_path
          writes_files: true
          writes: []                                # produces files, not state — no contract needed

        - id: run-tests
          type: script
          command: pytest -x
          cwd: $state.worktree_path
          contract:
            tests_pass: boolean
            failing_tests:
              type: list
              of: string
          writes: [tests_pass, failing_tests]

  - id: review
    type: ai
    agent: claude
    model: sonnet
    prompt: prompts/standard/review.j2
    template_vars:
      criteria: "Correctness, test coverage, regression risk"
    allowed_tools: [Read, Grep, Glob, Bash]
    contract: $contracts/review-verdict             # shared YAML schema
    cwd: $state.worktree_path
    writes: [status, issues]

  - id: gate-on-review
    type: check
    expr: state.status == "PASS"
    on_fail: cancel

  - id: teardown-worktree
    type: worktree
    action: cleanup
    policy: merge_to_base
```

### Step keys

| Key                  | Required         | Meaning                                                               |
| -------------------- | ---------------- | --------------------------------------------------------------------- |
| `id`                 | yes              | unique within workflow                                                |
| `type`               | yes              | `ai` \| `script` \| `check` \| `decision` \| `worktree` \| `loop`     |
| `depends_on`         | no               | explicit dependency override (default: previous step)                 |
| `actor`              | decision         | `llm` (v1) \| `human` (v2)                                            |
| `via`                | decision.human   | `cli` (v1 once shipped) \| `webhook` (future)                         |
| `message`            | decision.human   | string shown to the human; supports `$state.X` substitution           |
| `display_state`      | decision.human   | list of state field names to render alongside `message`               |
| `timeout`            | decision.human   | duration (e.g., `24h`); omit for no timeout                           |
| `on_reject`          | decision         | `cancel` \| `continue` \| `retry_loop:<id>` \| `pause_for_human`      |
| `on_timeout`         | decision.human   | `cancel` \| `continue` \| `reject_and_continue`                       |
| `agent`              | ai               | `claude` \| `ollama:<model>` \| `pi:<provider>/<model>`               |
| `model`              | ai               | model override (e.g., `haiku`, `sonnet`, `qwen2.5-coder:7b`)          |
| `prompt`             | ai               | path to Jinja2 template                                               |
| `template_vars`      | ai               | mapping of vars passed to the Jinja prompt template                   |
| `allowed_tools`      | ai               | list of tools the LLM may call (default: read-only `Read,Grep,Glob`)  |
| `contract`           | yes (any output node) | inline schema OR `$contracts/<name>` reference; compiled to Pydantic at load time |
| `command` / `script` | script           | shell command or script path                                          |
| `runtime`            | script           | `bash` \| `python`                                                    |
| `args`               | script           | list of args, supports `$inputs.X` and `$state.Y`                     |
| `cwd`                | ai, script       | working directory (usually `$state.worktree_path`)                    |
| `writes`             | yes              | state fields this step is allowed to mutate                           |
| `writes_files`       | no               | bool, true if the step mutates the filesystem                         |
| `stall_timeout_s`    | ai               | kill node if no SDK event (tool_called/completed) for N seconds; default: `300` (5 min). Distinct from hard `timeout_s` wall. |
| `persist_session`    | ai               | bool, resume the agent's conversation across re-executions (keyed by `step.id`) instead of running fresh; default `false`. Honoured by adapters that support session resume (ClaudeAgent); cleared by a `fresh_context: true` loop. |
| `expr`               | check            | Python boolean expression over `state`                                |
| `on_fail`            | check            | `cancel` \| `retry_loop:<id>` \| `continue`                           |
| `loop`               | loop             | nested block with `max_iterations`, `steps`, and one of `until` / `until_bash` (see §10) |
| `action`             | worktree         | `create` \| `cleanup`                                                 |
| `policy`             | worktree.cleanup | `merge_to_base` \| `leave_for_inspection` \| `delete_unconditionally` |

### Contracts

**Every node that writes state has a contract.** If a node produces no state output (`writes: []`) and its job is purely to mutate the worktree or fire a side effect, the `contract:` field is optional. The discipline holds where it matters — anything downstream nodes can reference is typed — and the friction disappears where it doesn't.

Concrete example: a code-implementation node inside a loop produces files, not state. Its output is "did the work get done" which is captured by the test-node that follows. No contract needed.

```yaml
- id: implement
  type: ai
  prompt: prompts/standard/implement.j2
  allowed_tools: [Read, Write, Edit, Bash]
  writes_files: true
  writes: []                # nothing flows to state — contract optional
```

Otherwise: contracts are declared, no defaults.

Contracts come in two forms:

**Inline** — declared right in the YAML, compiled to a Pydantic model at load time via `pydantic.create_model()`:

```yaml
contract:
  summary: string
  items:
    type: list
    of: string
  count: integer
  status:
    type: string
    enum: [PASS, FAIL]
  priority:
    type: integer
    min: 1
    max: 5
```

Supported types: `string`, `integer`, `boolean`, `number`, `list` (with `of: <type>`), nested objects (a mapping is treated as a sub-schema). Constraints: `enum`, `pattern` (regex), `min`/`max`, `format` (e.g., `datetime`).

**Shared (`$contracts/<name>`)** — for contracts reused across workflows, hoist them to a YAML file in `contracts/` and reference by name:

```yaml
# contracts/review-verdict.yaml
status:
  type: string
  enum: [PASS, FAIL]
issues:
  type: list
  of:
    severity: string
    description: string
blocking: boolean
```

```yaml
# any workflow
contract: $contracts/review-verdict
```

The harness resolves the reference at load time and compiles to the same Pydantic model. Adding a shared schema means writing YAML, not Python.

**Why every node?** Implicit shapes are the foot-gun. If a downstream node can reference `$state.<field>`, that field's existence is a load-time guarantee, not a runtime hope.

#### Contract compiles to two artefacts

At workflow load time, every contract compiles to:

1. **A Pydantic model.** Validates the final payload after the agent returns. Backstop guarantee.
2. **A tool schema** in the agent harness's native dialect (`submit_<node_id>(...)`). Injected into the agent's available tools at run time. The agent calls this tool with the typed payload to deliver its output. See §4.4 for the structured-output mechanism.

Both artefacts come from the same source — the YAML `contract:` block — so they can never drift. Authors write one schema and get both behaviours: native tool-call structured output for the agent, Pydantic validation for the engine.

### Decision nodes (LLM gates and human approvals)

The `check` node handles deterministic gating (boolean expressions over state). The `decision` node handles the *non*-deterministic kind: an LLM judging whether to proceed, or a human approving an artifact. Two actor flavors share one node type.

**`actor: llm`** (v1) — a bounded AI call whose contract must declare a `decision: bool` field. The engine routes on that field via `on_reject:`. Distinguished from a plain AI node only by the routing semantics and a dedicated `decision_made` event for audit.

```yaml
- id: should-proceed
  type: decision
  actor: llm
  agent: claude
  model: haiku
  prompt: prompts/standard/can_proceed.j2
  template_vars:
    question: "Is there enough information in $state.issue to plan a fix?"
  allowed_tools: [Read]
  contract:                         # MUST include `decision: bool`
    decision: boolean
    reasoning: string
    missing:                        # optional — what's lacking when decision=false
      type: list
      of: string
  on_reject: cancel                 # cancel | continue | retry_loop:<id> | pause_for_human
  writes: [data]
```

When `decision` is `true`, execution continues to the next step. When `false`, the engine applies `on_reject:`. `pause_for_human` is the bridge between LLM and human flavors: an LLM's "no" can escalate to a human gate without two separate nodes.

**`actor: human`** (v2 — schema reserved in v1) — the workflow pauses, awaits an external CLI invocation, then resumes. Schema is parsed and validated in v1; running a workflow that uses `actor: human` errors at load time with `actor: human is reserved for v2` until the resume machinery ships.

```yaml
- id: confirm-bug-report
  type: decision
  actor: human
  via: cli
  message: "Is this bug report accurate? See $state.report_path"
  display_state: [issue, root_cause, plan]
  timeout: 24h
  contract:
    decision: boolean
    comment: string                 # captured into the event log
  on_reject: cancel
  on_timeout: cancel                # cancel | continue | reject_and_continue
```

Mechanics (v2):

1. Engine reaches the node, emits `decision_requested`, writes status `paused` to the runs row, persists state.
2. Prints the rendered `message`, the run-id, and resume instructions to stdout.
3. Exits with code **4** (paused).
4. The decider (human or orchestrator) reviews and runs:
   ```bash
   harness decisions list                                # all paused runs
   harness decision show <run-id>                        # the question + display_state
   harness decision approve <run-id> [--comment="..."]
   harness decision reject  <run-id> [--comment="..."]
   ```
5. The approve/reject command rehydrates state, emits `decision_received`, resumes from the next step (or applies `on_reject:`).

**Why decision is its own node type, not just AI + check:**

- The audit trail (`decision_made`, `decision_requested`, `decision_received`) makes "where did this workflow ask for permission?" a one-grep query.
- Routing semantics (`on_reject:`, `on_timeout:`) live where they belong, not split across two nodes.
- `pause_for_human` escalation needs a single node identity to hand off cleanly.

### Inputs and CLI generation

The `inputs:` block declares the CLI surface for this workflow's `harness run` subcommand. The CLI introspects the workflow YAML at invocation and dynamically generates flags / positional args.

Per-input fields:

| Field      | Meaning                                                              |
|------------|----------------------------------------------------------------------|
| `type`     | `string` \| `integer` \| `boolean`                                   |
| `required` | boolean (default `false` if `default:` is set, else `true`)          |
| `default`  | fallback value if the caller omits the input                         |
| `pattern`  | regex the input must match (string types)                            |
| `enum`     | list of allowed values                                               |
| `flag`     | explicit CLI flag (default: `--<input_name>`, underscores → dashes)  |
| `position` | integer; if set, accepts as positional arg instead of flag           |

`harness run <workflow> --help` introspects the YAML and prints the input contract. Adding a new workflow means writing YAML, not editing CLI code.

Example workflow inputs supporting both flag and positional forms:

```yaml
inputs:
  linear_id:
    type: string
    pattern: "^[A-Z]+-[0-9]+$"
    flag: --linear
    required: false        # because we have a positional fallback below
  free_text:
    type: string
    position: 1
    required: false
```

Yields:

```bash
harness run feature --linear=PROJ-249                          # flag form
harness run feature "Build a dropdown menu"                   # positional form
harness run feature --linear=PROJ-249 "with these specifics…"  # both
```

### Variable substitution

Two namespaces, both prefixed `$`:
- `$inputs.X` — values the caller passed via CLI.
- `$state.X` — the live state object; always reflects the latest committed state.

Templating engine: Jinja2 inside prompt templates (full templating power); simple `$` substitution inside YAML scalar values (literal token replace, no expressions).

---

## 6. State Schema (derived)

**State is not declared. State is derived.** The harness builds the per-workflow state schema at load time by walking every node's `contract:` and `writes:`, taking the union of declared fields. No Python state classes exist.

### Base state (always present)

Framework-defined fields, prepended to every derived schema:

```python
class BaseState(BaseModel):
    run_id: str
    workflow_name: str
    base_branch: str
    worktree_path: Path | None = None
    worktree_branch: str | None = None
    artifacts_dir: Path
    started_at: datetime
```

### Derivation rule

For each step in the workflow:
- Compile the node's `contract:` to a Pydantic model.
- For each name in `writes:`, the field must exist on that contract. The contract field's type becomes the state field's type.
- If multiple steps write the same field name, their contract field types must be identical (load-time check) — divergence is a workflow error.

The result is a `Pydantic` model class that subclasses `BaseState` and carries every state field the workflow uses.

### Worked example

```yaml
- id: investigate
  contract:
    root_cause: string
    plan:
      type: list
      of: string
  writes: [root_cause, plan]

- id: run-tests
  contract:
    tests_pass: boolean
    failing_tests:
      type: list
      of: string
  writes: [tests_pass, failing_tests]
```

Derived state:

```python
class BugfixState(BaseState):
    root_cause: str | None = None
    plan: list[str] = []
    tests_pass: bool | None = None
    failing_tests: list[str] = []
```

Defaults are `None` for scalars, `[]` for lists, `{}` for dicts, applied automatically.

### Engine enforcement

- Every name in `writes:` must match a field name in that step's `contract:`. Otherwise: load-time error.
- Type consistency across multiple writers of the same field. Otherwise: load-time error.
- No `state_schema:` field on the workflow. Trying to declare one is a load-time error pointing the author at the derived model.

---

## 7. State Merge Semantics

When multiple steps write the same state field, the merge is **type-driven**, not configured per-write. This eliminates the need for a separate "notes channel" — accumulation falls out of the rules.

| Field type | Merge behaviour | Example |
|------------|-----------------|---------|
| `list`     | Append          | `notes: list[str]` — every writer appends; the field accumulates across nodes |
| Scalar (`string`, `integer`, `boolean`, `number`) | Overwrite | `tests_pass: bool` — last writer wins, which is what you want for status fields |

### Why this works

- **Accumulation is a list type.** Lists naturally append; perfect for the auto-populated notes channel.
- **Status fields are scalars.** `tests_pass`, `review_status`, `worktree_branch` overwrite naturally as the workflow progresses.

### Notes — framework-provided, auto-populated

The `notes: list[str]` field on `BaseState` is special only in *how it's populated*: the AI node captures the agent harness's text-delta stream (everything the model says between tool calls) and routes each chunk into `state.notes` as an append. No `note(text)` tool, no contract opt-in, no workflow ceremony.

Workflows that want *typed* notes (e.g., `warnings: list[string]` populated by a specific contract field) still work and stay unaffected — those are explicit contract fields. The framework `notes` channel is for the agent's free-form thinking, captured for debugging.

### Bounding strategy

Notes auto-capture can grow fast — a long-running AI node can emit thousands of words of "thinking aloud." Two caps applied in order on every write:

- **Per-list entry count** — max 100 entries; oldest dropped first.
- **Total character budget** — max 50 KB across the whole list; if a write would exceed, oldest entries dropped until under budget.

Both caps are non-configurable in v1. The character budget is the load-bearing one — entry count alone doesn't bound the worst case. Revisit if a real workflow hits either cap.

### Engine enforcement

- Type-driven merge is applied automatically at write time inside `StateStore.update`.
- Caps applied automatically per the bounding strategy above.

### Deferred to v1.5

- **Dict-merge semantics.** Multiple writers contributing keys to a shared `dict` field. Cut from v1 because no shipped workflow needs it; the same outcome is achievable with separate scalar fields. Add back when a real workflow forces the case.
- **Per-write merge override** (e.g., `merge: replace` on a list to force overwrite). Same reason — no concrete v1 workflow needs the override. Type-driven defaults are the only behaviour available.

---

## 8. Run ID and Identity

A single ULID (or short UUID) is generated at workflow start and propagated everywhere:

| Surface | Format |
|---------|--------|
| Worktree dir | `.worktrees/harness/<run-id>/` |
| Worktree branch | `harness/<run-id>` |
| State row | `runs.run_id` |
| Event log | `events.run_id` |
| Artifacts dir | `.harness/artifacts/<run-id>/` |
| Logs | `.harness/logs/<run-id>.log` |

`harness logs <run-id>`, `harness status <run-id>`, `git log harness/<run-id>` all work against the same identifier. One ID, one grep.

---

## 9. Worktree Isolation

### Composable, not baked in

Worktree handling is a node type, not an engine feature. Workflows opt in:

- **Code-mutating workflows** (feature, bugfix) start with `worktree.create` and end with `worktree.cleanup`.
- **Read-only workflows** (steward, review) skip worktree nodes entirely.

### Mount and path

- The container mounts the project repo at `/workspace` (bind mount of e.g., `/abs/path/to/your-repo` on the host).
- Worktrees are created inside the mount at `/workspace/.worktrees/harness/<run-id>/` so they share the gitdir.
- `.worktrees/` is in the project's `.gitignore` (already done for many projects).

### Branch identity

- Every run gets a unique branch: `harness/<run-id>`. No collisions between concurrent runs.
- Cleanup policies:
  - `merge_to_base` — fast-forward `<base>` to the worktree branch, delete worktree, delete branch.
  - `leave_for_inspection` — delete the worktree but keep the branch (for human follow-up).
  - `delete_unconditionally` — delete worktree and branch regardless of state. For ephemeral runs (e.g., shadow mode).

### Validation

At workflow load time the engine builds a dependency graph and checks: any node with `writes_files: true` has a `worktree.create` ancestor. Otherwise the workflow is rejected with a clear error.

---

## 10. Execution Engine Details

### Sequencing

Steps execute in declared order. `depends_on:` is rarely needed because most workflows are linear. When present, the executor topologically sorts within a step block.

### Loop blocks

```yaml
- id: implement-and-test
  type: loop
  loop:
    max_iterations: 5
    until: state.tests_pass
    steps: [...]
```

The loop runs its `steps` in declared order, evaluates `until:` against state, repeats up to `max_iterations`. On exit:
- If `until:` is true → continue to the next step in the parent.
- If `max_iterations` reached without satisfying `until:` → workflow fails (exit 1) with a `loop_exhausted` event.

`fresh_context: true` (optional) reinitialises the AI context per iteration. Useful for "self-correcting" loops where carrying prior reasoning hurts. It also clears any sessions stored by `persist_session: true` steps (via the adapter's `reset()`), so it overrides per-step session persistence.

**Satisfaction predicate — `until:` or `until_bash:`.** A loop block must declare exactly one. `until:` is a Python boolean expression over `state` (the default shape). `until_bash:` is a shell command run via `bash -c` after each iteration; exit 0 means satisfied, any non-zero exit means not-yet-satisfied. `$state.<field>` / `$inputs.<key>` references inside the command are substituted before exec; missing references fail the workflow. A 300s wall-clock timeout caps each invocation — a timed-out command is treated as "not satisfied" and the `loop_iteration` event carries `data.until_bash_timeout=true`. Declaring both `until:` and `until_bash:` is rejected as ambiguous.

**`retry_loop:<loop-id>` from a child check rewinds to the named loop.** When a `check` step inside (or after) a loop fails with `on_fail: retry_loop:<id>`, the enclosing loop starts another iteration of the loop whose `step.id` matches `<id>`. The retry counts against the same `max_iterations` budget. The pre-retry `loop_iteration` event carries `data.trigger=retry_loop_requested` and `data.requested_by=<check-id>` so the rewind is visible in the event log. A `retry_loop:<id>` referencing a loop that is not on the active stack fails the workflow with a message naming the offending id.

### Retry policies (three layers, distinct)

| Layer | Trigger | Policy (v1, fixed) |
|-------|---------|--------------------|
| Transient | Provider 5xx, network timeout | 3 attempts, exponential backoff |
| Contract violation | LLM output failed Pydantic validation | 2 attempts with stricter system message |
| Logic failure | Test/check returned fail | None — handled by `loop` block |

These layers never compound silently. Retries emit `retry_attempted` events with attempt number and reason.

**Non-configurable in v1.** The defaults above are baked in — there is no YAML knob to tune them per-node or per-workflow. This keeps the schema lean and forces real failure data before we add tuning surface. If a v1 workflow hits a retry pathology, the fix is to address the root cause (better prompt, better contract), not to twist the dial. Per-node configuration moves to v1.5 when there's evidence it earns its keep.

### Cancellation

`SIGINT` (Ctrl-C) gracefully aborts: emit `workflow_failed` with reason `cancelled`, run cleanup nodes (worktree teardown if applicable), exit 130.

### Stall detection (AI nodes)

An AI node is **stalled** when it's still running but the SDK has emitted no `tool_called` / `tool_completed` / `node_completed` event for `stall_timeout_s` seconds (default 300). On stall:

- Kill the underlying SDK call.
- Emit `node_failed` with reason `stalled`.
- Update run status to `stalled`.
- Apply the contract-violation retry layer (1 retry with stricter prompting) before giving up.

Stall is distinct from the hard `timeout_s` wall (which terminates after total elapsed time regardless of activity). Real failure mode for long-running AI nodes — captured separately so debugging can distinguish "agent ran 10 minutes producing useful output" from "agent hung 5 minutes producing nothing."

---

## 11. CLI Design

### Command surface

```
# Audited verbs — one-shot, ledger-backed; the orchestrating agent calls these
harness start  <ticket>   [--base <b>] [--repo <p>] [--db <p>] [--json]
harness review            [--run-id <id>] [--repo <p>] [--db <p>] [--json]
harness close  <ticket>   [--run-id <id>] [--repo <p>] [--db <p>] [--json]

# Read / inspection — never mutate state
harness status    <run-id>                [--json]
harness logs      <run-id>                [--follow] [--node <id>]
harness events    <run-id>                [--type <event_type>] [--json] [--after-id <n>]
harness runs                              [--failed] [--limit <n>]
harness worktrees list                    [--json]
harness worktrees cleanup                 [--age <duration>] [--merged]

# Ops
harness cancel    <run-id>                    # abandon an in-flight run (close without merge)
harness doctor                                # system health checks
harness serve     --local                     # host launcher control socket
harness version                           [--json]
```

#### Harness-as-tool verbs

`start` / `review` / `close` are the audited, one-shot verbs an
orchestrating agent calls — see `specs/proposals/harness-as-tool.md`. They
operate over the SQLite ledger, not the workflow engine.

**`harness review`** runs the configured reviewer (codex) against the worktree's
current HEAD and records a `review` event bound to the exact SHA reviewed — the
load-bearing correctness detail behind decision **D2** (the `close` gate
refuses a pass whose SHA ≠ HEAD, so a stale pass cannot be reused).

- Resolves *the current run* — the `status='open'` run whose `worktree_path`
  equals `--repo` (CWD by default), or the run named by `--run-id`. No open run
  resolved → exit 2.
- Captures `git rev-parse HEAD` in that worktree as `reviewed_sha`.
- Invokes `codex exec --dangerously-bypass-approvals-and-sandbox --ephemeral -`
  with the review prompt on stdin and scans stdout for the first `SUBMIT: <json>`
  line. The JSON carries `verdict` (`pass`|`fail`|`defer`), `issues[]`, and
  optional `commit_message` / `deferred_brief`. A missing, malformed, or
  unknown-verdict SUBMIT line is recorded as `verdict='fail'` with the sentinel
  issue `"reviewer emitted no valid SUBMIT line"` — the verb never raises on a
  bad reviewer, it records the failure.
- Appends a `review` event (`harness.events.schema` event type `review`) whose
  `data_json` holds `run_id`, `reviewed_sha`, `verdict`, `issues`, optional
  `commit_message` / `deferred_brief`, and `created_at`.
- **Context economy:** prints only the bounded verdict — `verdict`, `issues`,
  `reviewed_sha`, `run_id`. Codex's full stdout / reasoning stays inside the
  verb and never enters the printed or returned JSON, keeping the agent's
  context budget bounded. A recorded `fail` is still a *successful review*
  (exit 0); deciding what to do with a verdict is the agent's job, not the
  verb's. Exit codes mirror `start`: 0 success, 1 unexpected error, 2 no open
  run resolved.

### Fixed verb surface (no dynamic subcommands)

The surface above is **fixed**. There is no per-workflow dynamic subcommand
generation: each verb is a hand-written Typer command with a stable flag set,
and adding behaviour means adding or changing a verb, not loading YAML at
invocation. The authoritative, agent-facing contract for the verbs the
orchestrating session drives is [`commands/harness.md`](commands/harness.md);
the registered command set is wired in `harness/cli/__init__.py`.

### Exit codes (stable contract)

| Code | Meaning |
|------|---------|
| 0 | Command succeeded |
| 1 | Unexpected error (git failure, DB error, Linear error) |
| 2 | Invocation error or gate refusal (bad flags, unknown run-id, gate not satisfied) |
| 130 | SIGINT (user cancelled) |

### JSON output

`status` and `events` expose `--json` for machine consumers; `logs` is the
human-readable timeline (use `events --json` for its machine-readable form) and
`runs` prints a summary table. The verbs (`start` / `review` / `close`) also
take `--json`. Flag names and JSON keys are part of the public contract — no
breaking changes without a major version bump.

### Examples

```bash
# Open a run for a ticket (transitions it to In Progress, creates the worktree)
harness start CAL-123

# Review the worktree HEAD — the verdict binds to the reviewed SHA
harness review --run-id 01J...

# Close through the gate (merge/push, transition the ticket to Done)
harness close CAL-123 --run-id 01J...

# Inspect a run without mutating it
harness status 01J... --json | jq .status
```

---

## 12. SQLite Schema

Single database per project: `/workspace/.harness/harness.db`.

```sql
CREATE TABLE runs (
  run_id              TEXT PRIMARY KEY,
  workflow_name       TEXT NOT NULL,
  workflow_version    INTEGER NOT NULL,
  status              TEXT NOT NULL,  -- pending | running | completed | failed | cancelled | stalled | paused
  state_json          TEXT NOT NULL,  -- serialized Pydantic state, latest snapshot
  inputs_json         TEXT NOT NULL,  -- caller-provided inputs
  base_branch         TEXT,
  worktree_branch     TEXT,
  exit_code           INTEGER,
  started_at          TEXT NOT NULL,
  completed_at        TEXT,
  duration_ms         INTEGER
);

CREATE INDEX idx_runs_status ON runs(status);
CREATE INDEX idx_runs_workflow ON runs(workflow_name);
CREATE INDEX idx_runs_started ON runs(started_at);

CREATE TABLE events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id      TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  node_id     TEXT,
  event_type  TEXT NOT NULL,
  timestamp   TEXT NOT NULL,
  duration_ms INTEGER,
  data_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_events_run ON events(run_id);
CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_run_node ON events(run_id, node_id);
```

WAL mode enabled for concurrent reads (`harness status` while a run is in progress).

---

## 13. Docker Setup

### Image

```dockerfile
# docker/Dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /opt/harness
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY harness/ ./harness/
COPY workflows/ ./workflows/
COPY prompts/ ./prompts/

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["uv", "run", "harness"]
```

### Invocation

```bash
docker run --rm -it \
  -v "$(pwd)":/workspace -w /workspace \
  -v "$HOME/.claude":/root/.claude:ro \
  -e LINEAR_API_KEY \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434/v1 \
  harness:latest \
  run feature --linear=PROJ-249 --base=staging
```

### Mount strategy

- `$(pwd)` (host project repo) → `/workspace` (container).
- Worktrees land at `/workspace/.worktrees/harness/<run-id>/` (visible to host).
- State + events at `/workspace/.harness/harness.db` (visible to host).
- `~/.claude` (host) → `/root/.claude` (container, read-only) when using OAuth subscription auth — see Auth below.
- Ollama runs on the host; `host.docker.internal` lets the container hit it (v1.5+ adapters only).

### Auth

The engine wraps `claude_agent_sdk`, which follows Claude Code's auth conventions. Three paths, in order of preference:

| Path | Pricing | When |
|---|---|---|
| Mount `~/.claude` into the container (above example) | Subscription | Recommended for local + most CI cases where the OAuth host install exists. |
| `CLAUDE_CODE_OAUTH_TOKEN` env var (generated by `claude setup-token`) | Subscription | CI / non-interactive without OAuth file access. |
| `ANTHROPIC_API_KEY` env var | API rates | Fallback when neither OAuth source is available. |

The SDK picks them up in declared order. Other env vars (`LINEAR_API_KEY` for Linear-fetching workflows, `OPENAI_API_KEY` / `OLLAMA_BASE_URL` for v1.5+ adapters) are independent of the Claude auth choice.

All credentials come from environment / mount at runtime. Never baked into the image.

---

## 14. Example Workflow: Steward (smallest end-to-end)

The domain-steward workflow — read-only, no worktree, no code mutation. Smallest possible end-to-end exercise of the engine. Pure YAML, derived state, inline contracts.

```yaml
# workflows/steward.yaml
name: steward
version: 1
description: Domain steward review producing a structured report

inputs:
  domain:
    type: string
    enum: [architecture, harness, test, code, design]
    flag: --domain
    required: true

steps:
  - id: read-context
    type: ai
    agent: claude
    model: sonnet
    prompt: prompts/standard/analyze.j2
    template_vars:
      task: "Read the codebase and produce a structured summary of the $inputs.domain domain"
    allowed_tools: [Read, Grep, Glob, Bash]
    contract:
      summary: string
      key_files:
        type: list
        of: string
      open_questions:
        type: list
        of: string
    writes: [summary, key_files, open_questions]

  - id: assess
    type: ai
    agent: claude
    model: sonnet
    prompt: prompts/standard/review.j2
    template_vars:
      criteria: "$inputs.domain principles, recurring patterns, systemic issues"
    allowed_tools: [Read, Grep, Glob]
    contract:
      findings:
        type: list
        of:
          severity: string
          area: string
          description: string
      systemic_insights:
        type: list
        of: string
    writes: [findings, systemic_insights]

  - id: write-report
    type: script
    runtime: python
    script: scripts/write_steward_report.py
    args: ["--run-id", "$state.run_id", "--domain", "$inputs.domain"]
    contract:
      report_path: string
    writes: [report_path]
```

Three nodes, pure YAML. Derived state: `{ summary, key_files, open_questions, findings, systemic_insights, report_path }` plus the framework `BaseState` fields. Standard prompts (`analyze.j2`, `review.j2`) reused via `template_vars`.

### What the author did NOT write

- A `StewardState` Pydantic class — derived from the contracts.
- Any standalone Pydantic contract classes — declared inline.
- Custom Jinja templates — standard library is parameterised.
- A `state_schema:` declaration — there is no such field anymore.

The core ergonomics commitment: **a workflow is a YAML file. Nothing else.**

---

## 15. Migration Plan

Cut order: **stewards → bugfix → feature.**

| Phase | Scope | Done when |
|-------|-------|-----------|
| **A. Greenfield** | Build harness in isolation. Test with synthetic repo fixture. | Steward workflow runs end-to-end against fixture. Engine emits clean event log. |
| **B. Shadow** | Run steward + bugfix workflows against a target repo's dev branch alongside the existing pipeline. Worktrees + diffs + reports produced; **no merges**. Compare outputs against existing pipeline. | 5 successful shadow runs per workflow with comparable or better output. |
| **C. Cutover (partial)** | Stewards live (replace nightly-review). Bugfix live in normal mode. Feature work continues on current pipeline. | Legacy `nightly-review.skill` removed. Bugfixes flow through harness CLI. |
| **D. Cutover (full)** | Feature workflow live. Project manifest, change folders, strategy migrated or removed. CLAUDE.md slimmed to project-only content. | Project `harness/`, `manifest.yaml`, `harness/changes/` deleted. `CLAUDE.md` under 50 lines. |

### What goes back into a project's `CLAUDE.md` (target state)

A short, project-only file:
- Project description and tech stack
- Test/lint commands
- Code conventions
- Path to `skills/` (execution-side skills, not pipeline mechanics)
- Output-contract reminder for AI nodes invoked by harness

Pipeline phases, manifest, strategy, brand guidelines, harness mechanics — all leave the project's CLAUDE.md.

### What stays in a project's `skills/`

Only execution-side skills the AI nodes need to do good work: design-system rules, code conventions, security review checklist. Anything pipeline-related (linear-sync, worktree-isolation, dev-loop, start, nightly-review, etc.) deletes — the harness owns those concerns now.

---

## 16. Non-Goals (Important)

Explicit list of things this project does **not** do, even on request:

- Full DAG engine. v1 is linear + loop. DAG comes only when a real workflow needs it and a YAML hack would be uglier than parallel-step support.
- Web UI / dashboard. CLI + JSON output is enough.
- Workflow visual builder.
- Long-running daemon / server. The CLI runs, completes, exits. State persists in SQLite.
- Multi-tenancy / multi-project state in one DB. One DB per project mount.
- Built-in scheduling. Cron / launchd / systemd does that. The harness is invoked by them.
- LLM-driven workflow generation.
- General-purpose agent framework. The harness is a set of deterministic verbs an agent calls, not a framework that runs agents. If a use case wants an autonomous agent that spawns its own work, this isn't the tool.

---

## 17. Open Questions (deferred decisions)

These are deliberately unresolved. Pick before code lands.

1. **Workflow location: in-repo or harness-side?**
   - In-repo: workflows live in the project repo (`your-repo/.harness/workflows/`). Pro: per-project customisation lives with the project. Con: re-conflates the two repos we just decoupled.
   - Harness-side: workflows live in `harness/workflows/`, parameterised per project. Pro: clean decoupling. Con: per-project tweaks require touching the harness repo.
   - **Lean:** harness-side, because cleanliness > convenience for a single-team tool. Revisit when a second project consumes the harness.

2. **State persistence on resume.** ~~Defer until we hit a workflow that genuinely benefits from mid-run resume.~~ **Resolved by the `decision` node (§5):** `actor: human` requires resume capability, and that's promoted to v2 critical path. v1 stores latest state on the row; v2 lifts that to per-completion snapshots so paused runs can be rehydrated cleanly. Resume-from-failure (the broader case) follows the same machinery — once human-decision resume works, resume-from-failure is mostly a CLI verb away.

3. **Concurrent runs against the same project.** Multiple worktrees on the same repo are fine (different branches). The SQLite question deserves an explicit analysis, not a hand-wave:

   - **`runs` table:** each concurrent run owns its row by `run_id` PK. Updates target distinct rows — no contention.
   - **`events` table:** append-only, autoincrement PK. SQLite WAL mode handles concurrent appenders cleanly (writers serialise on the WAL, readers don't block).
   - **State writes:** the `runs.state_json` column is updated per-run, so concurrent state writes target different rows. No shared resource.
   - **Reads (`harness status`, `harness logs`) during a running workflow:** WAL means readers see a snapshot without blocking writers.

   The risk is bounded: the only real contention point is bursty event writes from many concurrent runs, which WAL serialises with millisecond-class lock acquisition. Acceptable for v1's expected workload (1–3 concurrent runs locally). If usage grows beyond that, switch to PostgreSQL — the schema is portable.

4. **External trigger source (Discord, etc.) — built-in or external?** *Resolved: external.* The harness exposes the CLI and does not listen; any process that watches a source and shells out to a verb lives in a sibling repo or in Hermes, never in this tool. The engine-era webhook listener that violated this boundary was retired in CAL-601.

5. **Prompt-cache strategy.** Anthropic cache breakpoints could materially cut token cost for steward runs that re-read the same context daily. Defer to v0.2 once we have real token-cost data.

---

## 18. Success Criteria

### For this spec (review)

- [ ] Read in one sitting (~30 minutes).
- [ ] No "what does X mean" gaps — every term used is defined or obvious.
- [ ] Repo structure proposal (§3) is concrete enough to scaffold without ambiguity.
- [ ] YAML schema (§5) is concrete enough to write a workflow without inventing fields.
- [ ] CLI surface (§11) is stable enough to publish to callers immediately.
- [ ] Migration plan (§15) is concrete enough to start Phase A this week.

### For v1 implementation (acceptance)

- [ ] **The 10-minute workflow test.** A new workflow can be written from a blank page in under 10 minutes, end-to-end, by someone who's read this spec once. Test with a real example: write a `release-notes` workflow that pulls Linear tickets from the last week and asks Claude to summarise. If it feels slow, verbose, or mentally taxing, the system is too heavy and v1 needs cuts before shipping.
- [ ] Steward workflow runs end-to-end against a synthetic repo fixture.
- [ ] Token cost per run is logged and visible in `harness status --json`.
- [ ] Event log captures every tool call inside an AI node (replay-quality observability).
- [ ] Concurrent runs against the same project don't collide (per §17.3 analysis).

If any of these fail at scaffolding time, fix the spec before continuing.

---

## Appendix A — Inspirations and design ancestry

- [Archon](https://github.com/coleam00/Archon) — workflow concepts (DAG node types, fresh-context loops, worktree-per-run, per-tool-call event log). This spec lifts the *ideas*; the *code* is greenfield Python.
- Anthropic's "harness design" essay — the bounded-LLM-as-function principle.
- Pydantic 2's strict mode — model for "validate at the boundary, trust within."
- Temporal — for the "deterministic engine, stateful inputs" mental model (we don't need the durable-execution machinery, but the conceptual split is the same).
