# Engine Loop — LoopExecutor, LoopExhausted, RetryLoopRequested

The loop block evaluator runs a `LoopStep`'s child steps repeatedly until a satisfaction predicate becomes true or `max_iterations` is reached.

---

## Purpose

Supports iterative patterns in workflows (implement-then-test, retry-until-pass) without requiring workflow authors to write Python. The evaluator sits between the runner (which delegates `LoopStep` dispatch to it) and the executor (which handles each child step).

---

## Key data structures

### `LoopBlock` (from `harness/workflow/schema.py`)

```python
class LoopBlock(BaseModel):
    max_iterations: int           # must be > 0
    until: str | None             # Python expression over state; coerced to bool
    until_bash: str | None        # shell command; exit 0 = satisfied
    fresh_context: bool = False   # call agent.reset() between iterations
    steps: list[Step]             # child steps, executed in declared order
```

Exactly one of `until` or `until_bash` must be non-empty. Both declared simultaneously is rejected at run time by `LoopExecutor._reject_combined_until_fields`.

### `LoopExhausted`

Raised when `max_iterations` is reached without the satisfaction predicate becoming true. The runner maps this to a `workflow_failed` event and exit code 1.

### `RetryLoopRequested`

Raised by the runner's check adapter when a `CheckStep` inside or after a loop evaluates `False` with `on_fail: retry_loop:<id>`. Carries `loop_id` and `requested_by`.

---

## Behaviour (as-implemented)

### Iteration lifecycle

1. For each iteration (1-based, up to `max_iterations`):
   a. If `fresh_context=True` and this is not the first iteration, call `agent.reset()` if the agent implements `ResettableAgent`.
   b. Execute each child step via the shared `Executor`. Child steps get the same retry policy, contract registry, and event log as top-level steps.
   c. If a child raises `RetryLoopRequested` with a matching `loop_id`, emit a `loop_iteration` event with `trigger="retry_loop_requested"` and start the next iteration.
   d. After the child steps complete, read state and evaluate the satisfaction predicate.
   e. Emit `loop_iteration` event with `iteration`, `max_iterations`, `until_satisfied`, `trigger="until_evaluated"`.
   f. If satisfied, return.
2. If all iterations are exhausted without satisfaction, raise `LoopExhausted`.

### Satisfaction predicate — `until:`

`until` is a Python boolean expression evaluated via `parse_and_eval` from `harness/nodes/_state_expr.py`. Unlike `CheckNode`, the loop evaluator applies `bool()` coercion — a state field that is `None` (the default for unwritten derived scalars) reads as `False` (not yet satisfied) without forcing every workflow to pre-initialise its signal field.

### Satisfaction predicate — `until_bash:`

The command runs via `asyncio.create_subprocess_exec(["bash", "-c", cmd, "harness-until-bash"])` — not `shell=True`. `$state.<field>` and `$inputs.<key>` references are substituted as strings before exec. Missing references raise `ValueError`. Exit 0 means satisfied; any non-zero exit or timeout means not-yet-satisfied.

A 300-second wall-clock cap (`_UNTIL_BASH_TIMEOUT_S`) prevents a hung command from stalling the loop. On timeout the `loop_iteration` event carries `data.until_bash_timeout=True`.

### `retry_loop:<id>` rewind

`RetryLoopRequested` is the engine's signalling mechanism, not a real error. The closest enclosing `LoopExecutor` catches it:

- If `exc.loop_id` matches this loop's `step.id`, break out of the current iteration's child steps, emit a `loop_iteration` event with `trigger="retry_loop_requested"`, and start the next iteration. The retry counts against the same `max_iterations` budget.
- If `exc.loop_id` does not match, re-raise so an outer loop (or the runner's generic failure handler) can resolve it. A `retry_loop:<id>` naming a loop not on the active stack surfaces as a workflow failure naming the offending id.

### `fresh_context`

`agent.reset()` is called between iterations (not before iteration 1). Only adapters that implement the optional `ResettableAgent` protocol are reset; the loop uses `isinstance` to probe and silently no-ops on adapters that don't implement it.

---

## Notable constraints

- Iteration numbering is 1-based throughout (event log, failure messages).
- Child errors propagate immediately after the executor's retry budget is exhausted; the `LoopExecutor` does not add a separate retry layer.
- `until=""` is treated as absent (legacy compatibility) so workflows pairing `until: ""` with `until_bash:` keep loading.
- `$inputs.X` substitution inside `until_bash:` is not yet wired to the actual run inputs; the implementation passes an empty dict and any `$inputs.X` reference raises `ValueError`.
