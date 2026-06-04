# Authoring Workflows

A practical guide to writing workflows for harness. Task-oriented and example-heavy. If you want the design rationale ("why does it work this way") read `SPEC.md`; this file covers the *how*.

> **Mental model in one sentence.** A workflow is a YAML file with declared inputs and a list of steps; each step has a `type:` and a `contract:` (the typed shape of its output); the engine derives the run's state schema from the union of all `writes:` declarations across steps.

---

## 1. The minimal workflow

The smallest thing that loads cleanly:

```yaml
name: hello
version: 1

steps:
  - id: say-hi
    type: script
    command: echo "hello"
    contract:
      output: string
    writes: [output]
```

That's a valid workflow. `name` (snake-case), `version` (integer ≥ 1), and `steps` (non-empty list) are the three required workflow-level fields. Each step needs an `id`, a `type:`, a `contract:` (if it writes state), and `writes:` listing which contract fields land in state.

---

## 2. Step types at a glance

| Type | One-liner | Required keys |
|---|---|---|
| `ai` | Call an agent harness with a prompt + contract | `prompt`, `contract` |
| `script` | Run a shell or python script, capture stdout | `command` *or* `script`, `contract` (if state writes) |
| `check` | Evaluate a deterministic boolean expression over state | `expr` |
| `decision` | Gate the workflow on an LLM or human decision | `actor`, plus actor-specific fields |
| `worktree` | Create or clean up an isolated git worktree for the run | `action` (and `base` or `policy`) |
| `loop` | Iterate a block of steps until a state condition is true | `loop:` block |

## Backend compatibility

Not all agent adapters support every AI step feature. The table below shows what v1's `ClaudeAgent` supports vs the v1.5 adapters.

| Feature | `ClaudeAgent` (v1) | `CodexAgent` (v1.5) | `OpencodeAgent` (v1.5) |
|---|---|---|---|
| `submit` tool injection | ✓ | ✗ (not supported) | ✗ (not supported) |
| `cwd:` | ✓ | ✓ | ✓ |
| `max_turns:` | ✓ | ✗ | ✗ |
| `allowed_tools:` | ✓ | ✗ | ✗ |

For production workflows, use `ClaudeAgent`. The v1.5 adapters exist for future use and raise `RuntimeError` in production (no `proc_fn` wired).

Minimal example of each:

```yaml
# ai
- id: investigate
  type: ai
  prompt: prompts/standard/analyze.j2
  template_vars:
    task: "Read app/models.py and explain the User schema"
  contract:
    summary: string
  writes: [summary]
```

Optional `ai` keys: `agent:` (defaults to `claude`), `model:` (defaults to `sonnet`), `allowed_tools:` (defaults to `[Read, Grep, Glob]`; **replaces** the default when set — not additive), `cwd:`, `writes_files:` (default `false`), `stall_timeout_s:` (default `300`), `timeout_s:` (default `600`).

```yaml
# script — bash form (default runtime). `command:` runs the value as bash.
# For multi-line bash use `command: |\n  ...`. For a script file, use
# `script:` + `runtime: bash|python`.
- id: run-tests-bash
  type: script
  command: pytest -x
  contract:
    tests_pass: boolean
  writes: [tests_pass]

# script — python form
- id: fetch-data
  type: script
  runtime: python
  script: scripts/fetch.py
  contract:
    items:
      type: list
      of: string
  writes: [items]
```

```yaml
# check — pure boolean expression over state
- id: gate
  type: check
  expr: state.tests_pass == True
  on_fail: cancel        # or: continue | retry_loop:<loop-id>
```

```yaml
# decision (LLM actor — v1; human actor is v2)
- id: should-proceed
  type: decision
  actor: llm
  prompt: prompts/standard/review.j2
  template_vars:
    criteria: "Is there enough info to plan a fix?"
  contract:
    decision: boolean
    reasoning: string
  on_reject: cancel      # or: continue | retry_loop:<id> | pause_for_human
```

