# Script Node — subprocess wrapper, variable substitution, contract override

> **Superseded 2026-06-11** — this spec describes the **retired deterministic workflow engine**, deleted in CAL-574 (proposal [`harness-as-tool`](../proposals/harness-as-tool.md), decision D1). The harness no longer walks a YAML workflow: a single Claude session orchestrates *and* implements, calling the `start` / `review` / `close` verbs over the SQLite ledger. Current references: [`SPEC.md`](../../SPEC.md) §1–2, [`run-ledger.md`](../features/run-ledger.md), [`commands/harness.md`](../../commands/harness.md). Kept for historical reference only.

The script node runs a bash or Python subprocess, captures stdout/stderr/exit code, and returns a typed result. Non-zero exit codes raise immediately.

---

## Purpose

Provides deterministic side effects and data-fetch steps in a workflow: call an external API, run tests, write a file. All output is captured; no streaming.

---

## Key data structures

### `ScriptOutput`

Default contract for a script step (used when no `contract_override` is supplied):

```python
class ScriptOutput(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
```

### `ScriptNodeError`

Raised on: non-zero exit code, timeout, missing `$state.X` / `$inputs.X` reference in `args`, malformed JSON when `contract_override` is set, Pydantic validation failure when `contract_override` is set.

---

## Behaviour (as-implemented)

### Variable substitution in `args`

Each entry in `step.args` is checked for `$state.<field>` and `$inputs.<key>` prefixes:

- `$state.<field>` — looks up the field on the current state object via `getattr`. Raises `ScriptNodeError` on missing attribute or empty field name.
- `$inputs.<key>` — looks up the key in the inputs dict. Raises `ScriptNodeError` on missing key or empty key name.
- Anything else — passed through unchanged.

Substitution is a whole-arg operation only (e.g. `$state.worktree_branch` is supported, but `prefix-$state.field` embedded mid-string is not). The substituted value is `str(value)`.

### Command dispatch

Two forms are mutually exclusive (enforced by `ScriptStep` model validator):

- `command: <shell string>` — runs as `bash -c <cmd> harness-script <args...>` (bash runtime) or `python -c <cmd> <args...>` (python runtime). The `harness-script` name as `$0` keeps author positionals starting at `$1`.
- `script: <path>` — runs as `bash <path> <args...>` or `python <path> <args...>`.

Default runtime is `bash`. Python runtime uses the project's `.venv/bin/python` if it exists, else `sys.executable`.

### Working directory

`step.cwd` wins (treated as a `Path`); else `state.worktree_path`; else `None`.

### Output capture

Both stdout and stderr are captured via `asyncio.subprocess.PIPE`. Each stream is capped at 1 MiB (UTF-8 encoded bytes); output exceeding the cap is truncated and a `\n…[truncated]` marker is appended. Default wall-clock timeout is 300 seconds; the child process is killed on timeout before the `ScriptNodeError` is raised.

### Contract override

When the executor passes `contract_override` (from `ctx.contracts[step.id]`), the script node:

1. Parses stdout as JSON.
2. Validates the parsed dict against the override Pydantic model.
3. Returns `NodeResult[override]` instead of `NodeResult[ScriptOutput]`.

JSON parse errors and Pydantic validation errors both raise `ScriptNodeError`, which includes the first 200 characters of stdout for debugging. Without `contract_override`, the node returns `NodeResult[ScriptOutput]` with the raw stdout/stderr/exit_code.

---

## Step schema (from `harness/workflow/schema.py`)

```python
class ScriptStep(_BaseStep):
    type: Literal["script"]
    command: str | None = None     # inline shell/python string
    script: str | None = None      # path to script file
    runtime: Literal["bash", "python"] = "bash"
    args: list[str] = []           # supports $state.X and $inputs.X
    contract: ContractSpec | None = None
    cwd: str | None = None
    writes_files: bool = False
```

Exactly one of `command` or `script` must be set (validated at parse time).

---

## Notable constraints

- Non-zero exit code always raises. There is no `on_fail: continue` for script steps in v1.
- Stdout streaming to the event log is not implemented in v1; only the final captured output is stored.
- Python runtime selection tries `.venv/bin/python` first, then `sys.executable`, then PATH `python` — this ensures the subprocess uses the same interpreter as the harness itself when the venv is available.
- The `contract_override` path is additive over the original `ScriptOutput` shape; steps that don't declare a contract still return `ScriptOutput` (all three fields always populated).
