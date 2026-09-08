---
proposal: spine-vocabulary-not-rules
status: under-decision   # draft | under-decision | accepted | shipped | rejected | split | superseded
date: 2026-09-08
related: [plugin-surface, lifecycle-reset, do-less-at-ingestion]
---

# Proposal: the spine carries vocabulary, the skills carry rules

> The contract section states rules that skills also state, so one semantic change costs four edit sites. Cut the contract to the words a builder and a reviewer must both know, and leave what each word obliges with the skill that already owns it.

## Problem / motivation

The spine's contract section opens with a claim its own tree falsifies:

> The vocabulary every agent and command shares. Nothing below is restated elsewhere; the skills assume it.

Five of its nine bullets are restated in the skill the same bullet names as owner:

| Contract bullet | Spine says | The named owner also says |
|---|---|---|
| Lanes | the three lanes and what each obliges, then "`authoring` chooses the lane" | `skills/authoring/SKILL.md:101-103` — the same three in a table |
| Verdicts | PASS / FAIL / DEFER and what each means | `skills/review-discipline/SKILL.md:99` |
| The binding | verdict binds to tree oid, both acceptance paths | `skills/review-discipline/SKILL.md:99,109` |
| The queue | "A slot is free when the count is below the limit" | `skills/work-discovery/SKILL.md:48` — near-verbatim, and it cites "(the spine's contract)" |
| Ticket states / Filing | explicit placement, Todo or Backlog by free slot | `skills/tracker/SKILL.md:40-43` |

**The cost is fan-out per clause change.** #597 narrowed one clause — the lane a proposal-spawned ticket takes. That single semantic change touched seven files, four of them homes of the clause: `templates/spine.md`, `AGENTS.md`, `CLAUDE.md`, and `skills/authoring/SKILL.md` (`23ef8a6`). The feature spec records the sweep at `specs/features/plugin-surface.md:104`.

Three of those four homes are byte-copies held in agreement by `tests/unit/test_spine_template_parity.py`, so they are diff noise rather than drift risk. **The fourth is the problem:** `skills/authoring/SKILL.md` states the same rule in different words, and no guard holds the two in agreement. #456 catalogued restatement drift as a measured cost; law 2 forbids the obvious remedy, because a criterion about what a document says has no measuring test.

Across the window 2026-08-01 to 2026-09-08, nine commits changed a contract clause. Files touched: 5, 7, 11, 12, 13, 19, 20, 29, 32 — median 13. Seventeen of the 26 commits touching `templates/spine.md` also touched `skills/` (65%).

**What this is not.** The spine is not oversized and not the churn centre. `AGENTS.md` is 85 lines against the 120-line ceiling #588 set (`specs/features/plugin-surface.md:60`), of which the plugin-owned generated block is 56. Over the same window `templates/spine.md` took 26 commits against 114 for `skills/` and 80 for `hooks/` and `scripts/`. Doing nothing costs a stale restatement on the day somebody edits one home and not the other, which is the failure #597 avoided by hand.

## Options

**Option A — Leave it, and guard the fourth home.** Add a gate stage asserting the spine's lane wording and `authoring`'s table agree. Cheap to state. It is a prose-about-prose guard, which ADR 0017 D5 admits under no class, and law 2 refuses it directly. It also defends agreement between two homes rather than removing the second one, which P0 refuses as a mechanism where a subtraction would do.

**Option B — Cut the contract to vocabulary; rules go to their owner.** The spine keeps the words a builder and a reviewer must both know and drops what each word obliges. `authoring` keeps the lane rubric it already has; the spine names the three lanes and stops. Removes the second home rather than guarding it. Costs a rule that reaches an agent only when the owning skill loads.

**Option C — Move laws and lifecycle to conditional loading.** The originating idea. Laws are 11 lines and their edit history is one law converging, not structural churn; their rationale already sits in HTML comments stripped before injection, so it costs nothing to keep (`specs/proposals/lifecycle-reset.md:146`). ADR 0017 rejected discovery-only loading at the system level ("pull is probabilistic; a stop rule cannot be") and #547 measured skills firing at 53% against 100% for path-scoped rules. A conditionally loaded law is a law that fails half the time, and these are the laws the hooks enforce. The lifecycle section is 9 lines of routing table; moving it makes an agent load a skill to learn which skill to load.

