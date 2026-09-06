---
name: architecture
description: Use when making or judging a cross-cutting design decision — data models, contracts, interfaces, or a proposal someone hands you — and recording it in the spec it governs. Also holds the architecture watchlist (the gravity-well files that trip a conditional refactor on the next touch) and the lenses for a periodic architecture assessment. Load when shaping how something is built; every decision should trace to the principles in `engineering`. Not for implementation technique, test mechanics, or the shape of a spec document — those are `engineering` and `authoring`.
model: inherit
---
# Architecture

How to make, judge, and record design decisions. Loaded by the architect; consulted by anyone proposing a cross-cutting change. Every significant decision traces to a principle in `engineering`, or to this repo's architecture-principles spec.

## What a design produces

A design is an artifact, not code. It answers *what* and *why* clearly enough that an implementer can build it test-first without guessing:

- Contracts — interfaces, endpoints, request/response shapes, status and error cases, auth rules.
- Data model — entities, fields, relationships, invariants.
- Test strategy — what to test, the key edge cases, the integration points. An implementer should be able to write a failing test from this alone.
- Security considerations — validation at each boundary, the trust model, what data is exposed to whom.
- The decisions behind it, recorded in the spec they govern.

Prefer simple, proven patterns over clever ones. Design for the current scope; leave room to extend, but do not build the extension (`engineering`: no speculation).

## Judging a contract someone hands you

Contracts arrive to be judged as well as written — a proposal, a migration plan, an integration another team designed. Judge each against the list above, then against what it assumes about the other side.

A condition defined by what the other side *lacks* reads absence as consent: "the repo has no first-party JavaScript and no custom verify command" treats a gap as agreement to whatever happens next. It also silently encodes your own repo's shape as the default consumer — the cases you did not enumerate are the consumers you did not picture, and reading the target repo cannot recover them, because the assumption lives in the designer rather than in the target.

So do two things, not one. Name the assumption about the consumer in a sentence its reader can disagree with — "this assumes a consumer shaped like ours: one language, the stock gate". Then restate the condition as something the consumer **positively declares** — a marker, a declared capability, an opt-in — so a consumer you never imagined either declares itself in or stays out. Replacing an absence condition with positive identification while leaving the assumption unnamed fixes the symptom and keeps the blind spot.

## When a choice is decision-worthy

Record a decision when a choice is **consequential and expensive to reverse** — one that future work must honour without relitigating: a stack or storage choice, a deployment topology, a security posture, a data-model invariant, an API-versioning rule, a field-naming convention. A routine choice with no lasting consequence gets none. The bar: would a future contributor benefit from knowing *why*, and would relitigating it be costly?

## Recording it honestly

Which spec a decision lives in, the block's shape, and how to supersede it are owned by `authoring` → *Decisions live in the spec they govern*; follow it there rather than a copy here. This skill governs only *when* a choice rises to a decision, and that the record is honest:

- Document the alternatives you rejected and why. A reader who cannot see the rejected branch re-proposes it.
- A design that contradicts a recorded decision or a principle is a conscious trade-off. Name it and update that decision in its spec — a contradiction left standing makes both records untrustworthy.
- Write decisions to the standard of `authoring` → `references/prose.md`: state the decision plainly, name the actors, cut the hedging.

## Architecture watchlist

Some files are gravity wells — the screen, orchestrator, or module where state, branching, and rendering keep accumulating because every nearby change is easiest to bolt on right there. "Refactor opportunistically when you touch one" is not a reliable instruction in a fully agentic system: a trigger that lives only in conversational memory is invisible to the next builder and reviewer. A repo makes it durable by naming those files in an optional `architecture_watchlist` in its `harness.yaml`:

```yaml
architecture_watchlist:
  files:
    - <repo-relative path or glob>   # a screen / orchestrator / module that keeps growing
```

The list is repo-owned: a repo opts in by naming its *own* gravity wells, and this guidance never hard-codes paths. `/update-guidance` never touches `harness.yaml`, so a repo's entries are never overwritten from the source. A repo that does not opt in has no `architecture_watchlist`, and the whole mechanism is a no-op for it.

### The trigger

