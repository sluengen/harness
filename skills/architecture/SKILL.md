---
name: architecture
description: Use when making a cross-cutting design decision — data models, contracts, interfaces — and recording it in the spec it governs. Load when shaping how something is built; every decision should trace to engineering-principles.
---
<!-- guidance:architecture@0.5.0 -->
# Architecture

How to make and record design decisions. Loaded by the architect; consulted by anyone proposing a cross-cutting change. Built on `engineering-principles` — every significant decision should trace to a principle there, or to this repo's architecture-principles spec (see `spec-authoring` → reference specs).

## What a design produces

A design is an artifact, not code. It answers *what* and *why* clearly enough that an implementer can build it test-first without guessing:

- **Contracts** — interfaces, endpoints, request/response shapes, status/error cases, auth rules.
- **Data model** — entities, fields, relationships, invariants.
- **Test strategy** — what to test, the key edge cases, the integration points. An implementer should be able to write a failing test from this.
- **Security considerations** — validation rules at each boundary, the trust model, what data is exposed to whom.
- **The decisions behind it**, recorded in place (see below).

Prefer simple, proven patterns over clever ones. Design for the current scope; leave room to extend, but do not build the extension (`engineering-principles`: no speculation).

## When a choice is decision-worthy

Record a decision when a choice is **consequential and expensive to reverse** — one future work must honour without relitigating. Examples: a stack or storage choice, a deployment topology, a security posture, a data-model invariant, an API-versioning rule, a field-naming convention.

Do **not** record a decision for a routine choice with no lasting consequence. The bar is: would a future contributor benefit from knowing *why*, and would relitigating it be costly?

## Where the decision is recorded

The mechanics — which spec a decision lives in, the block's shape, and how to supersede it — are owned by `spec-authoring` → "Decisions live in the spec they govern". The short version: a decision is recorded **in the spec it governs** (a Decision block in the feature spec, or the architecture-principles spec for a cross-cutting one), never a standalone ADR or a `decisions/` folder, and is superseded **in place** with a dated note. This skill governs only *when* a choice rises to a decision (above) and *that* it is recorded honestly (below); the recording rule itself lives in one place, there.

## Recording, not deciding alone

Document the alternatives you rejected and why. A design that contradicts a recorded decision or a principle is a conscious trade-off: name it, and update the decision in its spec rather than letting the contradiction sit silently. Write designs and decisions to the standard of `writing-quality`: state the decision plainly, name the actors, cut the hedging.

## Architecture watchlist

Some files are **gravity wells** — the screen, orchestrator, or module where state, branching, and rendering keep accumulating because every nearby change is easiest to bolt on right there. "Refactor opportunistically when you touch one" is not a reliable instruction in a fully agentic system: if the trigger lives only in conversational memory, the next builder and reviewer never see it. A repo makes the trigger durable by naming those files in an **optional** `architecture_watchlist` in its `CONTEXT.md`:

```yaml
architecture_watchlist:
  files:
    - <repo-relative path or glob>   # a screen / orchestrator / module that keeps growing
```

The list is **repo-owned**: a repo opts in by naming its *own* gravity wells, and the universal guidance never hard-codes paths. It is **preserved across guidance updates** — `/update-guidance` never touches `CONTEXT.md`, so a repo's entries are never overwritten from the source. A repo that does not opt in has no `architecture_watchlist`, and the mechanism is a **no-op** for it.

**The trigger.** When the files a change touches — *planned* (the builder, before writing the change spec) or *actual* (the reviewer, from the diff) — intersect `architecture_watchlist.files`, the change must carry a **`Watchlist trigger`** section (in the change spec, confirmed at review) with exactly one of two outcomes:

1. **A small behavior-preserving seam extraction** — pull one cohesive seam (a sub-component, a pure helper, a branch) out of the gravity well, with tests or a smoke check proving behaviour is unchanged. Small and safe, not a rewrite (`engineering-principles`: smallest change — the larger refactor stays its own ticket).
2. **An explicit deferral** — record *why* extraction is deferred this time (no safe seam in this diff, too risky without a redesign, blocked on a decision). A named reason, not silence.

Either outcome is valid; an *unrecorded* one is not. Touching a gravity well is never invisible — the change either improves the seam or states on the record why it did not.

**Computing the touched set (the reviewer).** Compare the actual diff against the repo's **integration branch** (`CONTEXT.md` → `branches.integration`):

```bash
git diff --name-only "<integration-branch>...HEAD"
```

If the integration branch is unknown or unavailable — a detached checkout, or a `CONTEXT.md` that omits `branches.integration` — **fall back** to the working-tree diff (`git diff --name-only HEAD` plus staged and untracked files) so the check still runs against whatever this change adds, rather than skipping silently. Match each changed path against the watchlist globs.

**Refreshing the list.** The watchlist is not write-once. When the steward (`/assess code`, and the `--deep` arm) finds a recurring gravity well or repeated architectural drag in a file, it proposes adding that file to `architecture_watchlist` so the next change there trips the trigger (`assessment-craft`). This skill is the one home for the mechanism; the builder reference is in `spec-authoring` (the change-spec section) and the reviewer reference in `review-discipline` (the Stage-2 check).
