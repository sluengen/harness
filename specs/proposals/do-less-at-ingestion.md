---
proposal: do-less-at-ingestion
status: draft            # draft | under-decision | accepted | shipped | rejected | split | superseded
date: 2026-09-07
related: [lifecycle-reset, purpose-before-proof, borrow-from-ponytail]
research: research/INDEX.md
---

# Proposal: do less, decided at ingestion

> Scope is decided once, at intake, and everything downstream inherits it. Give `/propose` three things it does not have — an explicit record of what the work will *not* do, a declared product stage that says how much "enough" is, and a breakdown that settles the foundations before it sequences features — and give `/capture` one sentence. The v8 principles already refuse over-building; they just do not act until after the shape is committed.

## Problem / motivation

Every control v8 shipped for over-building acts **after** the shape of the work is set: the review's over-engineering lens, `/assess process`, the build reflection, the retirement table. Intake is where the shape is actually decided, and intake is where the harness says the least.

Three specific gaps, against this tree:

**1. The proposal has no scope boundary.** `templates/proposal.md` carries Problem, Options, Recommendation, Open decisions, Breakdown, Risks. There is nowhere to record what the proposal decided *against*. The boundary is drawn one ticket at a time, in each spawned change spec's `Out of scope` (`templates/change.md:77`) — after the proposal already committed the shape, by an agent who was not in the decision. Options names the alternatives; nothing captures the capabilities that were considered and cut, which is a different set and the one that leaks.

**2. Nothing declares how much is enough.** `harness.yaml` declares the tracker, the branches, the lanes, the layers, the paths — every dimension of *how* work is done and none of *what the product is for yet*. So "the bare minimum that is solid and can be scaled later" has no anchor, and each proposal re-argues it from scratch against a model prior that reliably resolves ambiguity toward complete-and-professional. `spec-authoring` tells an author to scale a spec to the size of the work; it never says how large the work should be.

**3. The breakdown is feature-sequenced.** `/propose` step 4 files one issue per breakdown item, and `spec-authoring` sets one ordering constraint: each item "shippable on its own." That selects for vertical feature slices and pushes the data model into whichever ticket happens to touch it first. The `complex` lane does buy an independent design pass — but it runs *inside* that first feature ticket, after the sequence is committed and with a feature's delivery pressure on it. The decisions with the longest half-life are made in the worst position.

### What the evidence says

- `[E]` Atlassian: tickets that "read like executable specs (explicit acceptance criteria, areas in scope, out-of-scope notes, dependency links)" scored 83% agent-ready against 6% for the traditional form. "Tight scope keeps agents on the rails," preventing agents from "going rogue or inventing requirements." Heavy vendor bias — self-graded, their new process against their own old one. Direction only.
- `[R]` EvilGenie, carried from the lifecycle reset: clear reward hacking at 0.7–3.4% on unambiguous tasks and 22–44% on ambiguous ones. An unstated boundary is a species of ambiguity, and it is resolved in the direction that produces more work.
- `[E]` GitHub spec-kit orders its task output `Setup, Foundational, per-user-story, Polish` — foundations before features is the published ecosystem default, not an invention here (`research/06-spec-driven-development.md:57`).
- `[A]` Anthropic's spec quality bar names "state what is out of scope" as a required property, alongside naming the files and interfaces involved. And: "Time spent making the spec precise pays off more than time spent watching the implementation."
- `[A]` The counterweight, quoted so it is not ignored: "Sometimes a vague prompt is exactly right because you want to see how Claude interprets the problem before constraining it." Spec rigour scales with blast radius. This proposal binds *scope*, and deliberately does not touch how much anything is proven.

### The cost of doing nothing

The lifecycle reset measured the symptom it could not yet treat: "ballooning complexity and work creation — every ticket discovers small things; the small things go on a ledger." A ticket that discovers small things is usually a ticket whose boundary was never drawn. Leaving intake alone means the over-production waste (P2) is caught downstream by the review lens and the assessment sweep, which is a detector for an upstream ambiguity — the thing P1 explicitly refuses.

## Options

