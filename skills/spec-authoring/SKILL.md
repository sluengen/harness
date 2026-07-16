---
name: spec-authoring
description: Use when writing or revising any spec — a proposal, a change spec (the ticket), or a feature/reference spec — including its design and the decisions behind it. The craft of the spec; spec-driven-development is the lifecycle.
---
<!-- guidance:spec-authoring@0.7.0 -->
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

Why embedded: someone reading the feature spec sees the decision and its reasoning *in place*, not in a separate file they have to find and correlate. Superseding a decision means updating it in-place in its spec, with a dated note on what changed and why (*"Superseded YYYY-MM-DD: previously X; changed to Y because Z."*) — not a new numbered file — then updating the code, comments, and specs that relied on the old choice. (See `architecture` for when a choice is decision-worthy.)

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

**Grounding (before the change spec).** Ground the spec in current reality before writing it: verify every fact it will rest on that names a **file / function / flag / version / decision** against the code as it is *now* — not as memory or a system-reminder recalls it (a recalled fact reflects what was true when it was written). Record what you find as a **`Grounding`** section in the change spec (`templates/change.md`): verified facts each anchored to a `path:line` (or a current version / flag value), any decision the ticket assumed settled that is actually open or already superseded (surface it now, not mid-build), and open questions. Where a sub-agent host is available, a read-only `researcher` agent produces this brief in its own context and the executor records it verbatim; where none is available, the executor self-grounds inline — the fallback. Grounding always happens, scaled to size: a one-line fix gets a one-line grounding ("verified `foo.py:rename_flag` still exists"), not a research essay. The recorded section makes grounding auditable and pulls decisions forward to creation time — its honest limit is that it evidences the step was *recorded*, not that grounding was genuinely performed.

**Watchlist trigger (conditional).** Before writing the change spec, check the files this change will touch against the repo's `architecture_watchlist.files` in `CONTEXT.md` (a repo that has not opted in has no watchlist — skip this). When the planned diff intersects the watchlist, add a **`Watchlist trigger`** section recording one of the two valid outcomes: a small behavior-preserving seam extraction, or an explicit deferral with a reason. The mechanism — the trigger, the two outcomes, the no-op when a repo does not opt in — lives in `architecture` → *Architecture watchlist*; the change spec is where its result is recorded.

**Lifecycle sweep (conditional).** For any state-changing operation — a create / update / delete, or anything that mutates stored state — enumerate the **derived artifacts** of the affected entity (caches / query keys, share tokens, counts / aggregates, sessions) and state, per artifact, what happens to it. "Unaffected" is an acceptable answer; silence is not. This is the sweep that catches the write path that ships its primary mutation but drops a derived artifact — a stale cache, an unrevoked share token, a count left un-decremented — the defect class review keeps finding one artifact at a time. Do it at design time, in the change spec, where it is cheapest; a change that mutates no stored state has no sweep to do, so say so and move on.

**Scope-claim invariants (conditional).** An invariant stated as a scope claim — "the only consumer", "exactly one home", "nothing else reads this", "the single writer" — is a claim about the whole call graph, not a local fact. Cite the enumeration that establishes it — the grep, or the type followed to its readers — in the spec. If the enumeration finds a second consumer, the invariant is not recorded: it *is* a finding. A scope claim written without its enumeration is worse than none: it launders an open violation into a documented invariant that later review trusts and builds on, and it stops being true the moment a new reader touches the value without that knowledge. The enumeration is one grep; a change that makes no scope claim has none to cite.

## Feature spec

The canonical, as-built record of what the product does today, plus the decisions that shaped it (Decision blocks). Written by the **reviewer** on PASS, from the diff — never by the builder (`spec-driven-development`). See `templates/feature.md`. It answers "how does X work, and why is it that way?", grouped by user-visible behaviour, with the data model and interface surface that back it.

## Quality bar

A spec is ready when its type is right, its design is specified to the depth the work needs (an implementer would not have to invent a contract mid-build), the decisions behind it are recorded in place, every acceptance criterion is testable, and it holds no unresolved decision presented as settled. The reviewer checks change and feature specs against this bar (`review-discipline` Stage 1).
