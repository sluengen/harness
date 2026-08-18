---
proposal: design-system-scaffold
status: shipped         # draft | under-decision | accepted | shipped | rejected | split
date: 2026-07-28
related: [repo-guide-landing-page, specs/decisions/0004-repo-guide-drift-guard.md]
---

<!--
Decided 2026-07-28 (operator):
- Distribution: OPTION D — the contract doc (`templates/design-system.md`). Distribute the
  rules; an agent generates the tree, repo-native. No vendored scaffold tree, no init command.
- Dogfooding: YES — the harness flips `design_system: true` and stands up `design/` with layers
  00–03 substantive, 04–07 as declared scaffolds.
- Token seam: A REAL BUILD STEP — overrules the proposal's recommended hand-authored + drift
  guard. `docs/index.html`'s `:root` block is GENERATED from `design/03-tokens/tokens.json`.
  This NARROWS ADR 0004 ("a lean gate guard, not a generator") rather than extending it, so
  breakdown item 5 amends that ADR as a scope change, not a footnote. The generator emits
  INLINE — `tests/unit/test_landing_page.py::test_no_external_resource_requests` still holds.
- Location: `design/` at the repo root (not `docs/design/`, which Pages publishes world-readable).
  Matches both reference repos. Decided by the agent as a routine call, per the proposal.
-->

# Proposal: Distribute the eight-layer design-system scaffold, and use it on the landing page

***Shipped.** The eight-layer scaffold is `design/` (`00-brand` through `07-flows`), with `design/03-tokens/tokens.json` as the token source the landing page renders from.*

> Bring the layered design-system scaffold that `calibrate` and `nano-erp` both run into the harness — as distributable guidance any repo with `design_system: true` can stand up, and applied to `docs/index.html`, the one external-facing surface the harness owns.

## Problem / motivation

The harness distributes `skills/design-system/SKILL.md` to every repo it serves. That skill is explicit about what it is: *"routing and discipline, not a copy of the rules"*. It tells an agent to do a two-stage lookup — find the principle, then find its materialization — and points at "the path in `CONTEXT.md`" for the system itself (`paths.design_system`).

**There is nothing at the other end of that pointer.** The harness ships the discipline for using a design system and no way to get one. A repo that turns the layer on has to invent the structure, and two of them already did — independently, and identically.

`calibrate` (`~/Code/calibrate/design/`, remote `sluengen/calibrate`) and `nano-erp` (`~/Code/nano-erp/design/`) run the same eight-layer system:

```
00-brand → 01-voice → 02-principles → 03-tokens → 04-primitives → 05-patterns → 06-archetypes → 07-flows
```

They converge on far more than the folder names: a one-way dependency stack (a layer may consume what is above it, nothing reaches downward), the same three rules, the same frontmatter contract (`layer` / `kind` / `status` / `owner` / `last_updated`) that makes each file agent-readable, a `_template.md` per composable layer, a three-tier token model (primitive → semantic → component) with one `tokens.json` as source of truth, generated outputs that are committed and drift-checked and never hand-edited, and a lint that fails the gate on any raw colour or size literal in consuming code. `nano-erp`'s README says so outright: the structure is borrowed from `calibrate`, *"but the content is ERP-native and the delivery is different."*

That sentence is the whole finding. **What travels between the two repos is structure and contract. What does not travel is content and the build.** `calibrate` runs Style Dictionary through `tooling/build.mjs` to emit a typed TS module for React Native + Expo. `nano-erp` runs a TS script to emit CSS custom properties, because it re-skins per tenant at runtime from a branding resolver rather than per build. Same scaffold, two entirely different seams into the target stack.

Two costs to leaving this alone:

1. **The third repo re-derives it.** The convergence happened by hand, twice. Nothing captures it, so the next repo either copies a directory out of `calibrate` (inheriting coffee-flavour taxonomies and an Expo integration guide it does not want) or reinvents the layering badly. The `design-system` skill will keep pointing at nothing.
2. **The harness does not dogfood what it publishes.** The harness runs `feature_specs: true` for exactly this reason — it eats the surface it distributes. It runs `design_system: false`, and its one public artifact, `docs/index.html`, is 662 hand-authored lines with an ad-hoc `:root{--ink:#0e1430; --build:#0f9d6e; …}` block at the top. That block is a token layer with no naming scheme, no tiers, no principles above it, and no record of why those hues mean what they mean. It works, and it is precisely the state the eight-layer system exists to replace.

