---
name: design-system
description: Use when doing frontend work in a repo whose design-system layer is on — building UI with its tokens, primitives, and patterns rather than degrading them. Routing and discipline, not a copy of the rules. Pair with ux-design for new-surface design.
---
<!-- guidance:design-system@0.2.1 -->
# Design System

How to do frontend work without degrading the design system. Applies only when the repo's `design_system` layer is on; the system itself (tokens, primitives, principles) lives at the path in `CONTEXT.md`, often a dedicated subpackage or repo. This skill is routing and discipline, not a copy of the rules.

**This is the *don't degrade the system* half.** Designing or mocking up a *new* surface — deciding what it should be, not just conforming an existing one — starts with `ux-design` (the human, psychology, flow, and states). Use that to shape the surface, then this skill to materialize it in real tokens and primitives.

## Before any visual change — two-stage lookup

1. **Find the principle.** What does the design system say should be true here? (Its brand/UX principles, named in `CONTEXT.md`.)
2. **Find the materialization.** Where is that principle expressed in code — the token definitions, the primitive components? Use those.

If you are about to write a visual value by hand, stop and do this lookup first.

## Token discipline

Use named tokens, never raw values, wherever a token exists: colours, typography, spacing, radii. A hardcoded hex or a one-off pixel value where a token is defined is a defect — it drifts the moment the token changes. If no token covers your case, that is a gap to raise with the system, not a licence to hardcode.

## Primitives over bespoke markup

If a primitive exists for what you are building (button, card, field, badge, empty state), use it. Reimplementing its markup inline forks the design: the two copies drift, and the bespoke one decays. Build a new primitive in the system only when a pattern appears three or more times with no primitive (`code-quality`: rule of three).

## Adoption vs conformance

Two distinct questions; keep them apart:
- **Adoption** — does this screen use the right primitive and tokens? This is your job on every frontend change.
- **Conformance** — does the primitive itself render to spec? That is a question for changes to the primitive, reviewed against the visual reference, not something to re-check on every consuming screen.

## Don't degrade the system

A change to a primitive or a token ripples everywhere it is used. Before altering one:
- Check the UX principle it serves — a change that violates the principle is a regression even if it looks fine on your screen.
- Consider every consumer, not just the one in front of you.
- A change that relaxes a stated principle needs an explicit principle update with a rationale, not a silent edit (mirrors `engineering-principles`: trade-offs are conscious).

The reviewer checks adoption and accessibility on frontend changes (`review-discipline`).
