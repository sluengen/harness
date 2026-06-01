# AI Node — dispatch adapters, contracts, structured output, failure modes

The AI node renders a Jinja2 prompt, compiles the contract to a submit tool schema, dispatches to an agent adapter, and returns the agent's typed result.

---

## Purpose

Wraps one bounded agent call for the duration of a workflow step. The node never sees the agent harness's raw output — it delegates to a dispatch adapter that implements the `Agent` protocol and returns a validated `NodeResult`.

---

## Key data structures

### `Agent` protocol (`harness/dispatch/base.py`)

```python
class Agent(Protocol):
    async def execute(
        self,
        prompt: str,
        contract: type[BaseModel],
        submit_tool_schema: dict[str, Any],
        *,
        allowed_tools: list[str],
        cwd: Path | None,
        timeout_s: int = 600,
        stall_timeout_s: int = 300,
        max_turns: int | None = None,
    ) -> NodeResult[BaseModel]: ...
```

`ResettableAgent` (optional protocol): adds `reset() -> None`. The loop evaluator calls this between iterations of `fresh_context: true` loops.

### `NodeResult`

```python
class NodeResult(BaseModel, Generic[T]):
    contract: T          # typed deliverable — field source for writes:
    attestation: Attestation
    artifacts: Artifacts
```

`attestation.status` is informational only; engine control flow never reads it. `artifacts` is populated by the executor around file-mutation steps.

### `_EmptyContract`

A zero-field Pydantic model used for AI steps that declare `writes: []`. Gives the agent a `submit_<step_id>` tool with no required fields so it can signal completion after file mutations without writing anything to state.

---

## `AINode` behaviour (as-implemented)

### Contract resolution

Precedence: `contract_override` (passed by the executor from `ctx.contracts`) > compiled `type[BaseModel]` on `step.contract` > inline dict (compiled via `compile_inline_contract`) > `$contracts/<name>` string reference (raises `NotImplementedError` — the loader resolves these before the node sees them) > `None` (returns `_EmptyContract`).

### Prompt rendering

Jinja2 `Environment` with `FileSystemLoader(prompts_dir)` and `StrictUndefined`. Scope keys: `state` (the `BaseState` instance), `inputs` (workflow inputs dict), plus all `template_vars` flattened as top-level variables. Declaring `state` or `inputs` in `template_vars` is rejected at render time (reserved scope keys).

### Working directory

`step.cwd` wins (treated as a `Path`); else `state.worktree_path`; else `None`.

### Dispatch

The executor-supplied `Agent.execute` is called with the rendered prompt, compiled contract type, submit tool schema (from `compile_to_tool_schema`), `allowed_tools`, `cwd`, `timeout_s`, `stall_timeout_s`, and `max_turns`.

---

## Dispatch adapters

### `ClaudeAgent` (`harness/dispatch/claude.py`)

Wraps `claude_agent_sdk.query`. The submit tool is exposed as an in-process MCP server named `harness`; the agent sees it as `mcp__harness__submit_<node_id>`. Text deltas between tool calls are accumulated in `self.notes` (reset per call).

**Failure mode detection (five cases):**

| Pattern | Reason | Behaviour |
|---|---|---|
| Agent ends turn without calling submit | `not_called` | Raises `ContractViolation("not_called")` |
| Submit called with placeholder values | `placeholder` | Raises `ContractViolation("placeholder")` |
| Submit called but payload fails Pydantic | `validation_failed` | Raises `ContractViolation("validation_failed")` |
| Submit called twice | warning | First call wins; emits `decision_violation` event; continues |
| Agent never calls submit and stream ends | `not_called` | Same as above |

Placeholder detection: whole-string match against `^(TODO|<.*>|example|placeholder)$` (case-insensitive). Top-level string fields only.

Stall detection: each `__anext__` on the SDK stream is wrapped in `asyncio.wait_for(stall_timeout_s)`. On timeout, raises `AgentStalled(elapsed)`.

### `CodexAgent` (`harness/dispatch/codex.py`)

Runs `codex --full-auto -q [--model <model_id>]` as a subprocess. Prompt delivered via stdin. Output is NDJSON; classified line-by-line from `function_call`, `function_call_output`, `message` event types. Same `ContractViolation` / `AgentStalled` raise semantics as `ClaudeAgent`. `max_turns` is accepted but unused (codex CLI has no equivalent flag).

### `OpencodeAgent` (`harness/dispatch/opencode.py`)

Runs `opencode run --format json [--model <provider>/<model>]` as a subprocess. Prompt via stdin. Output is NDJSON with `tool_use`, `text`, `step_start`/`step_finish` event types. Model flag logic: `provider/model` if both set; `model` alone if only model; `provider/default` if only provider. Same failure-mode and stall semantics as other adapters. `max_turns` accepted but unused.

### `MockAgent` (`harness/dispatch/mock.py`)

Used by default in `Runner` when no agent is injected. Returns a `NodeResult` with a validated instance of the supplied contract, using default field values. Used in tests and for no-AI dry runs.

---

## `ContractViolation` and `AgentStalled`

Both are defined in `harness/dispatch/claude.py` and imported by `CodexAgent` and `OpencodeAgent` — they are spec-level concepts, not SDK-specific.

`ContractViolation` carries a `reason: ViolationReason` (`"not_called"`, `"placeholder"`, `"validation_failed"`).

`AgentStalled` carries `elapsed: float` (seconds since the last SDK event).

The executor's retry layer catches both and applies the contract-violation retry budget (2 attempts by default) with `RetryContext.contract_violation_reason` passed back to the operation.

---

## Notable constraints

- `template_vars` cannot shadow `state` or `inputs` — this is rejected at render time with a clear error.
- A defensive `isinstance(result.contract, contract_cls)` guard runs after dispatch; for `writes: []` steps it is skipped since the empty-contract path never extracts fields.
- Notes accumulation (`self.notes`) is the adapter's responsibility. Routing those notes into `state.notes` is the executor/AINode's concern and is not yet wired in v1.
- The `Artifacts` field on `NodeResult` is populated by the executor, not the node.
