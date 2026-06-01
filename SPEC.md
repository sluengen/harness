# Calibrate Harness — Design Specification

**Version:** 0.6 (planning)
**Status:** Under revision. No code lands until this is approved.
**Guiding principle:** *Build a deterministic execution engine, not an agent framework.*

---

## 1. Mission

Execute workflows deterministically. Decouple *what work gets done* (orchestration, agents, humans) from *how work runs* (this harness).

### Core principles

1. **Strict separation of concerns.** External layer decides what to run. Harness decides how it runs.
2. **Deterministic execution.** Control flow does not depend on LLM outputs. All branching, looping, and termination are defined in code or YAML.
3. **LLMs as bounded functions.** AI nodes execute tightly scoped tasks against declared contracts. The workflow declares the bounded *tool set* available to a node; the LLM chooses which tools to use within that set — that's where its creative problem-solving applies. **The YAML defines what to do with each step's output; the LLM provides typed answers to declared questions.** An LLM contributing a `decision: bool` to a gate is the LLM answering a question, not deciding the route — the YAML's `on_reject:` decides the route. Control flow shape is deterministic and lives in YAML, not in model judgement.
4. **Reproducibility.** Same inputs → same execution behaviour. Container provides consistent runtime.
5. **CLI is a public contract.** The harness is invoked by humans, agents, and meta-orchestrators through the same CLI surface. Stable flags, stable exit codes, stable JSON output.
6. **Data flows via the workflow, not the agent.** External data (Linear issues, Notion content, GitHub state) is fetched by deterministic upstream nodes and passed to AI nodes via state and template variables. AI nodes do not reach out to MCP servers, plugin systems, or external APIs at runtime. This keeps token cost predictable (no model burning context deciding what to fetch), keeps state explicit (the run record shows exactly what the agent saw), and keeps the agent-harness layer thin (no MCP servers to configure per-adapter, no asymmetry between Claude Code / codex / opencode features to paper over).

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  External layer (orchestration)                                 │
│  - Linear webhook / Discord intake / Cron / Claude Code agent   │
│  - Decides WHAT to run                                          │
│  - Invokes harness via CLI                                      │
└───────────────────────────┬─────────────────────────────────────┘
                            │ harness run <workflow> [flags]
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Harness (this project)                                         │
│  - Loads YAML workflow + Pydantic state schema                  │
│  - Walks steps in declared order                                │
│  - Dispatches AI / script / check / worktree nodes              │
│  - Validates contracts, writes state, emits events              │
└───────────────────────────┬─────────────────────────────────────┘
                            │ subprocess / SDK
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Execution environment (inside container)                       │
│  - Mounted project directory at /workspace                      │
│  - Worktree per run (when workflow opts in via worktree node)   │
│  - Agent harness: claude_agent_sdk / codex / opencode (subproc) │
│  - SQLite state + event log at /workspace/.harness/             │
└─────────────────────────────────────────────────────────────────┘
```

### Data flow per run

1. Caller invokes `harness run feature --linear CAL-249 --base staging`.
2. Harness generates a `run_id` (ULID).
3. Harness loads `workflows/feature.yaml` + its declared `state_schema`.
4. Harness initialises state, writes a `runs` row, emits `workflow_started`.
5. For each node in declared order:
   a. Resolve dependencies from prior state.
   b. Render prompt template (Jinja) with state.
   c. Dispatch to agent / script / check / worktree handler.
   d. Validate output against the node's `contract`.
   e. Apply `writes:` declarations to state. Reject any other state mutation.
   f. Emit `node_completed`.
6. On loop blocks, re-execute step list until `until:` condition evaluates true on state.
7. On workflow completion, write `completed_at`, emit `workflow_completed`, exit 0.

The engine never asks an LLM what to do next. The YAML decides.

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
│   ├── identity.py            ← run_id generation, propagation
│   └── log.py                 ← structured logging
├── workflows/                 ← YAML workflow definitions (yours go here)
│   ├── release-notes.yaml     ← shipped: pull Linear, summarise, write file
│   └── steward.yaml           ← shipped: domain steward review (calibrate-coffee context)
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

### 4.1 `harness.engine.runner`

Top-level orchestrator. One `Runner.run(workflow_path, inputs)` call per invocation.

Responsibilities:
- Generate `run_id`.
- Load workflow YAML and its state schema.
- Initialise state from `inputs` and defaults.
- Walk steps in declared order, including loop blocks.
- Catch fatal errors, emit terminal event, set exit code.

Does **not** know about AI, scripts, or worktrees — delegates to nodes.

### 4.2 `harness.engine.executor`

Per-node execution. `Executor.execute(step, state, context) -> NodeResult`.

Responsibilities:
- Resolve `depends_on` (state must contain referenced fields).
- Render prompt via `harness.workflow.prompt`.
- Dispatch to the matching `Node` implementation.
- Validate the node's output against its declared `contract` (Pydantic).
- Apply `writes:` declarations — only declared fields propagate to state.
- Emit `node_started` / `node_completed` / `node_failed`.

### 4.3 `harness.nodes.base`

The interface every node implements:

```python
class Node(Protocol):
    type: ClassVar[Literal["ai", "script", "check", "worktree"]]
    async def execute(self, step: Step, state: BaseState, ctx: Context) -> NodeResult: ...

