---
name: spec-authoring
description: Use when writing or revising any spec — a proposal, a change spec (the ticket), or a feature/reference spec — including its design and the decisions behind it. The craft of the spec; spec-driven-development is the lifecycle.
---
<!-- guidance:spec-authoring@0.14.0 -->
# Spec Authoring

How to write a spec that is actionable, consistent, and complete — including the **design** and the **decisions** behind it. Specs come in two families: **lifecycle specs** that flow with a task, and **reference specs** that document a standing part of the system. `spec-driven-development` is the lifecycle; this is the craft.

## Lifecycle specs — three moments in a task's life

| Spec | Answers | Lives in | When |
|---|---|---|---|
| **Proposal spec** | "Should we do this, and how big is it?" | `specs/proposals/<slug>.md` | Before it is confirmed work — needs a decision, carries real unknowns, or is too large to be one change |
| **Change spec** | "What exactly will this one piece of work do?" | The tracker issue | While the work is in flight |
| **Feature spec** | "What does the product do today?" | `specs/features/<feature>.md` | Permanent, as-built record |

They flow: a **proposal** (when needed) is decided and broken into one or more **change specs** (tracker issues); each change is built, and its delivered behaviour is recorded into the **feature spec**. Small, clear work skips the proposal and starts as a change spec.

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

**Embedded is the default.** A consequential decision is recorded *in the spec it governs*, so the what and the why stay together:

- A decision about **one feature** → a **Decision** block in that **feature spec** (`templates/decision.md` is the embeddable shape: context, decision, alternatives rejected, consequences). This holds everywhere: a decision that governs one feature stays in that feature's spec, whatever else the repo configures.
- A **cross-cutting** decision (governs many features) → recorded in the **architecture-principles spec**, as a principle plus its rationale and the alternatives rejected.

Why embedded: someone reading the feature spec sees the decision and its reasoning *in place*, not in a separate file they have to find and correlate. Superseding an embedded decision means updating it in-place in its spec, with a dated note on what changed and why (*"Superseded YYYY-MM-DD: previously X; changed to Y because Z."*) — not a new numbered file — then updating the code, comments, and specs that relied on the old choice; where a repo declares `paths.decisions`, its own architecture index owns supersession for the records filed there. (See `architecture` for when a choice is decision-worthy.)

**A repo may configure a decision directory, and that configuration is the only switch.** Where a repo declares `paths.decisions` in its `CONTEXT.md`, that directory is the home for its architecture decision records; a repo that declares none has no `decisions/` folder and no standalone ADRs — embedded, exclusively. There is no separate strategy setting to keep in step: the optional path is the whole signal.

A configured directory holds only decisions that are **cross-cutting, consequential, and expensive to reverse** — branch topology, tracker architecture, security posture, certification invariants. A decision that merely touches **several files** does not clear that bar, and one that governs a single feature never does; both stay embedded. Each qualifying decision has **one canonical record**: the feature specs it affects link to it and must not restate its reasoning, so superseding the record leaves them correct.

Placement, numbering, and supersession *inside* that directory are the repo's own convention — defer to its **architecture index** (the architecture-principles spec, or the decisions index in `CONTEXT.md`) rather than assuming one. Universal guidance names the `paths.decisions` key and stops there.

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

A single, concrete piece of work. The tracker issue is its home (`tracker`). Sections (see `templates/change.md`): **Problem**, **Approach**, **Design** (data model / interface / scenarios, scaled to size), **Acceptance criteria**, **Out of scope**. If the design rests on a cross-cutting decision, settle it in a proposal first and record it in the architecture-principles spec — do not bury it in the change spec.

**The capture on-ramp.** A bug or tweak noticed in actual use does not start here from a blank change spec — `/bug` / `/tweak` capture it straight into `templates/adjustment.md`, a capture-optimized change spec pre-framed for the moment of noticing (As-built / Desired / From actual use / Acceptance criteria). `/start` extends it with Grounding and the full Design section above at build time; it is an on-ramp to this form, not a competing artifact.

**Grounding (before the change spec).** Ground the spec in current reality before writing it: verify every fact it will rest on that names a **file / function / flag / version / decision** against the code as it is *now* — not as memory or a system-reminder recalls it (a recalled fact reflects what was true when it was written). Record what you find as a **`Grounding`** section in the change spec (`templates/change.md`): verified facts each anchored to a `path:line` (or a current version / flag value), any decision the ticket assumed settled that is actually open or already superseded (surface it now, not mid-build), and open questions. Where a sub-agent host is available, a read-only `researcher` agent produces this brief in its own context and the executor records it verbatim; where none is available, the executor self-grounds inline — the fallback. Grounding always happens, scaled to size: a one-line fix gets a one-line grounding ("verified `foo.py:rename_flag` still exists"), not a research essay. The recorded section makes grounding auditable and pulls decisions forward to creation time — its honest limit is that it evidences the step was *recorded*, not that grounding was genuinely performed.

**Watchlist trigger (conditional).** Before writing the change spec, check the files this change will touch against the repo's `architecture_watchlist.files` in `CONTEXT.md` (a repo that has not opted in has no watchlist — skip this). When the planned diff intersects the watchlist, add a **`Watchlist trigger`** section recording one of the two valid outcomes: a small behavior-preserving seam extraction, or an explicit deferral with a reason. The mechanism — the trigger, the two outcomes, the no-op when a repo does not opt in — lives in `architecture` → *Architecture watchlist*; the change spec is where its result is recorded.

