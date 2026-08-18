**Tracker operations go through the `tracker` skill.** Read `CONTEXT.md`'s `tracker:` field and use the matching provider recipe — `linear` → the `linear` skill, `github` → the `github-issues` skill, `none` → the degrade the `tracker` skill documents. Do not embed provider API calls here.
# /propose — work an idea before it becomes work

Usage: `/propose <idea>`

Creates and works a **proposal spec** for an idea that is not yet confirmed work — it needs a decision, carries real unknowns, or is too big to be a single change. The proposal is where the thinking happens before build time is spent. Implements the proposal tier of `spec-authoring`.

Use this when the idea is unconfirmed or large. A small, clear piece of work skips the proposal — go straight to `/start` (a change spec on a tracker issue).

## Steps

### 1. Scaffold
Create `specs/proposals/<slug>.md` from `templates/proposal.md`. Slug from the idea.

### 2. Work it through
Fill the proposal following `spec-authoring`:
- Problem / motivation — why now.
- Options with trade-offs — real alternatives, not one inevitable answer.
- Recommendation — the proposed direction, tied to `engineering-principles`.
- Open decisions — what must be decided and by whom. Surface these to the user; a cross-cutting one is recorded in the architecture-principles spec, or in the repo's configured `paths.decisions` directory when it clears that bar (`spec-authoring`, `architecture`).
- Breakdown — the change specs this would spawn, each shippable on its own.
- Risks / unknowns.

Write to the standard of `writing-quality`. Do not present an unresolved decision as settled.

### 3. Get a decision
Bring the open decisions to the user. Set the proposal's `status` to the outcome:
- **accepted** → proceed to step 4.
- **rejected** → keep the file as the record of why; stop.
- **split** → replace with smaller proposals; stop.

### 4. On accepted, spin out the work
- Record the decisions in the specs they govern (`architecture`, `templates/decision.md`).
- Create an issue per item in the breakdown through the `tracker` skill's `create` operation — which sets queue placement explicitly, or the item is filed but invisible to the queue — each with a change spec (`templates/change.md`) and exactly one assurance level chosen per `spec-authoring` → *Choosing assurance*. Link them back to the proposal. Under `tracker: none` the breakdown stays in the proposal file and is reported to the operator.

## Report
Print the proposal path, its status, the open decisions (and how they resolved), any decisions recorded, and the issues created from the breakdown.
