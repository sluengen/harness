---
layer: 06-archetypes
kind: template
status: scaffold
owner: sluengen
last_updated: 2026-07-29
---

# Archetype template

Copy this file when authoring an archetype. An archetype documents the
**chrome contract** a kind of page owns — the regions it fills and how each
behaves at every supported width. It does not document a specific page's
content; that belongs wherever that page's own record lives.

Front matter: `layer: 06-archetypes`, `kind: archetype`, `status:` one of
`designed` (authored, no consumer yet), `active` (a page adopts it), or
`superseded`.

---

```markdown
---
layer: 06-archetypes
kind: archetype
status: designed | active
owner: <who answers for it>
last_updated: <ISO date>
---

# <Name> archetype

> One sentence: what kind of page this is, and what its one job is.

## Regions

| Region | This archetype puts | Behaviour by width |
|---|---|---|

## Rules

Numbered, checkable statements a reviewer can hold a page against.

## Verification checklist

- [ ] Checkable at review time, in the order a reviewer would work through
      them.
```
