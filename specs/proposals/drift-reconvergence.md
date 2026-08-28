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

*Corrected 2026-08-28 after independent review — the first version of this table contained an error, and the correction changes the conclusion's basis. See* Amendments *below.*

The current rule is defended by the observation that re-binds find real defects. They do. Every re-bind in `project_loop_engineering_assessment.md`, ordered by commit timestamp rather than ledger position:

| # | Shipped | What the re-bind found | Caused by the drift? |
|---|---|---|---|
| #435 | 08-16 00:45 | integration failures — **the gate caught them**, as test failures | yes, but not by the reviewer |
| #436 | 08-16 14:18 | nothing recorded | — |
| #451 | 08-17 00:03 | two false counts (`git log` callers; an assertion count) | no — false already |
| #452 | 08-17 00:26 | a mutation-kill count contradicting its own table | no — false already |
| #459 | 08-17 00:36 | collected tests 1684 vs 1691 after seven merged in | **yes** |
| #456 | 08-17 06:12 | the `ship.md` reader count | no — false already |
| #462 | 08-17 11:04 | three unanchored present-tense counts in the record | no — false already |
| #484 | 08-19 11:07 | the spine's 97 lines, which the merge made 98 | **yes** |

**Seven of eight found something.** On its face that argues for keeping the stage. It does not, because of *what* they are:

1. **Six of the seven are counts in an as-built record.** The single exception is #435's, and the **gate** is what caught it — the ledger records both as test failures the merge surfaced.
2. **No re-bind in this ledger has ever produced a judgment about the change under review.** Not one. The stage is defended as a second look at the work; its entire recorded yield is re-measurement.
3. **Both drift-caused findings violated a rule this repo already has.** `skills/spec-authoring/SKILL.md:106`, shipped by #470 on 2026-08-17, forbids a bare present-tense quantity in an as-built record. #484 shipped one **two days after the rule landed**. Base drift has been acting as that rule's enforcement mechanism by accident.

### The tally that defends the stage cannot fail

The ledger carries a running score — #456 is *"the third time"*, #462 is *"4 for 4"*, #484 is *"5 for 5"*. The counted set is #451, #452, #456, #462, #484. It excludes #435 and #436, and it excludes **#459, whose re-bind found a real defect**.

The denominator only ever increments alongside the numerator. No entry anywhere reads *"re-bind found nothing — now 5 for 6."* It is a streak counter structurally incapable of recording a miss — the vacuity shape `craft.md` already names, sitting inside the tally that justifies a review stage.

Neither "5 for 5" nor a naive "1 of 8" is a usable yield figure. The usable statement is: **six of seven reviewer-only findings were counts in a record, and the one integration failure was caught by the gate.**

One repo's ledger, and the low-collision, fast-gate case at that — the weakest available witness for the failure this proposal describes. What transfers is the shape, not the rate.

## Options

**Option A — remove the collision causes, then re-measure.** Find and eliminate the shared insertion points that make concurrent changes conflict by construction: a single `[Unreleased]` changelog block, a version or build field, a barrel/index file every feature appends to, a migration ordinal, a lockfile. Fold the finding into `engineering` and `spec-authoring` as a drift-fragility rule. · *Trade-offs:* cheapest available, and this is precisely what took this repo's rate to zero (#267 removed *the dominant conflict source*). Each fix stands on its own merits whatever the residue turns out to be. But it does nothing to `W`: with a ten-minute gate, a repo with zero conflicts still loses races to any disjoint change that lands during certification.

**Option B — serialize the landing.** A candidate acquires the right to land before it certifies, and holds it through the push; others queue. The race is removed by construction rather than made cheaper to lose. Implementations range from a server-side merge queue (robust, and it is the authoritative-control shape the repo already prefers over client-side hooks) to a lease-with-expiry on a lock ref (cheap, no server support needed). · *Trade-offs:* the only option that **takes `λ` out of the exponent** rather than shrinking the term it multiplies, and so the only one whose benefit does not decay as the repo gets busier. Costs a coordination primitive and introduces a new failure mode — a holder that dies wedges the queue, so the lease must expire and expiry must be observable. Also converts a parallelism problem into a latency one: with a ten-minute gate, a four-deep queue is a forty-minute wait.

