<!-- guidance:template-proposal@0.1.3 -->
---
proposal: plugin-shaped-guidance
status: under-decision   # draft | under-decision | accepted | shipped | rejected | split
date: 2026-08-17
related: [0015-harness-v4-thin-verification-layer, guidance-system, harness-as-tool, rebase-stable-certification]
---

# Proposal: Ship the guidance as a plugin — one version, one hub, hydrated repos, and a guard cull

> Stop being a hand-rolled package manager for cross-referenced prose. Package the surface as a Claude Code plugin (skills, commands, agents, hooks — one version, bumped at release), compile the Codex surface from it, decouple every leaf file from every other except one small contract hub, replace the installer with a hydration command, and delete the guard classes whose subjects those moves remove.

## Problem / motivation

ADR 0015 retired the runtime and left three parts: the guidance surface, the gate, and the guards. The activity since then says the thin verification layer is not yet thin. Measured over the 14 days to 2026-08-17, on `dev`:

| Surface | Lines | Files | 14-day commits |
|---|---|---|---|
| skills + commands + agents (the product) | ~3,400 | 35 | ~90 |
| hooks + scripts (the enforcement) | ~4,650 | 14 | 39 |
| `tests/unit/` (the guards) | ~35,500 | 138 | **205** |
| `registry.yaml` (the versioning) | — | 1 | **85** |

Of the 138 guard modules, **118 read prose** — parity between a file's header and its registry row, pointers landing where they claim, restatements agreeing with their owner, sentences sitting inside the right paragraph. Twenty test code. The product carries a 10:1 guard-to-prose ratio, the guards are the most-churned area in the repo, and the current Todo queue is dominated by guard-hardening work about the guards themselves.

Three costs, in causal order:

1. **The distribution is a hand-rolled package manager.** `registry.yaml` versions every file individually; every ticket bumps its touched files plus the registry self-version (85 commits/14d to one file); the freshness hook, `/update-guidance`, `BOOTSTRAP.md`, and the consumer lock-file exist to move those versions around. The self-version is a monotonic field at a shared append point, and it collides on concurrent work exactly the way `CHANGELOG.md` did before ADR 0010's #267 — observed live on #461 the day after #443 shipped a vigilance rule against it.
2. **The prose is a reference graph.** 161 instances of one guidance file citing another, in chains (command → skill → provider skill → `CONTEXT.md` field) with partial restatements at the hops. #456 catalogued the failure class: divergence appears exactly where prose was duplicated rather than pointed at — a verdict (`DEFER`) handled by the orchestrator that the reviewer's own guidance could never emit.
3. **The guards grew to police 1 and 2.** Version-parity triples, pointer guards, restatement sweeps, positional prose pins. Each is individually justified; collectively they are an immune system larger than the organism, now growing guards over guards (mutation-proving the killers of killers). Nothing in the current shape stops that growth, because its subjects — per-file versions and duplicated prose — keep regenerating work.

If nothing is done: the overhead persists and compounds. Every guidance edit pays version fan-out, reference maintenance, and guard updates; the reconcile churn measured on the gate-redo question (15 reconciliation merges per 73 shipped commits; four tickets paying twice) is one downstream symptom.

The trajectory context: `harness-as-tool` (v3) removed the orchestrator; ADR 0015 (v4) removed the runtime. This is the same move applied to the remaining machinery — v5 removes the package manager.

## Options

**Option A — Status quo plus targeted fixes.** Build #479 (derive the registry self-version), #480 (reconcile before certifying), and keep culling ad hoc. · *Trade-offs:* smallest step, no distribution risk. But it optimises the hand-rolled package manager rather than questioning it: the per-file fan-out, the reference graph, and the guard growth all continue. The 205-commits-per-fortnight guard churn is untouched.

