# Workflow Schema — YAML structure, step types, inputs, contracts, validation

> **Superseded 2026-06-11** — this spec describes the **retired deterministic workflow engine**, deleted in CAL-574 (proposal [`harness-as-tool`](../proposals/harness-as-tool.md), decision D1). The harness no longer walks a YAML workflow: a single Claude session orchestrates *and* implements, calling the `start` / `review` / `close` verbs over the SQLite ledger. Current references: [`SPEC.md`](../../SPEC.md) §1–2, [`state-store.md`](../state-store.md), [`commands/harness.md`](../../commands/harness.md). Kept for historical reference only.

A workflow is a YAML file that fully defines its inputs, steps, and contracts. No Python files are required to add a new workflow.

---

## Purpose

The `Workflow` and step Pydantic models parse and validate workflow YAML at load time. The loader compiles contracts, resolves `$contracts/<name>` references, and runs additional cross-step validations.

---

## Workflow root

```yaml
name: build                  # required; snake-case, starts with letter
version: 2                   # integer >= 1
description: "..."           # optional
inputs:                      # optional mapping of input name → InputSpec
  linear_id:
    type: string
    pattern: "^[A-Z]+-\\d+$"
    flag: --linear
    required: true
steps:                       # required; at least one step
  - ...
```

`name` must match `^[a-z][a-z0-9_-]*$`. Step ids must be unique within the workflow (checked by a `model_validator`).

---

## Step types (discriminated union on `type:`)

All steps share `_BaseStep` common fields: `id`, `depends_on`, `writes`, `retry`.

### `ai`

```yaml
- id: review
  type: ai
  agent: claude              # adapter hint; currently only "claude" is live
  model: sonnet              # model hint forwarded to adapter
  prompt: prompts/build/review.j2
  template_vars: {}          # extra top-level Jinja vars
  allowed_tools: [Read, Grep, Glob]  # default
  contract: {...}            # inline or $contracts/<name>
  cwd: $state.worktree_path  # optional; falls back to state.worktree_path
  writes_files: false
  stall_timeout_s: 300
  timeout_s: 600
  max_turns: null            # optional cap on agent turns
  writes: [verdict, issues, commit_message]
```

### `script`

```yaml
- id: fetch-ticket
  type: script
  command: "curl -s ..."     # inline string; OR use script: path/to/file.sh
  runtime: bash              # bash (default) or python
  args: ["$inputs.linear_id"]
  contract:
    ticket_title: string
    ticket_description: string
  cwd: null
  writes_files: false
  writes: [ticket_title, ticket_description]
```

Exactly one of `command` or `script` must be declared.

### `check`

```yaml
- id: gate
  type: check
  expr: state.verdict == "PASS"
  on_fail: cancel            # cancel | continue | retry_loop:<id>
```

No contract field. `on_fail` must match `^(cancel|continue|retry_loop:[A-Za-z][A-Za-z0-9_-]*)$`.

### `decision`

```yaml
- id: approve
  type: decision
  actor: llm                 # llm | human (human = v2, rejected at load time)
  prompt: prompts/standard/can_proceed.j2
  allowed_tools: []
  contract:
    decision: boolean
    reasoning: string
  on_reject: cancel          # cancel | continue | retry_loop:<id> | pause_for_human
  writes: [data]
```

`actor: human` is reserved for v2 and rejected at load time with a clear error. `actor: llm` requires `prompt`.

### `worktree`

```yaml
- id: setup
  type: worktree
  action: create             # create | cleanup
  base: $inputs.base_branch
  writes: [worktree_path, worktree_branch]

- id: teardown
  type: worktree
  action: cleanup
  policy: delete_unconditionally  # merge_to_base | leave_for_inspection | delete_unconditionally
```

`action: create` requires `base`. `action: cleanup` requires `policy`. No contract field — writes go directly to `BaseState`.

### `loop`

```yaml
- id: implement-and-test
  type: loop
  loop:
    max_iterations: 5
    until: state.tests_pass  # OR until_bash: "pytest -q" (not both)
    fresh_context: false
    steps: [...]
```

`loop.steps` is a list of the same `Step` types (recursive). Exactly one of `until` or `until_bash` must be non-empty (validated by `LoopBlock`'s `model_validator`; combined use rejected by `LoopExecutor` at run time).

---

## `InputSpec`

```yaml
inputs:
  base_branch:
    type: string             # string | integer | boolean
    required: false
    default: main
    pattern: null            # regex; validated at CLI dispatch time
    enum: null               # list of allowed values
    flag: --base-branch      # explicit CLI flag (default: --<input_name>)
    position: null           # integer; positional arg instead of flag
```

`flag` and `position` are mutually exclusive. Boolean inputs cannot be positional.

---

## `WriteSpec`

```yaml
writes:
  - plan                     # short-form: field="plan", merge=None
  - field: notes
    merge: replace           # long-form: force overwrite (bypasses append)
```

Both forms normalise to `WriteSpec(field=..., merge=...)` at parse time.

---

## Contract inline schema

Inline contracts use a YAML mini-schema compiled to Pydantic at load time:

```yaml
contract:
  summary: string
  count: integer
  active: boolean
  score: number
  items:
    type: list
    of: string
  nested:
    sub_field: string
  status:
    type: string
    enum: [PASS, FAIL]
  priority:
    type: integer
    min: 1
    max: 5
```

Supported types: `string`, `integer`, `boolean`, `number`, `list` (with `of:`), nested objects (a mapping without `type:` is treated as a sub-schema). Constraints: `enum`, `min`/`max` (numeric).

Shared contracts live in `contracts/<name>.yaml` and are referenced as `contract: $contracts/<name>`. The loader resolves them at load time and produces the same Pydantic model.

---

## Load-time validations (in `harness/workflow/loader.py`)

1. **Writes against contract**: every name in a step's `writes:` must exist as a field on the compiled contract.
2. **Writer type consistency**: if multiple steps write the same field name, their contract field annotations must be identical.
3. **Worktree ancestry**: any step with `writes_files: true` must have a `worktree.create` ancestor in the dependency graph (checked across implicit predecessor edges and explicit `depends_on` edges, including inside loop blocks).
4. **Decision actor**: `actor: human` is rejected with a clear "not supported in v1" message.
5. **Writes without contract**: a step with non-empty `writes:` and no `contract:` is rejected (`WorktreeStep` is excluded — its writes are framework-managed).

All failures surface as `WorkflowLoadError` with the original exception preserved on `__cause__`.

---

## Per-node retry configuration

Any step may declare:

```yaml
retry:
  transient:
    attempts: 5              # overrides the global default (3) for this step only
```

Fields not declared in the step's `retry:` block inherit from the global `RetryPolicy`. Currently only `retry.transient.attempts` is exposed.

---

## Notable constraints

- `workflow_name` must be `^[a-z][a-z0-9_-]*$` (lowercase, starts with a letter, allows digits/hyphens/underscores).
- There is no `state_schema:` field; declaring one causes a Pydantic `extra="forbid"` error pointing at the derived-state approach.
- Adding a new workflow requires only a YAML file. No Python changes.
