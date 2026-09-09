---
layer: 05-patterns
kind: template
status: scaffold
owner: sluengen
last_updated: 2026-07-29
---

# Pattern template

Copy this file when authoring a pattern. A pattern documents a **reusable
composition of primitives** (layer 04) that solves one recurring UI problem.
It introduces no new tokens and owns no page chrome — that is what an
archetype (layer 06) is for.

Front matter: `layer: 05-patterns`, `kind: pattern`, `status:` one of
`designed` (authored, no consumer yet), `active` (something on the page
adopts it), or `superseded`.

---

```markdown
---
layer: 05-patterns
kind: pattern
status: designed | active
owner: <who answers for it>
last_updated: <ISO date>
---

# <Name> pattern

> One sentence: the recurring problem this composes primitives to solve.

## Composes

Which primitives (layer 04) this pattern builds from, and what each
contributes.

## Behaviour

The states and transitions a reviewer needs to hold a consumer against.

## Verification checklist

- [ ] Checkable at review time, in the order a reviewer would work through
      them.
```
