---
proposal: refresh-alignment
status: under-decision  # draft | under-decision | accepted | shipped | rejected | split | superseded
date: 2026-09-08
related: [specs/features/plugin-surface.md, skills/init/references/refresh.md]
---

# Proposal: align harness, calibrate and nano-erp so the next refresh is seamless

> Retire the design layer's twin-file convention in favour of one file placed where both hosts read it, correct a spine sentence that asserts a control two of the three repos cannot have, and repair the drift a refresh cannot reach.

**Standalone, and deliberately not merged with `spine-vocabulary-not-rules`.** The two proposals depend on one question — copy or bridge — and [ADR 0021](../decisions/0021-copy-or-bridge-by-failure-mode.md) answers it in **opposite directions for their two subjects**: the spine keeps its byte copy, and the design layer takes the bridge. That is why they stay separate rather than combining into one batch of twelve items and eight decisions across three repos and two hosts, which P3 refuses. Nothing here proposes changing the spine's copy; #558 stands.

## Problem / motivation

Both consumers refreshed to harness@9.1.0 on 2026-09-08. Everything `--refresh` owns landed correctly, and an audit that day confirmed it byte for byte: the managed trio (`gate-marker.js`, `harness-config.js`, `package.json`) is identical to the plugin's copies in both repos, the five Codex adapters are identical, both spine blocks match `templates/spine.md`, both `CLAUDE.md` files are bounded derived copies, and both gates wire `exec node <helper> run` with the emptiness test and no stale runner-flag comparison. The refresh is not the problem.

The problem is the region around it. Three separate faults, one shared cause.

**The design layer ships as two files that must stay identical, and nothing keeps them identical.** Step 5 seeds `.claude/rules/design-system.md` and `<paths.design_system>/AGENTS.md` from one template, declares everything from the first `##` heading down to be a shared region, and then never rewrites either — both are repo-owned. A refresh can report divergence; it cannot repair it. calibrate's twins had drifted into two unrelated documents (the harness-seeded rule and the design system's own pre-existing contributor guide) and were folded by hand in `774117ec`. Neither repo carries a guard over the shared region, so nothing stops the same drift recurring.

**Folding the twins did not fix host parity, because the two hosts scope by inverted mechanisms.** Claude Code loads a path-scoped rule when it reads a file matching the rule's `paths:` globs — one central file naming any number of directories. Codex reads the nearest `AGENTS.md` walking up from the edited file — a placed file whose scope is its own subtree. calibrate's rule names `design/**` and `mobile/**`; `design/AGENTS.md` is invisible from `mobile/`, so **259 mobile UI files get the rule on Claude Code and the root spine on Codex**. Identical bytes cannot close that gap, because the twin convention governs what the files say and not where each one fires.

**nano-erp's rule was seeded and never filled in.** `.claude/rules/design-system.md:4` still reads `- "<ui-source-glob>/**"`, the template placeholder. Step 5 requires the plan to report it by name for the operator to fill; it was reported at seed time and never actioned. The glob matches a literal directory that does not exist, so the rule fires only on `design/**` (72 files) and **227 `.tsx` files under `frontend/`, the actual UI, reach neither host**. The whole shared region is still byte-identical to the template, never adapted to the repo.

Underneath all three: the harness ships a convention that requires two copies of one document to stay in step, which its own research already rejected. `research/01-instruction-files.md:117` records the ecosystem shape as "one source of truth in `AGENTS.md`; `CLAUDE.md` is a thin bridge … Never maintain two copies of the same content", and judges the generated-second-copy variant "the worst of the three: it doubles the maintenance surface, it needs a drift guard to stay honest, and the drift guard needs its own tests." The design layer is that pattern, one directory down.

