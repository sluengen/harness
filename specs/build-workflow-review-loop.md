# Build Workflow — Review Loop Design

**Status:** Approved for implementation  
**Scope:** `workflows/build.yaml`, `prompts/build/`, `harness/engine/loop.py`, `harness/workflow/schema.py`

---

## Problem

The current build workflow treats any reviewer verdict of PASS as "ship it", regardless of
whether the reviewer flagged findings. Findings are recorded in state and surfaced in the
summary, but nothing acts on them. The result: known issues get shipped, a human creates a
follow-up ticket, and a future session spends tokens re-loading context to fix things that
should have been fixed in the original session.

---

## Design

### Verdict semantics

Expand the review contract's verdict enum from `PASS | FAIL` to `PASS | FAIL | DEFER`.

| Verdict | Meaning | What the workflow does |
|---------|---------|------------------------|
| `PASS`  | No findings. | Commit and push. |
| `FAIL`  | Has findings the implementer can fix in this session. | Retry the implement step with findings as context, up to `max_iterations`. |
| `DEFER` | Has a finding that is genuinely out of scope for this ticket — requires a new spec, a new session, or architectural redesign. The current code is otherwise shippable. | Create a Linear child ticket with the deferred brief, then commit and push. |

**DEFER threshold:** The reviewer should only use DEFER when the finding cannot be resolved
without work that is clearly beyond this ticket's boundary — e.g. "this function needs to be
redesigned, and doing it right requires a new spec." If the reviewer can describe the fix in
a sentence and the implementer could write it in this session, it is FAIL, not DEFER.
DEFER is for genuinely architectural or cross-cutting concerns. It is rare.

**Any finding = FAIL.** The reviewer does not grade by severity before deciding the verdict.
If there is a finding — any finding — and it is fixable in-session, the verdict is FAIL. The
implementer fixes it and the loop retries. Fixing issues once, in context, costs less than a
separate session. MEDIUM and LOW findings are just as disqualifying as HIGH.

---

### Workflow structure

The implement–review cycle becomes a `loop` step. Post-loop, DEFER and EXHAUSTED cases are
handled before the commit path.

```
fetch-ticket
     │
     ▼
┌─── fix-loop (max_iterations: 3) ────────────────────────────────┐
│  implement  ──►  review  ──►  gate-retry                        │
│                               │  verdict == FAIL → back to top  │
│                               │  verdict != FAIL → exit loop    │
└─────────────────────────────────────────────────────────────────┘
     │ (exit: verdict is PASS, DEFER, or loop exhausted)
     ▼
notify-exhausted         (no-op if not exhausted; posts Linear comment + sets Todo if exhausted)
     │
gate-exhausted           (cancel if still FAIL — exhaustion path ends here)
     │
handle-deferred          (no-op if PASS; creates Linear child ticket if DEFER)
     │
commit-and-push
     │
teardown
     │
close-task
```

---

### Engine change required — `LoopBlock.on_exhaust`

`LoopExhausted` currently fails the workflow immediately. To enable post-loop exhaustion
handling, `LoopBlock` gains a new field:

```python
on_exhaust: Literal["cancel", "continue"] = "cancel"
```

- `cancel` (default): existing behaviour — `LoopExhausted` propagates and the workflow
  fails. Backwards-compatible.
- `continue`: when `max_iterations` is reached without `until` becoming true, the executor
  does not raise. Execution falls through to the steps after the loop as if the loop exited
  normally. The run state at that point reflects the last completed iteration (so
  `state.verdict` will still be `"FAIL"`). The post-loop steps detect this and route
  accordingly.

`LoopExecutor.execute()` change: after the `raise LoopExhausted(...)` call, check
`loop.on_exhaust` and return normally if it is `"continue"`.

---

### Review contract additions

```yaml
contract:
  verdict:
    type: string
    enum: [PASS, FAIL, DEFER]
  issues:
    type: list
    of: string
  commit_message: string      # required for PASS and DEFER; empty string on FAIL
  deferred_brief: string      # one-line Linear ticket title; empty string unless DEFER
writes: [verdict, issues, commit_message, deferred_brief]
```

`deferred_brief` is the title of the child ticket to create on the DEFER path. The reviewer
writes one line: what the deferred work is, framed as a ticket title.

---

### Implement prompt — retry context

On the first iteration, `state.issues` is an empty list. On retry iterations it contains the
reviewer's findings from the previous pass. The implement prompt renders both cases:

```jinja
{% if state.issues %}
## Previous review — issues to fix

This is a retry. The previous implementation was rejected. Fix **all** of the following
before re-submitting:

{% for issue in state.issues %}
- {{ issue }}
{% endfor %}

Do not re-submit until every item above is addressed and verified.

---
{% endif %}

## Ticket

**{{ state.ticket_title }}**
...
```

---

### Review prompt — verdict rubric

