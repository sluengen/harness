---
proposal: {short-slug}
status: draft            # draft | under-decision | accepted | shipped | rejected | split | superseded
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

The proposed direction and why it wins over the others. Connect to `engineering` and to repo principles where relevant.

## Not doing

The capabilities considered and cut, one line each: the capability, why it is out, and the trigger that would reopen it. The raw material is the options rejected above, plus whatever the decision cut. A ticket this proposal spawns cites this section in its `Out of scope` rather than reconstructing the boundary from the recommendation, and nothing named here enters a spawned ticket without amending this proposal first.

- {capability} — {why it is out}. Reopen if {trigger}.

## Open decisions

What must be decided before this becomes work, and by whom. A cross-cutting decision (one future work must honour) is recorded, once made, in the spec it governs (`architecture`).

| Decision | Who decides | Recorded in |
|---|---|---|
| {question} | {user / architect} | {feature spec / architecture spec} |

## Breakdown

The change specs this proposal would spawn once accepted, each becoming a tracker issue (`authoring` → change spec). Order them by dependency, not by what ships alone. Where the work introduces a shape that is expensive to unpick, that shape is item 1, held for the operator, and the items building on it declare a dependency on it. `authoring` → *Proposal spec* carries the four-dimension test that decides whether a shape earns that position.

1. {change} — {one-line scope}
2. {change} — {one-line scope}

## Risks / unknowns

What could go wrong, what is not yet understood, what would invalidate the recommendation.

---

**Lifecycle.** A proposal ends in one explicit state: **accepted** (spawn the change specs as tracker issues; record its decisions in the relevant specs), **rejected** (keep this file as the record of why), or **split** (replace with smaller proposals). It does not sit half-decided. Lives in `specs/proposals/`.

**`under-decision`** sits between `draft` and those three. A proposal is `draft` while it is worked and clarified, `under-decision` once it is handed over complete for a decision, and `accepted`, `rejected` or `split` only on an explicit act against it as written. An answered question is not that act: answers change what the proposal says, not what state it is in, so a run that asked four questions and got four replies still holds an `under-decision` proposal and has spawned nothing.

Two further states apply *after* the decision rather than instead of it: **shipped**, once the change specs it spawned have landed, and **superseded**, when the machinery it describes is retired — whether it was built first or not. Advance the status and amend the file **in place**, with a dated banner naming the record that superseded it; never move or delete it, so links stay stable and the audit keeps the reasoning. An `accepted` proposal is a standing instruction to build, so leaving one accepted after its subject died is how a later ticket inherits instructions targeting deleted code.
