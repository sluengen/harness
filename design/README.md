---
layer: root
kind: readme
status: active
owner: sluengen
last_updated: 2026-07-29
---

# harness design system

A layered design system for the harness's **one external-facing artifact**:
[`docs/index.html`](../docs/index.html), the landing page explaining the
operating model, the harness's own verbs, and the guidance catalog. The
structure follows `templates/design-system.md` (#239) — a one-way dependency
stack, a three-tier token model, and (once #243 lands) a lint that forbids
raw values in the generated region.

The harness has no product UI and no end-users — it is infrastructure other
repos self-host. This system exists to eat its own contract: distributing
`templates/design-system.md` without running it here would leave the
contract aspirational (#241).

```
┌─ 00 · Brand        ─ who the harness is, and what the page is for
├─ 01 · Voice        ─ how the page reads (headings, loop/verb descriptions)
├─ 02 · Principles   ─ the self-contained-page constraint, density, a11y laws
├─ 03 · Tokens       ─ the atomic decisions — colour, elevation (the source of truth)
├─ 04 · Primitives   ─ single-responsibility UI elements (scaffold — no consumer yet)
├─ 05 · Patterns     ─ reusable compositions of primitives (scaffold)
├─ 06 · Archetypes   ─ page-level chrome contracts (scaffold — only one page exists)
└─ 07 · Flows        ─ multi-screen sequences (scaffold — only one screen exists)
```

A layer may consume the layers above it; **nothing reaches downward**. A
token that references a component, or a primitive that defines its own page
chrome, is in the wrong layer.

## Three rules

1. **A layer never reaches downward.** If you find a downward dependency,
   the abstraction lives in the wrong layer — move it up.

2. **Nothing is hardcoded.** The source of truth is
   [`03-tokens/tokens.json`](03-tokens/tokens.json). Once the generator
   lands (#242), consuming code — the generated region of
   `docs/index.html` — binds to semantic (or component) tokens only, never
   a raw hex or pixel value; #243 wires a drift check into
   `scripts/verify.sh` to enforce it.

3. **Chrome belongs to the archetype, never the screen.** Not yet
   exercised — the harness has one page, so layer 06 is a scaffold. The rule
   stands for the day a second page exists.

## Status

Layers **00-brand**, **01-voice**, **02-principles** and **03-tokens** are
**substantive** as of #241: the harness's positioning and the rules that
constrain the page (00), its existing register captured from the page's own
prose (01), the self-contained-page and density/accessibility laws (02), and
`tokens.json` capturing every colour and elevation literal the page renders
today, byte-identical (03).

Layers **04-primitives**, **05-patterns**, **06-archetypes** and
**07-flows** are declared **scaffolds** — each states its purpose and why it
is empty rather than omitted. The harness's public surface is one
hand-authored HTML page with no component build step, so there are no
primitives to extract, no patterns to compose, only one page (so no second
archetype to contrast it against), and no multi-screen sequence (so no
flow). Each would fill in only if that precondition changes — a real
component boundary, or a second page.

**No visual change shipped with #241.** `docs/index.html` is byte-unchanged;
`tokens.json`'s values were captured from what the page already renders. The
generator that makes the page consume `tokens.json` — and the first (and
so far only) real stack seam — is [`03-tokens/how-it-works.md`](03-tokens/how-it-works.md),
built in #242; the gate wiring and the ADR 0004 amendment that narrows its
scope to the token block are #243.
