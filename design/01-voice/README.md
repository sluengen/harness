---
layer: 01-voice
kind: readme
status: active
owner: sluengen
last_updated: 2026-07-29
---

# 01 · Voice

How the page reads: headings, labels, and the descriptions of what each loop
and verb does. Captured from the page's existing prose (issue #241), not
invented.

**Register: plain, technical, unhurried.** The page describes an operating
model to an audience of engineers and agents — it does not sell. Sentences
state a mechanism and its cadence, not a benefit. Compare the loop cards'
own copy:

> "A scheduled Claude routine that autonomously picks which task to work on."
> "The product owner (human) working with Claude."
> "Human-run, on no fixed period — assisted by agent research."

Each is a **trigger + driver** stated as fact, in the same grammatical shape
across all four loops — no loop gets an adjective the others don't.

## Principles

- **Name the mechanism, not the benefit.** "Ring size = cycle length" states
  what the diagram encodes; it does not say the diagram is "intuitive" or
  "powerful". A claim about how good something is, rather than what it does,
  is a voice violation.
- **Every section heading is a question or a plain label**, in the small-caps
  eyebrow style already established (`How we build · operating model`, `How
  the loops are triggered`) — never a slogan.
- **Command names and syntax are never paraphrased.** `/build`, `/propose`,
  `--refresh` appear verbatim, in `<code>`, exactly as a user would type them —
  this is also what lets
  `tests/unit/test_landing_page_inventory.py::test_the_page_inventory_matches_the_tree`
  hold the page to the surface the tree actually carries.
- **Status is stated at the cadence and mechanism level**, e.g. "Automated ·
  the verify gate is the tool inside this loop", "Human-driven — the rudder
  for everything inside" — one line, no elaboration, always ending on who or
  what drives the loop.
- **Bold marks the one word that carries the sentence's point**, not for
  emphasis generally — "Intent flows inward" is bolded on *inward*, because
  the direction is the fact being stated.

Voice is distinct from **tokens** (layer 03): tokens govern what the page
*looks* like, voice governs what it *says*. A copy change never needs a
token change, and vice versa.

## Terms that are fixed

These names are load-bearing (guidance ids the page cross-references via
`data-guidance`) and must not be paraphrased: `Build`, `Product`, `Quality`,
`Strategy` (the four loops); `harness`, `build`, `start`, `propose`,
`assess`, `researcher` (verbs/commands/agents named on the page). Renaming
one on the page without a matching `registry.yaml` id is exactly the drift
`test_named_guidance_resolves_in_registry` exists to catch.