**Option A — Guidance only.** Add a *Not doing* section to `templates/proposal.md`, a scope subsection to `spec-authoring`, and one step to `/propose`. No config key, no ordering rule, no new vocabulary. · *Cheapest, ~25 lines. Leaves "how much is enough" un-anchored, so the section gets filled with whatever the author already believed, and leaves gap 3 untouched.*

**Option B — Guidance, a declared stage, and foundations-first.** Option A, plus a `stage:` key in `harness.yaml` that the scope rule cites, plus a breakdown ordering rule that puts a foundations item first where the work introduces a stored shape or a contract. · *~60 lines and one config key across five surfaces. Anchors the refusal in something an author can cite rather than argue, and moves the data-model decision out of the first feature ticket. Adds a held ticket at the head of some proposals — a waiting cost, paid to the operator.*

**Option C — A `spike` assurance level.** A fourth lane for exploratory work whose output is a decision rather than a diff. · *Rejected. The lane axis is blast radius — how much a change must be proven — and a spike is a statement about scope, how much should be decided before building. Overloading one label with two axes breaks the upgrade-only rule (`trivial → simple → complex` has no position for it) and gives every filer a lane that ships nothing. The hold contract (`input`, comment, label, assignment) already stops a run for an operator decision; a lane that duplicates it is the second copy P2 refuses.*

**Option D — Enforce it with a hook.** A filing-time guard that refuses a proposal with an empty *Not doing*, or a breakdown whose first item is not a foundations item. · *Rejected, and it is the tempting one. P2 refuses "a guard over prose"; law 1 and ADR 0019 send prose to review, never to a predicate. A guard here would check that a heading has bytes under it, which is over-processing that proves a stage ran — precisely the ceremony the reset was written to delete. This is a review obligation and a template shape, or it is nothing.*

## Recommendation

**Adopt Option B.** Two of the three gaps cannot be closed by the *Not doing* section alone, and the section without an anchor is decoration.

The rule, stated once so `spec-authoring` can carry it in one place:

> **The Do Less rule.** Before a proposal is decided, state what it will not do and why, at the stage the repo has declared. Build the smallest thing that is solid at that stage and can be extended without being unpicked. Where the work introduces a stored shape or a contract, settle that shape first, with the operator, before any feature is sequenced against it.

Five changes carry it:

1. **`templates/proposal.md` — a `Not doing` section**, immediately after Recommendation. One line per item: the capability, why it is out, and the trigger that would reopen it. Its raw material is the Options section — options rejected are already non-goals with reasons attached — plus what the operator cut during the decision. A spawned ticket's `Out of scope` may cite it rather than re-arguing it.
2. **A boundary that binds downstream.** Anything named in *Not doing* cannot be pulled into a ticket the proposal spawned without amending the proposal. This is the mirror of the existing no-silent-descoping rule (`engineering:49`): a builder may not quietly shrink a criterion, and may not quietly widen one either. It costs nothing new — it is a Stage 1 review check against an artefact the reviewer already reads.
3. **`harness.yaml` — a `stage:` key** (`prototype` | `mvp` | `scaling` | `mature`), read through `scripts/harness-config.js` like every other key, cited by `spec-authoring`'s scope rule and by `/propose`. An undeclared stage resolves to `mvp`: the default errs toward less build, which is the error direction this proposal wants.
4. **`spec-authoring` — a `Scope at ingestion` subsection** under the proposal tier, holding the Do Less rule, the stage table, and the breakdown ordering rule. One home; the commands cite it and do not restate it.
5. **`/propose` — two steps; `/capture` — one sentence.** In `/propose` step 2, fill *Not doing* from the options actually rejected. In step 4, order the breakdown foundations-first and file the foundations item held. In `/capture` step 2, extend the stop condition to cover what the change explicitly does not do — the escape hatch and the cost line already handle the rest, and a capture is by definition already decided.

### What the stage binds, and what it must never bind

The load-bearing decision in this proposal. The stage binds **scope** — how much is built. It binds **nothing** about assurance — how much is proven.

