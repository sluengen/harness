---
feature: verb-model
status: implemented
last_updated: 2026-06-14
linear: [CAL-570, CAL-574, CAL-586, CAL-661]
---

# Verb model — start / review / close

> The three audited verbs an orchestrating agent calls to drive a ticket from open to merged, with review enforced as a gate before anything lands.

## Behaviour

The harness is **not** a pipeline that drives agents. A single Claude session orchestrates *and* implements a ticket, shelling out to three one-shot, ledger-backed verbs — `start`, `review`, `close` — over the [run ledger](run-ledger.md). The agent owns *what gets built and how*; the verbs own *the durable record and the gate* (decision D1, [`specs/architecture-principles.md`](../architecture-principles.md)). The lifecycle of one run is `start → implement → review → (fix → review)* → close`.

### `start` — open a run

`harness start <ticket>` validates the ticket, opens the run, and hands back the worktree the agent will build in.

#### Scenario: a clean open

- GIVEN a Linear ticket that has no other `open` run
- WHEN the agent runs `harness start <ticket>`
- THEN the verb fetches and canonicalises the ticket, generates a ULID `run_id`, creates an isolated git worktree off the base branch (default `dev`, see [worktree lifecycle](worktree-lifecycle.md)), inserts the `open` `runs` ledger row, and **transitions the ticket to In Progress last**
- AND it emits a `StartOutput` JSON object (`run_id`, ticket context, `worktree_path`, `worktree_branch`, `base_branch`)

The Linear transition is the only non-local side effect, and it runs **last**: if the worktree creation or the ledger insert fails, nothing has touched Linear. The rollback ordering is locked by `test_cli_start.py::test_worktree_failure_leaves_no_db_row_and_no_transition` and `::test_db_failure_removes_worktree_and_no_transition`. The open run is recorded as the `runs` row, not as an event.

#### Scenario: a ticket that already has an open run

- GIVEN a ticket that already has an `open` run
- WHEN the agent runs `harness start <ticket>` again
- THEN `start` resolves the existing open run (keyed on the canonical Linear identifier) and **returns it successfully** (exit 0) — it does not create a second worktree or row, and does not error (`harness/cli/start.py`, step 4: `if existing is not None: return existing`)

The partial unique index `idx_runs_ticket_open` is the database-level backstop for the concurrent-race path: if two `start` calls both pass the existence check, the index refuses the second insert and that loser cleans up its worktree and surfaces the run that beat it (at most one `open` run per ticket).

### `review` — record a verdict bound to the reviewed SHA

`harness review [--run-id <id>] [--engine claude|codex]` runs the selected review engine (`--engine`, **default `claude`**; CAL-701) against the worktree's current HEAD and records a verdict **bound to the exact SHA reviewed** — the load-bearing detail behind decision D2: the `close` gate refuses a pass whose SHA ≠ HEAD, so a stale pass cannot be reused. Each engine is a **read-only CLI subprocess** (`claude -p --permission-mode plan` or `codex exec --sandbox read-only`) emitting the same `SUBMIT:` contract — never the Agent SDK (see the "Review engine" principle in `architecture-principles.md`).

#### Scenario: a review pass

- GIVEN an open run whose worktree HEAD holds committed work
- WHEN the agent runs `harness review`
- THEN the verb resolves the current run (the `status='open'` run whose `worktree_path` equals `--repo`, or the run named by `--run-id`), captures `git rev-parse HEAD` as `reviewed_sha`, invokes the selected engine with the review prompt on stdin, scans stdout for the first `SUBMIT: <json>` line, and appends a `review` event carrying `{ run_id, reviewed_sha, verdict, issues, engine, created_at }` (and optional `commit_message` / `deferred_brief`)
- AND it prints **only** the bounded verdict (`verdict`, `issues`, `reviewed_sha`, `run_id`, `engine`) — the engine's full reasoning stays inside the verb (context economy)

A recorded `fail` is still a *successful* review (exit 0): deciding what to do with a verdict is the agent's job, not the verb's. A missing, malformed, or unknown-verdict `SUBMIT` line is recorded as `verdict='fail'` with the sentinel issue `"reviewer emitted no valid SUBMIT line"` — the verb never raises on a bad reviewer, it records the failure.

The agent acts on the verdict:

- `fail` → fix the root cause in the worktree, commit, and **re-run `review`** (the `(fix → review)*` loop). Each review binds to the new HEAD.
- `defer` → the implementation is shippable, but the review surfaced a genuinely out-of-scope finding; file a follow-up for it. Note the close gate opens **only** on a `verdict=pass` (`harness/cli/close.py` queries `verdict='pass'`; a run with only a `defer` is refused `no_passing_review`), so to close you still need a passing review bound to HEAD — obtain one before closing.
- `pass` → proceed to close.

### `close` — enforce the gate, then merge

`harness close <ticket> --run-id <id>` enforces the gate, integrates the current `origin/<base>`, merges the already-committed HEAD to the base branch, pushes, transitions the ticket to Done, and finalizes the run.