Replace the current "tag each finding HIGH/MEDIUM/LOW and call submit" rubric with:

```
## Verdict

Choose exactly one:

- **PASS** — no findings. The implementation is correct, tested, and focused.
- **FAIL** — one or more findings that should be fixed before shipping. Use this for
  any finding you can describe in a sentence and the implementer could address in this
  session. Severity does not matter — a LOW finding that is fixable is still FAIL.
- **DEFER** — a finding that is genuinely out of scope for this ticket: requires
  architectural redesign, a new spec, or work clearly beyond this ticket's boundary.
  The current code is shippable as-is; the deferred item is tracked separately.
  Use DEFER sparingly. If in doubt, use FAIL.

On FAIL: populate `issues` with each finding (file:line, description). Leave
`commit_message` empty and `deferred_brief` empty.

On PASS: `issues` is empty. Write `commit_message`.

On DEFER: populate `issues` with the deferred finding. Write `commit_message` (the
current code ships). Write `deferred_brief` as a one-line ticket title for the new
Linear issue.
```

---

### Workflow YAML sketch

```yaml
name: build
version: 3
...

steps:
  - id: setup
    ...

  - id: set-in-progress
    ...

  - id: fetch-ticket
    ...

  - id: fix-loop
    type: loop
    loop:
      max_iterations: 3
      until: state.verdict != "FAIL"
      on_exhaust: continue            # NEW engine field
      steps:

        - id: implement
          type: ai
          ...                          # prompt reads state.issues for retry context

        - id: review
          type: ai
          ...
          contract:
            verdict: {type: string, enum: [PASS, FAIL, DEFER]}
            issues: {type: list, of: string}
            commit_message: string
            deferred_brief: string
          writes: [verdict, issues, commit_message, deferred_brief]

        - id: gate-retry
          type: check
          expr: state.verdict != "FAIL"
          on_fail: retry_loop:fix-loop

  - id: notify-exhausted
    type: script
    cwd: "."
    command: |
      if [ "$1" = "FAIL" ]; then
        # Post comment to Linear issue with accumulated issues and branch name
        BODY=$(printf '{"query":"mutation{issueUpdate(id:\"%s\",input:{stateId:\"%s\"}){success}}"}' "$2" "$3")
        # ... Linear comment mutation ...
        printf '{"exhausted": true}'
      else
        printf '{"exhausted": false}'
      fi
    args: ["$state.verdict", "$inputs.linear_id", "<todo-state-id>"]
    # (in practice, fetch the Todo state ID dynamically as set-in-progress does)
    writes: []

  - id: gate-exhausted
    type: check
    expr: state.verdict != "FAIL"
    on_fail: cancel

  - id: handle-deferred
    type: script
    cwd: "."
    command: |
      if [ "$1" = "DEFER" ]; then
        # Create child Linear ticket with deferred_brief as title
        # ... Linear GraphQL createIssue mutation ...
      fi
      printf '{}'
    args: ["$state.verdict", "$state.deferred_brief", "$inputs.linear_id"]
    writes: []

  - id: commit-and-push
    ...

  - id: teardown
    ...

  - id: close-task
    ...
```

---

### notify-exhausted detail

When exhaustion fires (verdict still `FAIL` after `max_iterations`):

1. Post a Linear comment on the ticket listing the final `issues` set and the branch name
   (`state.worktree_branch`) so the pushed work-in-progress is findable.
2. Set the ticket state back to **Todo** (not Backlog — it has been partially worked and
   needs human triage before the next attempt).

The branch is left pushed on the remote. The next session can inspect it, decide whether to
continue from it or start fresh.

---

## What does NOT change

- `commit-and-push` is unchanged — it runs only if the loop exits with PASS or DEFER.
- `teardown` is unchanged — worktree is always cleaned up on the normal and DEFER paths.
- `close-task` is unchanged — ticket is closed only on the commit path (PASS or DEFER).
- On exhaustion, teardown and close-task are skipped (the `cancel` from `gate-exhausted`
  stops execution). The worktree and branch are left for inspection; Linear is updated by
  `notify-exhausted` before the cancel.

---

## Implementation order

1. **Engine** — add `on_exhaust: Literal["cancel", "continue"] = "cancel"` to `LoopBlock`
   and update `LoopExecutor.execute()` to honour it.

2. **Review contract** — add `DEFER` to the enum, add `deferred_brief: string` field,
   update the loader's contract compiler to handle it.

3. **Prompts** — update `review.j2` (verdict rubric) and `implement.j2` (retry context).

4. **Workflow** — replace the flat implement–review–gate with the loop structure above,
   add `notify-exhausted`, `gate-exhausted`, and `handle-deferred` steps.

5. **Tests** — unit tests for `on_exhaust: continue` in `LoopExecutor`; integration test
   for the FAIL→retry→PASS path and the DEFER→child-ticket path.
