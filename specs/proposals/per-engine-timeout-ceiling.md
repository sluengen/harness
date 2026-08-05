<!-- guidance:template-proposal@0.1.2 -->
---
proposal: per-engine-timeout-ceiling
status: rejected
date: 2026-08-02
related: [specs/proposals/harden-loop-layer.md, specs/decisions/0009-verb-attempt-telemetry.md]
---

# Proposal: split `engine_timeout_seconds` per engine, or keep one ceiling

> `CONTEXT.md` records that one timeout knob serving both the design and review engines is "the underlying mis-fit to revisit". Now that both verbs record latency, the ledger can settle it — and it does not support the split.

## Problem / motivation

`engine_timeout_seconds` is a single per-subprocess ceiling applied to two
different engine invocations: `design` (opus, plan mode, studies a whole
worktree) and `review` (`claude -p` / `codex exec`, reads a diff). When it was
raised 600 → 720 on 2026-07-30, the rationale recorded in `CONTEXT.md:42` named
the coupling as a known defect:

> the design engine (studies a whole worktree) is systematically slower than the
> review engine (reads a diff), so one knob for two workloads is the underlying
> mis-fit to revisit.

If that is true, one knob is genuinely wrong: it must be set from design's tail,
which leaves review's ceiling far looser than review needs, so a hung review
burns the full design budget before it is killed. The cost of doing nothing
would be a review engine that can hang for 720s when its own honest ceiling is
much lower.

