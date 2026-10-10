---
proposal: {short-slug}
status: draft            # draft | under-decision | accepted | shipped | rejected | split | superseded
date: YYYY-MM-DD
related: []              # feature specs or other proposals
---

# {Title: the outcome in plain words}

## In brief

For a reader who was not in the conversation that produced this proposal and has two minutes. 250 words at most, table included; images don't count. No term that needs looking up, and no ticket number, principle number or file path doing work a plain phrase could do.

**So what.** Two or three sentences: what changes, for whom, and why now.

**What you get.** Only when the proposal changes something a user sees: the target-state screens of the recommended change, labelled as under *Visuals*, so the reader sees what they are getting before any analysis. Where they are not captured yet, write *Capture owed: {screen}, needs {route}* here as well, so the gap is the first thing the reader sees.

**What changes.**

| Today | After |
|---|---|
| {what the affected person sees or does now} | {what they see or do after} |

**What we need from you.** The decision this page asks for, its options and the recommended answer. Name any risk that bears on it. If nothing is open: approve as written.

## Settled already

Each question answered while this was drafted, with its answer and who gave it when, so a reader who missed the exchange sees both halves. Omit the section when there are none.

| Question | Answer | Who, when |
|---|---|---|
| {question} | {answer} | {who, date} |

## Why

The problem and its evidence, inline: the number, the short quote, the example. Never give a pointer the reader has to follow. Name the cost of the status quo: what happens if nothing is done. Define each term where it first appears.

## Options

The approaches considered. For each: what it is, and its trade-offs. Present real alternatives, not one blessed answer dressed as inevitable, and mark the recommended one.

**Option A — {name}** · {what it is} · {trade-offs}
**Option B — {name}** · {what it is} · {trade-offs}

## Recommendation

The proposed direction and why it wins over the others. Connect to `engineering` and to repo principles where relevant.

### Visuals

Required when the proposal changes something a user sees; omitted otherwise. The recommended target state already sits in *In brief*. This section holds the rest: the before-and-after pairs, each alternative's screens, and the analysis behind them.

A screen that exists starts from a capture of it taken through the repo's visual-evidence route (the *Visual evidence* section of its design-system rule), at a named commit. The "after" is the change built on a throwaway branch from the app's own components and captured the same way; that branch is never merged, and each capture names the commit or bundle it came from. Label every screen *Captured*, *Spike capture* or *Sketch, not the app*. A sketch never stands in for a screen that exists. Where this host cannot take a capture, put *Capture owed: {screen}, needs {route}* in its place. Diagrams and charts are not screens and need no label.

## Not doing

The capabilities considered and cut, one line each: the capability, why it is out, and the trigger that would reopen it. The raw material is the options rejected above, plus whatever the decision cut. A ticket this proposal spawns cites this section in its `Out of scope` rather than reconstructing the boundary from the recommendation, and nothing named here enters a spawned ticket without amending this proposal first.

- {capability} — {why it is out}. Reopen if {trigger}.

## Open decisions

What must be decided before this becomes work, its options, the recommended answer, and who decides. Once answered, a decision moves to *Settled already*. A cross-cutting decision (one future work must honour) is recorded, once made, in the spec it governs (`architecture`).

| Decision | Options | Recommended | Who decides |
|---|---|---|---|
| {question} | {option · option} | {answer, and why} | {user / architect} |

## Breakdown

The change specs this proposal would spawn once accepted, each declared separable or a sequential step (`authoring` → *Proposal spec*): a separable item becomes a tracker issue of its own, a run of sequential steps becomes one (`authoring` → change spec). Order them by dependency, not by what ships alone. Where the work introduces a shape that is expensive to unpick, that shape is item 1, held for the operator, and the items building on it declare a dependency on it. `authoring` → *Proposal spec* carries the four-dimension test that decides whether a shape earns that position.

1. {change} — {one-line scope} · `assurance:{level}` · {separable | sequential with N}
2. {change} — {one-line scope} · `assurance:{level}` · {separable | sequential with N}

## Risks

What could go wrong, what is not yet understood, what would invalidate the recommendation.

## For the builder

Grounding for the agents who file and build this: anchors by identifier, file paths, ticket numbers and tree facts, each read against a named commit. It sits last because the decider may skip it, and it is where the agents start.

---

**Lifecycle.** A proposal ends in one explicit state: **accepted** (spawn the change specs as tracker issues; record its decisions in the relevant specs), **rejected** (keep this file as the record of why), or **split** (replace with smaller proposals). It does not sit half-decided. Lives in `specs/proposals/`.

**`under-decision`** sits between `draft` and those three. A proposal is `draft` while it is worked and clarified, `under-decision` once it is handed over complete for a decision, and `accepted`, `rejected` or `split` only on an explicit act against it as written. An answered question is not that act: answers change what the proposal says, not what state it is in, so a run that asked four questions and got four replies still holds an `under-decision` proposal and has spawned nothing.

Two further states apply *after* the decision rather than instead of it: **shipped**, once the change specs it spawned have landed, and **superseded**, when the machinery it describes is retired — whether it was built first or not. Advance the status and amend the file **in place**, with a dated banner naming the record that superseded it; never move or delete it, so links stay stable and the audit keeps the reasoning. An `accepted` proposal is a standing instruction to build, so leaving one accepted after its subject died is how a later ticket inherits instructions targeting deleted code.
