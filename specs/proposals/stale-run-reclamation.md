<!-- guidance:template-proposal@0.1.1 -->
---
proposal: stale-run-reclamation
status: accepted   # draft | under-decision | accepted | rejected | split
date: 2026-06-16
related: [run-ledger, verb-model, four-loops, CAL-734, CAL-735, CAL-736, CAL-737, CAL-738, CAL-739]
---

# Proposal: Reclaim runs whose orchestrating agent dies mid-flight

> When the Claude session driving a run stops without finishing (session/usage limit, crash, container timeout), the ticket is stranded **In Progress** and silently blocks every dependent — until something reverts it. This proposes a time-based reclamation sweep, keyed on Linear, that the next routine runs before it picks work.

## Problem / motivation

The Build loop is an hourly autonomous routine: a fresh Claude session reads the Linear `Harness v3` queue, picks the next logical Todo ticket, and drives it `start → implement → review → close`. `harness start` does three things atomically — transitions the ticket to **In Progress**, opens a `runs` row (`status='open'`), and creates a worktree.

If that session then **stops mid-run** — it hits a usage limit, the context fills, the container times out — it just stops. Nothing finishes the run. It leaves three pieces of stranded state:

1. **A Linear ticket stuck In Progress** — `start` set it; only `close` clears it, and `close` never ran.
2. **An `open` `runs` row** — in the per-checkout `.harness/harness.db`.
3. **A git worktree + branch** — possibly with WIP commits, possibly with a passing review event.

Of these, **(1) is the one that hurts.** The next hourly run is a *different* session that can observe nothing about the dead one — the container was ephemeral, there is no PID to ping, and a cloud-cloned routine does not even share the local DB. All it can see is **Linear**. It reads the queue, sees a predecessor sitting In Progress, concludes work is underway, and refuses to advance dependents. The backlog wedges. Overnight, that is hours of lost loop iterations for a run that died in the first ten minutes. **This has already happened.**

The status quo has no recovery path. `harness cancel` exists but only flips the local `open` row to `cancelled` and emits an event — it never touches Linear, so the ticket stays In Progress and the dependent stays blocked. `harness worktrees cleanup --age` prunes stale worktrees but knows nothing about tickets. There is **no transition that reverts an In-Progress ticket back to Todo**, and nothing that detects an abandoned run in the first place. Recovery today is a human noticing and hand-editing Linear.

### The one inescapable constraint

Liveness **cannot be observed**. The orchestrating session runs in an ephemeral container with no durable handle a later session can probe. So "is this run still alive?" is unanswerable directly — it can only be *inferred from a time signal*: a run that has shown no progress for longer than any legitimate run takes is presumed dead. Every viable option is a variation on that heuristic. The user's instinct — "expire runs that haven't updated in over 90 minutes" — is exactly right; the design question is **where the signal lives, who acts on it, and what reclaiming does to the work.**

## Options

**Option A — Lazy, Linear-keyed reclamation sweep (+ a `harness reclaim` verb).** Add a pre-flight step to `/harness routine build`: before picking work, sweep for In-Progress tickets whose last activity is older than a staleness threshold and revert each to Todo (with a comment + a `reclaimed` marker), via a new auditable `harness reclaim` verb. The verb does the full reconciliation — revert the Linear ticket, flip the matching local `open` row to `cancelled` (reusing the `cancel` path), and prune the worktree (reusing `worktrees cleanup`). · *Trade-offs:* survives a hard kill (a time heuristic is the only thing that does); needs no new infrastructure — the sweep rides the hourly routine that already runs; Linear is the substrate every run actually reads, so reverting there is what unblocks the dependent; the revert goes through a verb, honouring routing discipline (D5). Costs: recovery latency up to one routine interval (≤1h — the cadence already in play); needs a correct threshold to avoid reclaiming a genuinely-slow live run; requires a new `transition_to_unstarted` on `LinearClient` (the existing `_transition` already generalises to it).