```yaml
# worktree — opt-in isolation, two actions.
# worktree.create writes worktree_path + worktree_branch into BaseState;
# declare them with writes: like any other step. No contract: needed —
# the fields are framework-managed. Downstream nodes reference them via
# $state.worktree_path / $state.worktree_branch.
# worktree.cleanup reads state, mutates the filesystem, writes nothing.
- id: setup
  type: worktree
  action: create
  base: $inputs.base_branch
  writes: [worktree_path, worktree_branch]

- id: teardown
  type: worktree
  action: cleanup
  policy: merge_to_base  # or: leave_for_inspection | delete_unconditionally
```

`merge_to_base` fast-forwards the configured `base:` branch (from the upstream `create`) to the worktree branch — a **local** operation, no remote push required. It assumes the worktree branch already has the commits you want, typically staged by a preceding `script` step (`git add && git commit`).

```yaml
# loop — note: type:loop IS required (the spec table requires it).
# `until:` accepts any Python boolean expression over state. `until: state.x`
# (truthy check) and `until: state.x == True` are both valid.
# `until:` is evaluated *after* each iteration — the body always runs at least once.
# State written inside loop steps persists across iterations — the next
# pass reads what the previous pass wrote.
- id: implement-and-test
  type: loop
  loop:
    max_iterations: 5
    until: state.tests_pass
    steps:
      - id: implement
        type: ai
        prompt: prompts/standard/implement.j2
        allowed_tools: [Read, Write, Edit, Bash]
        cwd: $state.worktree_path
        writes_files: true
        writes: []     # produces files, not state — contract optional
      - id: run-tests
        type: script
        command: pytest -x
        cwd: $state.worktree_path
        contract:
          tests_pass: boolean
        writes: [tests_pass]
```

**Committing inside loops.** An AI step with `writes_files: true` mutates the filesystem but does not commit. If the loop feeds a `worktree.cleanup` step with `policy: merge_to_base`, add an explicit commit step between the loop and cleanup so `merge_to_base` has commits to merge:

```yaml
- id: commit-changes
  type: script
  command: "git -C $state.worktree_path add -A && git -C $state.worktree_path commit -m 'wip'"
  writes: []
```

**Alternative satisfaction predicate — `until_bash:`.** Use when the exit condition is naturally a shell command rather than a Python expression over state (e.g. polling an external endpoint, waiting on a file mtime). Exit 0 satisfies; any non-zero exit means "iterate again". `$state.<field>` is substituted before exec. Declare one of `until:` / `until_bash:`, not both.

```yaml
- id: wait-for-marker
  type: loop
  loop:
    max_iterations: 10
    until_bash: "test -f $state.worktree_path/.ready"
    steps:
      - id: poll
        type: script
        command: 'sleep 1; printf "%s" "{}"'
        writes: []
```

**Retry a loop from a child check — `on_fail: retry_loop:<loop-id>`.** When a `check` inside a loop fails with this `on_fail`, the loop starts another iteration of the named loop. The retry counts against `max_iterations`. Use this when a check ratifies a side-effect that the loop body produces; falling through to `until:` would require pushing the same boolean into state twice.

```yaml
- id: settle
  type: loop
  loop:
    max_iterations: 5
    until: state.settled
    steps:
      - id: tick
        type: script
        command: 'printf "%s" "{\"settled\": false}"'
        contract:
          settled: boolean
        writes: [settled]
      - id: ratify
        type: check
        expr: state.settled
        on_fail: retry_loop:settle  # matches the enclosing loop's `id`
```

---

## 3. Inline contracts — the grammar

Every step that puts data into state declares its output shape with `contract:`. The harness compiles the YAML to a Pydantic model at load time, the agent (for AI nodes) calls a generated tool with that schema, and `writes:` then extracts the named fields into state.

**Four primitive types** — `string`, `integer`, `boolean`, `number`. Plus `list` (with `of:`), and nested objects (a mapping is a sub-schema).

### Example 1 — flat scalars

```yaml
contract:
  status: string
  count: integer
  has_pii: boolean
```

### Example 2 — list of strings, then list of objects

```yaml
contract:
  warnings:
    type: list
    of: string
  findings:
    type: list
    of:
      severity: string
      area: string
      description: string
```

### Example 3 — nested object + constraints

```yaml
contract:
  verdict:
    type: string
    enum: [PASS, FAIL]
  priority:
    type: integer
    min: 1
    max: 5
  release_id:
    type: string
    pattern: "^v[0-9]+\\.[0-9]+\\.[0-9]+$"
  summary:
    type: string
    format: long      # informational; doesn't constrain
```

