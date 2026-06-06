<!-- guidance:template-architecture@0.1.0 -->
---
spec: architecture-principles
last_updated: YYYY-MM-DD
---

# Architecture Principles

How this system is built — the technical principles that govern design *here*. They extend the universal `engineering-principles` with this repo's specifics, and they are where **cross-cutting decisions** are recorded (`spec-authoring`, `architecture`). A **reference spec**: update it when the architecture changes.

> Distinct from product principles (what we build and why). These define *how* we build it.

## Principles

Group by area (data, schema, API, deployment, security — whatever fits). For each, a bold one-liner and a short rationale; trace to a universal principle or a product principle where relevant.

### {Area, e.g. Data}

**{Principle, stated as a claim.}**
{Why it holds; what it rules out. *Derived from: {engineering-principles tenet / product principle}.*}

## Cross-cutting decisions

Decisions whose scope crosses features live here as Decision blocks (`templates/decision.md`), recorded in place rather than as standalone files. Each states context, decision, alternatives rejected, and consequences; superseding updates it inline with a dated note.

### Decision: {title}

*Decided {YYYY-MM-DD}.*

**Context.** … **Decision.** … **Alternatives.** … **Consequences.** …
