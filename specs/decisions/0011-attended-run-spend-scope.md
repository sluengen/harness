# ADR 0011 — The wall clock bounds unattended runs; an attended run declares itself and is bounded by the operator

- **Status:** Accepted
- **Date:** 2026-08-02
- **Source:** `specs/proposals/attended-runs-and-the-wall-clock.md`

## Context

`loop.wall_clock_budget_minutes` measures exactly one thing — `now - runs.started_at` — and two consumers act on it, deliberately reading one value so they cannot diverge (#260):

- **`review`'s breaker** refuses the upcoming review with exit 4 / `reason=wall_clock_budget` once elapsed exceeds the budget (`evaluate_breakers`).
- **`reclaim --stale`** resolves the same value as its default staleness threshold and reverts the ticket to Todo with a `reclaimed` label.

The breaker was built for one regime (`harden-loop-layer` D1, CAL-906): the unattended Build routine has no view of the orchestrating session's token meter, so two ledger-observable facts — review count and run age — stand in for spend. That substitution is what makes the clock necessary, and it is what an attended session does not need.

In an attended session the operator is regularly asked a question mid-run — a judgment call, a permission, a choice of approach. The clock runs across that wait, and both consumers then misfire on a run that is neither dead nor overspending. The breaker's premise is false: a run paused on a question spends nothing, and is refused for a cost it did not incur. The sweep's premise is unobservable: a paused session touches none of the three liveness clocks `reclaim_liveness` reads — tracker `updatedAt`, ledger last activity, worktree tracked-file mtime — because a human thinking looks exactly like an orchestrator that died. The operator answers and finds the ticket reverted underneath them.

The operating record is consistent with this and cannot fully quantify it. Fifteen runs carry a `reclaimed` finalization; two ran ~9h before being reclaimed (`01KWHCXBJZBCEE`, `01KYHTXG7Q31FZ` — the shape of a session left overnight), and several were reclaimed at 61–67m of lifetime. Breaker trips are **uncountable**: exit 4 records no event at all, so the prospective half of the waste leaves no ledger trace. That gap is adjacent to [ADR 0009](0009-verb-attempt-telemetry.md)'s rule that every verb records its attempt, and it is why this decision rests partly on the operator's report.

Two facts constrain any fix. First, **liveness cannot be inferred** — no clock, however chosen, separates a human thinking from a dead orchestrator, so the sweep half is unfixable by measurement alone. Second, **the unattended ceiling must not move**: it is the only bound on autonomous spend, and buying attended tolerance by raising it for everyone trades away the thing the breaker exists for.

## Decision

**Attendance is a declared property of a run. The wall clock applies to unattended runs only; an attended run is bounded by the operator, by the cycle ceiling, and — for reclamation only — by a separate, much longer idle threshold.**

Concretely:

- **`harness start --attended` declares the mode**, recorded in the run row's `inputs_json`. That column is already free-form (`"{}"` at insert), so this needs no schema migration.
- **Bounded is the default.** An undeclared run behaves exactly as it does today. Every existing caller, every routine, and every self-hosting repo keeps its ceiling with no change, and a forgotten flag fails safe *toward* the bound rather than away from it. Only the interactive `/harness run` declares attended; no routine path may pass the flag.
- **`review`'s wall-clock check does not apply to an attended run.** The verb resolves the mode from the run row and skips that check alone.
- **The review→fix cycle ceiling still applies to an attended run**, unconditionally. Presence justifies removing the *spend clock*, not the *non-convergence* bound: six cycles is what catches a run going in circles, and the operator's attention is not a substitute for it.
- **`reclaim --stale` applies `loop.attended_idle_minutes` (480) to an attended run** instead of the wall-clock budget — a longer threshold, not an exemption. An attended session abandoned overnight is still reclaimed by morning, so the board self-heals and worktrees do not accumulate. The sweep's three-clock idle rule is unchanged underneath it; only the threshold it compares against is selected by mode.
- **Attendance is fixed at `start`.** It cannot be changed mid-run. The walk-away case — an attended session the operator never returns to — is covered by `attended_idle_minutes`, not by a mode transition.

**Why this preserves #260's invariant.** #260 forbids a run being refused at review yet spared reclamation — alive on the board, unable to finish. Under this decision the attended mode has no review-side clock at all, so that window cannot open; the unattended mode keeps one configured value read by both consumers. One quantity per mode, and still no equality kept by hand.

## Alternatives rejected

- **Measure idle, not age, in the breaker** — replace `now - started_at` with `now - last_activity`, reusing what `reclaim_liveness` already computes. Rejected **as the fix**, not on its merits: at the verb boundary after the operator returns, idle is minutes, so it does resolve the breaker half with no flag and no mode. But it leaves the sweep half untouched — the sweep already reads idle and still reclaims a paused session — and it removes the only ceiling on a run that stays *busy* indefinitely, since the cycle ceiling bounds review→fix churn but not a run that never reaches `review`. It remains a defensible independent improvement to the *unattended* breaker and is not foreclosed by this decision.
- **Explicit hold — the session brackets each wait** (a hold/resume pair; elapsed subtracts held intervals; the sweep spares a held run), with precedent in [ADR 0006](0006-hold-kinds.md)'s hold kinds. Rejected: correctness depends on the session bracketing *every* wait, which it cannot be relied on to do, and a session that dies during a hold is spared forever unless the hold expires — reintroducing the threshold it was meant to avoid. More machinery than the problem warrants.
- **Raise the budget for everyone.** Rejected on the stated constraint: it weakens the ceiling in the only regime that needs it, to buy tolerance for a latency no number bounds — overnight is not four hours.
- **Exempt attended runs from reclamation entirely.** Rejected: an abandoned attended session would leak an open run row, a worktree, and an In-Progress ticket indefinitely. A longer threshold gets the same practical tolerance while the board still self-heals.

## Consequences

- **Attendance is a claim, not an observation.** A run declared attended and then abandoned escapes the spend ceiling for up to `attended_idle_minutes`. This is bounded, not eliminated. The routine-path guard — a test asserting no routine passes `--attended` — is what keeps the erosion from happening by edit.
- **The sweep gains a mode dimension**, and it is the subtlest code in the repo: #216, #254 and #255 each corrected it, twice after it reclaimed a live session. The threshold-selection change is the risky part of this decision; the breaker change is not.
- **The effect cannot be measured from the ledger.** Exit 4 writes no event, so there is no denominator for attended breaker trips before or after. Closing that is separate work in the spirit of ADR 0009; until it exists, the reclamation count is the only observable half.
- **`loop:` grows a third threshold.** Repos self-hosting the harness inherit `attended_idle_minutes` with its default and never have to set it, in the same way `engine_timeout_seconds` moves with its constant (#291).
- **Asking the operator a question stops being expensive.** The status quo penalised the one behaviour that most improves a run's outcome; removing that incentive is part of the point, not a side effect.
