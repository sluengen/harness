---
layer: 03-tokens
kind: naming
status: active
owner: sluengen
last_updated: 2026-07-29
---

# Token naming

> One scheme, followed everywhere. Predictable names beat creative names.

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

## CSS custom-property name (for the #242 generator)

The build derives the variable name from the path by **dropping the tier
word** (`primitive` / `semantic`) and joining the rest with dashes.
`component` is kept, since it is the namespace, not a tier word:

| Token path | CSS variable |
|---|---|
| `color.semantic.loop.build.accent` | `--color-loop-build-accent` |
| `color.semantic.surface.card` | `--color-surface-card` |
| `shadow.semantic.elevation.default` | `--shadow-elevation-default` |

Primitives (`*.primitive.*`) are not emitted as variables — they resolve to
literals inside the semantic values that reference them. This is a naming
convention for the generator #242 builds; it is a deliberate rename from the
page's *current* hand-authored variable names (`--build`, `--build-soft`,
`--build-ink`, …), which #242's own change spec settles.

## Rules

1. **Lowercase, dot-delimited in JSON; dash-delimited as a CSS variable.**
2. **Singular roles.** `border`, not `borders`; `loop`, not `loops`.
3. **State and variant trail the role.** `loop.build.accent`, never
   `accent.build.loop`.
4. **Numbers count up with weight or step** where a scale exists. Not
   exercised yet — the current ramps are named steps (`base`/`soft`/`ink`),
   not numbered.
5. **No abbreviations unless industry-standard.** `background`, not `bg`.
