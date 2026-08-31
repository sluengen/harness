---
layer: 03-tokens
kind: how-to
status: active
owner: sluengen
last_updated: 2026-09-01
---

# How tokens flow into `docs/index.html`

> One JSON. One narrow, marker-bounded write into the page's `:root` block.
> No runtime re-skin, no per-tenant anything — the harness's page has exactly
> one skin.

This describes the generator that writes the token source into the page.

```
 ┌──────────────────┐   scripts/build_design_tokens.py   ┌───────────────────────┐
 │ 03-tokens/        │ ─────────────────────────────────► │ docs/index.html      │
 │ tokens.json       │      (stdlib-only Python, #242)     │ :root{ ... } — a     │
 │ (source of truth) │                                     │ marker-bounded region │
 └──────────────────┘                                     └───────────────────────┘
```

## Why a narrow, marker-bounded write

`docs/index.html` combines hand-authored CSS, SVG, and prose. The token
generator owns only the `:root{...}` region between its markers; it must not
reflow any other part of the page. `tests/unit/test_build_design_tokens.py`
and the verification gate check that generated region. The inventory test
checks the plugin surface, while narrative copy remains direct-review work.

## The two tiers the build emits

Only **semantic** tokens become `:root` custom properties — primitives
resolve to literals inside them and stay out of the page:

```css
:root {
  --color-loop-build-accent: #0f9d6e;   /* primitive ref -> literal */
  --shadow-elevation-default: 0 1px 2px rgba(16,24,64,.05), 0 10px 30px rgba(16,24,64,.06);
}
```

There is no component tier to emit in this capture — `tokens.json`'s
`component` namespace is empty (see [`README.md`](README.md)).

## The contract #242 and #243 hold to

1. `tokens.json` is authored by hand; it is the only file a person edits.
2. `docs/index.html`'s `:root` block becomes a **generated region**, written
   only inside explicit start/end markers.
3. `scripts/verify.sh` drift-checks the generated region against
   `tokens.json`.
4. The generated region is never hand-edited; an edit there is lost the next
   build.
