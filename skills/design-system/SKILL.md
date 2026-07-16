---
name: design-system
description: Use when doing frontend work in a repo whose design-system layer is on — building UI with its tokens, primitives, and patterns rather than degrading them. Routing and discipline, not a copy of the rules. Pair with ux-design for new-surface design.
---
<!-- guidance:design-system@0.3.1 -->
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

**Composition chrome a value scan can't see.** A sheet header, card shell, or list row is a *composition* of several token rules. Every value in it is already a token, so a raw-value scan sees nothing wrong even when the same composition is reimplemented inline across many files — the duplication lives at the composition layer, invisible to a value scan. Before adding chrome composed of three or more token rules, grep for an existing primitive; if that same composition already appears in three or more files, extract one. The rule of three applies to compositions, not just raw values.

**Extract, then finish adopting.** Extracting a primitive is not done at the first callsite. When you extract one from N inline copies, enumerate all N callsites in the ticket's acceptance criteria and migrate every one — or file an explicit follow-up listing the un-migrated callsites by `file:line`. A primitive with partial adoption is drift the value scan cannot see: the inline copies it was meant to retire become a maintained second source of truth.

**Materialise a primitive only when a consumer adopts it in the same change.** A primitive with zero callsites is not a design system — it is dead code the value scan cannot see: it passes every token-purity rule while the composition it was meant to own is duplicated inline and drifts. Build it *from* the first consumer, not ahead of one. A gate should fail an unadopted primitive — adopt it or delete it.

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