Separately, and discovered while pricing the enforcement question: **`AGENTS.md`'s Enforcement section asserts a control that two of the three repos cannot have.** It reads "Hooks are evidence plumbing, not authority: the controls of record are server-side branch protection and gate output in CI." calibrate and nano-erp are private repositories on a plan that refuses branch protection — `GET /repos/{owner}/{repo}/branches/dev/protection` returns HTTP 403, "Upgrade to GitHub Pro or make this repository public to enable this feature." nano-erp additionally runs its gate in CI only inside `nightly-staging-promotion.yml`; no workflow gates a push or a pull request, so nothing verifies `dev` between nightly runs. Only harness, which is public, sits behind the control the sentence describes. In the other two the local hooks and the gate marker are not plumbing under a real control — they are the only control there is.

Cost of doing nothing: the design rule keeps missing the surface it exists to govern on at least one host in both repos, the next hand-fold is the third, and a spine sentence that is false in two of three repos keeps licensing the conclusion that local enforcement is redundant.

## Options

Scope note, and the options below are kept for the record rather than as a live choice. D1 (hold the scripts) was settled by the operator; **D2 and D5 were settled by [ADR 0021](../decisions/0021-copy-or-bridge-by-failure-mode.md)**, which admits Option B for the design layer and refuses the symlink outright. What follows is the reasoning that decision was taken against, retained so a reader can see what was weighed.

**Option A — keep the root path-scoped rule; give Codex placed files.** `.claude/rules/design-system.md` stays the authored source with its `paths:` globs. For each directory a glob names, place an `AGENTS.md` symlinked to one shared body file so Codex reaches the same bytes. Claude Code keeps one central file and full glob expressiveness, including cross-cutting patterns like `**/*.tsx` that placement cannot express. Costs: two mechanisms remain in play, the plugin still seeds a file whose scope the repo must keep in sync with a second set of placements, and the frontmatter that scopes the Claude copy is meaningless to Codex, so the shared body needs separating from the host wrapper.

**Option B — placement on both hosts, one file per location.** Retire `.claude/rules/design-system.md`. `design/AGENTS.md` becomes the single authored source; `design/CLAUDE.md` sits beside it as a one-line `@AGENTS.md` import. Any further directory needing the rule gets a `CLAUDE.md` importing `@../design/AGENTS.md`; Codex, which has no import syntax, is served by prose in the root spine rather than a placed file (ADR 0021 refuses the symlink). Both hosts then scope by position, the mechanism Codex already uses and the one Claude Code documents for monorepos: subdirectory `CLAUDE.md` files "load on demand when Claude reads files in those directories." One authored file, N locations, no copied bytes, no shared-region convention, no divergence to guard. Costs: loses glob expressiveness (a rule that must fire on `**/*.tsx` wherever it appears cannot be expressed by placement); the plugin seeds only the design directory's pair, leaving extra placements repo-owned; and Codex coverage beyond the design directory degrades to a pointer in the always-on spine, which is weaker than a loaded rule.

**The host capabilities are asymmetric, and it decides how much of Option B is safe.** Claude Code has two mechanisms that need no duplicated file — the glob rule and the `@path` import. Codex has neither: the AGENTS.md standard is placement-only, with no globs and no import syntax, so a second directory's Codex coverage needs a physical file that is a symlink, a copy, or nothing. Every fragile part of Option B sits on that one side.

**Option C — leave the mechanism, add a guard.** Keep both twins and write a test in each repo asserting the shared regions are byte-identical. Cheapest to build and repairs nothing: the guard detects the drift after it happens, the fold is still manual, and host parity is untouched because the guard compares contents rather than coverage. It also adds a guard whose subject is a copy, which is the shape P0 refuses when the alternative is removing the copy.

## Portability, measured

The recommendation originally rested on symlinks, on an untested reading of the docs. Measured 2026-09-08 in a scratch repository and against the three repos themselves.

**Git versions symlinks natively.** A committed symlink is mode `120000` with the target path as its blob content — `design/CLAUDE.md -> AGENTS.md` is a 9-byte blob reading `AGENTS.md`. An ordinary clone restores it as a real symlink that resolves.