class NodeResult(BaseModel, Generic[T]):
    contract: T                 # workflow-defined Pydantic — the actual deliverable
    attestation: Attestation    # agent's self-report (informational only)
    artifacts: Artifacts        # file mutations

class Attestation(BaseModel):
    status: Literal["complete", "partial", "blocked"]
    reasoning: str              # short, for the event log

class Artifacts(BaseModel):
    diff: str | None
    commit_sha: str | None
    files_changed: list[Path]   # validated to be inside state.worktree_path
```

**Hard rule (engine enforcement):** Control flow may read from `state` and from `check` node results. It may **not** read from `attestation`. Attestation is for the event log and human debugging only.

### 4.4 `harness.nodes.ai`

AI node. Wraps an agent harness (claude_agent_sdk / codex / opencode — see §4.7) for the duration of one bounded task.

Inputs:
- Rendered prompt (Jinja2, with `state`, `inputs`, and any `template_vars` in scope).
- Contract type (Pydantic — compiled from inline YAML or `$contracts/<name>` reference).
- Allowed tool set (`allowed_tools:`; default read-only: `Read`, `Grep`, `Glob`).

Output: `NodeResult[contract]`.

#### Structured output via native tool calling

The contract compiles to **two** artefacts at workflow load time:

1. A **Pydantic model** for final validation.
2. A **tool schema** (in the agent harness's native dialect) called `submit_<node_id>`, with one parameter per contract field, typed.

The agent's instructions are: do the work using the allowed tools, then call `submit_<node_id>` exactly once with the typed payload. The harness extracts the call's arguments → validates against Pydantic → that's the `NodeResult.contract`.

This pattern uses what RL-trained models are best at (tool calling), avoids fighting the harness's response format, and gives us first-line validation from the harness itself before our Pydantic check runs.

#### Notes channel — auto-captured from text deltas

Whatever text the agent emits *between* tool calls — "I'll start by reading X, looks like the issue is Y, now I'll check Z" — is captured automatically into `state.notes` (list-append). This is framework-provided, not workflow-opt-in: the harness listens to the agent harness's text-delta stream and routes each chunk as a note entry. No `note(text)` tool, no special declaration in the contract. The agent just talks; the harness just listens.

Notes are bounded — see §7.

#### Failure-mode catalogue (real, not hypothetical)

Tool-call-based structured output works almost every time. The "almost" is what makes the engine robust. The patterns below are MECE — each carries a distinct retry response, so the engine discriminates by `ContractViolation.reason` rather than collapsing them.

| Pattern | `reason` | Detection | Response |
|---|---|---|---|
| Model narrates the answer in chat instead of calling submit | `not_called` | Submit tool not called by end of turn | Contract-violation retry: stricter system message ("you MUST call submit_X with the typed payload, not narrate"). Fails after retry. |
| Model calls submit with placeholder values (`"summary": "TODO"`) | `placeholder` | Pydantic validation passes but values look like placeholders (regex on common patterns: `TODO`, `<...>`, `example`, etc.) | Contract-violation retry: "be specific — placeholders are not acceptable values." Engine logs the suspicious payload. |
| Model calls submit but the payload fails Pydantic validation | `validation_failed` | Submit tool called; Pydantic raises ValidationError on the arguments | Contract-violation retry: error feedback inline, "match the schema fields exactly." Distinct from `placeholder` because Pydantic itself rejected — the agent didn't even produce a structurally valid call. |
| Model calls submit twice with different content | (warning, not violation) | Engine sees two `tool_called(submit_*)` events | First call wins. Second call is logged as `decision_violation` event and emits a warning. Workflow continues. |
| Model calls submit then keeps emitting text | (informational) | submit was called, but agent hasn't ended turn | Engine treats first call as the result; subsequent text becomes notes. |
| Model never calls submit and exits the loop | `not_called` | Submit tool not called by turn end + agent stop | Same as the narration case — agent never produced output. Contract-violation retry. |

Each detection runs in the executor wrapper around the agent call. Each fires a `node_failed` (or, in the double-submit case, a `decision_violation` event) with a specific reason so failure-mode debugging is a single grep, not interpretive archaeology.

Retries: see §10. Contract violations retry up to N with stricter system messages, then fail with exit code 3.

### 4.5 `harness.nodes.decision`

Decision/approval gate. Two actor flavors:

**`actor: llm`** (v1) — same execution shape as an AI node, but the contract must include a `decision: bool` field and the engine routes on it via `on_reject:`. Emits a dedicated `decision_made` event so audit queries can find gates without parsing every node output. Implemented as syntactic sugar over the AI dispatch path plus routing.

**`actor: human`** (v2 — schema reserved in v1, errors at load time until v2 ships) — pauses the workflow. Engine emits `decision_requested`, writes `paused_awaiting_decision` status to the runs row, persists state, prints the prompt + run-id to stdout, and exits with code **4**. The decision arrives via a separate CLI invocation (`harness decision approve|reject <run-id>`) which rehydrates state, emits `decision_received`, and resumes from the next step.

The resume machinery lives in `harness/decisions/`. v1 ships the schema parser (which validates the YAML) and a load-time guard that rejects workflows using `actor: human` until v2 lands.

### 4.6 `harness.nodes.worktree`

Three sub-types via parameter, not separate node types:

```yaml
- id: setup
  type: worktree
  action: create
  base: $state.base_branch
  writes: [worktree_path, worktree_branch]