**Option D — Split the plugin into delivery, assurance and design-system packages.** Assessed and rejected in session on 2026-09-08. `build → worktree-isolation → build` is a reference cycle, law 3 is a delivery obligation enforced by an assurance hook, and the split converts an internal contract into a versioned cross-plugin interface with no dependency declaration to hold it. ADR 0017 already rejected full decoupling for the same two reasons. The design-system boundary is real and already cut: `layers.design_system`, `paths.design_system`, `design/AGENTS.md`, and a path-scoped twin.

## Recommendation

**Option B**, bounded by a loading rule that keeps governance deterministic.

A rule may leave the spine only where an artefact deterministically loaded for that task pulls it. `/build` always loads `build`; `build` already loads `authoring`, `review-discipline` and `worktree-isolation`. That load is deterministic inside a lifecycle command, which is not the 53% discovery path #547 measured. Anything an agent needs while loading nothing else stays in the spine.

The line between vocabulary and rule, per bullet:

| Bullet | Stays in the spine | Moves to |
|---|---|---|
| Ticket states | the six names; only Todo is pulled | `tracker` |
| Holds | held = assigned to a human; `input` or `operator` | `tracker` |
| Lanes | the three names; upgrade-only; a protected area stops and holds | `authoring` |
| Verdicts | PASS, FAIL, DEFER, one clause each | `review-discipline` |
| The binding | a verdict binds to a tree oid; two acceptance paths exist | `review-discipline` |
| The queue | `wip_limit` bounds the queue; no free slot means Backlog | `work-discovery` |
| Filing | folds into Ticket states | `tracker` |
| Tracker dispatch | folds into Configuration | `tracker` |
| Configuration | unchanged — it already names the file rather than restating a value | — |

This traces to P0 (a subtraction where Option A adds a mechanism), P2 (the restatement is over-production, and the second home is a second copy), and ADR 0017 D2, which put the contract in the spine so builder and reviewer share a wire format. D2 is the reason the vocabulary stays; it never argued that the obligations attached to each word had to sit beside them.

