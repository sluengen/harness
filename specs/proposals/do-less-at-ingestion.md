---
proposal: do-less-at-ingestion
status: draft            # draft | under-decision | accepted | shipped | rejected | split | superseded
date: 2026-09-07
related: [lifecycle-reset, purpose-before-proof]
research: research/INDEX.md
---

# Proposal: do less, decided at ingestion

> P0 refuses over-building, and the stage line says how much is enough. Neither reaches the two places at intake where scope is actually set: a proposal has nowhere to record what it decided *against*, and a breakdown is ordered by what ships alone rather than by what is expensive to unpick. Two template sections, one skill subsection, two command steps.

## Grounding

Verified against `origin/dev` at `e3bb202`, 2026-09-07. This section exists because the first draft of this proposal was written against a 133-commit-stale tree and one of its three changes did not survive contact.

- **P0 *Do less* is already in the spine** (`AGENTS.md`, `spine:generated harness@8.1.0`), ahead of the five and taking precedence in any conflict. It already refuses "an assurance calibrated for a stage the product is not at" and "a mechanism added where a number would do."
- **The operating context is already stated** — pre-user, pre-revenue; speed and simplicity; the risk appetite named in three accepts and three refusals, including: *we do not accept a week of cycle time to prevent a defect a revert would fix in an hour*.
- **The stage is already declared**, per repo, in one line under *This repo*: "Stage: pre-user, pre-revenue. Posture: speed and simplicity; a wrong change costs a revert. Protected: user data, credentials, money." **A `stage:` key in `harness.yaml` is therefore withdrawn from this proposal** — it would be a second copy of a value that has a home, which P2 refuses, and it would contradict a decision landed days ago.
- **`templates/proposal.md` still has no scope-boundary section.** Problem, Options, Recommendation, Open decisions, Breakdown, Risks. Nowhere records what was cut.
- **The breakdown still has one ordering rule.** `skills/authoring/SKILL.md:38` — "each sized to ship alone"; `skills/propose/SKILL.md` step 2 repeats it.
- **The change spec's `Out of scope` section survives** (`templates/change.md:79`), unchanged, and is still per-ticket.
- **The lane rubric still reads "anything a proposal spawned" as `complex`** — now in the spine's *Lanes* contract, not only in `authoring`, so D3 below is a spine change rather than a skill change.
- Skills consolidated 28 → 16 in the same cycle; `spec-authoring` is now `authoring`, and the provider skills are one `tracker`.

## Problem / motivation

P0 and the stage line tell an agent *how much* to build. Neither is attached to the moment where the amount is decided, so both act as a standard to be recalled rather than a step to be taken. Two gaps remain at intake.

**1. A proposal has no scope boundary.** Options names the alternatives considered; nothing records the capabilities considered and cut. Those are different sets, and the second is the one that leaks. The boundary gets drawn later, one ticket at a time, in each spawned change spec's `Out of scope` — after the shape is committed, by an agent that was not in the decision and is reconstructing the cut from the recommendation. A boundary reconstructed is a boundary widened.

**2. The breakdown is ordered by shippability, not by cost of being wrong.** "Each sized to ship alone" selects for vertical feature slices, which pushes the data model into whichever ticket touches it first. The `complex` lane does buy a design pass, but it runs *inside* that first feature ticket, with a feature's delivery pressure on it. A shape that is expensive to unpick gets decided in the worst position the lifecycle offers.

### The evidence, and the counterweight

- `[E]` Atlassian: tickets carrying "explicit acceptance criteria, areas in scope, out-of-scope notes, dependency links" scored 83% agent-ready against 6%; "tight scope keeps agents on the rails," preventing agents from "going rogue or inventing requirements." Self-graded, vendor-authored — direction only.
- `[R]` EvilGenie, carried from the lifecycle reset: clear reward hacking at 0.7–3.4% on unambiguous tasks against 22–44% on ambiguous ones. An unstated boundary is a species of ambiguity, and it resolves toward more work.
- `[E]` spec-kit orders its task output `Setup → Foundational → per-user-story → Polish` (`research/06-spec-driven-development.md:57`). Foundations before features is the ecosystem default.
- `[A]` "State what is out of scope" is a named property of a spec worth executing.
- `[A]` **The counterweight, which binds this proposal harder than the support does:** "Sometimes a vague prompt is exactly right because you want to see how Claude interprets the problem before constraining it." Rigour scales with blast radius. At pre-user stage most blast radii are a revert.

