---
layer: 07-flows
kind: readme
status: scaffold
last_updated: 2026-07-29
---

# 07 · Flows

Multi-screen sequences that carry a user through a goal — the top of the
stack, referencing everything below and referenced by nothing.

A flow documents what carries a user *between* screens: the entry points, the
decision at each step, what happens on failure, and where the sequence can be
resumed. Sign-up, checkout and a multi-step form are the usual first entries.

**Write the first one when there is a sequence to write down** — more than one
screen, and a goal that spans them. On a single screen a "flow" degenerates into
a description of reading order, which layer 00 and layer 02 already carry; the
entry would restate them and then go stale independently.

> Scaffold. Flows describe transitions *between* screens. This layer fills in
> when this repo's surface has a sequence that connects two.
