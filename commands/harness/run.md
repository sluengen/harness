<!-- guidance:harness-run@0.1.0 -->
# /harness run

Usage: `/harness run <ISSUE-ID>` or `/harness run <ISSUE-ID> --codex-only`.

Drive `start → design → implement → review → (fix → review)* → close`. The verbs own state; the orchestrating agent implements in the worktree and branches on structured outputs.

## Prerequisites and engine mode

Default mode uses the `~/bin/harness` Docker wrapper. Configure the selected tracker credential per the `tracker` skill; Claude auth comes from the wrapper. `--codex-only` is native-only until #314: install `harness`, run `codex login`, and confirm `harness doctor --engine codex`. Every design/review call in that mode carries `--engine codex`; review also carries `--no-fallback`, so it must never invoke Claude.

## Step 1 — start

```bash
harness start <ISSUE-ID> --attended
```

An interactive run declares `--attended`; a routine must omit it. Attendance skips only the wall-clock breaker and uses `loop.attended_idle_minutes` for reclamation. The review-cycle ceiling always applies. Parse `StartOutput`, retain `run_id`, read the ticket title/description, and work only in `worktree_path`. Use `--resume` for a reclaimed ticket with preserved WIP.

**Step 1.5 — `design`.**

```bash
harness design --run-id <run_id>
harness design --run-id <run_id> --engine codex   # --codex-only
```

Save `DesignOutput.design_markdown` inside the repo for review. The event binds `design_hash` and `grounded_sha`. A resumed, authenticated predecessor design may be adopted with `inherited_from`; no engine runs and no comment is posted. Otherwise run design once as one top-level command. Avoid nested-background invocation: never combine an inner bare `&` with a host background flag. An empty redirected output means not finished yet. Wait instead of relaunching. If concurrent calls occur, `concurrent_prior_at` warns that the last invocation to finish became authoritative; run one clean design and implement that output. This recovery leaves the idempotent re-run contract unchanged.

Assurance is snapshotted at start. `complex` requires a usable design. `simple`, unlabelled/conflicting/unknown assurance, and upgraded `trivial` return `status: "not_required"` with empty design and require no `--design-file`. A failed design records `status="failed"` and exits 3: this is degrade-and-record. On work that does not require design, the failed attempt still satisfies review enforcement and implementation may proceed; complex review refuses `no_design` or `design_not_usable`, so retry design once and ask the operator if it remains unusable. A design file outside the mounted workspace is refused as `design_file_outside_workspace`.

**Step 2 — implement and verify.**

Follow the entry process doc: read the spec and sibling pattern, write the failing test first, implement the smallest scoped change, and run `CONTEXT.md`'s lint, type-check, and verify gate. Commit green increments. The harness review engine is read-only, so this orchestrating path authors the as-built record before review, includes it in the candidate, verifies it, and commits it. Final-evidence ordering is load-bearing: a post-pass record commit produces `stale_review`.

After every green increment, and before a long design/gate stretch, preserve WIP:

```bash
harness checkpoint --run-id <run_id>
```

Checkpoint pushes only the run branch and records an event. Failure loses durability, not the run; report it and continue.

**Step 3 — `review`.**

Run the verify gate yourself, capture its output, then call:

```bash
harness review --run-id <run_id> --gate-exit <code> --gate-log <path>
harness review --run-id <run_id> --gate-exit <code> --gate-log <path> --design-file <repo-path>
harness review --run-id <run_id> --engine codex --no-fallback   # --codex-only
```

The verb never runs the repo gate. It records evidence and binds the verdict to HEAD. `review-discipline` owns final-evidence ordering: record reality before the certifying verdict. A matching design file enriches review; unreadable/hash-mismatched content warns and drops, while a path outside the workspace refuses. A resumed byte-identical HEAD may inherit a prior green-gated pass with `inherited_from`; dirty/different HEAD, a red supplied gate, or this run's missing required design cannot inherit.

Pre-engine refusals run in root-cause order:

- required design absent/unusable → exit 5, `no_design` / `design_not_usable`;
- design path outside workspace → exit 5, `design_file_outside_workspace`;
- configured verify gate but no evidence → exit 5, `no_gate_evidence`;
- red gate → exit 5, `gate_failed`, no verdict;
- worktree beyond `loop.untracked_file_limit` → exit 5, `polluted_worktree`; clean the named untracked entries and keep gate environments outside the worktree;
- missing ledger → exit 2, `no_ledger`; return to the repo/worktree start reported or pass `--repo`/`--db`.

The reviewer may propose bounded mutations. The probe stage applies at most `loop.probe_max_entries` in throwaway trees and combines its result with the read-only verdict; `0` disables it. It never mutates the candidate.

