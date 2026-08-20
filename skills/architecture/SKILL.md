---
name: architecture
description: Use when making a cross-cutting design decision — data models, contracts, interfaces — and recording it in the spec it governs. Load when shaping how something is built; every decision should trace to the principles in engineering.
---
# Architecture

How to make and record design decisions. Loaded by the architect; consulted by anyone proposing a cross-cutting change. Built on `engineering` — every significant decision should trace to a principle there, or to this repo's architecture-principles spec (see `spec-authoring` → reference specs).

## What a design produces

A design is an artifact, not code. It answers *what* and *why* clearly enough that an implementer can build it test-first without guessing:

- **Contracts** — interfaces, endpoints, request/response shapes, status/error cases, auth rules.
- **Data model** — entities, fields, relationships, invariants.
- **Test strategy** — what to test, the key edge cases, the integration points. An implementer should be able to write a failing test from this.
- **Security considerations** — validation rules at each boundary, the trust model, what data is exposed to whom.
- **The decisions behind it**, recorded in place (see below).

Prefer simple, proven patterns over clever ones. Design for the current scope; leave room to extend, but do not build the extension (`engineering`: no speculation).

## When a choice is decision-worthy

Record a decision when a choice is **consequential and expensive to reverse** — one future work must honour without relitigating. Examples: a stack or storage choice, a deployment topology, a security posture, a data-model invariant, an API-versioning rule, a field-naming convention.

Do **not** record a decision for a routine choice with no lasting consequence. The bar is: would a future contributor benefit from knowing *why*, and would relitigating it be costly?

## Where the decision is recorded

The mechanics — which spec a decision lives in, the block's shape, and how to supersede it — are owned by `spec-authoring` → "Decisions live in the spec they govern". The short version: a decision is recorded **in the spec it governs** (a Decision block in the feature spec, or the architecture-principles spec for a cross-cutting one) and superseded **in place** with a dated note — never a standalone ADR or a `decisions/` folder unless the repo declares one (`CLAUDE.md` → `paths.decisions`), which is the only switch and carries its own threshold. This skill governs only *when* a choice rises to a decision (above) and *that* it is recorded honestly (below); the recording rule itself lives in one place, there.

## Recording, not deciding alone

Document the alternatives you rejected and why. A design that contradicts a recorded decision or a principle is a conscious trade-off: name it, and update the decision in its spec rather than letting the contradiction sit silently. Write designs and decisions to the standard of `writing-quality`: state the decision plainly, name the actors, cut the hedging.

## Architecture watchlist

Some files are **gravity wells** — the screen, orchestrator, or module where state, branching, and rendering keep accumulating because every nearby change is easiest to bolt on right there. "Refactor opportunistically when you touch one" is not a reliable instruction in a fully agentic system: if the trigger lives only in conversational memory, the next builder and reviewer never see it. A repo makes the trigger durable by naming those files in an **optional** `architecture_watchlist` in its `CLAUDE.md`:

```yaml
architecture_watchlist:
  files:
    - <repo-relative path or glob>   # a screen / orchestrator / module that keeps growing
```

The list is **repo-owned**: a repo opts in by naming its *own* gravity wells, and the universal guidance never hard-codes paths. It is **preserved across guidance updates** — `/update-guidance` never touches `CLAUDE.md`, so a repo's entries are never overwritten from the source. A repo that does not opt in has no `architecture_watchlist`, and the mechanism is a **no-op** for it.

**The trigger.** When the files a change touches — *planned* (the builder, before writing the change spec) or *actual* (the reviewer, from the diff) — intersect `architecture_watchlist.files`, the change must carry a **`Watchlist trigger`** section (in the change spec, confirmed at review) with exactly one of two outcomes:

1. **A small behavior-preserving seam extraction** — pull one cohesive seam (a sub-component, a pure helper, a branch) out of the gravity well, with tests or a smoke check proving behaviour is unchanged. Small and safe, not a rewrite (`engineering`: smallest change — the larger refactor stays its own ticket).
2. **An explicit deferral** — record *why* extraction is deferred this time (no safe seam in this diff, too risky without a redesign, blocked on a decision). A named reason, not silence.

