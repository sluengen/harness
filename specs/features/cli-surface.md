---
feature: cli-surface
status: implemented
last_updated: 2026-07-17
linear: [CAL-583, CAL-603, CAL-661, CAL-738, CAL-739, CAL-1113, CAL-1114, CAL-1115, CAL-1116]
---

# CLI surface — the fixed verb contract

> A fixed set of hand-written commands — audited verbs, read-only inspection, and ops — with stable flags, exit codes, and JSON output, invoked identically by a human and by Hermes.

## Behaviour

The Typer app (`harness/cli/__init__.py`) is the public contract. The surface is **fixed**: there is no per-workflow dynamic subcommand generation (an engine-era idea, retired). Each command is a hand-written Typer command with a stable flag set; adding behaviour means adding or changing a command, not loading YAML at invocation. The authoritative, agent-facing contract for the verbs is [`commands/harness.md`](../../commands/harness.md); the emitted CLI JSON is locked against drift by `test_cli_surface_locked.py` and `test_verb_contract_locked.py`.

### The command surface

```
# Audited verbs — one-shot, ledger-backed; the orchestrating agent calls these
harness start  <ticket>   [--base <b>] [--resume] [--repo <p>] [--db <p>] [--json/--no-json]   # --resume: continue a reclaimed ticket from its checkpoint-pushed WIP branch when one exists; else a clean start
harness review            [--run-id <id>] [--gate-exit <code>] [--gate-log <p>] [--engine <e>] [--repo <p>] [--db <p>] [--json/--no-json]   # --gate-exit/--gate-log: evidence that YOU ran CONTEXT.md → verify: — required when the repo configures one; the verb never runs the gate itself. --engine: claude (default) | codex
harness close  <ticket>   [--run-id <id>] [--repo <p>] [--db <p>] [--json/--no-json]
harness checkpoint        [--run-id <id>] [--repo <p>] [--db <p>] [--json/--no-json]   # push the run branch to origin mid-flight so committed WIP survives the container dying — pushes only the feature branch, never merges

# Read / inspection — never mutate state
harness status    <run-id>                [--db <p>] [--json]
harness logs      <run-id>                [--follow] [--node <id>] [--db <p>]
harness events    <run-id>                [--type <event_type>] [--after-id <n>] [--db <p>] [--json]
harness runs                              [--limit <n>] [--db <p>]
harness worktrees list                    [--repo-root <p>] [--json]

# Maintenance / ops — mutate outside the audited lifecycle
harness cancel    <run-id>                [--db <p>] [--json]      # abandon an in-flight run: marks the ledger row cancelled
harness reclaim   [<run-id>] [--ticket <id>] [--stale --project <name> [--older-than <dur>]] [--db <p>] [--json]   # reclaim a stranded run (single ticket), or --stale sweeps the project for In-Progress tickets idle past the threshold
harness defer     <ticket> --reason <text> [--reason-file <p>] [--db <p>] [--json]   # triage: comment + additively apply the `decision` label on a Build-queue ticket; record a defer event (CAL-1143)
harness worktrees cleanup                 [--repo-root <p>] [--age <duration>] [--merged]   # remove stale worktrees (git/fs)
harness doctor                            [--db <p>]               # system health checks (read-only)
harness version                           [--json]

# Promotion lifecycle — move dev -> staging -> main (ADR 0003); v1 surface, mechanics land per CAL-1114+
harness promote start     [--repo <p>] [--from <b>] [--to <b>] [--json]   # open a promotion: merge --from into --to and classify
harness promote continue  [--promotion-id <id>] [--repo <p>] [--json]   # resume an agent_may_fix promotion after one bounded repair
harness promote status    [--promotion-id <id>] [--repo <p>] [--db <p>] [--json]   # read a promotion by id: the typed ledger view
harness promote pr        [--promotion-id <id>] [--repo <p>] [--db <p>] [--json]   # success finalizer: push the promotion branch + open the PR (gated)
harness promote escalate  [--promotion-id <id>] [--repo <p>] [--team <k>] [--project <n>] [--db <p>] [--json]   # non-success terminal: file/update a Linear ticket
```