Default review uses Claude with `loop.review_model`; `--model` overrides that alias. Host-only `--engine codex` falls back once on Codex usage exhaustion unless `--no-fallback` (ADR 0013 records the corrected seccomp reason). Other Codex failures do not fall back. **A review that produced no verdict is not a `fail`.** A protocol failure exits 3 as `no_submit` or `malformed_submit`; retry once, not until it works. Retry one `engine_timeout` at the same HEAD. A further same-tree attempt is refused before spending with exit 4, `reason=repeat_engine_timeout`; do not raise the timeout.

Act on `verdict`:

- **`fail`** — fix the root cause test-first and review the new HEAD. `review-discipline` solely owns the cycle policy. `convergence_check_required: true` requires a written judgment before the next cycle. `cycles_exhausted: true` stops automation: `harness checkpoint --run-id <run_id>` then `harness defer <TICKET> --needs operator`. Never cancel/resume on the automated path. A subsequent call is refused with `reason=review_cycle_ceiling`; an unattended wall-clock refusal uses `reason=wall_clock_budget` and the configured `loop.wall_clock_budget_minutes`.
- **`defer`** — file the genuinely out-of-scope finding through `/harness ingest`, then close the shippable candidate.
- **`pass`** — close.

### Human-authorized breaker recovery

Plain `--resume` returns an existing open run unchanged: same `run_id`, `started_at`, and spent budgets. After an explicit human decision, recover once in order:

1. `harness checkpoint --run-id <run_id>`.
2. Post the handoff comment described below.
3. `harness cancel <run_id>` to clear the open row without touching ticket state or git.
4. `harness start <TICKET> --resume --attended` to open a new budget window.

Cancel + resume resets both breakers; automation may never loop this recipe.

**Step 4 — `close`.**

```bash
harness close <ISSUE-ID> --run-id <run_id>
```

Close requires a start and a pass whose `reviewed_sha` equals current HEAD, then integrates in a detached throwaway worktree, pushes, confirms the tracker Done response, and closes the ledger row.

**Run it once. Exit 0 → done; non-zero → escalate.** The verb absorbs transient failures with a bounded retry. By the time a non-zero exit arrives, retrying has failed. **Do not re-run `close` in a loop**, and do not hand-roll the merge, push, or transition. Escalate with the `reason` and `run_id`; absorbed retries remain in the ledger.

There is no `dirty_base_checkout` refusal: `close` uses a throwaway worktree. A merge conflict with `origin/<base>` or a rejected non-fast-forward push is an exit-1 error carrying `reason=merge_conflict` or `reason=push_rejected`; neither is a gate refusal or carries `merged`. `push_rejected` has already exhausted the verb's bounded retry and needs escalation. `merge_conflict` needs the run branch to merge `origin/<base>`, resolve, commit, verify, review, and close again.

Gate refusals: `no_run` → start; `dirty_worktree` → commit/discard and re-review; `no_passing_review` → review; `stale_review` → re-review current HEAD; `no_gate_evidence` → verify and review. `merge_conflict` requires merging `origin/<base>` into the run branch, resolving, committing, re-verifying and re-reviewing. Base movement and `push_rejected` do not justify a rebase; close handles base integration and retries push races. Never raw-merge, force-push, or transition the ticket around the gate. Ticket transition failures report `merged: true` with `ticket_transition_failed` or `ticket_transition_unconfirmed`; escalate because the merge already landed.

#### Base movement needs no rebase

`close` fetches `origin/<base>` and integrates the run in a detached throwaway worktree. A run **must not** rebase merely because the base moved: rebasing rewrites every SHA and invalidates the HEAD-bound passing review. `push_rejected` is handled by close's bounded retry; if it remains, escalate rather than rebase or retry by hand.

#### Proactive context-rollover handoff

Re-orient after compaction from `harness status <run_id>`, ledger events, `git status`, `git log`, and the diff.

For a live session nearing its context limit:

1. `harness checkpoint --run-id <run_id>`.
2. Through `tracker.comment`, post `Context-rollover handoff by \`harness checkpoint\`` and `Preserved branch: <branch>`; leave In Progress with no `reclaimed` label.
3. Run `harness cancel <run_id>` after the comment, then a fresh session runs `harness start <TICKET> --resume` (plus `--attended` only if attended) and re-orients from the recovered branch.

**This is distinct from death-keyed reclamation**. A dead run is reverted to Todo, gets the `reclaimed` label and `Reclaimed by \`harness reclaim\`` marker, and resumes through `fetch_resume_branch`. The proactive handoff stays In Progress with no label and uses `fetch_handoff_branch`. Distinct tracker states and marker strings prevent collision.
