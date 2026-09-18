---
layer: 02-principles
kind: readme
status: scaffold
last_updated: 2026-09-18
---

# 02 · Principles

The interaction, motion, density and accessibility laws the surface obeys — the
rules that hold regardless of what changes in the layers below.

Scaffold — this file states what belongs here and is otherwise empty. A law
lands when a change needs it, not speculatively: a principle written before
anything tests it is a guess that later changes route around.

## What to write

- **The one constraint everything else answers to.** Most surfaces have one —
  it must render offline, it must work on a shared terminal, it must stay under
  a size budget, it must be printable. Write it first and say plainly whether it
  is **enforced** by something in the gate or merely **stated**, because a rule
  a reader assumes is mechanical is one nobody checks by hand.
- **Density.** Which way the surface leans between a scannable reference and a
  spacious page, and what the shared rhythm is — heading, body, actions. This is
  what makes "a new section needs its own spacing scale to breathe" a finding
  rather than a matter of taste.
- **What colour is for.** Whether a hue marks structure (which domain a thing
  belongs to) or mood. Layer 00 holds the mapping; this layer holds the law that
  a hue is never introduced for variety.
- **Interactivity.** What the surface is allowed to require — script, client
  state, a network round trip — and which layer decides when that changes. A
  default stated here keeps a single feature from quietly raising the floor for
  everything.
- **Motion.** Duration, easing and what respects `prefers-reduced-motion`. Write
  it the first time a change proposes an animation.

## Accessibility — the floor

State the standard this repo holds itself to and where it is checked. The
per-change obligations — keyboard, focus, contrast, colour never the only
carrier of meaning, every state designed and not just the happy one — belong to
the rule that loads while you work on a screen, not to this file, which says
what the floor *is* rather than repeating how to meet it.

What does belong here is anything specific to this surface: which text roles
were chosen against which background roles, whether any image carries meaning
and what it needs to ship (`role="img"` and a descriptive label), and any
exception with its reason.
