---
spec: architecture-principles
last_updated: YYYY-MM-DD
---

# Architecture Principles

How this system is built — the technical principles that govern design *here*. They extend the universal `engineering` with this repo's specifics, and they are where **cross-cutting decisions** are recorded (`spec-authoring`, `architecture`). A **reference spec**: update it when the architecture changes.

> Distinct from product principles (what we build and why). These define *how* we build it.

## Principles

Group by area (data, schema, API, deployment, security — whatever fits). For each, a bold one-liner and a short rationale; trace to a universal principle or a product principle where relevant.

### {Area, e.g. Data}

**{Principle, stated as a claim.}**
{Why it holds; what it rules out. *Derived from: {engineering tenet / product principle}.*}

## Cross-cutting decisions

Decisions whose scope crosses features live here as Decision blocks (`templates/decision.md`), recorded in place rather than as standalone files unless this repo declares `paths.decisions`. Each states context, decision, alternatives rejected, and consequences; superseding updates it inline with a dated note.

Where a decision directory *is* configured, this section becomes the **index** for it: state the bar a record must clear (cross-cutting, consequential, expensive to reverse), the naming and numbering convention, and how supersession is recorded there — universal guidance defers all three to this page — then link each record rather than restating its reasoning. Decisions below that bar stay inline here.

### Decision: {title}

*Decided {YYYY-MM-DD}.*

**Context.** … **Decision.** … **Alternatives.** … **Consequences.** …
