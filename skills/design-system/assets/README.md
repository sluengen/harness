---
layer: root
kind: readme
status: active
last_updated: 2026-09-18
---

# Design system

A layered design system for this repo's user-facing surface. The structure
follows `templates/design-system.md` — a one-way dependency stack, a three-tier
token model, and a drift check that keeps the generated region of a page honest
against its token source.

This tree arrived from hydration, which copies it out of the `design-system`
skill once. **It is yours from that moment**: no later hydration rewrites a file
here, so edit freely and delete what you have no use for.

```
┌─ 00 · Brand        ─ who the product is, and what this system governs
├─ 01 · Voice        ─ how it sounds — copy principles, tone, register
├─ 02 · Principles   ─ interaction, density and accessibility laws
├─ 03 · Tokens       ─ the atomic named decisions (the source of truth)
├─ 04 · Primitives   ─ single-responsibility elements
├─ 05 · Patterns     ─ reusable compositions of primitives
├─ 06 · Archetypes   ─ page-level chrome contracts
└─ 07 · Flows        ─ multi-screen sequences
```

A layer may consume the layers above it; **nothing reaches downward**. A token
that references a component, or a primitive that defines its own page chrome, is
in the wrong layer.

## Three rules

1. **A layer never reaches downward.** If you find a downward dependency, the
   abstraction lives in the wrong layer — move it up.

2. **Nothing is hardcoded.** The source of truth is
   [`03-tokens/tokens.json`](03-tokens/tokens.json). Consuming code binds to
   semantic (or component) tokens only, never a raw hex or pixel value. A token
   builder resolves that source into a page's generated region;
   [`03-tokens/how-it-works.md`](03-tokens/how-it-works.md) describes the
   mechanism, and the reference implementation ships with the `design-system`
   skill and is copied **on request** rather than by default, so a repo that
   already builds tokens keeps its own.

3. **Chrome belongs to the archetype, never the screen.** A page's shell, its
   breakpoints and its scroll behaviour are the archetype's contract; a screen
   fills that shell rather than redefining it.

## Filling it in

Tiers **00**–**03** are where a new system earns its keep, and they are worth
writing before any component work: who the product is (00), how it reads (01),
the interaction and accessibility laws that constrain every screen (02), and the
palette, type and spacing decisions everything else binds to (03).

Tiers **04**–**07** ship as scaffolds. Each states its purpose and why it is
empty rather than being omitted — a tier fills in when its precondition arrives
(a real component boundary, a second page, a multi-screen sequence), and an empty
tier that says so is worth more than a missing one. Each carries a
`_template.md` for its first real entry to copy.

**The starting token values are a placeholder palette, not a recommendation.**
They resolve, and they demonstrate the three tiers; they are not your brand.
Replace them in `03-tokens/tokens.json` and rebuild.