- id: teardown
  type: worktree
  action: cleanup
  policy: merge_to_base    # or: leave_for_inspection | delete_unconditionally
  reads: [worktree_path, worktree_branch]
```

**Engine enforcement (load-time validation):** any node with `writes_files: true` (set by AI / script nodes that mutate the worktree) must have a `worktree.create` node upstream in the dependency graph. Workflows lacking this are rejected at load time. Prevents file mutations from escaping to source.

### 4.7 `harness.dispatch.base`

The `Agent` protocol wraps an **agent harness**, not a raw model API. We do not reimplement the tool loop — Claude Code, codex, and opencode have all converged on the same shape and frontier labs RL-train against it. We rent that loop and own the deterministic workflow layer above.

```python
class Agent(Protocol):
    async def execute(
        self,
        prompt: str,
        contract: type[BaseModel],
        submit_tool_schema: dict,    # auto-generated from contract; see §4.4
        *,
        allowed_tools: list[str],
        cwd: Path | None,
        timeout_s: int = 600,
        stall_timeout_s: int = 300,
    ) -> NodeResult: ...
```

Implementations:

- **v1 — `dispatch.claude_agent.ClaudeAgent`** — uses `claude_agent_sdk` (Anthropic's Python SDK that embeds the Claude Code loop in-process). Auths via `claude /login` for **subscription pricing** or `ANTHROPIC_API_KEY` for API rates. Ships day one.
- **v1.5 — `dispatch.codex.CodexAgent`** — subprocess `codex` CLI for OpenAI models. OpenAI's frontier models are RL-trained against the codex tool-call format — using the native harness avoids the small-but-real performance penalty of routing through opencode's generic dispatch.
- **v1.5 — `dispatch.opencode.OpencodeAgent`** — subprocess `opencode` CLI for **local models** (Ollama / llama-swap / llama.cpp via OpenAI-compatible endpoint). Could also serve OpenAI as a fallback, though codex is preferred for OpenAI native models.

#### Why claude_agent_sdk and not the raw `anthropic` SDK

The raw Anthropic SDK gives us a model API. `claude_agent_sdk` gives us the Claude Code loop in-process (tool execution, structured response handling, sandbox semantics). Building the loop ourselves is ~1000 LOC of agent-harness reinvention. Using the SDK is ~150 LOC of adapter code and we inherit Anthropic's improvements as the SDK evolves.

#### Feature symmetry — resolved by Principle 6

Different agent harnesses expose different feature surfaces (Claude Code has rich MCP, skills, hooks; codex has a different dialect; opencode has its own). On the surface that's an asymmetry problem.

**It isn't, because of Principle 6.** We don't use those features in the agent loop. Linear data is fetched by an upstream `script` node and passed via state, not by an in-loop MCP server. Domain knowledge lives in the prompt template (and Jinja partials), not in skills. Pre/post-tool-call interception, if we ever need it, lives at the engine level (executor wraps the agent call), not at the harness level — that makes it portable.

The lowest-common-denominator we *do* depend on across all three adapters:
- Tool calling with typed schemas
- Streaming text output (for notes capture)
- A bounded, explicit tool list (for `allowed_tools:`)
- Per-tool-call observability (events captured during execution)

All three harnesses support all four. Asymmetry is real but doesn't bite the workflow layer.

Adding a new agent (e.g., aider, cline, or a future opencode replacement) is one ~150–250-line module that implements `Agent`. No engine changes.

### 4.8 `harness.state.store`

Per-run state lives as a single JSON blob on the `runs` row. The state schema is **derived** at workflow load time from the union of `writes:` declarations across all nodes (see §6). State changes always go through `StateStore.update(run_id, **fields)` which (a) validates fields against the derived schema, (b) applies type-driven merge semantics (see §7), (c) updates the JSON, (d) emits a `state_changed` event.

**Direct state mutation by nodes is forbidden.** Nodes return a `NodeResult`; the executor extracts fields per the `writes:` declaration and calls the store.

### 4.9 `harness.events.emitter`

Append-only event log in SQLite. Schema in §12.

Events:
- `workflow_started`, `workflow_completed`, `workflow_failed`, `workflow_paused`
- `node_started`, `node_completed`, `node_failed`
- `tool_called`, `tool_completed` (per tool call inside an AI node — captured from the SDK)
- `state_changed`
- `loop_iteration`
- `retry_attempted`
- `decision_requested`, `decision_made` (LLM actor), `decision_received` (human actor, v2), `decision_timeout` (v2), `decision_violation` (warning when an agent calls submit twice — see §4.4)

Each event has `run_id`, `node_id` (nullable), `event_type`, ISO timestamp, JSON `data`, `duration_ms` (nullable).

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
harness run feature --linear=CAL-249                          # flag form
harness run feature "Build a dropdown menu"                   # positional form
harness run feature --linear=CAL-249 "with these specifics…"  # both
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

- The container mounts the project repo at `/workspace` (bind mount of e.g., `/Users/scottluengen/Documents/1_Projects/calibrate-coffee` on the host).
- Worktrees are created inside the mount at `/workspace/.worktrees/harness/<run-id>/` so they share the gitdir.
- `.worktrees/` is in the project's `.gitignore` (already true for Calibrate).

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

`fresh_context: true` (optional) reinitialises the AI context per iteration. Useful for "self-correcting" loops where carrying prior reasoning hurts.

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
harness run <workflow> [<positional>...] [--<input>=<value> ...]
harness status <run-id>                   [--json]
harness logs <run-id>                     [--follow] [--node <id>]
harness events <run-id>                   [--type <event_type>] [--json]
harness worktrees list                    [--json]
harness worktrees cleanup                 [--age <duration>] [--merged]
harness decisions list                    [--json]                  # v2: paused runs
harness decision show <run-id>            [--json]                  # v2
harness decision approve <run-id>         [--comment="..."]         # v2
harness decision reject  <run-id>         [--comment="..."]         # v2
harness validate <workflow.yaml>          # static validation, no execution
harness version                           [--json]
```

