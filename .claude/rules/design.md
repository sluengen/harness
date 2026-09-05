---
paths:
  - "design/**"
  - "docs/**"
description: How the design layer and the landing page relate; loaded when either is opened.
---

# The design layer

Loaded when a file under `design/` or `docs/` is opened.

- `design/03-tokens/tokens.json` is the **source**; the generated `:root` block in
  `docs/index.html` is built from it by `scripts/build_design_tokens.py`, and the gate
  fails on drift. Edit the source, never the generated block.
- A token **value** appears nowhere in `docs/index.html` outside that generated region. A
  hand-copied hex is a second copy that no longer tracks its source (ADR 0004, narrowed).
- `docs/index.html` advertises the plugin surface, and the inventory is compared against
  the tracked tree unit by unit. A unit added or renamed is a page edit in the same change,
  and the printed count on a card is the length of the list beneath it.
- The design layer is on for this repo (`layers.design_system` in `harness.yaml`). Use the
  `design-system` skill for the tokens and primitives, and `ux-design` for a new surface.
