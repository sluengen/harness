<!-- guidance:template-proposal@0.1.2 -->
---
proposal: bug-and-tweak-capture-commands
status: shipped         # draft | under-decision | accepted | shipped | rejected | split
date: 2026-07-24
related:
  - commands/propose.md
  - commands/start.md
  - templates/change.md
  - templates/proposal.md
  - skills/spec-driven-development/SKILL.md
---

# Proposal: a capture front door for bugs and tweaks

***Shipped.** The capture front door is `/bug` and `/tweak` (`commands/bug.md`, `commands/tweak.md`), both filing straight to Todo through the shared `templates/adjustment.md`.*

> When actual use surfaces a bug or a small tweak, there is no lightweight way to get it onto the board. `/propose` is the wrong shape (it decides the unconfirmed; these are already confirmed) and manual issue plumbing is fiddly and trap-laden. Add a thin capture command — one shared template, one process — for the *as-built adjustment*.

## Problem / motivation

The command surface has a front door for **unconfirmed or large** work (`/propose` → decide → spawn change specs) and a front door for work **already on the board** (`/start` / `/build` / `/harness run` → pick it up and build). It has nothing for the most common thing that happens when you actually *use* the shipped product: you notice a bug, or you want a small upgrade. That observation has nowhere lightweight to land.

The two available routes are both wrong:

- **`/propose` is overkill and mis-shaped.** A proposal *decides the unconfirmed* — options, recommendation, a decision gate, a breakdown into multiple change specs. A bug is not unconfirmed (something is broken; it should be fixed) and a small tweak is not multiple change specs. Running the full proposal machinery for "the promote output should sort verbs alphabetically" produces ceremony no one reads and a decision gate for a decision that was never in doubt. The proposal tier answers "should we, and how big is it"; a bug/tweak has already answered both.