This block lists each command's public flags as registered today; `harness <cmd> --help` and the agent-facing [`commands/harness.md`](../../commands/harness.md) are the authoritative per-flag reference. The audited verbs (`start` / `review` / `close`) drive the run lifecycle through the gate; their behaviour is the [verb model](verb-model.md). `start --resume` is the read side of reclamation: when the picked ticket is `reclaimed` and a checkpoint-pushed WIP branch survives, `start` bases the worktree on that branch (fetch + continue) instead of off `dev`, so the new run recovers the dead run's work; it records `base_branch` unchanged (the merge target stays `dev`) and degrades to a clean start when no durable WIP exists (CAL-739, proposal `stale-run-reclamation` D4). `checkpoint` is a fourth lifecycle verb the orchestrating run calls *between* `start` and `close` — after each green increment it pushes the run's `worktree_branch` to `origin` so committed WIP survives the container dying, and appends a `checkpoint` event bound to the pushed SHA. It pushes **only** the feature branch — never the base, never a merge — so the `close` gate is untouched; the event is the durable-WIP signal `reclaim` reads to report a resumable branch (CAL-738, proposal `stale-run-reclamation` D4). Three maintenance commands also mutate, but **outside** the gated lifecycle: `cancel` writes the [run ledger](run-ledger.md) — it marks an in-flight run `cancelled` (a close-without-merge), stamps `completed_at`, and emits a `workflow_failed` event; `reclaim` recovers a run whose orchestrator died — it reverts the stranded Linear ticket to Todo (with a `reclaimed` label + comment), then reuses `cancel`'s ledger transaction to clear the `open` row (so a fresh `start` is not blocked), while **preserving** the worktree/branch; its `--stale` sweep enumerates a project's In-Progress tickets and reclaims each whose Linear `updatedAt` is idle past `--older-than` (default 90m) — keying on time alone (proposal D2), since a dead run's liveness cannot be observed — reusing the single-ticket path per ticket (the bulk pre-flight the Build routine calls); `worktrees cleanup` mutates git/the filesystem by removing stale worktree directories with `git worktree remove --force` (the branch itself is retained). The read/inspection commands surface the ledger without mutating it. Every command runs as a one-shot container exactly as the human's `~/bin/harness` does.

### The promotion lifecycle group

`harness promote` drives release movement as a first-class, audited lifecycle over the universal `dev → staging → main` topology ([ADR 0003](../decisions/0003-promotion-lifecycle.md)). Its v1 subcommands are the real orchestrator **pause points**: `start` opens a promotion (create the worktree + promotion branch, attempt the `--from` → `--to` merge, and classify the result); `continue` resumes after one bounded, in-policy repair; `status` reports the lifecycle state (read-only); `pr` is the success finalizer (push the promotion branch, open the PR); `escalate` is the non-success terminal path (file/update a Linear ticket and mark the promotion `escalated`). The surface is locked in v1 (CAL-1113); the mechanics land against it — the ledger + JSON contract (CAL-1114), worktree/merge (CAL-1115), gate evidence (CAL-1116), PR creation (CAL-1117), and escalation (CAL-1118).

The **promotion ledger + read-path JSON contract** landed with CAL-1114. Promotion state persists in a sibling `promotions` table in the same per-project `.harness/harness.db` — one row per promotion, a `Promotion` JSON blob keyed by `promotion_id`, read back by id so a later invocation reads what an earlier one wrote (the [run ledger](run-ledger.md) records the promotion table). Two subcommands are wired to it: `promote status --promotion-id <id>` reads a promotion and emits the typed `Promotion` view (a structured `not_found` when the id is unknown), and `promote pr --promotion-id <id>` enforces the **PR gate** — it is refused with `{ "reason": "gate_not_satisfied" }` unless the promotion is `pr_ready` with a fresh gated SHA (the same evidence discipline `review`/`close` enforce).

