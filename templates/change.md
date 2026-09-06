# Change spec

The structure for a single piece of work. This is the body of the **tracker issue** — there is no separate file. It is what the builder builds and the reviewer reviews against. Scale every section to the size of the work: a one-line fix needs a sentence, a cross-cutting change needs all of it.

**Capture mode.** `/capture` fills this template at the moment of noticing, not the moment of building: the kind (`bug` — as-built contradicts intent, repro required · `tweak` — correct behaviour being upgraded), what was observed, the desired outcome, the situation that surfaced it, the cost line, and the acceptance criteria. Grounding and Design stay empty until `/build` extends the spec at build time. A tweak that turns out to carry a real decision or spawn more than one change is not a tweak — stop and `/propose` it.

**The title is verb + where** — *refuse a push with no marker*, *split the plugin-surface record*. A noun phrase names a topic; the queue is read by agents ranking work they did not file, and a topic does not say what done looks like.

**`[NEEDS CLARIFICATION: …]` is the unanswered-question marker.** Write it inline, in the sentence the answer would change, wherever intake could not settle something material. `/build` refuses to start while one remains, so the marker is a hold with a location rather than a note somebody has to notice. Answering one means replacing the sentence it sits in, not appending the answer beside it.

---

## Problem

Why this change, now. Two or three sentences at build time. A capture fills it
with more, because it is the only narrative heading `/capture` has: the kind and
the area, what happens today, what is wanted, and the situation that surfaced it.

## Cost

*Required at creation; a filing without it is incomplete.* One line: what this costs, what it buys, which principle it serves and which it spends against, and which waste it removes or adds. The waste categories are the spine's P2 — rework, waiting, over-processing, over-production, motion, inventory, defects. Naming what a change *spends* is the half that gets skipped, and it is the half that lets an operator refuse work that only adds inventory.

- *Cost:* {…} *Buys:* {…} *Serves:* P{n}. *Spends against:* P{n}, by {…}. *Waste:* removes {category} / adds {category}.

## Approach

How the change lands — the shape of the solution at a glance.

## Grounding

*Record current reality for the facts this change rests on — every one that names a file / function / flag / version / decision — verified against the code as it is now, not recalled from memory. State what was checked with a `path:line` anchor (or a current version / flag value), surface any decision the ticket assumed settled that is actually open or superseded, and list open questions. Where a sub-agent host is available this is a host-native read-only sub-agent's brief, recorded here verbatim; otherwise the executor self-grounds inline (the fallback). Always present, scaled to size — a one-line fix gets one line ("verified `foo.py:rename_flag` still exists"). See `authoring` → Grounding.*

## Lane

`trivial` (fix) | `simple` (change) | `complex` (feature)

*Choose exactly one before build, per `authoring` → *Choosing assurance* —
the one home for how that choice is made. What each lane then obliges the run to
pay for: the **fix** lane ships on the gate and the push guard alone, with no
reviewer and no as-built record; **change** requires an independent review;
**feature** requires an independent design and review. Missing, conflicting, or
unknown values default to `simple`. The run may upgrade this value with a
recorded reason but may never downgrade it.*

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

*Conditional — include this section only when the planned diff touches a file in `harness.yaml` `architecture_watchlist.files`. Record exactly one outcome: a small behavior-preserving seam extraction (name the seam and the test/smoke evidence), or an explicit deferral with a reason. See `architecture` → Architecture watchlist. Omit the section entirely when no watchlisted file is touched (or the repo has no watchlist).*

## Acceptance criteria

Specific outcomes. For each, name what it protects and state the evidence selected from ADR 0019. Use RED then GREEN for executable behaviour and invariants; a runtime floor needs its declaration plus functional execution. Request direct review or representative use for prose, never a predicate or wording guard.
- AC-1: {…}
- AC-2: {…}

## Assumptions

*Decisions taken without the authority to take them.* One line each, or `none`. A question intake could not get answered and could not defer is recorded here as the answer that was assumed, so a reviewer reads what was decided rather than reconstructing it from the diff. An assumption that turns out wrong is a finding against the spec, not against the builder. Anything still genuinely open stays a `[NEEDS CLARIFICATION]` marker instead — an assumption is a decision, a marker is a hold.

## Protected areas

*A tripwire, not a scope note.* Name the surfaces where a diff must **stop and hold** rather than proceed on a stated assumption: authentication, billing, migrations, permissions, the gate, the hooks, and whatever else this repo treats that way. Reaching one is an andon pull (P4) — comment, label, assign — never an assumption recorded in the section above. Write `none` when the change touches no such surface; the section is never omitted, because a blank one and an absent one read the same and only one of them means the question was asked.

## Out of scope

What this change explicitly does not do. Substantial deferrals become their own change spec (or a proposal, if unconfirmed).
