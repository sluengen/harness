---
kind: bug              # bug | tweak
area: {surface/feature}
---

# {title}

The shared capture form for `/bug` and `/tweak` — an **adjustment to as-built
functionality, surfaced by actual use**. It is a **capture-optimized change
spec**: same destination as `templates/change.md` (the tracker issue body),
pre-framed for the moment of noticing rather than the moment of building.
Filled by whoever noticed, before a builder is assigned; `/start` extends it
with Grounding and Design at build time. It is not a competing artifact to
`templates/change.md` — an on-ramp to it.

---

## As-built (observed)

What actually happens today, as observed in use.

- **`kind: bug`** — the wrong behaviour, plus a repro: the steps or input that
  trigger it.
- **`kind: tweak`** — the current, correct behaviour that is being upgraded —
  no repro needed, since nothing is broken.

## Desired

What should happen instead. One or two sentences — the direction, not the
implementation. The full **Design** (data model / interface / scenarios) is
filled at build time; capture states the outcome, not the how.

## From actual use

The situation that surfaced this — what you were doing, what you expected,
what tipped you off. This is the context a builder starting cold would
otherwise have to reconstruct.

## Acceptance criteria

Specific, testable outcomes. Each must be verifiable by a test (not "feels
right").
- AC-1: {…}
- AC-2: {…}

---

**Escape hatch (`kind: tweak` only).** If, while filling this in, the tweak
turns out to carry a real decision (more than one reasonable direction) or
would spawn more than one change, it is not a tweak — stop and use `/propose`
instead. A `kind: bug` has no escape hatch: the as-built behaviour already
contradicts the intent, so there is nothing to decide.
