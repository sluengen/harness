---
proposal: drift-reconvergence
status: accepted         # draft | under-decision | accepted | shipped | rejected | split
date: 2026-08-28
related: [rebase-stable-certification, plugin-surface]
---

# Proposal: a slow gate turns base drift from a cost into an exponential

> `commands/build.md`'s post-verdict drift rule re-enters reconciliation, delta review, the full gate and the final verdict every time the integration branch moves underneath a candidate. In this repo that is cheap and rare. In consuming repos with a slow gate and concurrent agents it is neither: the expected cost to land goes exponential in the product of gate duration and the rate at which other agents push.

## Problem / motivation

The rule is one sentence, `commands/build.md:131`:

> **Post-verdict drift:** if the integration branch moves again and the push loses the race, re-enter reconciliation (its bound counts the attempt), delta review, the complete gate, and the final verdict before trying again. No evidence or verdict follows the old tree into that cycle.

It is correct. A verdict binds to a tree, the tree that ships must equal the tree the verdict covered, and a merge produces a tree no reviewer has read. Nothing below disputes the binding.

What is in dispute is the **cost per retry and the width of the window that triggers it**, because those two multiply. The candidate is exposed to drift from the reconcile through delta review, the full gate, the verdict, and the push. Call that window `W`. Every push to the integration branch inside `W` costs one more iteration — which itself opens a new window of width `W`.

