# CLI — command surface, dynamic subcommands, exit codes, JSON output

The CLI is the public contract. Stable flags, stable exit codes, stable JSON output. Implemented with Typer (top-level) and Click (dynamic per-workflow subcommands).

---

## Purpose

Provides a human- and machine-friendly interface for running workflows, querying run state, and managing worktrees. The CLI is the only entry point to the engine; the `Runner` is never called directly except in tests.

---

## Command surface

```
harness start <ticket>    [--base <branch>] [--repo <path>] [--db <path>] [--json/--no-json]
harness run <workflow> [--base <branch>] [--quiet] [--workflows-dir <dir>] [<workflow-inputs>...]
harness cancel <run-id>   [--json] [--db <path>]
harness status <run-id>   [--json] [--db <path>]
harness logs <run-id>     [--follow] [--node <id>] [--db <path>]
harness events <run-id>   [--type <event_type>] [--after-id <integer>] [--json] [--db <path>]
harness validate <workflow.yaml>
harness version
harness worktrees list    [--json] [--repo-root <path>]
harness worktrees cleanup [--age <duration>] [--merged] [--repo-root <path>]
harness decisions list    [--json] [--db <path>]
harness decision show <run-id>    [--json] [--db <path>]
harness decision approve <run-id> [--comment <text>] [--workflows-dir <dir>] [--json]
harness decision reject <run-id>  [--comment <text>] [--workflows-dir <dir>] [--json]
```

---

## `harness start`

Opens a run for a Linear ticket. Intended for machine consumption — JSON output is the default and the only supported format.

```
harness start <ticket> [--base <branch>] [--repo <path>] [--db <path>] [--json/--no-json]
```

**Flags:**

| Flag | Default | Description |
|---|---|---|
| `--base` | `dev` | Base branch for the worktree. |
| `--repo` | `.` (CWD) | Repo root for git worktree operations. |
| `--db` | `<repo>/.harness/harness.db` | Path to the ledger database. Defaults to `DEFAULT_DB_PATH` relative to `--repo`. |
| `--json/--no-json` | `--json` | Emit machine-readable JSON. Always on by default. |

**Operation order (all-or-nothing):**

1. Validate `LINEAR_API_KEY` is set.
2. Fetch the Linear issue via `issue(id: <ticket>)`.
3. Check for an existing open run (refuse duplicate).
4. Create the git worktree at `.worktrees/harness/<run_id>/` on branch `harness/<run_id>`.
5. Insert an `open` row into `runs` (see `specs/state-store.md`).
6. Transition the ticket to In Progress (last — the only non-local side effect). On failure, delete the DB row and remove the worktree.

**JSON output schema (`StartOutput`):**

```json
{
  "run_id": "<26-char ULID>",
  "ticket": {
    "id": "<Linear UUID>",
    "identifier": "<e.g. CAL-570>",
    "title": "<ticket title>",
    "description": "<ticket description, capped at 4096 chars>",
    "url": "<https://linear.app/...>"
  },
  "worktree_path": "<absolute path to worktree>",
  "worktree_branch": "harness/<run_id>",
  "base_branch": "<base branch name>"
}
```

`description` is capped at 4096 characters and suffixed with `... [truncated]` if the original exceeded that limit.

If an open run already exists for the ticket, the command exits 0 and returns the existing run's `StartOutput` rather than opening a second run.

**Exit codes:**

| Code | Meaning |
|---|---|
| 0 | Run opened (or existing run returned). |
| 1 | Unexpected error (worktree creation failed, DB error, etc.). |
| 2 | Invocation error (missing ticket, Linear unreachable, transition failed). |

---

## `harness run`

Locates `<workflows_dir>/<workflow>.yaml`, loads it, then dynamically builds a Click command from the workflow's `inputs:` block. The outer Typer command holds the workflow name and `--workflows-dir`/`--quiet`/`--base` flags; the inner Click command receives the workflow-specific flags.

Per-workflow flags are generated from the `inputs:` block:
- `flag:` inputs → `click.Option`
- `position:` inputs → `click.Argument`
- Boolean inputs → `is_flag=True` option
- `enum:` → `click.Choice`

A reserved `--base` / `_base_branch__` flag is added to every dynamic subcommand (default: `main`). The kwarg name is namespaced to avoid collision with a workflow input also called `base`.

`pattern:` validation is applied in the callback via `re.fullmatch` before the runner is invoked.

On workflow not found: exits 2. On load error: exits 2. On runner return value: propagates that exit code.

The default `ClaudeAgent` is constructed at dispatch time via `_build_runner`. `--quiet` suppresses per-node progress output.

---

## `harness cancel`

Delivers a SIGTERM to the process running the workflow identified by `run-id`.
The process PID is recorded in the `runs.pid` column at run-start (H-2-006).

