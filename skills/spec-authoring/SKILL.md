---
name: spec-authoring
description: Use when writing or revising any spec — a proposal, a change spec (the ticket), or a feature/reference spec — including its design and the decisions behind it. The craft of the spec; spec-driven-development is the lifecycle.
---
<!-- guidance:spec-authoring@0.3.1 -->
# Spec Authoring

How to write a spec that is actionable, consistent, and complete — including the **design** and the **decisions** behind it. Specs come in two families: **lifecycle specs** that flow with a task, and **reference specs** that document a standing part of the system. `spec-driven-development` is the lifecycle; this is the craft.

## Lifecycle specs — three moments in a task's life

| Spec | Answers | Lives in | When |
|---|---|---|---|
| **Proposal spec** | "Should we do this, and how big is it?" | `specs/proposals/<slug>.md` | Before it is confirmed work — needs a decision, carries real unknowns, or is too large to be one change |
| **Change spec** | "What exactly will this one piece of work do?" | The Linear issue | While the work is in flight |
| **Feature spec** | "What does the product do today?" | `specs/features/<feature>.md` | Permanent, as-built record |

They flow: a **proposal** (when needed) is decided and broken into one or more **change specs** (Linear issues); each change is built, and its delivered behaviour is recorded into the **feature spec**. Small, clear work skips the proposal and starts as a change spec.

## Reference specs — standing documentation

Some specs are not tied to a task. They document a stable part of the system and are updated when that part changes. A reference spec *is* a spec — held to the same bar (actionable, honest, current). Two recognised types (paths in `CONTEXT.md`):

- **Infrastructure spec** (`templates/infrastructure.md`) — the operational reality: domains, hosting, services, deployment, accounts. The source of truth when making a deployment or configuration decision.
- **Architecture-principles spec** (`templates/architecture.md`) — how the system is built: the technical principles that govern design *here*, extending the universal `engineering-principles` with this repo's specifics. A repo with rich architecture conventions keeps them in this spec; a small repo keeps a brief version in `CONTEXT.md` and skips the file.

## What every spec shares

- **Actionable.** A reader can act without asking — a decider can decide on a proposal, an implementer can build a change spec test-first.
- **Design, not just acceptance.** State *how* it works, not only *what* the user can do: the data model, the interface/contract, the behaviour in scenarios. Acceptance criteria check the outcome; the design says how the outcome is produced. A spec with criteria but no design pushes the hard decisions onto the implementer mid-build, where they are made fastest and worst.
- **Testable.** Every acceptance criterion is verifiable by a test, not a subjective judgement ("feels fast" → "responds within 200 ms").
- **Honest prose.** No TBDs standing in for decisions, no hedging. Follow `writing-quality`.
- **Scaled to size.** A one-line bug fix is one line. Depth earns its place; do not pad.

## Decisions live in the spec they govern

**There is no separate `decisions/` folder and no standalone ADRs.** A consequential decision is recorded *in the spec it governs*, so the what and the why stay together:

- A decision about **one feature** → a **Decision** block in that **feature spec** (`templates/decision.md` is the embeddable shape: context, decision, alternatives rejected, consequences).
- A **cross-cutting** decision (governs many features) → recorded in the **architecture-principles spec**, as a principle plus its rationale and the alternatives rejected.

Why embedded: someone reading the feature spec sees the decision and its reasoning *in place*, not in a separate file they have to find and correlate. Superseding a decision means updating it in-place in its spec, with a dated note on what changed and why — not a new numbered file. (See `architecture` for when a choice is decision-worthy.)

## Proposal spec

For an idea that is not yet confirmed work. Sections (see `templates/proposal.md`):

- **Problem / motivation** — why this matters now.
- **Options** — the approaches considered, with trade-offs. Not one blessed answer dressed as inevitable.
- **Recommendation** — the proposed direction and why.
- **Open decisions** — what must be decided, and by whom. Once made, each decision is recorded in the spec it governs (the feature spec, or the architecture-principles spec if cross-cutting).
- **Breakdown** — the change specs this would spawn, each sized to ship on its own.
- **Risks / unknowns** — what could go wrong or is not yet understood.

A proposal's outcome is explicit: **accepted** (spawns change specs; records its decisions into the relevant specs), **rejected** (kept as the record of why), or **split** (replaced by smaller proposals). It does not sit half-decided.

## Change spec

A single, concrete piece of work. The Linear issue is its home (`linear`). Sections (see `templates/change.md`): **Problem**, **Approach**, **Design** (data model / interface / scenarios, scaled to size), **Acceptance criteria**, **Out of scope**. If the design rests on a cross-cutting decision, settle it in a proposal first and record it in the architecture-principles spec — do not bury it in the change spec.

## Feature spec

The canonical, as-built record of what the product does today, plus the decisions that shaped it (Decision blocks). Written by the **reviewer** on PASS, from the diff — never by the builder (`spec-driven-development`). See `templates/feature.md`. It answers "how does X work, and why is it that way?", grouped by user-visible behaviour, with the data model and interface surface that back it.

## Quality bar

A spec is ready when its type is right, its design is specified to the depth the work needs (an implementer would not have to invent a contract mid-build), the decisions behind it are recorded in place, every acceptance criterion is testable, and it holds no unresolved decision presented as settled. The reviewer checks change and feature specs against this bar (`review-discipline` Stage 1).