The `decisions` / `decision` surface is **reserved in v1** — the verbs exist as no-ops or "not yet implemented" errors, but the names won't change in v2. Callers can plan for them.

### Per-workflow inputs (dynamic subcommand generation)

The `<workflow>` slot in `harness run <workflow>` is dynamic. The CLI loads the workflow YAML at invocation, reads its `inputs:` block, and generates the appropriate flag and positional argument structure on the fly. **The workflow IS the CLI definition for its own subcommand.**

This means:
- `harness run feature --help` introspects `workflows/feature.yaml` and prints that workflow's specific flags + positional args.
- Adding a new workflow means writing YAML, not editing CLI code.
- Per-workflow input shape is defined in the YAML's `inputs:` block (see §5 — *Inputs and CLI generation*).

Examples across workflows:

```bash
harness run feature --linear=CAL-249               # flag form
harness run feature "Build a dropdown menu"        # positional form (input has `position: 1`)
harness run steward --domain=architecture
harness run bugfix --linear=$LINEAR_ID --base=staging
harness run review --pr=142 --json | jq .review_status
```

### Exit codes (stable contract)

| Code | Meaning |
|------|---------|
| 0 | Workflow completed successfully (state matches expected terminal condition) |
| 1 | Workflow failed (caught error during execution — e.g., loop exhausted, check failed) |
| 2 | Invocation error (bad flags, missing config, workflow YAML invalid, state schema import failed) |
| 3 | Contract violation (LLM output failed validation after exhausting retries) |
| 4 | Paused awaiting decision (human-decision node, v2) — not a failure; resumes via `harness decision approve\|reject` |
| 130 | SIGINT (user cancelled) |

### JSON output

