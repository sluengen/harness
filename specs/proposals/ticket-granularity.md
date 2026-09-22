---
proposal: ticket-granularity
status: under-decision   # draft | under-decision | accepted | shipped | rejected | split | superseded
date: 2026-09-22
related: [do-less-at-ingestion]
---

# Proposal: file at the granularity of a build run

> Every filing decision in the harness is made about one ticket, at the moment of discovery, and is never revisited. Two consuming repos measured the result in the same week: 28 tickets absorbed by four hand-run consolidation passes in eight days, and nine tickets where five would do in a single assessment. Four changes — a co-change test at filing, a materiality floor, a batch pass at the four surfaces that file more than one ticket, and a premise-and-size re-check at pull.

## Grounding

Verified against `497f416` (merge of #703), 2026-09-22. Every anchor below was read this session.

- **The spine's *Filing* rule is keyed to surface** (`AGENTS.md:54`): "search the open queue and extend an unstarted ticket **on the same surface** instead of creating a twin." It catches duplicates. Nothing in it reaches a *co-change* — findings on different surfaces that one builder would fix in one sitting.
- **`/assess` files one ticket per finding and says so** (`skills/assess/SKILL.md:57`): "For every finding, create an issue … Triage happens in the tracker, not at report time." An assessment walks a tree and emits one finding per site, so the instrument's granularity becomes the queue's.
- **`/drain` already carries a partial consolidation rule** (`skills/drain/SKILL.md:44`): "group entries whose suggested home is the same file, abstract several small ones into the pattern-level candidate." It exists in one skill, binds one pile, and is keyed to the file a fix lands in rather than to the sitting that would do it.
- **`/propose` files one issue per breakdown item** (`skills/propose/SKILL.md:50`), and `authoring` gives the breakdown an ordering rule with no sizing rule: "Order the breakdown by cost of being wrong, not by what ships alone" (`skills/authoring/SKILL.md:42`). `tracker` adds "split by what can proceed independently, not by what is shippable alone" (`skills/tracker/SKILL.md:74`). Three rules about *order* and *independence*; none about *size*.
- **The finding bar has no materiality test.** `skills/assess/references/finding-bar.md:11-13` tests specificity, evidence and hypotheticals. The floor that would refuse a ticket for a stale comment lives in `review-discipline` and `tracker` → `ledger`, and is never applied at the moment a steward's finding becomes an issue.
- **`templates/change.md:81` manufactures tickets and contradicts P5.** *Out of scope* reads: "Substantial deferrals become their own change spec (or a proposal, if unconfirmed)." P5 (`AGENTS.md:18`) reads: "the ledger by default, a ticket only where its fix is already decided and sized."
- **The watchlist trigger does not require a ticket.** `skills/architecture/SKILL.md:59` and `skills/authoring/references/conditional-sections.md:15` both accept "an explicit deferral … a named reason, not silence." A consuming repo's reflection reported the opposite; it is wrong about this repo's guidance, and line 81 above is the sentence it was reaching for.
- **Actionability never tests truth or size** (`skills/work-discovery/SKILL.md:85`): "the goal is stated, the acceptance criteria are checkable, and nothing it depends on is still open." A ticket whose premise dissolved since filing passes all three.
- **The lane table prices blast radius, not overhead** (`skills/authoring/SKILL.md:105-110`). It is the right axis for how much verification a change needs, and it is the only axis stated. Nothing in the repo states what a build run costs.
- **`do-less-at-ingestion` (accepted, 2026-09-07) settled the adjacent question and not this one.** It gave a proposal somewhere to record what it decided against, and re-ordered the breakdown by cost of being wrong. Both act on *which* work exists and in *what order*; neither acts on how the work is cut.

## Problem / motivation

The queue grows faster than the work, and consolidation is running as a periodic hand-sweep. Two consuming repos measured it independently in the same week.

**Nano-ERP.** One `/assess code` pass on 2026-09-21 produced ERP-597/598/599/600; three of those four were one change. A ledger drain on 09-14/15 produced ERP-540–545 and 552–554; two pairs inside that were each one change. Nine tickets where five would do — four build runs of worktree, change spec, test-first build, independent review, two rebases, gate and landing, for roughly two hours of editing. ERP-599 and ERP-600 were worse than inefficient: 600's deliverable was an annotation naming `SWEPT_DIRS` as the list to extend, 599's deliverable was extending it, and they were filed as independents with no relation recorded. Whichever landed first made the other stale.

**Calibrate.** Four consolidation passes in eight days absorbed 28 tickets. None was junk — the most recent pass found zero clean cancellations in 25 backlog items. The culling had already happened; what kept recurring was filing at the wrong granularity. CAL-1780/1781/1782 were three CI-guard gaps folded into one ticket the same day they were filed. CAL-1735's breakdown cut six slices against a 402-site migration, and by the time four had landed the tail was 14 sites across 6 files plus a two-export deletion — two full build runs for one change, sharing a single `npm run typecheck` as acceptance evidence.

Three failures produce all of it, and they are the same shape seen from three sides.

**One at a time, so nothing consolidates.** The twin search fires per filing, against one candidate, keyed to surface. An assessment or drain run produces co-changes by construction and files each one past a check that cannot see them. Worse, `/assess` files N findings in one act, each clearing a twin search against a board the same run is populating.

**At discovery, so granularity and truth are both frozen.** A finding's granularity is "one site the instrument walked past". A ledger entry's is "one thing someone noticed". Neither is the granularity of a fix. And a premise true at filing goes on being asserted: ERP-544 was fixed by ERP-513 landing on 09-18 and sat open until 09-22; ERP-606's AC-1 was satisfied mid-session by ERP-605; five Calibrate tickets cited a proposal that has never existed in any branch, two were correctly held, and three stayed in Todo for six more days with a routine tick starting a build on one of them.

**Never revisited, so nothing re-sizes.** CAL-1735's slice rationale was right for the big surfaces and wrong for the tail, and nobody re-measured it as the problem shrank. Slice size is a property of the work left, not of the work at filing.

Underneath all three is a number the harness does not state: **what a build run costs.** The lane table answers "how much verification does this need". Nothing answers "is this worth a run". Without that figure, one more ticket reads as free at every filing surface, and both reports had to measure the cost by hand to make their case.

If nothing is done, the sweep is the recurring cost. Calibrate's pass cost a session and absorbed 18 tickets; Nano-ERP's removed four build runs after the tickets already existed. That is rework over a filing step, and it repeats at whatever rate the queue refills.

## Options

**Option A — consolidate at filing.** A run filing more than one ticket files them as one batch after a consolidation pass, against a co-change test: *would one builder, in one worktree, do all of this in one sitting?* Add a materiality floor at the finding bar, and default a deferral to the ledger. · Prevention at the source, and it retires the sweep rather than scheduling it. Costs one step on every multi-filing run, cannot touch what is already filed, and rests on a judgment the filing agent makes — which P1 is entitled to be suspicious of.

**Option B — consolidate at pull.** Leave filing alone. Make `work-discovery` absorb adjacent unstarted tickets and re-check premises before handing one to a build. · Says the queue's *depth* is not the problem and the *run count* is, which is half true. Filing stays cheap and honest — one finding, one record — and nothing wears a run it does not deserve. But the board is what the operator reads and ranks against, a 60-ticket board is a management cost whether or not it becomes 20 runs, and a stale premise sits on the board misinforming every ranking pass until something pulls it.

**Option C — institutionalise the sweep.** Make the hand-pass a command, or a fourth `/assess` scope. · It demonstrably works; both reports are its output. It is also the status quo with a name on it, and both reports identify the sweep itself as the waste (P2 rework). It buys a cadence for a problem whose fix is upstream of it.

**Option D — throttle with numbers.** Lower `queue.wip_limit`, tighten `active_projects`. No new mechanism, which P0 prefers. · It throttles the symptom and changes no granularity: the same N tickets exist, they wait in Backlog instead of Todo. Calibrate's evidence refutes it directly — the culling already happened and nothing was junk, so a tighter limit starves the queue rather than shrinking the work.

## Recommendation

**Option A, plus the narrow half of Option B.**

A is the only option that acts on the cause. The others act on where the tickets accumulate (B, D) or on clearing them afterwards (C), and P2 refuses a periodic pass over a step that should not have produced the pile.

B's pull-time re-check is retained for exactly what filing cannot know. A filing agent cannot know that a sibling will land next week and dissolve this ticket's premise, and cannot know that a breakdown's tail will shrink below the run that carries it. Those are properties of the work *remaining*, discoverable only when something reaches for it. Keeping the whole of B alongside A would be two consolidation mechanisms for one problem; keeping the two questions filing cannot answer is the smallest thing that closes ERP's pattern 4 and Calibrate's patterns 3 and 4.

Both halves cite one figure — the cost of a `simple`-lane build run — so state it once and let the rules reference it. That is the mechanism P0 prefers: a number, where four separate judgments would otherwise be invented independently.

Traces to P0 (a ticket for a comment is refused by name), P2 (the sweep is rework; the batch pass retires it), and P3 (small batches through explicit dependencies — a co-change filed as two independents is a dependency nobody recorded).

**This proposal's own breakdown applies its test.** The analysis behind it names six guidance edits across six files. Four of them — the finding bar's materiality floor, `templates/change.md:81`, `authoring` → *Grounding*, and the admission question they share — are one sitting for one builder, so they are one ticket, item 3, with the count in its title. Filing this as six would be the failure the proposal exists to close.

## Not doing

- **A consolidation command or `/assess` scope** — Option C institutionalises the rework the reports identify as the waste. Reopen if A ships and the filing-time ratio (below) fails to move over two assessment cycles.
- **A queue-limit change** — Option D throttles Todo depth without changing granularity, and Calibrate's zero-cancellation pass shows the queue is not carrying junk. Reopen if the run count falls and board depth remains the operator's stated problem.
- **A hook enforcing the batch pass** — the repo's *Enforcement* posture defaults to no guard and escalates only where a failure is unrecoverable or silent-and-consequential. A missed consolidation costs one extra build run, which is recoverable and visible. Reopen if the filing-time ratio shows the prose rule is not being honoured.
- **Widening the fix lane** — more work shipping without a ticket would cut overhead without touching granularity, and it reaches the independent-review question. A separate decision on a separate axis.
- **Re-grounding every ticket at every pull** — the reflection that proposed it costs a re-read per tick. Every failure it cites was *something landed since filing*, so the trigger is narrowed to that in item 4.
- **A re-sizing cadence for breakdowns** ("more than three slices, re-check at halfway") — P0 refuses a mechanism where a number would do, and the pull step already judges actionability. Folded into item 4's size question.
- **Hold-contract and project-state fixes** — incomplete holds are already refused by the contract (comment + label + assignment, verified by read-back); adding guidance for an existing rule is over-processing. Project-state consistency is repo configuration, not plugin guidance.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| The cost of one `simple`-lane `/build` + `/promote` cycle — wall-clock and tokens. Items 1, 3 and 4 all cite it; without a measured figure each rule invents its own threshold | user | the spine's *Lanes* contract, beside the lane table it complements |
| Does the co-change test bind a proposal's breakdown at authoring time, or only when a slice is pulled? Binding at authoring means a proposal may not file a slice thinner than a run, which constrains how a large migration is cut | user | `authoring` → *Proposal spec* |
| Is a merged ticket's absorbed-findings list an obligation or a convention? It is the mitigation for the under-filing risk below, and an obligation makes it a criterion a reviewer can fail | user / architect | the spine's *Filing* contract |

## Breakdown

Four items. Item 1 fires the comprehension and blast dimensions — it changes the spine's *Filing* contract, which every hydrated consumer carries, and items 2 to 4 each cite it — so it is held for the operator and the rest declare a dependency on it. Items 2, 3 and 4 are independent of each other and may run in parallel once 1 lands.

1. **State run overhead and the co-change test in the spine's *Filing* contract** — extend `AGENTS.md:54` (and its `templates/spine.md` twin) from "twin" to "twin or co-change", give the test its wording, and state the cost of a build run once beside the lane table. Held for the operator: the figure is Open Decision 1, and every later item reads it. `complex`.
2. **Apply the batch pass at the four surfaces that file more than one ticket** — `tracker` → `create` gains the batch precondition; `/assess` step 2, `/drain` pile two and `/propose` step 4 each call it. Retires `/assess`'s "Triage happens in the tracker, not at report time" and promotes `/drain`'s local grouping rule to the shared one. Depends on 1. `complex` — it changes `tracker`'s `create` contract.
3. **Raise the filing-time admission bar (three obligations, three files)** — a materiality test at `finding-bar.md` (a finding names the user outcome or consumer behaviour it breaks, or it is a ledger entry); `templates/change.md:81` aligned with P5 so a deferral defaults to the ledger; `authoring` → *Grounding* extended so a filing resting on a decision names the artefact **and** the commit carrying it. One question in three places: what must be true before a ticket exists. Depends on 1. `simple`.
4. **Add premise and size questions to pull-time actionability** — `work-discovery` → *Actionability* gains two: has anything landed on this ticket's surface since it was filed (if so, re-state the premise in one line and cancel if it has dissolved), and is this ticket smaller than the run that would carry it with an adjacent unstarted ticket to absorb it. Depends on 1. `simple`.

**The measure, carried by item 1 and read at every later assessment: findings in versus tickets out, per filing run.** A run that files one ticket per finding did not run the consolidation pass, whatever the quality of each ticket. It is recorded at the moment of filing, needs no sweep to observe, and belongs as a fourth row on `/assess process`'s baseline table.

## Risks / unknowns

- **Consolidation loses a finding.** A merged ticket that names only its first item hides the rest — `/drain` already warns about exactly this for bundles. Mitigated by requiring a merged ticket to name every finding it absorbed, which is Open Decision 3, and unmitigated until that is answered.
- **The co-change test is a judgment, and P1 refuses a stage that ends when the model feels finished.** "One builder, one worktree, one sitting" is sharper than "same surface" and is still not a predicate. The filing-time ratio is the compensating control: it does not check any single call, and it makes a run that skipped the pass visible. This is the weakest part of the proposal and the place to push on it.
- **Bundles that blow context.** The proposal moves ticket size up; too far up is the other failure the operator named. Item 4's size question only ever absorbs *adjacent unstarted* work, and item 3's admission floor removes items rather than merging them, so neither compounds. Item 2's batch pass is where an over-large bundle would come from, and nothing in this proposal bounds it from above. Open.
- **The overhead figure goes stale.** It is measured on today's models and today's gate. Recording it beside the lane table rather than inside four rules means one edit when it moves.
- **Item 1 is a spine contract change.** Every hydrated consumer's spine changes, and `/harness:hydrate` and the audit agent both read it. The blast is known and bounded; the sequencing is what makes it item 1.
- **Unknown: whether an assessment's findings cluster often enough to be worth the pass.** Both reports measured roughly a 40% reduction (9→5, 32→23). One more assessment cycle measured under the new rule would settle whether that holds or whether those two runs were unusually clustered.
