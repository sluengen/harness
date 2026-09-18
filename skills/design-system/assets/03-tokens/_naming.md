---
layer: 03-tokens
kind: naming
status: active
last_updated: 2026-09-01
---

# Token naming

> Semantic paths name token roles; the generator maps them to the page's
> stable CSS custom-property names.

## Path in `tokens.json`

`{namespace}.{tier}.{role…}` — the tier is a literal segment in the tree:

```
color.primitive.build.base
color.semantic.loop.build.accent
shadow.semantic.elevation.default
component.<domain>.<role>...          ← component tier is its own top-level namespace
```

- `namespace` — `color` | `shadow`, or the top-level `component`.
- `tier` — `primitive` | `semantic` (component tokens live under `component.*`
  directly, so the tier is implied).
- `role…` — what the token is for, one or more segments (`loop.build.accent`,
  `elevation.default`).

## CSS custom-property names in the page

The builder maps each emitted semantic token to the custom property the page
already uses; **it does not derive the property name from the token path.** That
explicit map is what lets a design system land on a page whose CSS variables
were named before it existed, without renaming every consumer:

| Token path | CSS variable |
|---|---|
| `color.semantic.loop.build.accent` | `--build` |
| `color.semantic.surface.card` | `--card` |
| `shadow.semantic.elevation.default` | `--shadow` |

Those rows are the shipped example's map, and rewriting it for your page's
variables is one of the two edits the builder's own guidance calls for.

Primitives (`*.primitive.*`) are not emitted as variables — they resolve to
literals inside the semantic values that reference them. Keeping the map
explicit also keeps the write confined to the marked `:root` region.

## Rules

1. **Lowercase, dot-delimited in JSON; dash-delimited as a CSS variable.**
2. **Singular roles.** `border`, not `borders`; `loop`, not `loops`.
3. **State and variant trail the role.** `loop.build.accent`, never
   `accent.build.loop`.
4. **Numbers count up with weight or step** where a scale exists. Named steps
   (`base`/`soft`/`ink`) and numbered ones are both fine; pick one per ramp and
   do not mix them within it.
5. **No abbreviations unless industry-standard.** `background`, not `bg`.
