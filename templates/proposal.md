<!-- guidance:template-proposal@0.1.2 -->
---
proposal: {short-slug}
status: draft            # draft | under-decision | accepted | shipped | rejected | split
date: YYYY-MM-DD
related: []              # feature specs or other proposals
---

# Proposal: {title}

> One sentence: what is being proposed and why it is worth a decision.

## Problem / motivation

Why this matters now. The situation that makes it worth considering, and what happens if nothing is done. Be specific — name the cost of the status quo.

## Options

The approaches considered. For each: what it is, and its trade-offs. Present real alternatives, not one blessed answer dressed as inevitable.

**Option A — {name}** · {what it is} · {trade-offs}
**Option B — {name}** · {what it is} · {trade-offs}

## Recommendation

The proposed direction and why it wins over the others. Connect to `engineering-principles` and to repo principles where relevant.

## Open decisions

What must be decided before this becomes work, and by whom. A cross-cutting decision (one future work must honour) is recorded, once made, in the spec it governs (`architecture`).

| Decision | Who decides | Recorded in |
|---|---|---|
| {question} | {user / architect} | {feature spec / architecture spec} |

## Breakdown

The change specs this proposal would spawn once accepted. Each should be shippable on its own and become a Linear issue (`spec-authoring` → change spec).

1. {change} — {one-line scope}
2. {change} — {one-line scope}

## Risks / unknowns

What could go wrong, what is not yet understood, what would invalidate the recommendation.

---

**Lifecycle.** A proposal ends in one explicit state: **accepted** (spawn the change specs as Linear issues; record its decisions in the relevant specs), **rejected** (keep this file as the record of why), or **split** (replace with smaller proposals). It does not sit half-decided. Lives in `specs/proposals/`.