**That premise was never measured.** It could not be: as ADR 0009 records,
`review` carried only `created_at`, so review engine latency was not
reconstructable — the 600 → 720 decision turned entirely on *design* durations,
with review's distribution assumed rather than observed. Items 4 and 5 of
`verb-telemetry` (#264, #265) closed that gap. The data now exists.

**Measured 2026-08-02 from `.harness/harness.db`**, excluding inherited reviews
and the one `engine_timeout` kill (which is censored at the ceiling, not a real
duration):

| | n | min | q1 | median | q3 | max | mean |
|---|---|---|---|---|---|---|---|
| `design` | 16 | 232s | 289s | 366s | 447s | 561s | 373s |
| `review` | 24 | 195s | 279s | 321s | 457s | 587s | 347s |

The two distributions are not meaningfully different. Design's median is 45s
higher; review's **q3 is higher** (457 vs 447) and review's **max is higher**
(587 vs 561). Each has one run past 560s. Whatever else is true, "design is
systematically slower" is not what the ledger shows — and the direction of the
tail, which is the only part a timeout ceiling interacts with, slightly favours
review.

So the motivating problem for this proposal is mostly absent. What remains is
the smaller question of whether to split anyway on structural grounds.

## Options

**Option A — keep one ceiling; correct the record.** · Leave
`engine_timeout_seconds` as one value; delete the "one knob for two workloads"
claim from `CONTEXT.md:42` and replace it with the measurement above. ·
Trade-offs: no new config surface, no second knob to drift, and the ceiling is
set from the pooled tail of both verbs, which is what the data supports. Costs
the ability to tune the two independently if they diverge later — recoverable by
re-running this measurement, which is now a one-line query.

**Option B — split into `design_timeout_seconds` / `review_timeout_seconds`.** ·
Two keys in the `loop:` block, each read by its verb, both defaulting to today's
value. · Trade-offs: allows independent tuning, but encodes a distinction the
evidence does not show. It doubles the config surface every consumer repo
inherits (and which the bootstrap template only just started shipping), adds a
second value that can drift from the first, and needs a migration path for repos
setting the existing key. Buys nothing measurable today.

**Option C — split on the real variance driver instead.** · The spread within
each verb (232–561s for design, 195–587s for review) is far wider than the gap
*between* them, so the variance is driven by something other than which engine
runs — most likely ticket size and diff size, which both verbs see for the same
ticket. A ceiling derived per-ticket, or scaled from diff size, would track the
actual signal. · Trade-offs: strictly more capable and strictly more complex — a
derived ceiling is harder to reason about when it fires, and "the engine was
killed at a number nobody configured" is a worse failure to debug than a flat
one. No evidence yet that flat-720 is costing anything: exactly one timeout kill
appears in the ledger, against a design run that was genuinely stuck.

## Recommendation

**Option A.** The proposal that prompted this exists because of a claim about
the two engines' relative speed; the claim does not survive contact with the
ledger. Splitting now would add a knob, a default, a template line, and a
migration to encode a difference of 45 seconds of median that reverses sign at
the tail.

This is `engineering-principles` on premature abstraction and smallest change:
two knobs are justified when two quantities are observed, and here one quantity
is observed with noise. It is also the same reasoning #260 applied in the
opposite direction — it *collapsed* two values into one on the grounds that they
were one quantity seen from two directions, and that collapse is exactly what
made the wall-clock breaker and reclamation impossible to drift apart.

Option C is the one worth keeping alive, but not now: it should wait for an
observed failure (a legitimately slow run killed at 720, or a hang that 720 let
run too long) rather than being built against a distribution whose tail has one
data point on each side.

The residual work is small and already has a home: **#291's AC-4** rewrites
`CONTEXT.md:42`. That rewrite should drop the "one knob for two workloads is the
underlying mis-fit to revisit" clause and cite this measurement, rather than
leaving a documented defect that the data says is not one.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| Split the ceiling per engine, or keep one? (recommendation: keep one — Option A) | user | this proposal; the rationale lands in `CONTEXT.md:42` via #291 |
| If keeping one: fold the record correction into #291's AC-4, or file it separately? (recommendation: fold — it is the same comment, and splitting it invites two half-edits) | user | #291 |

No cross-cutting architecture decision either way: this is one config key's shape,
not a contract other work must honour, so nothing lands in `specs/decisions/`.

## Breakdown

If **Option A** (recommended): no new change specs. One amendment to the
existing #291 — extend AC-4 so the rewritten `CONTEXT.md:42` comment also drops
the "mis-fit to revisit" clause and cites the measured distributions. This
proposal is the record of why.

If **Option B**: two changes —
1. Split the key in `harness/loop_budget.py` (`LoopBudget` gains a second field;
   `design.py` and `review.py` each read their own), with the old key honoured as
   a fallback for repos that set it.
2. Update `templates/CONTEXT.template.md`, `CONTEXT.md`, and the anti-drift guard
   from #291's AC-3 to cover both keys.

## Risks / unknowns

- **Sample size and window.** 16 design and 24 review durations, all from
  2026-07-31 to 2026-08-02, all from this one repo. Enough to refute a claim of a
  *systematic* difference; not enough to characterise either tail precisely. The
  recommendation is "the evidence does not support splitting", not "the two are
  proven identical".
- **A model confound sits underneath, unrecorded.** `design` events record
  `model: opus`; `review` events record **no model at all** (the payload has no
  `model` key), and per-ticket model tiering (#177) meant review may not have run
  a fixed model. So the comparison is between two verbs whose models may differ,
  and the ledger cannot say how. If review has been running a cheaper model and
  later moves to opus, its distribution could shift and this measurement would
  need re-running. That is an argument for recording review's model, not for
  splitting the timeout. *(Both halves of this confound have since closed: #293
  records `model` on the review event, and #321 retired the per-ticket mechanism
  for one configured value — so a re-run of this measurement would now be able to
  say which model each side ran. The recommendation it supports is unchanged.)*
- **The censored point.** Design's one `engine_timeout` at 721s is a right-censored
  observation: the true duration is unknown and unbounded. Design's tail is
  therefore slightly understated relative to review's. It is one event, and it
  does not close a 110-second q3 gap that runs the other way, but it is the single
  fact most capable of changing the conclusion if it recurs.
- **What would invalidate the recommendation:** repeated `engine_timeout` kills
  concentrated in one verb. That is the observation the split was hypothesised
  from, and it is now directly queryable — `harness stats` reports latency median
  and max per verb, so re-testing this costs one command rather than the
  archaeology ADR 0009 describes.

## Resolution — rejected, 2026-08-02

**Decided: keep one ceiling (Option A).** The split is not built. The claim that
motivated it — that the design engine is systematically slower than the review
engine — is refuted by the measurement above: design leads by 45s at the median
and *trails* at both q3 and max, and the tail is the only part a timeout ceiling
touches. Two knobs are justified when two quantities are observed; here one
quantity is observed with noise, so this is the premature abstraction
`engineering-principles` names, and the mirror of the collapse #260 made in the
opposite direction.

Option C (derive the ceiling from ticket or diff size, the plausible real
variance driver) is **not rejected — deferred**, and deliberately without a
ticket. It should be built against an observed failure, and the ledger holds
exactly one `engine_timeout` kill. The trigger to revisit is stated under
Risks: repeated timeout kills concentrated in one verb, now a one-command check
via `harness stats` rather than the archaeology ADR 0009 describes.

**Where the record correction landed.** #291 shipped mid-proposal (`6abe850`,
merged `900e1c4`) and its AC-4 rewrote the first half of `CONTEXT.md:42` — the
default-divergence clause — while explicitly leaving the one-knob-two-workloads
sentence for this proposal. That sentence still asserts the refuted claim, so
the correction was filed as its own change (#292) rather than folded into a
ticket that had already closed. The hazard folding was meant to avoid (two competing
rewrites of one comment) does not apply: #291's rewrite is already on `dev`, so
the follow-up edits a settled line.

---

**Lifecycle.** A proposal ends in one explicit state: **accepted** (spawn the change specs as Linear issues; record its decisions in the relevant specs), **rejected** (keep this file as the record of why), or **split** (replace with smaller proposals). It does not sit half-decided. Lives in `specs/proposals/`.
