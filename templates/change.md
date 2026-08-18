# Change spec

The structure for a single piece of work. This is the body of the **tracker issue** (`tracker`) — there is no separate file. It is what the builder builds and the reviewer reviews against. Scale every section to the size of the work: a one-line fix needs a sentence, a cross-cutting change needs all of it.

---

## Problem

Why this change, now. One or two sentences.

## Approach

How the change lands — the shape of the solution at a glance.

## Grounding

*Record current reality for the facts this change rests on — every one that names a file / function / flag / version / decision — verified against the code as it is now, not recalled from memory. State what was checked with a `path:line` anchor (or a current version / flag value), surface any decision the ticket assumed settled that is actually open or superseded, and list open questions. Where a sub-agent host is available this is the read-only `researcher` agent's brief, recorded here verbatim; otherwise the executor self-grounds inline (the fallback). Always present, scaled to size — a one-line fix gets one line ("verified `foo.py:rename_flag` still exists"). See `spec-authoring` → Grounding.*

## Assurance

`trivial` | `simple` | `complex`

*Choose exactly one before build, per `spec-authoring` → *Choosing assurance* —
the one home for how that choice is made. What each level then obliges the run to
pay for: `trivial` requires the repo's conservative allowlist certification;
`simple` requires an independent review; `complex` requires an independent design
and review. Missing, conflicting, or unknown values default to `simple`. The run
may upgrade this value with a recorded reason but may not downgrade it.*

## Design

*The load-bearing part for anything non-trivial. Specify enough that an implementer does not invent a contract mid-build. Omit a sub-section only when the work genuinely does not touch it.*

### Data model
Entities, fields, relationships, invariants that change. Note migrations.

### Interface / contract
Endpoints, commands, or component contracts: request/response shapes, status and error cases, auth rules.

### Scenarios
Behaviour where it is non-obvious or edge cases are easy to forget.
- GIVEN {precondition} WHEN {action} THEN {outcome}

## Watchlist trigger

*Conditional — include this section only when the planned diff touches a file in `CONTEXT.md` `architecture_watchlist.files`. Record exactly one outcome: a small behavior-preserving seam extraction (name the seam and the test/smoke evidence), or an explicit deferral with a reason. See `architecture` → Architecture watchlist. Omit the section entirely when no watchlisted file is touched (or the repo has no watchlist).*

## Acceptance criteria

Specific, testable outcomes. Each must be verifiable by a test (not "feels right").
- AC-1: {…}
- AC-2: {…}

## Out of scope

What this change explicitly does not do. Substantial deferrals become their own change spec (or a proposal, if unconfirmed).