**Option C — scope the re-gate on drift.** The full gate certifies the candidate once; a subsequent drift re-merge re-runs a bounded subset — the tests reachable from the union of both diffs — with the full gate on a declared cadence. · *Trade-offs:* attacks `W` directly, which is the term that dominates; a one-minute re-gate makes the race winnable *and* each retry cheap, helping both failure modes at once. But it weakens what a marker asserts, and [#513](https://github.com/sluengen/harness/issues/513) is already open on exactly that gap — *the marker names a hardcoded gate and records nothing about what a selective gate covered*. This option cannot ship before #513 answers it, and should not jump that queue.

**Option D — mechanically-licensed re-bind.** On drift, the existing PASS re-binds to the merged tree without a reviewer round trip when four conditions all hold, each checkable: the merge was a clean auto-merge with no authored bytes; no monotonic-field collision (the trap `build.md:110` already names, and the one case where a clean auto-merge still yields a wrong third state); the gate is green over the merged tree; and every measured claim in the as-built record has been re-derived at that tree. Any failure falls back to today's path. · *Trade-offs:* removes the reviewer cost and closes both drift-caused findings in the table above, at low risk — the gate still runs, so the #435 class is still caught by what caught it. The re-derivation is the only judgment, and it is an enumerable checklist rather than an assessment. But it leaves `W` gate-dominated, so on its own it barely moves the exponent — it makes a losing attempt cheaper without making one less likely.

**Option E — do nothing.** · *Trade-offs:* zero risk here, where the rule costs almost nothing. Leaves consuming repos with a lifecycle whose cost to land is set by how quiet the integration branch happens to be, and that cost falls hardest on unattended `/routine` runs where nobody is watching the retries.

## Recommendation

**A and D now; read the rate; B if the residue is real. C waits on #513.**

The sequencing is the same discipline `rebase-stable-certification` applied and was vindicated on: do not buy a structural change to remove a cost the cheap fixes may already remove. What is different this time is that the endpoint is pre-identified rather than open — if the residue is real, **B is the answer, not C or D**. C and D shrink `W`, which the exponent then re-inflates as soon as the repo gets busier; only B removes `λ` from the exponent at all.

- **A and D are independent of the measurement and can proceed immediately.** A is free and precedent says it may be sufficient on its own. D is a strict improvement at any collision rate: it removes a round trip that this repo's own ledger shows yields, on the drift-caused axis, only re-measurement.
- **Reading the rate is the gating step**, not building an instrument to read it with. *Amended 2026-08-28: the instrument this bullet originally called for was filed as #515 and closed unbuilt — the taxonomy and `λ` are recoverable from git retrospectively, and `W` is measured by timing the gate once. The gate on B is unchanged in substance: it is still not bought on an assumption. What changed is that satisfying it costs a query rather than a build-and-wait.*
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

1. **Instrument reconcile-after-verdict.** Record each occurrence with its cause (disjoint drift / textual conflict / monotonic collision) and the elapsed certification window, so `λ` and `W` become readable. Nothing else here should be decided on assumptions. — `simple` Filed as [#515](https://github.com/sluengen/harness/issues/515) — **closed unbuilt 2026-08-28**, see *Amendments*.
2. **A drift-fragility rule in `engineering` and `spec-authoring`.** Name the shared-insertion-point class (single-block changelog, version field, barrel file, migration ordinal) and require new work to avoid creating one. This is #267's lesson generalised from a fix into guidance. — `simple` Filed as [#516](https://github.com/sluengen/harness/issues/516).
3. **The mechanically-licensed re-bind** (Option D). Rewrite `commands/build.md:131` to carry the four conditions and the fallback, and regenerate `skills/command-build/SKILL.md` (generated by `scripts/generate_codex_artifacts.py`, held by the gate's codex drift stage). — `simple` Filed as [#517](https://github.com/sluengen/harness/issues/517).
4. **Enforce the present-tense-quantity rule that already exists.** `spec-authoring:106` (shipped by #470) forbids the exact class both drift-caused findings belong to, and #484 violated it two days later. Nothing checks it. Give it a guard, or a reviewer-side check on the record-writing path. This is not new policy — it is an unenforced rule doing no work. — `simple` Filed as [#518](https://github.com/sluengen/harness/issues/518) — **rewritten 2026-08-28**, see *Amendments*.
5. **Landing serialization** (Option B) — *conditional on item 1's measurement.* Spine `landing:` key, the acquire/hold/release discipline in `/build`'s ship stage, lease expiry, and the wedged-holder path. — `complex`

Items 1–4 were filed as #515, #516, #517 and #518. **Item 5 was never filed** — per D1 it waited on item 1's instrument, and item 1 has since been closed unbuilt, which changes how item 5 would be decided. See *Amendments*.

## Risks / unknowns

- **Nothing from the affected repos is measured.** The ordering rests on transferring this repo's cause distribution to repos that may not share it — and this repo is the low-collision, fast-gate case, so it is the weakest possible witness for the failure being described. Item 1 exists because of this, and it should land before item 5 is filed.
- **The tally is eight re-binds, seven carrying findings, from one repo's ledger.** Enough to show *what shape* a re-bind finding takes; not enough to bound how often a re-bind would catch something D's four conditions let through. The named residual: a change on the integration branch that falsifies the reviewed *rationale* without breaking the gate and without touching a count — dev landing a guard the candidate should have satisfied, or already fixing the same bug. D is blind to that class by construction.
- **A lock's failure mode is worse than a lost race.** A wedged queue stops every agent, where today a losing candidate merely retries. Expiry and observability are not optional parts of item 5.
- **Serialization trades throughput for predictability.** With a slow gate, a queue converts concurrent agents into a waiting line. If that latency is unacceptable the real ticket is gate duration, not coordination — which loops back to the third bullet of the recommendation.
- **Item 4 is a guard over prose, and ADR 0017 D5 constrains what a guard may assert.** A guard may assert code behaviour, a spine property, asset integrity, frontmatter, or tree consistency — never what prose *means*. "Is this numeral anchored?" sits close to that line, and item 4's first job is to establish which side it falls on. If it cannot be guarded within D5, the reviewer-side check is the answer and the item shrinks accordingly.
- **Removing a count is a deletion.** Where item 4's remedy is to drop a figure rather than anchor it, #492's lesson applies: prove the surviving sentence still says something true without it.


---

## Amendments — 2026-08-28

The four filed items were reviewed the same day by the session that ran `/build 511`, which culled two of them and asked for its reasoning to be attacked rather than ratified. What follows is the settled state, including a correction to this proposal's own evidence.

### The evidence table was wrong, and the correction strengthens the conclusion

The original table recorded #462's re-bind as finding nothing. It found three unanchored present-tense counts. The error was reading the ledger's summary line for #462 and not its detail bullets. The corrected table is above; **seven of eight re-binds found something, not six**, and the conclusion changed basis: not *the re-bind rarely finds anything*, but **every reviewer-only finding it has ever produced is a count in an as-built record**.

The ledger's own "5 for 5" tally was also examined and is unsound: its denominator only increments when a re-bind finds something, so it cannot record a miss. Both the tally defending the stage and this proposal's first attempt to measure it were wrong — which is a better argument for item 3 than either version made.

### Item 1 (#515) — closed unbuilt, and the closure was tested

Closed on the argument that the data is already in git: post-verdict drift leaves merge commits, parents, and timestamps, so a query beats an instrument that must be built, adopted, and waited on.

The closure named its own weak point — whether `monotonic` collisions are detectable retrospectively. **They are.** Measured on 2026-08-28 with a scratch repo: both sides advancing `version: 1→2` independently produce a clean merge with zero conflicts, and intersecting each parent's `old → new` line replacements against the merge base detects it. It fires on the pure case and on the realistic mixed-change case, and stays silent on a control where both sides edit the same file in different regions.

One trap worth carrying: a **whole-file** diff comparison passes the pure fixture and **misses** the mixed-change one. The detector must work at replacement granularity. Build it against the mixed fixture first.

What the retrospective route does not recover: **which** merges were post-verdict, since git has no record of when a verdict was issued. Counting all reconciliation merges is an upper bound, which is what this proposal's model needed. `W` was never a historical question — it is measured by timing the gate once.

**The closure stands.**

### Item 4 (#518) — rewritten, then partly overturned

Rewritten to cut `spec-authoring:106` from three remedies to one — *an as-built record carries no counts*, with a derived escape — on the grounds that a guard over this predicate is unavailable (ADR 0017 D5, iron law 2 as amended by `5bd1660`, and #511's measured cost of attempting one). That diagnosis is correct and is not disputed.

The rewrite named its own reversal condition: a load-bearing count in `specs/features/plugin-surface.md` that the derived escape cannot cover. **Two exist**, at `:144` and `:145` — the three sweep shapes named outside the craft file, and the process filing split *stated seven times*, the latter existing so the next editor knows how many places to keep in step. Neither is derived, and `:146` of the same document states that neither can be: *"No test holds the assessment guidance recorded above… That is D5 working as written, not an oversight."*

#470's body also records why anchoring exists: it was operator-promoted from the proposals ledger at an `/assess` drain, converging *"four false or **unreconstructable** measured claims"*. Anchoring is the remedy for the unreconstructable case.

**Settled position: two remedies — anchor or derive.** Drop *restate as the invariant*, which no violation ever needed. An anchored count is drift-proof by construction, so this delivers what the rewrite wanted without deleting what no guard can reconstruct.

One further correction, of the same shape the reviewer flagged in its own rationale: the rewrite moved from *no guard is possible* (supported) to *no enforcement point is needed* (not). Amended law 2 says guidance is verified **by using it** — an enforcement mode, not an absence. #470's rule was already clear and was violated two days after landing, so clarity was never the binding constraint. The reviewer writes the as-built record on PASS (`skills/spec-authoring/SKILL.md:100`), which is the non-guard enforcement point.

### Item 3 (#517) — unchanged, better evidenced

Condition 4 still dies, but via anchoring rather than deletion: an anchored count cannot be falsified by a later merge, so nothing needs re-deriving at merge time. The design drops to two conditions — clean auto-merge with no monotonic-field collision, plus a green gate over the merged tree.

### The residual, demonstrated

The risk this proposal named — *an incoming change that falsifies the reviewed rationale without breaking the gate and without touching a count* — occurred **to this proposal's own tickets, within hours of filing**. `5bd1660` amended iron law 2 and invalidated acceptance criteria on #516, #517 and #518 while the gate stayed green throughout. Nothing mechanical caught it; reading the incoming range did.

That is evidence the two surviving conditions are necessary but not sufficient, and item 3 should say so rather than implying they are.
