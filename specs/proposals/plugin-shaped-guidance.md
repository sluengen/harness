<!-- guidance:template-proposal@0.1.3 -->
---
proposal: plugin-shaped-guidance
status: under-decision   # draft | under-decision | accepted | shipped | rejected | split
date: 2026-08-17
related: [0015-harness-v4-thin-verification-layer, guidance-system, harness-as-tool, rebase-stable-certification]
---

# Proposal: Ship the guidance as a plugin — one version, one spine, hydrated repos, and a guard cull

> Stop being a hand-rolled package manager for cross-referenced prose. Package the surface as a plugin (skills, commands, agents, hooks — one version, bumped at release), collapse the always-on context into a single hydrated spine that carries the iron laws, the shared contract, and the repo's executive summary, make every skill a freestanding leaf, restructure the build/design/operate triad as generic method over evolving assets, replace the installer with a hydration command, collapse the command/agent/template inventories to what earns its keep, and delete the guard classes whose subjects those moves remove.

## Problem / motivation

ADR 0015 retired the runtime and left three parts: the guidance surface, the gate, and the guards. The activity since then says the thin verification layer is not yet thin. Measured over the 14 days to 2026-08-17, on `dev`:

| Surface | Lines | Files | 14-day commits |
|---|---|---|---|
| skills + commands + agents (the product) | ~3,400 | 35 | ~90 |
| hooks + scripts (the enforcement) | ~4,650 | 14 | 39 |
| `tests/unit/` (the guards) | ~35,500 | 138 | **205** |
| `registry.yaml` (the versioning) | — | 1 | **85** |

Of the 138 guard modules, **118 read prose** — parity between a file's header and its registry row, pointers landing where they claim, restatements agreeing with their owner, sentences sitting inside the right paragraph. Twenty test code. The product carries a 10:1 guard-to-prose ratio, the guards are the most-churned area in the repo, and the Todo queue is dominated by guard-hardening work about the guards themselves.

Three costs, in causal order:

1. **The distribution is a hand-rolled package manager.** `registry.yaml` versions every file individually; every ticket bumps its touched files plus the registry self-version (85 commits/14d to one file); the freshness hook, `/update-guidance`, `BOOTSTRAP.md`, and the consumer lock-file exist to move those versions around. The self-version is a monotonic field at a shared append point, and it collides on concurrent work exactly the way `CHANGELOG.md` did before ADR 0010's #267 — observed live on #461 the day after #443 shipped a vigilance rule against it.
2. **The prose is a reference graph.** 161 instances of one guidance file citing another, in chains (command → skill → provider skill → `CONTEXT.md` field) with partial restatements at the hops. #456 catalogued the failure class: divergence appears exactly where prose was duplicated rather than pointed at — a verdict (`DEFER`) handled by the orchestrator that the reviewer's own guidance could never emit.
3. **The guards grew to police 1 and 2.** Version-parity triples, pointer guards, restatement sweeps, positional prose pins. Each is individually justified; collectively they are an immune system larger than the organism, now growing guards over guards. Nothing in the current shape stops that growth, because its subjects — per-file versions and duplicated prose — keep regenerating work.

If nothing is done: the overhead persists and compounds. Every guidance edit pays version fan-out, reference maintenance, and guard updates; the reconcile churn measured on the gate-redo question (15 reconciliation merges per 73 shipped commits; four tickets paying twice) is one downstream symptom.

The trajectory context: `harness-as-tool` (v3) removed the orchestrator; ADR 0015 (v4) removed the runtime. This is the same move applied to the remaining machinery — v5 removes the package manager.

## Options

**Option A — Status quo plus targeted fixes.** Build #479 (derive the registry self-version), #480 (reconcile before certifying), keep culling ad hoc. · *Trade-offs:* smallest step, no distribution risk. But it optimises the hand-rolled package manager rather than questioning it: the per-file fan-out, the reference graph, and the guard growth all continue.

