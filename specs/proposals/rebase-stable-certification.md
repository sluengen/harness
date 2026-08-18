---
proposal: rebase-stable-certification
status: shipped          # draft | under-decision | accepted | shipped | rejected | split
date: 2026-07-30
related: [run-ledger, verb-model, 0008-inherited-ledger-events, resume-earned-stages]
---

# Proposal: a re-certification that costs a full review buys nothing when the tree did not change

> When a run's HEAD moves for a reason that leaves earlier hunks byte-identical, the close gate's HEAD binding invalidates the passing review wholesale and the engine re-reviews the whole change to re-learn a verdict it already gave. This proposed removing the *causes* first and only then, if the residue justified it, narrowing the re-certification itself.

**This file is recorded retrospectively, on 2026-08-01.** The proposal was decided on 2026-07-30 and its three breakdown items were filed together at 03:26Z that day ([#266](https://github.com/sluengen/harness/issues/266), [#267](https://github.com/sluengen/harness/issues/267), [#268](https://github.com/sluengen/harness/issues/268)); the file itself never landed, and the accompanying ADR 0010 was cited by number without landing either — the same state `specs/features/run-ledger.md` records for ADR 0009. It is written now because #268's Precondition names this path as where its measurement and decision must be recorded. Everything below is drawn from the three tickets and the run ledger; no deliberation is reconstructed beyond what those record.

## Problem / motivation

`close`'s gate binds a passing review to an exact `reviewed_sha` and refuses `stale_review` once HEAD moves. That binding is correct and load-bearing — it is what makes "a recorded pass" mean "a pass over the tree that is about to merge". But it is indifferent to *why* HEAD moved. A conflict resolution or a rebase can leave most of the change byte-identical and still cost a full engine re-review.

The cost measured when the proposal was written: **260 `pass` events across 222 runs** (38 more passes than runs), and **18 runs with ≥2 distinct passing SHAs and no intervening `fail`** — 24 review cycles that produced no finding.

That number was an **upper bound on the opportunity, not a measured rate of the problem**. At the time `close` recorded nothing when it refused, so how often a run actually hit `stale_review` was unobservable. Two suspected causes were cheap to remove and one fix was expensive, which set the ordering below.

## Options

**Option A — remove the causes, then re-measure.** Fix the two things that were making HEAD move unnecessarily, then read the residual rate off the telemetry before building anything else. · *Trade-offs:* cheap, and each fix stands on its own merits regardless of what the residue turns out to be. Defers the benefit if the residue is large.

**Option B — `harness review --since <sha>`.** The engine reviews `git diff <sha>..HEAD` — the resolution only — and the recorded pass names the source pass it extends; `close`'s gate accepts it only atop a verified ancestor pass. · *Trade-offs:* addresses the residue directly, and fits [ADR 0008](../decisions/0008-inherited-ledger-events.md)'s rule for an event asserting what the emitting verb did not observe. But it is a **gate change** — new fields on `ReviewEventData`, a shared ancestor-pass predicate used by both `review` at write time and `close` at read time, and a new refusal on the close path — and every gate change is a chance to weaken the thing the loop rests on.

**Option C — recomputed merge tree.** Compare the post-move tree against the reviewed one and re-certify if they match. · *Trade-offs:* narrower than B and does not help when the resolution genuinely changes content. Held as a fallback.

**Option D — do nothing.** · *Trade-offs:* zero risk; leaves the waste, which falls on long unattended runs where no human is watching the spend.

## Recommendation

**A first, then decide B on the measured residue.** Ship the two cheap fixes, ship the telemetry that makes the rate readable, and treat B as conditional on what the rate then shows. This is `engineering-principles`' smallest-change discipline applied to sequencing: do not pay for a gate change to remove a cost that the cheap fixes may have already removed.

## Breakdown

1. **#266 — `close`'s merge-conflict message must stop prescribing a rebase.** Shipped 2026-07-31 (tick #137). The message told a conflicted run to rebase; `close` merges in a detached throwaway worktree and integrates the base itself, so base movement never needed a rebase — and a rebase rewrites every SHA, invalidating the passing review for hunks it never touched. The message was manufacturing the very re-certifications this proposal set out to remove.
2. **#267 — the changelog moves to `changelog.d/` fragments.** Shipped 2026-07-31 (tick #148). Every ticket appended to one `[Unreleased]` block, so two concurrent runs conflicted at the same insertion point by construction. This was the dominant conflict source.
3. **#268 — `harness review --since`: delta-scoped re-certification.** **Closed unbuilt on the measurement below.**

## Decision — item 3 is retired, not deferred

Measured on 2026-08-01, after items 1 and 2 had both landed.

**The `stale_review` rate is zero.** [#263](https://github.com/sluengen/harness/issues/263) made `close`'s gate refusals recordable; the instrumented window runs from the first close carrying an `outcome` field (2026-07-31T10:43:29Z) to 2026-07-31T13:48:18Z and covers **7 close attempts**. Across them there are **no `stale_review` refusals and no gate refusals of any kind** — and no event anywhere in the ledger, of any age, carries `stale_review`. Two closes failed, both `merge_conflict` against `origin/dev`, both on `CHANGELOG.md`.

Seven attempts is a thin window, so the decision does not rest on it. It rests on **attribution**: every excess-pass run in the post-fix era has a named cause, and each cause is one the shipped items removed.

| Run | Ticket | Why HEAD moved after a pass | Removed by |
|---|---|---|---|
| `01KYV5ZC131PHGJYKBKN8E5A02` | #249 | a **rebase**, performed under the prescription #266 deleted | #266, merged 05:44:02Z — two minutes after that run's second pass |
| `01KYW01ANPB1APE498R39VR7EW` | #253 | `CHANGELOG.md` merge conflict | #267 |
| `01KYW071G5AW9GYSFPGH95094C` | #269 | `CHANGELOG.md` merge conflict | #267 |

Those are all three of the excess-pass runs on 2026-07-31, against a long-run base rate of 26 such runs / 33 excess cycles across 244 reviewed runs (~10%). The one run since #267 landed reviewed once and closed first try.

**The mechanism argues the same way, independently of the counts.** `--since` requires the source pass's SHA to be an **ancestor** of the new HEAD. That holds on the merge-resolution route — merge `origin/<base>` in, commit, re-review — and fails after a genuine rebase, where no commit on the branch is the one that passed. So `--since` never served the case in #268's own title; it served the merge route. #266 made that route the prescribed one and removed the pressure to rebase, and #267 removed the conflicts that sent runs down it. The remaining trigger is a genuine content conflict on `origin/dev` — rare, and one where the resolution is exactly the part a reviewer should read.

Against that: the work is a change to both gate surfaces (`review`'s write path and `close`'s read path), adding a fifth `CertificationVerdict`, a new close refusal, and a predicate that makes certification no longer a ledger-only question. That is a real, permanent widening of the gate's surface area, bought for a cost the two cheap fixes appear to have already removed.

**Decision: close #268 unbuilt.** The design work is not lost — it is on the ticket, and the ADR 0008 framing it developed stands for whatever needs it next.

### What would revisit this

Any of the following puts the work back on the queue, and the second is the one to watch:

- a recorded `stale_review` refusal on the `close` path, readable via `harness stats`;
- an excess-pass run — two distinct passing SHAs with no intervening `fail` — whose cause is **not** attributable to #266 or #267;
- the long-run ~10% excess rate failing to fall as the instrumented window widens past a few dozen closes.

The first two are single events, so this does not depend on anyone re-running the analysis on a schedule.

## Risks / unknowns

- **The window is short.** Seven instrumented closes cannot distinguish "zero" from "rare". This is why the reversal conditions above are single-event triggers rather than a rate threshold.
- **`merge_conflict` is not gone, only its dominant source.** A content conflict on `origin/dev` still costs a merge, a resolution commit, and a full re-review. If that becomes common, item 3's problem returns by a different door — and the trigger list above catches it.
- **ADR 0010 never landed.** With item 3 retired there is no decision left for it to record; the reasoning that would have gone in it is in the Decision section above.
