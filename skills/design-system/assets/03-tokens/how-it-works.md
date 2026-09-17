---
layer: 03-tokens
kind: how-to
status: active
last_updated: 2026-09-01
---

# How a token reaches a page

> One JSON. One narrow, marker-bounded write into the page's `:root` block.
> No runtime re-skin and no per-tenant resolution: a system that needs either
> is making a layer-00 decision, not a token one.

This describes the generator that writes the token source into the page. It
ships with the `design-system` skill and is copied out only on request, so this
file describes the mechanism whether or not the builder itself is beside it.

```
 ┌───────────────────┐          the token builder          ┌───────────────────────┐
 │ 03-tokens/        │ ──────────────────────────────────► │ your page             │
 │ tokens.json       │                                     │ :root{ … } — a        │
 │ (source of truth) │                                     │ marker-bounded region │
 └───────────────────┘                                     └───────────────────────┘
```

## Why a narrow, marker-bounded write

A page combines hand-authored CSS, markup and prose. The builder owns only the
`:root{…}` region between its markers and must not reflow any other part of the
page — which is what makes a generated region safe to drop into a file people
still edit by hand. Wire the builder's check mode into this repo's gate so that
region is verified on every change; everything outside it stays review work.

## The semantic tier the build emits

Only **semantic** tokens become `:root` custom properties. The generator
resolves primitive references to literals, then maps each semantic path to the
existing custom property its page consumers use; it does not derive a new CSS
name from the token path. Primitives stay out of the page:

```css
:root {
  --build: #0f9d6e;   /* color.semantic.loop.build.accent */
  --shadow: 0 1px 2px rgba(16,24,64,.05), 0 10px 30px rgba(16,24,64,.06);
}
```

The shipped `tokens.json` has an empty `component` namespace, so nothing is
emitted from that tier until you add one (see [`README.md`](README.md)).

## The contract

1. `tokens.json` is authored by hand; it is the only file a person edits.
2. The consuming page's `:root` block becomes a **generated region**, written
   only inside explicit start/end markers.
3. The repo's verification gate drift-checks the generated region against
   `tokens.json`, so a source edited without a rebuild fails rather than
   drifting quietly.
4. The generated region is never hand-edited; an edit there is lost the next
   build.