#### Scenario: the gate is satisfied

- GIVEN an open run with a clean worktree and a `verdict=pass` whose `reviewed_sha` equals HEAD
- WHEN the agent runs `harness close <ticket> --run-id <id>`
- THEN the verb fetches and fast-forwards the local base to `origin/<base>`, merges (`git merge --no-ff`) the run branch into the base, pushes the base, transitions the ticket to Done, flips the run to `status=closed`, and emits `CloseOutput` (`run_id`, `ticket`, `reviewed_sha`, `merged`, `ticket_done`, `status`)

#### Scenario: the base advanced during the run

- GIVEN an open run that passed review, and `origin/<base>` has advanced since `start` with non-conflicting work (a concurrent run landed a ticket)
- WHEN the agent runs `harness close <ticket> --run-id <id>`
- THEN the verb fetches and fast-forwards the local base to `origin/<base>` **before** merging, so the push lands rather than being rejected non-fast-forward (CAL-777); the HEAD-bound gate is preserved — the reviewed SHA is the merge's second parent, so only the reviewed commit's content rides in
- AND GIVEN instead the run branch conflicts with what landed on `origin/<base>`, the verb aborts the merge and exits 1 with a clear message (not a raw git conflict dump), leaving the run open and resumable — rebase the run branch on the updated base, re-review, and close again

#### Scenario: a gate refusal

- GIVEN an open run that does not satisfy the gate
- WHEN the agent runs `harness close`
- THEN the verb exits 2 with exactly one structured `reason`: `no_run` (no `start` row), `dirty_worktree` (uncommitted edits — never reviewed), `no_passing_review` (no `verdict=pass` on record), or `stale_review` (a pass exists but HEAD moved after it)

`close` does **not** auto-commit. A dirty worktree is refused outright, because uncommitted edits are not in HEAD and so were never reviewed (`stale_review` catches a commit *after* review; only the clean-tree check catches an edit *without* committing — CAL-586, locked by `test_cli_close.py::test_dirty_worktree_refused_when_uncommitted_edits`). A gate refusal is the gate doing its job and is never worked around — the verb never bypasses its own gate.

### Routing discipline

The ledger is a complete audit trail only if nothing hand-rolls a `git merge` / `push` or a Linear mutation for the run lifecycle. Every git/ticket state transition routes through a verb; `close` validates against the ledger as a backstop (decision D5). The `/harness run` skill ([`commands/harness.md`](../../commands/harness.md)) forbids out-of-band mutation.

### Triggers

One execution model, **two triggers** that produce an identical execution path: a human (`/harness run <ticket>`) or Hermes (the autonomous trigger slot — deferred; the launcher/trigger scaffolding was removed in CAL-712, design archived at [`hermes-orchestration.md`](../retired/hermes-orchestration.md)). A trigger launches a per-session Claude runtime; each verb runs as a one-shot container *outside* that runtime, exactly as `~/bin/harness` is a `docker run`.

## Interface surface

The verbs are part of the CLI surface; their flags, exit codes, and JSON shapes are documented in [cli-surface.md](cli-surface.md), and the agent-facing contract is [`commands/harness.md`](../../commands/harness.md). The verb implementations live in `harness/cli/start.py`, `harness/cli/review.py`, `harness/cli/close.py`; the emitted CLI JSON is locked by `test_verb_contract_locked.py`.

## Known limitations

- The orchestration *between* verbs is deliberately not reproducible: it varies with the agent, which buys full context retention and graceful degradation to manual driving on a verb failure (decision D1). Reproducibility applies to the verbs, not the end-to-end run.
- A run can be abandoned without merging via `harness cancel` (close-without-merge); see [cli-surface.md](cli-surface.md).
- A run whose orchestrator died mid-flight is recovered via `harness reclaim` — it reverts the stranded Linear ticket to Todo (so dependents unblock) and reuses `cancel`'s ledger transaction to clear the `open` row, while preserving the worktree/branch. See [run-ledger.md](run-ledger.md) and the accepted proposal [`stale-run-reclamation`](../proposals/stale-run-reclamation.md).

## Decisions

The cross-cutting decisions that shaped the verb model — D1 (orchestration inversion), D2 (the reviewed-SHA gate), D5 (routing discipline) — are recorded once in [`specs/architecture-principles.md`](../architecture-principles.md) and referenced from here, not duplicated.

## Cross-references

- [run-ledger.md](run-ledger.md) — the SQLite ledger the verbs read and write
- [worktree-lifecycle.md](worktree-lifecycle.md) — the isolated worktree `start` creates and `close` merges
- [cli-surface.md](cli-surface.md) — the full command surface, flags, exit codes, JSON
- [`specs/architecture-principles.md`](../architecture-principles.md) — the orchestration-inversion decision record
- [`specs/proposals/harness-as-tool.md`](../proposals/harness-as-tool.md) — the accepted model