## Options

These are two questions — how the scaffold is distributed, and whether the harness adopts it — and they are separable. Options A–D answer the first.

**Option A — One reference doc (`templates/design-system.md`)** · Follow the `templates/size-guard.md` precedent: a single distributed markdown file describing the system, with the layer structure, the three rules, the token tiers, and copy-paste `_template.md` bodies inline, adopted by hand. · One registry entry, zero installer change, consistent with how the harness already ships an adoptable reference implementation. But the size guard compresses to one doc because it *is* one ~30-line file; this scaffold is ~28 files whose value is partly that they exist as a walkable tree. A single doc describing a directory is not the same artifact as the directory.

**Option B — Vendor the scaffold tree into the registry (`design-system/**`)** · Add the generic scaffold — eight layer `README.md`s, the `_template.md` files, `_naming.md`, a starter `tokens.json`, `governance/`, an `AGENTS.md` contract — as ~28 registry-tracked files the installer copies like any other guidance. · Highest fidelity; a repo gets a real tree it can start filling in immediately. But the installer copies the **whole profile** to every consumer, and install-time layer gating is explicitly unbuilt (CAL-749, noted in `registry.yaml`). Every repo running `design_system: false` — most of them — would get 28 dormant files. It also grows the registry's file count by roughly 40% for a layer that is off by default.

**Option C — Vendor the tree, materialize it on demand (`/design-system init`)** · As B, but the scaffold ships as a payload a new command writes into the consuming repo only when the operator asks, so it never lands in a repo that has not opted in. · Solves B's every-repo-gets-28-dormant-files problem and keeps the tree faithful. Cost: a new command plus a materialization mechanism, and the harness has no precedent for a command that writes a file tree — every existing command drives a process.

**Option D — Distribute the contract, generate the tree (recommended)** · `templates/design-system.md` carries the **contract**: the eight layers and what each answers, the one-way dependency rule, the three rules, the frontmatter fields, the three token tiers and the naming scheme, the no-raw-values rule, the committed-and-drift-checked output discipline, and — named explicitly as the repo's own job — the **stack seam**: the build that turns `tokens.json` into whatever the target stack consumes, and the lint that enforces it there. An agent reading that doc stands the tree up for the repo it is in, with content native to that repo. · Leanest, and it matches what the harness actually distributes everywhere else: knowledge, not code. It is also the honest artifact — since content does not travel between `calibrate` and `nano-erp`, a vendored tree of empty READMEs is a directory of prompts pretending to be a system. Cost: no walkable tree out of the box, and generation quality depends on the doc being good.

## Recommendation

**Option D for distribution, plus adoption on `docs/index.html`.**

Distribute the contract, not the carcass. The evidence from the two repos is that the transferable asset is the *rules* — the layering, the tiers, the naming, the frontmatter, the enforcement discipline — and that every byte of content is repo-native. That is knowledge, and knowledge is the thing the harness's registry is built to version and ship. It also keeps `engineering-principles`' preference for the simplest thing that works: one versioned markdown file against a 28-file tree copied into repos that do not want it.

The doc must name the stack seam as out of its own scope and in the adopting repo's. This is the boundary the user identified and the one place the two reference implementations genuinely diverge: `tokens.json` → typed TS for Expo, or → CSS custom properties for runtime multi-tenant theming, or → something else. The scaffold defines the contract the seam must satisfy (semantic tokens only in consuming code; generated output never hand-edited; a lint that fails the gate on raw values) and leaves the implementation to the repo.

Then **use it here**, which is what makes the distributed doc trustworthy rather than aspirational:

- Flip `layers.design_system: true` and set `paths.design_system` in `CONTEXT.md`.
- Stand up `design/` with layers **00–03 substantive** and **04–07 as honest scaffolds** — the same status `nano-erp` records, and the truthful shape for a repo whose entire surface is one static page. `00-brand` and `01-voice` already have real content to capture: the page's own voice ("an evidence layer for agent-driven development") and the four-loop colour semantics (`--build` green, `--product` blue, `--quality` amber, `--strategy` violet) that currently exist only as unexplained hex.
- Rewrite the page's `:root` block as the generated form of `design/03-tokens/tokens.json`, keeping every rendered value identical. This is a re-expression, not a redesign.

