---
proposal: attended-runs-and-the-wall-clock
status: shipped             # draft | under-decision | accepted | shipped | rejected | split
date: 2026-08-02
related: [specs/decisions/0011-attended-run-spend-scope.md, specs/proposals/harden-loop-layer.md, specs/proposals/stale-run-reclamation.md, specs/decisions/0006-hold-kinds.md, specs/features/run-ledger.md]
---

# Proposal: the wall clock bounds unattended runs; an attended run is bounded by the operator

> The per-run wall clock exists to bound autonomous spend, but it is applied to every run — so human latency in an attended session (a question asked while the operator is away) burns the budget and costs the run. Scope the clock to the regime it was built for.

## Problem / motivation

`loop.wall_clock_budget_minutes` (110) measures one thing: `now - runs.started_at`. It cannot see whether a human was in the room, and two consumers act on it (#260):

- **`review`'s breaker** — `evaluate_breakers` refuses the upcoming review with exit 4 / `reason=wall_clock_budget` once elapsed exceeds the budget ([loop_budget.py:213-220](harness/loop_budget.py#L213-L220)). The work is done and un-certifiable: no verdict, so no `close`.
- **`reclaim --stale`** — the hourly Build pre-flight resolves the *same* value as its default staleness threshold ([reclaim.py:633-640](harness/cli/reclaim.py#L633-L640)) and reverts the ticket to Todo with a `reclaimed` label.

In an attended session the operator is frequently asked a question mid-run — a judgment call, a permission, a choice between approaches. The clock keeps running across that wait, and both consumers then misfire on a run that is neither dead nor overspending:

- the breaker's premise is false — a run paused on a question spends **nothing**. It is refused for a cost it did not incur;
- the sweep's premise is unobservable — a session paused on a question touches none of the three liveness clocks (`reclaim_liveness`: tracker `updatedAt`, ledger last activity, worktree tracked-file mtime), because a human thinking looks exactly like an orchestrator that died. The operator answers and finds the ticket yanked back to Todo underneath them.

The breaker was built for a specific regime (`harden-loop-layer` D1, CAL-906): the Build routine has no view of the token meter, so two ledger-observable facts stand in for spend. That substitution is what makes the clock necessary — and it is exactly what an attended session does not need. **A human present is the breaker**: they can stop the run at any point, and they are the one paying attention to what it costs. The clock is applied to the one regime where it buys nothing and can cost a whole ticket's work.

**What the ledger says.** 15 runs carry a `reclaimed` finalization. Two ran ~9h before being reclaimed (`01KWHCXBJZBCEE`, 521m; `01KYHTXG7Q31FZ`, 544m) — the shape of an attended session left overnight. Several were reclaimed at 61–67m of lifetime, inside even the old 90m budget. The breaker's trips are **not** countable: a tripped breaker records no event at all (no review event, engine never runs), so exit 4 leaves no ledger trace — an observability gap adjacent to ADR 0009's "every verb records its attempt", and one reason the frequency here rests on the operator's report rather than a query.

There is also a second-order cost: a clock that punishes asking the operator a question is an incentive not to ask one.

Doing nothing costs a ticket's work, or a recovery cycle, each time it happens — and it happens repeatedly.

**The constraint any fix must respect.** The unattended ceiling must not move. Whatever ships leaves the routine's bound exactly where it is today.

## Options

**Option A — Declared attendance, carried on the run.** `harness start --attended` records the mode in the run row's `inputs_json` (already free-form `{}` — [start.py:549](harness/cli/start.py#L549) — so no schema migration). `review`'s wall-clock check is skipped for an attended run; `reclaim --stale` applies a separate, much longer threshold to one. `/harness run` declares attended; the routine commands declare nothing and keep today's behaviour byte-for-byte. · **For:** one declaration, both consumers read it; it is the *only* option that fixes the sweep, because no clock can distinguish a human thinking from a dead orchestrator. Bounded stays the default, so a forgotten flag fails safe toward the ceiling. · **Against:** a declaration is a claim, not an observation — a mis-declared run escapes the spend ceiling, and an attended run genuinely abandoned would leak an open run, a worktree and an In-Progress ticket unless some threshold still reaches it. Adds a mode dimension to every run.

**Option B — The breaker measures idle, not age.** Replace `now - started_at` with `now - last_activity`, reusing the signal `reclaim_liveness` already computes. When the operator returns, works, and hits the next verb boundary, idle is minutes — the breaker passes; a genuinely stalled run still trips. · **For:** no flag, no mode, no new configuration; reuses a written module (the #255 precedent of sharing reclaim's predicate with close's gate); it also makes the *unattended* breaker better, since it stops charging a run for time it was not running. · **Against:** it does not fix reclamation at all — the sweep already reads idle and still reclaims a paused session. And it removes the only ceiling on a run that stays *busy* indefinitely: the cycle ceiling bounds review→fix churn, but a run that never reaches `review` would be unbounded.

**Option C — Explicit hold: the session brackets the wait.** Before asking the operator, the session records a hold; elapsed subtracts held intervals and the sweep spares a held run. Precedent exists in ADR 0006's hold kinds (`defer --needs operator`). · **For:** the most accurate — it measures what actually happened, and it serves both consumers. · **Against:** correctness depends on the session reliably bracketing *every* wait, which it cannot be relied on to do; and a session that dies *during* a hold is spared forever unless the hold itself expires — reintroducing the threshold the hold was meant to avoid. More machinery than the problem warrants.

**Option D — Raise the budget for everyone.** One line in CONTEXT.md. · **Against:** it weakens the unattended ceiling — the only regime the breaker exists for — to buy tolerance for human latency, and human latency has no bound a number covers (overnight is not 4 hours). Rejected on the stated constraint.

## Recommendation

**Option A, bounded-by-default, with an attended reclamation threshold rather than an exemption.**

1. **Attendance is declared at `start`** and carried in `inputs_json`. Undeclared means today's behaviour exactly — every existing caller, every routine, every self-hosting repo keeps its ceiling with no change. Only `/harness run` declares attended.
2. **`review`'s wall-clock breaker does not apply to an attended run.** The **cycle ceiling still does** — six review→fix cycles is a non-convergence bound the operator's presence does not justify removing, and it is the breaker that actually catches a run going in circles.
3. **`reclaim --stale` applies a separate `attended_idle_minutes` to an attended run** rather than skipping it. An abandoned attended session is still eventually reclaimed and the board self-heals, and the sweep's three-clock idle rule keeps working unchanged underneath it — an attended session that is actually working refreshes those clocks anyway.

Why this over B: the failure is half breaker, half sweep, and **only a declaration fixes the sweep**. B is a real improvement to the unattended breaker on its own merits and should be considered separately, not as a substitute.

Why a longer threshold over an exemption: it keeps #260's invariant intact instead of trading it away. #260 forbids a run being *refused at review yet spared reclamation* — alive on the board, unable to finish. Under this design the attended mode has no review-side clock at all, so that window cannot open; and the unattended mode keeps its single value read by both consumers. One quantity per mode, still no hand-kept equality.

This follows `engineering-principles` on smallest change (a declared field on an existing free-form column, two read sites, no migration) and on errors never swallowed (an attended run that is genuinely abandoned still ends up reclaimed, loudly, rather than leaking).

## Open decisions

All resolved 2026-08-02 by the operator and recorded in [ADR 0011](../decisions/0011-attended-run-spend-scope.md).

| Decision | Resolved | Recorded in |
|---|---|---|
| Direction | **Declared attendance** (Option A). Idle-based measurement was not taken as the fix — it cannot reach the sweep half — and stays available as an independent improvement to the unattended breaker. | ADR 0011 |
| Which way the default runs | **Bounded by default; `--attended` opts out.** A forgotten flag keeps the ceiling. | ADR 0011 |
| Does an attended run keep the cycle ceiling? | **Yes, unconditionally.** Presence removes the spend clock, not the non-convergence bound. | ADR 0011 |
| Value of `attended_idle_minutes` | **480 (8h)** — an overnight gap still reclaims by morning; not an exemption. | `CONTEXT.md` `loop:` + `loop_budget.py` default |
| Can attendance change after `start`? | **No.** Fixed at `start`; the walk-away case is covered by `attended_idle_minutes`. | ADR 0011 |
| Own ADR? | **Yes** — it changes what both spend consumers mean, and every self-hosting repo inherits it. | `specs/decisions/0011-attended-run-spend-scope.md` |

## Breakdown

1. **`start` records attendance** — `--attended` flag, written to `inputs_json`; a test proving an undeclared run records today's default and nothing else changes.
2. **`review` scopes the wall-clock breaker to unattended runs** — `evaluate_breakers` takes the mode; the cycle ceiling stays unconditional. Measuring tests on both arms (attended run past the budget proceeds; unattended run past it still trips exit 4).
3. **`reclaim --stale` applies `attended_idle_minutes`** — new `loop:` key with a default in `loop_budget.py`, resolved the same way the wall clock is; a measuring test that an attended run is spared below the threshold and reclaimed above it.
4. **`/harness run` declares attended; the routines do not** — plus a guard test that no routine path passes `--attended`, so the unattended ceiling cannot erode by edit.
5. **Record it** — `CONTEXT.md` `loop:` block (the new `attended_idle_minutes` key), `specs/features/verb-model.md`, `commands/harness.md`. (ADR 0011 is already written.)

Item 2 alone fixes the breaker half and is shippable without 3; item 3 alone fixes the sweep half. Both need 1.

## Risks / unknowns

- **Attendance is a claim, not an observation.** A run declared attended and then abandoned escapes the spend ceiling until `attended_idle_minutes`. Mitigated by that threshold plus the routine-path guard (item 4), not eliminated.
- **The sweep is the subtlest code in the repo** (#216, #254, #255 all corrected it). Adding a mode to its threshold resolution is the risky part of this proposal, not the breaker change.
- **The breaker's trips are invisible.** Exit 4 records no event, so there is no denominator for "how often did this actually cost a run" — before or after. Worth a separate ticket in the spirit of ADR 0009; without it, this change's effect cannot be measured from the ledger.
- **What would invalidate the recommendation:** evidence that the attended trips are rare and that the reclamation half dominates — then item 3 (or B) alone is the whole fix and the flag is not worth carrying. The ledger cannot settle this today, for the reason above.