**Option B — Plugin distribution only.** Package as a plugin, delete the registry machinery, keep the internal coupling and the guard suite as they are. · *Trade-offs:* kills cost 1 outright (one version at release; no per-ticket stamps; no self-version to collide — supersedes #479 by construction). But 118 prose guards keep their subjects: the reference graph still needs pointer and restatement policing, so the dominant churn survives. Half a fix that forecloses none of the rest — viable as a first step, not as the destination.

**Option C — Full decoupling, discovery only.** Every skill, command, and agent freestanding; no file references another; agents find what they need from descriptions; `CLAUDE.md` shrinks toward zero. · *Trade-offs:* maximally simple to maintain, and genuinely right for the craft skills (TDD, debugging, writing — nothing needs to point at them). Rejected as stated, on two grounds. **Contracts:** builder and reviewer must agree on wire formats — verdict vocabulary, ticket states, hold labels, assurance levels, the tree-oid binding. Discovery cannot make two independently-loaded files agree; #456's orphaned `DEFER` is precisely this bug, and full decoupling recreates it everywhere while deleting the guards that caught it. Freestanding-by-duplication is worse: it restores restatement drift with the immune system off. **Governance:** skills are pull, and pull is probabilistic. The load-bearing rules are in `CLAUDE.md` "so they bind even if no skill file gets opened" — an agent that never triggers `review-discipline` does not know a review-cycle budget exists. A stop rule cannot be probabilistic.

**Option D — Plugin + hub-and-spoke + hydration + guard cull.** The four moves together: plugin distribution (from B); coupling reduced to one small contract hub plus freestanding leaves (C's insight, bounded by C's failure); the installer becomes an init command that hydrates a repo; and the guard suite is culled to the classes whose subjects survive. · *Trade-offs:* the largest change, and it stakes the Codex story on a compile step that must be proven before the rest is worth building. But it is the only option that removes the *subjects* of the overhead rather than the symptoms, and each move is separately reversible up to the teardown step.

## Recommendation

**Option D**, gated on a Codex-parity spike, sequenced so the teardown comes last. This is `engineering-principles`' simplicity-over-cleverness applied to the repo itself: the complexity being deleted is real machinery (a versioning scheme, a reference graph, 100-odd prose guards), and what replaces each piece is a smaller thing that already exists in the ecosystem (a plugin version, a description index, a hook). The cull is the payoff and must be decided explicitly — without it, Option D ships a plugin dragging 35k lines of prose-readers behind it.

### Target shape

**One plugin, `harness`, one semver, bumped at release** (the `dev → staging → main` promotion of ADR 0003 — the topology and `promotion-step.sh` survive unchanged; the version bump and changelog fold happen there, per ADR 0014's commits-are-the-entries rule). No file-level versions, no `guidance:` headers, no registry, no lock. Plugin commands are namespaced by the runtime (`/harness:start`), which retires the command-collision protocol in the process doc.

**Skills — 17 today → 15, one of them the hub:**

| Skill | Disposition |
|---|---|
| *(new)* `lifecycle` — **the hub** | The one file leaves may reference. Owns the shared contract: the task lifecycle, the six ticket states, hold labels + assignment semantics, assurance levels, verdict vocabulary (PASS/FAIL/DEFER), the tree-oid/gate-marker binding, and the tracker dispatch rule. Target ≤200 lines. |
| `spec-driven-development` | Absorbed into the hub — it *is* the lifecycle spine. |
| `tracker` | Protocol content absorbed into the hub (states, holds, dispatch); dies as a separate file so hub→tracker→provider never chains. |
| `linear`, `github-issues` | Freestanding provider recipes, dispatched from the hub. |
| `review-discipline` | Freestanding craft; verdict vocabulary moves to the hub; keeps `references/` as assets. |
| `code-quality` + `engineering-principles` | Merged into one building skill (principles are what building is measured against; two files today, one subject). |
| `spec-authoring` | Freestanding; gains the spec templates as skill assets. |
| `test-driven-development`, `systematic-debugging`, `writing-quality`, `architecture`, `ux-design`, `design-system`, `assessment-craft`, `work-discovery`, `worktree-isolation` | Freestanding leaves, unchanged in role. Cross-references removed; discovery carries them. |

**Commands — 13 today → 13:** keep `propose`, `bug`, `tweak`, `start`, `review`, `ship`, `build`, `promote`, `decision`, `routine`, `digest`, `assess`; **delete `update-guidance`** (plugin update replaces it); **add `init`** — the hydration command that replaces `BOOTSTRAP.md`.

**Agents — 5, unchanged:** `dev`, `reviewer`, `architect`, `steward`, `researcher`. Descriptions become load-bearing (they are what discovery matches on) and get written to that standard.

**Hooks — 7 today → ~4:** `gate-evidence-guard` and `push-target-guard` are the enforcement core and ship in the plugin. `guidance-freshness` dies with the registry. `context-monitor`, `git-push-guard`, `prompt-guard`, `workflow-guard` are audited against the plugin shape at build time — kept only where still earning their event (breakdown item, not decided here).

**Templates — 12 today → skill assets + init assets:** spec templates (`proposal`, `change`, `adjustment`, `feature`, `decision`, `architecture`, `assessment`, `infrastructure`, `design-system`, `size-guard`) become `spec-authoring` assets; `CONTEXT.template.md`, the spine stub, a `verify.sh` template, and a settings template become `init` assets; `generate_codex_artifacts.py` moves to `scripts/` as the compile step.

**What a consuming repo holds after `/harness:init`** — the hydration answer to "could CLAUDE.md and the repo structure be captured in skills":

- `CLAUDE.md` — a **stub, not zero** (~50 lines): the iron laws (test-first; measurable criterion needs a measuring test; no completion claim without fresh gate evidence), a pointer to the `lifecycle` hub, and the repo's layer switches. Always-on because governance is push; everything else is pull.
- `AGENTS.md` — compiled for Codex from the same source (below).
- `CONTEXT.md` — per-repo values (stack, commands, branches, tracker, layers). Cannot live in the plugin by definition; hydration writes it, the repo owns it.
- `scripts/verify.sh` — the repo's gate, instantiated from the template; `gate_marker.py` beside it.
- `.claude/settings.json` — hook wiring.
- `specs/{proposals,features,decisions}/` — scaffold for the repo's own memory.

**What stays a repo (the source):** the plugin source and marketplace manifest; the compile step; the gate scripts and `mutate.py`; the surviving tests; `specs/` (proposals, ADRs, features, assessments — the product's memory is repo content, not overhead); `README`, `CONTRIBUTING`. The `process/harness.md` + `CLAUDE.md`/`AGENTS.md`/`GEMINI.md` byte-mirror arrangement is retired: one spine template, hydrated per repo, compiled per runtime.

**Codex parity is a compile target, not a parallel surface.** `templates/generate_codex_artifacts.py` (at 0.3.0) already generates `.codex/` agents, skills, and commands from the canonical files — the seed of the build step. At plugin build time it emits the Codex artifacts: an `AGENTS.md` index (push — Codex has no skill runtime, so the index tells it what to read and when) plus the leaf files. The spike must prove a Codex session actually follows the index into the right leaves before anything else in this proposal is built.

**The guard cull, by admission rule rather than by list.** A guard may assert: (a) behavior of executable code — hooks, gate scripts, the compile step, the init command; (b) a property of the **hub** — the one file whose vocabulary other things depend on (e.g. #456's verdict-vocabulary guard, retargeted: leaves name no verdict outside the hub's set); (c) integrity of shipped assets — templates carry their placeholders, the compile output parses. Everything asserting prose-about-prose — version parity, pointer targets, restatement agreement, positional pins — dies **with its subject**, in the same change that removes the subject, never before. Expected order: 138 modules → ~40, ~35k lines → ~10k. `mutate.py` survives, retargeted at the surviving classes. The rule is recorded in the ADR so future guards are admitted against it rather than by momentum.

### How the system comes together

- **Install:** add the marketplace, install `harness`, run `/harness:init` → the six repo files above. No lock, no per-file versions, no freshness hook.
- **Daily work:** ticket → `/harness:start` (or `/build`); the always-on stub binds the iron laws; agents pull craft skills by description; builder and reviewer speak the hub's vocabulary; the gate writes the tree marker; the two hooks enforce evidence exactly as today.
- **Update:** plugin update. One version moved; nothing in the repo to reconcile.
- **Release:** promotion to `main` bumps the plugin version, folds the changelog from commit bodies, publishes; the compile step emits the Codex artifacts as part of the build.
- **Dogfood:** the harness repo installs its own plugin from source, so the process governing this repo is the shipped artifact itself — same property as today, one indirection shorter.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| **D1 — Distribution: plugin + marketplace, or keep the installer?** Rec: plugin. Consumers need a plugin-capable Claude Code; the registry, freshness hook, `/update-guidance`, `BOOTSTRAP.md`, and lock all delete. | user | ADR 0016 |
| **D2 — Coupling: hub-and-spoke, or full freestanding?** Rec: hub — one contract file, one-hop references only. Full freestanding re-imports the #456 bug class with the guards off. | user | ADR 0016 |
| **D3 — The spine: hydrated stub, or zero always-on context?** Rec: stub. Governance is push; a stop rule cannot depend on probabilistic skill triggering. | user | ADR 0016 |
| **D4 — Guard admission rule and cull scope.** Rec: the (a)/(b)/(c) rule above; prose-about-prose guards die with their subjects. This is the payoff decision — without it D1–D3 just relocate the overhead. | user | ADR 0016 |
| **D5 — Is Codex-by-compile sufficient?** Rec: decide *after* the spike (breakdown 1). If a Codex session cannot follow the compiled index into the right leaves, the fallback is a maintained parallel surface — which changes the economics of the whole proposal and would argue for stopping at Option B. | user, on spike evidence | spike ticket + ADR 0016 |
| **D6 — In-flight work disposition.** #479 (registry self-version) superseded by D1 — hold now, close on acceptance. #480 (reconcile ordering) proceeds; it is process, not machinery. The guard-hardening queue (#470, #471, #472, #475, #476) holds pending D4 — building guards the cull would delete is the one clearly wrong move. | user | the tickets |
| **D7 — The landing page.** `docs/index.html` and its two drift guards read `registry.yaml`, which D1 deletes. Retire the page, or re-point it at the plugin manifest? | user | feature spec |

## Breakdown

Sequenced; 1 gates everything after it. Suggested assurance in brackets.

1. **Codex-parity spike** [simple] — extend `generate_codex_artifacts.py` into the build-time compile; prove on a scratch repo that a Codex session follows the compiled `AGENTS.md` index into the correct leaves for a representative task. Evidence goes to D5. No teardown of any kind rides on this ticket.
2. **Extract the hub** [simple] — create the `lifecycle` skill; move the contract vocabulary (states, holds, assurance, verdicts, tree-oid binding, tracker dispatch) into it; retarget the #456 vocabulary guard at the hub; absorb `spec-driven-development` and `tracker`.
3. **De-reference pass** [simple] — reduce the 161 cross-citations to one-hop hub references; delete restatements in the same change as the guards that policed them (per D4's die-with-subject rule).
4. **Plugin packaging** [simple] — plugin + marketplace manifests, directory shape, namespaced commands; the repo installs its own plugin from source.
5. **`/harness:init` hydration** [simple] — the init command with its assets (stub, `CONTEXT.md`, verify template, settings, scaffold); absorbs and deletes `BOOTSTRAP.md`; templates move to skill assets.
6. **Distribution teardown** [simple] — delete `registry.yaml`, `guidance:` headers, the freshness hook, `/update-guidance`, the mirror arrangement; release becomes the version bump. Lands only after 1–5 are green.
7. **Guard cull** [simple] — apply D4's admission rule to the surviving suite; retarget `mutate.py`; record the before/after counts in the ADR.
8. **Consumer migration + first plugin release** [simple] — migration note for lock-file consumers; promote; publish.

## Risks / unknowns

- **Codex discovery is unproven.** The compile step exists; whether a Codex session *follows* a compiled index with the reliability the lifecycle needs is the open question. The spike gates the proposal; a negative result stops it at Option B, which is still worth having.
- **Plugin runtime maturity.** Consumers need plugin-capable Claude Code versions; marketplace hosting and private-repo access need checking for each consumer. A consumer that cannot run plugins keeps the current install until it can — the migration is per-consumer, not flag-day.
- **One version flattens per-file pinning.** A consumer today can hold one file back via the lock; under the plugin they take releases whole. Accepted as the point, but stated: a consumer that needs to fork a single skill now forks it locally (plugins layer under repo-local files) rather than pinning.
- **The cull could delete a guard that was catching something real.** Mitigations: cull by class with the subject's removal (never a standalone deletion pass before the subject dies), keep the mutation instrument over survivors, and record every culled class in the ADR with what replaced its protection (usually: the subject no longer exists to drift).
- **Transitional double surface.** Between packaging (4) and teardown (6) both shapes exist; the repo must not ship a release in that window. Sequencing inside one promotion cycle bounds it.
- **Hub scope creep.** The hub is the one file allowed to be referenced, which makes it the tempting home for everything. The ≤200-line target and D4's guard on it are the counterweight; growth of the hub is the metric to watch in the first `/assess` after shipping.
- **This proposal's own tickets meet the machinery they retire.** Items 2–6 each carry today's version fan-out until 6 lands. Accepted as the last payment; the #479 hold means no effort is spent improving what 6 deletes.