| | Decided by | Answers |
|---|---|---|
| **Stage** (`harness.yaml`) | The operator, once, for the repo | How much do we build? |
| **Lane** (`assurance:` label) | The filer, per ticket, by blast radius | How much do we prove? |

Conflating them is the predictable failure: `stage: mvp` read as licence to skip tests. The repo has already refused that shape once — the fix lane is earned by the diff, not by a certifier (`34ae822`). An MVP-stage change to authentication is still `complex`, still stops and holds at the protected area, still gates. It is simply a smaller change.

| Stage | Build | Refuse |
|---|---|---|
| `prototype` | The thinnest thing that answers the question. Throwaway is acceptable. | Persistence, migration paths, anything for a second consumer. |
| `mvp` *(default)* | The bare minimum that is solid: correct behaviour, a data model that can carry the next three features, no abstraction with one caller. | Configurability, extension points, a second implementation of a thing with one, optimisation before a measurement. |
| `scaling` | What the current load and the next tier need. Seams where a second consumer exists. | Capabilities no user has asked for. |
| `mature` | Compatibility and migration paths, because breaking changes now cost more than building the bridge. | — |

### The foundations item

Not a spike. A spike ends when the model feels finished, which P1 refuses; and a ticket whose deliverable is a conversation is over-production with a ticket number. The foundations item is a real change with a pass/fail exit:

- **It ships.** The data model, schema, or contract as executable artefact — types, migration, interface — with the tests that hold it. A shape you cannot run is a guess written down.
- **The decision is recorded** in the spec it governs (a Decision block, or `paths.decisions` where it clears that bar), so the downstream tickets inherit it rather than re-deriving it.
- **It is held.** Filed with the `input` label, assigned, with the comment naming what the operator must settle — the existing hold contract, unchanged. The unattended loop cannot start it, which is the whole point: this is the decision worth an operator's attention, and the one place in the lifecycle where paying for a person is obviously cheaper than not.
- **Downstream items depend on it** and say so, so nothing sequences past an unsettled shape.

**When it does not apply:** work that introduces no stored shape and no new contract — a guidance change, a refactor behind an existing interface, a change confined to one call site. There, item 1 is whatever the proposal's dependencies actually make first. The rule is a default with a stated exception, not a ritual first ticket.

### What this retires

P2 obliges an addition to name what it removes. Three things, and the honest total:

- **The per-ticket scope re-derivation.** A spawned ticket's `Out of scope` cites the proposal's *Not doing* instead of re-arguing a boundary from a decision it was not in.
- **The design pass hidden in the first feature ticket.** Where a foundations item exists, the shape it settles is already paid for; the downstream tickets carry a thinner Design section, honestly rather than by omission.
- **"Shippable on its own" as the only breakdown ordering rule** in `spec-authoring` — replaced by dependency order with foundations first.

**Net:** about +60 lines of guidance and one config key, against roughly 20 lines retired. This is an addition, and calling it a wash would be the rationalisation the cost line exists to prevent. It is proposed because intake is currently the cheapest place in the lifecycle to prevent work and the harness spends nothing there.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| **D1.** Stage as a `harness.yaml` key, or as prose in each repo's `AGENTS.md` "This repo" section? | operator | `specs/architecture-principles.md` |
| **D2.** Four stages, or three (`prototype` folded into `mvp`)? | operator | the stage decision record |
| **D3.** Does the foundations item ship code, or only a recorded design? | operator / architect | the foundations decision record |
| **D4.** Is foundations-first a default with the stated exception, or mandatory for every accepted proposal? | operator | `spec-authoring` |
| **D5.** `/capture` — one sentence in the stop condition, or the full *Not doing* treatment? | operator | `skills/capture/SKILL.md` |
| **D6.** `spec-authoring`'s assurance rubric makes every proposal-spawned ticket `complex`. Does that clause survive this change? | operator | `spec-authoring` |

**D1 — recommend the config key.** The spine's own rule is that configuration lives in `harness.yaml` and is never restated in prose. A stage stated per-repo in prose is a value with no reader, and the harness has one reader for exactly this reason. The counter-argument is real: a key that only feeds a sentence in a skill is thin, and prose would cost nothing to add. It comes down to whether the stage should be citable by an agent that never read that repo's `AGENTS.md`. It should.

