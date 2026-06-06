<!-- guidance:spec-authoring@0.1.0 -->
# Spec Authoring

How to write a spec that is actionable, consistent, and complete — including the **design**, not just acceptance criteria. Three kinds of spec serve three moments in a task's life. This skill defines each, what goes in it, and how they flow. `spec-driven-development` is the lifecycle; this is the craft.

## The three specs

| Spec | Answers | Lives in | When |
|---|---|---|---|
| **Proposal spec** | "Should we do this, and how big is it?" | `specs/proposals/<slug>.md` | Before it is confirmed work — needs a decision, carries real unknowns, or is too large to be one change |
| **Change spec** | "What exactly will this one piece of work do?" | The Linear issue | While the work is in flight |
| **Feature spec** | "What does the product do today?" | `specs/features/<feature>.md` | Permanent, as-built record |

They flow: a **proposal** (when needed) is decided and broken into one or more **change specs** (Linear issues); each change is built, and its delivered behaviour is recorded into the **feature spec**. Small, clear work skips the proposal and starts as a change spec.

## What every spec shares

- **Actionable.** A reader can act without asking — a decider can decide on a proposal, an implementer can build a change spec test-first.
- **Design, not just acceptance.** State *how* it works, not only *what* the user can do: the data model, the interface/contract, the behaviour in scenarios. Acceptance criteria check the outcome; the design says how the outcome is produced. A spec with criteria but no design pushes the hard decisions onto the implementer mid-build, where they are made fastest and worst.
- **Testable.** Every acceptance criterion is verifiable by a test, not a subjective judgement ("feels fast" → "responds within 200 ms").
- **Honest prose.** No TBDs standing in for decisions, no hedging. Follow `writing-quality`.
- **Scaled to size.** A one-line bug fix is one line. Depth earns its place; do not pad.

## Proposal spec

For an idea that is not yet confirmed work. The proposal is where you think it through before it costs build time. Sections (see `templates/proposal.md`):

- **Problem / motivation** — why this matters now.
- **Options** — the approaches considered, with trade-offs. Not one blessed answer dressed as inevitable.
- **Recommendation** — the proposed direction and why.
- **Open decisions** — what must be decided, and by whom. A cross-cutting decision becomes an ADR (`architecture`).
- **Breakdown** — the change specs this would spawn, each sized to ship on its own.
- **Risks / unknowns** — what could go wrong or is not yet understood.

A proposal's outcome is explicit: **accepted** (spawns change specs + any ADRs), **rejected** (kept as the record of why), or **split** (replaced by smaller proposals). It does not sit half-decided.

## Change spec

A single, concrete piece of work. The Linear issue is its home (`linear-sync`) — this is what the builder builds and the reviewer reviews against. Sections (see `templates/change.md`):

- **Problem** — why now, in a sentence or two.
- **Approach** — how the change lands.
- **Design** — the load-bearing part for anything non-trivial: data-model changes, the interface/API contract (shapes, status/error cases, auth), and behaviour scenarios (GIVEN/WHEN/THEN). Scale it: a small change needs a sentence, a cross-cutting one needs all three.
- **Acceptance criteria** — specific, testable outcomes.
- **Out of scope** — what this explicitly defers.

If the design needs a cross-cutting decision, that belongs in a proposal + ADR first, not buried in the change spec.

## Feature spec

The canonical, as-built record of what the product does today. Written by the **reviewer** on PASS, from the diff — never by the builder (`spec-driven-development`). See `templates/feature.md`. It answers "how does X work?", grouped by user-visible behaviour, with the data model and interface surface that back it.

## Quality bar

A spec is ready when its type is right (no proposal for a one-line fix; no big unconfirmed idea pushed straight to a change spec), its design is specified to the depth the work needs (an implementer would not have to invent a contract mid-build), every acceptance criterion is testable, and it holds no unresolved decision presented as settled. The reviewer checks change and feature specs against this bar (`code-review` Stage 1).