When the files a change touches — *planned* (the builder, before writing the change spec) or *actual* (the reviewer, from the diff) — intersect `architecture_watchlist.files`, the change carries a **`Watchlist trigger`** section in its change spec, confirmed at review, recording exactly one of two outcomes:

1. A small behaviour-preserving seam extraction — pull one cohesive seam (a sub-component, a pure helper, a branch) out of the gravity well, with tests or a smoke check proving behaviour is unchanged. Small and safe, not a rewrite; the larger refactor stays its own ticket (`engineering`: smallest change).
2. An explicit deferral — why extraction is deferred this time (no safe seam in this diff, too risky without a redesign, blocked on a decision). A named reason, not silence.

Either outcome is valid; an unrecorded one is not. Touching a gravity well is never invisible: the change either improves the seam or states on the record why it did not.

### Who carries the section

Review *confirms* the record; it is not the only place the record can be made. Where the repo runs a distinct design step before the build, that step is the earlier carrier: when its grounding diff or ticket touches `architecture_watchlist.files`, its output carries the `Watchlist trigger` section, the same way its other sections are conditioned on what the change touches. The section stays conditional — present only when the touched set intersects the watchlist, absent otherwise. A repo with no design stage is unaffected: the builder carries the section and review is its sole confirmation.

### Computing the touched set (the reviewer)

Compare the actual diff against the repo's integration branch (`harness.yaml` → `branches.integration`):

```bash
git diff --name-only "<integration-branch>...HEAD"
```

If the integration branch is unknown or unavailable — a detached checkout, or a `harness.yaml` that omits `branches.integration` — fall back to the working-tree diff (`git diff --name-only HEAD` plus staged and untracked files), so the check still runs against whatever this change adds rather than skipping silently. Match each changed path against the watchlist globs.

### Refreshing and growing the list

The watchlist is not write-once, and it grows two ways.

- **The steward proposes an entry.** When an `/assess code` pass finds a recurring gravity well or repeated architectural drag in a file, it proposes adding that file so the next change there trips the trigger; `assess` owns the bar such a finding has to clear.
- **A change adds its own entry.** A *second* seam extraction from the same non-watchlisted module is itself the signal that the module is a gravity well: add it to `architecture_watchlist.files` in that change, with the same descriptive comment the entry-currency rule requires. One extraction alone does not qualify. This is what makes repeated structural drag durable without waiting for a steward pass.

This skill is the mechanism's one home; the change-spec template and the reviewer's checks point here rather than restating it.

## Architecture assessment

The steward loads this section for `/assess architecture`. Where a design decision shapes *one* change, an architecture assessment judges the *whole* system shape: is that shape still right for the product, and what should we preserve, change, or watch? It is a holistic judgement, not a finding sweep — its output is a verdict and a narrative (`templates/assessment.md`, the architecture report shape), and only the *actionable* risks become tickets. `assess` owns that report contract; do not re-derive it here.

Assess against these lenses, each grounded in `engineering` and this repo's architecture-principles spec:

1. Purpose fit — are the major structural choices still serving the product, or has the product moved past them?
2. Boundary integrity — are the API / client / domain / data boundaries holding, or has logic leaked across them?
3. Domain-model coherence — do names, entities, and invariants still match the product language, or has the model drifted from the words the team uses?
4. Change ergonomics — where are gravity wells or awkward seams forming, the files every change has to fight? (Feed these to the `architecture_watchlist` above.)
5. Operational / efficiency fit — is the deploy / test / local-dev workflow aligned with how the system is actually run and changed?
6. Verification architecture — do the tests and gates prove the *important* contracts, or do they cluster on the easy ones while a load-bearing path goes unguarded?
7. Spec-record health — do the as-built records still match shipped behaviour?
8. Watchlist recommendations — which files or boundaries should trip a conditional refactor on the next touch? Propose them for the repo's `architecture_watchlist`.

Name the positive bets to preserve as first-class output, not only the risks: a pass that records what is working and which trade-off to keep is doing its job even when it files no ticket. Calibrate each risk you do file to the finding bar `assess` carries — evidence first, a concrete fix, an honest blocking call — and leave the verdict, what is working, and the trade-offs in the report rather than forcing them into the tracker.