**Option B — A persistent reaper service / dedicated frequent cron.** A long-lived process (or a 5-minute cron) that expires stale `open` runs / In-Progress tickets on a tight timer — the literal "expire runs > 90 min." · *Trade-offs:* lower recovery latency. But it reintroduces a standing runtime the architecture deliberately retired — the whole point of the verb model (Decision: *Invert the orchestration boundary*) was to delete the Hermes supervisor and have **no daemon**. A separate cron needs its own auth, env, and schedule; and against a cloud-cloned routine there is no persistent local DB to read, so it would have to key on Linear anyway — at which point it is Option A on a faster, costlier timer. Heavier than an hourly loop warrants.

**Option C — Supervisor-on-exit cleanup (watchdog wrapper).** Wrap the launch of the orchestrating session; on exit — including error — run `harness reclaim`. · *Trade-offs:* immediate, deterministic recovery with no timeout guessing — *when it fires.* But a hard kill (usage-limit/OOM/container-timeout) can take the supervisor down with the child, and a hard kill is precisely the reported failure. It cannot be the backstop, only a latency optimisation layered on a time-based sweep. Adds a wrapper around the scheduled trigger.

**Option D — Resume instead of reclaim.** Have the next run *continue* the abandoned run (re-orient from the ledger + worktree) rather than revert it. · *Trade-offs:* preserves WIP, and the In-Progress state is arguably *correct* — work is paused, not abandoned. But cross-container resume is usually impossible: a fresh cloud clone has no worktree from the dead run, and resuming a fresh session from a half-state is fragile. Worse, it does not unblock *other* dependents if the resumed run still cannot finish. A good enhancement on a persistent local checkout; not a general fail-safe.

**Option E — Lease/TTL on `start`.** `harness start` writes `expires_at = now + lease`; holding the ticket requires renewal (heartbeat), and once the lease lapses any run may reclaim. · *Trade-offs:* clean fencing semantics, and the lease *is* the staleness signal. But a lease alone moves nothing — it still needs a sweep (Option A) or reaper (Option B) to act on expiry. It is really a refinement of *which* signal Option A reads (a lease deadline vs. a Linear timestamp), not a standalone alternative. Renewal during a long implement phase depends on the session remembering to heartbeat, which is unreliable.

## Recommendation

**Adopt Option A.** It is the smallest thing that actually fixes the reported failure, and the only family that survives a hard kill without standing infrastructure.

The reasoning, against `engineering-principles` and this repo's architecture:

- **Linear is the real substrate.** The dependent blocks because it reads an In-Progress ticket; nothing else it can see matters. So reclamation must, above all, revert the *ticket*. The local DB and worktree are secondary cleanup — useful where the checkout persists, irrelevant where it does not.
- **Only a time heuristic survives a hard kill.** Supervisor-on-exit (C) and resume (D) both assume something graceful happened. The reported failure is ungraceful. The lazy sweep is the load-bearing piece; C is at best a latency optimisation on top of it.
- **No new daemon.** The verb model exists to keep the harness "deterministic verbs, a ledger, and a gate" with the agent doing orchestration — *not* a standing runtime. A reaper (B) walks that back. A sweep that rides the already-hourly Build routine adds zero infrastructure.
- **The revert is a state mutation, so it goes through a verb (D5).** Routing discipline says every run-lifecycle git/ticket mutation flows through a verb so the ledger stays whole; a hand-rolled Linear revert in routine prose would be exactly the hole D5 forbids. `harness reclaim` is the deterministic, testable home for it, composing the pieces that already exist (`cancel`, `worktrees cleanup`) with the one that does not (the Todo revert).