**The failure mode is real, silent, and reproducible.** Cloning with `core.symlinks=false` — git's default on Windows without the privilege, and settable anywhere — produces a *regular file* whose content is the target path. `design/CLAUDE.md` becomes nine bytes reading `AGENTS.md`, and a host loads that as the rule. Nothing errors.

**Symlinks reach Claude cloud sessions.** harness already tracks three (`.claude/agents`, `.claude/hooks`, `.claude/skills`, each pointing one level up), `.claude/skills` is load-bearing at 16 entries, and the repo has run cloud sessions across six `claude/*` branches. Broken symlinks there would have stopped the repo's own skills loading. This is evidence from use rather than from documentation.

**A one-line `@path` import survives what a symlink does not.** Under the same `core.symlinks=false` clone, a `CLAUDE.md` containing `@AGENTS.md` is still a regular file containing `@AGENTS.md`, and still means it. The import is the documented bridge for exactly this purpose, needs no privilege on any platform, and cannot silently degrade into its own target string. Where Claude Code is the reader, **the import strictly dominates the symlink** and the choice is settled.

**A lazily-loaded nested `CLAUDE.md` does expand its import, including a parent-relative one.** This was the recommendation's last unmeasured premise — the documentation describes imports expanding "at launch" and subdirectory files loading on demand, and says nothing about the combination. Probed directly on 2026-09-08 with three fixture directories under the working directory, each carrying a distinct marker string, read through the `Read` tool:

| Fixture | `CLAUDE.md` contains | Marker reached context? |
|---|---|---|
| control — body inline | the rule text itself | yes (`ZEPHYR-INLINE-8M2`) |
| same-directory import | `@RULEBODY.md` | yes (`ZEPHYR-IMPORT-4K9`) |
| parent-relative import | `@../design/AGENTS.md` | yes (`ZEPHYR-PARENT-2R7`) |

The inline control is what makes the other two rows mean anything: it fires only if nested lazy loading is happening in this session at all, so a null result in the import rows would have been a real negative rather than a probe that never ran. All three markers differ, so no row can be mistaken for another. The third row is the exact shape `mobile/CLAUDE.md` needs — one authored file in a *sibling* directory, reached by import, expanded when a source file in `mobile/` is read.

**This removed the symlink from the Claude Code side entirely**, leaving only the Codex placement — which [ADR 0021](../decisions/0021-copy-or-bridge-by-failure-mode.md) then refused outright on the `core.symlinks=false` measurement above, so the recommended shape now contains no symlink at all.

**The prior burn was dangling links, not portability.** calibrate's `test_no_discovery_symlink_survived_the_migration` guards against `.claude/commands` and `.claude/hooks` still pointing into guidance trees the plugin migration deleted. That is a different failure — a link whose target is gone — but it is the reason to keep symlinks scarce and to make a refresh report one it finds pointing at nothing.

## Recommendation

**Option B, implemented with imports and no symlinks — as decided by [ADR 0021](../decisions/0021-copy-or-bridge-by-failure-mode.md).** The load-bearing case is the ADR's, not this proposal's: guidance whose absence is *visible in the work it governs* takes the bridge, and a design rule qualifies because its absence surfaces as a hardcoded hex in a diff that review meets. The measurements in *Portability, measured* are what that decision rests on, and they stay here as its evidence rather than as an open question. What the shape then buys, on top of the decision: two files that must agree become one file read from two names, and nothing that cannot diverge needs a guard. That is the same move as #589 — give the mechanism the job rather than adding a detector for nobody having done it — and it traces to P0 (*a guard larger than the change it guards*, *a mechanism added where a number would do*) and P2 (*a second copy*, *an addition names what it retires*: the twin convention, the shared-region rule in step 5, and any guard over either retire together).

It also fixes host parity as a side effect rather than as extra work, because both hosts end up reading the same file in the same place. Option A can reach parity too, but only by keeping two scoping mechanisms and adding placements to hold them in agreement — more moving parts for the same result.

The division of ownership this produces is the one the operator asked for. The plugin seeds the design directory's pair from `paths.design_system`, a key it already reads. Extending coverage to a repo's UI directories is repo-owned and sits in the repo, beside the code it governs. Nothing plugin-owned needs to know a consumer's tree layout.

