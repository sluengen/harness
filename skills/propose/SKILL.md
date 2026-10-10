---
name: propose
description: "/propose — work an idea to a decision before build time is spent: a proposal spec with options and trade-offs, a recommendation, the open decisions, and a breakdown that becomes tickets once it is accepted. Use when the operator says `/propose`, \"should we do X\", \"work up an approach for X\", or \"this is too big for one ticket\" — an idea that is unconfirmed, carries real unknowns, or spans several changes. Not for work already decided (`/capture` files that onto the queue), not for a one-line fix, and it writes no code. Operator-triggered only; the model does not fire it."
disable-model-invocation: true
model: inherit
effort: high
---

The portable plugin root is two directories above this SKILL.md. Resolve embedded paths beginning `skills/`, `agents/`, `templates/`, `hooks/`, or `.codex/` from that root; resolve repository artifacts from the workspace root.

# /propose — work an idea before it becomes work

Usage: `/propose <idea>`

Creates and works a **proposal spec** for an idea that is not yet confirmed work — it needs a decision, carries real unknowns, or is too big to be a single change. The proposal is where the thinking happens before build time is spent. Implements the proposal tier of `authoring`.

Use this when the idea is unconfirmed or large. A small, clear piece of work skips the proposal — `/capture` files it onto the queue, and the smallest needs no ticket at all (the spine's fix lane). Every tracker read or write here goes through `tracker`, per the spine's *Tracker dispatch* contract.

## Steps

### 1. Scaffold
Create `specs/proposals/<slug>.md` from `templates/proposal.md`. Slug from the idea.

**Decide now whether the proposal changes something a user sees, and whether this host can capture it.** Where it does, read the repo's visual-evidence route, which is the *Visual evidence* section of its design-system rule, and check that this host can take the captures it needs: today's screens, and the change built on a throwaway branch. Where it cannot, because the route needs a machine this is not or the repo declares no route at all, tell the operator before drafting. Name the screens and the route they need, so they can relaunch somewhere that can. Then carry on: those screens are *Capture owed* in the draft, and step 3 says where they go.

### 2. Work it through
Fill the proposal following `authoring`:
- In brief — for a reader who was not in this conversation: so what, what you get (the target-state screens, for a change someone will see), what changes, and what we need from you. Write it last, from the sections below, within the template's word budget.
- Settled already — every question answered while drafting, beside its answer and who gave it. An answer that changes the proposal also changes the section it governs.
- Why — the problem, its evidence inline, and the cost of doing nothing.
- Options with trade-offs — real alternatives, not one inevitable answer.
- Recommendation — the proposed direction, and the principle it traces to (`architecture`). For a change someone will see, its *Visuals* follow the template: captures of today, the change built on a throwaway branch and captured the same way, each screen labelled.
- Not doing — fill it from the options you actually rejected, one line each: the capability, why it is out, and the trigger that would reopen it. A rejected option is already a non-goal with its reason attached, so carry it down here instead of leaving each spawned ticket to re-derive the boundary.
- Open decisions — what must be decided, its options, the recommended answer, and who decides. Surface these to the user; a cross-cutting one is recorded in the architecture-principles spec, or in the repo's configured `paths.decisions` directory when it clears that bar (`authoring` → *Decisions live in the spec they govern*).
- Breakdown — the change specs this would spawn, ordered by dependency and foundations first (`authoring` → *Proposal spec*).
- Risks.
- For the builder — the grounding the agents who file and build this will need, read against a named commit.

Write to the standard of `authoring` → `references/prose.md`. Do not present an unresolved decision as settled.

### 3. Hand it over, then wait for a decision
Hand over two things: the completed proposal spec, and a shareable rendering of it, published wherever the host can publish one. Where the host cannot publish one, say so and the proposal file is the rendering — the same degradation as `tracker: none`. The rendering is what the decision is taken against, and it is where a misunderstanding surfaces before tickets are filed rather than after. Bring the open decisions over with it.

**The rendering follows the file.** It shows the file's sections in the file's order and adds nothing the file does not say. *In brief*, with its target-state screens, is what the reader lands on, and *For the builder* is folded away or left as a link to the file. A rendering that restyles the proposal is a second document, and the reader cannot tell which one was decided.

**Run a cold read before you hand it over.** Give a fresh agent the rendering and nothing else, neither this conversation nor the repo, and ask it for the so-what, what changes, and the decision asked. Where its answer differs from *In brief*, the page is wrong, not the reader: fix the page and read it again. Ask it too for every term it could not follow without outside context, and define or replace those in *In brief*. Where the host cannot start a fresh agent, say so in the hand-over.

**Screens still owed go one of two ways, and the operator picks.** Either the run hands off to a session that can capture them, naming each screen and the route it needs, or the decision proceeds without them and step 4 files their capture first. Ask which in the hand-over; the status is `under-decision` either way.

Set `status` to `under-decision` and stop there.

**Advance only on an explicit act against the proposal as written.** An answered clarifying question is not that act, and neither is engagement with the content, silence, or a direction chosen on a single open decision. Those settle what the proposal says and leave its state alone. An approval names the proposal and says proceed. Step 4 files tickets, so a run that reads clarification as approval creates work nobody agreed to and consumes queue slots holding it. Where you cannot point to the act, the status stays `under-decision`, step 4 does not run, and the report says so.

On that act, set `status` to the outcome:
- *accepted* → proceed to step 4.
- *rejected* → keep the file as the record of why; stop.
- *split* → replace with smaller proposals; stop.

### 4. On accepted, spin out the work
- Record the decisions in the specs they govern (`architecture`, `templates/decision.md`).
- File the breakdown as one batch through `tracker`'s `create` operation, which consolidates it by each item's separable-or-sequential declaration and sets queue placement explicitly, or a ticket is filed but invisible to the queue. Each ticket carries a change spec (`templates/change.md`) and exactly one assurance level chosen per `authoring` → *Choosing assurance*. Link them back to the proposal. Under `tracker: none` the breakdown stays in the proposal file and is reported to the operator.
- **Where the tracker models a parent/sub-issue relationship, file the breakdown under one umbrella issue** and every ticket as its sub-issue, through `tracker`'s `create` operation. The grouping is what makes a set of tickets legible as one initiative on the board, and the umbrella is where the initiative gets audited against what the proposal decided. What the umbrella carries, and how it stays out of the build loop, is that backend's reference; a backend without the relationship files the breakdown flat and the rest of this step is unchanged.
- File them in the breakdown's order, foundations first, and declare each ticket's dependency on the one it builds on. Where the four-dimension test fired (`authoring` → *Proposal spec*), hold the foundations item through `tracker`'s `hold` operation with the `input` label, so the unattended loop cannot start the shape before the operator has seen it.
- **Where screens are still *Capture owed* at acceptance, their capture is the first ticket.** It comes in addition to the breakdown's own tickets: file it before any of them, under the umbrella where there is one, and hold it through `tracker`'s `hold` with the `operator` label: capture today's screens and the change built on a throwaway branch, and lock them into the proposal's *Visuals*. Every ticket that changes a screen declares its dependency on it, so no screen work starts against a guessed screen.
- Give each spawned ticket an `Out of scope` that cites the proposal's *Not doing* rather than re-deriving the boundary. Nothing named there enters a ticket without amending the proposal first.

## Report
Print the proposal path and where the rendering was published — or, where the host could not publish one, say so and name the file as the rendering — then what the cold read returned, any screens still owed and where they went, the status, the open decisions (and how they resolved), any decisions recorded, and the issues created from the breakdown.

Where the run stopped at `under-decision`, say so, name the act you could not point to, and list no issues: step 4 did not run, and a report that omits the stop reads as a run that finished.
