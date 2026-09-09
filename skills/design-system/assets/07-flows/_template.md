---
layer: 07-flows
kind: template
status: scaffold
owner: sluengen
last_updated: 2026-07-29
---

# Flow template

Copy this file when authoring a flow. A flow documents a **multi-screen
sequence** that carries a user through one goal, composed of archetypes
(layer 06) in order, with the transitions and completion state between them.

Front matter: `layer: 07-flows`, `kind: flow`, `status:` one of `designed`
(authored, no consumer yet), `active` (the sequence exists and is live), or
`superseded`.

---

```markdown
---
layer: 07-flows
kind: flow
status: designed | active
owner: <who answers for it>
last_updated: <ISO date>
---

# <Name> flow

> One sentence: the goal this sequence carries a user through.

## Sequence

The archetypes (layer 06) this flow sequences, in order, and the decision
point or transition between each.

## Done means

What state marks the flow complete.

## Verification checklist

- [ ] Checkable at review time, in the order a reviewer would work through
      them.
```
