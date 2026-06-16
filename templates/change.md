<!-- guidance:template-change@0.1.0 -->
# Change spec

The structure for a single piece of work. This is the body of the **Linear issue** (`linear`) — there is no separate file. It is what the builder builds and the reviewer reviews against. Scale every section to the size of the work: a one-line fix needs a sentence, a cross-cutting change needs all of it.

---

## Problem

Why this change, now. One or two sentences.

## Approach

How the change lands — the shape of the solution at a glance.

## Design

*The load-bearing part for anything non-trivial. Specify enough that an implementer does not invent a contract mid-build. Omit a sub-section only when the work genuinely does not touch it.*

### Data model
Entities, fields, relationships, invariants that change. Note migrations.

### Interface / contract
Endpoints, commands, or component contracts: request/response shapes, status and error cases, auth rules.

### Scenarios
Behaviour where it is non-obvious or edge cases are easy to forget.
- GIVEN {precondition} WHEN {action} THEN {outcome}

## Acceptance criteria

Specific, testable outcomes. Each must be verifiable by a test (not "feels right").
- AC-1: {…}
- AC-2: {…}

## Out of scope

What this change explicitly does not do. Substantial deferrals become their own change spec (or a proposal, if unconfirmed).
