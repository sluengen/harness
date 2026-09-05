---
paths:
  - "<design-directory>/**"
  - "<ui-source-glob>/**"
description: What binds while building or changing a user-facing surface in this repo.
---

# Building a user-facing surface here

Loaded whenever a file under this repo's design directory or its UI source paths is
opened. `/harness:init` seeded it from the plugin when `layers.design_system` was
turned on, filling the globs above from `harness.yaml`. **It is yours now** —
`--refresh` never overwrites it, so edit it to match how this repo actually works,
and delete anything below that does not.

*Why a rule and not a skill: guidance that has to be triggered by a description
fires when something remembers to trigger it; a rule attached to a path is simply
present every time a matching file is opened. Measured at 53% against 100%
(research 01 §10). This file replaced the `design-system` and `ux-design` skills
at #547 for that reason.*

## The two-stage lookup, before any visual change

1. **Find the principle.** What does this repo's design system say should be true
   here — its brand and UX principles, at the path `harness.yaml` names?
2. **Find the materialization.** Where is that principle expressed in code: the
   token definitions, the primitive components? Use those.

If you are about to write a visual value by hand, stop and do this lookup first.

**No system yet is a gap to fill, not a licence to hardcode.** Where
`paths.design_system` is unset or names a location with nothing at it, stand one up
from the plugin's `templates/design-system.md` scaffold and set the path. An
external package you have yet to install is not a missing system.

## Tokens and primitives

- **Named tokens, never raw values,** wherever a token exists — colour, type,
  spacing, radii. A hardcoded hex or a one-off pixel value where a token is defined
  drifts the moment the token changes.
- **Use the primitive if one exists** (button, card, field, badge, empty state).
  Reimplementing its markup inline forks the design, and the bespoke copy decays.
  Build a new primitive only when a pattern appears three or more times without one.
- **Composition chrome a value scan cannot see.** A sheet header, a card shell, a
  list row is a composition of several token rules: every value in it is already a
  token, so a raw-value scan sees nothing wrong even when the same composition is
  reimplemented across many files. Before adding chrome composed of three or more
  token rules, grep for a primitive; if that composition already appears in three or
  more files, extract one.
- **Extract, then finish adopting.** Extracting a primitive is not done at the first
  callsite: enumerate every inline copy in the ticket's acceptance criteria and
  migrate them, or file a follow-up listing the un-migrated ones by `file:line`.
- **Materialise a primitive only when a consumer adopts it in the same change.** A
  primitive with zero callsites is dead code the value scan cannot see.
- **Adoption and conformance are different questions.** Adoption — does this screen
  use the right primitive and tokens — is your job on every change here.
  Conformance — does the primitive itself render to spec — is a question for changes
  to the primitive.
- **Changing a token or a primitive ripples.** Check the principle it serves,
  consider every consumer, and make a relaxation of a stated principle an explicit
  principle update with a rationale rather than a silent edit.

## Every state, not just the happy one

A screen designed only in its success state hides the work. Before handoff, the
surface answers all of these:

- [ ] **Empty** — useful, not "no data found"; it is often the first thing a new
      user sees.
- [ ] **Loading** — a skeleton for content, inline feedback for an action, never a
      blocking spinner over work the user is mid-way through.
- [ ] **Error** — specific, helpful, and with a clear path back to success.
- [ ] **Edge** — 0 items, 1 item, many items, long names, missing data.

## Accessibility

- [ ] Works with the keyboard alone, and focus is always visible.
- [ ] Interactive elements are obviously interactive, and every action gives visible
      feedback.
- [ ] Hover is never the only way to reveal critical functionality.
- [ ] Contrast meets the repo's stated standard; colour is never the only carrier of
      meaning.
- [ ] It works one-handed on mobile rather than merely fitting.
- [ ] Copy is clear, specific, and actionable (`authoring` → *Prose*).

## Visual evidence, when the diff touches a user-facing surface

Not a judgment call about size or risk: any diff touching a screen, route, view,
template, or the styles behind one renders evidence before handoff.

**Render** the changed surface with realistic **seeded** state — synthetic
throughout, never production data — at the repo's reference widths, at least one
mid-width, and both sides of every breakpoint the change touches.

**Capture** at a fixed viewport, in **viewport-height slices** scrolled one viewport
at a time and numbered in scroll order. Never a full-page capture at any width, and
never a capture over 2000 px tall: a taller one reaches the reviewer downscaled past
legibility (measured — 16 px body text arrived at 7 of 8 characters from a 5726 px
capture).

**Store** captures and their manifest in `.evidence/<TICKET-ID>/` at the worktree
root. That path is git-ignored, so evidence never reaches the committed tree through
`git add -A`; if this repo's `.gitignore` does not ignore `.evidence/`, add the line
before capturing. Name captures `<page>-<state>-<width>w-<slice>.png` and the
manifest `manifest.md`.

**Bound it:** at most 12 captures per review. Narrow the set to the states carrying
the change, and never shrink an image to fit — that reintroduces the failure the
slice rule prevents.

**Judge** each capture against the reference or the applicable archetype, and inspect
the implementation too: screenshots do not replace code review. Fix, re-render, and
retain only the final evidence. Revert seeded data and capture-only code before
verification.
