<!-- guidance:template-adr@0.1.0 -->
# ADR-NNN: {short title — the decision, e.g. "Use Postgres for primary storage"}

**Date:** YYYY-MM-DD
**Status:** Proposed | Accepted | Superseded by ADR-NNN
**Deciders:** {who}
**Supersedes:** {ADR-NNN, if any}

---

## Context

What situation forced this decision? Include the specific problem, the non-negotiable constraints, and what happens by default if no decision is made.

Be specific. "We needed a database" is not context. "We needed storage that supports multi-tenant row isolation, runs on our PaaS without custom ops, and is manageable by one person" is.

## Decision

State it in one or two sentences. What was chosen?

> We will use {X} for {purpose}.

## Rationale

Why this option. Connect to `engineering-principles` and to repo principles in `CONTEXT.md` where relevant.

- **{principle / constraint}** — how this decision upholds it.

## Alternatives considered

For each option evaluated and rejected: what it is, why it was considered, why it lost. Undocumented rejections get relitigated.

**{Option}** — {what} · {why considered} · {why rejected}

## Consequences

- **Positive** — what this enables.
- **Trade-offs** — what it costs, constrains, or makes harder.
- **Follow-on** — decisions this creates or forecloses.