**The concrete shape**, for calibrate; nano-erp is the same with `frontend/` for `mobile/`:

| Path | What it is | Read by |
|---|---|---|
| `design/AGENTS.md` | the one authored file | Codex, in `design/` |
| `design/CLAUDE.md` | one line: `@AGENTS.md` | Claude Code, in `design/` |
| `mobile/CLAUDE.md` | one line: `@../design/AGENTS.md` | Claude Code, in `mobile/` |
| root `AGENTS.md`, one line | points Codex at the rule when touching `mobile/` | Codex, everywhere |

**Every one is an ordinary file that survives any checkout, and no symlink appears at all.** ADR 0021 refuses the symlink this proposal originally carried in the fourth row, on this session's own measurement: a `core.symlinks=false` clone leaves a regular file holding its own target path, and the host loads that *as the rule*. Present-and-wrong is worse than absent. Codex therefore gets `design/` coverage from placement and everything else from one line of always-on spine prose — weaker than a loaded rule, and the honest cost of a host with no import syntax.

Two limits belong on the record rather than in the recommendation. **Which** directories carry the rule stays a per-repo decision (D3). And on Claude Code only the project-root file survives compaction — nested files and path-scoped rules both reload when re-triggered — so anything that must hold across a long session belongs in the root spine under either option; that limit is identical for A and B and does not separate them.

## Not doing

- **Dropping the gate marker and hooks for advisory controls** — the spine's named fallback, branch protection, is unavailable on both private repos (HTTP 403), and nano-erp has no CI gate on push or pull request, so advisory controls would leave those repos with no enforcement at all. Reopen if the repos move to GitHub Pro or public and branch protection with a required gate check is configured on `dev`; the local machinery is then genuinely optional and P0 applies to it.
- **A byte-equality guard over the design twins (Option C)** — under the recommendation the twins do not exist, so the guard would assert an invariant about a state that cannot occur. Reopen only if the decision lands on Option A, where two files persist.
- **Reworking the twin convention for hosts other than Claude Code and Codex** — no third host consumes these repos. Reopen when one does.
- **Filling nano-erp's `<ui-source-glob>` in place** — a one-line repair to a mechanism this proposal retires. Superseded by the placement work; it is not a separate item. Reopen if the design-layer decision is deferred past the coverage repair, in which case it ships alone as a fix.
- **Changing how `--refresh` handles the managed trio, adapters, or spine derivation** — an audit on 2026-09-08 found all three correct and byte-identical in both consumers. Reopen on evidence of an actual failure.
- **Adding CI gating or branch protection to the consumer repos** — a repository-administration change with a billing consequence, outside this proposal and the operator's to make. Reopen as its own decision; the spine correction below records the current state rather than changing it.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| D1 — Hold the gate marker and hooks, or thin them to advisory controls? **Resolved 2026-09-08: hold.** The audit's branch-protection finding supports it; the local machinery is the only control in two of three repos. | user | this proposal; the spine correction in item 2 |
| D2 — Design-layer mechanism: Option A or Option B? **Resolved 2026-09-08 by [ADR 0021](../decisions/0021-copy-or-bridge-by-failure-mode.md): Option B.** A design rule's absence is visible in the work it governs — it surfaces as a hardcoded hex in a diff, which review meets — so it takes the bridge. | architect (ADR 0021) | ADR 0021; consequence still to be recorded in `plugin-surface.md` (item 1) |
| D3 — Which directories carry the design rule in each repo? calibrate: `design/` and `mobile/`. nano-erp: `design/` and `frontend/`, on the evidence that 227 of its UI files sit there. Confirm before item 3 places files. | user | each repo's `harness.yaml` and the placements themselves |
| D4 — Does the Enforcement correction state the current position plainly ("branch protection where available; otherwise the hooks are the control"), or does it commit to making branch protection available? The second is a billing decision. | user | `AGENTS.md` Enforcement section |
| D5 — Symlinked `AGENTS.md` for Codex in a UI directory beyond the design directory? **Resolved 2026-09-08 by [ADR 0021](../decisions/0021-copy-or-bridge-by-failure-mode.md): no.** A `core.symlinks=false` clone leaves a regular file holding its own target path, which the host loads *as the rule* — present-and-wrong, worse than either mechanism. Root-spine prose is the fallback where Codex has no import. | architect (ADR 0021) | ADR 0021; the placements |