### What doing nothing costs

The lifecycle reset measured the symptom: "ballooning complexity and work creation — every ticket discovers small things." A ticket that discovers small things is usually one whose boundary was never drawn. Leaving intake alone means over-production is caught downstream by the review lens and the assessment sweep — a downstream detector for an upstream ambiguity, which P1 explicitly refuses.

## Options

**Option A — Nothing. P0 and the stage line are enough.** They are new, they are stated well, and the cull that shipped them has not been given time to show whether the gap is real. · *Genuinely defensible and the cheapest thing on this page. Its weakness: a principle is recalled, a template section is filled. The reset's own diagnosis was that the harness spends downstream and prevents nothing upstream, and the two surfaces where intake decides scope are untouched by it.*

**Option B — The `Not doing` section only.** One template section, one binding rule, one `/propose` step. · *Closes gap 1 for about 15 lines. Leaves the breakdown ordering as it is, which is the gap with the longer half-life.*

**Option C — `Not doing` plus a foundations-first ordering rule** *(recommended)*. Option B, plus: where the work introduces a shape that is expensive to unpick, that shape is item 1, held for the operator, and downstream items depend on it. · *About 35 lines and no new configuration, vocabulary, or machinery. Adds a held ticket at the head of some proposals, which is waiting waste paid to the operator.*

**Option D — A `spike` assurance level.** · *Rejected. The lane axis is blast radius — how much a change must be proven. A spike is a statement about scope — how much should be decided before building. One label carrying two axes breaks the upgrade-only rule (`trivial → simple → complex` has no position for it) and hands every filer a lane that ships nothing. The hold contract already stops a run for an operator decision; a lane duplicating it is the second copy P2 refuses.*

**Option E — Enforce it with a hook.** A filing-time guard refusing a proposal with an empty `Not doing`, or a breakdown whose first item is not a foundations item. · *Rejected, and it is the tempting one. P2 refuses a guard over prose; law 1 sends prose to review, never to a predicate. Such a guard checks that a heading has bytes under it — over-processing that proves a stage ran, and P0 refuses a guard larger than the change it guards. This is a review obligation and a template shape, or it is nothing.*

## Recommendation

**Adopt Option C.** Three changes, no configuration.

**1. `templates/proposal.md` — a `Not doing` section**, immediately after Recommendation. One line per item: the capability, why it is out, and the trigger that would reopen it. Its raw material is the Options section — rejected options are already non-goals with reasons attached — plus whatever the operator cut during the decision. A spawned ticket's `Out of scope` cites it rather than re-deriving it.

**2. The boundary binds downstream.** Anything named in `Not doing` cannot be pulled into a ticket the proposal spawned without amending the proposal. This is the mirror of the existing no-silent-descoping rule: a builder may not quietly shrink a criterion, and may not quietly widen one either. It costs nothing new — it is a Stage 1 review check against an artefact the reviewer already reads.

**3. `authoring` and `templates/proposal.md` — order the breakdown by cost of being wrong.** Replace "each sized to ship alone" with: *ordered by dependency; where the work introduces a shape that trips the foundations test below, that shape is item 1.* `/propose` step 2 cites it; step 4 files item 1 held.

`/capture` gets one sentence and nothing else: extend step 2's stop condition — currently *architecture, contract, data model, test design* — to include what the change explicitly does not do. A capture is already decided, and it already has a cost line that refuses, an escape hatch to `/propose`, and an unbounded clarify loop.

### The foundations item, and the trigger that fires it

**Not a spike.** A spike ends when the model feels finished, which P1 refuses; a ticket whose deliverable is a conversation is over-production with a ticket number. The foundations item is a real change with a pass/fail exit: it **ships** the shape as an executable artefact — types, schema, migration, interface — with the tests that hold it; the **decision is recorded** in the spec it governs; it is **held** (`input`, comment, assignment — the existing contract, unchanged) so the unattended loop cannot start it; and downstream items **declare a dependency** on it.