Either outcome is valid; an *unrecorded* one is not. Touching a gravity well is never invisible — the change either improves the seam or states on the record why it did not.

**Who carries the section.** Review is the last checkpoint, not the only one — where the repo's process runs a distinct design step before the build, that step is the earlier carrier: when its grounding diff or ticket touches `architecture_watchlist.files`, its output should include the `Watchlist trigger` section, the same way its other sections are already conditioned on what the change touches. The section stays **conditional** — present only when the touched set intersects the watchlist, absent otherwise. Review then *confirms* the record is there rather than being the first and only place it could have been remembered; a repo with no such stage is unaffected, and the builder stays the carrier with review as the sole confirmation, exactly as today.

**Computing the touched set (the reviewer).** Compare the actual diff against the repo's **integration branch** (`CLAUDE.md` → `branches.integration`):

```bash
git diff --name-only "<integration-branch>...HEAD"
```

If the integration branch is unknown or unavailable — a detached checkout, or a `CLAUDE.md` that omits `branches.integration` — **fall back** to the working-tree diff (`git diff --name-only HEAD` plus staged and untracked files) so the check still runs against whatever this change adds, rather than skipping silently. Match each changed path against the watchlist globs.

**Refreshing the list.** The watchlist is not write-once. When the steward (`/assess code`) finds a recurring gravity well or repeated architectural drag in a file, it proposes adding that file to `architecture_watchlist` so the next change there trips the trigger (`assessment-craft`). This skill is the one home for the mechanism; the builder reference is in `spec-authoring` (the change-spec section) and the reviewer reference in `review-discipline` (the Stage-2 check).

**Growing the list from a change.** A **second seam extraction** from the same **non-watchlisted module** is itself the signal that the module is a gravity well: add it to `CLAUDE.md`'s `architecture_watchlist.files` in that change. Give the entry the same descriptive comment the entry-currency rule requires. One extraction alone does not qualify; the point is to make repeated structural drag durable without waiting for a steward pass.

## Architecture assessment

The steward loads this section for `/assess architecture` (`agents/steward.md`, the `architecture` scope). Where a design decision (above) shapes *one* change, an architecture assessment steps back and judges the *whole* system shape periodically: **is the shape still right for the product, and what should we preserve, change, or watch?** It is a holistic judgement, not a finding sweep — its output is a verdict and a narrative (`templates/assessment.md`, the architecture report shape), and only the *actionable* risks become tickets (`assessment-craft`: a report may carry non-ticket narrative; `commands/assess.md`: file only actionable architecture risks).

Assess against these lenses — each grounded in `engineering` and this repo's architecture-principles spec:

1. **Purpose fit** — are the major structural choices still serving the product, or has the product moved past them?
2. **Boundary integrity** — are the API / client / domain / data boundaries holding, or has logic leaked across them?
3. **Domain-model coherence** — do names, entities, and invariants still match the product language, or has the model drifted from the words the team uses?
4. **Change ergonomics** — where are gravity wells or awkward seams forming — the files every change has to fight? (Feed these to the `architecture_watchlist`, above.)
5. **Operational / efficiency fit** — is the deploy / test / local-dev workflow aligned with how the system is actually run and changed?
6. **Verification architecture** — do the tests and gates prove the *important* contracts, or do they cluster on the easy ones while a load-bearing path goes unguarded?
7. **Spec-record health** — do the as-built records (feature specs / `SPEC.md` / `specs/`) still match shipped behaviour?
8. **Watchlist recommendations** — which files or boundaries should trip a conditional refactor on the next touch? Propose them for the repo's `architecture_watchlist` (above).

The assessment names **positive bets to preserve** as first-class output, not only risks: a holistic review that records what is working and which trade-off to keep is doing its job even when it files no ticket. Calibrate risks with the `assessment-craft` finding bar — evidence first, a concrete fix, an honest blocking call — but keep the narrative (verdict, what is working, trade-offs) in the report rather than forcing it into the tracker.
