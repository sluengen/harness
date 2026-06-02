# CLI — command surface, dynamic subcommands, exit codes, JSON output

The CLI is the public contract. Stable flags, stable exit codes, stable JSON output. Implemented with Typer (top-level) and Click (dynamic per-workflow subcommands).

---

## Purpose

Provides a human- and machine-friendly interface for running workflows, querying run state, and managing worktrees. The CLI is the only entry point to the engine; the `Runner` is never called directly except in tests.

---

## Command surface

```
harness run <workflow> [--base <branch>] [--quiet] [--workflows-dir <dir>] [<workflow-inputs>...]
harness status <run-id>   [--json] [--db <path>]
harness logs <run-id>     [--follow] [--node <id>] [--db <path>]
harness events <run-id>   [--type <event_type>] [--json] [--db <path>]
harness validate <workflow.yaml>
harness version
harness worktrees list    [--json] [--repo-root <path>]
harness worktrees cleanup [--age <duration>] [--merged] [--repo-root <path>]
harness decisions list    [--json] [--db <path>]
harness decision show <run-id>    [--json] [--db <path>]
harness decision approve <run-id> [--comment <text>] [--json]   (v2-reserved)
harness decision reject <run-id>  [--comment <text>] [--json]   (v2-reserved)
```

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

## `harness status`

Reads the `runs` row for `run_id` from `.harness/harness.db`. Exits 2 if the run does not exist.

Default (human) output: `run_id`, `workflow_name`, `workflow_version`, `status`, `started_at`, `completed_at`, `exit_code` as key-value pairs.

`--json` output: full row as a single JSON object. `state_json` and `inputs_json` are parsed and re-emitted as `state` and `inputs` (parsed objects, not strings).

---

## `harness logs`

Prints a compact timeline of events for a run: `<timestamp> <event_type> [node=<id>] <data>`.

`--node <id>` filters to events for a single node. `--follow` polls for new events every 500ms and exits when the run's status leaves `{pending, running}`. Ctrl-C exits 130 (Typer/Click default).

---

## `harness events`

Same event fetcher as `logs` but without `--follow`. `--type <event_type>` filters to a single event type. `--json` emits one JSON object per event, one per line (useful for `jq` piping).

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
| 130 | SIGINT / KeyboardInterrupt |

---

## Notable constraints

- `--json` on read commands uses `json.dumps(..., default=str)` for non-serialisable values.
- `decisions list` and `decision show` are live. `decision approve` / `decision reject` remain v2-reserved stubs (exit 2 with "deferred to v2").
- `--db` defaults to `Path.cwd() / ".harness/harness.db"` for all read commands. The `run` command uses the `Runner`'s `DEFAULT_DB_PATH` (relative `.harness/harness.db`).
- Progress output (per-node `node_started`/`node_completed` lines) goes to stderr via `ProgressReporter`; `--quiet` suppresses it.
