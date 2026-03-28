# ADR-NNN: [Short title — decision made, e.g. "Use FastAPI for the backend API"]

**Date:** YYYY-MM-DD
**Status:** Proposed | Accepted | Deprecated | Superseded by [ADR-NNN]
**Decider:** [architect | user | both]
**Affects:** [product name(s) | All products]

---

## Context

What situation or requirement forced this decision? Include:
- The specific problem or question that needed answering
- Constraints that were non-negotiable (from strategy, principles, or existing architecture)
- What would happen if no decision was made (default path and its risks)

Be specific. "We needed to choose a database" is not enough context. "We needed a database that supports multi-tenant row isolation, is manageable by one person, and can run on a PaaS without custom server configuration" is.

---

## Decision

State the decision clearly in one or two sentences. What was chosen?

> We will use [X] for [purpose].

---

## Rationale

Why this option? Connect to architecture principles from `specs/arch/principles.md` and strategy from `strategy/strategy.md`.

- **[Principle name]** — How this decision upholds or expresses that principle
- **[Principle name]** — How this decision upholds or expresses that principle

Include any additional reasoning not captured by a named principle.

---

## Alternatives Considered

Document the options that were evaluated and rejected. For each:

**Option: [name]**
- What it is
- Why it was considered
- Why it was rejected

Not documenting rejected options is how the same debates get relitigated. Future agents and contributors should be able to see that an option was considered and understand why it didn't win.

---

## Consequences

**Positive:**
- What this decision enables or improves

**Negative / Trade-offs:**
- What this decision costs, constrains, or forecloses
- What becomes harder as a result

**Neutral / What changes:**
- Downstream decisions this creates or constrains
- What future ADRs this makes necessary

---

## Review Notes

*Optional. Add if the decision was contested, required user input, or produced a notable carry-forward.*