**In this repo that is a rounding error.** The gate is ~20-30s, and the recent ledger is mostly *no base drift at any point* (#472, #489, #492, #500, #503, #510). The rule costs a reviewer round trip a handful of times per quarter.

**In a repo where the gate runs ten minutes and several agents land per hour, the same rule behaves differently.** `W` is dominated by the gate, so `W ≥ 10min` no matter how cheap the rest is. Retrying does not shrink it. Landing now depends on the integration branch happening to be quiet for a ten-minute stretch — a property of the *other* agents, not of the one retrying.

A model, with its inputs named because none of them are measured — this is arithmetic on assumptions, not a finding:

| Input | Assumed | Source |
|---|---|---|
| `W` — reconcile → delta review → gate → verdict → push | 15 min | 10-min gate + review round trip |
| `λ` — pushes to the integration branch by other agents | 8/hr | four agents landing every 30 min |
| `P(no collision in W)` = `e^(−λW)` | `e^(−2)` ≈ **13%** | |
| expected attempts to land = `e^(λW)` | **≈ 7.4** | |

The loop still terminates almost surely — each attempt is independent and `P > 0`. What breaks is the *expected* cost, which is `e^(λW)` and so grows exponentially in the product. That is the difference that matters: at a 25-second gate the rule is a rounding error, and at ten minutes the same rule is an exponential in someone else's push rate.

Note what the exponent implies. Halving the reviewer's share of `W` moves `P` from 13.5% to 18.9% — worth having, and nowhere near enough. Only removing `λ` from the exponent changes the shape, and nothing that makes a retry cheaper can do that.

### This is the revisit condition a prior decision named

[`rebase-stable-certification`](rebase-stable-certification.md) worked this exact problem in the v3 runtime era — `close`'s `reviewed_sha` gate, `harness review --since`, delta-scoped re-certification. It shipped two cheap cause-removals and **closed the re-certification item unbuilt on measurement**: after #266 (stop prescribing a rebase) and #267 (fragment the shared `CHANGELOG.md` append point), the stale-review rate went to zero and every excess-pass run had a cause one of those two fixes removed.

That decision named what would put the work back on the queue. One of its own stated risks:

> **`merge_conflict` is not gone, only its dominant source.** A content conflict on `origin/dev` still costs a merge, a resolution commit, and a full re-review. If that becomes common, item 3's problem returns by a different door.

It has, by that door, in repos other than this one. This proposal is the sanctioned revisit — with one input the 2026-08-01 analysis did not have, because this repo's gate has never been slow enough for it to matter: **`W` is now dominated by gate duration**, which moves the cost from linear in the collision rate to exponential in it.

### What a re-bind actually catches

The current rule is defended by the observation that re-binds find real defects. They do. Derived from `project_loop_engineering_assessment.md` on 2026-08-28, the ledger records **eight** re-binds after base drift. Two named no finding (#436, #462). The other six:

| Ticket | What the re-bind found | Caused by the drift? |
|---|---|---|
| #484 | as-built record said the spine was 97 lines; the merge had made it 98 | **yes** |
| #459 | record said `1863 → 1684` collected tests; the shipping tree had 1691 once dev's 7 new tests merged in | **yes** |
| #435 | the second merge broke #434's contract module and tripped the AC3 sweep | **yes — and the gate is what caught it**, as two test failures |
| #456 | record claimed one other reader of `ship.md`; the ticket itself had already added a second | no — false before the drift |
| #452 | a mutation-kill count contradicting its own table, and a false measured claim of the re-bind's own | no — false before the drift |
| #451 | a `git log`-caller count (two, actually four) and an assertion count the first pass had invalidated itself | no — false before the drift |

**Both drift-caused findings violated a rule this repo already has.** `skills/spec-authoring/SKILL.md:106`, shipped by #470 on 2026-08-17, requires that an as-built record never state a bare present-tense quantity: the figure names the commit it was measured at, or a guard derives it, or the record restates it as the invariant it was evidence for. A 97 that becomes 98 when someone else's commit lands is precisely the class that rule forbids — and #484 shipped it **two days after the rule landed**. The rule is unenforced, and the re-bind has been acting as its enforcement mechanism by accident.

Three patterns, and none of them is *the reviewer re-judged the change*:

1. **Every drift-caused reviewer finding is one class** — a measured count in the reviewer-owned as-built record that the incoming commit falsified. Both of them.
2. **The one genuine code-level integration failure was caught by the gate**, not by a reviewer reading the delta.
3. **Half of the findings were already false before any drift occurred.** They are the yield of a *second read*, not of reconciliation.

That third value is real, and on this evidence it is the larger one. But base drift is an arbitrary trigger for it: it fires on whichever tickets happen to collide, not on whichever records happen to carry a false count.

Six findings from one repo's ledger, and this repo is the *low*-collision, fast-gate case — the weakest available witness for the failure this proposal describes. What transfers is not the rate but the shape: the re-bind's drift-specific yield is concentrated in re-measurement, which is mechanical, while its judgment-shaped yield is incidental to drift.

## Options

**Option A — remove the collision causes, then re-measure.** Find and eliminate the shared insertion points that make concurrent changes conflict by construction: a single `[Unreleased]` changelog block, a version or build field, a barrel/index file every feature appends to, a migration ordinal, a lockfile. Fold the finding into `engineering` and `spec-authoring` as a drift-fragility rule. · *Trade-offs:* cheapest available, and this is precisely what took this repo's rate to zero (#267 removed *the dominant conflict source*). Each fix stands on its own merits whatever the residue turns out to be. But it does nothing to `W`: with a ten-minute gate, a repo with zero conflicts still loses races to any disjoint change that lands during certification.

**Option B — serialize the landing.** A candidate acquires the right to land before it certifies, and holds it through the push; others queue. The race is removed by construction rather than made cheaper to lose. Implementations range from a server-side merge queue (robust, and it is the authoritative-control shape the repo already prefers over client-side hooks) to a lease-with-expiry on a lock ref (cheap, no server support needed). · *Trade-offs:* the only option that **takes `λ` out of the exponent** rather than shrinking the term it multiplies, and so the only one whose benefit does not decay as the repo gets busier. Costs a coordination primitive and introduces a new failure mode — a holder that dies wedges the queue, so the lease must expire and expiry must be observable. Also converts a parallelism problem into a latency one: with a ten-minute gate, a four-deep queue is a forty-minute wait.

**Option C — scope the re-gate on drift.** The full gate certifies the candidate once; a subsequent drift re-merge re-runs a bounded subset — the tests reachable from the union of both diffs — with the full gate on a declared cadence. · *Trade-offs:* attacks `W` directly, which is the term that dominates; a one-minute re-gate makes the race winnable *and* each retry cheap, helping both failure modes at once. But it weakens what a marker asserts, and [#513](https://github.com/sluengen/harness/issues/513) is already open on exactly that gap — *the marker names a hardcoded gate and records nothing about what a selective gate covered*. This option cannot ship before #513 answers it, and should not jump that queue.

**Option D — mechanically-licensed re-bind.** On drift, the existing PASS re-binds to the merged tree without a reviewer round trip when four conditions all hold, each checkable: the merge was a clean auto-merge with no authored bytes; no monotonic-field collision (the trap `build.md:110` already names, and the one case where a clean auto-merge still yields a wrong third state); the gate is green over the merged tree; and every measured claim in the as-built record has been re-derived at that tree. Any failure falls back to today's path. · *Trade-offs:* removes the reviewer cost and closes both drift-caused findings in the table above, at low risk — the gate still runs, so the #435 class is still caught by what caught it. The re-derivation is the only judgment, and it is an enumerable checklist rather than an assessment. But it leaves `W` gate-dominated, so on its own it barely moves the exponent — it makes a losing attempt cheaper without making one less likely.

**Option E — do nothing.** · *Trade-offs:* zero risk here, where the rule costs almost nothing. Leaves consuming repos with a lifecycle whose cost to land is set by how quiet the integration branch happens to be, and that cost falls hardest on unattended `/routine` runs where nobody is watching the retries.

## Recommendation

**A and D now; instrument; B if the residue is real. C waits on #513.**

The sequencing is the same discipline `rebase-stable-certification` applied and was vindicated on: do not buy a structural change to remove a cost the cheap fixes may already remove. What is different this time is that the endpoint is pre-identified rather than open — if the residue is real, **B is the answer, not C or D**. C and D shrink `W`, which the exponent then re-inflates as soon as the repo gets busier; only B removes `λ` from the exponent at all.

- **A and D are independent of the measurement and can proceed immediately.** A is free and precedent says it may be sufficient on its own. D is a strict improvement at any collision rate: it removes a round trip that this repo's own ledger shows yields, on the drift-caused axis, only re-measurement.
- **The instrument is the gating item.** The 2026-08-01 decision rested on being able to read a rate. Nothing currently records a reconcile-after-verdict or its cause, so `λ` and `W` in the table above are assumptions. B is a real coordination primitive and should not be bought on an assumption.
- **The ten-minute gate is a fixed input.** Decided 2026-08-28 (below): it is that slow for reasons that will not move, so the machinery here exists to tolerate it rather than to postpone fixing it. This is the assumption to revisit first if the ordering above stops making sense.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| Does D's record re-derivation violate iron law 4 (*the builder does not write the as-built record*)? The position taken here is that re-measuring an existing claim against a new tree is not authorship, and that the run report naming the drift range keeps it falsifiable — but the law is the operator's to interpret | user | `CLAUDE.md` spine, `commands/build.md` |
| Is landing serialization something the plugin **prescribes**, or something it **requires the repo to declare**? A merge queue is server-side infrastructure the guidance cannot install | user / architect | `specs/decisions/`, spine `branches:` block |
| Does the spine gain a `landing:` key (`free` \| `queued` \| `locked`) so `/build` can read the repo's strategy rather than assume one? | architect | spine config, `plugin-surface.md` |
| Does a scoped re-gate leave the marker meaning anything? Blocks C entirely | — | [#513](https://github.com/sluengen/harness/issues/513) |

## Decisions — 2026-08-28

Taken by the operator on this proposal; each is carried into the breakdown item that implements it.

**D1 — the sequencing stands.** A and D proceed now, item 1 instruments the rate, and Option B is not bought until that instrument reports. Items 1–4 are filed; **item 5 is deliberately unfiled**. This repeats the ordering `rebase-stable-certification` was vindicated on, and the reversal condition is the same: item 1 reporting a residue the cheap fixes did not remove.

**D2 — re-measuring is not authoring; iron law 4 is not engaged.** Under Option D the reviewer still writes every sentence of the as-built record. The builder re-runs only the measurements those sentences cite, against the merged tree, and changes a numeral or removes the claim. It may not add, reframe, or reinterpret — any edit beyond re-deriving an existing measurement returns the record to the reviewer. Item 3 carries this distinction into `commands/build.md` in that wording; a re-bind that cannot be closed by re-derivation alone falls back to today's path.

**D3 — gate duration is an input, not a target.** The affected repos' gates are slow for reasons that will not move, so no ticket is filed against the duration itself and no option here is scored on its ability to shorten it. Recorded so a later reader does not mistake the omission for an oversight.

## Breakdown

1. **Instrument reconcile-after-verdict.** Record each occurrence with its cause (disjoint drift / textual conflict / monotonic collision) and the elapsed certification window, so `λ` and `W` become readable. Nothing else here should be decided on assumptions. — `simple` Filed as [#515](https://github.com/sluengen/harness/issues/515).
2. **A drift-fragility rule in `engineering` and `spec-authoring`.** Name the shared-insertion-point class (single-block changelog, version field, barrel file, migration ordinal) and require new work to avoid creating one. This is #267's lesson generalised from a fix into guidance. — `simple` Filed as [#516](https://github.com/sluengen/harness/issues/516).
3. **The mechanically-licensed re-bind** (Option D). Rewrite `commands/build.md:131` to carry the four conditions and the fallback, and regenerate `skills/command-build/SKILL.md` (generated by `scripts/generate_codex_artifacts.py`, held by the gate's codex drift stage). — `simple` Filed as [#517](https://github.com/sluengen/harness/issues/517).
4. **Enforce the present-tense-quantity rule that already exists.** `spec-authoring:106` (shipped by #470) forbids the exact class both drift-caused findings belong to, and #484 violated it two days later. Nothing checks it. Give it a guard, or a reviewer-side check on the record-writing path. This is not new policy — it is an unenforced rule doing no work. — `simple` Filed as [#518](https://github.com/sluengen/harness/issues/518).
5. **Landing serialization** (Option B) — *conditional on item 1's measurement.* Spine `landing:` key, the acquire/hold/release discipline in `/build`'s ship stage, lease expiry, and the wedged-holder path. — `complex`

Items 1–4 are independent of each other and of the measurement, and are filed (#515, #516, #517, #518). **Item 5 is not filed** — per D1 it waits on item 1's instrument.

## Risks / unknowns

- **Nothing from the affected repos is measured.** The ordering rests on transferring this repo's cause distribution to repos that may not share it — and this repo is the low-collision, fast-gate case, so it is the weakest possible witness for the failure being described. Item 1 exists because of this, and it should land before item 5 is filed.
- **The tally is eight re-binds, six carrying findings, from one repo's ledger.** Enough to show *what shape* a re-bind finding takes; not enough to bound how often a re-bind would catch something D's four conditions let through. The named residual: a change on the integration branch that falsifies the reviewed *rationale* without breaking the gate and without touching a count — dev landing a guard the candidate should have satisfied, or already fixing the same bug. D is blind to that class by construction.
- **A lock's failure mode is worse than a lost race.** A wedged queue stops every agent, where today a losing candidate merely retries. Expiry and observability are not optional parts of item 5.
- **Serialization trades throughput for predictability.** With a slow gate, a queue converts concurrent agents into a waiting line. If that latency is unacceptable the real ticket is gate duration, not coordination — which loops back to the third bullet of the recommendation.
- **Item 4 is a guard over prose, and ADR 0017 D5 constrains what a guard may assert.** A guard may assert code behaviour, a spine property, asset integrity, frontmatter, or tree consistency — never what prose *means*. "Is this numeral anchored?" sits close to that line, and item 4's first job is to establish which side it falls on. If it cannot be guarded within D5, the reviewer-side check is the answer and the item shrinks accordingly.
- **Removing a count is a deletion.** Where item 4's remedy is to drop a figure rather than anchor it, #492's lesson applies: prove the surviving sentence still says something true without it.
