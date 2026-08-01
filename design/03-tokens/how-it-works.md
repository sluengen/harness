---
layer: 03-tokens
kind: how-to
status: active
owner: sluengen
last_updated: 2026-07-29
---

# How tokens flow into `docs/index.html`

> One JSON. One narrow, marker-bounded write into the page's `:root` block.
> No runtime re-skin, no per-tenant anything — the harness's page has exactly
> one skin.

This describes the seam #242 builds. It does not exist yet as of #241 — this
issue stands up `tokens.json` as the source of truth; #242 is the generator
that makes the page consume it.

```
 ┌──────────────────┐   scripts/build_design_tokens.py   ┌───────────────────────┐
 │ 03-tokens/        │ ─────────────────────────────────► │ docs/index.html      │
 │ tokens.json       │      (stdlib-only Python, #242)     │ :root{ ... } — a     │
 │ (source of truth) │                                     │ marker-bounded region │
 └──────────────────┘                                     └───────────────────────┘
```

## Why a narrow, marker-bounded write

`docs/index.html` is 662 lines of hand-tuned CSS, SVG, and prose, pinned by
seven unit tests (`tests/unit/test_landing_page.py`). The generator's write
must be scoped to exactly the `:root{...}` block — a generator that reflows
anything outside its markers would fight every future hand edit to the rest
of the page. ADR 0004 chose a lean drift-checked guard over a full generator
for the page's narrative content for the same reason; #243 narrows that ADR's
scope to record that the token block is the one part of the page that *is*
now generated.

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
   `tokens.json` (#243) — the same discipline
   `scripts/check_landing_page_guidance.py` already applies to the page's
   guidance references.
4. The generated region is never hand-edited; an edit there is lost the next
   build.