**D2 — recommend three.** `prototype` and `mvp` differ genuinely (throwaway versus solid-and-extensible), but a repo in prototype mode is not running a spec-driven lifecycle with independent review. Four values where three are used is inventory.

**D3 — recommend code where a shape exists.** A data model recorded only in prose is not settled; it is settled the first time something has to store a value in it. Where the foundations item is a contract with no implementation yet, the artefact is the interface plus its contract tests.

**D4 — recommend default with the exception**, stated as written above. Mandatory produces a foundations ticket for a guidance change, which is ritual.

**D6 — recommend narrowing the clause.** "Came from a proposal" as an automatic `complex` predates foundations-first. If the shape is settled in item 1, the downstream tickets have less design left, not more, and holding them all at `complex` buys a design pass for work whose design is already recorded. Narrow it to: *carries a consequential decision the proposal did not settle*. Flagging this because it makes this proposal's own breakdown either non-compliant or an argument for the change — and pretending otherwise would be the tell.

## Breakdown

Ordered by dependency, foundations first — this proposal applied to itself.

1. **Settle the ingestion vocabulary** *(foundations · held, `input` · `complex`)*. The stage enum and its default, the *Not doing* line shape, the reader contract for `stage:`, and the foundations-item definition. Deliverable: the decision recorded in `specs/architecture-principles.md`, plus the `stage:` key in `templates/harness.yaml` and this repo's `harness.yaml`. Resolves D1–D4.
2. **Read `stage:` through the one reader.** `scripts/harness-config.js` accessor, its unreadable-declaration behaviour matching the existing keys, and the gate test. Depends on 1.
3. **`spec-authoring` — `Scope at ingestion`.** The Do Less rule, the stage table, the stage-binds-scope-not-assurance boundary, and the breakdown ordering rule. Depends on 1.
4. **`templates/proposal.md` — `Not doing`,** plus the breakdown section's ordering note. Depends on 3.
5. **`/propose` — the two steps** (fill *Not doing* in step 2; foundations-first and held filing in step 4). Depends on 3, 4.
6. **`/capture` — the stop-condition sentence.** Depends on 3. Resolves D5.
7. **Narrow the proposal-spawned assurance clause.** Only if D6 resolves that way; independent of the rest.

## Risks / unknowns

- **The section becomes decoration.** *Not doing* filled with non-goals nobody would have done anyway ("we are not rewriting the database"). The mitigation is that its raw material is the rejected options — a real set with reasons already attached — and that Stage 1 review has one artefact to check a widened ticket against. Weak mitigation; this is the most likely way the change fails.
- **The stage becomes an assurance dial.** The failure this proposal most wants to prevent, guarded by prose — and prose is what this repo says it cannot enforce. Accepted deliberately: the alternative is Option D, and a guard that a heading has bytes under it does not detect this failure either.
- **Foundations-first moves the bottleneck to the operator.** A held ticket at the head of a proposal is waiting waste (P2) and a serialised landing (P3 refuses one). Bounded by the exception, and the hold is `input`, which `/digest` already drains. If the drain is slow, this trades rework for waiting at a bad rate.
- **Guidance is verified by use, not by reading.** Nothing here measures whether it works. Two signals, both derivable from the tracker, both cheap: **tickets spawned that were not in the breakdown** (over-production leaking past the boundary) and **data-model changes landing after the first feature ticket** (the shape was not settled). Take both over the last ten proposals as the baseline before item 1 lands.
- **A stage may be wrong for part of a repo.** One repo, one stage — but a mature billing path can sit beside an MVP surface. The stage is a default an author cites, not a fact; a proposal may state a different stage for its subject with a reason. If that becomes common, the key is at the wrong granularity.

---

*Named, at the operator's request, for the argument rather than the author: **Nafis' Do Less approach** — the observation that the cheapest moment to not build something is before anyone has agreed it exists.*

**Lifecycle.** Draft, 2026-09-07. Awaiting decision on D1–D6. Lives in `specs/proposals/`.