Every read command supports `--json` for machine consumers. Schema is versioned via `output_schema_version` field. Flag names and JSON keys are part of the public contract — no breaking changes without a major version bump.

### Examples

```bash
# Human / agent kicks off a feature
harness run feature --linear=CAL-249 --base=staging

# Cron fires the nightly architecture steward
harness run steward --domain=architecture

# Linear webhook (future) shells out
harness run bugfix --linear=$LINEAR_ID --base=staging

# Claude Code session inside the agent flow
# (the harness binary is on PATH inside any container that has it)
harness run review --pr=142 --json | jq .review_status
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
  run feature --linear=CAL-249 --base=staging
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
| **B. Shadow** | Run steward + bugfix workflows against Calibrate dev branch alongside the existing pipeline. Worktrees + diffs + reports produced; **no merges**. Compare outputs against existing pipeline. | 5 successful shadow runs per workflow with comparable or better output. |
| **C. Cutover (partial)** | Stewards live (replace nightly-review). Bugfix live in normal mode. Feature work continues on current Calibrate harness. | Calibrate's `nightly-review.skill` removed. Bugfixes flow through harness CLI. |
| **D. Cutover (full)** | Feature workflow live. Calibrate manifest, change folders, harness/, strategy/ migrated to Notion or removed. CLAUDE.md slimmed to project-only content. | Calibrate `harness/`, `manifest.yaml`, `harness/changes/` deleted. `CLAUDE.md` under 50 lines. |

### What goes back into Calibrate's `CLAUDE.md` (target state)

A short, project-only file:
- Project description and tech stack
- Test/lint commands
- Code conventions
- Path to `skills/` (execution-side skills, not pipeline mechanics)
- Output-contract reminder for AI nodes invoked by harness

Pipeline phases, manifest, strategy, brand guidelines, harness mechanics — all leave Calibrate.

### What stays in Calibrate's `skills/`

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
- General-purpose agent framework. This is an execution engine for *bounded* AI tasks. If a use case wants an autonomous agent, this isn't the tool.
- **Tracker writes from the engine.** The harness reads from trackers (Linear, GitHub) for intake and status checks. Writing back — updating ticket status, posting PR comments, transitioning workflow state — is the agent's job (via its tool calls inside an AI node) or an explicit `script` node's job. The engine itself never writes to a tracker. This boundary keeps the engine portable and prevents implicit coupling to any one tracker's state machine.

---

## 17. Open Questions (deferred decisions)

These are deliberately unresolved. Pick before code lands.

1. **Workflow location: in-repo or harness-side?**
   - In-repo: workflows live in the project repo (`calibrate-coffee/.harness/workflows/`). Pro: per-project customisation lives with the project. Con: re-conflates the two repos we just decoupled.
   - Harness-side: workflows live in `harness/workflows/`, parameterised per project. Pro: clean decoupling. Con: per-project tweaks require touching the harness repo.
   - **Lean:** harness-side, because cleanliness > convenience for a single-team tool. Revisit when a second project consumes the harness.

2. **State persistence on resume.** ~~Defer until we hit a workflow that genuinely benefits from mid-run resume.~~ **Resolved by the `decision` node (§5):** `actor: human` requires resume capability, and that's promoted to v2 critical path. v1 stores latest state on the row; v2 lifts that to per-completion snapshots so paused runs can be rehydrated cleanly. Resume-from-failure (the broader case) follows the same machinery — once human-decision resume works, resume-from-failure is mostly a CLI verb away.

3. **Concurrent runs against the same project.** Multiple worktrees on the same repo are fine (different branches). The SQLite question deserves an explicit analysis, not a hand-wave:

   - **`runs` table:** each concurrent run owns its row by `run_id` PK. Updates target distinct rows — no contention.
   - **`events` table:** append-only, autoincrement PK. SQLite WAL mode handles concurrent appenders cleanly (writers serialise on the WAL, readers don't block).
   - **State writes:** the `runs.state_json` column is updated per-run, so concurrent state writes target different rows. No shared resource.
   - **Reads (`harness status`, `harness logs`) during a running workflow:** WAL means readers see a snapshot without blocking writers.

   The risk is bounded: the only real contention point is bursty event writes from many concurrent runs, which WAL serialises with millisecond-class lock acquisition. Acceptable for v1's expected workload (1–3 concurrent runs locally). If usage grows beyond that, switch to PostgreSQL — the schema is portable.

4. **Discord intake — built-in or external?** Initial bias: external. The harness exposes the CLI; a separate `intake/discord.py` script (in this repo or a sibling) listens to Discord and shells out. Keeps the harness boundary clean.

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
