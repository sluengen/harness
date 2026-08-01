---
layer: 04-primitives
kind: template
status: scaffold
owner: sluengen
last_updated: 2026-07-29
---

# Primitive template

Copy this file when authoring a primitive. A primitive is a
single-responsibility UI element — it binds only to **semantic** or
**component** tokens (layer 03), owns no page layout, and composes into
patterns (layer 05).

Front matter: `layer: 04-primitives`, `kind: primitive`, `status:` one of
`designed` (authored, no consumer yet), `active` (something on the page
consumes it), or `superseded`.

---

```markdown
---
layer: 04-primitives
kind: primitive
status: designed | active
owner: <who answers for it>
last_updated: <ISO date>
---

# <Name> primitive

> One sentence: the single thing this element does.

## Binds to

Which semantic/component tokens (layer 03) this primitive uses, and for
what.

## States

Every visual state a reviewer needs to hold a consumer against (default,
hover, focus, disabled, …), and what token changes between them.

## Verification checklist

- [ ] Checkable at review time, in the order a reviewer would work through
      them.
- [ ] No raw colour or size literal — every value traces to a token.
```
