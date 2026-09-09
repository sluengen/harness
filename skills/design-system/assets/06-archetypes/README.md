---
layer: 06-archetypes
kind: readme
status: scaffold
owner: sluengen
last_updated: 2026-07-29
---

# 06 · Archetypes

Page-level chrome contracts — the regions a kind of page owns, and how each
behaves across widths.

The harness's public surface is **one page**. There is no second archetype
to contrast it against, and no chrome to extract from a single instance —
`docs/index.html`'s `<div class="wrap">` shell, its single `@media
(max-width:780px)` breakpoint, and its section ordering are the whole of
"page chrome" today, described in prose by layer 00 (brand) and layer 02
(principles: density) rather than as a reusable contract with more than one
consumer.

> Scaffold. An archetype documents a contract *shared by more than one
> page*; the harness has exactly one. This layer fills in only if the
> harness's external surface grows a second page.