D2 is the shape decision. Item 1 below is held for the operator on it, and items 3 and 4 depend on the answer.

## Breakdown

Ordered by dependency. Item 1 was held pending D2; **ADR 0021 answered D2, so that hold is lifted and most of item 1 is already done** — the decision is taken and recorded in an ADR. What remains of it is recording the consequence in `plugin-surface.md`, which needs no operator. Re-checked for any other hold: item 1 has none. Items 4 and 5 still wait on D3, which is the operator's, and item 2 still carries D4.

1. **Record the design-layer decision's consequence** — ADR 0021 has decided it; carry the consequence into `specs/features/plugin-surface.md`: the design layer takes the bridge, step 5's shared-region convention is retired, and no symlink is placed. Change lane, not feature — the contract decision is already an ADR, so what is left is the record. **No longer held**: D2 is answered and nothing else holds it. Blocks 3.
2. **Correct the Enforcement section** — replace the claim that branch protection and CI are the controls of record with what is true per repo, and state that where branch protection is unavailable the hooks and the marker are the control. Depends on nothing and needs no decision from this proposal; **ships first, on its own branch, as a fix.** Carries D4, which is the operator's and must be answered before the sentence is written.
3. **Implement the mechanism in the plugin** — rewrite step 5 of `skills/init/references/refresh.md` and `templates/rules/design-system.md` to the decided shape, including what `--refresh` seeds, what it never touches, and how it reports a consumer still on the old shape. Depends on 1. Feature lane.
4. **Migrate calibrate** — apply the decided shape over `design/` and `mobile/`, retiring the folded twins, and add the root-spine line that carries Codex's `mobile/` coverage. Depends on 3. **Holds on D3.** Change lane.
5. **Migrate nano-erp** — apply the decided shape over `design/` and `frontend/`, which is also the coverage repair for the 227 files the placeholder left uncovered, and adapt the still-pristine template body to the repo. Depends on 3. **Holds on D3.** Change lane.
6. **Repair calibrate's guidance guards** — port the derivation guard that `1f93004c` dropped (nano-erp's equivalent at `test/agent_guidance_contract.test.ts:126` is the model: prefix relation plus exactly one boundary marker), and correct the module's inverted framing, which still names `CLAUDE.md` the spine and `AGENTS.md` its copy after 9.1.0 reversed that. Independent of D2. Change lane.
7. **Sweep both repos' harness-owned guards against the current principles** — assess each guard over a harness-owned surface for whether it survives P0 and the 3:1 guard-to-change ratio, retiring what the mechanism now handles. Depends on 3 and 6, since those change what is left to guard. Change lane.
8. **Establish whether the `InstructionsLoaded` hook can gate a bridge** — the hook is verified to exist and fire, including on an expanded import. What is unestablished is whether that can become a check the gate runs rather than an observation a live session makes. Its outcome is ADR 0021's reopening condition, so it is filed against the ADR rather than against this proposal. Independent of everything above. Change lane.

## Risks / unknowns

**The probe measured one host at one version.** The import result above was taken in a Claude Code session on 2026-09-08, through the `Read` tool, with the fixtures directly under the working directory. It does not establish the behaviour for a file reached some other way — through Grep, through a subagent, or in a session started from a different directory — nor that the behaviour is contractual rather than current. Item 3 should re-probe on the host version the migrations land against. The standing instrument for that is the `InstructionsLoaded` hook, now verified rather than assumed — see below.