**How deep the Design section goes.** Write it to the depth the *decision* needs and no further. The ticket's **assurance** level, not your judgment while writing, decides whether the work earns a separate design pass at build time: only work labelled for the highest level does, and everything unlabelled resolves to the level that requires none. So a thin Design section is right on a change whose design was never going to be the hard part, and wrong on one carrying a real decision. *Which* level the ticket carries is a different question, and *Choosing assurance* below is where it is answered.

**Lifecycle sweep (conditional).** For any state-changing operation — a create / update / delete, or anything that mutates stored state — enumerate the **derived artifacts** of the affected entity (caches / query keys, share tokens, counts / aggregates, sessions) and state, per artifact, what happens to it. "Unaffected" is an acceptable answer; silence is not. This is the sweep that catches the write path that ships its primary mutation but drops a derived artifact — a stale cache, an unrevoked share token, a count left un-decremented — the defect class review keeps finding one artifact at a time. Do it at design time, in the change spec, where it is cheapest; a change that mutates no stored state has no sweep to do, so say so and move on.

**Scope-claim invariants (conditional).** An invariant stated as a scope claim — "the only consumer", "exactly one home", "nothing else reads this", "the single writer" — is a claim about the whole call graph, not a local fact. Cite the enumeration that establishes it — the grep, or the type followed to its readers — in the spec. If the enumeration finds a second consumer, the invariant is not recorded: it *is* a finding. A scope claim written without its enumeration is worse than none: it launders an open violation into a documented invariant that later review trusts and builds on, and it stops being true the moment a new reader touches the value without that knowledge. The enumeration is one grep; a change that makes no scope claim has none to cite.

**File size is never an acceptance criterion.** A change spec states the *structural outcome* a size target is a proxy for — "the engine-protocol layer lives in its own module; the verb file holds only glue; no test imports change" — which is checkable by import structure and tests, not by a raw line count. A quantity gets no size carve-out: if a spec author insists on one, the measuring-test rule applies with no exemption (`code-quality` Part C — *a measurable criterion needs a measuring test*): write the test that counts the lines and fails outside the bound, or it is not a criterion. Being forced to write that test is the tell that the number was never the requirement — a cohesive unit split to satisfy a line count moves reader-load up, not down.

**Renegotiating a criterion mid-build.** A builder who discovers a criterion is wrong while building — a stale estimate, an impossible bound, the wrong target — does not descope it silently; `engineering-principles` forbids that, but nothing replaced it until now. The sanctioned move is: comment on the issue with the evidence, amend the acceptance criterion *there*, then build to the amended spec — all before any Done claim. The renegotiation lives on the ticket, where the canonical record can see it. A correct engineering call argued only in a commit body or PR description leaves the tracker's criterion wrong and the ticket falsely Done — the record everyone reads after the work says one thing while the diff did another.

### Choosing assurance

Every ticket carries **exactly one** `assurance:<level>` label, chosen when it is filed, and this subsection is the one home for *how that choice is made*. The other direction — which stages a level obliges a run to pay for, and what a run does with a label that is missing, doubled, or unrecognized — is the driving command's (`/build`), **not this rubric's**. The two answer different questions, at different moments, for different readers; neither restates the other.

| Level | Choose it when |
|---|---|
| `trivial` | The expected diff falls inside the repo's configured allowlist (`CONTEXT.md` → `assurance.trivial_certify`) and the work carries no unresolved design or public-contract decision. |
| `simple` | The default: a normal change, a bug, a missing detail. |
| `complex` | The work carries a consequential architecture, data-model, interface, or security decision, or spans more than one interacting lifecycle contract. |

Two rules carry the weight.

**Uncertain is `simple`.** A filer who cannot place the work confidently chooses `simple`, always. Guessing high costs one design pass; guessing low costs the independent read that would have caught the guess.

**Never infer `trivial` from low severity, a short description, or a small estimated diff alone.** All three are properties of a ticket's *text*, written by whoever filed it and influenceable by anyone who can open an issue — and three of the surfaces that file tickets are agents acting on content someone else wrote. `trivial` is earned only by the repo's own certification command measuring the real diff against its versioned allowlist; until that command has run and passed, the work is `simple`. A ticket cannot argue its way down.

## Feature spec

The canonical, as-built record of what the product does today, plus the decisions that shaped it (Decision blocks). Written by the **reviewer** on PASS, from the diff — never by the builder (`spec-driven-development`). See `templates/feature.md`. It answers "how does X work, and why is it that way?", grouped by user-visible behaviour, with the data model and interface surface that back it.

An as-built record must not enumerate a set the code owns — a class family, a command surface, or a reason vocabulary. Name the module that owns it and stop; or, where the list genuinely aids the reader, pair it with a guard that derives the set from the code and fails when the two disagree. A prose list with no derivation is a claim nothing measures, and it goes stale at the commit that adds the next member.

## Quality bar

A spec is ready when its type is right, its design is specified to the depth the work needs (an implementer would not have to invent a contract mid-build), the decisions behind it are recorded in place, every acceptance criterion is testable, and it holds no unresolved decision presented as settled. The reviewer checks change and feature specs against this bar (`review-discipline` Stage 1).