The **worktree + merge mechanics** for the two write-path openers landed with CAL-1115, on a new `harness/promotion.py` mechanics library (the promotion analogue of `harness/worktree.py`). `promote start` fetches `origin`, validates the `--from` → `--to` pair (a degenerate or unresolvable pair is refused `invalid_branch_pair` before any state is created), creates a promotion worktree/branch **from the target** (`promote/<date>-<from>-to-<to>` based on `origin/<to>`, under `.worktrees/harness/<promotion_id>/` so `worktrees cleanup` reclaims it), attempts `git merge --no-ff origin/<from>`, and records the promotion: a clean merge is `opened` with its merged HEAD in the new `Promotion.merged_sha` field, and a conflict is left in a resumable worktree and classified `agent_may_fix` or `needs_ticket` per the ADR 0003 repair policy (a conflict touching a migration / auth / payment / security / release / deploy script / lockfile, or spanning more than a bounded file count, escalates). `promote continue --promotion-id <id>` resumes an `agent_may_fix` promotion after one bounded repair — it commits the resolved merge, records the merged HEAD, and increments the `attempts` count (refusing `dirty_worktree` when the repair is incomplete, `not_resumable` from any other state).

The **gate + evidence capture** inside those openers landed with CAL-1116, on a new `harness/promotion_gate.py` module (the executor half; gate *config* is still read through the one `harness/gate.py` seam, and evidence is bounded by the same `GATE_OUTPUT_TAIL_LIMIT` the `review` gate uses). After a **clean** merge, `promote start` runs the merged tree's own `verify:` command in the worktree and maps the result: green → `pr_ready`, recording the `gated_sha` (== merged HEAD) and a bounded `evidence` tail; a failed gate → `needs_ticket` (a red promoted tree is human-owned in v1 — `agent_may_fix` is reserved for small merge *conflicts*, conservatively narrowing ADR 0003); an unrunnable gate (launch error / timeout) → `blocked`; and no `verify:` configured → `opened` (ungated, matching `review`/`close`'s `not_configured` honesty — it cannot advance to `pr_ready` without evidence). `promote continue` re-runs the same gate on the resolved merge, so a promotion that passes only after a bounded repair reaches `pr_ready`, while one that still fails has spent its attempt → `needs_ticket`. `promote pr` now enforces **two** gates: the `pr_ready` + gated-SHA PR gate (`gate_not_satisfied`), and a branch-HEAD **freshness** check — it refuses `stale_gate` when the promotion branch tip has moved past the `gated_sha`, so a commit sneaked in after the gate cannot be pushed on stale evidence (AC-3).

The **PR publication** past those two gates landed with CAL-1117, on a new `harness/promotion_pr.py` module (the publication half — the analogue of `harness/promotion_gate.py` for the publish step, git + `gh` only, no ledger or Typer). Once both gates pass, `promote pr` pushes **only** the promotion branch to `origin` via an explicit `<branch>:<branch>` refspec (never a direct push to `staging` / `main`), assembles the PR title/body from **deterministic facts** read from git (the `origin/<to>..<gated_sha>` commit range, the Linear IDs in those subjects, the changed `specs/` paths, and the captured gate evidence — ADR 0003 "PR authority"), opens the PR into the target branch through the `gh` CLI (harness-owned, not orchestrator-owned), and records the `pr_url` + the terminal `pr_opened` state. A push or `gh` failure surfaces as a structured refusal (`push_failed` / `pr_create_failed`), never a bare traceback; no auto-merge or `promote land` command exists in v1.

The **escalation path** — the non-success terminal — landed with CAL-1118, on a new `harness/promotion_escalation.py` module (the content half — the analogue of `promotion_pr.build_pr_body` for the escalate step, pure builders, no Linear I/O). `promote escalate --promotion-id <id>` files or updates a Linear ticket carrying the promotion evidence: the id, status, endpoints, promotion branch/worktree to inspect, the live conflict files (read from the worktree — best-effort, empty when clean or torn down), the captured gate summary, and the next human action keyed on the blocking status. The target team/project resolve from `CONTEXT.md` (`repo.linear` / `repo.project`, read by the new `harness/repo_config.py`), overridable with `--team` / `--project`. Escalation is **idempotent** (ADR 0003): a promotion not yet linked to a ticket gets a fresh Todo issue (via `LinearClient.create_issue`, resolving team/project/Todo-state at runtime), while one already carrying an `escalation_ticket` is **commented on** instead of duplicated; either way the row records the ticket id and the terminal `escalated` state. Missing Linear credentials return a structured `{ "reason": "blocked" }` result and leave the promotion row untouched — auth failure is a first-class blocked outcome, not a generic crash (proposal `local-promotion-steward`, item 7). With `escalate` wired, the whole `promote` surface is implemented; no subcommand remains a stub.

