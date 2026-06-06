<!-- guidance:architecture@0.2.0 -->
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

## Where the decision lives

There are **no standalone ADRs and no `decisions/` folder**. A decision is recorded **in the spec it governs**, so the what and the why stay together (`spec-authoring` → "Decisions live in the spec they govern"):

- **Governs one feature** → a **Decision** block in that **feature spec** (`templates/decision.md` is the embeddable shape).
- **Cross-cutting** (governs many features, or the system's shape) → the **architecture-principles spec**, as a principle plus its rationale and the alternatives rejected.

A decision block records: **context** (what forced the choice), **decision** (what was chosen, stated plainly), **alternatives** (what was rejected and why — undocumented rejections get relitigated), and **consequences** (what it enables, costs, and forecloses).

## Superseding a decision

When a decision changes, **update it in place** in its spec — do not leave a stale version elsewhere. Replace the decision text with the new choice, and add a dated note: *"Superseded YYYY-MM-DD: previously X; changed to Y because Z."* Then grep the repo for code/comments/specs that relied on the old decision and update them. The spec always shows the current decision with its history inline, not a chain of separate files to reconcile.

## Recording, not deciding alone

Document the alternatives you rejected and why. A design that contradicts a recorded decision or a principle is a conscious trade-off: name it, and update the decision in its spec rather than letting the contradiction sit silently. Write designs and decisions to the standard of `writing-quality`: state the decision plainly, name the actors, cut the hedging.
