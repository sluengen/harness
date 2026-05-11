# Review: H-021 (CAL-285) — Loop block evaluator

**Verdict:** PASS

## Acceptance criteria

CAL-285 collapses to four behavioural ACs ("iterate until until: true or max_iterations; fresh_context flag; emit loop_iteration events; exhaustion → exit 1"). The dev split these into eleven concrete tests AC1..AC11 against the loop module's public seam plus runner integration. Each maps to impl + test:

- [✓] **AC1 — iterate child steps in declared order, exit on `until:` true** — implemented at `harness/engine/loop.py:117-157` (iteration loop, state read, `until:` evaluation, early return). Tested by `tests/unit/test_engine_loop.py::test_loop_runs_until_condition_true` (full runner E2E proving the post-loop step ran) and `::test_loop_state_propagates_between_iterations` (iteration N's writes seen by iteration N+1).
- [✓] **AC2 — `max_iterations` exhaustion raises LoopExhausted** — implemented at `harness/engine/loop.py:159-162`. Tested by `tests/unit/test_engine_loop.py::test_loop_exhaustion_raises_loop_exhausted` (raw exception shape: step id + iteration count in message).
- [✓] **AC3 — exhaustion → workflow_failed + exit 1** — runner mapping at `harness/engine/runner.py:323-337` (catch-all `BaseException` arm). Tested by `tests/unit/test_engine_loop.py::test_loop_exhaustion_emits_workflow_failed_with_loop_exhausted_reason` (exit==1, `workflow_failed.data.reason` carries `LoopExhausted` marker).
- [✓] **AC4 — `loop_iteration` events emitted per iteration** — implemented at `harness/engine/loop.py:145-154` (one emit per iteration after children + until-eval, payload `{iteration, max_iterations, until_satisfied}`, `node_id=step.id` on the row). Tested by `tests/unit/test_engine_loop.py::test_loop_emits_loop_iteration_per_iteration` (count, sequential 1-based indices).
- [✓] **AC5 — state propagates between iterations** — relies on existing `Executor.execute → update_state` and `read_state` at `harness/engine/loop.py:140-142`. Tested by `tests/unit/test_engine_loop.py::test_loop_state_propagates_between_iterations` (counter-driven workflow: iteration 1 writes `flipped=false`, iteration 2 sees counter > 1 and writes `flipped=true`, loop exits).
- [✓] **AC6 — `fresh_context: true` resets agent between iterations** — implemented at `harness/engine/loop.py:124-129` with the optional `ResettableAgent` protocol (`harness/dispatch/base.py:53-64`). Tested by `tests/unit/test_engine_loop.py::test_loop_fresh_context_resets_agent` (3 iterations → 2 reset calls; reset is *between*, not before iteration 1).
- [✓] **AC7 — `until_bash:` alone raises NotImplementedError** — implemented at `harness/engine/loop.py:181-186`. Tested by `tests/unit/test_engine_loop.py::test_loop_until_bash_alone_raises_not_implemented` (runner-level: exit 1, failure data names `until_bash`).
- [✓] **AC8 — both `until` and `until_bash` raise ValueError (ambiguous)** — implemented at `harness/engine/loop.py:175-180`. Tested by `tests/unit/test_engine_loop.py::test_loop_both_until_and_until_bash_rejected`.
- [✓] **AC9 — child error propagates immediately, no further iterations** — implicit at `harness/engine/loop.py:135-136` (the loop doesn't catch executor exceptions). Tested by `tests/unit/test_engine_loop.py::test_loop_child_error_propagates_immediately` (script exits 7; at most one `loop_iteration` event; failure reason is not loop_exhausted).
- [✓] **AC10 — `retry_loop:<id>` on CheckNode still raises LoopNotImplemented** — implemented at `harness/engine/runner.py:574-578` (check adapter). Tested by `tests/unit/test_engine_loop.py::test_check_retry_loop_still_raises_loop_not_implemented`.
- [✓] **AC11 — `LoopNotImplemented` export remains usable** — at `harness/engine/runner.py:91-100`. Tested by `tests/unit/test_engine_loop.py::test_loop_not_implemented_still_exported` and `tests/unit/test_engine_runner.py::test_ac9_loop_not_implemented_still_exported`.
- [✓] **AC9-runner — runner dispatches LoopStep to LoopExecutor** — at `harness/engine/runner.py:284-300` and the retirement of `_reject_loop_steps`. Tested by `tests/unit/test_engine_runner.py::test_ac9_loop_workflow_runs_via_loop_executor` (exit 0, one runs row, one `loop_iteration` event).

## Verification

- ruff: All checks passed!
- mypy: Success: no issues found in 40 source files
- pytest: 533 passed in 40.14s (no skips, no failures)

## Findings

### CRITICAL
- (none)

### HIGH
- (none)

### MEDIUM
- (none)

### LOW

- **`tests/unit/test_engine_loop.py`** — no direct test for the loop wrapper propagating a `StateExpressionError` raised by `until:` (e.g. missing-attribute or disallowed-AST-node). The underlying evaluator is well-tested via `tests/unit/test_node_check.py` AC10–AC13 and the loop's `execute()` method has no error-handling that could swallow it, so coverage is *transitive*. Adding a one-line `pytest.raises(StateExpressionError)` test specifically for the loop wrapper would close the loop on the public seam. Carry-forward — out of scope for the binary AC set; not material to merge.
- **`harness/engine/loop.py:151`** — the `loop_iteration` data payload includes `iteration / max_iterations / until_satisfied`. `step.id` lives on the event row's `node_id` column (correct), but operators reading just the `data_json` blob in isolation would miss the loop name. The runner-level `_fetch_events` query in tests does pull `node_id`, so this is purely a "if you query data_json directly without node_id you lose context" concern. Carry-forward — not worth a fix in this PR; the row schema is the right place for `node_id`.

## Notes

**TDD shape is clean.** `git log --oneline origin/main..HEAD` is `test(RED) → feat(GREEN) → feat(wire-in)`. The RED commit (642 lines of pure tests, imports fail by design) genuinely fails before GREEN lands; the wire-in commit only touches the runner + its tests. No "tests at the end" anti-pattern.

**Scope discipline is tight.** Nine files touched, three of them tests:
- `harness/engine/loop.py` (+187, new module body — the evaluator)
- `harness/nodes/_state_expr.py` (+265, new shared module)
- `harness/nodes/check.py` (-207, extracted into _state_expr; thin wrapper remains with `CheckNodeError = StateExpressionError` alias preserving the public API)
- `harness/dispatch/{base,claude,mock}.py` (+42 total, adding the optional `ResettableAgent` protocol + `reset()` on the two concrete agents)
- `harness/engine/runner.py` (+31/-42, retiring `_reject_loop_steps`, wiring LoopExecutor)
- Three test files updated/added.

No "while I was there" edits. The `_state_expr.py` extraction is *necessary*, not stylistic: the loop genuinely needs the same AST allow-list as CheckNode, and duplicating the 200-line walker would be the worse alternative. The `CheckNodeError = StateExpressionError` alias keeps every existing call site working without disturbing tests.

**Design calls all defensible and documented in the code itself:**

- 1-based iteration numbering — explicit comment at `harness/engine/loop.py:25-28`, asserted in `test_loop_emits_loop_iteration_per_iteration` (`indices == [1, 2]`).
- `bool()` coercion for `until:` vs CheckNode's strict-bool — explicit comment at `harness/engine/loop.py:30-36` explaining the rationale (state field starts as None → reads naturally as "not yet satisfied" without forcing default-init).
- `ResettableAgent` as separate optional Protocol — explicit rationale at `harness/dispatch/base.py:13-20` ("keeping reset() off the core Agent protocol means existing structural-typing tests keep passing").
- `until_bash` raises NotImplementedError; both raises ValueError — explicit comment at `harness/engine/loop.py:38-42`, two distinct exception classes name the misconfiguration.
- `retry_loop:<id>` from CheckNode still raises `LoopNotImplemented` — explicit deferral at `harness/engine/runner.py:91-100` with a doc string update saying "the top-level loop evaluator is now wired in, but the retry_loop:<id> integration on the check node is a separate ticket."
- Shared state-expression evaluator extracted to `harness/nodes/_state_expr.py`; CheckNode slimmed to a 100-line wrapper. Module docstring at `_state_expr.py:1-36` explains the two public seams (`parse_and_eval` raw / `evaluate_bool_strict` typed) and the historic alias.

**State propagation verified directly, not by trust.** `test_loop_state_propagates_between_iterations` runs a counter-based workflow where iteration 2 writes `flipped=true` only after iteration 1 has run and the side-effect counter has ticked. The final state assertion (`state["flipped"] is True`) and the exactly-two iterations assertion together prove the data path end-to-end.

**Edge cases I checked:**
- `until_bash="true"` + `until=""` → empty until is falsy → branch 2 raises NotImplementedError (`_reject_until_bash_combinations` checks `loop.until_bash is not None and loop.until` — both truthy). Test `test_loop_until_bash_alone_raises_not_implemented` covers this exact shape.
- Child raises during iteration 3 of 5 → `execute()` doesn't catch, exception propagates to runner's catch-all → exit 1. Test `test_loop_child_error_propagates_immediately` proves it (uses iteration 1 for simplicity; the no-catch design means iteration N is equivalent).
- `max_iterations=1` and body has 5 children → all 5 run once, until evaluates, LoopExhausted raised if false. This is the same code path as the general case; the iteration boundary is *the children list*, not individual children. Implicitly covered by AC1/AC2's correctness.
- `until:` references non-existent state field → `parse_and_eval` raises StateExpressionError, propagates to runner → exit 1. Not directly tested for the loop seam (LOW finding above), covered transitively by CheckNode tests sharing the same evaluator.

**`loop_iteration` event payload is sufficient for hung-loop debugging:** `node_id` (loop step id) + `iteration` + `max_iterations` + `until_satisfied`. An operator can see "loop 'implement-and-test' iteration 4/5, until still false" and act.

Recommend PASS as-is. The two LOW findings are carry-forward — neither blocks merge nor justifies a same-PR fix on already-touched files (the missing-test is genuinely out of scope for the AC set; the event-payload nit reflects a row-schema design that's correct as it stands).
