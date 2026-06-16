---
name: architecture
description: Use when making a cross-cutting design decision — data models, contracts, interfaces — and recording it in the spec it governs. Load when shaping how something is built; every decision should trace to engineering-principles.
---
<!-- guidance:architecture@0.4.0 -->
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