- **Filing by hand is fiddly and trap-laden.** The alternative is raw tracker plumbing. On this repo's GitHub backend that is three steps — `gh issue create`, `gh project item-add`, then `gh project item-edit` to set Status=Todo — and the middle step has a live trap already burned into memory: **`gh project item-add` does not set Status**, so an item filed and forgotten lands with Status unset and `work-discovery`'s Todo-scoped read never sees it (tick #90). Every hand-filed bug is a chance to drop a ticket into a state the loop cannot find.

So the friction is real and it falls exactly where friction is most expensive — at the moment of noticing, when the cost of capture should be near zero or the observation is lost. The operator's own framing names the gap precisely: a **bug** is an issue with the current implementation; a **tweak** is a small upgrade to it. Both are *an adjustment to as-built functionality, surfaced by actual use* — the same shape, and a shape neither existing front door fits.

## The shared shape, and the one axis they differ on

Bug and tweak take the same form: *here is what it does today (observed in use), here is what it should do instead, here is the situation that surfaced it.* That is a **change spec** — confirmed, single-piece work — not a proposal. The capture command's job is to write that change spec straight onto the board as Todo, ready for `/start` to pick up. It is the inverse of `/propose`: `/propose` *decides, then files*; capture *files the already-decided*.

They differ on exactly one axis — **certainty of direction**:

- A **bug** is unambiguous. The as-built behaviour contradicts the intent (or the feature spec). There is nothing to decide; the fix direction is "make it match." Straight to Todo.
- A **tweak** carries a faint "should we?" The as-built behaviour is *correct* — it is being upgraded, not corrected — so occasionally a tweak is really a small proposal in disguise. The escape hatch matters: if a tweak turns out to carry a real decision or spawn more than one change, it is a `/propose`, not a capture.

This one-axis difference is the whole design question: does it justify two commands, or one command with a `kind`?

## Options

**Option A — two thin commands (`/bug`, `/tweak`) over one shared template and one shared process** · Two bare-name commands, each a thin wrapper that fills the same `templates/adjustment.md` (with a `kind` field) and files it straight to Todo through the tracker-neutral path `/propose` step 4 already uses. The command files carry only the framing prompts unique to each kind; the template and the filing process are shared and live once. · *Trade-offs:* two more names in the universal surface, and a steward's *lean* check will ask why two commands share a template. Answered by the speech act: at the moment of noticing you type the verb for what you noticed — `/bug` or `/tweak` — with no flag to recall, and the two carry a genuinely different default (a bug is confirmed; a tweak may escalate to `/propose`).

**Option B — one command with a kind (`/report bug …` / `/report tweak …`, or inferred)** · A single front door, single template, `kind` selected by argument or inferred from the text. · *Trade-offs:* one name, unambiguously lean. But "report" fits a bug and strains on a tweak (you do not *report* an upgrade), the kind becomes a token to remember, and it flattens the certainty-of-direction axis that actually wants different handling — a single command that treats bug and tweak identically loses the one distinction worth keeping.

**Option C — a fast path inside `/propose` (`/propose --quick` / a capture mode)** · Fold capture into the command the operator already reaches for, as a mode that skips options/recommendation/decision and files one change spec. · *Trade-offs:* no new name. But it overloads one command with two opposite intents — *decide the unconfirmed* and *capture the confirmed* — and the mode flag is exactly the ceremony the operator is trying to escape. `/propose`'s value is that it means one thing; a `--quick` that means the opposite erodes that.

**Option D — do nothing; keep manual filing** · *Trade-offs:* zero new surface. Leaves every use-surfaced observation behind a three-step `gh` dance with a Status trap, or an over-heavy proposal — which in practice means observations get dropped rather than captured. The status quo is what motivates the proposal.

## Recommendation

**Option A — two thin commands (`/bug`, `/tweak`) sharing one `templates/adjustment.md` and one capture process** — with the tweak's escape hatch to `/propose` written into the command rather than built as a gate.

The duplication objection is the only real one, and it dissolves on how this guidance is already built: commands are thin, the durable content lives in templates and skills (`/start` is 33 lines over the `spec-driven-development` lifecycle; `/promote` and `/decision` delegate their judgment to skills they do not restate). `/bug` and `/tweak` follow the same pattern — each is a few lines of kind-specific framing over one shared template and one shared filing process. There is no meaningful duplication to remove, and collapsing them to one command (Option B) *costs* the one distinction worth keeping: the verb-at-point-of-use ergonomics and the different default (bug → Todo; tweak → Todo *unless* it is really a proposal). *Smallest change that fits*: the filing mechanism already exists (`/propose` step 4 files issues; the tracker-neutral path is `CONTEXT.md`'s concern), so this is two command files plus one template — no new engine surface, no new verb.

On the template: a bug/tweak is a change spec, but `templates/change.md` is the *build-time* form — Grounding, Design (data model / interface / scenarios), Watchlist trigger — filled by the builder who picks the ticket up. Capture happens *before* a builder is assigned, by the person who noticed, who has the observation but not yet the fix. Forcing the full change-spec form at capture time reintroduces exactly the friction this removes. So `templates/adjustment.md` is a **capture-optimized change spec**: same destination (the issue body), pre-framed for the as-built adjustment, and *extended* by `/start` with Grounding and Design at build time. It is an on-ramp to the change spec, not a competing artifact — the reviewer still records what shipped into the feature spec exactly as for any change.

On the tweak's "should we?": handle it as an **escape hatch, not a gate**. A tweak whose direction is clear files straight to Todo like a bug; a tweak that carries a real decision or spawns more than one change is not a tweak — `/tweak` says so and points at `/propose`. This keeps both commands to a single job (capture) and avoids inventing a bespoke confirm step. The existing hold machinery (`/decision`, the `decision` hold kind, ADR 0006) already covers the case where a *filed* item later turns out to need a call — a captured tweak is not special there.

## Open decisions

All four decided by the operator on 2026-07-24 — each resolved to the recommended option. Resolutions below; they are recorded into the specs they govern when the breakdown items ship.

| Decision | Resolution | Recorded in |
|---|---|---|
| One command or two | **Two** — `/bug` + `/tweak`, thin over one shared template and process. | `commands/bug.md`, `commands/tweak.md`, `CLAUDE.md` command table |
| Capture template | **New `templates/adjustment.md`** — a lightweight capture form that `/start` extends into a full change spec at build time. | `templates/adjustment.md`, `spec-authoring` |
| The tweak's "should we?" | **Escape hatch to `/propose`** — clear tweaks file straight to Todo; a tweak carrying a real decision or spawning >1 change stops and points at `/propose`. No bespoke gate. | `commands/tweak.md` |
| Names | **`/bug`, `/tweak`, `templates/adjustment.md`** — matching the operator's own "adjustment to as-built functionality" framing. | `CLAUDE.md` command table |

## Breakdown

Accepted as Option A. Each item is shippable on its own and is filed as a Todo issue on `sluengen/2`. Ordered by dependency — the template must exist before either command fills it.

1. **[#199](https://github.com/sluengen/harness/issues/199) — `templates/adjustment.md`** — the shared capture template: `kind: bug | tweak` and `area` frontmatter; body sections *As-built (observed)* / *Desired* / *From actual use* / *Acceptance criteria*, with per-kind framing notes (a bug's observed is the wrong behaviour + repro; a tweak's is the current behaviour + the friction). Explicitly a capture form that `/start` extends into a full change spec. Version-stamped. Blocks #200 and #201.
2. **[#200](https://github.com/sluengen/harness/issues/200) — `commands/bug.md`** — files a `kind: bug` adjustment straight to Todo through the tracker-neutral filing path (`CONTEXT.md` tracker; on GitHub, create → add-to-board → **set Status=Todo**, closing the item-add-no-status trap). Thin over the template. Depends on #199.
3. **[#201](https://github.com/sluengen/harness/issues/201) — `commands/tweak.md`** — as `/bug`, `kind: tweak`, plus the escape-hatch rule: if the tweak carries a real decision or spawns more than one change, stop and point at `/propose`. Thin over the template. Depends on #199.
4. **[#202](https://github.com/sluengen/harness/issues/202) — wire it into the process docs** — name the capture on-ramp in `spec-driven-development` / `spec-authoring` (where change specs are introduced) and add both commands to the `CLAUDE.md` / `AGENTS.md` command table with the boundary against `/propose` and `/start`. Register the two command versions and the template version. Depends on #199–#201.

Items 2 and 3 could land as one change; splitting keeps each command's default honest (bug → Todo; tweak → Todo-or-escalate) rather than a shared branch with an `if kind` scattered through it. Item 4 lands last so the docs describe what shipped.

## Risks / unknowns

- **Redundancy / lean pressure.** Two commands sharing a template invites a steward *lean/MECE* finding. The defense is the crisp three-way boundary — capture the confirmed-small (`/bug`, `/tweak`) vs decide the unconfirmed (`/propose`) vs pick up the filed (`/start`) — and it must be written into the command table, not left implicit, or the next assessment re-litigates it.
- **The tweak/proposal boundary is genuinely fuzzy.** "Small upgrade" and "small proposal" shade into each other. The escape-hatch rule (real decision or >1 change → `/propose`) is a one-line test, but it will misfire at the margin; the cost of a miss is low (a tweak that should have been a proposal gets filed as one ticket and the builder escalates at `/start`).
- **Scope creep into a bug tracker.** `/bug` could accrete severity, triage, assignee, reproduction-environment fields. Hold the line at *capture* — the template stays the four sections; anything more is the tracker's job, not the command's.
- **Tracker coupling.** The filing path must set Todo across both `github` and `linear` backends. The GitHub Status trap is known and documented; the `linear` skill covers its side. This is the same coupling `/propose` step 4 and `/decision` already carry — no new seam, but it is real.
- **Two more bare names.** `/bug` and `/tweak` claim universal names. Both read as natural verbs, but a repo with its own `/bug` would collide; the namespacing rule (repo prefixes its own) covers it, and neither name is currently taken in this guidance.

---

**Lifecycle.** A proposal ends in one explicit state: **accepted** (spawn the change specs as issues; record its decisions in the relevant specs), **rejected** (keep this file as the record of why), or **split** (replace with smaller proposals). It does not sit half-decided. Lives in `specs/proposals/`.