Start the **staleness signal** simple: compare against the time the ticket last moved (its Linear `updatedAt`/`startedAt`) with a generous fixed threshold that exceeds the longest legitimate single run. Add an explicit heartbeat (Option E's renewal) only if false positives actually appear — do not build the lease machinery up front (no premature abstraction).

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| **D1 — Reclaim target state.** Revert In Progress → **Todo** (re-pickable immediately; may redo work) vs. → a distinct parking state/label (`stalled`/`needs-recovery`; visible, avoids silent restart, but needs a human or a resume path to re-queue). *Rec: revert to **Todo** and stamp a `reclaimed` label + a comment naming the time it went silent — re-pickable AND visibly marked.* | user | run-ledger feature spec |
| **D2 — Staleness threshold & signal.** Fixed threshold on Linear's last-activity timestamp (zero new mechanism) vs. an explicit heartbeat the session writes (tighter, but relies on the session pinging). And: **what is the threshold?** It must exceed the longest legitimate single run. *Rec: fixed threshold on the Linear timestamp; **90 min** (the hourly cadence + buffer); add heartbeat only if false positives appear.* | user | run-ledger feature spec |
| **D3 — Trigger & deployment.** Lazy pre-flight in `/harness routine build` (recommended) vs. a dedicated reaper. **This depends on an unresolved fact:** `commands/harness.md` says routines are *local-trigger only* (persistent checkout, local DB reachable), but the operating model treats Build as a *scheduled cloud routine* (fresh container, only Linear reachable). The answer determines how much of the local cleanup (`cancel` + worktree prune) is even reachable. *Rec: lazy pre-flight, Linear-keyed, so it works in **both** regimes; local cleanup is best-effort where the checkout persists.* | user | run-ledger feature spec / CONTEXT.md |
| **D4 — WIP handling.** Discard the dead run's worktree/branch on reclaim (clean restart; gate prevents double-merge) vs. attempt to preserve/resume. *Rec: discard in v1; resume is a later enhancement gated on a persistent checkout.* | user | run-ledger feature spec |

### Resolved 2026-06-16

- **D1 → Todo + `reclaimed` marker.** Reclaim reverts the ticket to Todo, applies a `reclaimed` label, and posts a comment naming when it went silent — re-pickable AND visibly marked.
- **D2 → Linear timestamp @ 90 min.** Staleness = `now − ticket.updatedAt > 90 min`, read straight off Linear. No new column, no session pinging. Heartbeat deferred unless false positives appear.
- **D3 → Lazy pre-flight, Linear-keyed.** The sweep runs as step 0 of `/harness routine build`, before it picks work. No daemon; works in both the local and cloud regimes because it keys on Linear. (The cloud-vs-local fact behind this is still worth pinning down — see Risks — but the design no longer *depends* on the answer.)
- **D4 → Preserve / resume (not discard).** Reclaim does **not** prune the dead run's branch; the work is preserved and the next pick resumes from it rather than restarting cold. **Consequence — this is only real if WIP is durable.** A worktree on a dead ephemeral container is gone, so "preserve" means *the run's branch was pushed and the ticket references it*, not *keep the local worktree*. For the cloud hard-kill case to actually resume, the run must **checkpoint-push WIP before it dies** — without that, the branch is unpushed, nothing survives, and resume degrades to a clean restart for exactly the failure we care about. So D4 pulls in a checkpoint-push requirement (breakdown items 5–6); where no durable WIP exists, reclaim falls back to clean restart, and `close`'s HEAD-bound gate keeps even a cold restart safe from double-merge.

## Breakdown

The change specs this would spawn, each shippable on its own (the decisions above are folded in):

1. **`LinearClient.transition_to_unstarted` + a `reclaimed` marker.** The missing Todo revert (D1). The existing `_transition` already parameterises on `state_type`/`preferred_name`; add the `unstarted`/"todo" entry point, plus the helpers reclaim needs to apply a `reclaimed` label and post a comment. Small, no behaviour change to existing transitions.
2. **`harness reclaim` verb (single run/ticket).** Given a run-id (or ticket): revert the Linear ticket to **Todo + `reclaimed` label + a comment** naming when it went silent (D1), and flip the matching `open` row to `cancelled` so a fresh `start` is not blocked by `idx_runs_ticket_open` (reuse the `cancel` transaction). It **preserves** the branch (D4) — it does *not* prune the worktree. One auditable verb, one transaction for the ledger write; mirrors `cancel` but adds the Linear revert.
3. **Staleness detection.** `harness reclaim --stale [--older-than 90m]` (default 90 min, D2): enumerate In-Progress tickets (Linear) whose `updatedAt` is older than the threshold and reclaim each. Idempotent (reclaiming an already-reclaimed/terminal run is a no-op); never reclaims a fresh run. Clock comparisons UTC-correct via the `_time.py` seam.
4. **Wire the pre-flight into `/harness routine build`.** Add step 0: run the stale sweep before picking work, so the queue is unblocked first. Guidance/command-body change to `commands/harness.md` + the routine logic.
5. **Durable WIP capture — checkpoint-push (D4 prerequisite).** For resume to be real in the cloud regime, the orchestrating run must push its branch periodically (e.g. after each green checkpoint) so the work survives the container dying, and reclaim must record the branch ref on the ticket. Without this, resume degrades to clean restart for the cloud hard-kill case. This is the load-bearing half of D4 — scope it deliberately, not as an afterthought.
6. **Resume-from-branch in the pick logic.** When the routine picks a `reclaimed` ticket carrying a pushed WIP branch, base the new run on that branch (fetch + continue) rather than starting cold; fall back to clean restart when no durable WIP exists. `close`'s HEAD-bound gate keeps both paths safe from double-merge.
7. **(Deferred refinement) Heartbeat.** The orchestrating session periodically touches the ticket/run; staleness then keys on the gap rather than a fixed threshold. Build only if D2's 90-min threshold proves too blunt.
8. **Tests.** Reclaim leaves the ticket Todo + `reclaimed` + run cancelled + branch preserved; the sweep reclaims only past-threshold runs and never a fresh one; idempotency; resume continues from a pushed branch and falls back cleanly when none exists; UTC clock correctness. *(Test coverage rides each change above — TDD — rather than a standalone ticket.)*

### Spawned issues (2026-06-16, CAL / Harness v3)

Created in dependency order; lower ID = earlier (the Build routine picks by ID order):

| Item | Ticket |
|---|---|
| 1 — `transition_to_unstarted` + markers | CAL-734 |
| 2 — `harness reclaim` verb | CAL-735 |
| 3 — `harness reclaim --stale` sweep | CAL-736 |
| 4 — wire pre-flight into `/harness routine build` | CAL-737 |
| 5 — checkpoint-push durable WIP | CAL-738 |
| 6 — resume-from-branch in pick logic | CAL-739 |

Item 7 (heartbeat) is deferred — not ticketed until D2's 90-min threshold proves too blunt.

## Risks / unknowns

- **False positives** — reclaiming a genuinely-alive long run puts two sessions on one ticket. Mitigated by a generous threshold (D2) and/or a heartbeat, and bounded by the `idx_runs_ticket_open` index + `start`'s duplicate-open detection. **Worst case is wasted work, not corruption** — `close`'s HEAD-bound gate prevents a double-merge. Reclaim must fully clear the `open` row so a fresh `start` is not rejected as a duplicate.
- **The cloud-vs-local fact (behind D3) is still worth pinning down.** The *sweep* no longer depends on it (it keys on Linear), but **resume (D4) does**: in a fresh cloud container the dead run's worktree is gone, so the only recoverable work is what got pushed. This is why checkpoint-push (item 5) is the load-bearing half of resume — confirm the deployment to know whether item 5 is mandatory (cloud) or merely an optimisation (persistent local checkout).
- **Resume is only as good as the last checkpoint-push.** If a run dies between pushes, the work since the last push is lost regardless — resume narrows the loss to "since last checkpoint," it does not eliminate it. The cost/value of tightening the checkpoint cadence is a tuning question for item 5, not a v1 blocker.
- **Ledger/reality divergence** — a dead run leaves an orphaned `open` row that the local ledger and Linear no longer agree on. Reclaim must reconcile both, and `close`'s "a start exists" check must not be fooled by a prior *reclaimed* (cancelled) run on the same ticket.
- **Clock source** — Linear timestamps (UTC) and local time must be compared consistently; route everything through the `_time.py` seam.
- **What would invalidate the recommendation:** if the routine were ever moved into a persistent, supervised process that *can* observe its child's exit reliably, Option C becomes a clean primary and the time-based sweep drops to a backstop. As long as the trigger is an ephemeral, hard-killable container, the lazy sweep stays load-bearing.

---

**Lifecycle.** A proposal ends in one explicit state: **accepted** (spawn the change specs as Linear issues; record its decisions in the relevant specs), **rejected** (keep this file as the record of why), or **split** (replace with smaller proposals). It does not sit half-decided. Lives in `specs/proposals/`.
