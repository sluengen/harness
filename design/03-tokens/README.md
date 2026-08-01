---
layer: 03-tokens
kind: readme
status: active
owner: sluengen
last_updated: 2026-07-29
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
| [`how-it-works.md`](how-it-works.md) | How a token flows from JSON into `docs/index.html`, and the seam #242 builds to do it. |

There is no `../build/` directory yet — no generator exists (#242). Until then,
`tokens.json` is the source of truth in the sense that its values are
byte-identical to what the page renders, not in the sense that the page is
generated from it.

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

Every token value in `tokens.json` is byte-identical to what
[`../../docs/index.html`](../../docs/index.html) renders today via its
hand-authored `:root` block — pinned by
[`tests/unit/test_design_system_layer.py`](../../tests/unit/test_design_system_layer.py),
which resolves the full tree and compares it against the page's rendered
`:root` values as a set. This issue (#241) only stands up the source of truth;
no visual change ships here, and the page itself is byte-unchanged.

## What's next

[`how-it-works.md`](how-it-works.md) describes the seam #242 builds: a
generator that writes `tokens.json`'s resolved values back into
`docs/index.html`'s `:root` block, inside marker-bounded region, checked for
drift in `scripts/verify.sh` (#243).