That last step runs straight into a recorded decision, and the proposal takes a position on it rather than sliding past it. **ADR 0004 chose a lean gate guard over a generator for this page**, and `tests/unit/test_landing_page.py::test_no_external_resource_requests` forbids a linked stylesheet — so the tokens must stay inline in the file whatever the mechanism.

The proposal recommended applying ADR 0004's own logic one layer down: hand-author the `:root` block and add a drift check that it matches `tokens.json` — the same shape as `check_landing_page_guidance.py`, one cheap invariant, no standing machinery for a single page.

**The operator decided otherwise: a real build step.** `design/03-tokens/tokens.json` is the source, and a generator emits the `:root` block into `docs/index.html` — inline, so the page stays self-contained and `test_no_external_resource_requests` is unaffected. This is the discipline both reference repos run (`nano-erp` commits its `build/tokens.css` and drift-checks it in `verify`), and it buys what a guard cannot: the palette can never diverge from its source, because the source is the only place it is written.

Recognize what that costs, because the decision record has to be honest about it. **This narrows ADR 0004 rather than extending it.** That ADR rejected "a real build system for a single page" and settled on a guard; a generator that writes into the page is the machinery it declined. The narrowing is defensible on its own terms — ADR 0004 reasoned about the *guidance catalog*, whose value is narrative prose that cannot be generated, whereas a colour ramp is exactly the mechanical, fully-generatable content the ADR's argument does not cover — but that is a change to a recorded decision, and breakdown item 5 amends it as one.

One consequence specific to this repo: the harness has no npm and no Style Dictionary, so the generator is **stdlib Python**, run from `scripts/verify.sh` like every other gate step. That is the harness supplying its own stack seam — the exact boundary the contract doc says belongs to the adopting repo — which makes it a third worked example alongside `calibrate`'s typed TS and `nano-erp`'s CSS custom properties, and the one a reader of the doc can see end-to-end in the same repo.

## Open decisions

All blocking decisions are resolved (2026-07-28). One remains open by design, to be settled at design time.

| Decision | Who decides | Outcome | Recorded in |
|---|---|---|---|
| Distribution shape: contract doc (D) vs. vendored tree (B) vs. tree + `/design-system init` (C) vs. single reference doc (A) | user | **D — the contract doc.** Distribute the rules; the tree is generated repo-native. | this proposal + `registry.yaml` (item 1) |
| Does the harness itself adopt the layer (`design_system: true`) for one static page, or distribute without dogfooding? | user | **Adopt.** Layers 00–03 substantive, 04–07 declared scaffolds. | `CONTEXT.md` (item 3) |
| Token materialization for `docs/index.html`: hand-authored `:root` + drift guard vs. a real build step vs. leave the page alone | user | **A real build step**, overruling the recommendation. Generator emits the `:root` block inline from `tokens.json`. Narrows ADR 0004. | `specs/decisions/0004-repo-guide-drift-guard.md`, amended (item 5) |
| Where the harness's own system lives: `design/` at the repo root vs. `docs/design/` | user | **`design/` at the root** — matches both reference repos; `docs/` is Pages-published and world-readable. Taken as a routine call. | `CONTEXT.md` `paths.design_system` (item 3) |
| How much of layers 00–02 gets authored for the harness — full brand/voice/principles, or only what `docs/index.html` demonstrably needs today | architect, at design time | **Open.** Settled when item 3 is designed. | `design/README.md` status section |

## Breakdown

Each shippable on its own, in dependency order. Items 1 and 2 are the template half; 3–5 are the adoption half and can stop after 3 if the operator declines the rest.

