---
layer: 03-tokens
kind: readme
status: active
last_updated: 2026-09-01
---

# 03 · Tokens

The atomic design decisions — colour, elevation, and whatever else this
product names — as a single committed source of truth. This is the layer every
other one binds to: a value that exists here has a name, and a value that does
not is a hardcode waiting to drift.

## Files

| File | What it is |
|---|---|
| [`tokens.json`](tokens.json) | **The source of truth.** A three-tier tree: primitive → semantic → component. Authored by hand; the only file you edit. |
| [`_naming.md`](_naming.md) | The naming scheme. Predictable names, followed everywhere. |
| [`how-it-works.md`](how-it-works.md) | How a token flows from JSON into the generated `:root` region of a page. |

A token builder resolves `tokens.json` and writes **only** a marker-bounded
region inside the consuming page's `:root` block; the rest of the page stays
hand-authored. The reference implementation ships with the `design-system`
skill and is copied on request — see [`how-it-works.md`](how-it-works.md) for
the mechanism, which holds whether or not that builder is the one you use.

## The three tiers

- **primitive** — a raw value named by what it *is*: `color.primitive.build.base`
  is `#0f9d6e`. Primitives are the palette; nothing consumes them directly, and
  they are not meant to become public CSS variables on their own.
- **semantic** — an alias named by what a value is *for* — the contract:
  `color.semantic.loop.build.accent` → `{color.primitive.build.base}`. This is
  what gives `#0f9d6e` a *meaning* (the Build loop's accent) rather than just a
  value.
- **component** — an optional per-component narrowing of a semantic value.
  Start empty. A component entry earns its place when one component needs a
  value genuinely single-use; inventing narrowings up front gives every
  component a private palette and defeats the semantic tier.

## Starting values

The values shipped here are a **placeholder palette**: they resolve, and they
demonstrate the three tiers working together. They are not a recommendation and
they are not your brand. Replace them, keep the structure, and rebuild.

## Wire up the drift check

The point of a single source is that nothing may disagree with it. Add the
builder's check mode to this repo's verification gate, so a generated region
edited by hand — or a source edited without a rebuild — fails the gate rather
than drifting quietly. [`how-it-works.md`](how-it-works.md) describes the
contract that check enforces.
