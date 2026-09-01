---
layer: 01-voice
kind: readme
status: active
owner: sluengen
last_updated: 2026-09-01
---

# 01 · Voice

How the page reads: headings, labels, and descriptions of the plugin surface.
Captured from the page's existing prose, not invented.

**Register: plain, technical, unhurried.** The page describes an operating
model to engineers and agents; it does not sell. Sentences state a mechanism,
its evidence, or the role that carries it.

## Principles

- **Name the mechanism, not the benefit.** "Ring size = cycle length" states
  what the diagram encodes; it does not say the diagram is "intuitive" or
  "powerful". A claim about how good something is, rather than what it does,
  is a voice violation.
- **Every section heading is a plain label** in the established small-caps
  eyebrow style, never a slogan.
- **Command names and syntax are never paraphrased.** `/build`, `/propose`,
  `--refresh` appear verbatim, in `<code>`, exactly as a user would type them.
- **Status describes the actual enforcement or advisory role.** Use the page's
  `refuses` and `advises` labels, then name the evidence or condition behind it.
- **Bold marks the one word that carries the sentence's point**, not for
  emphasis generally — "Intent flows inward" is bolded on *inward*, because
  the direction is the fact being stated.

Voice is distinct from **tokens** (layer 03): tokens govern what the page
*looks* like, voice governs what it *says*. A copy change never needs a
token change, and vice versa.

## Terms that are fixed

The page's commands, skills, agents, and hooks are identified by `data-unit`
tags. Their visible names and identifiers come from the tracked tree. The
inventory test verifies that correspondence; reviewers check the surrounding
narrative directly rather than pinning sentence wording.
