---
layer: 02-principles
kind: readme
status: active
owner: sluengen
last_updated: 2026-07-29
---

# 02 · Principles

The interaction, motion, density, and accessibility laws the page obeys —
the rules that hold regardless of what changes above them.

**The page must stay self-contained.** No external resource request at
render time — no external stylesheet, script, image, iframe, web font, or a
CSS `url()`/`@import` pointing at a remote host. Navigation links
(`<a href="https://...">`) are fine — a click, not a load-time fetch. This is
the constraint that governs everything else this layer might add: any
pattern, primitive, or archetype proposed for this page must remain
renderable from the single committed HTML file, with nothing fetched. It is
enforced, not just stated —
[`tests/unit/test_landing_page.py::test_no_external_resource_requests`](../../tests/unit/test_landing_page.py)
fails the gate on any violation.

**Density favours a scannable reference over a marketing page.** The page
packs four loop cards, a trigger grid, a spec-flow diagram, verb cards, and a
guidance catalog into one scroll — compact cards with a fixed internal
rhythm (header → detail grid → steps → footer), not generous whitespace
between sections. A new section that needs its own bespoke spacing scale to
"breathe" is a finding; reuse the existing card/section rhythm.

**Colour carries structure, not mood.** Each loop's hue (layer 00) marks
*which loop* a card, diagram ring, or spec stage belongs to — consistently,
never decoratively. A hue introduced for visual variety rather than to mark
a loop membership is out of scope for this layer.

**Every interactive element is a plain link or has no interactivity at
all.** The page has no forms, no client-side state, and no JavaScript —
by design (see layer 00, rule 4). A future addition that requires script to
function is a layer-00 brand decision, not a layer-02 default.

**Accessibility — the floor.**
- Text contrast against its surface is legible at a glance; the ink/muted
  text roles (layer 03) were chosen against the light card/background
  surfaces they pair with.
- Nothing on the page communicates meaning by hue alone — every loop card
  also carries its number, name, and role in text; every status pip
  (`pip--auto`, `pip--human`, …) sits next to a text label, never bare.
- The SVG diagram carries a `role="img"` and a descriptive `aria-label`
  summarising what the rings encode, for a reader who cannot see it.

> Partial. Motion has no tokens and no stated law — the page is currently
> static (no animation, no transition). A law is written here the first time
> a change proposes one, rather than speculatively now.
