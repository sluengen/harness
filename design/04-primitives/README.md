---
layer: 04-primitives
kind: readme
status: scaffold
owner: sluengen
last_updated: 2026-07-29
---

# 04 · Primitives

Single-responsibility UI elements — a card, a pill, a status pip — that bind
only to semantic or component tokens (layer 03) and own no page layout.

`docs/index.html` already has recurring shapes that *would* become
primitives if this page grew a second screen or a component build step: the
loop card, the pill/status badge, the code chip. None is extracted yet — the
page is a single hand-authored HTML file with no component system, so a
"primitive" today is just a repeated CSS class, not an independently
testable unit.

> Scaffold. There is nothing to specify yet: a primitive with no consumer
> other than the CSS class it already is would be dead code the value scan
> can't see (`skills/design-system`). This layer fills in only if the page
> grows a real component boundary — e.g. a build step that assembles the
> page from fragments — at which point the first extracted primitive lands
> here as the worked example the rest of the layer follows.