**Up-front thinking is not assurance, and P0 does not refuse it.** The operating context refuses "a week of cycle time to prevent a defect a revert would fix in an hour." That sentence is about *assurance* — guards, gates, verification machinery built to catch a defect after the fact. Deciding a shape before building on it is not assurance; it is P1's "clarity before build", which comes first in the principles for a reason, and it is how P0's "the best change is the one not made" gets found at all. Reading that refusal onto design time produces a rule that never fires — which is exactly how the first draft of this section was written, and why it was wrong. Thinking is cheap. Building the wrong shape and then living on it is not.

**The cost of a late shape change is not the revert.** It is the revert, *plus* re-deciding under worse information, *plus* reloading the context that produced the original decision, *plus* everything already built on top of it, *plus* the flow the queue loses while that happens. In P2's vocabulary that is **motion** and **rework**; in P3's it is a serialised landing. A revert measures the git operation and none of the rest.

**The trigger, in four dimensions. Any one fires it.**

| Dimension | Fires when | Does not fire when |
|---|---|---|
| **Migration** | Data already written must be transformed rather than dropped — including seed data, dev state, and any deployed instance somebody relies on | Nothing has been stored in the shape yet |
| **Blast** | Changing it fans out across call sites — restructuring keys touches every query | It sits behind one interface |
| **Access** | The shape determines how it can be queried, so getting it wrong surfaces as a rewrite under load rather than as a bug to revert | Access patterns are unaffected |
| **Comprehension** | The operator cannot guide the work without seeing the shape first, and would otherwise have to reconstruct the model from a diff to hold an opinion | The shape is evident from the ticket |

Adding a column fires none of them and is ordered by dependency like anything else. Restructuring tables and keys fires the first three. A new entity's primary shape usually fires access and comprehension.

**Three of the four are stage-independent.** Only *migration* softens at pre-user, and only partly — there is no customer data, but there is still seed data, dev state, and any deployed instance. Blast, access and comprehension do not care what stage the product is at. So this rule fires **regularly, now** — not "seldom now and reliably later", which is what an earlier draft claimed and is the tell that the trigger had been written to cancel itself. The stage line calibrates how much gets *built*; it does not calibrate whether the shape gets *decided*.

**Comprehension is a dimension, not a tiebreaker.** At a startup the operator holds product context no agent has. A shape they have not seen is a shape they cannot steer, and their correction then arrives late, as rework, instead of early, as direction. Nothing in the harness makes provision for this today: every existing control asks whether the *agent* has enough information, never whether the *human* does.

### What it retires

- **"Each sized to ship alone" as the breakdown's ordering rule** (`authoring:38`, echoed in `/propose` step 2) — replaced, not added to.
- **The per-ticket scope re-derivation.** A spawned ticket cites the proposal's `Not doing` instead of reconstructing a boundary from the recommendation.
- **Withdrawn from this proposal before it was proposed:** the `stage:` config key and its four-value table, which the grounding found already served by the stage line under *This repo*.

Net: about +35 lines against ~10 retired, and no new configuration key, label, lane, hook, or command. It is an addition; calling it a wash would be the rationalisation the cost line exists to prevent. *Serves:* P0, P1. *Spends against:* P2, by adding guidance to two surfaces. *Waste:* removes over-production and rework; adds waiting, where a foundations item holds.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| **D1.** Option A (nothing — P0 and the stage line are enough) against Option C? | operator | this proposal |
| **D2.** Does the foundations item ship code, or only a recorded design? | operator / architect | `authoring` |
| **D3.** The spine's *Lanes* contract makes anything a proposal spawned `complex`. Does that survive foundations-first? | operator | `AGENTS.md` |
| **D4.** Does `/capture` get the one sentence, or nothing at all? | operator | `skills/capture/SKILL.md` |

**D1 — recommend Option C.** The case for waiting is that P0 landed days ago and the reset's own thesis was that additions earn their place against a measurement. The case for acting is stronger and is what settled it: P0 is a principle to be *recalled* at a moment nothing prompts, and the failure mode it leaves open is not over-building — it is **never doing the up-front thinking at all**, because every individual instance of skipping it is locally defensible at this stage. That failure compounds silently and is invisible to a review that only sees the diff in front of it. Both surfaces are one-line edits. If the answer is A, take the two signals under *Risks* as a baseline anyway.

