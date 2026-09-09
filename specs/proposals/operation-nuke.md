---
proposal: operation-nuke
status: under-decision
date: 2026-09-08
related:
  - specs/decisions/0017-harness-v5-plugin-shaped-guidance.md
  - specs/decisions/0018-gate-marker-convention-is-node.md
  - specs/decisions/0020-authored-tree-binding.md
  - specs/decisions/0021-copy-or-bridge-by-failure-mode.md
  - specs/features/plugin-surface.md
---

# Proposal: Operation Nuke — delete the machinery, ship the guidance

> Retire the gate-marker enforcement complex and everything built to serve it, make CI the control of record, and reduce this repo to what it distributes: skills, agents, three small hooks, and two workflows that hydrate and audit a consumer.

## Problem / motivation

**This repo is nine parts machinery to one part product.** The measured inventory at `dev`:

| Category | Lines | What it is |
|---|---|---|
| Guidance — skills, agents, templates | **4,056** | the thing consumers install |
| Executables — `scripts/`, `hooks/` | 9,384 | machinery |
| Tests | 28,065 | machinery guarding machinery |

Assurance per product line is **6.86 and rising** — 5.36 six weeks ago, per the 2026-09-08 process assessment. The suite grew 31.5% in that window; guidance grew 2.7%. We are not building the product. We are maintaining its scaffolding.

**The growth is an accretion spiral, and each layer names the layer that caused it.** Read the file headers:

- `gate-marker.js` binds a verdict to a tree oid.
- `land.js` (585 lines) exists because that binding "modelled at 7.4 attempts to land at eight pushes an hour" — a landing problem the binding created.
- `harness-refs.js` (483 lines) exists to share gate outcomes between sessions "without a service" — a coordination problem the binding created.
- `harness-config.js` (598 lines) exists because three hand-rolled readers of the same YAML — two of them in marker hooks — produced four recorded parser bugs (#487, #488, #510).
- `plugin-version.js` (522 lines) is the third attempt at one version bump: #556 built a 713-line guard, #588 deleted it for a release-hop plan that could not work, #589 landed this.

ADR 0020 puts a number on the consumer-side cost of the binding it defends: **23% of commits on `calibrate`'s integration branch are reconciliation merges** — churn that exists because a verdict binds to a tree while the branch moves under it.

Not one of those solves a problem a user has. Every one solves a problem the previous mechanism introduced. **This is the definition of over-processing (P2), and P0 refuses "a mechanism added where a number would do" and "an assurance calibrated for a stage the product is not at."** The machinery enforces a zero-defect-reaches-integration posture. The spine's own risk appetite says the opposite in plain words: *"we **accept** a defect reaching the integration branch, because the gate and the next builder catch it and a revert is cheap."* **We built enforcement for a risk appetite we explicitly declined.**

**Incremental retirement is not converging.** The most recent process assessment ran a full mutation sweep and its single concrete deletion candidate was a **39-line** wording guard — 0.1% of the machinery. Four assessments have each returned refinements. The mechanism is working; it is pointed at the wrong subject.

**The marker's actual purchase is roughly two minutes of detection latency.** CI runs `bash scripts/verify.sh` on every push to `dev` and `main` and on every PR to `dev` (`.github/workflows/ci.yml`). A red tree that reaches `dev` is caught by CI within the job's runtime, which is under a minute for this gate. The marker complex — 16,877 lines across hooks, scripts and tests — buys the difference between catching that in-session and catching it at CI. At the declared risk appetite, that difference is not worth 45% of the repository.

**And the machinery is the distribution friction.** Because gate assets are *vendored* into consumers (`scripts/gate-marker.js`, `scripts/harness-config.js`, `scripts/package.json`), a plugin release and a consumer's committed copies must stay in lockstep. That is why `--refresh` output must land on `main` before a cloud session initialising from `main` works, and it is why ADR 0021 and #617 exist at all. **If nothing is vendored, the lockstep problem does not exist to be solved.** The friction is not a bug in `--refresh`; it is the cost of shipping code instead of guidance.

**Doing nothing costs** another cycle of the same: refinements to mechanisms nobody outside this repo benefits from, while the process and skill effectiveness — the actual product, and the thing with four unsettled weak-skill results in `plugin-surface.md:390–425` — stays unmeasured.

## Options

**Option A — Nuke: plugin-only distribution, CI as the control of record.** Delete the marker complex (`gate-marker.js`, `gate-evidence-guard.js`, `push-target-guard.js`, `git-push-guard.js`, `land.js`, `harness-refs.js`, `promotion-step.sh`) and the ~11,400 lines of tests holding them. Keep three hooks that need no vendored assets: `test-lock-guard.js` (291 lines, independently evidenced), `prompt-guard.js`, `workflow-guard.js`. Replace `/harness:init` with `hydrate` (greenfield or brownfield reconciliation of `AGENTS.md`/`CLAUDE.md` and sub-directory files) and add `audit` as a sub-agent that assesses an implementation for consistency. Nothing is vendored, so nothing must stay in lockstep. · *Trade-off:* on a private consumer with no branch protection, a red tree can reach the integration branch and stay there until CI reports or the next builder trips over it. Unattended `/routine` can stall a tick on a red base — which is the andon cord functioning, but it is a throughput cost, not a free lunch.

**Option B — Nuke the marker, keep a thin advisory push guard.** As A, but retain a warn-only guard that tells a session it is pushing an ungated tree. · *Trade-off:* keeps roughly 300–400 lines and one vendored reader, so the lockstep coupling survives in miniature and the guard is the first place the accretion restarts. Buys a warning nothing acts on.

**Option C — Continue incremental retirement.** Keep assessing, delete what mutation proves dead. · *Trade-off:* the measured rate is 39 lines per assessment against 37,449; the ratio has moved the wrong way for six weeks. This option's own evidence is that it does not converge.

**Option D — Keep the machinery, buy GitHub Pro.** Closes the #618 gap so server-side protection exists everywhere, keeping the marker as the in-session control. · *Trade-off:* addresses the enforcement gap and none of the maintenance burden, which is the actual complaint. Spends money to keep the thing that costs time.

## Recommendation

**Option A.** It is the only one that changes the ratio rather than trimming it, and it is what P0 requires once the machinery is read against the stage the spine declares.

Three things make it safe enough at this stage:

1. **Consumers already hold their own control, and it was never ours to hold.** `calibrate` runs automated CI that pushes to `staging`, with `main` bumped from `staging`; `nano-erp` does similar. Their topology is their business — **we stay in our lane.** This repo decides what the plugin delivers; a consumer decides how it protects its own branches. That is not a gap this proposal has to close, and it is a reason the marker was solving a problem outside its scope.
2. **The andon cord means stop the line, not stop.** A ticket that goes red at integration time — whether from its own diff or a clobber landed on the integration branch meanwhile — is fixed by the builder who hit it, as part of landing. Deleting the marker does not remove that response; it removes a second, local, expensive attempt to prevent the thing the cord exists to handle. What survives is a small duplication window, not a stalled queue: see *Risks*.
3. **`test-lock-guard.js` stays.** It is the one guard with independent evidence — over 79% of measured cheating is editing the test directly — it is 291 lines, and it vendors nothing. Deleting the marker complex does not weaken it. Keeping it is P0-consistent: it is the guard whose cost is a fraction of the change it guards.

What we get back is the ability to iterate on process and skill effectiveness at plugin speed: update the plugin, and a consumer is 90% current. `hydrate` reconciles the repo-owned remainder, `audit` reports drift. **Drift is bounded by the next hydrate**, so consumers stop needing to be correct continuously and only need to be correctable — which is a much cheaper contract to hold.

One further simplification falls out. With no tree binding to preserve, **plain `git rebase` onto the integration branch is available again** as the reconciliation move — the thing `land.js`'s three-case logic exists to avoid. A builder rebases, runs the gate, and pushes. That is the whole of it.

This traces to P0 (do less; the machinery is a guard larger than what it guards), P2 (reduce waste; the marker duplicates a control the consumer already holds, and re-implements coordination git and CI provide), and P3 (flow; the vendored lockstep serialises every consumer refresh behind a `main` landing).

## Not doing

- **Anything inside a consumer repo's CI, branch protection or billing** — out because we stay in our lane. This repo decides what the plugin delivers; `calibrate` and `nano-erp` already run their own gated paths to `main` via `staging`, and #618's purchase question is theirs, not this proposal's. Reopen only if a consumer asks the plugin to carry a control it cannot hold itself.
- **Any guard that reads gate state** — no lighter marker, no "is this tree certified" warning, no tree resolution. Out because that is the accretion restart: a guard that must know whether a tree was gated needs the marker, the config reader and the tree computation behind it, which is how 3,110 lines happened the first time. **The boundary is testable and belongs in item 1's ADR: a surviving hook may read the push target and the branch names in `harness.yaml`, and nothing else.** A future ticket that wants a hook to know whether the tree was gated is making a new decision, not extending this one. Reopen if a measured incident shows a red tree reaching an integration branch and *staying* there past the next builder.
- **A target-aware advisory hook is explicitly *in*** — it reads the push target, warns on a declared role branch, and is the surviving fragment of `push-target-guard.js` rather than a new mechanism. It is named here only because the line above would otherwise appear to rule it out.
- **Deleting `test-lock-guard.js`, `prompt-guard.js`, `workflow-guard.js`** — out of scope; these are the portable hooks the target state keeps.
- **Rewriting the assessment cadence or the ledger** — out; `/assess` is guidance and stays. Only its subject changes.
- **Changing the tracker, the lanes, or the review discipline** — out. This proposal deletes enforcement, not process.
- **Migrating consumer repos' product code** — out. Consumers get a `hydrate` run; their own code is untouched.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| D1 — Does `mutate.py` (1,503 lines + 2,314 lines of tests) go? Its primary consumer is proving *guards* can fail; with the guards gone, "change the line, run the test, revert" is a technique that belongs in `engineering` as prose. | user | ADR (new) |
| ~~D2~~ — **Withdrawn 2026-09-08.** Consumer CI and branch protection are out of lane. `calibrate` gates through `staging` with `main` bumped from it, and `nano-erp` does similar; #618 remains theirs to close. | — | — |
| D3 — Does `plugin-version.js` (522 lines) go? Without vendored assets there is no version-mismatch failure mode; `claude plugins update` still compares the manifest string, so a bump is still needed — but it may be a line in `/build` rather than a script. | user | ADR (new) |
| D4 — The design system: skill-with-attached-assets, copied out at hydration. Does `build_design_tokens.py` (352 lines) travel with it as a skill asset, or is the 8-tier structure carried as assets alone? | user / architect | `specs/features/` |
| ~~D6~~ — **Resolved 2026-09-08 by the operator.** No new `/land`: the landing half folds into **`/promote`**, which already moves a branch to its next destination. One skill, two altitudes. **One consequence must ship with it — see D7.** | resolved | `skills/promote` |
| ~~D7~~ — **Resolved 2026-09-08 by the operator.** Whatever it is called, unattended agents must be able to run the landing step in a routine. `disable-model-invocation` comes off `/promote`, `/routine` gains the call, and misuse is discouraged by an **advisory** target hook rather than by withholding the command. | resolved | `skills/promote`, `skills/routine` |
| D8 — Does a force-push to a declared role branch stay a **refusal**, or become advisory? A ~1,400-line question (the hook plus its lexer tests), not a philosophical one. **Advisory does not mean nothing refuses:** `settings/harness.json` already carries force-push and `reset --hard` deny globs, and they survive either way. The lexer exists only because globs miss exotic spellings (`-fq`, trailing `--force`, `+HEAD:dev`). Recommendation is advisory — globs refuse the common spellings, the hook warns, the lexer goes. | user | ADR (item 1) |
| D9 — `/digest`'s section 2 carries the **R line** (tickets opened vs closed, split by source) and the **load line** (open against `wip_limit`), and its own text says the R line "is the only place the queue's growth rate is visible". Retiring the console retires that measurement. Does it move into `drain`'s output, or is it dropped? **Recommendation: drop it here and let `/assess process` own the series** — the load line is multi-project machinery for a repo that declares `project_field: none`. | user | `skills/drain` |
| ~~D5~~ — **Resolved 2026-09-08 by the operator.** Stop the line, don't stop: the builder who hits red at integration fixes it then, whether the cause is their diff or a clobber. No tick stalls. Residual risk is duplicated effort in the window before a fix is visible, bounded by rebasing from the integration branch before running the gate. Item 4 writes this into `/build`. | resolved | `skills/build`, `skills/routine` |

With D2 withdrawn and D5, D6, D7 resolved, **no open decision blocks item 1.** D1, D3 and D4 are answered when their item comes up; **D8 at item 2**, where the lexer either survives or does not; **D9 at item 8**.

## Target manifest

What the repository contains when items 1–9 have landed, and what each thing does. **This is the sign-off surface.** Statuses: **keep** (unchanged) · **rewrite** (same job, new content) · **reduce** (survives smaller) · **new** · **decide** (an open decision owns it).

### Skills — the deliverable (17)

| Skill | Status | What it does |
|---|---|---|
| `engineering` | keep | Build method, test-first discipline, scope, the verification standard. The largest craft skill and the one builders read most. |
| `review-discipline` | reduce | Two-stage review, the finding 2×2, the verdicts. Loses the tree-binding and delta-review sections. |
| `authoring` | keep | Shape and prose of every artefact a downstream agent reads — specs, tickets, records, commits. |
| `architecture` | keep | Cross-cutting design decisions, the watchlist, ADR discipline. |
| `tracker` | keep | Ticket semantics over whichever backend `harness.yaml` names. |
| `worktree-isolation` | reduce | Branch, worktree, teardown. Loses the green-pointer machinery that `harness-refs.js` served. |
| `work-discovery` | keep | Choosing the next ticket off the queue; the andon check. |
| `build` | rewrite | Setup → spec → test-first build → review, ending at PASS. Loses landing entirely. |
| `promote` | rewrite | **Gains the landing half.** Rebase → gate → PASS → tree-compare → push → close → reflect → clean up, at whatever altitude the topology names. Loses `disable-model-invocation` (D7). |
| `review` | keep | The review stage run alone against a branch. |
| `routine` | reduce | One unattended tick. Gains the `/promote` call; loses the green-pointer and re-bind logic. |
| `capture` | keep | File one ticket onto the queue. |
| `propose` | keep | Work an idea to a decision before build time is spent. |
| `drain` | **new** (replaces `digest`) | Operator-present only, two piles with **different procedures**. *Held tickets:* per item — read the thread, answer, write it into the change spec, release the hold. The DEFER return path. *Improvement ledger:* a corpus pass — re-validate each entry against the tree, consolidate entries sharing a home and abstract small ones into the pattern they evidence, check the open queue for a twin, drop what names no user or consumer outcome, then bring the surviving slate back for one sitting. `/assess` calls it as its close-out. |
| `assess` | reduce | Periodic health pass: dispatch the steward, write the dated report, file findings, apply retention. **Step 5 moves out to `drain`**, which it calls. |
| `hydrate` | **new** (replaces `init`) | Greenfield setup or brownfield reconciliation. Writes `AGENTS.md`/`CLAUDE.md` at the root and per sub-directory for progressive discovery, seeds path-scoped rules, copies out attached assets. **Vendors no gate code**, so it carries no migration paths and no fixture corpus. **Ends by dispatching `harness-audit`** and carrying its findings into the report. |
| `design-system` | **new** (D4) | The 8-tier structure (`00-brand` … `07-flows`) as skill-attached assets, copied out at hydration. |

### Agents (6)

| Agent | Status | What it does |
|---|---|---|
| `dev` | keep | Implementation sub-agent, dispatched when a diff would flood context or the feature lane wants a fresh one. |
| `architect` | keep | Design artefacts and decisions; produces no code. |
| `reviewer` | keep | The change lane's reviewer. |
| `reviewer-feature` | keep | Same mandate, deeper model and effort. The lane buys depth through the runtime (ADR 0005). |
| `steward` | keep | Whole-system periodic assessment for `/assess`. |
| `harness-audit` | **new** · `model: sonnet` | Validates a hydrated repo against the current plugin and reports drift. **`hydrate`'s close-out**, and separately dispatchable by name when the operator wants a check without re-hydrating. No paired skill — see *Why the audit is an agent and not a skill*. |

### Hooks (4, from 6)

| Hook | Status | What it does |
|---|---|---|
| `test-lock-guard.js` | keep · 291 | Refuses a test edit while a run declares its tests locked. **The one guard with independent evidence** — over 79% of measured cheating is editing the test directly. Vendors nothing. |
| `prompt-guard.js` | keep · 105 | Advisory: flags injection-shaped content on write. |
| `workflow-guard.js` | keep · 139 | Advisory: flags source edits outside a worktree. |
| `push-target-guard.js` | **reduce** · 1,143 → small | Advisory: warns on a push targeting a declared role branch. **May read the push target and the branch names in `harness.yaml`, and nothing else** — the boundary item 1's ADR records. Its marker half goes. |
| ~~`gate-evidence-guard.js`~~ | delete · 996 | Stop-hook marker check. |
| ~~`git-push-guard.js`~~ | delete · 971 (D8) | Force-push refusal and its POSIX lexer. The `settings/harness.json` deny globs stay regardless. |

### Scripts

| Script | Status | What it does |
|---|---|---|
| `verify.sh` | keep · 145 | **This repo's own gate.** Not shipped: a consumer writes its own and names it in `harness.yaml`. Loses the marker write. |
| `setup-cloud-env.sh` | keep · 206 | Cloud session bootstrap for this repo. |
| `session-start-bootstrap.sh` | keep · 16 | SessionStart hook entry. |
| `harness-config.js` | **reduce** · 598 → small | Reads `harness.yaml`. Was hardened across three readers and four parser bugs; now serves one advisory consumer, so advisory tolerance applies. |
| `build_design_tokens.py` | decide · 352 (D4) | Builds `docs/index.html` from `design/03-tokens/tokens.json`. Travels with the design skill or is retired. |
| `plugin-version.js` | decide · 522 (D3) | Raises the plugin version at `/build` step 1. Without vendored assets there is no mismatch failure mode, but `claude plugins update` still compares the manifest string. |
| `mutate.py` + `_mutate_outcomes.py` | decide · 1,578 (D1) | Proves a guard can fail. Its main consumer is the guards being deleted. |
| ~~`gate-marker.js`~~ | delete · 1,013 | Writes the tree-keyed marker. |
| ~~`land.js`~~ | delete · 585 | The three-case landing decision. |
| ~~`harness-refs.js`~~ | delete · 483 | The `refs/harness/*` cross-session namespace. |
| ~~`promotion-step.sh`~~ | delete · 249 | Scripted promotion; `/promote` does it in git. |

### Supporting surface — all keep

`templates/` (11 files + `rules/`) · `.codex/` adapters, `config.toml`, `harness.rules` · `settings/harness.json` permissions and deny globs · `.claude/rules/` path-scoped rules · `.github/workflows/ci.yml` and `nightly-promotion.yml` · `AGENTS.md`, `CLAUDE.md`, `README.md`, `CONTRIBUTING.md`, `SECURITY.md` · `specs/` and `assessments/`.

`MIGRATION.md` is rewritten by item 5 for the one-time cutover: a consumer carrying vendored assets must have them **removed**, not merely left unrefreshed.

### Tests — the largest single change

| Group | Lines | Disposition |
|---|---|---|
| Marker, gate-evidence, push-target, gate-command, branch-parsing, merge-path | ~9,600 | delete with items 2–3 |
| `promotion-step`, `land`, `harness-refs`, gate-lock | ~3,150 | delete with item 3 |
| Force-push hook + heredoc lexer | ~960 | delete if D8 is advisory |
| `mutate` suite | ~1,920 | delete if D1 retires it |
| `plugin-version` | 743 | delete if D3 retires it |
| Refresh fixtures, manifest, gate-ignores, git-init fixtures | ~560 + corpus | delete with item 5 |
| Hook manifest, fail-open, module-type, Codex compatibility, marketplace, settings parity, toolchain, coverage gate, proposal-path, reportable-path | ~3,400 | **keep** — they guard what survives |
| `test-lock`, `prompt-guard`, `workflow-guard` hook suites | ~1,100 | **keep** |
| `test_workflow_skill_invocability.py` | 91 | **keep, and item 4 updates it** — it is the guard that pins which skills carry `disable-model-invocation`, so D7's change lands here |
| `spine_template_parity`, `build_lifecycle_order`, `seeded_assets` | ~1,340 | decide at item 5 — wording guards over prose, which ADR 0017's admission rule and the last assessment both question |
| Design tokens + landing-page inventory | ~1,460 | decide with D4 |
| Helpers (`_toolchain`, `_gitutil`, `conftest`, `_hooks`, `_prose`) | 625 | reduce with their consumers |

### The ratio this is signed off against

| | Now | Target | Δ |
|---|---|---|---|
| Guidance — skills, agents, templates | 4,056 | ~4,400 | grows: two new skills, one new agent |
| Executables — scripts, hooks | 9,384 | ~900–2,900 | depends on D1, D3, D4 |
| Tests | 28,065 | ~9,000–11,000 | |
| **Total** | **41,505** | **~14,300–18,300** | **−56% to −66%** |
| **Assurance per product line** | **6.86** | **~2.0–2.5** | the measure item 9 re-baselines |

The wide bands are the open decisions, and they are wide on purpose: D1, D3 and D4 together move roughly 4,000 lines. Signing off the shape does not commit any of them.

## Breakdown

Item 1 sets the shape — *the plugin is the whole product, a consumer's own CI is its control, hydrate+audit is the consumer contract* — and is expensive to unpick once the deletions follow it. It is held for the operator, and every item below declares a dependency on it.

1. **Record the shape** *(feature; held — `input`)* — an ADR stating that the plugin is the whole deliverable, that nothing is vendored into consumers, that a consumer's own CI and branch protection are out of lane, and what the accepted residual risk is. Supersedes ADR 0020 and, in effect, ADR 0018. Held because the shape is expensive to unpick, not because a decision is outstanding. **Depends on: nothing. Everything below depends on this.**
2. **Retire the marker complex, and reduce the push guards to one advisory** *(feature)* — delete `gate-marker.js` and `gate-evidence-guard.js` outright. **`push-target-guard.js` is reduced, not deleted:** its branch-name recognition survives as a small advisory hook that warns on a push to a declared role branch; its marker half goes with the binding. `git-push-guard.js`'s fate is D8. Rewrite spine laws 3 and 5 and the *Enforcement* section around CI and the surviving hooks. ~13,600 lines, less whatever D8 keeps. **Depends on 1.**
3. **Retire the landing and promotion machinery** *(feature)* — delete `land.js`, `harness-refs.js`, `promotion-step.sh` and their tests; `/promote` and `/build`'s ship step become plain git against a green CI status. ~3,300 lines. **Depends on 2** — these exist only to serve the binding. Item 4 then gives `/promote` the landing half, so sequencing these two adjacently avoids rewriting the same skill twice.
4. **Split the lifecycle at PASS, and rebase before review instead of after** *(feature)* — `/build` ends at a reviewed branch; `/promote` takes it from there. The stage order becomes:

   | `/build` | `/promote` |
   |---|---|
   | `in_review` → `rebase` → `substantive_review` loop → `pass` | `rebase` → `full_gate` → `pass` → `tree_compare` → `push` |

   **`delta_review` disappears, and that is the point.** It exists because reconcile runs *after* review, so new bytes arrive that no verdict covers. Rebase first and the reviewer reads the branch as it will actually land. Also carries the resolved D5 posture, since that is landing behaviour. **Depends on 3** — the seam is only clean once the binding is gone; see *The seam* below.
5. **`init` → `hydrate`** *(feature)* — one workflow that recognises greenfield vs brownfield and reconciles rather than refreshing; no vendored gate assets, so no migration paths, no fixture manifest. Writes `AGENTS.md`/`CLAUDE.md` at the root and in sub-directories for progressive discovery. Retires `references/refresh.md` and the refresh fixture corpus. **Depends on 2, 3.**
6. **`harness-audit` agent** *(change)* — one agent definition, no paired skill: `hydrate` dispatches it as its close-out, and it is dispatchable by name for a check without a re-hydration. Pinned to `sonnet` per ADR 0005's tiering. **Depends on 5.**
7. **Design system as a skill with attached assets** *(feature)* — the 8-tier structure and assets live in the skill folder and are copied out at hydration. Answers D4. **Depends on 5.**
8. **`digest` → `drain`** *(feature)* — retire the console; keep the two drains and put them in one operator-present skill with **two distinct procedures**, the ledger's being a corpus pass (re-validate, consolidate, twin-check, drop, return the slate) rather than per-item Q&A. Carries `/assess` step 5 across intact and **makes the twin check explicit at the fold step** rather than inherited from the spine's *Filing* contract. `/assess` calls `drain`; the steward never does. **Repoints the DEFER return path** in `build`, `review`, `work-discovery`, `tracker` and its two transport references, `review-discipline/references/improvement-ledger.md`, the spine and `templates/spine.md` — 19 mentions across 10 files. Answers D9. **Depends on 1 only**, so it runs in parallel with everything else.
9. **Decide `mutate.py` and `plugin-version.js`** *(change)* — execute D1 and D3. ~5,000 lines if both go. **Depends on 2.**
10. **Re-baseline the ratio** *(change)* — one `/assess` process pass measuring assurance-per-product-line against the 6.86 baseline, so the change is evidenced rather than asserted. **Depends on 2–9.**

Items 2, 4 and 9 are independent of 5–7 once 1 lands, so the deletion track and the hydrate track run in parallel; item 8 touches guidance only and depends on nothing but the shape, so it can run alongside either (P3).

### Why `digest` goes and `drain` is the skill that was actually wanted

**There are two drains in the current design, and they are in different skills.** `/digest --drain` clears **held tickets** — the `input`-labelled, operator-assigned pile a DEFER leaves behind. `/assess` step 5 drains the **improvement ledger** — deciding each entry done, folded or dropped. They share a name, a shape and an operator, and nothing else connects them to the skills they sit in. That split is why "the drain" is ambiguous in conversation and why one of them is buried inside a periodic assessment.

What they share is the posture — operator present, an accumulation cleared, every outcome recorded — not the procedure. **The two procedures are genuinely different, and the ledger's is the substantial one.**

The held pile is per item: read the thread (`/digest` already says to check whether it was answered rather than re-asking), capture the operator's call, write it into the change spec, release the hold. Items do not interact.

The ledger pile is a **corpus pass**, and its steps are already in `/assess` step 5:

| Step | Step 5's own words |
|---|---|
| Re-validate for staleness | *"Re-validate each entry against the tree before deciding it… re-read the file an entry names, and re-run any count it quotes rather than carrying the number forward."* |
| Consolidate and abstract | *"group entries whose suggested home is the same file, abstract several small ones into the pattern-level candidate they are evidence for."* |
| Drop against criteria | *"Drop is the default. An entry is promoted only when it names what a user or a consuming repo gets from it."* |
| Return the delta | *"prioritise what is left by the cost of leaving it, and present a short slate the operator can decide in one sitting — each with its case, not the raw list."* |

**One step is missing from step 5 and belongs in `drain` explicitly: the twin check.** The spine's *Filing* contract governs it — *"before filing a ticket, search the open queue and extend an unstarted ticket on the same surface instead of creating a twin"* — and step 5's **fold** outcome inherits it silently by creating a ticket. That is the wrong place to leave it implicit, because a fold is the one filing that happens *immediately after a corpus-level consolidation*: the pattern-level candidate just abstracted from several entries is precisely the thing most likely to already exist on the queue. `drain` states it at the fold step rather than relying on inheritance.

None of this is new material to write. Re-validation, consolidation and the twin check are craft the repo already carries in `authoring`, `work-discovery` and the spine's *Filing* contract, so `drain` stays thin control flow that pulls them — the same shape as `/build`, which is "a thin one" deferring to `engineering` and `review-discipline` rather than restating them. One skill, two piles.

**What is left of `digest` once the drain leaves is a console nobody opens.** Its five sections report input-held tickets (the drain's own input), run outcomes, parked work, new ledger entries (read-only, deciding nothing), and hands-on errands. At one operator, one queue and a tracker that is already the source of truth, that is a daily report of what the tracker shows — over-production (P2), and the evidence is that it has gone unused. The report half is the part with no consumer; the drain half is the part that is reached for.

**Two things must not fall out with it.**

- **The DEFER return path.** `/build` states that "`input` is the whole return path for a DEFER: `/digest --drain` selects `input` and nothing else", and `/review` sends deferrals the same way. Nineteen mentions across ten files — `build`, `review`, `work-discovery`, `tracker` and both transport references, `review-discipline/references/improvement-ledger.md`, the spine, and `templates/spine.md` — repoint at `drain`. A run that renames the skill and misses those leaves every DEFER with no way back.
- **The R line.** `/digest`'s own text says it "is the only place the queue's growth rate is visible". That is D9.

**One correction to the shape as proposed: `/assess` calls `drain`; the steward must not.** The steward is the sub-agent that *writes* ledger entries — systemic insights it raised in the same pass. `/assess` step 5 already refuses this explicitly: *"an unattended run does not drain… A pass deciding its own proposals is the grant this split exists to close."* Letting the steward drain reopens exactly that grant, and it is the same law-4 problem as the audit: the agent that wrote the finding is the wrong one to decide it. So the call sits in `/assess`, after the steward has reported and with the operator present — which also keeps `drain` operator-only, where an unattended `/assess` notes the ledger's size and stops.

### Why the audit is an agent and not a skill

An earlier draft of this proposal gave the audit both a skill and an agent, on the model of `steward` + `/assess`. That was over-production, and the pairing it copied does not apply: `/assess` earns its skill because it does work the agent does not — it writes a dated report, files findings as tickets, and drains the improvement ledger. A skill wrapping `harness-audit` would only dispatch it, which is a file that exists to call another file.

**The stronger reason for the agent is the fresh context.** The main agent that just performed a hydration is the worst possible auditor of it: it holds every assumption it acted on, and it checks the repo it believes it left rather than the repo that is there. That is law 4's problem exactly — the reviewer writes the record, never the builder — and a sub-agent is what buys the separation. So the agent is not a delivery-mechanism preference; it is the mechanism that makes the audit worth running.

Two consequences worth stating so nobody re-derives them later:

- **No skill does not mean "only reachable through `hydrate`."** An agent in `agents/` is dispatchable by name, so an operator who wants to check a repo without re-hydrating it just asks for `harness-audit`. Nobody needs to add a skill later to make it invocable.
- **`hydrate` reports the audit's findings; it does not act on them.** Hydration is working-tree-only and the operator reviews the result, so the close-out's job is to put drift in the report, not to repair it silently.

**On the name — skills and agents are addressed differently, and only one of them is namespaced.** A plugin *skill* invokes as `/harness:<name>`, so the prefix is already there and `harness-audit` as a skill would give the doubled, awkward `/harness:harness-audit`. A plugin *agent* is dispatched by bare name through the host's Agent tool, in a flat list beside the host's own (`general-purpose`, `Explore`, `Plan`) and beside whatever the consuming repo defines. **Because this is an agent, `/harness:harness-audit` never occurs** — the awkward form only exists for the shape this is not.

That leaves the flat namespace as the only naming consideration, and its cost is small either way: `harness-audit` is unambiguous and slightly verbose; `auditor` matches the role-noun convention the five siblings use (`dev`, `architect`, `reviewer`, `reviewer-feature`, `steward`) but says no more about what it audits than `audit` does. **Recommendation: `harness-audit`**, because these definitions land in a consumer's own `agents/` directory and a new one should not inherit a known collision risk. *Observation, not an item:* the existing five carry that risk and the same argument would rename them — a separate change, out of scope here, noted so the inconsistency is known rather than overlooked.

### Why the advisory hook is cheap, and what would make it expensive

Adding a hook to a proposal about deleting hooks needs its reason on the record.

`git-push-guard.js` is 971 lines, and its own header says why: *"most of this file is a POSIX shell lexer — quoting, `$(…)`, backticks, ANSI-C escapes, parameter expansion — because deciding a force-push from the raw command string is what CAL-1001 proved cannot be done."* Deny globs missed `-fq`, `--force` in trailing position, `+HEAD:dev` with the remote omitted, and `git -C … push` reordering. The lexer exists because **a refusal must not be bypassable.**

An advisory warning has the opposite tolerance. A false negative costs one un-warned push; nobody is relying on it to hold a line. So a target hook can match the command with an ordinary pattern, accept imperfect coverage, and stay small — **but only while it stays advisory.** The moment it must refuse, the lexer comes back, and with it the reason this repo has 971 lines to decide the meaning of one flag. That is the accretion trigger, and it is worth writing into item 1's ADR beside the read-only boundary.

Which turns D8 into an arithmetic question. Keep force-push-to-a-role-branch as a refusal and the lexer stays. Make it advisory and it goes with the rest. **The recommendation is advisory**, for two reasons: this repo is public, so GitHub branch protection already refuses a force-push to `main` and `dev` server-side, in the right place and for free; and a consumer's protection is out of lane by the operator's own scoping. There is also a third layer nobody has to build: **`settings/harness.json` already denies `git push --force` in eight spellings and `git reset --hard`**, and those globs survive whichever way D8 goes. So "advisory" does not mean nothing refuses a force-push — it means the glob layer refuses the common spellings, the hook warns, and the 971-line lexer that closes the exotic ones goes.

The counter-argument deserves stating: a force-push is the one action a revert cannot undo, so it is not stage-calibrated the way a red tree is. It is still *recoverable* — server-side reflog, and other agents' clones carry the commits — which, with the glob layer standing, is why the recommendation is advisory.

### The seam, and why item 4 waits for item 3

`/build`'s current stage order is `in_review → substantive_review → reconcile → delta_review → full_gate → pass → tree_compare → push`. **Review and landing are interleaved, not sequential** — reconcile sits *between* two review stages, and the gate runs after it. Split at "once review is cleared" today and the cut runs straight through that interleaving.

That interleaving exists *only* to keep a verdict bound to a tree while the integration branch moves. Delete the binding at items 2 and 3 and the sequence collapses to **review → rebase → gate → push**, which has an obvious seam at PASS. Splitting first would mean designing `/land` around `land.js`'s three cases and then redesigning it when those cases vanish — building the shape twice. Splitting after costs nothing extra, because item 3 is already rewriting the ship step.

The split earns its keep on three counts beyond tidiness. **Portability:** everything before PASS is universal — spec, tests, build, review — while landing is the most repo-variable part of the lifecycle (`dev` here, `staging` on `calibrate`, its own shape on `nano-erp`). Putting the variable part behind one artefact whose only job is closing out is a real separation, not a file move. **Re-entry:** a run whose context ran out after review, or a DEFER the operator has since answered, currently has no clean resumption point; `/promote <TICKET>` is one, which matters most for unattended runs. **Load:** `/build`'s section 4 currently carries ship, reflect, close, FAIL, DEFER and spent-budget in one place; landing's outcomes move out with it.

### Why `delta_review` goes, and it is not just a saved cycle

Moving the rebase to *before* the review deletes a stage rather than relocating one. The reviewer reads the branch as it will land, so no post-review reconcile can introduce bytes the verdict does not cover, and there is nothing for a delta review to be about.

The deeper reason is what that delta review was actually reading. Bytes arriving from the integration branch are **other tickets' work, each already reviewed and gated in its own run.** `delta_review` re-reviews reviewed code. It exists only because the tree binding demands that the reviewed tree *be* the pushed tree, so any newly arrived byte — however well certified elsewhere — invalidated the verdict. `references/reconcile.md` says as much in its own placement rationale: it sits where it does "to close the review-wide window in which the base could move, by putting reconciliation adjacent to the gate and verdict that **bind** the result." Remove the binding and the stage has no remaining purpose.

**`references/reconcile.md` is relocated, not deleted.** Only its closing delta-return paragraph goes with the binding. Everything above it is hard-won and binding-independent — base movement is normal concurrency rather than a stop, the two-attempt bound, the functional-conflict escalation, and above all **the monotonic-field trap**, where two branches advance the same version number or migration ordinal to identical text, git raises no conflict, and the merged tree ships a third state under a value each side already claimed. That trap does not care why you are merging. Those rules move to wherever rebase now lives, which after this item is **both** places.

`tree_compare` survives in reduced form. With no marker to compare against, it degrades to a local check that the tree just gated is the tree being pushed — that nothing was edited between the two. Cheap, and worth keeping.

## Risks / unknowns

- **A small duplication window, not a stalled queue.** Under the resolved D5 posture the builder who hits red at integration fixes it then and there, so no tick stops. What remains is narrower: an agent that branched from an integration branch already red, and has not yet rebased, can spend effort on a fix another agent is landing at the same moment. Rebasing from the integration branch before running the gate closes most of it; the residual is the interval between one builder's fix landing and another's rebase. **That is the honest cost of this change, and it is duplicated effort measured in minutes rather than a prevented defect.**
- **The `/build` → `/land` handoff is a new unguarded seam, and it compounds the one below.** Today the push guard reads the marker, so a branch that was never reviewed cannot reach the integration branch. After items 2 and 4, nothing mechanical stops `/land` shipping a branch that skipped review, and nothing stops a `/build` that ends at PASS from simply never being landed. CI does not check whether a review happened. The mitigations are ordinary rather than clever: the ticket's own state is the record — a ticket sitting In Review with a pushed branch is a visible unlanded run — and `/land` refuses a ticket not in In Review. Both are prose. **Worth naming plainly: splitting the skill buys portability and re-entry at the price of a second prose-enforced boundary, on top of the reconcile one below.** At this stage that is affordable; it would not be at a stage with users.
- **`/promote`'s second rebase can still surface unreviewed bytes, and that is deliberate.** The pre-review rebase means the reviewer reads what lands, but the integration branch can move again between PASS and the push. `/promote` rebases a second time and gates; if that goes red, the builder's fix is made *after* the review that no longer covers it. Under the old regime this is exactly what `delta_review` caught. The bet is that the incoming bytes are other tickets' reviewed work and the fix is a merge repair, not a design change — and that where it is a design change, the gate going red is the signal to stop and return it. **This is the residual the restructure trades for deleting a stage, and it should be named rather than discovered.**
- **The reconcile step becomes prose, and it has to actually be followed.** Today `land.js` decides reconciliation in code. After this, "rebase from the integration branch before you gate" is an instruction in `/build`. This is the one place the proposal moves an obligation *out* of a mechanism and into guidance — which is the trade being made deliberately, but it is the trade, and item 4 owns writing it well. If any single instruction in the new shape is worth measuring for effectiveness, it is this one.
- **`test-lock-guard.js` reads run-state written by `/build` and resolves config through `harness-config.js`.** Item 2 must confirm the surviving hooks' dependency set before deleting the reader, or a "delete the marker complex" ticket silently breaks the one guard we agreed to keep.
- **A consumer mid-flight during the cutover** carries vendored assets whose plugin-side counterparts no longer exist. `hydrate` must remove them, not just stop refreshing them — a consumer left with an orphaned `gate-marker.js` and a `verify.sh` calling it has a broken gate, which is worse than either end state.
- **Deletion is not free to review.** ~22,000 lines removed across several tickets, each needing a reviewer who can tell "this was load-bearing" from "this served the marker." The mitigation is item order: nothing is deleted before item 1 has stated what replaces it.
- **One factual discrepancy to reconcile, outside this proposal's scope.** #618, filed today, measured `nano-erp` as having *no* workflow gating a push or pull request. The operator reports a gated path through `staging`. Nothing here depends on which is current — consumer topology is out of lane either way — but #618 should be corrected or closed rather than left asserting a gap.
- **Unknown: whether four weak skill results in `plugin-surface.md:390–425` are guidance problems or measurement problems.** This proposal bets the freed capacity on skill effectiveness without yet knowing that the effectiveness work is tractable. It does not depend on that bet — the deletion pays for itself in maintenance alone — but the stated upside does.
- **What would invalidate the recommendation:** evidence that a red tree reaching an integration branch has actually cost more than a revert in one of these repos, a duplication window that turns out to be measured in hours rather than minutes; or a consumer gaining real users during the cutover (which changes the stage line, and with it every calibration above).