**Codex coverage outside the design directory is prose, not a loaded rule.** ADR 0021 refuses the symlink that would have carried it, and Codex has no import, so a `mobile/` or `frontend/` edit on that host gets a pointer in the always-on spine rather than the rule itself. That is a real reduction in strength, accepted because the alternative measured worse: a degraded symlink loads its own target path *as the rule*. It is also the part of this proposal most likely to want revisiting if Codex ever gains an import.

**Placement cannot express a cross-cutting glob.** If either repo later needs the design rule on a pattern like `**/*.tsx` scattered across directories, Option B cannot express it and a path-scoped rule returns alongside the placements. Both repos' UI is directory-clustered today (calibrate 259 files under `mobile/`, nano-erp 227 under `frontend/`), so this is a future risk rather than a current one.

**An import whose target moves resolves to nothing, and a link did exactly that here before.** calibrate's retired discovery symlinks pointed into guidance trees the plugin migration deleted, which is why it carries a guard against them. An `@path` import has the same exposure — the pointer survives, the target does not — so item 3 owes a refresh check that reports an import resolving to a missing file rather than leaving it to a later audit.

**The audit that grounds this proposal covered two consumers at one version.** Everything asserted about `--refresh` correctness was measured on 2026-09-08 against harness@9.1.0 with both project pins current. A consumer on an older pin, or a repo not audited, may carry faults not described here.

**Retiring the shared-region convention leaves existing consumers on the old shape.** Any repo that refreshed before item 3 lands still carries twins. Step 5 must report that state and name the migration rather than rewriting repo-owned files, or the change breaks the rule that `--refresh` never overwrites what the consumer owns.

## The `InstructionsLoaded` hook, verified

[ADR 0021](../decisions/0021-copy-or-bridge-by-failure-mode.md) names one condition that would reopen it: *"If a host reports what it actually loaded, a bridge stops failing silently and the asymmetry collapses… Confirming such a hook exists and fires is the condition for reopening this record."* It recorded, correctly, that this repository contains no reference to the hook and that `hooks/hooks.json` registers only `PreToolUse` and `Stop`. That is a fact about the harness tree, not about the host.

**The hook exists as a host event and it fires.** Measured 2026-09-08 in a scratch repository with an `InstructionsLoaded` hook registered in `.claude/settings.json`, driven by a fresh `claude -p` session:

| `load_reason` | `file_path` reported | `trigger_file_path` |
|---|---|---|
| `session_start` | the root `CLAUDE.md` | — |
| `nested_traversal` | `sub/CLAUDE.md` | `sub/thing.ts` |
| `include` | `RULEBODY.md`, the **imported** file | `bridged/widget.ts` |

The third row is the one that bears on the decision. Reading a source file in `bridged/` caused the host to report the file its `CLAUDE.md` imported — resolved target, load reason, and the file whose read triggered it. The documented matchers are `session_start`, `nested_traversal`, `path_glob_match`, `include` and `compact`.

**What this does and does not establish.** It meets the ADR's stated condition: the host does report what it loaded, including an expanded pointer. It does **not** make a bridge gate-checkable, and the ADR's narrower claim — *"a repo-side test cannot detect a reader-side failure"* — still holds as written, because this instrument runs inside a live session reading a file, not over the tree in `scripts/verify.sh`. Turning it into a check would mean a session-based probe in CI, which is a different and larger thing than a comparison over two files.

Whether that is enough to reopen ADR 0021 is the architect's call, not this proposal's. Nothing here depends on it: Option B is admitted by the ADR as written. Recorded because the ADR asked for it, and filed as a ticket.

## Audit findings

Everything the 2026-09-08 session measured, so the session that subsumes this proposal inherits the evidence rather than re-deriving it. Baseline: harness@9.1.0, marketplace checkout `59bd7fe`, both consumer project pins current at 9.1.0.

**Clean — every asset `--refresh` owns.** Verified byte for byte in both consumers, so none of it is in scope for repair:

| Asset | calibrate | nano-erp |
|---|---|---|
| `gate-marker.js`, `harness-config.js`, `package.json` | identical, in `scripts/` | identical, in `scripts/gate/` |
| spine generated block, in `AGENTS.md` and `CLAUDE.md` | identical to `templates/spine.md` | identical |
| the five `.codex/agents/*.toml` adapters | identical | identical |
| `CLAUDE.md` derivation | bounded, byte-prefixed, one marker | bounded, byte-prefixed, one marker |
| gate wiring | `exec node … run`, emptiness test, no stale `= "1"` | same |

Both managed-pair locations are legal: step 3 takes the pair wherever its content sweep finds it, and a consumer is free to keep it somewhere other than `scripts/`. Both repos also reach `preflight` on the internal path — calibrate inline before any arm, nano-erp through `npm run gate:preflight` inside `verify:stages`, pinned by `test/gate_marker.test.ts:300`. The runner does not call preflight itself (`gate-marker.js` invokes it only from the CLI dispatch, never from `runGate`), so a consumer that dropped both routes would lose the nested-worktree check silently; neither has.

**Faults, each measured.**

1. `nano-erp/.claude/rules/design-system.md:4` still carries the template placeholder `<ui-source-glob>/**`. It matches a literal directory that does not exist, so the rule reaches 72 files under `design/` and **none of the 227 `.tsx` files under `frontend/`**, which is the repo's actual UI. The whole shared region is still byte-identical to `templates/rules/design-system.md`, never adapted.
2. calibrate's design twins had drifted into two unrelated documents and were folded by hand in `774117ec`. Neither repo carries a guard over the shared region, and step 5 never rewrites either file, so nothing prevents recurrence.
3. Host parity is broken independently of the fold: calibrate's rule names `design/**` and `mobile/**`, but `design/AGENTS.md` is unreachable from `mobile/`, so **259 mobile UI files get the rule on Claude Code and the root spine on Codex**.
4. `AGENTS.md`'s Enforcement section names branch protection and CI as the controls of record. `GET /repos/{owner}/{repo}/branches/dev/protection` returns **HTTP 403** on both consumers — private repositories on a plan that refuses the feature. nano-erp additionally gates only inside `nightly-staging-promotion.yml`, with no workflow on push or pull request. Only harness, which is public, sits behind the control the sentence describes.
5. calibrate dropped `test_the_codex_mirror_is_a_byte_copy_of_the_spine` in `1f93004c`, reasoning that the copy relationship is the plugin's job now. That holds only at refresh time; between refreshes an edit to `AGENTS.md` alone leaves `CLAUDE.md` stale. nano-erp kept the equivalent invariant, ported to the new mechanism, at `test/agent_guidance_contract.test.ts:126`. The deleted test's own docstring had named the failure it prevented.
6. calibrate's `tests/guidance/test_repo_agent_guidance.py` still sets `SPINE = CLAUDE.md` and calls `AGENTS.md` "its Codex byte-copy". That relationship inverted at 9.1.0, so every spine assertion in the module reads the derived file rather than the source. A stale cross-reference sits at `tests/test_verify_sh_scope.py:7206`.
7. The two repos declare the same fact under different unread keys: calibrate has `repo.linear` (retired by #592, and step 2 obliges the refresh to report it as dead), nano-erp has `tracker_address`. `harness-config.js` resolves only `branches`, `commands`, `loop`, `paths` and `queue`; neither key is read by any skill, and both appear in the plugin only inside test fixtures copied from these repos. Inert, but it is two spellings where one would do.

**Host mechanics, measured rather than read.** Git versions a symlink as mode `120000` with the target path as its blob. A `core.symlinks=false` clone silently produces a regular file containing that path — nine bytes reading `AGENTS.md` where the rule should be. Symlinks do reach Claude cloud sessions: harness tracks three, `.claude/skills → ../skills` is load-bearing at 16 entries, and the repo has run cloud sessions across six `claude/*` branches. A one-line `@path` import survives the same restricted checkout intact, and expands on lazy load from a nested `CLAUDE.md`, including the parent-relative form — see *Portability, measured* for the fixture table.