Supported constraint keys: `enum`, `pattern`, `min`, `max`, `format`. For anything more complex (custom validators, computed fields), hoist the schema to `$contracts/<name>` (see §6).

### Contract is optional when `writes: []`

A step that mutates files but writes nothing to state (typically an AI node inside a loop body) doesn't need a contract:

```yaml
- id: implement
  type: ai
  prompt: prompts/standard/implement.j2
  writes_files: true
  writes: []           # nothing flows to state — contract optional
```

Otherwise: `contract:` is required and `writes:` field names must match the contract's field names exactly.

---

## 4. State and `writes:`

**State is derived, not declared.** You don't write a state-schema file. The harness walks every step's `contract:` and `writes:`, takes the union, and builds the state schema for the run. There's no `state_schema:` field on the workflow — trying to declare one is a load-time error.

### Rules

- For each step, every name in `writes:` must match a field name in that step's `contract:`. Type comes from the contract.
- If two steps write the same field name, they must agree on type. Mismatch is a load-time error.
- `BaseState` (framework-provided) is always present: `run_id`, `workflow_name`, `base_branch`, `worktree_path`, `worktree_branch`, `artifacts_dir`, `started_at`, `notes`.

### Merge semantics by type

When two steps both write the same state field, the merge follows the field's *type*:

| Type | Behaviour |
|---|---|
| `list` | Append |
| Scalar (`string`, `integer`, `boolean`, `number`) | Overwrite |

So a `findings: list[...]` field accumulates across nodes; a `status: string` field reflects the last writer.

### Variable references

Two namespaces inside YAML scalar values:

- `$inputs.X` — caller-provided CLI inputs
- `$state.X` — the live state object (any field from any earlier step's `writes:`)

`$`-substitution happens inside **any YAML scalar string** before the step runs. Concrete list of where substitution applies:

| Where | Step types | Example |
|---|---|---|
| `args:` list entries | `script` | `args: ["--days", "$inputs.lookback"]` |
| `command:` (single-line or multi-line `\|`) | `script` | `command: "ls $state.worktree_path"` |
| `cwd:` | `ai`, `script` | `cwd: $state.worktree_path` |
| `base:` | `worktree` (`create`) | `base: $inputs.base_branch` |
| `template_vars:` *values* | `ai`, `decision` | `template_vars: { task: "$state.plan" }` |

Multi-line `command: |` blocks are a single YAML scalar — `$state.X` and `$inputs.X` are substituted across all lines of the block before bash sees it.

Jinja templates (the `.j2` files referenced by `prompt:`) receive the resolved values as `state`/`inputs` Jinja variables (no `$` prefix needed inside the template body).

```yaml
args:
  - "--since-days"
  - "$inputs.since_days"
  - "--tickets-json"
  - "$state.tickets"
```

Inside Jinja prompt templates the same vars are available as Jinja variables (no `$` prefix):

```jinja
{{ state.tickets }}
{{ inputs.since_days }}
```

#### Safe bash quoting with `$inputs.*` and `$state.*`

Substitution in `args:` replaces the whole token, so quoting is safe:

```yaml
- id: run
  type: script
  command: scripts/deploy.sh
  args: ["$inputs.env", "$state.branch"]
```

**Do not** use `$inputs.*` or `$state.*` inside `command:`. The `command:` string is passed verbatim to `bash -c` — the shell will try to expand `$inputs` as a shell variable (which is empty), not the harness value. Use `args:` for dynamic values:

```yaml
# WRONG — $inputs.env will be empty in bash
- id: bad
  type: script
  command: scripts/deploy.sh $inputs.env

# CORRECT — value is substituted before bash sees it
- id: good
  type: script
  command: scripts/deploy.sh
  args: ["$inputs.env"]
```

`$inputs.*` also works in `until_bash:` (the whole command is preprocessed before shell execution):

```yaml
loop:
  max_iterations: 10
  until_bash: "[ -f $inputs.output_path ]"
```

**Why not argv-style commands?** An earlier design considered replacing the `until_bash:` string with an argv list (e.g. `until_bash: ["test", "-f", "$state.path"]`) to make quoting and argument boundaries explicit. This was deferred: the single-string form is simpler for the common case (polling a file, calling a script), harness preprocessing handles `$state.*`/`$inputs.*` substitution before the shell sees the command, and the quoting pitfalls are documented above. If argv-style becomes necessary (e.g. for values that may contain spaces), a `until_script:` node reference will be a cleaner fit than extending `until_bash:`.

---

## 5. Standard prompts

Four reusable Jinja templates live in `prompts/standard/`. Each accepts a small set of `template_vars` documented in the file's header comment.

| File | Use it for | Required `template_vars` | Optional `template_vars` |
|---|---|---|---|
| `analyze.j2` | Read-only investigation; produce a structured summary | `task` | `tools_hint` |
| `implement.j2` | Mutate code/files in the worktree, optionally with tests | `task` | `constraints` |
| `review.j2` | Evaluate against criteria; produce a verdict + findings | `criteria` | `severity_levels` (default `[HIGH, MEDIUM, LOW]`) |
| `summarize.j2` | Summarise a subject; produce structured output | `subject` | `length` (default `"concise"`) |

Reference one in an AI step:

```yaml
- id: review-pr
  type: ai
  prompt: prompts/standard/review.j2
  template_vars:
    criteria: "Correctness, test coverage, regression risk"
  contract:
    status:
      type: string
      enum: [PASS, FAIL]
    issues:
      type: list
      of: string
  writes: [status, issues]
```

If a standard prompt doesn't fit, write your own `.j2` in `prompts/<workflow>/<name>.j2`. Keep custom prompts as the exception — the standard library covers most cases via `template_vars`.

---

## 6. Sharing schemas with `$contracts/<name>`

A schema used by multiple workflows can be hoisted into `contracts/<name>.yaml` and referenced by name:

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
- id: review
  type: ai
  prompt: prompts/standard/review.j2
  template_vars:
    criteria: "..."
  contract: $contracts/review-verdict
  writes: [status, issues, blocking]
```

The harness resolves the reference at load time and compiles the same Pydantic model it would for an inline contract.

---

## 7. Worked example: release-notes

A three-step workflow that pulls closed Linear tickets, summarises them, and writes a release-notes markdown file. This is the canonical example used for the 10-minute ergonomics test.

```yaml
# workflows/release-notes.yaml
name: release-notes
version: 1
description: Pull recent Linear tickets and summarise into release notes markdown.

inputs:
  since_days:
    type: integer
    default: 7
  output_path:
    type: string
    default: ""

steps:
  - id: fetch-tickets
    type: script
    runtime: python
    script: scripts/fetch_recent_linear_tickets.py
    args: ["--since-days", "$inputs.since_days"]
    contract:
      tickets:
        type: list
        of:
          id: string
          title: string
          labels:
            type: list
            of: string
          kind: string
    writes: [tickets]

  - id: summarise
    type: ai
    agent: claude
    model: sonnet
    prompt: prompts/standard/summarize.j2
    template_vars:
      subject: "Linear tickets closed in the last $inputs.since_days days: $state.tickets"
      length: "release-notes markdown grouped by type (Features, Bug fixes, Improvements)"
    allowed_tools: [Read]
    contract:
      release_notes: string
    writes: [release_notes]

  - id: write-file
    type: script
    runtime: python
    script: scripts/write_release_notes.py
    args: ["--run-id", "$state.run_id", "--output-path", "$inputs.output_path"]
    contract:
      output_path: string
    writes: [output_path]
```

What's going on:

- **Inputs.** Two CLI inputs with defaults. The caller can override either: `harness run release-notes --since-days=14 --output-path=/tmp/notes.md`.
- **Step 1 (script).** Deterministic data fetch — runs a Python script that hits the Linear API. Contract declares the shape of one ticket; writes the list into `state.tickets`. The engine never asks an LLM to fetch data — that's Principle 6 (`SPEC.md` §1.6).
- **Step 2 (ai).** Summarises the tickets using the standard prompt with parameterised `template_vars`. The agent's contract has one field (`release_notes: string`) which becomes a tool the agent calls to submit its output. `allowed_tools: [Read]` keeps the agent bounded — no Write/Bash/Edit.
- **Step 3 (script).** Writes the summarised string to disk. Returns the output path so a caller can find it via `harness status <run-id> --json`.

**Derived state** (you don't write this; the engine builds it):

```python
class ReleaseNotesState(BaseState):
    tickets: list[Ticket] = []
    release_notes: str | None = None
    output_path: str | None = None
```

---

## 8. Running a workflow

```bash
harness run release-notes --since-days=7 --output-path=/tmp/notes.md
```

Each workflow's CLI surface is generated from its `inputs:` block (see SPEC §11 — *Per-workflow inputs*). `harness run <workflow> --help` prints the flags + positionals for that specific workflow.

Common flags every workflow supports:

```bash
harness status <run-id>             # current status + state snapshot
harness logs <run-id> [--follow]    # tail the log
harness events <run-id> [--type tool_called]   # filter events
```

---

## 9. Validating a workflow

Two ways:

```bash
# Static validation — does the YAML load + cross-validate?
harness validate workflows/release-notes.yaml
```

```python
# Programmatic, from any test or script
from harness.workflow.loader import load_workflow
loaded = load_workflow("workflows/release-notes.yaml")
print(loaded.workflow)        # the Workflow Pydantic model
print(loaded.contracts)       # compiled Pydantic models per step
print(loaded.state_schema)    # derived state class
```

The load step runs every cross-validation: `writes:` matches `contract:` field names, type consistency across writers, worktree-rule (any `writes_files: true` step has a `worktree.create` ancestor), `actor: human` rejected as v2-reserved, etc. If it loads, the workflow's shape is sound.

---

## 10. Common pitfalls

Real ones, in roughly the order people hit them:

| Pitfall | Fix |
|---|---|
| Loop step omits `type: loop` | The spec table requires `type:` on every step including loops. Add `type: loop`. |
| `writes:` field name doesn't match `contract:` field name | They must agree exactly. `writes: [tickets]` requires the contract to have a `tickets:` field. |
| Two steps write the same state field with different types | One says `tickets: string`, another says `tickets: list of object`. Pick one, or rename one of the fields. |
| AI step with `writes_files: true` but no worktree | Load-time error. Add a `worktree.create` step upstream. |
| Trying to declare `state_schema:` on the workflow | There is no such field — state is derived. Remove it. |
| `decision` step with `actor: human` | v2-reserved; loads but errors at run-time. Use `actor: llm` or wait for v2. |
| Inline contract for a list of objects written as `list[object]` | YAML syntax is `type: list` + `of: { field: type, ... }`. See §3 example 2. |
| AI step has `prompt:` pointing at a file that doesn't exist | The loader resolves prompt paths relative to the workflow file's directory. Check the path or move the prompt. |
| Forgot to fill in `template_vars` that a standard prompt requires | Read the `.j2` file's header comment — required vars are listed. `analyze.j2` needs `task`, `summarize.j2` needs `subject`, etc. |
| Bash output silently empty during local verification | The Claude Code Bash tool sometimes auto-backgrounds long-running commands. Redirect to `/tmp/<file>.txt` and `tail`. See `skills/verification-before-completion.md`. |
| Want "do X on PASS, Y on FAIL" branching from a single `check` | The grammar has no multi-branch routing. `check.on_fail:` is single-direction (`cancel`/`continue`/`retry_loop:<id>`). Canonical workaround: gate with `on_fail: cancel`, put only the success-path cleanup downstream; the workflow halts before cleanup on failure. For richer branching, split into two workflows. |
| Worktree left on disk after `on_fail: cancel` | When a workflow cancels, any `worktree.cleanup` step downstream of the cancel point never runs. Run `harness worktrees cleanup` periodically to remove stale worktrees, or add a dedicated cleanup step before the gate if immediate cleanup is needed on the failure path. |

---

## 11. When to read SPEC.md

This guide is enough to *write* a workflow. Read SPEC.md when you need to:

- Understand *why* a constraint exists (e.g., why every node needs a contract — §4.4 failure-mode catalogue)
- Decide whether a new step type should be a node type or a script (§4.1–§4.6)
- Tune retry behaviour, decide between human and LLM actors, design a new shared contract (§4.4, §4.5, §5)
- Audit the engine for the events it emits or the state it persists (§12)

For everything else — writing workflows, picking step types, declaring contracts — this guide should be self-contained.