**Option B — Plugin distribution only.** Package as a plugin, delete the registry machinery, keep the internal coupling and the guard suite as they are. · *Trade-offs:* kills cost 1 outright (one version at release; no self-version to collide — supersedes #479 by construction). But 118 prose guards keep their subjects, so the dominant churn survives. Viable as a first step, not as the destination.

**Option C — Full decoupling, discovery only.** Every skill, command, and agent freestanding; no file references another; agents find what they need from descriptions; the always-on context shrinks toward zero. · *Trade-offs:* maximally simple to maintain, and genuinely right for the craft skills — nothing needs to point at `systematic-debugging` for it to be found. Rejected as stated, on two grounds. **Contracts:** builder and reviewer must agree on wire formats — verdict vocabulary, ticket states, hold labels, assurance levels, the tree-oid binding. Discovery cannot make two independently-loaded files agree; #456's orphaned `DEFER` is precisely this bug, and full decoupling recreates it everywhere while deleting the guards that caught it. **Governance:** skills are pull, and pull is probabilistic. A stop rule cannot depend on a skill happening to trigger.

**Option D — Plugin + spine + hydration + inventory collapse + guard cull.** The moves together: plugin distribution (from B); C's freestanding leaves, with the contract placed where it cannot fail to load — the always-on spine; the installer becomes an init command that hydrates a repo; the command/agent/template inventories collapse to what earns its keep; the guard suite is culled to the classes whose subjects survive. · *Trade-offs:* the largest change, but the only option that removes the *subjects* of the overhead rather than the symptoms, and each move is separately reversible up to the teardown step.

## Recommendation

**Option D.** This is `engineering-principles`' simplicity-over-cleverness applied to the repo itself: the complexity being deleted is real machinery (a versioning scheme, a reference graph, 100-odd prose guards), and what replaces each piece is smaller and already exists in the ecosystem. The cull is the payoff and must be decided explicitly — without it, this ships a plugin dragging 35k lines of prose-readers behind it.

### The spine: one always-on file, not a hub skill

An earlier draft placed the shared contract in a `lifecycle` hub *skill*. That is the wrong loading class. Skills are conditional — loaded on demand, by description match — while the lifecycle contract is needed in essentially **every working session**: any session that opens a ticket, builds, reviews, or ships speaks its vocabulary. The only sessions that do not are one-off questions outside the lifecycle, and the cost there is a few unused KB of context — the right price for a contract that can never fail to load. So the contract goes in the file that is loaded at start, unconditionally: the spine (`CLAUDE.md`, and `AGENTS.md` compiled from the same source).

The spine also absorbs `CONTEXT.md`. What `CONTEXT.md` holds — stack, commands, branches, tracker, layers — is the repo's executive summary, which is exactly the corpus that must be loaded every time; keeping it in a second always-read file next to the first is a division without a difference. The spine's shape, hydrated per repo:

1. **Iron laws** — test-first; a measurable criterion needs a measuring test; no completion claim without fresh gate evidence; builder does not write the as-built record.
2. **The contract** — lifecycle steps, the six ticket states, hold labels + assignment semantics, assurance levels, verdict vocabulary (PASS / FAIL / DEFER), the tree-oid / gate-marker binding, tracker dispatch — and the **isolation norm**: many agents work these repos concurrently, so nobody builds on a shared branch; every change works isolated, ticketed or not.
3. **Repo cliff notes** — the machine-readable config block hooks parse today from `CONTEXT.md` (commands, branches, tracker, layers, paths), retargeted, plus the prose summary of what the repo is.

**Not every change is a ticket.** The enforcement layer is already ticket-agnostic — the gate marker names a *tree*, and no hook asks for an issue id — so the contract states the fast lane plainly: a small fix takes the same isolation and the same gate, and ships without a ticket. A ticket is filed when the work deserves a record: it changes documented behaviour, spans commits, or needs independent review. Today's prose ("the tracker issue is the front door") stated a ceremony the mechanics never required; the spine aligns the stated contract with the enforced one. **No command carries the fast lane** — a fast lane behind a slash command is ceremony reintroduced. The norm and the gate bind mechanically through the hooks, the worktree mechanics load on demand, and the conversation is the interface: "fix X" is the whole invocation.

Target ≤250 lines total. Skills become depth behind the spine: the spine states *that* reviews are two-stage and bounded; `review-discipline` holds *how*. Leaves may assume the spine (it is guaranteed loaded — zero hops) and reference nothing else. The spine is repo-owned after hydration; `/harness:init --refresh` regenerates the generated sections (laws + contract) in place after a plugin update, preserving the repo-values section — the one drift surface this design accepts, and the refresh command is its remedy.

### The how/what pattern: generic method over evolving assets

For the build/design/operate triad — `engineering`, `architecture`, `infrastructure` — each skill splits into a generic *how* and an evolving *what*:

| Layer | Owner | Content | Update path |
|---|---|---|---|
| Skill body — the how, with the principles **stated** | plugin | the method, plus the one-liner working vocabulary (a dozen lines) | plugin release |
| Plugin asset — the universal what, **argued** | plugin | elaboration, examples, learned cases — the corpus with room to grow | plugin release; this is where the system learns across repos |
| Repo asset — the local what | repo, seeded by `init` | this repo's principles, decisions, and infrastructure reality | the repo's own lifecycle |

The pattern is already running in this repo, twice. `review-discipline` carries `references/craft.md` — the skill body is the method, and craft.md is the learning asset that #443 *appended to* when the counterfeit-delimiter and version-collision classes were discovered. And `architecture` is the pattern by another name: the skill is the how, and the repo-owned architecture-principles spec (plus its decisions) is the what. This proposal names the pattern and completes the triad rather than inventing it.

Two boundaries hold the pattern honest. **The body is never an empty pointer:** the principles stay *stated* in the skill (they are working vocabulary, needed on every load); the asset carries the *argument* — rationale, examples, accumulated cases — opened when a principle is contested or a hard call is being made. And **ownership splits by file, not by section:** the spine needs generated-plus-repo sections because it must be one file; assets have no such constraint, and the repo-owned what-documents are heavily edited (decisions accrete, infrastructure changes), so mixed-ownership files would turn every `--refresh` into a merge. Two files, clean owners, the skill reads both.

Restraint: three instances is a pattern; six is a reorganization. `ux-design`/`design-system` rhyme with it (the design directory is already a repo-owned what), but they wait for the first `/assess` after the triad ships.

### Target inventory

**One plugin, `harness`, one semver, bumped at release** — the promotion of ADR 0003, whose version bump and changelog fold (ADR 0014) happen there. No file-level versions, no `guidance:` headers, no registry, no lock. Commands are runtime-namespaced (`/harness:build`); in practice only `init` needs the prefix spoken, to avoid the native `/init`.

**Skills — 17 → 13 freestanding leaves** (the contract having moved to the spine):

| Skill | What it is | Disposition |
|---|---|---|
| `spec-driven-development` | The lifecycle spine as prose | **Absorbed into the spine** (contract section) |
| `tracker` | Backend-neutral tracker protocol: operations, states, holds, filing | **Absorbed into the spine** (states/holds/dispatch) — recipes stay in providers, so spine → provider is the only hop |
| `linear` / `github-issues` | Provider recipes (API mechanics per backend) | Keep, freestanding |
| `review-discipline` | Two-stage review, finding 2×2, final-evidence ordering, stop rule; `references/craft.md` is the pattern's precedent | Keep; verdict vocabulary moves to spine |
| `code-quality` | Scope discipline, structure, verification gate | **Merge into `engineering`** with `engineering-principles` and `test-driven-development` — the co-loading test: no agent builds without all three, and `dev.md`'s mandatory reading list is the evidence they were one load wearing three names |
| `engineering-principles` | The durable design principles | ↑ merged; principles stay *stated* in the body, move *argued* into the plugin asset (the how/what pattern's build leg) |
| `test-driven-development` | The iron law, expanded — watch it fail for the right reason, red-green-refactor | ↑ merged — the law's salience lives in the spine unconditionally; the skill only ever carried the craft, which belongs with the rest of the building craft |
| *(new)* `infrastructure` | The operate leg: environments, what a gate means at each boundary, promotion discipline, CI/CD movement, release mechanics | **Add** — this how is currently smeared across ADR 0003, `/promote`, and `promotion-step.sh` with no skill home; its repo asset (seeded from the `infrastructure.md` template) records the actual topology, environments, and services |
| `spec-authoring` | The craft of proposals / change specs / as-built records | Keep; gains the spec templates as assets |
| `systematic-debugging` | Reproduce → isolate → fix → prove | Keep — fires conditionally (on a failure), which is what the trigger mechanism is for |
| `writing-quality` | Prose standards | Keep |
| `architecture` | The design leg: how decisions are made and where they are recorded | Keep — already instantiates the pattern (skill = how; repo-owned architecture-principles spec = what) |
| `ux-design` | Designing user-facing surfaces | Keep |
| `design-system` | Using a design system without degrading it (layer-gated) | Keep; gains the design-system scaffold as an asset |
| `assessment-craft` | The steward's finding bar and severity method | Keep |
| `work-discovery` | How the unattended loop picks its next ticket | Keep |
| `worktree-isolation` | Workspace mechanics for any change | Keep, reframed — the *norm* (concurrent agents, nobody on a shared branch) moves to the spine, where it binds unconditionally, ticket or not; this leaf keeps the mechanics. Deliberately **not** folded into `/build`: the fast lane needs it too |

**Commands — 13 → 9.** The lifecycle collapses onto `/build`: it already runs the whole arc, and the attended path is the same arc watched, not a different arc.

| Command | What it does | Disposition |
|---|---|---|
| `/build <TICKET>` | End-to-end driver: worktree, change spec, implement test-first, gate, independent review, ship, close | **Keep — the workhorse** |
| `/start` | The front half of `/build` (workspace + build to review-ready), attended | **Fold into `/build`** |
| `/ship` | The tail of `/build` (integrate + close after PASS), incl. the base-drift rule | **Fold into `/build`** — #480's ordering fix lands in `/build`'s ship step instead |
| `/review` | Run the independent final gate on the current branch | **Keep** — the one stage with standalone value: re-binding a verdict, or reviewing work `/build` didn't produce. (Contestable — fold if unused.) |
| `/routine` | One unattended tick: discover → build → ship, with the standing dev-push authorisation and the hold rule | Keep — the scheduled entry point |
| `/propose <idea>` | Work an unconfirmed/large idea to a decision, then spawn tickets | Keep |
| `/bug <desc>` | Capture a defect straight to Todo (adjustment template) | **Merge with `/tweak` into `/capture`** — same template, same destination; the escape-hatch difference is one paragraph that moves into the template |
| `/tweak <desc>` | Capture a small upgrade straight to Todo, with a `/propose` escape hatch | ↑ merged |
| `/decision` | Interactive sweep draining tickets held for operator input: present each, capture the call, write it into the spec, release | **Merge into `/digest`** — report the holds, then offer to drain them; one operator console instead of two commands whose split ("read" vs "act") nobody remembers |
| `/digest` | Read-only morning report: holds, overnight outcomes, proposals, errands | ↑ absorbs `/decision` |
| `/promote` | Drive a promotion between role branches: merge, gate, publish | Keep (simplified by the staging skip below) |
| `/assess <scope>` | Steward pass over code or architecture; drain proposals with the operator | Keep |
| `/update-guidance` | Pull upstream guidance into the repo | **Delete** — plugin update replaces it |
| `/harness:init` *(new)* | Hydrate a repo: spine, gate, settings, specs scaffold; `--refresh` after updates | **Add** — replaces `BOOTSTRAP.md` |

**Agents — 5 → 4:**

| Agent | What it does | Disposition |
|---|---|---|
| `dev` | Implements test-first in a worktree, in scope, hands off with evidence | Keep |
| `reviewer` | Independent final gate; records the as-built spec; binds the verdict to the tree | Keep — the separation-of-concerns cornerstone |
| `architect` | Design sub-agent for complex work: produces a design (with test strategy + security section), never code; write-capable but tool-restricted, worktree-isolated | Keep — its frontmatter carries real config (tool limits, isolation) a skill cannot; `/build`'s complex path dispatches it |
| `steward` | Read-only periodic assessment; reports cross-file cumulative patterns; does not fix | Keep |
| `researcher` | Read-only grounding pass before the change spec: verified facts at `path:line`, decisions surfaced, open questions, returned as a brief | **Delete** — host-native read-only agents do the dispatch; the grounding *schema* already lives in `spec-authoring` → Grounding and `change.md` already names self-grounding as the fallback. What earns keep is the schema, not the persona. (Contestable.) |

**Hooks — 7 → 5:**

| Hook | What it does | Disposition |
|---|---|---|
| `gate-evidence-guard.js` | Stop hook: refuses ending a turn that claims completion with no fresh marker over the worked trees | Keep — enforcement core |
| `push-target-guard.js` | Refuses `git push` targeting a protected branch unless a fresh marker covers the pushed tree | Keep — enforcement core |
| `git-push-guard.js` | Refuses history-rewriting pushes (`--force`, `+refspec`, hidden in wrappers) unconditionally | Keep — orthogonal to the marker, cheap |
| `prompt-guard.js` | Advisory: flags injection-shaped content in Write/Edit | Keep — low-cost security nudge |
| `workflow-guard.js` | Advisory: nudges when source is edited on a shared branch / outside a worktree | Keep — the worktree-isolation nudge |
| `context-monitor.js` | Advisory: transcript growing near the context window, commit and hand off | **Delete** — the host manages context natively now |
| `guidance-freshness.js` | Advisory: version-stamp / mirror / registry drift | **Delete** — dies with the registry |

Hooks are code: they keep their real tests (the surviving class), and they are Claude-side. Codex sessions run without them — acceptable, since Codex never had them and the authoritative controls (server-side branch protection, CI gate output) are runtime-independent.

**Templates — 12 → 9, re-homed as assets:**

| Template | What it is | Disposition |
|---|---|---|
| `change.md` | The change-spec structure (ticket body): Problem, Approach, Grounding, Design, ACs, out-of-scope | Keep → `spec-authoring` asset |
| `adjustment.md` | Capture-optimized front half of a change spec, for `/bug`/`/tweak` at the moment of noticing | **Merge into `change.md`** as its capture mode — one ticket template; capture fills the front sections, `/build` extends with Grounding/Design. Matches the `/capture` merge |
| `proposal.md` | Proposal spec structure | Keep → `spec-authoring` asset |
| `feature.md` | As-built feature record (`feature_specs` on) | Keep → `spec-authoring` asset |
| `architecture.md` | Architecture-principles reference spec scaffold | Keep → `spec-authoring` asset |
| `decision.md` | Embeddable four-part decision block | Keep → `spec-authoring` asset |
| `assessment.md` | The steward's report format + retention rule | Keep → `assessment-craft` asset |
| `design-system.md` | Contract for standing up a layered design system | Keep → `design-system` asset |
| `infrastructure.md` | Reference spec for operational reality (domains, hosting, services) | Keep → the seed for the `infrastructure` skill's **repo asset**, written by `init` |
| `size-guard.md` | Ready-to-adopt test enforcing the 500-line justification tripwire mechanically | Keep → `engineering` asset (it is a shipped test, admission class (c)) |
| `CONTEXT.template.md` | The `CONTEXT.md` scaffold | **Retire** — folds into the spine template (`init` asset) |
| `generate_codex_artifacts.py` | Generates `.codex/` agents, skills, and commands from the canonical files | Move to `scripts/` as the release-time compile step |

**Scripts:** `verify.sh`, `gate_marker.py`, `mutate.py` (retargeted at surviving guard classes), `promotion-step.sh` (adjusted below) keep. `check_landing_page_guidance.py` and `build_design_tokens.py` follow the landing-page decision (D8) — the former reads `registry.yaml` and cannot survive teardown unchanged.

**What a consuming repo holds after `/harness:init`:** the spine (`CLAUDE.md` + compiled `AGENTS.md`), `scripts/verify.sh` + `gate_marker.py`, `.claude/settings.json` (hook wiring), `specs/{proposals,features,decisions}/` scaffold. Five things, all repo-owned. No lock, no registry, no `CONTEXT.md`.

**What stays a repo (the source):** the plugin source and marketplace manifest, the compile step, the gate scripts and `mutate.py`, the surviving tests, `specs/` (the product's memory), `README`, `CONTRIBUTING`. The `process/harness.md` + three byte-identical mirrors arrangement is retired: one spine source, hydrated per repo, compiled per runtime.

### Codex is a secondary surface, compiled not maintained

Codex consumes `AGENTS.md` natively and handles the same skill and agent file shapes; commands port as a skill type (the existing workaround), and `generate_codex_artifacts.py` already emits `.codex/` agents, skills, and commands — the compile step extends it rather than starting cold. The one genuine gap is hooks, and it is acceptable: Codex sessions never had them, and enforcement of record is server-side. This proposal therefore does **not** gate on a Codex parity spike; the compile work (chunk 3) carries a scratch-repo verification as an ordinary check, and a disappointing result narrows the Codex surface rather than stopping the proposal.

### The guard cull, by admission rule rather than by list

A guard may assert:

- **(a) behavior of executable code** — hooks, gate scripts, the compile step, the init command;
- **(b) a property of the spine** — the one text whose vocabulary other things depend on (e.g. #456's verdict-vocabulary guard, retargeted: leaves name no verdict outside the spine's set);
- **(c) integrity of shipped assets** — templates carry their placeholders; compile output parses; the size-guard reference test runs;
- **(d) frontmatter compliance** — skills/agents/commands carry valid frontmatter (name, description, tool lists), specs carry valid frontmatter (status enums, dates). Structured and machine-checkable — schema, not prose.

Everything asserting prose-about-prose — version parity, pointer targets, restatement agreement, positional pins — dies **with its subject, in the same change that removes the subject, never before**. Expected order: 138 modules → ~40, ~35k lines → ~10k. The rule is recorded in the ADR so future guards are admitted against it rather than by momentum.

### Skip staging in this repo

`dev → staging → main` is ADR 0003's general topology, but staging is a deployment concept and this repo deploys nothing — for the harness it is a third gate run and a third merge that verify the same trees. Branch roles are already per-repo config: the harness declares `integration: dev`, `release: main`; `/promote` and `promotion-step.sh` drive `dev → main`. Repos that ship to staging environments keep all three roles — the topology becomes what it already almost is: configuration, and with the `infrastructure` skill it gains its natural home — the harness's own infra asset records the two-branch topology as its first entry, with the prose for *why* attached instead of a bare YAML key.

### How the system comes together

- **Install:** add the marketplace, install `harness`, run `/harness:init` → spine, gate, settings, scaffold.
- **Daily work:** ticket → `/harness:build` (attended or via `/routine` unattended); the spine binds the laws and the contract in every session; agents pull craft skills by description; the gate writes the tree marker; the hooks enforce evidence exactly as today.
- **Update:** plugin update, then `/harness:init --refresh` regenerates the spine's generated sections.
- **Release:** promotion `dev → main` bumps the plugin version, folds the changelog from commit bodies, runs the compile step, publishes.
- **Dogfood:** the harness repo installs its own plugin from source; the process governing this repo is the shipped artifact itself.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| **D1 — Distribution: plugin + marketplace, or keep the installer?** Rec: plugin. Registry, freshness hook, `/update-guidance`, `BOOTSTRAP.md`, and the lock all delete. | user | ADR 0016 |
| **D2 — The contract lives in the always-on spine (absorbing `CONTEXT.md`), not a conditional skill — and it states the fast lane?** Rec: yes to both. The lifecycle is needed in every working session; only one-off Q&A pays unused context, and that price is right for a contract that cannot fail to load. The fast lane (small fixes ship with the same isolation and gate but no ticket) is a real contract change from "the issue is the front door" and is called out as such — the enforcement layer never required the ticket; the prose did. Accepts the spine-refresh drift surface (`init --refresh` is the remedy). | user | ADR 0016 |
| **D3 — The how/what pattern, applied to the triad only.** `engineering`, `architecture`, `infrastructure` each split into a generic skill body, a plugin asset (the universal argument, where learning accretes), and a repo asset (the local reality, seeded by `init`). `ux-design`/`design-system` wait for the first `/assess` after the triad ships. | user | ADR 0016 |
| **D4 — Inventory dispositions.** Approve the fold/delete columns: skills 17→13 (`engineering` absorbs `code-quality`, `engineering-principles`, and `test-driven-development`; `infrastructure` added; `worktree-isolation` kept as mechanics with its norm in the spine), commands 13→9 (`start`/`ship` into `build`; `bug`+`tweak`→`capture`; `decision` into `digest`; `update-guidance` deleted; `init` added), agents 5→4 (`researcher` deleted, `architect` kept), hooks 7→5, templates 12→9 (`adjustment` into `change`; `CONTEXT.template` retired). Contestable items are marked in the tables — `/review` kept vs folded, `researcher`, `architect`, the TDD merge. | user | ADR 0016 |
| **D5 — Guard admission rule (a–d) and the cull.** The payoff decision — without it D1–D4 relocate the overhead. | user | ADR 0016 |
| **D6 — This repo skips staging** (`dev → main`), recorded as the first entry in the harness's own infrastructure asset; the three-role topology stays available as configuration for repos with staging environments. | user | ADR 0003 (amended in place) + the infra asset |
| **D7 — In-flight work disposition.** Swept 2026-08-17 on the operator's direction: closed as superseded or folded into the v5 chunks — #479 (the plugin *is* the fix), #480 (its ordering fix lands in chunk 2's `/build`), #471/#475/#476 (guards whose subjects chunk 1 deletes), #473/#477/#478 (folded into chunk 4, named there), #474 (folded into the `infrastructure` skill, chunk 2). Kept: #450 (standing proposals ledger), #464 (release-chain health, operator-held — not v5 work), #468 (held retention edge; its surface survives), #472 (craft patterns — content for the surviving review-discipline asset, built post-v5 under the new process). | user | the tickets |
| **D8 — The landing page.** `docs/index.html` and its drift guards read `registry.yaml`, which D1 deletes. Retire the page, or re-point it at the plugin manifest? | user | feature spec |

## Implementation: the `v5` branch, four chunks

This is a restructure of guidance, not production software, so it does **not** run through the assurance machinery it retires: no per-chunk change specs, no per-ticket review cycles, no per-file version bumps, no per-increment shippability. Paying the old process's price to delete the old process is the one clearly absurd spend. What still binds: the **gate** — green at the end of every chunk, which chunk 1 makes possible by deleting guards *with* their subjects (a chunk that deletes prose but keeps its guards can never be green, so the ordering is forced, not chosen); the **hooks** — tree-based and branch-agnostic, they stay armed throughout; and the **operator reviews the `v5` merge itself**, which is where the assurance for the whole restructure actually lives.

All work on branch `v5`, cut from `dev`. Four chunks:

1. **Delete.** Everything leaving, and the guards whose subjects leave, in the same chunk: `registry.yaml` + every `guidance:` header, `guidance-freshness.js` + `context-monitor.js`, `/update-guidance`, `BOOTSTRAP.md`, the three process-doc mirrors, `/start` `/ship` `/bug` `/tweak` `/decision` as files, `researcher.md`, `CONTEXT.template.md`, the landing page per D8 — and the prose-guard bulk of `tests/unit/`. Gate green by chunk end over what remains.
2. **Dogfood minimum.** The spine (laws + contract + fast lane + config block; hooks retargeted from `CONTEXT.md`); plugin packaging and namespacing, the repo installing its own plugin from source; the triad (`engineering` merged incl. TDD, `infrastructure` born — absorbing `/promote`'s back-merge discipline, closing the #474 gap — with both repo assets seeded); the collapsed commands (`/build` absorbing start/ship *including #480's reconcile-before-certify ordering*, `/capture`, `/digest` absorbing `/decision`); `/harness:init` with `--refresh`.
3. **Dogfood and finish.** Run real work through the new shape — the remaining v5 work is itself the dogfood. Codex compile (`generate_codex_artifacts.py` → `scripts/`, `AGENTS.md` emission, a scratch-repo check). Flesh the repo assets, including the two-branch topology as the harness infra asset's first entry (D6) with `promotion-step.sh` adjusted. Fix friction where found.
4. **Audit and polish.** The guard pass under D5's admission rule, with before/after counts recorded in ADR 0016; `mutate.py` retargeted at the survivors; the folded backlog items on surviving code — #477 (`pushd`/`--git-dir` slip past the push guard's directory tracking), #478 (the gate preflight never probes `node`, so a broken interpreter reads as a red tree), #473 (a tree-keyed lockfile as `mutate.py`'s first refusal); the consumer migration note; then promote and publish the first plugin release — clearing #464's waived red on the way through the chain.

## Risks / unknowns

- **Spine refresh drift.** The spine is repo-owned after hydration, so a plugin update does not rewrite it; a consumer that never runs `init --refresh` carries a stale contract. Bounded: the laws and contract change rarely by design, and the refresh is one command. The generated/repo-owned boundary must be mechanically obvious in the file.
- **Spine scope creep.** The one always-loaded file is the tempting home for everything; every addition taxes every session's context. The ≤250-line target and a class-(b) guard on its section inventory are the counterweight; spine growth is the metric for the first `/assess` after shipping.
- **Asset bloat.** The plugin assets exist to grow, which is also how they decay into encyclopedias agents skip. Two counterweights, both proven on craft.md: the asset states its own admission rule at its head, and the skill body names *when* to open it — the body is the working surface, the asset is the argument.
- **The fast lane could leak.** "Small fix, no ticket" invites scope drift — a behaviour change shipping unrecorded. The bound is stated in the contract (documented-behaviour changes, multi-commit work, and review-needing work are tickets), the gate still binds mechanically either way, and the steward's pass is where leakage would surface.
- **Plugin runtime maturity.** Consumers need plugin-capable hosts; marketplace hosting and private access need checking per consumer. A consumer that cannot run plugins keeps the current install until it can — per-consumer migration, not flag-day.
- **One version flattens per-file pinning.** A consumer today can hold one file back via the lock; under the plugin they take releases whole, and a consumer needing a divergent skill forks it locally (repo-local files layer over plugin content). Accepted as the point.
- **The cull could delete a guard that was catching something real.** Mitigations: cull by class with the subject's removal (never a standalone deletion pass before the subject dies), keep the mutation instrument over survivors, record every culled class in the ADR with what replaced its protection — usually, that the subject no longer exists to drift.
- **Codex verification could disappoint.** Not gating: a negative scratch-repo result narrows the Codex surface (spine + skills, no command porting) rather than stopping the proposal. Hooks never worked there and are not the enforcement of record.
- **The v5 merge is one large diff.** No per-increment review means the assurance concentrates at the end: the operator reviews the landing merge, and the branch has been dogfooding itself since chunk 2 — the restructure is validated by being built under the process it installs. Accepted deliberately; the alternative (running the retiring assurance machinery over its own deletion) was the cost this plan exists to avoid.
- **Deletion could outrun replacement.** Chunk 1 removes the mirrors and `CONTEXT.template.md` before chunk 2 writes the spine, so between chunks the repo's own always-on guidance is thin. Bounded: the work is one branch driven by one session with this proposal in hand, and `dev` remains untouched until the merge.
