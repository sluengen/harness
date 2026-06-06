<!-- guidance:architecture@0.1.0 -->
# Architecture

How to make and record design decisions. Loaded by the architect; consulted by anyone proposing a cross-cutting change. Built on `engineering-principles` — every significant decision should trace to a principle there (or to a repo principle in `CONTEXT.md`).

## What a design produces

A design is an artifact, not code. It answers *what* and *why* clearly enough that an implementer can build it test-first without guessing:

- **Contracts** — interfaces, endpoints, request/response shapes, status/error cases, auth rules.
- **Data model** — entities, fields, relationships, invariants.
- **Test strategy** — what to test, the key edge cases, the integration points. An implementer should be able to write a failing test from this.
- **Security considerations** — validation rules at each boundary, the trust model, what data is exposed to whom.
- **An ADR** when the decision is cross-cutting (see below).

Prefer simple, proven patterns over clever ones. Design for the current scope; leave room to extend, but do not build the extension (`engineering-principles`: no speculation).

## When to write an ADR

Write an Architecture Decision Record when a choice is **cross-cutting and expensive to reverse** — one future work must honour without relitigating. Examples: a stack or storage choice, a deployment topology, a security posture, a data-model invariant, an API-versioning rule.

Do **not** write an ADR for a routine choice that lives inside one feature. ADRs are for decisions whose scope crosses features. Use the [`adr` template](../templates/adr.md).

## Numbering and storage

ADRs are numbered sequentially: list the decisions directory (path in `CONTEXT.md`, commonly `decisions/`), take the next free `ADR-NNN`. Do not reuse the number of a cancelled ADR — leave the gap. One decision per file: `ADR-NNN-short-title.md`.

## Superseding an ADR

When a decision changes, do not edit the old ADR's substance. Supersede it, and complete all four steps or you leave stale context that misleads future work:

1. Set the old ADR's status to `Superseded by ADR-NNN`.
2. Set the new ADR's `Supersedes: ADR-NNN`.
3. Update the decisions index in `CONTEXT.md` so the one-line summary reflects the new decision.
4. Grep the repo for references to the old decision (code comments, specs, other ADRs) and update them.

## Recording, not deciding alone

Document the alternatives you rejected and why. Undocumented rejections get relitigated. A design that contradicts an existing ADR or a principle is a conscious trade-off: name it, and if it is cross-cutting, supersede the ADR rather than letting the contradiction sit silently.

Write designs and ADRs to the standard of `writing-quality`: state the decision plainly, name the actors, cut the hedging.
