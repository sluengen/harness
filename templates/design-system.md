# Design-system scaffold (reference contract)

The contract for **standing up** a layered design system, not a copy of one.
Its counterpart is `skills/design-system/SKILL.md` — the discipline for *using*
a system once it exists, routing to `CONTEXT.md` `paths.design_system` for
where the result lives. This doc is what goes at that path when nothing does
yet.

**Precondition.** This file installs into every consuming repo regardless of
layer setting — install-time layer gating is not built. It is inert unless your
repo's `layers.design_system` is on, or you are turning it on now. If the layer
is off, skip this file.

## The eight layers

A layer may consume lower-numbered layers only; nothing reaches upward. The
zero-padded numeric prefix *is* the dependency order — that is the whole point
of encoding it in the directory name.

| Layer | Answers |
|---|---|
| `00-brand` | Who the product is, what it stands for |
| `01-voice` | How it sounds — copy principles, tone |
| `02-principles` | Interaction, motion, density, accessibility laws |
| `03-tokens` | The atomic named decisions — colour, space, type (source of truth) |
| `04-primitives` | Single-responsibility UI elements (button, field, badge) |
| `05-patterns` | Reusable compositions of primitives |
| `06-archetypes` | Page-level chrome contracts |
| `07-flows` | Multi-screen sequences for a user goal |

## The one-way dependency stack

A layer may consume the layers above it in this table; **nothing reaches
downward**. A token that references a component, or a primitive that defines
its own page chrome, is in the wrong layer — that is the diagnostic, not a
style preference.

## The three rules

1. **A layer never reaches downward.** If you find a downward dependency, the
   abstraction lives in the wrong layer. Move it up.
2. **Nothing is hardcoded.** The source of truth is one `tokens.json`.
   Consuming code binds to **semantic** (or component) tokens only, never to a
   raw hex or pixel value. This is *enforced*, not asked for — a lint fails
   your repo's verification gate on any raw colour or size literal in scanned
   code.
3. **Chrome belongs to the archetype, never the screen.** Status bar, top bar,
   title, sub-nav, safe areas — these are an archetype's job. A screen that
   renders its own chrome is a bug, not a shortcut.

## The frontmatter contract

Every entry file in the tree carries five fields. This is what makes the tree
agent-readable — an agent doing the two-stage lookup (`skills/design-system`:
find the principle, then find its materialization) reads frontmatter, not
filenames. It is not decoration.

| Field | Meaning |
|---|---|
| `layer` | the owning layer id — matches the directory the file sits in |
| `kind` | what the entry is (token set, primitive, pattern, archetype, flow…) |
| `status` | `scaffold` \| `draft` \| `stable` (or your repo's equivalent) |
| `owner` | who answers for it |
| `last_updated` | ISO date |

Each composable layer carries a `_template.md` so a new entry inherits the
contract instead of re-deriving it.

## The three token tiers, and the naming scheme

| Tier | Role | Consumed by app code? |
|---|---|---|
| `primitive` | raw ingredients — a full hue ramp, a spacing scale | No — resolved into semantic values only |
| `semantic` | roles — surface, text, border, danger | Yes |
| `component` | component-scoped narrowing of a semantic value | Yes |

Every semantic token resolves to a primitive. A minimal fragment showing the
shape (not a starter palette):

```jsonc
{
  "color": {
    "primitive": { "blue": { "600": { "value": "#2563eb" } } },
    "semantic": {
      "accent": { "default": { "value": "{color.primitive.blue.600}" } }
    }
  },
  "component": {
    "button": {
      "background": { "default": { "value": "{color.semantic.accent.default}" } }
    }
  }
}
```

**Naming rules** (the invariant; the exact scale is your repo's call):

1. Lowercase, dot-delimited.
2. Singular role names — `space`, not `spaces`; `border`, not `borders`.
3. State and variant trail the role — `accent.hover`, never `hover.accent`.
4. Numbers count up with weight or step — a higher number is a stronger or
   larger value.
5. No non-standard abbreviation — `background`, not `bg`.

## Output discipline

One `tokens.json` per system, as the single source of truth. Everything a
build emits from it (a typed module, a stylesheet, flat JSON) is a **generated
output**: committed to the repo *and* drift-checked in your verification gate
so it can never diverge from its source silently, and never hand-edited — an
edit to a generated file is lost the next build and hides the real change.
`templates/size-guard.md` is the precedent for a small, distributed check
your repo adopts into its own suite; the drift check here follows the same
shape.

## The stack seam — the adopting repo's job

Everything above is the contract. What turns `tokens.json` into something your
application actually consumes — the **stack seam** — is not: it is specific to
your stack, and this doc does not choose it for you. The seam must satisfy the
same contract regardless of shape: semantic tokens only in consuming code,
generated output never hand-edited, and a lint that fails your verification
gate on a raw colour or size literal.

Two worked shapes, so you can recognise which one your stack resembles:

- **Build-time, typed.** A mobile app builds `tokens.json` through a token
  build tool into a typed TypeScript module, `as const`, imported directly —
  no runtime resolution, one value baked in per build.
- **Runtime, CSS custom properties.** A multi-tenant web application emits CSS
  custom properties instead, because it re-skins per tenant from a branding
  resolver at request time rather than per build — the same bundle renders a
  different accent with no rebuild.

If your repo has no build tooling at all, a conforming seam can still be a
hand-authored generated file plus a drift check that fails if it stops
matching `tokens.json` — the contract does not mandate a package or a network
fetch.

## Stand it up

Bootstrap in this order, so each layer has something real to reference before
the next asks for it:

1. **`00-brand`** — who you are, in a sentence a designer or an agent can act
   on.
2. **`01-voice`** — how the product reads: labels, errors, empty states.
3. **`02-principles`** — the interaction and accessibility laws you actually
   enforce today, not an aspirational list.
4. **`03-tokens`** — `tokens.json`, plus a naming doc.
5. **The first primitive** — one real component, built against the tokens
   above, as the worked example the rest of `04-primitives` follows.

Layers you have not filled in yet are not omitted — they are **declared
scaffolds**: a `README.md` with `status: scaffold` and a one-line note on what
belongs there. An absent layer reads as *not applicable*; a scaffold reads as
*not yet*. Only the second is honest when the layer is coming.

`paths.design_system` in `CONTEXT.md` may point at an in-tree directory or an
external package/repo — this contract describes a tree relative to that path
and never assumes a repo-root `design/`.
