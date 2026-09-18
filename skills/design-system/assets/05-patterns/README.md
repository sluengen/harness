---
layer: 05-patterns
kind: readme
status: scaffold
last_updated: 2026-07-29
---

# 05 · Patterns

Reusable compositions of primitives (layer 04) that solve one recurring UI
problem — a card grid, a labelled-value list, a step sequence.

A pattern is where composition chrome gets a name — a card shell, a list row, a
sheet header. Those are the shapes a raw-value scan is blind to: every value in
them is already a token, so the same composition can be reimplemented across
many files with nothing flagging it. Naming it here is the only thing that
catches that.

**Write one once layer 04 has primitives to compose.** A pattern with no
primitives beneath it is prose describing CSS that already exists, which is not
what this layer is for.

> Scaffold. Fills in after layer 04; `_template.md` is what the first entry
> copies.