There is **no separate `verify` command** in v1, by design. Gate execution runs *inside* `start` and `continue` — a promotion cannot reach `pr_ready` without fresh gate evidence, the same evidence discipline the `review` / `close` gate enforces — so a standalone `verify` would name a step that is never an independent orchestrator pause/resume point. The pause points are exactly where the outer agent stops and re-enters (open, resume-after-repair, read, finalize, escalate); running the gate is a phase of `start` / `continue`, not a state the orchestrator parks at, so it earns no command of its own.

### Exit codes are a stable contract

| Code | Meaning |
|------|---------|
| 0 | Command succeeded (including a recorded review `fail` — a *successful* review) |
| 1 | Unexpected error (git failure, DB error, Linear error) |
| 2 | Invocation error or gate refusal (bad flags, unknown run-id, gate not satisfied) |
| 3 | `review`: an infra failure — the engine could not run at all (`sandbox_init_failure` / `engine_timeout`) |
| 4 | `review`: a spend breaker tripped (`review_cycle_ceiling` / `wall_clock_budget`) |
| 5 | `review`: the verify gate cannot certify the tree — red evidence (`gate_failed`) or none supplied (`no_gate_evidence`); no engine ran, no verdict was recorded |
| 130 | SIGINT (user cancelled) |

Each of `review`'s dedicated codes exists so an orchestrating agent can tell the *kind* of stop apart without parsing prose: an environment wall (3), a bounded-out loop (4), and a tree that cannot show it is green (5) call for three different responses, and none of them is a rejected diff.

#### Scenario: a gate refusal exits 2

- GIVEN `harness close` whose gate is not satisfied
- WHEN it runs
- THEN it exits 2 with exactly one structured `reason` (`no_run` / `dirty_worktree` / `no_passing_review` / `stale_review` / `no_gate_evidence` / `dirty_base_checkout`)

#### Scenario: missing or red gate evidence exits 5

- GIVEN `harness review` in a repo that configures a `CONTEXT.md` `verify:` command
- WHEN it runs with no `--gate-exit`
- THEN it exits 5 with `reason=no_gate_evidence`, having invoked no engine and recorded no `review` event (CAL-1082)
- AND WHEN it runs with a non-zero `--gate-exit`, THEN it exits 5 with `{ "error": ..., "reason": "gate_failed", "gate_output_tail": ... }`, the same way

### JSON output is part of the public contract

The verbs (`start` / `review` / `close`) and `status` / `events` / `version` expose `--json` for machine consumers; `logs` is the human-readable timeline (use `events --json` for its machine-readable form) and `runs` prints a summary table. **Flag names and JSON keys are part of the public contract — no breaking changes without a major version bump.**

#### Scenario: inspect a run without mutating it

- GIVEN any run
- WHEN a consumer runs `harness status <run-id> --json`
- THEN it prints the run's state as JSON and touches nothing

## Interface surface

Commands are split per concern across `harness/cli/*.py` for readability and registered in `harness/cli/__init__.py`. The verb output shapes (`StartOutput` / `ReviewOutput` / `CloseOutput`) are defined alongside their verbs and locked by `test_verb_contract_locked.py`; the full registered command set is locked by `test_cli_surface_locked.py`.

## Known limitations

- No dynamic subcommands: the surface only changes by editing a verb, by design (the engine-era YAML-driven subcommand generation was retired in CAL-574).

## Decisions

The verb surface is a public contract (decision; [`specs/architecture-principles.md`](../architecture-principles.md)) — stable flags, exit codes, and JSON, because humans and Hermes invoke the harness through the same commands.

## Cross-references

- [verb-model.md](verb-model.md) — what the audited verbs do
- [run-ledger.md](run-ledger.md) — what the read/inspection commands surface
- [worktree-lifecycle.md](worktree-lifecycle.md) — the `worktrees` housekeeping commands
- [`commands/harness.md`](../../commands/harness.md) — the agent-facing verb contract
