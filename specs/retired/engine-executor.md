# Engine Executor — per-node execution, contract validation, state writes, snapshots

> **Superseded 2026-06-11** — this spec describes the **retired deterministic workflow engine**, deleted in CAL-574 (proposal [`harness-as-tool`](../proposals/harness-as-tool.md), decision D1). The harness no longer walks a YAML workflow: a single Claude session orchestrates *and* implements, calling the `start` / `review` / `close` verbs over the SQLite ledger. Current references: [`SPEC.md`](../../SPEC.md) §1–2, [`state-store.md`](../state-store.md), [`commands/harness.md`](../../commands/harness.md). Kept for historical reference only.

The `Executor` wraps a single step end-to-end: resolve dependencies, dispatch to the node, validate the result, apply writes to state, snapshot, emit lifecycle events.

---

## Purpose

One `Executor` instance is shared across the entire workflow run. It is the only place that writes state (via `update_state`) and the only place that emits `node_started` / `node_completed` / `node_failed` events.

---

## Key data structures

### `Context` (frozen dataclass)

```python
@dataclass(frozen=True)
class Context:
    run_id: str
    db_path: Path
    contracts: dict[str, type[BaseModel]]   # step.id → compiled Pydantic type
    state_schema: type[BaseState]           # derived at load time
    nodes: dict[str, NodeRunner]            # step.type → async callable
    workflow_name: str = ""
    progress_sink: Callable | None = None
```

Built once by the runner and passed to every `Executor.execute` call.

### `NodeRunner`

```python
NodeRunner = Callable[[Step, BaseState, Context], Awaitable[NodeResult[BaseModel]]]
```

The uniform call shape every node adapter exposes. Each concrete node class has its own signature; the runner builds thin closures that conform to this shape.

### `DependencyNotSatisfied`

Raised when a `depends_on` field is absent from or `None` in the current state.

### `ContractMismatch`

Raised for three conditions: no contract registered for a step that has `writes:`, the node returned an instance of the wrong contract type, or a name in `writes:` does not exist on the contract.

---

## Behaviour (as-implemented)

### Execution sequence for one step

1. Read current state from the DB.
2. Check `depends_on`: every named field must exist on state and be non-`None`.
3. Resolve the contract type from `ctx.contracts[step.id]`. For `WorktreeStep`, returns `None` (framework-managed writes skip the contract registry).
4. Resolve the `NodeRunner` from `ctx.nodes[step.type]`.
5. Emit `node_started`.
6. Call `run_with_retry(op, policy, event_sink)` where `op` invokes the runner. Retry events are buffered in `retry_events`.
7. On any exception: flush buffered retry events, emit `node_failed` with `reason=type(exc).__name__` and `message=str(exc)`, re-raise.
8. Flush buffered retry events on success.
9. Validate the result's contract type with `isinstance`. For `WorktreeStep`, the effective type is `type(result.contract)`.
10. Validate `writes:` field names exist on the contract.
11. Call `update_state` with only the declared `writes:` fields and any per-write `merge` overrides.
12. Call `write_snapshot` to record the post-step state.
13. Emit `node_completed` with `duration_ms`.
14. Return the `NodeResult`.

### Per-step retry policy

Each step may declare a `retry:` block in YAML. The executor merges only the declared fields over the global `RetryPolicy` via `_policy_for_step`. Currently only `retry.transient.attempts` is exposed; absent fields inherit the global default.

### State writes

Only the declared `writes:` fields propagate to state. The `WriteSpec` short-form (a plain string) and long-form (`{field: name, merge: replace}`) are both supported. `merge: replace` forces unconditional overwrite regardless of field type (most useful for lists, which normally append).

### Snapshots

After every successful step completion, `write_snapshot` appends an immutable row to `run_snapshots` keyed by `run_id`, `node_id`, and an auto-incrementing `seq`. The v2 resume machinery reads the highest-`seq` snapshot instead of the mutable `runs.state_json` column.

### Event invariant

Every `node_started` is paired with exactly one terminal event (`node_completed` or `node_failed`). Post-dispatch failures (contract validation, write application) emit `node_failed` before re-raising.

---

## Retry policy (three layers)

Implemented in `harness/engine/retry.py` and used by `run_with_retry`:

| Layer | Trigger | Default |
|---|---|---|
| Transient | `OSError`, `anthropic.APIConnectionError`, `httpx.TimeoutException`, `anthropic.APIStatusError` with status >= 500 | 3 attempts, exponential backoff (1s base, 30s cap) |
| Contract violation | `ContractViolation` or `AgentStalled` | 2 attempts, no backoff |
| Logic failure | Any other exception | Re-raised immediately, no retry |

Layers do not compound: a transient retry that then hits a `ContractViolation` does not get the contract-violation budget on top. Each layer tracks its own attempt counter.

Each retry emits a `retry_attempted` event to the executor's sink before the next attempt.

---

## Notable constraints

- The executor is stateless except for the base retry policy set at construction.
- The runner (not the executor) handles loop blocks — the executor never sees `LoopStep`.
- `WorktreeStep` bypasses the contract registry because `worktree_path` and `worktree_branch` map directly onto `BaseState` fields without going through the normal `contract: → writes:` path.
