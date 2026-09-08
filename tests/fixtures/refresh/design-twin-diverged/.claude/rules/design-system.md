---
paths:
  - "design/**"
  - "mobile/**"
description: What binds while building or changing a user-facing surface in this repo.
---

# Building a user-facing surface here

Loaded whenever a file under `design/` or `mobile/` is opened. Seeded from the
harness plugin's template when `layers.design_system` was turned on, then edited
down to what is actually true here. **It is repo-owned** — `/harness:init
--refresh` never overwrites it, so correct it when the repo moves.

Two deliberate scope calls. `controlplane/` is **excluded**: it is a local-only
Vite dev tool, not a shipped surface, and the visual-evidence rule below would be
noise there. And the Codex half of this rule is **not** seeded as
`design/AGENTS.md` — that path already holds the design system's own agent
contract, about changing the system rather than consuming it. Read both.

*Why a rule and not a skill: guidance triggered by a description fires when
something remembers to trigger it; a rule attached to a path is present every
time a matching file is opened.*

## The two-stage lookup, before any visual change

1. **Find the principle.** `design/` is a one-way stack, `00-brand` → `07-flows`.
   The principle you need is usually in `02-principles/` (`accessibility.md`,
   `interaction.md`, `ux-principles.md`) or, for a whole screen, in
   `07-flows/<flow>.md`.
2. **Find the materialization.** Tokens are `design/03-tokens/tokens.json`,
   built to `design/build/tokens.{ts,json,css}`. Primitives are
   `mobile/components/primitives/`.

If you are about to write a visual value by hand, stop and do this lookup first.
Before changing anything *inside* `design/`, read `design/AGENTS.md` — it owns
where each kind of change belongs and what the forbidden moves are.

## Tokens and primitives

- **Named tokens, never raw values,** wherever a token exists. This is enforced:
  `design/tooling/lint/no-raw-values.mjs` runs under `npm run tokens:lint` and
  scans integrated app code for raw hex and unit literals.
- **Use the primitive if one exists.** `mobile/components/primitives/` already
  holds `Screen`, `ScreenHeader`, `SheetHeader`, `TabBar`, `SegmentedControl`,
  `TextField`, `ListItemRow`, `SectionBlock`, `Chip`, `Hairline`,
  `LoadErrorStatus`, and the three button tiers. **Headers especially** — do not
  re-roll one inline. Build a new primitive only when a pattern appears three or
  more times without one.
- **Composition chrome a value scan cannot see.** A sheet header, a card shell, a
  list row is a composition of several token rules: every value in it is already
  a token, so `no-raw-values` sees nothing wrong even when the same composition
  is reimplemented across many files. Before adding chrome composed of three or
  more token rules, grep for a primitive; if that composition already appears in
  three or more files, extract one.
- **Extract, then finish adopting.** Extraction is not done at the first
  callsite: migrate every inline copy, or file a follow-up listing the
  un-migrated ones by `file:line`.
- **Materialise a primitive only when a consumer adopts it in the same change.**
  A primitive with zero callsites is dead code the value scan cannot see.
- **Adoption and conformance are different questions.** Adoption — does this
  screen use the right primitive and tokens — is your job on every change here.
  Conformance — does the primitive render to spec — is a question for changes to
  the primitive.
- **Changing a token or a primitive ripples.** A relaxation of a stated principle
  is an explicit principle update with a rationale, never a silent edit. The
  design system carries its own `CHANGELOG.md`; a token or primitive change is
  recorded there.

## Every state, not just the happy one

- [ ] **Empty** — useful, not "no data found"; often the first thing a new user
      sees.
- [ ] **Loading** — a skeleton for content, inline feedback for an action, never
      a blocking spinner over work the user is mid-way through.
- [ ] **Error** — specific, helpful, with a clear path back to success.
- [ ] **Edge** — 0 items, 1 item, many items, long names, missing data.

**Absence is not zero.** A nullable domain value crosses a client mapping as
nullable; each surface decides how absence *looks*. Never narrow it to `0` or to
"today" to make a screen easier to render — that records a choice the brewer
never made.

## Accessibility

`design/02-principles/accessibility.md` is the standard and it is specific: a
44pt minimum touch target, type surviving 200% Dynamic Type without layout
breakage, 4.5:1 contrast on text. Read it rather than working from a generic
checklist. This is React Native, so the web reflexes do not transfer — keyboard
focus order and hover affordances are not the axes here. What is:

- [ ] Touch targets clear 44pt. A caller that sheds a primitive's box owes a
      `hitSlop` restoring the minimum, then a check that the slop does not eat
      the gap to its neighbour. A `hitSlop` is clipped by an `overflow: 'hidden'`
      ancestor, not by the parent's height.
- [ ] ★ **`accessible` on a container hides every control inside it.** The
      container becomes the accessibility element and its children are
      unreachable to VoiceOver. Put an accessible label on the label element, not
      on the row container and not on the track. RNTL does **not** catch this —
      the whole suite passes over it — so it is a read-the-diff check.
- [ ] Colour is never the only carrier of meaning; a decorative status dot needs
      the meaning in its label text too.
- [ ] It works one-handed rather than merely fitting.
- [ ] Copy is clear, specific, and actionable.

## Where testable logic goes

Screens under `mobile/app/` are not unit-testable and are checked in the
simulator. Pure logic belongs in `mobile/lib/`, covered by Jest; the coverage
floor may rise but never fall. Before adding state or a business transition to a
screen already on the `architecture_watchlist` in `harness.yaml`, extract to the
seam that entry names — or record a ticket-backed deferral.

## A new route is gate-blocked until it is scored

Every screen added under `mobile/app/` needs a row in
`specs/controlplane-app-flow-scorecard.md`, verified by actually visiting the
route under Expo Web — not by the route file existing. `app_flow_scorecard_gate()`
enforces it on any mobile-scoped run. Adding the route without the row is a red
gate, not a follow-up.

## Visual evidence, when the diff touches a user-facing surface

Not a judgment call about size or risk: any diff touching a screen, route, view,
or the styles behind one renders evidence before handoff.

**Render** the changed surface with realistic **seeded** state — synthetic
throughout, never production data. Two working recipes, both on record: the iOS
simulator (`bash scripts/sim-db.sh populated|clean`, then sign in with the
dev-only account in `.env.example` — the seed owner must equal the Supabase JWT
`sub`), or `npx expo start --web` driven by Playwright at **390×844** with a
hand-crafted Supabase session in `localStorage`.

**Capture** at a fixed viewport, in **viewport-height slices** scrolled one
viewport at a time and numbered in scroll order. Never a full-page capture, and
never one over 2000 px tall — a taller capture reaches the reviewer downscaled
past legibility.

**Store** captures and a `manifest.md` in `.evidence/<TICKET-ID>/` at the
worktree root. That path is git-ignored and **per-worktree**: it does not survive
a subagent's auto-cleaned worktree, and it never reaches the committed tree. To
put evidence somewhere durable, upload it to the Linear issue.

**Bound it:** at most 12 captures per review. Name them
`<page>-<state>-<width>w-<slice>.png`. Never shrink an image to fit — that
reintroduces the failure the slice rule prevents.

**Judge** each capture against the reference or the applicable archetype, and
review the implementation too: screenshots do not replace code review. Revert
seeded data and capture-only code before verification.