1. **[#239](https://github.com/sluengen/harness/issues/239) — `templates/design-system.md`, the scaffold contract.** The eight layers and what each answers; the one-way dependency rule; the three rules; the frontmatter contract; the three token tiers and `_naming.md` scheme; the no-raw-values lint rule; the committed-and-drift-checked output discipline; and the stack seam named as the adopting repo's job, with `calibrate` (typed TS for Expo) and `nano-erp` (CSS custom properties for runtime theming) cited as the two worked shapes. Registered in `registry.yaml`.
2. **[#240](https://github.com/sluengen/harness/issues/240) — point `skills/design-system/SKILL.md` at it.** The skill currently routes to a path in `CONTEXT.md` that may not exist. Add the fallback: no system yet → stand one up from `templates/design-system.md`. Version bump. Closes the dangling pointer that motivates this proposal.
3. **[#241](https://github.com/sluengen/harness/issues/241) — stand up `design/` for the harness, layers 00–03.** Brand, voice, principles, and a `tokens.json` whose values are exactly today's rendered `docs/index.html` palette and scale. Layers 04–07 as scaffolds with a status note. Flip `layers.design_system: true` and set `paths.design_system` in `CONTEXT.md`.
4. **[#242](https://github.com/sluengen/harness/issues/242) — build the token generator, and generate the page's `:root` block.** A stdlib-only `scripts/build_design_tokens.py` reading `design/03-tokens/tokens.json` and emitting the `:root` block **inline** into `docs/index.html` between explicit generated-region markers, so the rest of the hand-authored page is untouched and the file stays self-contained. Every rendered value byte-identical to today; the seven `<style>`-block colour groups mapped onto semantic token names. No visual change — `tests/unit/test_landing_page.py` must pass untouched, `test_no_external_resource_requests` included. This is the harness's own stack seam, the boundary item 1's doc assigns to the adopting repo.
5. **[#243](https://github.com/sluengen/harness/issues/243) — wire the build into the gate, and amend ADR 0004.** A `--check` mode that fails when the committed `:root` block drifts from `tokens.json`, run from `scripts/verify.sh` beside `check_landing_page_guidance.py` — the committed-and-drift-checked output discipline both reference repos run. Amend `specs/decisions/0004-repo-guide-drift-guard.md` to record that its "guard, not generator" scope is now **narrowed to the guidance catalog**: the catalog stays guarded and hand-authored because its value is narrative prose, while the token block is generated because a colour ramp is mechanical content the ADR's reasoning does not cover.

## Risks / unknowns

- **The eight-layer system may be disproportionate for one static page.** Four of eight layers would be honest scaffolds indefinitely; the harness has no components, no flows, and no second surface. The dogfooding argument is real (`feature_specs: true` exists on the same reasoning) but so is the ceremony. If the operator judges it disproportionate, items 3–5 drop and item 1–2 still deliver the distribution value on their own — which is why the breakdown is ordered to allow that.
- **Option D's quality is the doc's quality.** A contract doc that generates a weak scaffold is worse than a vendored tree, because the failure is invisible until a repo has already built on it. Mitigation: write the doc from the two working systems and check it by generating a tree and diffing the structure against both.
- **ADR 0004 is being narrowed, and that is the sharpest risk here.** The decided build step is the machinery that ADR explicitly declined for this page, so items 4–5 must carry the amendment rather than quietly adding a generator beside a decision that says there isn't one. The distinction the amendment rests on — generated mechanical content vs. guarded narrative prose — is sound but it is a *new* line, drawn after the fact. If it does not hold up at design time, the fallback is the proposal's original recommendation (hand-authored `:root` + a match check), which delivers the same drift protection without touching the ADR.
- **A generator that rewrites a hand-authored HTML file is a delicate seam.** The page is 662 lines of hand-tuned CSS, SVG, and prose pinned by seven unit tests. The generated region must be fenced by unambiguous markers and must never reformat anything outside them; a generator that reflows the file will fight every future hand edit. This is the concrete cost ADR 0004 was avoiding, and item 4 has to earn it with a narrow, marker-bounded write.
- **The reference repos are moving.** `calibrate`'s `design/` has active tooling (a workbench server, ERD and flow renderers, a search index) that is well past scaffold. The contract doc must capture the stable core, not chase that surface area, or it will be stale on arrival.
- **What would invalidate the recommendation** — if the operator wants a repo to receive a *runnable* scaffold (install, `npm run tokens:build`, green) rather than a generated one, Option D is the wrong shape and this becomes Option C: vendored tree plus a materialization command, roughly triple the work.

---

**Lifecycle.** A proposal ends in one explicit state: **accepted** (spawn the change specs as Linear issues; record its decisions in the relevant specs), **rejected** (keep this file as the record of why), or **split** (replace with smaller proposals). It does not sit half-decided. Lives in `specs/proposals/`.