Errors (exit 2):
- Run not found in the DB.
- Run exists but status is not `running` (already completed, failed, cancelled, or paused).
- Run was started before H-2-006 and has no recorded PID (`runs.pid IS NULL`).
- The recorded PID belongs to a process that is no longer alive (stale PID).
- Insufficient permission to signal the process.

On success (exit 0): prints a confirmation line (or `--json` object) and exits.
The running `harness run` process handles the SIGTERM by converting it to
`KeyboardInterrupt`, which flows through the normal cancellation path:
`workflow_failed` with `reason='cancelled'`, `status='cancelled'`, exit 130.

`--json` output:
- Success: `{"run_id": "<id>", "outcome": "cancelled"}`
- Failure: `{"error": "<message>"}`

---

## `harness status`

Reads the `runs` row for `run_id` from `.harness/harness.db`. Exits 2 if the run does not exist.

Default (human) output: `run_id`, `workflow_name`, `workflow_version`, `status`, `started_at`, `completed_at`, `exit_code` as key-value pairs.

`--json` output: full row as a single JSON object. `state_json` and `inputs_json` are parsed and re-emitted as `state` and `inputs` (parsed objects, not strings). The following enriched fields are included for Hermes consumption (see `specs/hermes-orchestration.md` §Observability requirements):

| Field | Type | Source |
|---|---|---|
| `current_node` | `string?` | `node_id` from the latest `node_started` event |
| `failure_reason` | `string?` | `data.reason` from the latest `workflow_failed` event |
| `failure_retryable` | `bool?` | derived from `failure_reason`; `null` if no failure |
| `artifact_paths` | `object?` | non-null artifact fields from `state` (`worktree_path`, `worktree_branch`, `pr_url`, `report_path`) |
| `agent_session_ids` | `list[str]?` | unique `session_id` values from `tool_called` event data |

`failure_retryable` derivation: `false` for `ContractViolation*`, `loop_exhausted`, `cancelled`, `rejected`; `true` for all other reasons (transient errors).

---

## `harness logs`

Prints a compact timeline of events for a run: `<timestamp> <event_type> [node=<id>] <data>`.

`--node <id>` filters to events for a single node. `--follow` polls for new events every 500ms and exits when the run's status leaves `{pending, running}`. Ctrl-C exits 130 (Typer/Click default).

---

## `harness events`

Same event fetcher as `logs` but without `--follow`. `--type <event_type>` filters to a single event type. `--json` emits one JSON object per event, one per line (useful for `jq` piping).

`--after-id <integer>` returns only events with `id > <integer>`. This enables efficient incremental polling: callers store the last-seen event `id` and pass it on the next call to receive only new events, without re-reading the full event log. Default is `0` (all events).

---

## `harness validate`

Loads the workflow YAML via `load_workflow`. On success: prints `OK <name> v<version>` and exits 0. On failure: prints the `WorkflowLoadError` message to stderr and exits 2.

---

## `harness worktrees list`

Walks `<repo_root>/.worktrees/harness/` for child directories. For each, resolves the branch via `git worktree list --porcelain`. Output: `<run_id>\t<last_modified>\t<branch>\t<path>`. `--json` emits the full list as a JSON array.

## `harness worktrees cleanup`

Filters discovered worktrees by `--age <duration>` (directory mtime older than the given duration) and/or `--merged` (branch fully merged into `main` or `master`). Without filters, all worktrees are kept. Removal via `git worktree remove --force`. Exits 1 if any removal fails.

Duration format: `30m`, `12h`, `7d` (minutes, hours, days). `s` (seconds) is also accepted.

---

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Workflow completed / read command succeeded |
| 1 | Workflow failed (execution error — loop exhausted, check failed, etc.) |
| 2 | Invocation error (bad flags, unknown run-id, workflow YAML invalid) |
| 3 | Contract violation (LLM output failed validation after retry exhaustion) |
| 4 | Paused awaiting decision (v2 — reserved) |
| 130 | SIGINT / SIGTERM / KeyboardInterrupt (running workflow cancelled) |

---

## Notable constraints

- `--json` on read commands uses `json.dumps(..., default=str)` for non-serialisable values.
- `decisions list`, `decision show`, `decision approve`, and `decision reject` are all live. `approve` and `reject` load the workflow YAML, emit `decision_received`, then resume execution of remaining steps (approve or on_reject=continue) or call `_finalise_failure` (on_reject=cancel). `--workflows-dir` overrides the default `workflows/` directory.
- `--db` defaults to `Path.cwd() / ".harness/harness.db"` for all read commands. The `run` command uses the `Runner`'s `DEFAULT_DB_PATH` (relative `.harness/harness.db`).
- Progress output (per-node `node_started`/`node_completed` lines) goes to stderr via `ProgressReporter`; `--quiet` suppresses it.