**D2 — recommend both, because they serve different readers.** A data model recorded only in prose is not settled; it is settled the first time something must store a value in it, so the **executable shape** is what the downstream tickets need. But the *comprehension* dimension means the **recorded decision** is not a by-product — it is what lets the operator hold an opinion without reading a diff. Shipping the code without recording the reasoning satisfies the agents and fails the human; recording the reasoning without shipping the code satisfies nobody. Where the item is a contract with no implementation yet, the artefact is the interface plus its contract tests.

**D3 — recommend narrowing to: *carries a consequential decision the proposal did not settle*.** The clause predates foundations-first. If the shape is settled in item 1, downstream tickets have less design left, not more, and holding them all at `complex` buys a design pass for work whose design is already recorded — which is P0's "assurance calibrated for a stage the product is not at" in miniature. Flagged because it makes this proposal's own breakdown either non-compliant or an argument for the change, and pretending otherwise would be the tell. It is now a spine edit, so it is heavier than it looks.

**D4 — recommend the one sentence.** The gap is narrow and real: the stop condition asks what would change the architecture, a contract, the data model, or the test design — not what the change explicitly will not do. Anything more at capture is a second copy of the proposal tier.

## Breakdown

Ordered by dependency. The trigger fires on **comprehension** and nothing else: migration, blast and access are all inert for a prose change, but the shape here *is* the four-dimension test, and it is not something the operator could hold an opinion on from a diff. That foundations decision is being taken in this proposal, with the operator, which is where it belongs when the shape is prose rather than schema — so item 1 carries it rather than a separate held ticket. The rule, applied to itself, and it fires.

1. **`templates/proposal.md` — the `Not doing` section**, with the binding rule stated in `authoring`'s proposal tier. Resolves D1 by being built.
2. **Order the breakdown by cost of being wrong.** `authoring:38` and `templates/proposal.md`'s Breakdown section; the foundations-item definition and its trigger. Depends on 1 sharing the same subsection. Resolves D2.
3. **`/propose` — the two steps.** Fill `Not doing` in step 2; foundations-first ordering and held filing in step 4. Depends on 1, 2.
4. **`/capture` — the stop-condition sentence.** Independent. Resolves D4.
5. **Narrow the proposal-spawned lane clause** in the spine's *Lanes* contract. Only if D3 resolves that way; independent of the rest.

Items 1–3 are one surface and could be one ticket; they are split here because item 3 is the only one that changes a command, and `/propose` is the busiest surface in the lifecycle. If the operator prefers one ticket, take one — the split is not load-bearing.

## Risks / unknowns

- **The section becomes decoration.** `Not doing` filled with non-goals nobody would have done anyway. Mitigation: its raw material is the rejected options, a real set with reasons attached, and Stage 1 review gets one artefact against which to check a widened ticket. Weak mitigation, and the most likely way this fails.
- **The trigger gets read as a licence to skip the thinking.** Demonstrated, not hypothesised: the first draft of this proposal wrote the trigger so narrowly that it would almost never fire, by reading the operating context's assurance refusal onto design time. Every individual skip is locally defensible at this stage, which is what makes the drift invisible. The four dimensions are stated as *any one fires it*, and three of them are stage-independent, specifically to close that reading. This is now the failure this proposal most needs to survive.
- **Foundations-first moves work onto the operator.** A held ticket at the head of a proposal is waiting waste and a serialised landing, which P3 refuses, and the corrected trigger fires more often than the first draft's did — so this cost is real rather than theoretical. It is accepted: the thing being bought is a decision made once with the person who holds the product context, against a rework loop that would otherwise run every time an agent guesses the shape. `input` holds are what `/digest --drain` exists for. The rate to watch is how long these sit, not how many are raised.
- **Nothing here measures whether it works**, and guidance is verified by use, not by reading. Two signals, both cheap and both derivable from the tracker: **tickets spawned that were not in the breakdown** (over-production past the boundary), and **data-model changes landing after the first feature ticket** (the shape was not settled). Take both over the last ten proposals as a baseline whichever way D1 goes.
- **The stage line is prose, and prose is what this repo says it cannot enforce.** Foundations-first depends on an agent reading it correctly. Accepted deliberately: the alternative is Option E, and a guard that checks a heading has bytes under it does not detect a misread stage either.

---

*Named, at the operator's request, for the argument rather than the author: **Nafis' Do Less approach** — the cheapest moment to not build something is before anyone has agreed it exists.*

**Lifecycle.** Draft, 2026-09-07. Awaiting D1–D4. Lives in `specs/proposals/`.
