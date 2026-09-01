---
layer: 03-tokens
kind: readme
status: active
owner: sluengen
last_updated: 2026-09-01
---

# 03 · Tokens

The atomic design decisions — colour and elevation — as a single committed
source of truth for `docs/index.html`, the harness's one external-facing
artifact. This is the substantive layer of the system (#241); the page's
`:root` block is what it captures.

## Files

| File | What it is |
|---|---|
| [`tokens.json`](tokens.json) | **The source of truth.** A three-tier tree: primitive → semantic → component. Authored by hand; the only file you edit. |
| [`_naming.md`](_naming.md) | The naming scheme. Predictable names, followed everywhere. |
| [`how-it-works.md`](how-it-works.md) | How a token flows from JSON into the generated `:root` region in `docs/index.html`. |

[`../../scripts/build_design_tokens.py`](../../scripts/build_design_tokens.py)
resolves `tokens.json` and writes only the marker-bounded generated region in
[`../../docs/index.html`](../../docs/index.html)'s `:root` block. The rest of
the page remains hand-authored. Its write and drift-check behaviour is covered
by [`../../tests/unit/test_build_design_tokens.py`](../../tests/unit/test_build_design_tokens.py).

## The three tiers

- **primitive** — a raw value named by what it *is*: `color.primitive.build.base`
  is `#0f9d6e`. Primitives are the palette; nothing consumes them directly, and
  they are not meant to become public CSS variables on their own.
- **semantic** — an alias named by what a value is *for* — the contract:
  `color.semantic.loop.build.accent` → `{color.primitive.build.base}`. This is
  what gives `#0f9d6e` a *meaning* (the Build loop's accent) rather than just a
  value.
- **component** — an optional per-component narrowing of a semantic value.
  Empty in this capture: every literal the page renders today resolves at
  primitive/semantic, with nothing genuinely single-use enough to warrant its
  own component-tier entry.

## Capture, not redesign

Every emitted token value in `tokens.json` is byte-identical to what
[`../../docs/index.html`](../../docs/index.html) renders through its generated
`:root` region. `tests/unit/test_build_design_tokens.py` verifies the generated
region is derived from the token source, is confined to its markers, and fails
the drift check when either source or region changes without regeneration.

## What's next

[`how-it-works.md`](how-it-works.md) explains the generated region and the
drift check that `scripts/verify.sh` runs against it.