**The success criterion is falsifiable.** Median files touched per contract-clause change is 13 today, and the isolated single-clause case (#597) is 7 files across 4 homes. After the change, a clause narrowing of #597's shape should touch the three spine copies only where the vocabulary itself moved, and otherwise one skill. If the figure does not fall, the restructure failed and should be reverted rather than defended.

## Not doing

- **A guard holding the spine and a skill in agreement** — prose-about-prose, refused by law 2 and admitted by no ADR 0017 D5 class. Reopen if D5 gains a class that admits it.
- **Moving laws out of the spine** — governance cannot be probabilistic (ADR 0017; #547 measured 53% against 100%). Reopen if a host ships deterministic conditional loading for a non-path-scoped artefact.
- **Moving the lifecycle section out** — 9 lines of routing table, and relocating it makes finding a command require loading a skill. Reopen if the section grows past routing into rules.
- **Splitting the plugin into three** — the delivery/assurance boundary is a reference cycle and a shared wire format, not a seam. Reopen if the goal becomes distributing the gate machinery without the delivery process, which is a market decision rather than an engineering one.
- **Shrinking the spine for its own sake** — it is 85 lines against a 120-line ceiling. Size is not the problem and no line is cut to hit a number.
- **Touching the three-copy chain** (`templates/spine.md` → `AGENTS.md` → `CLAUDE.md`) — the parity test holds it and it carries no drift risk. Reopen if that test is retired.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| Does the vocabulary/rule line sit where the table above draws it, in particular whether *the binding*'s two acceptance paths are vocabulary or rule | user | `specs/features/plugin-surface.md` |
| Is the deterministic-loader rule cross-cutting enough for an ADR, or a Decision block in the plugin-surface spec | architect | `specs/decisions/` or `specs/features/plugin-surface.md` |
| Whether a consumer repo's hydrated spine is migrated by `--refresh` in the same change as each move, or once at the end | user | `skills/init/references/refresh.md` |

## Breakdown

Item 1 is held for the operator. The four-dimension test fires on three counts: **migration**, because consumer repos already carry a hydrated `AGENTS.md` and `engineering:119` requires the `--refresh` rewrite to ship with the contract change, proved against real consumer files; **blast**, because the boundary decides edits in four skills; and **comprehension**, because the operator cannot steer the remaining items without seeing where the line falls.

1. **The boundary, applied to one clause** — held, `input`. Record the vocabulary/rule split and the deterministic-loader rule in the spec the second open decision names. Apply it to *The queue* alone: cut the spine bullet to the two vocabulary sentences, leave the slot arithmetic in `work-discovery` (already there at `:48`), and ship the `--refresh` migration with it, evidenced against a real consumer repo. Depends on nothing. `complex` — a contract change.
2. **Lanes → `authoring`** — cut the spine bullet to the three names, upgrade-only, and the protected-area stop; `authoring:101-103` keeps the rubric. Depends on 1. `complex` — a contract change.
3. **Verdicts and the binding → `review-discipline`** — spine keeps the three verdict names and the tree-oid sentence; the acceptance-path detail and the cycle bound move. Depends on 1. `complex` — a contract change, and the binding is the wire format ADR 0017 D2 named.
4. **Ticket states, Holds, Filing, Tracker dispatch → `tracker`** — spine keeps the six state names, the definition of held, and the two labels; placement and dispatch rules move. Tracker dispatch folds into Configuration. Depends on 1. `complex` — a contract change.
5. **Measure the result** — re-derive median files per contract-clause change over the commits items 2 to 4 produced, and compare against the 13-file median and #597's 7. Report to the improvement ledger. Depends on 2, 3, 4. `simple`.

## Risks / unknowns

- **The mitigation is prose, not a guard.** The deterministic-loader rule is a sentence in a spec. Nothing fails a gate when a future move puts a rule behind a skill that only discovery loads. This is the largest risk and law 2 forbids the guard that would close it; the counterweight is that each move is a `complex` lane change with an independent review.
- **Churn relocates rather than disappears.** A lane change still edits `authoring`. The saving is fan-out, not edit count, which is why item 5 measures the former.
- **Consumer repos lag.** A hydrated spine keeps the old rules until `--refresh` runs. During the gap a consumer's spine states a rule its installed skill also states, which is the status quo, so the gap degrades to today rather than to something worse.
- **The dual-home count is a floor.** It came from grepping the five owners the contract itself names. It did not sweep every skill for every contract concept, so unnamed restatements elsewhere are not counted, and the fan-out may be larger than measured.
- **The median-13 figure reflects whole commits.** Six of the nine contract-clause commits were larger restructures where the clause edit was incidental. #597 is the only isolated case in the window (2 spine lines changed, 7 files), so the clean before-figure rests on one commit.
- **What would invalidate the recommendation:** evidence that an agent inside a lifecycle command does not reliably load the owning skill. That turns every move into a governance hole and returns the answer to Option A or to leaving it alone.

## Grounding

Verified against the tree at `e4f086e` on 2026-09-08.

- Spine generated block, 56 lines: Principles 12, Laws 11, The lifecycle 9, The contract 13, Enforcement 4 (`AGENTS.md`, section extraction between the `spine:generated` markers).
- Churn 2026-08-01 to 2026-09-08: `templates/spine.md` 26 commits, `skills/` 114, `hooks/` + `scripts/` 80. 17 of the 26 spine commits also touched `skills/`.
- Nine commits changed a contract clause; files touched 5, 7, 11, 12, 13, 19, 20, 29, 32. Method: for each commit touching `templates/spine.md`, match added or removed lines against the nine contract bullet labels. Blind spot: matches the bullet's first line only, so a change to a bullet's later sentences is missed and the count is a floor.
- `23ef8a6` (#597): 7 files, 4 of them clause homes.
- Dual-homing verified at `skills/authoring/SKILL.md:101-103`, `skills/review-discipline/SKILL.md:99,109`, `skills/work-discovery/SKILL.md:48`, `skills/tracker/SKILL.md:40-43`. Method: targeted grep per owner named in the contract's own delegation pointers. Blind spot: does not enumerate restatements in skills the contract does not name.
- `AGENTS.md` at 85 lines against the 120-line ceiling: `specs/features/plugin-surface.md:60`. The ceiling's origin and the stripped-comment rationale: `specs/proposals/lifecycle-reset.md:146`.
- Trigger reliability 53% against 100%: `design/AGENTS.md`, citing research 01 §10, the basis for #547.
- ADR 0017's rejection of full decoupling and its D2 and D5: `specs/decisions/0017-harness-v5-plugin-shaped-guidance.md`.
