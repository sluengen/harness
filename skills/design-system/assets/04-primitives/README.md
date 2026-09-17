---
layer: 04-primitives
kind: readme
status: scaffold
last_updated: 2026-07-29
---

# 04 · Primitives

Single-responsibility UI elements — a card, a pill, a status pip — that bind
only to semantic or component tokens (layer 03) and own no page layout.

**Extract one when the same shape appears three or more times** and there is a
component boundary to extract it into. Before that, a "primitive" is a repeated
CSS class rather than an independently testable unit, and documenting it here
produces an entry that describes markup instead of governing it.

**Materialise a primitive only when a consumer adopts it in the same change.**
One with no callsites is dead code that a raw-value scan cannot see, because
every value in it is already a token.

> Scaffold. The first extracted primitive lands here as the worked example the
> rest of the layer follows; `_template.md` is what it copies.
