---
feature: plugin-surface
status: implemented
last_updated: 2026-09-10
---

# The plugin surface

> The harness is a spec-driven development process shipped as native plugins for Claude Code and Codex. Both packages carry the same skills, lifecycle procedures, role guidance, and hooks under one version, plus the guards this repo runs over them. Since #621 the assurance is the gate a repo declares in `commands.verify`, run and read by the builder, plus the independent review; server-side controls are the repository's own and are neither required nor assumed. This record is the canonical answer to "what is the harness now" (v5, ADR 0017); its registry-era predecessor, the `guidance-system` record, left the tree with `specs/retired/` at #547 and stays in git history.

## Behaviour

### One plugin, one version

The repository root **is** the plugin. `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` name the same `harness` release at one semver (`11.0.0` at this record's date). `.claude-plugin/marketplace.json` and `.agents/plugins/marketplace.json` expose that root through each host's native marketplace contract. The manifests are updater-facing selectors; the generated spine markers in `templates/spine.md`, in `AGENTS.md`, and since #558 in the `CLAUDE.md` derived from it carry the same version. The parity guard enumerates the first three and reaches the fourth by construction: `CLAUDE.md` carries `AGENTS.md` as a byte-exact prefix, so its stamp cannot differ from the spine's without the prefix assertion failing first. `tests/unit/test_spine_template_parity.py` and `tests/unit/test_native_codex_plugin.py` reject a mismatch on every gate run. There are no per-file versions, no `guidance:` headers, no `registry.yaml`, and no consumer lock file — the whole distribution channel ADR 0017 retired. Since #537 each of the nine lifecycle workflows ships **once**, as a skill under `skills/<name>/SKILL.md`, and both hosts read that one artefact: Claude Code exposes it as a slash command under the plugin prefix every plugin skill carries, and Codex discovers it from `skills/` — the only content key `.codex-plugin/plugin.json` declares. The generated `command-*` and `agent-*` mirror skills are gone.

**When it moves (#556, superseded by #588, owned since #589).** #556 moved the bump off the release hop and onto the *start* of a release cycle, on the integration branch, because nothing in this repo can write at the hop: the automated promotion opens a pull request whose head is the integration branch itself and pushes nothing new, and a bump authored onto the release branch by hand leaves `scripts/promotion-step.sh`'s content-divergence pre-condition non-empty and wedges every later nightly. The occurrence that forced it: the release merged on 2026-09-05 (`a609d5b`) carried both manifests at `6.0.1`, and `7.0.0` reached the integration branch the next day, so a consumer running `claude plugins update harness` in between was told it was already current over bytes that had changed. **#588 retired that obligation and gave it to nobody.** The plan was to hand the bump to `scripts/promotion-step.sh` at the hop; that implementation was built and removed before landing, because the hop's commit slot has to be created by writing a ref and GitHub raises no workflow run from a commit written with `GITHUB_TOKEN` — the bumped head would carry no required check, the script's poll would spend its full wait and exit 1, and the next night would read the same runless SHA, so the promotion would wedge permanently rather than once. Between #588 and #589 the version was therefore raised **by hand at a release**, with no builder owing a bump and no guard checking for one; #589 gave it an owner and the paragraph below records what that owner does. `specs/architecture-principles.md` carries the superseded clause and four dated amendments, the spine's *Repo principles* names `/build` step 1 as the owner and minor as the floor, `skills/promote/SKILL.md` still does not name a version bump as content the release branch may gain, and `skills/build/references/reconcile.md` no longer carves this one value out of the monotonic-field trap by name — it states the general rule instead, that a value both branches compute from a predecessor which cannot move while they run is agreement rather than a collision.

**Who moves it now (#589).** `scripts/plugin-version.js`, run by `/build` step 1 in the new worktree between the worktree's creation and the run-state write — before the first edit of the change being built, so the raise lands inside the tree the gate certifies and the reviewer reads, and no second commit follows the verdict. That ordering is the whole reason `scripts/land.js` is the wrong home despite being the obvious one: a content edit after the certifying gate voids the marker the verdict binds to. The script reads the five homes — `CLAUDE.md` joined them at #558 — out of the **working tree** rather than the index, because its operand has to be the bytes it is about to modify; the shipping-tree claim stays where it was, with the index-reading parity guards running inside the gate over the committed raise. It compares the homes' agreed version against the release branch's `.claude-plugin/plugin.json`, read through `refs/remotes/<remote>/<release>` after a fetch of the whole remote, with the release role taken from `harness.yaml` through `declaredBranches` rather than named in the source. Equal versions raise the minor and zero the patch across every home; an integration version already above the release's writes nothing and reports `already-ahead`, which is what every ticket after the cycle's first sees. A release version above the integration's refuses in one of two ways, told apart by `git merge-base --is-ancestor HEAD <release-commit>`: `stale-base` when the release branch already contains this checkout's HEAD, whose remedy is a rebase, and `release-ahead` when it does not, which is `promotion-step.sh`'s own content-divergence condition. A declared release ref that will not resolve refuses at exit 2 rather than skipping — the `NO_RELEASE_REF` behaviour of the deleted guard is the failure this refuses by construction.

Membership in the home set is **positive identification, never absence**, and that is the property with the largest blast radius here. `/build` step 1 is shipped guidance, so this runs in calibrate, nano-erp and lab-book too, and each of those carries an `AGENTS.md` marker naming the harness version that hydrated it. A writer that raised every `spine:generated` marker it found would rewrite three repos' record of which guidance they run, silently, on their next build. A repo is a plugin source only by carrying `.claude-plugin/plugin.json`, and a marker is one of *this* plugin's homes only where the name it carries equals that manifest's `name`. The absence check is the first thing the script does, before the configuration read and before any network call: measured at review by running the shipping script against `/Users/scottluengen/Code/calibrate` with `--repo`, which printed `no-plugin-manifest` at exit 0 and left that repo's `AGENTS.md` byte-identical (`harness@7.0.0`, unmoved). `tests/unit/test_plugin_version_script.py` holds the same property over a fixture, together with the marker-naming-another-plugin case, and every fixture names a plugin and versions this repo has never published so a hardcoded `harness` or `8` would be indistinguishable from nothing.

The homes are rewritten by **substring**, never reserialized. `.codex-plugin/plugin.json` carries `keywords` and `defaultPrompt` as single-line arrays that `JSON.stringify(…, null, 2)` reflows, which would turn a three-character change into a fifteen-line diff in the first review of every cycle. Only the version's own span moves; interior spacing, the marker's name and the line's whitespace survive byte for byte. Reads parse and writes splice: the plugin name comes from `JSON.parse`, the span from a pattern. The marker pattern is `test_spine_template_parity.py`'s `_BEGIN` with its literal `harness` generalised to a capture and otherwise structurally identical, so no marker that guard can see is invisible to this writer, and it is line-anchored — an unanchored pattern makes a marker quoted inside a sentence a second site, which refuses the home rather than raising it. The manifest pattern collects every `"version": "…"` site and requires exactly one, so a future nested `version` refuses loudly instead of having its first hit rewritten. All homes are read and validated before any write, so a refusal never leaves a partial write behind; the five writes are not atomic as a set, and `homes-disagree` is the refusal the next run gives if they ever diverge.

**The level is minor, and the script never decides otherwise.** The compatibility grammar carried a `patch` level — "wording only, no behaviour change" — from before ADR 0015: with a runtime, a reworded skill body changed nothing a consumer executed, and with the runtime retired the shipped product is prose, so a reworded body is a behaviour change. **#590 retired that level** (the paragraph below), so the floor is now also the bottom of the grammar rather than one step above it. There is no `--level` flag, because a flag would invite a guess at step 1. A raise above the floor is a judgment about the whole diff, so it belongs to the review: `skills/review-discipline/references/certifying.md` gained *The version class*, which puts the version homes in scope for every change that carries them and asks whether the diff exceeds the floor. Verified by use rather than by a wording predicate (law 2; ADR 0017 D5), in two fresh contexts differing only in the diff: a change that flips a hook's verdict from deny to allow returned *raise to major*, and a pure refactor of the same hook — the refusal string extracted into a helper, byte-identical text, identical conditions — returned *the floor is correct*, three times out of three.

**And the floor is the whole grammar now (#590).** #589 raised the floor to minor and left open, in `specs/architecture-principles.md` itself, whether `patch` kept any meaning; #590 took the first of that ticket's three options and retired the level, so the grammar is minor and major. The ground is narrower than emptiness: a level earns its place by the consumer action it names, and only major names one — a decision rather than an auto-pull. Patch and minor both leave the release to arrive on its own, so patch subdivided the half no consumer acts on, and the inert class it was reached for — a comment inside a shipped hook — buys that consumer nothing by being called a patch. The provenance supports it: D3 of the *Merge the guidance repo into the harness* decision, which this grammar derives from, named minor and major and no third level (`d334232`, 2026-06-13, is where the `Patch` bullet entered the restatement instead). Two things it deliberately does not touch, and the distinction is the whole care in the change: the version keeps **three components** — `raised` still writes `X.Y.0` and a review-time major still writes `X.0.0`, so no manifest version, no spine stamp and no parity guard changed — and a reworded body keeps a home on minor, whose condition it already met. Patch's two recorded inhabitants are the argument and they are the whole of it: `6.0.1`, written at `15908d2` (2026-09-01), carried unchanged through `60ec53e` and `971bbdc`, and still the release branch's version at `a609d5b` (2026-09-05) — the very commit the #556 amendment names for telling a consumer it was current over bytes that had changed — and `7.0.1`, the one cycle open three commits wrote over the same `7.0.0` predecessor `f4ecfa7` (`83442ef`, `baa3e82`, `b9aca3d`), raised to `8.0.0` at review (`901e6dd`, and `fa3b8a9` naming that same open from ADR 0018). One caught, one not; neither named anything a consumer could act on. The change is prose in four files — the grammar, this repo's two spine copies' *Repo principles* bullet, and the header comment of `scripts/plugin-version.js` — and it carries **no test**, because law 2's subject is code and a criterion about what a document says has no measuring test (#511, #520). The evidence is the gate plus a reviewer's read of the amended section against the retired bullet, against ADR 0015's retirement of the runtime, and against a re-derivation of the *level, worked* verdict below, which still returns major off the unmoved *interface change* clause. `templates/spine.md` gains nothing: the bullet lives after the `spine:generated` block, in the section each repo owns.

A bump moves five files since #558: the two manifests and the `spine:generated` marker in `AGENTS.md`, in the `CLAUDE.md` derived from it, and in `templates/spine.md`. Since #588 **nothing measures that it happened**. `tests/unit/test_release_version_cycle.py` — 713 lines — compared the index's `.claude-plugin/plugin.json` version against the highest one any locally present release-role ref carried and failed when this tree's content differed from the release tree without a strictly greater version; #588 deleted it together with the obligation it enforced. Its record is that it enforced nothing where it mattered: under `ci.yml`'s bare shallow checkout it found no release ref, reported `NO_RELEASE_REF` and skipped on every `push: dev`, and the one run that did compare — the nightly promotion of 2026-09-06, run 34046398127 — failed `Kind.EQUAL` and stopped the promotion it was written to protect. #580 had just given that checkout `fetch-depth: 0`, which is what would have made it compare on every push instead. The key stays and `ci.yml`'s comment now records why: no gate stage requires it, removing it is an untested change to the one checkout every gate run depends on, and nothing now fails if a later edit re-shallows the clone. `tests/unit/test_nightly_promotion_workflow.py` lost the two assertions that pinned that key and the single-checkout count, both still green at deletion, because the guard they were a precondition for no longer exists. What survives measures **agreement, not movement**: `tests/unit/test_spine_template_parity.py` derives the reference from the manifest, refuses a reference that is not `X.Y.Z`, and fails when the manifest and the two enumerated spine markers disagree, and fails on the third marker through the prefix assertion rather than a fourth operand, with `tests/unit/test_native_codex_plugin.py` holding the two manifests equal. So a bump that happens must be complete across all five homes, and a bump that never happens is invisible to the gate. #589 left that unmeasured on purpose rather than by omission: the writer at `/build` step 1 either performs the raise or refuses loudly at exit 2, and a gate stage re-reading the same two operands would share them with the mechanism it was meant to back up, which is not a second defence (P0, and #580's shared-operand finding).

**The level, worked (#565).** By the time #565 was reviewed, `main` had been promoted to `7.0.0` (`d7f39e4`) and `dev` had already diverged from it (`2aca9b0` and its merge, neither a version-bearing change), so the cycle-start guard above — deleted at #588 — was already failing `EQUAL` before this ticket touched a byte — any tree shipping `dev`'s current content needed a version strictly greater than `7.0.0`, named in the guard's own remedy message. That settles *whether* to bump, not *how far*. The ticket's own change removes `disable-model-invocation` from `digest` and `assess`, which is precisely a *refusal reason changed* under `specs/architecture-principles.md`'s compatibility grammar — a call that `Skill(digest)` and `Skill(assess)` used to refuse now succeeds — so patch ("wording only, no behaviour change") does not fit, and minor is excluded by name (minor requires invocation and refusal reasons unchanged). The candidate as built declared `7.0.1`; the review raised it to `8.0.0` and re-ran the gate green over the corrected tree, on the reasoning above rather than the cycle-start default, which governs only the *first* bump of a cycle and not a later change's own compatibility class.

The shipped inventory, counted at tree `8281ecf` — the tree #547's build produced, and the one every figure below was measured over. `tests/unit/test_landing_page_inventory.py` derives the skill, agent and hook figures from the tracked tree in both directions and holds `docs/index.html`'s printed counts to them, so those three cannot go stale in silence; the remaining rows are a reviewer's count at that tree.

| Surface | Count | Where |
|---|---|---|
| Skills | 17 directories | `skills/*/SKILL.md`, all authored: the 9 lifecycle workflows (`assess`, `build`, `capture`, `drain`, `init`, `promote`, `propose`, `review`, `routine`) and 8 craft skills (`architecture`, `authoring`, `design-system`, `engineering`, `review-discipline`, `tracker`, `work-discovery`, `worktree-isolation`). #547 took the craft set from 15 to 7 and #626 added `design-system`, the first skill to carry copied-out assets; *The skill surface after #547* below records every merge and every deletion with its reason. A workflow is the subset whose `description` opens with the slash trigger it answers to — the shape `tests/unit/test_native_codex_plugin.py` derives rather than lists. `tests/unit/test_landing_page_inventory.py` derives the inventory and the page's printed counts from the tracked tree. |
| Agents | 5 files | `agents/*.md` (`architect`, `dev`, `reviewer`, `reviewer-feature`, `steward`). `reviewer-feature` arrived at #547: a body that defers to `agents/reviewer.md` in full over two lines of frontmatter that buy the deeper model |
| Configuration | 1 file | `harness.yaml` at the repo root, read by one shared reader, `scripts/harness-config.js` |
| Hooks | 6 scripts | `hooks/*.js`, auto-discovered from `hooks/hooks.json` by both manifests via `${CLAUDE_PLUGIN_ROOT}`; `hooks/package.json` pins CommonJS |
| Templates | 11 files | `templates/*.md`, `templates/harness.yaml`, and `templates/rules/design-system.md` (#547) — referenced from the skill bodies as their assets (e.g. `authoring` → `templates/change.md`, `init` → `templates/harness.yaml`); the physical directory is shared rather than per-skill |
| Path-scoped rules | 3 files | `.claude/rules/*.md`, each with a `paths:` frontmatter of globs: `scripts.md` (scoped to `scripts/**`, `hooks/**`, `tests/**`), `design.md` (the design directory and `docs/**`), and `design-system.md` (#547) on those same two globs. Since #626 the design glob reads `skills/design-system/assets/**` in this repo, because that is where `harness.yaml`'s `paths.design_system` now points; `scripts.md` also names `skills/design-system/assets/build_design_tokens.py`, the one Python file this repo owns outside `scripts/` |

How and what follows ADR 0017 D3's pattern: the skill body states the method, a plugin asset argues it (`skills/engineering/references/principles.md`; `skills/review-discipline/references/craft.md` is the running precedent), and a repo-owned asset records local reality (`specs/architecture-principles.md` for design, `specs/infrastructure.md` for operations, the spine's *Repo principles* section for build). Two skills carry it since #547, not three: `engineering` for build and `architecture` for design. The `infrastructure` skill was the operate leg and is deleted — `/promote` already transcribed the whole promotion loop and cited the skill exactly once, in a parenthetical, so the skill was a second copy of a procedure the workflow owned. The three obligations it alone held moved into `skills/promote/SKILL.md`: the back-merge after the release hop, *the tree that lands equals the tree the gate certified* where a protected target forces a pull request, and the reserved exit code separating an infrastructure failure from a red tree. The repo-owned *what* stays in `specs/infrastructure.md`, where it already was.

### Evidence follows its subject

ADR 0019 is the one evidence contract. The spine carries its full subject matrix; architecture principles, authoring, engineering, review, the build procedure, roles, and templates cite it and state their own action. Executable behaviour and mechanically enforceable invariants retain RED then the smallest GREEN. A runtime or compatibility floor has a declared floor and functional execution on every supported environment; configuration and generated artifacts use a validator, producer check, or smoke without duplicate consumer suites. Prose is reviewed or used directly, never judged by a predicate or wording guard, and an unobserved preventive guard requires a recorded risk decision. The prose discipline is `skills/authoring/references/prose.md` since #547 folded the `writing-quality` skill into `authoring`: the minimum effective edit, the author's terminology and cadence preserved, and a sentence carrying no decision, constraint, evidence, action or necessary context cut. Developer and reviewer roles load that reference immediately before substantial handoffs and review reports; `/build` and `/capture` load it before authoring change specs, while short status and structured output stay outside it. A criterion may change before implementation only with evidence, a smaller replacement, owner approval, and a tracker amendment; it is never silently descoped.

### Landing-page muted text

The source muted token is `#656d8c`; the generated `--muted` declaration in `docs/index.html` resolves from it through `color.semantic.text.muted`. Normal-size muted text meets WCAG 2.1 AA's 4.5:1 contrast floor on the page background, white cards, marker panel, and both body-gradient endpoints. `tests/unit/test_build_design_tokens.py` measures those five rendered surfaces, while `skills/design-system/assets/build_design_tokens.py --check` (relocated from `scripts/` at #626) keeps the page's generated token region aligned with `tokens.json`.

### Landing-page install layout

The self-contained public page keeps three install cards above its existing 780px breakpoint and one below it. The `.install` grid uses `minmax(0, 1fr)` tracks and `.step` permits shrinking, so long commands cannot widen the document; each command block remains horizontally scrollable within its card. Ticket #534's browser captures at 1440, 834, 781, 779, and 390 CSS pixels recorded no document-level horizontal overflow after this containment change.

### The spine

There is **one** always-loaded spine, `AGENTS.md`, and both hosts read it; `CLAUDE.md` carries the whole of `AGENTS.md`, byte for byte, followed by the deltas that apply on that host alone and nothing else (#558, reversing #537's pointer). *The host copy* below records that contract, its guard, and what the copy costs. It is no longer a compiled artifact — nothing generates it, and this repo's copy is 85 lines at #588 against the 120-line ceiling the ticket set. The spine carries, in order, the **operating context** #588 put ahead of everything else — pre-user, pre-revenue; speed and simplicity as the route to quality rather than a trade against it; and a four-line risk appetite whose two refusals are the only protected areas there are, user data, credentials and money; then **P0 Do less**, which takes precedence over the five principles behind it in any conflict (build quality in · reduce waste · flow · stop the line · continuous improvement), each stating what it refuses; the **laws** derived from them, one obligation per line with the rationale in an HTML comment beside it; the lifecycle (a fix / a ticket / a proposal); the shared contract (ticket states, holds, the three lanes, the PASS/FAIL/DEFER verdict vocabulary, the tree-oid binding, configuration, tracker dispatch, the queue and its limit, filing rules); and an enforcement summary. Each repo restates its own stage in one repo-owned line under *This repo* — this one's reads *Stage: pre-user, pre-revenue. Posture: speed and simplicity; a wrong change costs a revert. Protected: user data, credentials, money.* — and that line is what the generated paragraph is read against on the day a product gains a user. It carries **no configuration** — that moved to `harness.yaml`, and the contract's *Configuration* bullet names the file rather than restating a value from it. Skills are conditional depth behind the spine and may assume it is loaded. The generated block sits between `<!-- spine:generated:begin … -->` / `<!-- spine:generated:end -->` markers and is byte-identical to `templates/spine.md`'s block — held since #489 by `tests/unit/test_spine_template_parity.py`, which extracts the delimited region of `AGENTS.md` and of the template from the git index and fails in either direction, anchoring on both the `## Principles` and the `## Laws` headings so an extraction reaching one of them is not mistaken for reaching the block. Everything after an end marker is repo-owned.

Guidance that matters only in one part of the tree lives in `.claude/rules/<name>.md`, with a `paths:` frontmatter of globs, and loads only while a matching file is open — narrower than the spine, never a cheaper spine. This repo ships three: `scripts.md` for `scripts/`, `hooks/` and `tests/` (stdlib-only Python, the no-dependency rule for the shipped JavaScript, the hook fail-open posture, ADR 0018's no-per-invocation-source rule, and *a guard asserts a property of the tracked tree, never the working directory* with its one named carve-out), and two on the design directory and `docs/` that split by subject: `design.md` carries the token-source relationship, and `design-system.md` — seeded at #547 from `templates/rules/design-system.md`, repo-owned since — carries the craft, the states checklist, accessibility, and the visual-evidence capture rules that used to sit in `skills/build/references/visual-evidence.md`. Its visual-evidence rule carries one carve-out since #608: a text-only diff — every changed line altering only the characters inside a string or text node, with no element, attribute, class, style, token, layout value or conditional touched — renders no evidence, while an unclear case, or a string whose element already constrains its length (a capped width, a single-line or truncating rule, a control sized to its label), still does. The carve-out landed in all three homes at once — `.claude/rules/design-system.md`, `templates/rules/design-system.md`, and `design/AGENTS.md` — whose shared region from the first `##` heading stayed byte-identical. Codex has no path-scoped rules, so where the design layer is on `/harness:hydrate` seeds the equivalent nested instruction file inside the design directory, which Codex reads nearest-wins; this repo's is `skills/design-system/assets/AGENTS.md` since #626 moved the design directory there.

#### Scenario: the fix lane

- GIVEN a small fix that changes no documented behaviour, spans one commit, and needs no independent review
- WHEN an agent is asked to "fix X"
- THEN it works on its own branch in its own worktree, runs the gate, and ships without a ticket — no command carries the fix lane, and the hooks enforce exactly as for ticketed work.

### The host copy — `CLAUDE.md` carries the spine verbatim (#558)

`CLAUDE.md` is the whole of `AGENTS.md`, byte for byte, followed by the deltas that apply on Claude Code alone. The boundary the guard asserts is positional, at character `len(AGENTS.md)`, and everything past it is repo-owned. #594 writes a `<!-- spine:copy:end -->` line at exactly that position, but it delimits nothing for the comparison — it is hydration's recovery locator, and *The boundary marker* below is where it earns its place. `AGENTS.md` stays the source and the file Codex reads, so the copy is derived from it and never the reverse. #537 had reduced this file to `@AGENTS.md`; #558 reverses that, putting the spine's bytes in the file the host loads instead of arriving through an import the repo does not control. Measured at capture, the `@AGENTS.md` line did resolve and inline on this host, so the change buys independence from that behaviour rather than recovering a load that was missing.

`tests/unit/test_spine_template_parity.py` holds the relation. `derived_spine_divergence` reads both operands from the git index, asserts the prefix with no normalisation, and reports the first differing character, its line, and a unified diff over the copied region. It refuses three degenerate pairs rather than passing them: an empty or whitespace-only source, which is a prefix of every file; an empty derived file; and a remainder with no non-whitespace content, the shape a hydration that dropped the host deltas leaves behind. The assertion is a prefix rather than the delimited-block comparison the module already carried, because comparing the generated block alone would pass a copy whose repo-owned tail had drifted from the spine's.

The prefix carries a second load. `version_disagreements` still enumerates three homes and excludes `CLAUDE.md`: a byte-exact prefix makes the copy's `spine:generated` stamp agree by construction, so a fourth operand would measure one fact twice (#492). That subsumption fails under containment, which is why `test_content_above_the_copy_is_a_divergence_not_a_containment` pins the relation with a copy sitting below frontmatter. Weakening `derived.startswith(source)` to `source in derived` reddens that row and nothing else, measured at this review.

**The version home the copy creates.** `scripts/plugin-version.js` gained `CLAUDE.md` in `CANDIDATES`. Without it the cycle's first `/build` would raise `AGENTS.md` and leave the copy behind at the version line, the one line every raise touches, and the prefix guard would then red the gate for every later build in that cycle. Measured on the merged tree before the fix, the copy stamped `harness@7.0.0` against `8.1.0` in the other markers. Measured again at this review by a staged probe: staging a copy whose only divergence is the version line reddens three rows, names character 402 at line 5 and prints the remedy, and reverting the index re-derived tree `be20f613` byte for byte. Membership is earned as every other home earns it, so neither control fires wrongly — a pre-#558 pointer carries no marker and is skipped, and a repo with no `CLAUDE.md` has one fewer home rather than a missing one, both pinned by `tests/unit/test_plugin_version_script.py`.

**~~`--refresh` re-derives the copy, and classifies before it writes.~~** Retired at #624 with `skills/init/references/refresh.md`. The procedure that paragraph recorded read `AGENTS.md` before the generated block was replaced, called that text `A_old`, and located the boundary with it, then sorted a host file into five states: a **pointer** expanded without asking, a **derived copy** — bounded, or prefixed by `A_old` — re-derived, a **drifted copy** with no usable boundary marker left untouched and `blocked` with the offset at which it first differs, a **legacy second spine** spliced and version-stamped in place, and anything else `blocked` as boundary unfindable. The asymmetry it was ordered on is kept as history because it still holds: misrouting a legacy spine into retain-and-report costs one stale block reported on every run, while misrouting a drifted copy into the legacy branch overwrites repo-authored bytes silently. `skills/hydrate/SKILL.md` step 12 replaces it with four states — absent `written`, bounded `rewritten`, pointer `rewritten`, anything else `blocked` — dropping `A_old` and both branches that needed it. Those two existed to find a boundary in a repo the plugin had been rewriting by byte comparison, and nothing is vendored to rewrite. The `<!-- spine:copy:end -->` line stays the only locator, and its mandatory overwrite report — every line in the copy region `AGENTS.md` does not carry, verbatim, or the words saying no such line exists — stays the reason a hand-placed marker is safe to trust.

**The boundary marker (#594).** `A_old` locates the boundary only while the copy is still correct, so the first edit to either file destroyed the one thing that could delimit the deltas and the copy reached `blocked` until a human re-derived it. The spine's own contract tells every consumer to edit `AGENTS.md` under *This repo*, which made that the ordinary case rather than the edge — measured at #558 by probe. `CLAUDE.md` now carries `<!-- spine:copy:end -->` alone on a line at the end of the copied region, written by every state that produces the file, and a copy carrying exactly one is re-derived however far the region above it has drifted. Recognition ignores surrounding and interior whitespace and requires the comment to be the whole of its line, so a mention inside a sentence delimits nothing; two or more anchored occurrences leave the file unbounded, because one may have arrived inside the copy and one may sit in the deltas and nothing can tell which is which. That case blocks with a one-line remedy — delete the wrong one — rather than the hand re-derivation the marker-less case still needs.

Trusting a declaration means a re-derivation can overwrite bytes above the boundary, so *Reporting an overwrite* makes the write name what it replaces, in three branches that are never allowed to read alike: equal, and it says nothing repo-authored was overwritten; differing, and it lists verbatim every copy-region line the refreshed `AGENTS.md` does not carry, with the first-difference offset and a pointer at `git diff` for the rest; differing with nothing absent, and it says in those words that the copy had only fallen behind. The third branch exists because an empty listing and an unexamined one are otherwise the same report.

Measured at this review by five direct-use probes, each a fresh context executing the shipped `refresh.md` against a fixture repo, and each paired with a control that had to differ. A bounded copy whose region had drifted classified **derived copy** and `rewritten`, and listed the one line leaving the file verbatim with its offset; the same fixture with the marker removed classified **drifted copy** and `blocked`, which is the pair the whole ticket turns on. An unbounded but undrifted copy was re-derived and came out carrying one marker where its input carried none, which is the migration path. Who walks it is narrower than the ticket assumed: #558 and #594 land in the same unpromoted cycle, so no released version ever produced a marker-less copy, and the path serves a repo hydrated mid-cycle from the integration branch rather than a released consumer. It is owed anyway — a hydration can be taken from any tree — and it is the only thing standing between such a repo and a permanent block. A bounded, undrifted copy run twice produced byte-identical output both times and one marker, not two — the failure mode where the deltas are read to include the boundary and each run lays down another. A fifth fixture carrying two markers blocked with the ambiguity reason and the one-line remedy rather than a hand re-derivation, and a legacy second spine and a file that is neither still reached states 4 and 5. Every fixture's classification and action word was decidable from the prose without inference, the state tests walked in the order the prose sets; two probes independently flagged one seam that is not, recorded under *Known limitations*.

**What the guard did not need.** `derived_spine_divergence` is unchanged: the marker lands in the remainder, at `len(source)`, which the predicate already treats as opaque, so all three clauses hold as written and the `version_disagreements` subsumption above is unmoved — the relation asserted is still a prefix, and the marker carries no version. `test_the_host_file_marks_where_the_copy_ends` is the new sweep: it reads the marker positionally as the first line of the remainder rather than by containment, which would pass for a marker sitting anywhere including inside the copy, and requires exactly one occurrence, which is what makes this repo's own copy bounded and subsumes "`AGENTS.md` carries none" — the spine is a prefix of the copy, so an occurrence there would be a second occurrence here. Measured at this review by a staged probe: staging a marker-less `CLAUDE.md` reddens that row and no other, and restoring the bytes re-derived tree `49e46762` exactly. Two synthetic samples carry the teeth, and both were mutation-proved here. A drifted copy carrying a well-formed marker is still reported, so the relaxation the ticket invites — returning `{}` for anything containing the marker, on the reasoning that a later hydration will re-derive it — is killed; that mutant also reddens the paired-splice row, so its killer is not the exclusive one the sample's docstring claims, which understates the coverage rather than overstating it. A copy with an extra line above a well-formed marker is still accepted, which exclusively kills every reimplementation that locates the copy region by the marker instead of by position. Those two answer different questions on purpose: the gate says the copy is correct now, and the marker says where a later hydration starts from.

**~~One refusal guards the configuration reader.~~** Retired at #624 with `--refresh`, and both of its operands had gone first. It refused to expand or create the copy where `AGENTS.md` still carried a qualifying fenced `yaml` block, because `scripts/harness-config.js` reads `CLAUDE.md` as a configuration source and `gateCommand` took the first source that *existed*, so a copied fence would have been a second declaration of what may mint gate evidence. #621 deleted `gateCommand` with the marker, and #624 deleted the configuration-migration step whose state the remedy branched on. `skills/hydrate/SKILL.md` step 12 copies `AGENTS.md` whole, fence included; what survives in the reader is the searching rule, which takes the first source that *declares* a key, and `AGENTS.md` precedes `CLAUDE.md` in that order, so the copy is never read in preference to the source it was taken from. This repo's spine carries no configuration, so its copy declares none.

The cost is the second copy P2 refuses, in this repo and in every repo hydrated after it, including a duplicate of the consumer's own repo-owned spine tail. What pays for it is P1: the sync obligation moves from a documented convention to a byte comparison that can fail a landing. That payment lands in this repo alone, which is the *Known limitations* entry below.

**Both host-file shapes are valid, and one of them is where a hydrated repo lands (#592).** An `@AGENTS.md` bridge plus deltas and the byte-identical copy this derivation writes both work as the host file, and neither is an audit finding — two consuming repos were measured keeping the copy and pinning it with a test of their own for their `/build --engine codex` path, and calling that a deficiency was the audit error the decision corrects. What the plugin does **not** offer is a choice between them: the pointer state expands a pointer into the copy *without asking*, so the copy is where a hydrated repo lands and a repo pinning it is in the shape it means to be in. The decision as taken said refresh "offers the reduction and never performs it"; the pointer state has read *Expand without asking* since #558, and `skills/hydrate/SKILL.md` step 12 carries it forward unchanged — the shipped sentence records the mechanism rather than the decision's premise about it, a departure found at #592's first review cycle, where it had shipped the premise.

### Lanes, intake, and the andon cord

Since #538 that lane has a name the rest of the contract uses. The spine's **Lanes** bullet replaces the old assurance-level list: one lane per ticket, chosen at filing, carried as the same `assurance:<level>` label, and **upgrade-only** — **fix** (`trivial`), **change** (`simple`), **feature** (`complex`). The fix lane's whole assurance is the gate and the push guard: no ticket, no reviewer sub-agent, no as-built record (the accepted proposal's D2). `skills/authoring/SKILL.md` chooses the lane by blast radius and states what earns the fix one — a diff describable in one sentence that touches no protected area and adds tests without editing any — and states why the trade is worth taking: a lane nobody can afford is a lane every one-line fix routes around, which erodes the boundary for the changes that genuinely need a review. The repo-supplied `assurance.trivial_certify` allowlist command that used to earn `trivial` is retired with it; neither `harness.yaml` nor `templates/harness.yaml` declares an `assurance:` block, and no shipped skill names the key.

**A protected area is a tripwire, not a scope note.** Since #588 the list is three and closed — user data and its migrations, credentials and auth, money and billing — because those are the three losses the operating context says this stage does not accept, and anything else on such a list is inherited from a posture this repo is not in. A **directory** is not a protected area: `hooks/` and `scripts/` came off the list, and what decides the lane there is what the diff changes — a decision takes the feature lane, a message, a comment or a test-only edit takes the fix lane. A repo whose own stage line declares a later stage names its own additions there. `templates/change.md`'s *Protected areas* section says the same thing to a filer. A diff that reaches one stops and holds (`input`, assigned) whatever the lane says. Raising the lane is not an alternative to that hold; it is what the operator does when releasing it. What trips it is the **diff**, so a ticket may name an area its diff never touches, and a diff may reach one the ticket never named.

**The feature lane is priced on blast radius, not on provenance (#597).** The *Lanes* bullet's third trigger read **anything a proposal spawned**; it now reads **a consequential decision its proposal did not settle**. Foundations-first ordering is what made the old wording wrong rather than merely broad: once a proposal settles its shape in item 1 (#595, below), the items downstream of it carry *less* design, not more, so holding all of them at `complex` bought an independent design pass for work whose design the proposal had already recorded — P0's "an assurance calibrated for a stage the product is not at". Nothing else in the paragraph moved: a contract change and a protected area still take the lane, the tripwire still stops and holds, "uncertain is `simple`" and upgrade-only still hold, and the `hooks/`-and-`scripts/` sentence is untouched. Decided as D3 of `specs/proposals/do-less-at-ingestion.md` and recorded in the *Lanes* paragraph itself rather than as an ADR: `paths.decisions` holds what is expensive to reverse, and one clause of a lane rubric is cross-cutting but cheap to revert. The narrowing only ever lowers a lane, so no call a consuming repo makes is refused that used to succeed and none succeeds that used to be refused — the cycle's raise stays at the minor floor rather than reaching the major a changed refusal reason would force (`specs/architecture-principles.md`).

**The clause has four homes, and the spine names the fourth (#597).** Three are the `spine:generated` block — `templates/spine.md`, `AGENTS.md`, and the `CLAUDE.md` derived from it — held byte-identical over the index by `tests/unit/test_spine_template_parity.py` on every gate run. The fourth is `skills/authoring/SKILL.md`'s *Choosing assurance* table, which the spine's own sentence delegates the operative choice to ("`authoring` chooses the lane") and whose `complex` row closes with "the spine's three, and no fourth". Leaving that row on the old wording would have made its own closing clause false and left the mechanism a filer actually consults on the retired rule, so moving it is the twin sweep discharged, not scope widened; the edit changes that clause and no other cell. Both filing paths make that concrete: `/capture` and `/propose` each choose the level per `authoring` → *Choosing assurance*, the first adding "never restated here", so nothing reads the spine's bullet to price a lane and a spine-only edit would have shipped inert. The evidence is ADR 0019's for prose — direct review of the four files, plus representative use over the tickets the source proposal spawned: priced against the new rubric #596 is `simple`, which is the label it was filed under and the one the old clause contradicted; #595 stays `complex` on its contract change, so the narrowing does not lower every proposal-spawned filing; and #597 itself is the discriminating case, a ticket whose design D3 settled, where the narrowed clause does not fire and a different trigger holds the lane at `complex` anyway.

**One twin was deferred, and naming it is the deferral (#597).** `agents/reviewer-feature.md` and `.codex/agents/reviewer-feature.toml` still carry the retired wording twice each: the `description` frontmatter reads "a contract change, a protected area, or anything a proposal spawned", and the body repeats the same three-item list in its own words a few lines further down. Neither is a dispatch predicate — `/build` and `/review` choose between `reviewer` and `reviewer-feature` from the ticket's lane label, and that sentence explains why the deeper model is paid for — so the staleness changes no consumer behaviour and is an improvement rather than a bug (`review-discipline` → *Bugs are filed; improvements are proposed*). It is left to the next change that opens those two files.

Intake carries the upstream half. `/capture` gains a **clarification loop with a stop condition rather than a cap**: keep asking while any question remains whose answer would change the architecture, a contract, the data model, the test design, or what the change will explicitly not do; rank by impact; integrate each answer into the spec as it arrives, replacing the sentence it supersedes. Attended that is `AskUserQuestion`; unattended an unanswerable question is a hold, and a material question that should not block the filing becomes an inline `[NEEDS CLARIFICATION: …]` marker, which `/build` refuses to start on. It also gains the workflow's **one refusal**: a filing without a **cost line** — what it costs, what it buys, which principle it serves and which it spends against, and which waste it removes or adds — is incomplete and is filed as nothing until it can state one, because cost is uncomputable later, when the spend is sunk. `templates/change.md` carries the matching sections: **Cost** with its one-line shape, **Assumptions** (decisions taken without the authority to take them, `none` where there are none), **Protected areas** (never omitted — a blank section and an absent one read the same, and only one of them means the question was asked), the **Assurance** heading renamed **Lane**, the verb-plus-where title convention, and the marker's meaning.

`work-discovery` gains **Andon**, checked ahead of ranking: an open ticket that the tracker's own fields say is a **bug** at **top priority** is the only pick until it is closed. The check reads the open queue in **every** state rather than Todo alone, because a P1 bug somebody is already fixing is still the line stopped, and both halves come from the tracker's fields — never from a ticket's prose claiming urgency, which is text anyone who can open an issue may write (law 6). Two consequences are stated where they would otherwise be dropped: a **held** P1 bug is still the cord, so the loop reports the stopped line and stops rather than reaching past it; and a cord that is not actionable stops the tick rather than falling through to the next candidate, which is how an andon rule quietly becomes a ranking tweak. `/routine` step 1 names the same rule, and an attended `/build` on any other ticket reports the open P1 bug before it starts — it does not refuse, because an operator who names a ticket has the authority to build it, but silence would waste the signal. #588 narrowed what earns the cord to a hook or script that **refuses correct work or lands wrong work**, and nothing else: a rough edge, a confusing message, or a hook merely wrong about something nobody is blocked by is a P2 bug on the queue, because a repo whose cord is pulled by every misbehaving script has no cord.

**The queue is bounded, and one step performs the pull (#588).** `queue.wip_limit` (default 6) bounds a project's Todo, In Progress and In Review tickets with held ones excluded; `queue.active_projects` (default 3) bounds how many projects may have anything in flight; and `queue.project_field` names the tracker field a ticket's project is read from — `project` for Linear, `milestone` for GitHub — or declares that the repo is its own single queue, which is what this repo declares. **Backlog** stops meaning *existence uncertain*, which is what the improvement ledger holds, and becomes confirmed work waiting for a slot, ordered by dependencies then priority. What the bounds govern is what *enters*: `tracker`'s `create` grows from four mandatory elements to five — the fifth is the ticket's **project**, inherited from the parent where the filing comes from inside a build — and its existing placement step stops meaning *Todo* and starts meaning Todo where the project has a free slot and Backlog where it has none, a breakdown files its first `wip_limit` into Todo and the rest into Backlog, `/assess`'s drain folds only into Backlog and drops by default, and starting a ticket already in Todo is never blocked by a limit. `work-discovery` gains *The limit*, run after the andon check and before ranking, and it is the only step in the loop that moves a ticket out of Backlog: count, normalise a project over its limit by moving its lowest-ranked Todo tickets to Backlog, pull the highest-ranked eligible Backlog ticket while a slot is free, then rank. Without it the redefinition of Backlog would be one-way — filings and folds enter and nothing carries them back out — so the step is what makes the reservoir a queue rather than a second ledger. It does not run under a stopped line, because a stopped line moves no tickets, and the cord itself is filed into Todo whatever the count with nothing demoted to make room. `/digest` printed the numbers per project beside the R line, and #627 retired both with the console; nothing prints them now (*The console retires into a drain* below). **None of this is enforced mechanically**: the limit is guidance a run performs, and the only code the change adds is the reader that returns the keys.

**One improvement channel (#588).** The reviewer's Proposals section is gone from `review-discipline`, its evals, `skills/review/SKILL.md` and both hosts' reviewer agents; the 2×2's non-blocking/large cell now reads *let it go — say nothing*, and the one thing that still leaves a review is a **blocking** finding that is not this ticket's. The builder's three-line reflection is the single channel out of a build. A bug also gains a second half: the tree contradicts its own contract **and** the contradiction breaks a user outcome or a consumer behaviour that can be named — a stale comment, a wording mismatch, or a test asserting the wrong thing is an improvement, not a bug. `templates/change.md`'s cost line gains a **guard-to-change** figure and `engineering` states the bound: above 3 : 1 a guard needs a recorded reason naming the user outcome it protects at this repo's stage, and a mutation table is not that reason, because it says the guard works and never that it was worth writing.

### The proposal tier — a scope boundary, a decision gate, and foundations-first ordering

**A proposal records what it decided against (#595).** `templates/proposal.md` gains a **Not doing** section between Recommendation and Open decisions: one line per capability — what it is, why it is out, and the trigger that would reopen it — whose raw material is the options rejected above plus whatever the decision cut. Options records the alternatives considered and Not doing records the capabilities cut; the second is the set that leaked, because the boundary was drawn later, one ticket at a time, by an agent reconstructing it from the recommendation. It binds in both directions: a spawned ticket cites it in its `Out of scope` instead of re-deriving the boundary, and nothing named there enters a spawned ticket without amending the proposal first — the mirror of the no-silent-descoping rule `authoring` already states for criteria. `skills/authoring/SKILL.md` → *Proposal spec* carries that rule; `skills/propose/SKILL.md` step 2 fills the section from the options the run actually rejected.

**The breakdown is ordered by cost of being wrong (#595).** "Each sized to ship alone" is retired as the breakdown's ordering rule in both places it appeared — `authoring`'s section list and `/propose` step 2 — and `templates/proposal.md`'s Breakdown note is rewritten to match. Dependency decides the order, and where the work introduces a shape that is expensive to unpick, that shape is item 1, held for the operator, with the items building on it declaring a dependency on it. It is a real change rather than a spike: it ships the shape as an executable artefact — types, schema, migration, interface — with the tests that hold it, and records the decision in the spec it governs, so it ends on a pass/fail signal rather than on the model feeling finished (P1). Four dimensions decide whether a shape earns that position and any one of them fires it — **migration**, **blast**, **access**, **comprehension** — set out in `authoring` as a table with a *does not fire* column beside each, because a trigger written narrowly enough to cancel itself is the failure the source proposal (`specs/proposals/do-less-at-ingestion.md`) names as the one this change most needs to survive. Three of the four are stage-independent, so the test fires regularly at this repo's stage: the stage line calibrates how much gets built, not whether the shape gets decided. `/propose` step 4 files in that order, declares each item's dependency, and holds the foundations item through `tracker`'s `hold` operation with the `input` label where the test fired.

**`/propose` stops at a decision it can point to (#595).** Step 3 was *Get a decision*, a heading naming an action the run completes; it is now *Hand it over, then wait for a decision*, and the run ends there. It hands over two things — the completed spec and a shareable rendering of it, published wherever the host can publish one — sets `status` to `under-decision`, and advances only on an explicit act against the proposal as written. An answered clarifying question is not that act, and neither is engagement with the content, silence, nor a direction chosen on a single open decision. Step 4 files tickets, so a run that reads clarification as approval creates work nobody agreed to and consumes queue slots holding it — the failure observed in the run that authored the source proposal. No new machinery buys this: `under-decision` was already declared in `templates/proposal.md`'s status vocabulary and written by no skill, so the gate is an existing state given meaning (P2, native first), and the template's Lifecycle block now says what it means, between `draft` and the three outcomes. The rendering is stated capability-neutrally because Codex reads the same skill file: where the host cannot publish one, the run says so and the proposal file is the rendering, the same degradation as `tracker: none`. **The host-specific half lives in `CLAUDE.md` alone** — an **Artifact** here — and `skills/propose/SKILL.md` names no mechanism, vendor or URL scheme.

**No guard, and no measurement (#595).** Both refused in that proposal and carried into the ticket's *Out of scope*: P2 refuses a guard over prose and law 1 sends prose to review rather than to a predicate, so a filing-time check on either rule would assert that a heading has bytes under it; a `spike` assurance level is refused because the lane axis is blast radius while a spike is a statement about scope, and the hold contract already stops a run for an operator decision. The evidence is ADR 0019's for prose — direct review of the four files, plus representative use: a paired `/propose` run in a fresh context, differing only in the operator's last message, held at `under-decision` on an answered clarifying question and advanced only on a message naming the proposal and approving it, and a third run ordered a four-item breakdown foundations-first and held item 1 with `input`. The spine's *Lanes* clause was narrowed by #597, recorded above under *Lanes, intake, and the andon cord*, and `/capture`'s stop condition gained its half in #596.

### Configuration, and the one reader

`harness.yaml` at the repo root is the repo's configuration: `repo:`, `tracker:`, the tracker address block, `stack:`, `commands:`, `branches:`, `loop:`, `queue:` (#588), `layers:`, `paths:`, `env:`. Before #537 the same map was a fenced `yaml` block inside the spine's prose, and three hand-rolled parsers read it — `declaredBranches` in each of the two enforcement hooks, and the `commands.verify` reader in `scripts/gate-marker.js`. #487, #488 and #510 are each a bug in one of the three that the other two either shared or were spared by accident. The migration into the file was a **verbatim move**, and #624 deleted the step with `--refresh` itself: it took the fenced block byte for byte — comments, blank lines, key order — wrote it as `harness.yaml`, replaced the fence with a pointer, reported the key-by-key diff and stopped on any difference. `skills/hydrate/SKILL.md` step 3 writes `harness.yaml` from the interview where the file is absent and retains it whatever it says where it is present, so a repo still carrying a fenced block is interviewed rather than transcribed. A move cannot lose a key the plugin does not itself read — `conventions`, measured at this tree — nor flatten a shape it reads but never rewrites, such as the list of mappings an `architecture_watchlist` nests; a translating migration could do either. This sentence listed `tools` and `architecture_watchlist` among the unread until #561 measured them: `skills/tracker/references/linear.md` reads `tools.linear_cli`, and `skills/architecture/SKILL.md` reads `architecture_watchlist.files`. #592 removed `tracker_address` from it on the same ground: that recipe now reads `tracker_address.team`, but **only** where the workspace-scoped `teams` query returns more than one node, so the key is *conditionally* read — an override for the ambiguous case, alongside the cached state UUID that was already one — rather than unread. The same change retired `repo.linear` from the recipe's read set entirely, and `--refresh` reported it in the declared retired list beside the three `loop:` keys; a repo keeping it as a documentary pointer to its workspace URL was unaffected. **#624 dropped that report with the flag that carried it**, and the *Decision* below on the declared retired list now records a behaviour the tree no longer has. The drop is recorded rather than filed: an unread key is inert by construction — the reader ignores what it does not name, and `templates/harness.yaml` says keys the repo invents are kept as written — so what a consumer loses is a notification, not a working configuration.

All three parsers are now one module, `scripts/harness-config.js` — CommonJS, Node standard library only, no dependency. The hooks reach it as `../scripts/harness-config.js` from `__dirname` and its `scripts/` siblings as `./harness-config.js`. Until #621 the marker helper was the second of those siblings and `/harness:init` materialized the two into a consumer **as a pair**; ADR 0022 point 1 abolished that and the helper is deleted, so nothing is materialized and the module runs from the plugin root. Its source list is `harness.yaml`, `AGENTS.md`, `CLAUDE.md`, `CONTEXT.md`, in that precedence order, because a repo that has not migrated must keep working on the day this lands: one reader, several sources, is still one reader. Until #621 the two callers read that list by **different rules, on purpose**, and the difference was failure economics. What survives is the searching rule: `branches:` and `paths:` are searched — the first source that *declares* the key answers, and a source that exists but is unreadable or declares it in an unparsable spelling is reported on stderr and stepped over — because a missing declaration falls back to a conservative set that over-protects, or leaves a lock inactive. The other rule left with `gateCommand`: `commands.verify` took the **first source that exists** and refused (exit 3) if that one could not be read, because an ambiguous gate command decided what could mint evidence and must fail closed rather than shop for a second opinion.

The RED the extraction was built on is security-relevant and was live in both hooks: they cut a value at the first `#` anywhere in it (`raw.indexOf("#")`), while yaml opens a comment at `#` only when whitespace precedes it. So `integration: dev#1` declared a branch named `dev#1` and both hooks read `dev` — the push guard did not recognise the repo's own integration branch as protected. The marker helper's reader already handled it (#510); the fix is that there is now one reader and it is that one, and since #621 it is also the only one. #436's two stated reasons for declining a shared `hooks/lib/` are held rather than overturned: the module sits under `scripts/`, outside the non-recursive `hooks/*.js` scans that `test_hooks_fail_open_is_loud` and `test_hooks_module_type` perform, so those guards keep their meaning; and a module that cannot be **loaded** degrades a hook to the conservative fallback — never an empty set, which is a guard that has quietly stopped answering — measured by `tests/unit/test_harness_config_reader.py`, over the one branch-reading hook that survives #621 rather than over two. That load failure is also *loud*: `require` inside a `try` is a Class A site for `test_hooks_fail_open_is_loud`, so a silently swallowed load failure (the #302 shape) is red. `queueSettings` joined the map readers at #588 and is the one home for the queue's defaults: it fills 6 / 3 / `none` where the repo declares nothing, returns the two counts as **numbers** because every caller compares them against a count and raw strings would compare `"10"` below `"6"`, falls back to the default for any value it cannot read as a positive integer rather than handing an unusable bound to each caller, and reads a per-project override as the single flat key `projects.<name>.wip_limit`. Admitting that key widened the `PAIR` and `FLOW_PAIR` key patterns by one character, the dot, which can only make a previously unreadable line readable — no line that parsed before parses differently. A genuinely nested `projects:` block is refused whole by `blockMap`'s existing indentation rule and reported through `onUnreadable`, so an override the repo did declare is never silently dropped for a half-read map. No environment variable may redirect the module: an earlier draft reached it through `HARNESS_CONFIG_DIR`, which is a per-invocation source for the gate command and ADR 0018 forbids it — `test_the_gate_command_can_only_come_from_a_file_the_tree_carries` caught it, the variable is gone, and that guard now follows the read across the `require` boundary rather than going blind where the work moved (#510's shape).

**Decision — the refresh report declares the retired keys; it does not derive them.** *Decided 2026-09-07 by the operator, built as #561.*

**Context.** A consuming repo's `harness.yaml` outlives the mechanisms it configures: a move preserves every key, including keys whose feature the plugin has since retired, and nothing told the consumer which of its declarations were dead. The criterion as filed asked for the complement — every key the plugin does not read — which needs the read set, and the only derivation available to a prose plan is a search over the plugin's own text. Three review cycles failed on that derivation: the first decided membership and retirement against a single corpus, so the retired class was empty by construction; the second relied on the converse and would have emitted `paths.migrations — retired, ADR 0003` for a live consumer key, because a bare leaf name spelled `run`, `source`, `team` or `migrations` is indistinguishable from the ordinary word over a corpus that is mostly English prose.

**Decision.** `--refresh` reports a **declared list** of the keys naming retired mechanisms — `loop.engine_timeout_seconds`, `loop.review_model`, `loop.unconditional_review_cycles` — and derives, deletes and refuses nothing. The complement is dropped. The maintenance trigger is any **shipped decision** that retires a key, an ADR or an accepted proposal; the second half is load-bearing, because this repo's largest retirement was the lifecycle-reset proposal and a trigger naming only ADRs missed the third key for a whole review cycle. A reader can settle which proposals qualify from the `status:` field each one carries. The precedent sits in the same plan: step 5 names its two managed legacy SHA-256 hashes outright rather than computing them.

**Alternatives.** A declared *read* set plus a drift guard was rejected: it adds a second copy of a fact the code already states, to be kept true forever, and retires nothing (P2). A guard over the list's completeness was rejected because it would have to assert what a prose list means, which ADR 0017 D5 forbids.

**Consequences.** The list can fall behind a retirement. That failure under-reports and can never emit a false line, which is the fail-safe direction, so even a stale list is strictly better than the previous behaviour of reporting nothing at all. Completeness is therefore checked in the direction that can find an omission — sweep both consuming configs for keys no executing surface reads, then ask which of those carry retirement evidence — never by confirming the keys already listed, which can only return what is already written down. At this tree every unread key with retirement evidence in `specs/` is one of the three named, and all three sit under `loop:`.

### The shape the machinery retires into (ADR 0022)

[ADR 0022](../decisions/0022-plugin-only-shape.md), built as #620 from the accepted `operation-nuke` proposal. It states four binding points — no plugin-owned file persists in a consumer; a consumer's CI and branch protection are out of lane; a plugin-shipped executable reads what *is*, never what *passed*; and guards escalate from no guard, refusing only what is unrecoverable or silent-and-consequential, with point 3 taking precedence over point 4 — plus the accepted residual risk that a red tree can reach the integration branch and sit there until something surfaces it, the builder who meets it fixing it then. The reasoning is that record's and is not restated here.

**#620 deleted no code; #621 did.** #620 recorded the decision and moved which record a reader honours: ADR 0020's tree binding and ADR 0018's choice of language for the marker helper each carry a dated supersession banner and a `Status: Superseded 2026-09-09 by ADR 0022` line, and the decisions index in `specs/architecture-principles.md` carries the same marker against both, so neither is met as a standing instruction to build. #621 then performed the deletion, and the section below records it as built. #622 then took the guidance half, recorded below; what remains outstanding is #623, the lifecycle split at PASS. Every section below marked **retired at #621** describes machinery that is gone and is kept only so a reader meeting the name in history finds its shape.

**Point 3 holds over this tree with no grandfathering clause, and that was measured rather than assumed.** Verified at review over tree `403368d4`: `prompt-guard.js` reads the intercepted tool call alone; `workflow-guard.js` reads the tool call and `process.cwd()`; `test-lock-guard.js` reads `version`, `tests_locked`, `lane` and `base_commit` out of `.harness/run.json` and touches none of `verdict`, `reviewed_tree`, `gate_marker_tree` or `review_cycles` — the four verdict-shaped fields among the twelve `skills/build/references/run-state.md` declares; and `scripts/plugin-version.js` reads the declared release branch through `declaredBranches` plus manifest bytes at a ref. The three executables that do read a verdict are `gate-evidence-guard.js`, `git-push-guard.js` and `push-target-guard.js`, 3,110 of the 3,645 lines under `hooks/` at that tree, and they are exactly what #621 deletes or reduces.

**The retired server-side-control claim is swept by search, never against an inventory, and this file is one of the surfaces that sweep reaches.** ADR 0022 point 2 gives #621 the sweep and instructs it to search the tree for the sentence and decide every hit explicitly, on the stated ground that a list written into a decision record would be stale before the sweep ran — two attempts to enumerate it during #620's own review both undercounted, and a sweep at this review found the phrase in thirteen tracked files, the ADR's own quotation of it included. The closing sentence of *The enforcement loop* below, on how the two branch-reading hooks fail, is one of those hits and stands as it is — cited by its section rather than by a line number, which this very insertion moved. Whether it goes is #621's call, not this record's.

**The cycle's version raise (#620).** `scripts/plugin-version.js`, run in #620's worktree, raised all five homes from `10.0.0` to `10.1.0`: both plugin manifests and the `spine:generated` markers in `templates/spine.md`, `AGENTS.md` and the `CLAUDE.md` derived from it. `dev` and `main` both stood at `10.0.0` beforehand, which is the condition the script raises on, so this is the cycle-opening raise rather than a second one. Minor is the floor and this diff does not exceed it — no command or skill is renamed, no argument changes, and no refusal reason moves, so the release auto-pulls instead of reaching a consuming repo as a decision. Measured at review over the same tree, `CLAUDE.md` still carries `AGENTS.md` byte for byte across its first 18,770 bytes, with the `<!-- spine:copy:end -->` boundary immediately after.

### What #621 retired, as built

#621 is the deletion ADR 0022 authorised: roughly 19,700 lines out against some 700
in, derivable at this record's tree with a diff against the integration branch rather
than restated here as a figure.

**Deleted outright.** `scripts/gate-marker.js` (the marker convention's one writer),
`hooks/gate-evidence-guard.js` (the Stop hook), `hooks/git-push-guard.js` (the
force-push refusal and the shared POSIX lexer), `scripts/land.js`,
`scripts/harness-refs.js`, the test modules whose whole subject was one of them, and
`tests/conftest.py`, whose single fixture dropped the runner's identity variable.
`land.js` and `harness-refs.js` were #622's in the ticket body: `land.js` required the
deleted marker helper directly and its `certifies()` is a marker read point 3 forbids
outright, so shipping #621 without them would have left two non-functional executables
on the tree. The operator folded their deletion in mid-build, so #622 reduced to the
guidance those two executables were named in.

**Reduced, not deleted.** `hooks/push-target-guard.js` went from 1,143 lines to 203,
and from a refusal to an **advisory**: it warns when a `git push` names a branch the
repo declares under `branches:`, and lets it through. Its false negatives are named in
its own docblock rather than discovered — a push with no refspec, a push behind a
substitution, a heredoc or a variable, and `git -C <elsewhere> push`, which compares
against the wrong repository's declaration. Each costs one un-warned push the operator
still sees in the transcript. `tests/unit/test_retired_enforcement_surface.py` holds
that it cannot emit a `permissionDecision` at all, across every shape the retired
guard refused.

**Narrowed.** `scripts/harness-config.js` exports two names — `declaredBranches` and
`declaredPaths` — where it exported eleven. Nine went with their consumers or, in the
case of `queueSettings`, `declaredLoop` and `declaredCommands`, because they never had
a runtime consumer at all, only tests. **Narrower, not looser:** the scalar,
flow-mapping and `onUnreadable` layers are untouched, so every spelling the reader
cannot parse is still reported whole rather than half-read (#487, #488, #510). The
file's placement docblock is rewritten, because the reason it gave — the marker helper
beside it was materialised into a consumer — is exactly what ADR 0022 point 1
abolishes; the placement now stands on #436's `hooks/*.js` scans alone.

**The sharpest risk was AC-4's, and it is measured rather than argued.**
`hooks/test-lock-guard.js` reaches the reader for `declaredPaths` and law 7 rests on
it; a narrowing that dropped that export would not fail loudly, it would report the
lock inactive — indistinguishable from a repo that declares no `paths.tests`.
`tests/unit/test_test_lock_hook.py` drives the shipped hook end to end against a
fixture repo that declares `paths: tests:` and asserts `permissionDecision: "deny"`,
so producer and consumer are both exercised over the narrowed reader.

**`scripts/verify.sh` runs stages and exits.** The `exec` hop into the Node runner is
gone, the nested-worktree preflight went with the helper that implemented it, and
nothing is written to disk — the claim a green run licenses is law 3's, held by the
builder who ran it and read it. `git` left the toolchain probe list because the test
that resolved it was deleted, and the list is derived in both directions by
`tests/unit/_toolchain.py`, so a probe for a binary no test resolves fails. The
coverage floor moved 82 to 85 in `scripts/verify.sh` and in
`tests/unit/test_verify_coverage_gate.py`: deleting the marker helper and the landing
pair removed statements whose coverage sat below the ratio, and the measured value is
85.31%. The ratchet rose because the tree changed, not because a test was written.

**`scripts/mutate.py` lost the #473 gate lock**, which refused `run` unless a fresh
marker covered the target tree — a verdict read. The green-baseline refusal is now the
first thing standing between a mutation report and an ungated tree, and the module's
permitted-argv guard reduces to the simpler claim that it spawns nothing but its own
interpreter.

**Point 3 is held as a swept property, with no exemptions.**
`test_no_shipped_executable_reads_gate_state` walks every tracked `.js`, `.py` and
`.sh` under `hooks/` and `scripts/` and fails on the retired complex's own spellings —
the marker directory, the helper's name, the Stop hook's, and the verdict-shaped
run-state fields. It carried a self-retiring exemption for `land.js` and
`harness-refs.js` while those were still #622's; the exemption went with the files
rather than outliving them. The predicate is a spelling list rather than a semantic
one, which the constant's own comment states: it is a regression guard against this
complex returning, not a general detector of verdict reads. `verdict` is deliberately
absent from it, because `test-lock-guard.js` has a function of that name deciding its
own refusal, and a guard that fired on it would be reading a word rather than a
behaviour.

**The guidance sweep.** `AGENTS.md`'s laws 3 and 5 and its *Enforcement* section are
rewritten, and `CLAUDE.md` and `templates/spine.md` carry the same generated block
byte-identical. Law 3's evidence is the gate's own output read this session rather
than a token an earlier run left behind; *Enforcement* now reads "one hook refuses;
three advise" and states that the harness's assurance is the declared gate plus the
independent review, with server-side controls the repository's own.
`skills/worktree-isolation` branches from the fetched integration branch and gates it,
where it used to read the green pointer; `skills/build/references/re-bind.md` carried
the three landing cases as prose that ADR 0022 names as the instruction most worth
measuring for effectiveness, until #622 deleted it and moved the instruction into
`/build`'s own ship step; `skills/init` wrote no gate asset, and
`skills/hydrate/SKILL.md` now says so as a standing prohibition rather than as the
absence of a step — *write no gate asset into the repository, ever*.
#621 left steps 3 and 4 of `skills/init/references/refresh.md` **fenced** with a
do-not-execute banner rather than rewritten, on the trade that renumbering steps 3 to 8
and their cross-references for text #624 would delete wholesale cost more than the
banner, and step 6's legacy `gate_marker.py` sweep unfenced because it degraded to
retain-and-report. **#624 deleted the file, so the residue is gone rather than
fenced** — the bet that the banner would outlive nothing paid at one ticket's
distance.

**The retired server-side-control claim was swept by search.** ADR 0022 point 2 gave
#621 the sweep and forbade working from an inventory. At this review the phrase
survives in nine tracked files: the two in this record, repaired in this same change;
two in `research/03-quality-principles.md`, which quote the spine sentence as it stood
and are records of past reasoning; one each in `specs/proposals/lifecycle-reset.md` and
`specs/decisions/0020-authored-tree-binding.md`, both superseded records carrying dated
banners; and three in `specs/proposals/operation-nuke.md` and
`specs/decisions/0022-plugin-only-shape.md` that state the replacement claim correctly.
No live surface claims a server-side control as the harness's own.

**The version class.** `dev` stands at `11.0.0` and the release branch at `10.0.0`, so
this cycle already carries a major raise over what a consumer can pull. #621 removes
refusals — a push to a declared branch, a force push at the hook layer, and a
completion claim over an ungated tree each used to be refused and now are not — which
is a major change under `specs/architecture-principles.md`'s compatibility grammar.
The standing `11.0.0` covers it and no further raise is owed inside this diff.

### What #622 retired, as built

#622 is the guidance half of the landing retirement: 7 files, +16 / −84, net 68
lines out. The executables the ticket was filed against — `scripts/land.js` and
`scripts/harness-refs.js` with their tests — went forward into #621, so what was
left here was the prose instructing a builder to use them.

**Deleted.** `skills/build/references/re-bind.md`, 64 lines, the three-case landing
decision. It answered a question only the tree binding asked — which of three
things happened to the reviewed tree while the gate ran — and #621 deleted the
marker that let a machine answer it. `/build`'s ship step now carries the landing in
its own body: fetch once more, merge the integration branch if it moved, re-gate over
the resolved bytes, return them to the reviewer, and never push from a shape you
cannot describe. **The re-gate is unconditional on a move**, where `re-bind.md`
exempted a clean auto-merge from it. That is stricter than the spine's *binding*
entry, which still admits a git-authored merge without a re-gate; a builder following
the ship step never violates the spine, and #623 owns reconciling the two when it
splits the lifecycle at PASS.

**Kept, and this was the ticket's own risk.** `skills/build/references/reconcile.md`
lost its opening binding-placement rationale and its closing delta-return paragraph.
Its five rules survive **byte-identical**: base movement as normal concurrency rather
than a stop, resolving a textual conflict over the conflicted paths alone, the
two-attempt bound, the monotonic-field trap with its same-fixed-point exception, and
functional conflict as the only escalation. Verified at this review by diffing the
file against its parent blob — the five bullet lines hash the same before and after.
The delta-return obligation did not go with the paragraph: `skills/build/SKILL.md`'s
reconcile bullet carries it, reworded against the certifying gate rather than against
final binding.

**Trimmed.** `skills/worktree-isolation/SKILL.md` dropped two passages of green-pointer
archaeology — what #621 removed, and what the removal cost — and states the standing
rule instead: nothing records whether the integration tip is certified, so the base gate
is the evidence. Its eval #1 now expects what that skill says, the three
pointer-specific expectations replaced by the detached worktree, the base gate run, and
the andon pull a red base is; one trigger query that named a deleted script names a live
one.

**Retained by operator decision**, against the ticket as filed. `scripts/promotion-step.sh`
and `tests/unit/test_promotion_step_script.py` stay. The filed premise — that the three
scripts existed only to serve the binding — does not hold for this one: it reads no
marker, its only gate call is the declared `bash scripts/verify.sh`, and it exists for
GH006, since `main` requires a pull request and `github-actions[bot]` cannot update the
ref directly. It is this repository's own CI, invoked by
`.github/workflows/nightly-promotion.yml`, which ADR 0022 point 2 keeps by this repo's own
choice rather than by exemption. Deleting it would have left a kept workflow calling a
missing file, failing every nightly. `/promote` could not absorb the hop: it is
operator-invoked and does not run in a 14:00 UTC runner.
`specs/proposals/operation-nuke.md` item 3 carries the correction and is retitled
*Retire the landing machinery*.

**Left to #623.** `/promote` stands as a working promotion command, the `delta_review`
stage stands, and the spine's *The binding* entry stands, because #623 rewrites
`/promote` and splits the lifecycle at PASS; sequencing them adjacently avoids rewriting
one skill twice.

**Outstanding, and it belongs to neither #622 nor #623.** The retired marker survives in
guidance as a live *rationale*: every action those passages prescribe is still correct
and the reason each gives is not. #622's ticket carries the finding #621's certifying
review raised and declined to repair, and this change did not reach it. No enumeration
is written here on purpose — ADR 0022 point 2 requires such a sweep to search the tree
and decide each hit, on the ground that a list inside a record is stale before the sweep
runs, and two attempts to enumerate the last retired claim both undercounted.
**Resolved by #630**, below — swept by search rather than by this paragraph or
any other list.

**The version class.** `dev` stands at `11.0.0` and the release branch at `10.0.0`, so
the cycle already carries a major raise. This diff deletes one reference file and
rewords guidance; it renames no command or skill, changes no argument, and moves no
refusal reason, so it stays at the minor floor and owes no further raise inside the
standing major.

### What #623 split, as built

#623 is the guidance half of the lifecycle reshape: 20 files at `d08446a`, +388 / −148,
with the reviewer's record and twin sweep landing on top of it. It closes the three
things #622's *Left to #623* paragraph parked — `/promote` as a promotion-only command,
the `delta_review` stage, and the spine's *The binding* entry — and it is the ticket
ADR 0022's *Obligations this creates* named when it said the `/build` → `/promote`
handoff becomes a second prose-enforced boundary.

**The lifecycle is two blocks now, and the seam is PASS.** `skills/build/SKILL.md`'s
`harness:build-lifecycle` block runs `in_review` → `rebase` → `substantive_review` →
`pass`, four stages and no landing stage at all. `skills/promote/SKILL.md` carries a new
`harness:promote-lifecycle` block running `rebase` → `full_gate` → `pass` →
`tree_compare` → `push` → `tracker_done`. `reconcile` is renamed `rebase` and moved
*ahead* of the review; `delta_review` is deleted outright, because a reviewer reading a
branch already rebased has no delta to be shown, and the bytes it used to read were
other tickets' work already reviewed and gated in their own runs.
`tests/unit/test_build_lifecycle_order.py` was rewritten from one block to two and now
asserts each stage/authority pair in order, that the rebase precedes the review, that
neither block names a retired stage, and that no landing stage survives in `/build`.

**`rebase` and `pass` appear in both blocks, and the record states why that is one stage
each rather than two wearing one name.** `skills/build/references/run-state.md` — the
one home of the stage vocabulary — says `rebase` is the same operation under the same
rules from one reference, and that `pass` means *the run holds green certification over
the tree in hand and may proceed*, with the `authority` field carrying which system
certified it: `reviewer` in `/build`, `gate` in `/promote`. The ticket's own approach
table named both, so a fresh stage name would have been a scope change needing the
operator; the resolution written instead is a single meaning with two certifiers, and
the guard pins the authority alongside the name in both blocks, so a drift in either is
red. The residual it leaves is a resume landing on `stage: "pass"` without knowing which
command wrote it; `run-state.md` answers that by making `/promote`'s rebase the one
declared exception to the tree-match gate on `reviewed_tree` and `verdict`, and by
requiring `/promote` to re-read the ticket's live state before it trusts anything.

**`/promote` gained the landing half and lost `disable-model-invocation`** (proposal D6
and D7, both operator-resolved). It is one skill at two altitudes with no no-arg form:
`/promote <TICKET>` lands a reviewed branch, `/promote <src> to <dst>` runs the release
hop. The two altitudes take **opposite** postures on a red gate, and the file says so in
both places rather than leaving the reader to notice: altitude 1 stage 3 states D5 —
the builder who meets red at landing fixes it, whatever caused it, because stopping
stalls the tick — while altitude 2's *What the release hop must never do* scopes its
stop condition to "this altitude, and only at this one" and names altitude 1 as the
deliberate opposite. The one rule binding both is that nothing is pushed on a gate the
run did not read, which is ADR 0022 point 2 restated. Altitude 1 also names its own
residual rather than leaving it to be found: a fix made after the review is a fix the
review does not cover, and one large enough to want a reviewer goes back to one.

**`/routine` step 3 is now a `/promote <TICKET>` call**, and its standing authorisation
extends to the ticket's own branch as well as the integration branch — the same push,
by the same tick, onto the same declared role, moved inside `/promote`'s landing
altitude. Its hold rule gained the matching exclusion: a red gate at landing is not a
hold, because stage 3 says the builder fixes it.

**The unattended permission clause was rewritten because the old one had become
unsatisfiable.** `settings/harness.json` and `.claude/settings.json` both carried a
*Closing a shipped ticket* clause conditioned on a review PASS "whose `reviewed_tree`
equals the current HEAD's git tree object" — a condition `/promote`'s rebase moves the
tree past by design, so an unattended tick could never meet it and would have wedged at
the last step. The replacement conditions the same permission on four things instead: a
PASS on record for the ticket, a rebase onto the integration branch, the verify gate run
and read **green** over that merged tree, and nothing edited between that run and the
push. Three of the four are tighter than the text they replace; the one that loosens —
tree identity giving way to the verdict-on-record — is exactly the residual proposal D5
and ADR 0022's *Consequences* already accepted from the operator, not a new licence this
change invented. The clause is one opaque string to
`tests/unit/test_settings_template_parity.py`, so both copies had to move together and
did.

**The spine's *The binding* entry became *The two gates*.** A verdict covers the tree the
reviewer read; a push is licensed by a gate run over the tree that lands; those are two
trees whenever the integration branch moves, which is why the rebase runs twice. What
survives of the retired binding is one check — the tree may not change between the
landing gate and the push — and the entry says so in the sentence that names ADR 0022.
Law 3's rationale comment and the lifecycle bullet were repointed to match, and the
generated block is byte-identical across `AGENTS.md`, `CLAUDE.md` and
`templates/spine.md` (verified at this review by hashing the region in all three: 14,229
bytes, one digest). **Nothing in the rewrite claims a control the plugin cannot
require:** both gates are the repo's own `commands.verify`, run and read by an agent in
the run, and no CI or branch-protection claim entered the tree.
`skills/review-discipline/references/certifying.md` follows it — the `reviewed_tree` is
what a resume compares against, explicitly **not** what licenses the push — and the two
reviewer definitions and `skills/review/SKILL.md` were repointed the same way.

**Four folded tickets, each landed where it belongs.** #605's gap — nothing re-read the
ticket before landing — is `/promote`'s *Before the first stage*, which confirms In
Review, no hold, and a spec that still describes the branch, and stops rather than
holding, since the ticket already carries whatever moved it. #611(a) moved the lint run
ahead of the test lock, so a lint failure can no longer arrive behind tests the lock has
frozen; the general obligation stays where it already lived, in `engineering` →
*Verification* ("lint before types before tests"), so `/build` dropped a restatement
rather than an obligation. #611(b) is `/build` step 2, clearing a stale hold as the
ticket transitions to In Progress — written as producer-side housekeeping on the run's
own ticket, reading no other run's state and **naming no consumer of holds**, per the
*Reduce fan-out* principle and ADR 0022. #610(a) is `/build`'s new *Resuming a held or
deferred ticket* bullet: a resume cuts a fresh worktree off the current integration
branch, checks the pushed branch out in it, carries the gitignored `.harness/run.json`
across before removing the old one, and treats a never-pushed branch as the one case
where the old worktree is the only copy. #610's part (b), the periodic sweep, stays on
#610.

**The evals were read rather than gated, because skill evals are not in `verify.sh`.**
`skills/promote/evals/triggers.json` is new (10 positive, 10 negative) and its positives
cover both altitudes plus the post-verdict re-entry case; `skills/build/evals` swapped
one negative for two that route a landing request away from `/build`;
`skills/routine/evals` was left unchanged and re-read at this review — its one
promotion query is already a negative and nothing in it grades a stage that no longer
exists. Read at this review: no entry in any of the three grades the retired lifecycle.

**What this change deliberately did not buy, recorded so it is not rediscovered.** There
is no mechanical guard on the `/build` → `/promote` handoff. The ticket scopes it out and
the proposal's *Risks* accepts it: the handoff is prose, and a ticket sitting In Review
with a pushed branch is the record of an unlanded run. `scripts/promotion-step.sh`, its
test and the nightly workflow are untouched — #622 established that they are this
repository's own CI for GH006 rather than landing machinery.

**Twin sweep at this review, and one deferral.** `docs/index.html` carried four spans the
diff falsified and the builder's sweep of `README.md` and `CLAUDE.md` did not reach: the
ticket-lane card still asserting that a verdict "binds to the exact git tree it read —
what ships is that tree, or a merge git alone made from it", the workflow card's
operator-only count and its model-invocable list, `/build`'s one-line description, and
`/promote`'s. All four are corrected in this branch, because the guard over that page
(`tests/unit/test_landing_page_inventory.py`) reads `data-unit` names and never the prose
beside them, which is the stale-twin-ships-green case exactly. **Deferred:** the retired
marker surviving in `run-state.md` as a live *rationale* — "every oid, marker and
verdict it holds is a cache key", and a resume re-deriving "whether a marker exists and
is fresh". #622's record already booked that residual as belonging to neither #622 nor
#623, and ADR 0022 point 2 requires it to be swept by searching the tree and deciding
every hit rather than from a list; doing it inside this diff would be that list.

**The version class.** `dev` stands at `11.0.0` and the release branch at `10.0.0`, so
the cycle already carries a major raise and `plugin-version.js` reports `already-ahead`.
This diff would have earned one on its own: removing `disable-model-invocation` from
`promote` means a call to `Skill(promote)` that used to be refused now succeeds — a
changed refusal reason, which `specs/architecture-principles.md`'s compatibility grammar
makes major — and `/build`'s contract narrowed from "to Done" to "to a reviewed branch",
which a consuming repo must decide about rather than pull. The standing `11.0.0` covers
both and no further raise is owed inside this diff.

### What #630 swept, as built

#630 is the reasons-only sweep the paragraph above named: two commits, `6b8fb63`
then `e01b572`, 21 files, +71/−70 at `e01b572`. Swept by search, not from a list —
`grep -rInE` for `gate[- _]?marker|gateMarker`, `marker`, `certified tree`,
`certifies`, `verdict binds`, `binds to`, `covers the (pushed|tree)`, `fresh
evidence`, `tree oid`, `tree identity`, `tree binding`, `reviewed_tree`,
`gate_marker_tree` — 111 / 491 / 105 raw hits across the three term groups, most of
the bare-`marker` volume read and set aside as unrelated vocabulary (`spine:generated`
and `spine:copy` markers, design-token region markers, git conflict markers, the
`[NEEDS CLARIFICATION]` marker, pytest marks, the workflow-guard debounce marker,
`prompt-guard`'s role markers, `size:` markers).

**Fourteen homes carried a false reason for a correct action; every one is
rewritten, no prescribed action changed.** `AGENTS.md`, `CLAUDE.md` and
`templates/spine.md`'s *The two gates* bullet stopped crediting "the retired tree
binding" for the no-change window between the landing gate and the push, and cites
law 3 instead. `README.md` and `docs/index.html`'s *One verification gate* card
stopped saying the verify command "writes a marker named after the exact git tree
it verified"; the builder who ran it and read it now carries the claim, matching
`scripts/verify.sh`'s own docstring. `docs/index.html`'s *Green is a claim about
bytes* section and *The marker* card — the public landing page, caught mid-build by
a reviewer rendering #626's visual evidence and logged as a comment on this ticket
before the build started — dropped the `marker write` gate stage, the tree-oid
binding claim, and the sentence ADR 0022 point 2 forbids any shipped file from
carrying ("the controls of record stay server-side..."), and now states what a
green licenses. `harness.yaml`, `scripts/harness-config.js`,
`scripts/plugin-version.js`, `skills/assess/SKILL.md`,
`skills/review-discipline/SKILL.md`, `skills/build/references/run-state.md:11`,
`templates/change.md`'s example title, and six test modules
(`tests/unit/test_settings_template_parity.py`, `tests/unit/test_mutate.py`, and
`tests/_gitutil.py` twice, `tests/unit/_toolchain.py`,
`tests/unit/test_landing_page_inventory.py`,
`tests/unit/test_verify_toolchain_preflight.py`) each stopped citing the marker as
the reason the index, not the working file, is the operand these guards read, or as
the reason a widened `node` permission once existed.

**The cycle-1 undercount, named rather than smoothed over.** The first commit
rewrote the claim once, in `tests/unit/test_settings_template_parity.py:41`. Five
near-identical restatements of the same sentence — "what `git write-tree` certifies
and the gate marker is named after" — survived that pass, spread across four more
test modules and doubled in one of them, and were caught at review cycle 1, then
fixed in `e01b572`. This is the third time this programme's own retirement-sweep
rule (`skills/engineering/SKILL.md` → *a retirement sweeps for every home of what
it retired*) was missed in execution rather than in principle, after two rounds of
undercounting #620's "controls of record" claim (one home, then two, then thirteen
found by search). No rule, guard or checklist was added for the class — ADR 0022
point 4's default stands, and AC-3 forbids one — so what changes is execution,
carried as a ledger entry rather than a mechanism.

**Two live instructions, filed rather than reworded**, per this ticket's own third
disposition. **#635** — `skills/assess/references/process-economy.md:62` derives a
"median over the gate runs the marker series has recorded" that contradicts
`skills/assess/SKILL.md:49`'s own correct statement that no such history exists;
and `skills/build/references/run-state.md:6,76-78` instructs a resume to re-derive
"whether a marker exists and is fresh" though the file's own field table carries no
marker field. **#636** — all three evals in `skills/engineering/evals/evals.json`
grade against deleted machinery (`push-target-guard.js` refusing without a marker,
`scripts/gate-marker.js`, `scripts/land.js`) and all three point at
`/home/user/harness-ref`, absent from this host; a sibling of #631, a
different file. Both filed as `bug` + `assurance:simple`, unassigned and unheld —
correctly, since neither is a protected area or needs operator judgment.

**All three homes named above are now resolved, neither by this sweep.**
`docs/index.html:7`'s meta description landed with #633 (*The landing page's
prose numerals are gone*, above), which removed the stale count rather than
waiting on this entry. `skills/architecture/evals/evals.json` is resolved by
#631: eval 3's prompt now names `scripts/mutate.py`, the largest first-party
module and the still-live gravity well `scripts/gate-marker.js` (#621) no
longer is, with its six `expectations` untouched. `skills/engineering/evals/evals.json`
is resolved by #636 (*What #636 repointed, as built*, below): all three prompts
name live subjects and `expectations` is unchanged in each. #631's own repo-wide
sweep of `skills/*/evals/*.json` found no residue this ticket owns beyond the
#636 hits named above and the eval framework's own output-filename and
fixture-diff tokens, neither a claim about the tree.

**#635 is now resolved too.** `skills/assess/references/process-economy.md:62`'s
Gate wall-clock row dropped the marker-median clause; it now states what the row
measures — the per-run half of *Ground 3*'s own `cost per run × runs per week`
ranking (`:53`) — and carries no derivation, so `skills/assess/SKILL.md:49`
stays the row's one surviving derivation, untouched. `skills/build/references/run-state.md`
lost `marker` from the cache-key sentence at `:6` and from the always-re-derived
list at `:76-77`; the Fields table it already pointed at (`:15-27`) carried no
such field, so nothing else in the file moved. #636's evals residue is a
different file and stays open.

**Two findings reported, not fixed, agreed at review cycle 1 and again at cycle
2.** `tests/unit/test_mutate.py:713`'s function name,
`..._and_one_read_only_query`, outlived the query it named — a name is not a
reason, and renaming it is the kind of action change a reasons-only sweep forbids.
`docs/index.html`'s `<div class="marker">` keeps its CSS class because
`tests/unit/test_build_design_tokens.py:164` names it as a token-drift case;
renaming it reaches into the token set rather than the prose.

**The version class.** `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`
raised `11.0.0` → `11.1.0`. Reasons changed; no command, skill, argument or refusal
did, so the change stays at the minor floor.

**Reviewed independently across two cycles.** Cycle 1 returned FAIL on the
undercount above and nothing else. Cycle 2 re-ran the search from scratch — against
neither the ticket's own list nor the builder's disposition table — and found no
further home.

### The enforcement loop

**Retired at #621, and this is what stands in its place.** `bash scripts/verify.sh` is
the gate, run directly. It runs a host-binary probe (`node`, `jq`), the toolchain
probe under `uv run --extra dev` (ruff, mypy, pytest, then pytest-xdist by import),
then ruff, mypy over `scripts/`, pytest with coverage at a floor of 85% over
`scripts/`, and the design-token drift guard. Exit 97 is still reserved throughout for
infrastructure that makes the gate unrunnable, so that state never reads as a red or a
green tree; a red tree exits the tool's own code. It writes nothing. The claim a green
run licenses is law 3's, held by the builder who ran it and read it — nothing may
infer authorisation from the fact that this script once exited zero.

`git` left the host-binary probe at #621 with the Stop-hook scope guard that resolved
it. The membership rule is unchanged and is the reason the removal is safe: a binary
belongs there exactly when a tracked test resolves it off `PATH` at run time, the set
is derived from the tracked `tests/**/*.py` by `tests/unit/_toolchain.py`, and
`tests/unit/test_verify_toolchain_preflight.py` holds the correspondence in both
directions by **executing** the indexed script under a stubbed `PATH`. A probe for a
binary no test resolves fails, which is the half that keeps the list from accreting,
and it is what said `git` should go. The third direction — the completion condition
that every skip-shaped construct in `tests/` sits in a function that also resolves a
binary — is unchanged.

**What is gone.** The `exec` hop into `node scripts/gate-marker.js run`; the runner's
`commands.verify` resolution through the shared reader and the three yaml spellings it
refused; the `sh -c` launch, the inherited-streams decision (#561) and the
`npm_config_*` scrub (#582); the `HARNESS_GATE_MARKER_RUNNER` identity and its
re-entry refusal (#559, #592); the nested-worktree preflight (#494); the marker at
`<git-common-dir>/harness/gate/<tree-oid>.json`, its freshness variable, its payload,
its scope key and its prune; and `tests/conftest.py`, whose one fixture existed to
drop the runner's variable. ADR 0018 is superseded and carries the banner. A
consumer's vendored copy keeps working — it resolves a gate, runs it, and writes a
marker no surviving hook reads — so the cost of the transition is a redundant hop and
dead files, not a red gate (#629).

**One hook refuses and three advise, and none reads a verdict:**

- `test-lock-guard.js` (PreToolUse: `Write`|`Edit`, and Codex's `apply_patch`) refuses
  an edit to a file under the repo's declared `paths.tests` while the run has declared
  its tests locked — the hook half of law 7, detailed below. It reads `version`,
  `tests_locked`, `lane` and `base_commit` out of `.harness/run.json` and no `stage`,
  so a change to that vocabulary cannot move what it denies. It is the only refusal
  left, and ADR 0022 point 4's second ground is why: editing the test is over 79% of
  measured cheating, so the failure is both silent and consequential.
- `push-target-guard.js` (PreToolUse: Bash) **warns** when a `git push` names a branch
  the repo declares under `branches:`, read through the shared reader, and lets it
  through. It reads the intercepted call, the working directory git resolves for it,
  and the declaration — no marker, no ref state, no verdict.
- `prompt-guard.js` and `workflow-guard.js` advise on injection-shaped writes and
  out-of-worktree source edits.

The force-push refusal `git-push-guard.js` carried is now the eleven deny globs in
`settings/harness.json` — eight `--force` and `--force-with-lease` spellings across
the bare and `git -C` forms, and three `+refspec` ones — which are host-native and
survived the deletion untouched.

The public `docs/index.html` companion states the same boundary in its Hooks lede:
one refuses, three advise; the refusal is the test lock and it rests on what the run
declared about itself, never on a branch name granting an exemption; and the assurance
is the declared gate plus the independent review rather than the hooks.
`skills/design-system/assets/01-voice/README.md` records that plain, mechanism-first copy
discipline, and `skills/design-system/assets/03-tokens/how-it-works.md` records the separate
token-generation seam (both relocated at #626). The
inventory guard holds names and counts to the tracked tree; reviewers, rather than a
prose predicate, hold narrative accuracy — and at this review that lede was the one
place where #621 moved the guarded count and left the sentence beside it standing.

The same `hooks/hooks.json` serves both hosts. The PreToolUse scripts normalize Claude Code's `tool_name` / `tool_input` and Codex's corresponding payload before evaluating the request. Claude decisions retain their existing output contract. A Codex advisory returns `hookSpecificOutput.additionalContext`; a benign Codex request and every Codex fail-open catch path exit successfully with no stdout, rather than emitting the unsupported `{continue:true}` response. `prompt-guard.js` and `workflow-guard.js` also read Codex `apply_patch` requests from `tool_input.command`.

`push-target-guard.js` and `plugin-version.js` resolve `branches:` through
`scripts/harness-config.js`, and `test-lock-guard.js` resolves `paths.tests` through
the same module; those two accessors are its whole public surface since #621. The
reader searches `harness.yaml`, `AGENTS.md`, `CLAUDE.md` and `CONTEXT.md` in that
order for a source that declares the key, so a repo hydrated before v5, or before
#537, keeps working unchanged. The grammar below is that one reader's and is
**untouched by the narrowing** — the export set shrank, the parser did not.
`tests/unit/test_harness_config_reader.py` carries the parser's own behaviour and the
fail-open floor; what it can no longer do is hold two hooks equivalent, because only
one branch-reading hook is left, so `test_an_unloadable_reader_leaves_the_hook_protecting`
is the surviving half and asserts the advisory degrades to the conservative fallback
set rather than to an empty one. It reads two spellings of a declaration: the indented
block, and the one-line flow mapping `branches: {integration: dev, release: main}` a
real yaml loader reads identically to it — valid yaml that a line scanner keyed on a
bare `branches:` line read as *nothing* until #487, so the repo that wrote it got the
conservative fallback while believing its own declaration was in force. Within those
two spellings, #488 widened each arm to the legal spellings the subject already
contains. An **inline comment on the key line** opens a block: the arm asks whether the
key's value — comment-stripped through the same `scalar` helper that already strips
comments from values — is empty, instead of matching a bare `branches:` line, and this
repo's own yaml block writes inline comments on sibling lines. A **comma inside a
quoted flow value** survives a quote-aware pair scan that replaced a split on every
comma; the split had derived `"has` from `release: "has,comma"` in both of the hooks
that then existed and dropped the declared name *silently*, because two parsers wrong
identically satisfy the equivalence test between them. **CRLF line endings** parse in
both arms: the block arm matches its pair regex against the raw line, where `.` cannot
cross a `\r` because JavaScript counts it as a line terminator, so a clone made under
`core.autocrlf=true` lost its block declaration entirely while the same file's flow
spelling parsed. The grammar is deliberately strict and flat: a block has non-empty
scalar pairs with supported bare role keys at one entry indentation, while a one-line
flow mapping has a complete comma-delimited sequence of those pairs (with quoted scalar
values permitted); a repeated role key, unsupported pair, sequence, nested or
line-wrapped flow mapping, plain scalar, or mismatched block indentation makes the
**whole declaration unreadable**. Distinct role keys may assign the same branch value,
which becomes one protected branch. **Decision (2026-08-25):** parse the declaration
completely or read none of it, then issue the existing one-line stderr notice and
continue through `CONTEXT.md` and finally `FALLBACK_PROTECTED`; stdout and the hook
decision remain unchanged. **Alternatives rejected:** preserving the pairs a line
scanner happened to understand leaves the omitted declared branch unprotected and
suppresses the degradation signal; rejecting duplicate branch values mistakes a valid
multi-role topology for an ambiguous mapping.

**What went with the Stop hook.** `integrationTip`'s local-then-remote fallback chain,
the #483 remote-tracking-ref defect it closed, and the #490 verifying-spelling sweep
(`--verify --quiet`, so a bare `git rev-parse <name>` cannot answer with a pathspec)
were that hook's, and the reasoning is preserved here rather than in a live section:
resolving a branch name is not the same operation as parsing it, and a caller that maps
a non-zero exit to null reads a path where it expects an oid. Nothing in the surviving
set resolves a branch to a tip. Hooks still fail open loudly when they cannot run at
all; the surviving advisory then degrades to its conservative fallback set, which
over-warns, and the surviving refusal degrades to an inactive lock. Neither degrades to
silence pretending to be a pass. **The harness claims no server-side control here**
(ADR 0022 point 2): what a repository runs in CI or on its branches is its own.

`/build` ran review, reconciliation and landing as one interleaved sequence until #623 split it at PASS; *What #623 split, as built* above owns the shape that stands, and the paragraph this replaces described the retired one. What survives of it unchanged: `/build` enters In Review before the independent reviewer starts, the reviewer checks the whole candidate and writes the as-built record, the complete gate certifies a staged tree and the reviewer issues PASS only for that tree, no tracker write falls between PASS and the push, and tracker comments, Done and closure follow a successful push — all now spread across the two commands rather than one. Since #621 a push that loses a race is decided by the builder reading git, not by a script. Reconciliation — the `rebase` stage since #623 — keeps its two-attempt bound; a third attempt holds the ticket. ADR 0022 names the reconcile instruction as the single one in the new shape most worth measuring for effectiveness. The fix lane has no reviewer at all — the gate is its whole assurance — and therefore no reviewer-owned record; a diff that outgrows the lane is upgraded rather than shipped under it.

Since #538 the workflow itself is a short one — 68 lines at #547's tree, against the 70 #538's criterion set — with three stage-loaded references at this tree: `run-state.md`, `reconcile.md`, `codex-review.md`. It names no procedure one of those owns. `re-bind.md` was a fourth until #622 deleted it, and `visual-evidence.md` a fifth until #547 did: its rules moved into the seeded `.claude/rules/design-system.md`, which loads on its own whenever a UI file is opened, so `/build` names the obligation and owns none of its rules. #547 also made the review dispatch lane-dependent — `reviewer` in the change lane, `reviewer-feature` in the feature lane — so the lane buys depth through the runtime rather than through prose an agent may not honour. Four behaviours arrived at #538. It **refuses a change spec still carrying `[NEEDS CLARIFICATION: …]`**, names the line, and returns the ticket to the clarification loop rather than building past an unanswered question: attended, ask; unattended, hold it (`input`, assigned) and put it back in Todo, because a ticket left In Progress on a spec nobody can build is invisible to both the queue and the operator. It **checks the andon cord before any tracker write**. **The orchestrator is the builder by default** — a `dev` sub-agent is dispatched on exactly two conditions, a diff that would flood this context or a feature lane wanting a fresh design context — because a hand-off buys isolation and never independence, and the reviewer's context is fresh whoever built. And after the push, before close, it **reflects**: at most three lines or `none`, naming the wastes the run met by the spine's P2 categories and what should change, each line appended to the improvement ledger, or to the harness's own where it concerns the shipped guidance. `reflect` sits after `tracker_done` deliberately — a ledger append is a tracker write, and putting one between the push and the ticket's own state change would leave shipped work sitting In Review on a failed append. The `dev` role gains the matching sentence in both its files: if the criteria contradict each other or cannot be met honestly, stop and say so, returning it as DEFER, and never edit a test while implementing against it.

#567 fixed the one outlier in that hold-label contract. `build/SKILL.md`'s DEFER-or-spent-budget bullet had applied a single `operator` label to both outcomes, where three other sources already declared `input` authoritative for a DEFER — `review/SKILL.md`'s DEFER bullet, `digest/SKILL.md`'s drain selection, and `tracker/SKILL.md`'s `Holds` section on what the return path selects — and `/digest --drain` selects `input` and nothing else. A DEFER held under `operator` therefore never reached the console built to return it, the andon cord's own failure mode. The bullet is now two, at `build/SKILL.md:69-70`: *DEFER* applies the `input` label and states outright that `input` is DEFER's whole return path; *a spent cycle budget* applies `operator` instead, still assigns the operator, and names `/digest`'s *At the keyboard* section as its own path, incorporating the DEFER bullet's preserve-and-route obligations (integrate nothing, commit and push, comment the reason and carried findings, route findings by class, leave the worktree) by reference rather than restating them. No guard pins the wording — a regex over prose is the #511 failure ADR 0017 D5 forbids — so AC-3 was verified by use instead: three rounds of fresh contexts given only the shipped bullets and the spine's hold contract, the pair in each round differing only in the case put to it, all six answering `input` and `operator` correctly; rounds 1 and 2 each surfaced and fixed a defect in prose written minutes earlier (a `so`-clause that read as a warning against the very label it names, and a `preserve and route` phrase that did not import `Integrate nothing` or the assignment), round 3 introduced nothing and found none of this change's making. The file is otherwise untouched and now sits at 70 lines — the #538 criterion's own ceiling, two over the 68 the sentence above measured at #547's tree — with no live guard enforcing it in either direction. The version this cycle raised (`8.0.0` → `8.1.0`) stayed at the minor floor: the fix restores `build/SKILL.md` to a label contract three other sources already declared, so nothing new surfaces to a consuming repo as a decision.

`review-discipline` states the reviewer's mandate as **scoped** (#538): correctness, the criteria as they stand on the ticket now, the four cheat categories by name — modified tests, overloaded comparisons, hidden state, special-cased inputs — and one explicit item per test file in the diff, because silence on a test file is not a pass. It does not hunt for improvements, and the report names the mandate it reviewed under. A finding that is small, contained and in scope the reviewer repairs in place; a repaired candidate then goes to a **second fresh reviewer**, which may certify only if it makes no repair of its own. The review→fix ceiling is `loop.max_review_cycles`, **3** in both `harness.yaml` and `templates/harness.yaml`, and no live configuration declares `unconditional_review_cycles` — not this repo's `harness.yaml`, not `templates/harness.yaml`. Two guidance surfaces name it, both as the thing that was retired rather than as a setting: the accepted proposal, and since #561 the `--refresh` plan's retired-key list, because two consuming repos still declare it. With a three-cycle budget there is no separate unconditional window: one convergence judgment is owed, written down, before the last cycle, rather than a justification on every cycle after a window, which would be ceremony proving a stage ran. The as-built-record trigger is restated as a **documented-behaviour change in any lane**: the feature lane always reaches it, the fix lane never should, and a fix whose diff does reach it is not a fix and is upgraded rather than written up under the lane (D7).

### Heredocs are data in the shared lexer

**Retired at #621 with the lexer itself.** `lex()` lived in `hooks/git-push-guard.js`,
and `push-target-guard.js` imported it rather than growing a weaker twin (#436); both
files are gone, and the surviving advisory does a plain token scan whose false
negatives are named in its docblock instead. `tests/unit/test_heredoc_lexing.py` went
with them.

The reasoning is kept because it is the concrete case behind ADR 0022 point 4's
asymmetry — **a refusal must not be bypassable and therefore grows a parser, while an
advisory tolerates false negatives and stays small**. Deciding a push target or a force
push from a raw command string needed a POSIX shell lexer with a full heredoc model:
`<<` and `<<-` queue a delimiter read the way bash reads it, a quoted delimiter's body
is skipped and an unquoted one's `$(...)` and backticks are harvested and analysed
recursively, an unterminated heredoc is refused because bash warns and runs it anyway,
and a queued-but-bodyless `<<` — arithmetic like `echo $((1 << 2))` — is dropped
because nothing can hide in a body that does not exist. Two review cycles of #557
shipped a classifier that tried to tell arithmetic from a command list, and both were
fail-open inside a fail-closed guard. That is 971 lines bought by one refusal, and it
is the purchase ADR 0022 point 4 asks a change spec to record against its
guard-to-change ratio.

### The landing posture

**Retired at #621 with ADR 0020, which it implemented.** A verdict still names the tree
it covered, but the two-shape binding the spine admitted at #621 — the reviewed tree, or
a two-parent merge git alone produced from it — is gone as of #623: the spine's *The two
gates* replaced it, and what licenses a push is a second gate over the tree that lands
rather than a tree identity. **There is no machine half** either way. `hooks/push-target-guard.js`
no longer decides anything: the marker it read, the `merge-tree --write-tree`
recomputation, the five-fact second acceptance path, the `scope` field and the scoped
re-gate, `scripts/harness-refs.js`'s `refs/harness/*` namespace with its gate records,
claims and green pointer, and `scripts/land.js`'s `plan` / `finish` / `done` are all
deleted. #622 then deleted `skills/build/references/re-bind.md`, which had carried the
three cases as prose, and folded the landing into `/build`'s ship step;
`skills/worktree-isolation` branches from the fetched integration branch and gates it,
where it used to read the green pointer and fall back.

Two of that machinery's own measurements are what argued for its retirement and are
kept here. ADR 0020 recorded that **23% of commits on `calibrate`'s integration branch
were reconciliation merges** under the strict binding. And the accretion was
self-citing: `land.js` existed because the binding "modelled at 7.4 attempts to land at
eight pushes an hour", `harness-refs.js` existed to share gate outcomes between sessions
without a service — a coordination problem the binding created — and `harness-config.js`
existed because three hand-rolled readers of one yaml file produced four parser bugs,
two of those readers being marker hooks. What replaced all of it is a fetch, a merge,
and the builder reading what git did.

The accepted residual is ADR 0022's, stated there rather than here: a red tree can
reach the integration branch and sit until something surfaces it, and the builder who
meets it fixes it then.

### The test lock and the run file

`hooks/test-lock-guard.js` is one of four shipped hooks and, since #621, the only one that refuses. It arms only when three facts hold together: the repository resolved from the **edited file's** directory carries `.harness/run.json`, that file is version `1` and says `tests_locked: true`, and `harness.yaml` declares `paths.tests` — read through the shared reader's `declaredPaths` accessor, which since #621 is one of that module's two remaining exports rather than one of eleven. Any one of the three missing leaves the lock inactive, which is the state of every repo that never adopts the run file and of every session in this one that is not a build. Under the lock, an edit to a path under the declared test root is refused in the `change` and `feature` lanes and in any lane value the hook does not recognise — the permissive branch belongs to `fix` alone, so a typo, a truncated write or a lane invented later locks rather than unlocks. The `fix` lane may **add** a test file, where *new* means absent from `base_commit`'s tree: not absent from the filesystem, which would refuse the fix lane's own second edit to the file it just wrote, and not absent from the index, which flips the moment a run stages for review. Because the repository is resolved from the edited file rather than from the hook's own directory, a locked run in one worktree never reaches another worktree of the same repo, which matters where concurrency is the norm (law 5).

Two details are load-bearing and were found rather than designed. The repository is resolved from the edited path's nearest **existing** ancestor directory, because a `Write` creates the file *and* its directory: a `git` probe in a directory that is not there yet fails, no repository resolves, and the lock is simply off — `mkdir tests/new/` was a one-command bypass, and three lookalike controls had been passing vacuously against a predicate the hook never reached. And the refusal names the offending path, the law, and the escape — return the run to `stage: "tests"` with `tests_locked: false`, record why on the ticket, and expect the reviewer to ask — while echoing **nothing** from the model-writable run file into a reason that re-enters a model's context (law 6); the path itself is reduced to path characters and truncated.

The bounds are stated rather than implied. The hook sees `Write`, `Edit` and Codex's `apply_patch`, so a test rewritten through `Bash` is invisible to it, and extending to `Bash` would mean parsing arbitrary shell, which the deleted `git-push-guard.js` priced at 971 lines that still refused on ambiguity. Releasing the lock is one edit to a gitignored file — which is the point, not a hole: it makes a bypass deliberate and reviewable instead of silent. What stands behind it is the reviewer's explicit item per test-file diff and the declared gate; whatever a repository runs server-side is its own and is not claimed here (ADR 0022 point 2).

`.harness/run.json` is the run state `/build` writes at set-up, and `skills/build/references/run-state.md` owns its fields, its stage vocabulary and its resume rules. One rule bounds the file: it records *where the run is*, never *what is true of the tree*, so every oid and verdict it holds is a cache key re-derived from git before use and discarded on a mismatch — `reviewed_tree` and `verdict` are trusted only while the freshly derived tree oid still equals `reviewed_tree`, which is the reconciliation rule the resume path inherits rather than restating. #621 deleted the third of those fields, `gate_marker_tree`, with the marker it cached. **Only the orchestrator writes it**, which is what stops an agent told to make the tests pass from clearing the flag that governs the stage it is in, and a writer rewrites the whole object carrying through keys it does not recognise. #587 had given the file a second reader — `gate-evidence-guard.js` took `ticket` alone to decide whether a derived Stop candidate belonged to another run — and #621 deleted that hook, so the test lock is again the only reader and the `version`-handling asymmetry between the two is gone with it. It echoes no byte of the file into a reason. `tests` and `implement` are separate stages and that separation is the whole mechanism: the failing tests are authored with the lock off, then one write sets `stage: "implement"` and `tests_locked: true` together, before the first line of implementation. A malformed or unknown-version file stops the line at `/build`, where an operator can act on it, while the hook fails open loudly over the same file — denying there would lock a session out of its own tests over a corrupt cache file with no way to clear it from inside the hook.

The file is gitignored, and #538 moved `.harness/` out of a loose `.gitignore` line into the machine-identifiable `harness:gate-ignore` block that `/harness:hydrate` hydrates. Untracked *and* unignored, `run.json` would be swept into the tree identity by `/build`'s own `git add -A && git write-tree` — the exact failure `.evidence/` is in that block to prevent — and a consuming repo hydrated by `/harness:init` had never received the loose line at all. `tests/unit/test_hydrate_gate_ignores.py` holds the block's contents against the hydration copy in both directions and against an explicit set, so a shared omission cannot make the comparison vacuous.

After a successful push, `/build` runs the `worktree-isolation` cleanup procedure: it tears down only temporary resources owned by the task, removes the merged worktree, prunes Git's administrative records, and deletes the merged task branch. A failed cleanup reports the remaining resource; it never substitutes broad host cleanup.

`scripts/mutate.py` — the instrument that proves guards can fail — **lost its #473 gate lock at #621**. That refusal asked whether a fresh marker covered the target tree, which is a verdict read, and it went with the marker. The green-baseline refusal is now the first thing standing between a mutation report and an ungated tree, and the claim the lock protected rests where every other one does: the builder runs the declared gate and reads it. The module's argv guard narrows with it. It used to permit two shapes — its own interpreter, and exactly `["node", <a name bound to gate-marker.js>, "status"]`, an exemption earned from the argv shape rather than granted to the name `node` — and it now permits one, so `tests/unit/test_mutate.py` holds the simpler claim that this module spawns nothing but Python. `node` is no longer a precondition of `mutate run` and `RunnerUnavailableError` has one occurrence left, the baseline run that could not complete.

### The cloud session bootstrap

`scripts/setup-cloud-env.sh` provisions a bare checkout until `/build` and `/routine` can run in it: the Python toolchain the gate runs under, the host binaries its toolchain preflight probes, and `gh`, which the tracker needs and the gate does not. It checks `git` rather than installing it, on its own reasoning that no reasonable cloud sandbox lacks one. The exact set is the script's own header, and the gate-prerequisite part of it is recorded in `specs/infrastructure.md`'s *Local execution* row and in the toolchain-preflight Decision `specs/architecture-principles.md` carries; this entry cites them rather than adding another copy. Installation is idempotent, and the script probes the result instead of assuming it, so a provisioning gap is reported at setup time rather than surfacing mid-gate. It deliberately does not run under `set -e` — failures accumulate in a status variable and become a non-zero exit at the end, so one missing tool still leaves a complete report — and the severity separates a gate dependency from a tracker one: a missing `jq` fails, a missing or unauthenticated `gh` warns.

`scripts/session-start-bootstrap.sh` is the hook entry point that runs it; both landed at `4beb310`, and the spine's `commands:` block carries the provisioner as `bootstrap:`, which is where an agent reads it. The wrapper is registered in this repo's own `.claude/settings.json`, under `hooks.SessionStart` with the matcher `startup|resume`. The plugin's `hooks/hooks.json` declares no SessionStart hook, so nothing wires this in a repo that installs the harness and the provisioning stays this repo's own environment concern rather than a capability the plugin ships. That registration is the `hooks.SessionStart` block `tests/unit/test_settings_template_parity.py`'s subtree rule lets the installed settings carry over `settings/harness.json`, which declares no such key. The wrapper exits immediately unless `CLAUDE_CODE_REMOTE` is exactly `true`, which keeps a local session out of a provisioning run and rests on a host interface nothing in this tree can observe (*Known limitations*).

### The guards

`tests/unit/` holds every test module admitted under ADR 0017 D5's rule (count them at any tree with `git ls-files 'tests/unit/test_*.py'`, which leaves the suite's shared helper modules outside the count): (a) behaviour of executable code, (b) a property of the spine, (c) integrity of shipped assets, (d) frontmatter compliance, (e) tree-consistency — existence and correspondence of two things both in the tree, never prose meaning. The prose-guard corpus (118 modules on `dev` at 2026-08-17) is deleted; what survives executes the hooks under node, the gate scripts, the mutation instrument, and the workflows' contract modules. New guards are admitted against the rule, not by momentum. #537 retired `test_generate_codex_artifacts.py` and `test_ticket_522_test_first.py` with the generator they measured, and added three: `test_harness_config_reader.py` (the shared reader), `test_codex_agent_adapters.py` (below), and `test_seeded_assets_are_tracked.py`. #547 added none and deleted none — the largest diff in this range removed 10,900 lines of guidance and settled proposals, and prose is reviewed rather than guarded (ADR 0017 D5). What it did change is three modules at the `tests` stage, each to decouple a guard from a file the ticket removes: the landing page's splice target is derived from the page instead of naming one card's number, the cite guard's synthetic corpus member is plainly synthetic and its paired splice derives its file from `specs/proposals` under a floor, and one docstring cite was corrected. #539 added three, all class (a): `test_push_target_guard_merge_path.py` (the second acceptance path, built around two vacuity traps — a fail-open reads exactly like an allow, so every allow asserts stderr carries no `fail-open:` line, and a deny is the *default*, so every deny names the reason it expects), `test_harness_refs.py` (the ref namespace, whose no-object-transfer claim carries a real fetch as the control that must differ), and `test_land_script.py` (the three landing cases and the refusals). #538 added the forty-second, `test_test_lock_hook.py` (class (a)): every assertion runs the hook as a node subprocess against a real repository and reads the decision it emits, and the ALLOW controls outnumber the kills deliberately, because a kill table cannot see a false positive (#511) and this hook blocks work — the expensive failure here is a correct edit refused. What gives those controls teeth is mutation rather than their number: five mutations of the shipped hook, each making it over-refuse or mis-classify, each killing exactly the controls that name its failure and nothing else. The first table's three survivors were the finding — one real defect, one missing discriminator, and one docstring claiming a single mechanism for a property two mechanisms hold, corrected where it stands rather than kept as an entry that cannot kill. The last is the suite's one deliberate exception to the index-reading rule, and says so in its own docstring: every other guard reads `git ls-files` or `git show :<path>`, which makes a file that is *only* in the working tree invisible to all of them — present for the session that wrote it, absent from every clone, with the gate certifying a tree the author believes contains it. It happened twice inside this one branch: `.gitignore`'s unanchored `build/` swallowed `skills/build/SKILL.md`, so the plugin would have shipped without its main lifecycle workflow, and a machine-local `.git/info/exclude` entry swallowed `.claude/rules/design.md` while `AGENTS.md` named it. The guard is scoped to the directories whose contents are named elsewhere — `.claude/rules`, `hooks`, `skills`, `agents`, `templates`, `.codex/agents` — rather than sweeping for untracked files generally, which would fail on every scratch file and be deleted within a week. `tests/unit/test_landing_page_inventory.py` (class (e), #482) closes the catalog gap D8 left open: `docs/index.html` tags each inventory entry `data-unit="<kind>:<name>"`, and the guard derives the same inventories from the tracked tree — directory names under `skills/` carrying a `SKILL.md`, and the stems of `agents/*.md` and `hooks/*.js` — then asserts the two sets are equal per kind in both directions, so a page entry with no file behind it and a tracked unit the page never names each go red. Both operands read the **index** (`git ls-files`; `git show :docs/index.html`), which is the tree `git write-tree` certifies and the gate marker is named after; a working-file reader let a tree whose staged page was wrong pass the whole module, measured at review. `tests/unit/test_gate_evidence_hook_spellings.py` (class (a), #490) reads the Stop hook's source out of the index the same way, and holds two properties its behavioural suite cannot reach: every `rev-parse` call that passes a revision carries `--verify`, and the hook still spawns through exactly one bare, `PATH`-resolved `spawnSync("git", …)` — the premise the spawn bound in `test_gate_evidence_hook_scope.py` is measured through, which a `PATH` shim cannot check for itself, and which read 21 spawns against 251 real ones when it stopped holding. Both are derived by enumerating the file rather than from a list, and an occurrence in a spelling neither extractor reads is red rather than invisible. Three further class-(e) guards landed together at #489, closing twins D5 admits and nothing held: `tests/unit/test_settings_template_parity.py` holds every key `settings/harness.json` declares against `.claude/settings.json` by a **subtree** rule — objects recurse, so the installed file may add keys the template never declares (`extraKnownMarketplaces`, a `hooks.SessionStart` block), while every other value, arrays included, must be deep-equal, which is what refuses a permission list widened only on the installed side; `tests/unit/test_hook_manifest_matches_shipped_hooks.py` holds `hooks/hooks.json`'s command strings against the tracked `hooks/*.js` set in **both** directions, a wired command with no file and a shipped hook nobody wired, its extractor raising on a command shape it cannot read rather than dropping it from the wired set; and `tests/unit/test_spine_template_parity.py` holds the two generated blocks above. All three read both operands from the index, and each floors **both** sides by membership so that two derivations emptied by the same defect cannot compare equal; the manifest walk and the spine extractor additionally raise on an empty or ambiguous region rather than yielding a value another empty one would match. Where a divergence is reported with no line unique to either side — a change in how many times a line repeats, a change in the separator bytes a line split discards, or a genuine reordering — the spine guard names that condition rather than guessing at a cause, and attaches a unified diff over `keepends` lines, because a locator built from a plain line split is empty for exactly the differences that live in those bytes. The same pass corrected the one live divergence the unguarded interval had accumulated: `.claude/settings.json`'s *Closing a shipped ticket* clause cited a `/ship` command v5 retired, where the template already cited `/build`'s ship stage.

`tests/unit/test_landing_page_inventory.py` also measures the **printed counts**. The inventory sweep reads `data-unit` tags and has no opinion about the integer beside each heading, so the guard pairs each `<span class="n">` with the `data-unit` tags beneath it and asserts that every printed integer equals the list length. A second count check derives the four hero figures directly from the tracked inventories, and a positioning check requires the native dual-host description in both metadata and visible copy. These checks caught this change's initial landing page, which still described a Claude-only package and reported 14 skills while the tree carried 28.

### The skill surface after #547

The cull that ADR 0017 argued and the lifecycle-reset proposal scheduled. Twenty-eight
skills on `dev` at the start of the reset became sixteen, and — after #565 — four of
the nine workflows sit off the model's skill listing, down from six after #564. Four
of nine is no longer *most* of the workflow surface, which is why the framing changed
here rather than only the numbers: the listing now costs something on a majority of
the nine, not a minority of it.

**The listing, measured.** `disable-model-invocation: true` removes a skill from the
listing, so the listing is the twelve model-invocable skills — the seven craft skills
plus `build`, `review`, `routine`, `drain`, and `assess`, none of which carries the
flag because each answers to a caller that is not a human at a prompt: `/routine`
drives `/build`, `/build` drives the review stage, `routine` itself is the versioned
home of the prompt an unattended scheduled run pastes, `/assess` drives `/drain` for
the ledger, and a work-pull run falls back to `/assess code` when its own queue is
empty. `drain` holds the slot `digest` held until #627 and inherits the membership
rather than the reason: `digest`'s caller was a scheduled run firing its report half,
and `drain` has no report half to schedule. `routine` carried the flag through
#537 and #547 and lost it at
#564, once a scheduled run was observed refused on `Skill(routine)` — swept into the
operator-only bucket by category rather than by intent. `digest` and `assess` carried
the flag through #564 — whose reviewer flagged the identical contradiction in both and
recommended a follow-up rather than widening that branch — and lost it at #565, once
both were found refused on the operator's own host: two scheduled tasks invoking
`/harness:digest` and one `lab-book-work-pull` fallback invoking `/assess code`. Their
`description:` fields sum to **7,200 characters, about 1,800 tokens** at tree
`b2c7f63` (#627) — 7,294 / 1,823 before that rename, up from 5,896 / 1,474 (74% of
budget) at `21e1b2b` (`dev`, immediately before
#565), 3,496 / 874 at `3952f3a` (#564), 3,131 / 783 at `8281ecf` (#537), and down from
4,658 characters across 17 listed skills on `dev` at `c75c666`. Against a 1% listing
budget on a 200k window that is **90%**, up from 74% before #565 and 44% at `3952f3a`.
Two skills rejoining the listing cost the 17-point rise and #627's rename gave one
point back; 90% is close enough to the budget to state plainly rather than bury: the
next skill to rejoin would exceed it. The longest are now `routine` (716), `review`
(675) and `work-discovery` (652), with `drain` (650) just behind — `digest` (786) had
overtaken `routine` at #565 and its replacement hands the slot back — rather than
`authoring` (537) and `tracker` (577) before #548, and none reaches the cap. `digest`
(786) and `assess` (612) moved from the off-listing sum into this one at #565; a
skill's own length is unchanged by which
side of the flag it sits on, only which sum counts it. The four off-listing workflows
— `capture` (568), `init` (691), `promote` (170), `propose` (577) — sum to **2,006
characters** at the same tree, down from 3,129 at #564's tree and 1,019 before
#548. Nothing guards any
of these figures — a description is prose, and law 2's subject is code — so each is a
reviewer's measurement at a named tree, re-derivable by summing the `description:`
field of every `skills/*/SKILL.md` with and without the flag.

**Three merges, each because one caller was the only caller.**

| Was | Is | Why |
|---|---|---|
| `spec-authoring` + `writing-quality` | `skills/authoring/` with `references/prose.md` | The same discipline governs every artefact `spec-authoring` covered, and a second skill that had to be triggered separately fired only when something remembered it |
| `github-issues` + `linear` | `skills/tracker/` with `references/github.md` and `references/linear.md` | Two copies of the same ticket semantics wrapped around two sets of API calls, and the semantics had drifted between them. The semantics are in `SKILL.md` once; a transport is a reference |
| `assessment-craft` + `process-economy` | `skills/assess/references/finding-bar.md` and `skills/assess/references/process-economy.md` | `/assess` is the only caller of either. `skills/assess/` was already taken by the workflow, and two skills cannot share a name, so the standards moved inside it rather than beside it |

The two tracker references are **verbatim moves** of the provider skills' recipes.
That is what bounds the residual above: AC-3 exists to catch a rewrite silently
dropping an operation, and a byte-for-byte move cannot.

**Two deletions, and two re-homings.** The deletion test is *would the agent get this
wrong without it*. `systematic-debugging` was loaded by nothing in the tree and fired
by description alone; its one non-generic obligation — no fix without a stated root
cause — is a sentence, kept in `engineering` beside the test-first loop that already
owns it. `infrastructure` is above. `design-system` and `ux-design` were not deleted
but **re-homed**, into `templates/rules/design-system.md`, which `/harness:hydrate` step 5
seeds as `.claude/rules/design-system.md` with the repo's own globs and, for Codex, as
a nested `AGENTS.md` inside the design directory. Step 4 states what the two host forms
can actually be: the shared region is everything from the first `##` heading down and
is identical in both, while the preamble above it differs because it names a host
mechanism and the Claude form carries `paths:` frontmatter the Codex form has no use
for. Both preambles say which half is shared. Nothing holds the region byte-equal —
that guard is proposed, not built here.

**The ledgers.** The `proposals-ledger` reference under `skills/review-discipline/references/`
(removed from the tree by #547, kept in git history) becomes `improvement-ledger.md`
beside it, the standing issue is found by an
`improvement-ledger` label, and `tracker` → *`ledger`* migrates a repo still carrying
the pre-#547 `proposals-ledger` label on sight rather than opening a second one.
The destination is resolved, never written down: `.claude/settings.json`'s
`extraKnownMarketplaces` source first, then `.agents/plugins/marketplace.json`, then
the plugin root's own `.claude-plugin/plugin.json` `repository`, and where none
resolves the entry goes to the operator rather than to a guessed owner. A hardcoded
`sluengen/harness` in shipped guidance is the defect the rule exists to prevent: it
silently redirects every fork's feedback here. The ledger drain marks every entry
**done**, **folded** or **dropped**, and an entry not promoted at the drain is dropped
rather than carried — `/assess` step 5's own text until #627 moved the procedure into
`/drain`, which step 5 now invokes.

**Sequencing, so flow and andon have something to read.** `tracker` → *`create`*
requires a breakdown filing to carry its dependencies and its priority in the
tracker's own fields, and reports a filing carrying neither as incomplete, by the same
rule as a missing assurance label. A breakdown splits by what can proceed
independently rather than by what is shippable alone, and a ticket is blocked only by
what it genuinely reads from. `work-discovery` drops every blocked ticket as a filter
before it weighs anything, then prefers the higher priority, then the ticket that
unblocks the most.

One defect in that rule was found by exercising it rather than by reading it, and
fixed in the same branch. The andon cord is *a bug **and** the tracker's top
priority*, both read from the tracker's own fields; on a GitHub backend Priority is a
board field, and a session that cannot reach the board reads the kind cleanly and the
priority not at all. The rule said nothing about that case, so the loop degraded
silently to ordinary ranking and walked past an open P1 bug — the failure P4 exists to
prevent, inside the rule that implements P4. **A field that cannot be read is itself
an andon condition**: report the stopped line and stop.

**Cost is set through the runtime, not through prose.** Every kept skill and agent
carries `model:` and `effort:`. A skill without `context: fork` that declares a
concrete `model:` overrides the *session's* model for the rest of the turn, so every
skill carries `model: inherit` and only the operator-triggered workflows — which own
their whole turn — carry a concrete `effort:`. The lane picks the reviewer definition:
`reviewer` (sonnet) in the change lane, `reviewer-feature` (opus) in the feature lane,
same mandate and same report, differing only in the two frontmatter lines. ADR 0005
measured 110 Opus reviews against 114 Sonnet at 18.4% versus 17.3% fail rate, under
the noise floor, so the cheaper model is the right default and the deeper one is worth
paying for where a miss is expensive to reverse. Nothing asks an agent to honour a
tier by reading about it.

**`specs/harness-assumptions.md`** is the new record behind all of it: one row per
hook, script, skill and agent, each naming what the component assumes an agent gets
wrong on its own and the *retirement test* that would close it. A row is not
permission to keep the thing — the assumption is the case for the component, and the
test is what retires it. Without such a table the v5 cull reset a counter and changed
nothing else. The spine points at it from *Where deeper truth lives*.


### The craft surface after #548

#548 is the content pass over what #547 kept: the eight craft skills and their
references, the nine workflow skills for description and for text T2 made redundant,
and the five agent files. It changed no mechanism, no hook, no template and no clause
of the spine's contract. What it changed is the text, and — for the first time — it
measured the text instead of reading it.

**The instrument.** The official `skill-creator` plugin's published loop, unmodified:
no bespoke runner, grader or viewer. Three recorded-failure prompts per craft skill
ship at `skills/<name>/evals/evals.json`, with `review-discipline`'s three review
prompts carrying their `diff.patch` fixtures beside them at `evals/files/`. The
prompts are drawn from the tickets that went past review cycle 3 (#484, #510, #511,
#537, #539), from `craft.md`'s defect classes, and from the improvement ledger.
Nothing under `evals/` is a test: `pyproject.toml` sets `testpaths = ["tests"]`, so
pytest collects none of it, and no runner or grader ships there.

**Three experiments, and the first one measured nothing on purpose by the time it was
read.**

| Experiment | Arms | Result |
|---|---|---|
| Iteration 1 | current text against its own snapshot — *byte-identical*, since the snapshot is taken before the rewrite | No skill effect was possible. What it bought is the number nobody had: the **noise floor**, mean \|Δ\| 0.057 and max **0.110** at skill level, 0.330 at eval level, over eight comparisons |
| Iteration 2 | rewrite against snapshot, both staged at neutral sibling paths with byte-identical briefs, arm letter randomised at seed 548, graded blind | 7 of 8 positive, mean +0.078, worst −0.033 (`architecture`), one-sided sign test p = 0.035. By **arm letter** the split is 4–4, which is what excludes iteration 1's label confound rather than assuming it away |
| Baseline | the kept skill against **no guidance** on the same prompts | 7 of 8 positive, mean +0.169. Four clear the floor outright — `review-discipline` +0.387, `worktree-isolation` +0.317, `architecture` +0.247, `work-discovery` +0.113 — and four do not: `engineering` +0.110 exactly at it, `authoring` +0.093, `assess` +0.083, `tracker` **0.000** |

The last two rank the set almost inversely, which is the point: *did this edit help*
and *does this file earn its context* are different questions, and only the second
could ever license a cut. Every figure above was re-derived from the benchmark JSON
against the unblind keys at review, and the snapshot arms were walked file by file
against `origin/dev` to confirm they are the pre-rewrite bytes.

**No skill was cut.** The four below the floor are unproven, not disproven, and the
attributed cause is measured rather than asserted: the graders' provenance audits show
the no-skill arms rebuilding skill content out of artefacts that existed only because
this repo is the plugin's own source — this record, `specs/proposals/lifecycle-reset.md`,
`specs/harness-assumptions.md`, `tests/unit/test_teardown_guidance.py` (retired by #615).
The localised demonstration is `worktree-isolation`: its cleanup eval was pinned verbatim
by that test as literal strings, and it is the one of its three evals where no guidance
scores identically to the skill — 6/6 in both arms — inheriting a dead
iOS-simulator teardown step from the phrases it copied. Its two unpinned evals split 8/8 against 2/8 and 5/5 against 4/5.

One arithmetic fact belongs beside that attribution, because it bounds what the
baseline experiment could have shown at all: for every one of the four, the no-skill
arm scored high enough that clearing 0.110 was out of reach before any confound is
argued. A perfect with-skill score leaves `engineering` exactly 0.110 of headroom,
`authoring` 0.093, `assess` 0.083 and `tracker` 0.040. Three of the four did score
that perfect 1.000, so their shortfall is the ceiling and not a judgement about the
skill — the same defective-proxy shape this run diagnosed in the original AC-1, now
reaching its replacement. The dogfooding confound is real and measured; it is not
what decided these four.

**`tracker` is the one case where that attribution does not hold, and it is recorded
open rather than closed.** Its no-skill arm reached 0.96 by grounding in `AGENTS.md`,
`specs/decisions/0015` and `0006`, `settings/harness.json` and
`specs/harness-assumptions.md`. The spine and `templates/spine.md` **ship to every
consuming repo**, so that confound will be present in the four-week window too and the
carry cannot produce a different answer there. What the flat result actually says is
that the tracker semantics are stated in more places than one — AC-6's subject, and a
contract change, which #548's *Out of scope* assigns to T2. Holding was the correct
move and the run held; the question is open, not answered.

**The leaning, measured with the ticket's own three instruments** — whole-file
`wc -w`, a line-based count of `**…**` spans, and a fixed-string grep for backticked
names of other skills. Each was reproduced against the ticket's starting-line table
before being trusted, and each reproduces it exactly. The `dev` column is
`origin/dev` at `faff22c`. The reference-pointer row counts **directed edges** — one
per pointer, so a mutual pair counts twice — over every file under
`skills/*/references/`. That convention is why it reads 5 where the change spec's
amendment listed 4: the amendment counted `assess`'s mutual pair in both directions
and `engineering`'s in one, missed `process-economy.md` reaching `review-discipline`'s
`craft.md`, and counted one `SKILL.md` deep-link that is not a reference at all.

| | on `dev` | at this record's tree |
|---|---|---|
| Largest `SKILL.md` | `review-discipline`, 3,401 words | `authoring`, 1,797 (cap 1,800) |
| Most bold spans in one `SKILL.md` | `review-discipline`, 90 | `promote`, 12 (cap 12) |
| Most other skills cited by one skill | `build`, 7 | 3, tied across six — `architecture`, `assess`, `authoring`, `build`, `propose`, `tracker` |
| A reference reached through another reference | 5 | 0 |
| `craft.md` contents | none | 49 entries in 6 families, every anchor resolving and every level-3 heading listed, both directions checked |
| Agent files | `reviewer` at 76 lines | all five under 60 — `dev` and `reviewer` 59, `architect` 52, `steward` 50, `reviewer-feature` 26 — each setting `model` and `effort`, each citing only skills that exist |

The whole guidance surface moved **48,816 → 47,497 words across 38 → 42 markdown
files** under `skills/` and `agents/`, derived at `faff22c` and at this record's tree
by `find skills agents -name '*.md' -exec cat {} + | wc -w`. So the large per-`SKILL.md`
reductions are mostly redistribution into four new one-hop references —
`review-discipline/references/certifying.md`, `authoring/references/decisions.md` and
`conditional-sections.md`, and `init/references/refresh.md` (deleted at #624) — each cited from its parent
with a stated moment to load it. That is a real saving at load time, because a
reference is read on its trigger and a `SKILL.md` is read whenever the skill is. It is
not a saving in bytes shipped, and the distinction is stated here rather than left to
be read off the per-file table.

**Two ledger rules written in, both at the altitude the measurement asked for.**
`authoring` gains LEDGER-547-3 whole, including the clause that does the work — *a
criterion of the second kind does not block a PASS* — because naming who produces the
evidence without releasing the verdict only renames the problem. `engineering` extends
its existing dependent sweep instead of siting a second copy beside it: a retired
*claim* has no identifier to grep, so grep the phrase and the mechanism it described,
treat a docstring as a home, derive the count rather than remember it, and enumerate
before repairing. Both iteration-1 arms already produced a correct *name* sweep, which
is why the second rule went in as an extension rather than as the sibling the brief
named; a sibling would have been the duplicate definition AC-6 forbids.

**Four contract terms realigned, none redefined.** The 2×2's FAIL cell stopped
carrying DEFER's discriminator and now reads *return it to the builder*;
`review-discipline`'s verdict section cites the spine as the definitional home and
keeps only what a review *does* with each verdict; `tracker`'s hold-label meaning
table went, leaving the spine's; and `authoring`'s lane table dropped a fourth
feature-lane trigger the spine does not have. That last one has a consequence worth
naming: a ticket carrying a consequential architecture, data-model, interface or
security decision that reaches no protected area, changes no contract and came from no
proposal is now filed `simple` where `authoring` alone would have made it `complex`.
Whether the spine should gain the fourth trigger is a proposal, not a call this change
could make — the spine's contract section was a protected area at #548 (#588 closed that
list to three, and a directory or a document section is no longer on it) and this diff
does not touch it.

**AC-4 is carried, not met, and its deliverable is in the tree rather than in a
session.** Held-out trigger sets — 20 queries each, 9 positive and 11 near-miss
negatives drawn from the neighbouring skill each description fences off — ship at
`skills/<name>/evals/triggers.json` for all ten model-invocable skills, `routine`
included after #564 removed its flag. `digest` and `assess` joined the model-invocable
set at #565 without either gaining one: `digest` shipped no `evals/` directory at all,
and `assess` ships `evals/evals.json` but no `triggers.json` — a gap #565 found
already open, not one it made. #627 gave `digest`'s replacement half of it: `drain`
ships `evals/evals.json`, carrying the `drain-the-ledger` case that moved with the
procedure it scores, and still no `triggers.json`. The set is now twelve
model-invocable skills, ten of
which carry a held-out trigger file; generating one is #547's own multi-day, ~130-run
job, #565's criteria named no such deliverable, and the gap is carried here rather
than closed. The published loop could not rank the ten it has on this host: seven
skills — every loop run that produced a `results.json` — returned an identical 3/5,
and four probes established why —
`run_eval.py` counts a trigger when a one-shot `claude -p` invokes a temp command, and
here that fires only for a query handing the description back as an imperative.
Realistic positives scored 0.00 throughout; the negatives are the whole of the 3/5. An
instrument with no dynamic range cannot rank descriptions, so the number is withheld
rather than reported as one.

**Cost.** 123 sub-agent runs and 16 grader passes against the ticket's stated ~130-run
budget, plus the `evals/` directories that ship to every consumer: 21 files,
**69,087 bytes**, measured at this record's tree by
`git ls-files 'skills/*/evals/*' | xargs wc -c`. That is the P2 spend the ticket
declared and bounded. Two defects in the instrument were found and corrected
inside the run rather than after it: a no-skill envelope that barred
`review-discipline`'s own diff fixtures along with the repo, and absolute paths in all
24 copied `metrics.json` files naming the iteration and the arm, which identified the
with-skill arm to any grader who opened one and forced a full re-grade of all eight.

### The craft file's fiftieth entry

#603 adds one entry to `skills/review-discipline/references/craft.md` and moves nothing
else: *A corpus is blind to any dimension its fixtures hold constant*, in the *Vacuity*
family between *A positive control must exercise the predicate, not re-implement it* and
*Born green*, with its Contents line in the same position. The header sentence the count
was ever evidence for — *Fifty-odd entries in six families* — stays true, so no figure
here needs a date. Contents order matches heading order in all six families and every
entry link resolves, derived at this record's tree.

**The title was cited three times before it existed.**
`tests/unit/test_gate_command_declaration_contract.py:270` and `:447` cite it verbatim,
`tests/unit/test_context_branch_parsing_contract.py:222` in variant wording, each as
though the entry shipped — this file's own *A forward reference becomes a lie the day its
dependency ships*, in the direction where the dependency never arrived. The entry resolves
all three without editing any of them, and does not make the tree cite-clean: other
non-existent entries are cited elsewhere, and no criterion claimed otherwise. Nothing
mechanical holds any of it. No gate stage reads `craft.md`, no test reads its Contents,
and ADR 0017 D5 admits no guard over prose meaning, so the anchor derivation and the cite
resolution are a reviewer's read with the same standing as the process-economy claims
below.

**The falsifying example contradicts this repo's own history, deliberately.** V8 answers
a malformed document either with a window of its source quoted back or with a message
carrying none of its bytes, and which one a document draws turns on the parse error rather
than on its opening character:
`{"a":}` opens with `{` and is quoted, `{,}` opens with `{` and is not, both measured on
node v24.19.0. `f8cf773`'s commit message and the comment it added to
`tests/unit/test_gate_evidence_hook_scope.py` state the opening-character rule instead.
That commit's fixture repair was right and the generalisation beside it was not; the entry
is written against the measurement, and the two test files are left as they stand.

**The evidence is direct use, and the residual is stated rather than hidden.** Four
recorded rounds of fresh contexts, each handed the shipped entry and one probe diff and
asked for blocking findings. Every diff the entry fired on genuinely held its dimension
constant, and it fired on none that was sound along that dimension. The must-not-fire
direction rests on one context that weighed the entry by name and declined, and on others
that matched their diff to a *different* entry: no code-side control ever came back with
zero blocking findings, because each successive control draft carried a real defect of its
own and another entry in this file caught every one. The B-side stopped there rather than
spend another attempt on the instrument, the probe domain having turned out to carry more
interacting dimensions than the control needed.

**Four refusals, each with its principle.** No guard over the Contents/anchor
correspondence — admissible under ADR 0017 D5 as tree-consistency, but a guard module
against a one-entry diff blows the 3:1 ratio (P0). No second home in `skills/build/SKILL.md`, which carries no corpus, sample or probe
vocabulary and would be taxed on every build run for a class the reviewer's own file
already gates (P0, P2). No widening of `craft.md`'s load trigger, so a builder
commissioning a guidance probe on a prose-only diff still never loads the file — the
header makes the operator the budget-holder for that tax (P0), and the residual goes to
the improvement ledger alongside G2's, the choice to mutate the short-circuiting operand
of a conjunction as distinct from detecting a mispredicted killer. And no rewrite of the
three citing tests, which the entry makes correct where they stand.

### The console retires into a drain (#627)

`skills/digest/` is deleted and `skills/drain/` replaces it, built from the accepted
`operation-nuke` proposal. The console's report half does not move: five sections
restating, once a day, what one operator's tracker already shows, whose fourth section
was explicitly forbidden from deciding anything it surfaced. What survives is the act
the operator actually performed — clearing what has accumulated — and the improvement
ledger's pass joins it from `/assess` step 5. The two piles keep deliberately different
procedures because the material differs: **held tickets one at a time**, each one
question whose answer changes nothing about the next, and **the ledger as one corpus**,
because entries written weeks apart turn out to be one pattern and deciding them singly
is how a ledger grows a backlog instead of shrinking. Step 5 now invokes `drain` and
reports what it recorded; the steward is refused the call in both its homes
(`agents/steward.md` and `.codex/agents/steward.toml`), on law 4 — the agent that wrote
an entry is the wrong one to decide it — and an unattended `/assess` still states the
ledger's size and stops. The ledger drain also names the spine's twin rule at the fold
step, which it had been inheriting silently: a fold is the filing most likely to hit a
twin, because the pattern-level candidate was abstracted from several entries moments
earlier.

**The consumer-naming mentions are deleted, not repointed, and that is the point of the
ticket.** At `b2fc67a`, an anchored search for the string `/digest` over `skills/`,
`agents/`, `templates/`, `AGENTS.md` and `CLAUDE.md` returns **19 occurrences in 11
files**, six of them inside the retired skill's own body and thirteen in ten others.
Those thirteen were producers naming their consumer: `tracker`'s `Holds` section, both
transport references' held-pile recipes, `work-discovery`'s outbound half and *Return
path*, `build`'s and `review`'s DEFER bullets, `improvement-ledger.md`, and the spine in
three copies. `build`'s went furthest — *"`input` is the whole return path for a DEFER:
`/digest --drain` selects `input` and nothing else"* — a producer warned about a
consumer's selector, which documents a coupling rather than removing it. Rewriting each
mention under the new command name would have preserved every one of them, so each is
deleted against the interface that already mediates the relation: a producer calls
`tracker`'s `hold`, a clearing pass calls `held`, and neither knows the other exists.
`build`'s DEFER bullet now commits and pushes, holds through `hold`, routes findings by
class, and says in the run's own final summary that the ticket is held and what it waits
on. **This supersedes the second half of the #567 entry above**: that entry's
spent-budget path named `/digest`'s *At the keyboard* section as its own return, and
with the console gone a spent cycle budget differs from a DEFER by its label alone.

**`hold` got stricter, and that is where the change's risk concentrates.** The spine has
required comment + label + assignment since the hold contract was written, but the
operation trusted each caller to remember all three. It now writes all three, reads the
ticket back, and reports an **incomplete hold** naming the missing part rather than
succeeding. The failure it closes is specific: a hold that lands the comment and the
label and loses the assignment leaves the ticket **pickable**, so the next unattended
tick takes it and builds past the very question the hold was raised to ask — and it
reports success while doing so, which is why the operation reads the property back
instead of trusting an exit status. `github.md` names the concrete cause (`gh issue
edit` drops a login the repository cannot assign and still exits zero) and `linear.md`
gains the mutation triple plus the read-back, with the warning that a bare `labelIds`
on `issueUpdate` replaces the whole set and takes the `assurance:` label with it. The
write order is fixed — comment first, assignment last — so a partial hold leaves the
question on the record rather than a ticket held for a reason nobody wrote down.

**AC-2's evidence is verification by use, and the position is #567's.** The criterion
asked for RED then GREEN, and `hold` is prose in a skill body: a test asserting that a
section names three writes is a wording predicate over prose, which ADR 0017 D5 admits
under no class and law 2's own comment refuses (#511, #520); making `hold` executable
instead would ship a plugin-owned executable into a consumer, which ADR 0022 point 1
forecloses. So the evidence is two rounds of fresh contexts given only the shipped hold
text and the spine's contract — an `input` hold on an ambiguous spec, and an `operator`
hold with a colleague in the prompt urging a two-of-three shortcut — both performing all
three writes, reading them back per property, and naming the pickable-ticket failure;
the second refused the shortcut on the prose's own grounds, preferring a read-back to
hearsay. Neither round found a defect in the prose. That is the standing *The DEFER
return path* (#567) records on this same subject, and the reviewer's read is the other
half of it. The executable evidence in this change sits elsewhere: AC-4 on
`tests/unit/test_workflow_skill_invocability.py` (class (d)) and AC-1 on
`tests/unit/test_landing_page_inventory.py` (class (e)), whose both-directions
comparison is what forced `docs/index.html` to move with the directory rather than
leaving the page naming a skill the tree no longer carries.

**The version class is major, and the rename is why.** `10.1.0 → 11.0.0` across all
five homes — both plugin manifests and the `spine:generated` marker in `AGENTS.md`,
`CLAUDE.md` and `templates/spine.md` — raised at `/build` step 1 inside the worktree.
A renamed command is the first case the compatibility grammar's major clause names, and
the refusal moves with it: a call that `Skill(digest)` answered is now unanswerable and
`/drain` answers instead. A major reaches a consuming repo as a decision rather than an
auto-pull, which is the correct arrival for a workflow that no longer exists under the
name a repo's own notes may cite.

**What the drop costs, recorded rather than absorbed.** D9 of the proposal said the R
line — tickets opened against closed, with the opened count split by source — must not
fall out; the operator answered it by dropping the R line and the load line rather than
rehoming them, and the proposal carries that as a dated amendment in place rather than a
silent divergence. Nothing replaces the R line. `/assess process`'s baseline is three
fixed rows (assurance lines per product line, gate wall-clock, checks with no nameable
failure-reason) and none of them counts tickets opened against closed, so spine P3's
obligation to keep the queue's growth rate visible now rests on the tracker's own
opened-and-closed view. A second loss has no such fallback: `/digest`'s *At the
keyboard* section was the only enumeration of `operator`-labelled tickets anywhere in
the tree, and `/drain` deliberately does not surface them for an answer — they are
hands-on errands cleared on the actual task — so what remains of them is the count the
held pile closes with, one number that makes a pile nobody is clearing visible without
giving it a section. Both are calibrated to the stage the spine's *This repo* line
declares: one operator, a dozen open tickets. A repo that outgrows either adds the row
to `/assess process`'s baseline rather than rebuilding the console.

### The assessment layer

`/assess` writes one dated report per pass to `assessments/<YYYY-MM-DD>-<scope>.md` in the `templates/assessment.md` format. That template owns the **retention convention**; `skills/assess/SKILL.md` step 4 applies it after each pass, folding every superseded report into a one-line entry in the rolling `assessments/LOG.md` and deleting the file. The rule keeps the latest report per scope plus any report with an open finding, and since #468 a **retired scope** is its one exception: a report whose scope the current `/assess` can no longer produce — ADR 0015 narrowed the scopes to `code | architecture`, and `process` joined them below — is superseded once none of its findings are open, with the open-finding bound still binding until then. The clause had one live subject and the same change folded it: `assessments/2026-08-04-system.md`, the last `system` pass. Its findings, the tickets carrying them, and their closure against the tracker are recorded in that report's entry in `assessments/LOG.md` — the line keyed `2026-08-04 · system` — and cited from here rather than copied, so the two cannot disagree. They did disagree once, in the commit that wrote both (`10170c7`): the LOG entry counted tickets from the same day's other passes among this report's findings until `ad9c7f6` corrected the attribution, and this record happened to hold the version that was right. `assessments/` holds four reports at this record's date — `2026-07-19-pre-publication-readiness.md`, which exempts itself from the rotation in its own header, `2026-08-04-architecture.md`, `2026-08-17-code.md`, and the retained first process pass `2026-08-31-process.md` — plus `LOG.md`.

`/assess` takes exactly one parameter now: the scope. `--deep` is gone from the command, the steward role and its Codex mirror, the assessment standards (now `skills/assess/references/finding-bar.md`), `skills/architecture/SKILL.md`, and `specs/architecture-principles.md`. The lenses the modifier used to add — test-coverage quantity, design-system adherence, spec/doc coherence — fold into the `code` row rather than disappearing, so the parameter retired without retiring the work. The proposal that recommended it left the tree with the other settled proposals at #547; the three surviving `--deep` strings are all in `assessments/`, dated records of passes that ran under the modifier. `design/01-voice/README.md` swapped `--deep` for `--refresh` in its verbatim-syntax rule, and dropped the citation of `tests/unit/test_landing_page.py`, a module the v5 cull deleted.

The third scope is **`process`**, and its domain standard is `skills/assess/references/process-economy.md`. It shipped as a skill of its own and #547 folded it into `/assess`, alongside the shared assessment standards now at `skills/assess/references/finding-bar.md`, which were the `assessment-craft` skill. `/assess` is the only caller of either, and guidance that has to be triggered by a description fires only when something remembers to trigger it — measured at 53% against 100% for a rule that is simply present (research 01 §10). Neither is on the skill listing any more, and neither can fail to load. It reads the assurance machinery rather than the product: vacuous checks, guards no occurrence justifies, ceremony that proves a stage ran rather than the property it protects, and measured gate or CI waste. Because its output is subtractive, its results split by door — the contradictions are filed as `PROC-` findings, and every deletion or efficiency candidate is an improvement-ledger entry carrying its measurement, exempt from `finding-bar.md`'s three-insight cap on the ground that a deletion candidate is the pass's ordinary output rather than a guidance edit. `templates/assessment.md` gains the process report shape (verdict, a baseline table near the top, findings, deletion candidates, efficiency candidates, undefended incidents, held, not assessed), and its retention line gains a fourth field for a `process` fold — `· baseline: <assurance:product ratio> / <gate wall-clock> / <unjustified checks>` — because the directory keeps only the one prior report per scope while this scope's value is the series. `assessments/LOG.md` states that field for future process folds. `assessments/2026-08-31-process.md` is the first process pass and remains in `assessments/` as the latest report for its scope.

The baseline that reference pins is three numbers whose derivations are recorded beside them, and its worked example carries the trap that produced this repo's own incomparable pair — ADR 0017's *24 modules, ~10,600 lines* counting helpers against the *31 modules, ~17.0k lines* this record carried at the time, excluding them, at different dates, with no command written beside either. The example: `git ls-files 'tests/*.py'` matches 37 files where `tests/**/*.py` matches 35, git not expanding the doubled star across the missing slash. The two it drops are `tests/__init__.py`, an empty package marker, and `tests/_gitutil.py`, one of the suite's four shared helpers whose other three sit under `tests/unit/` and survive either glob — so neither pattern settles helper treatment, which is why the treatment goes in the recorded command. Every figure in that paragraph was re-derived against the tree at review.

Why `process` is a scope rather than a lens inside `code` is recorded once, in `specs/architecture-principles.md` → *Assessment layering*: **a scope is admitted by its report contract, not by its subject.** `code` is a finding engine, `architecture` a holistic judgement, `process` a subtractive slate — three contracts, three scopes. A fourth needs a fourth contract; a subject that fits an existing one is a lens inside it, and the single genuine exception, a codebase too large for one run, is about size and is handled per-repo in `skills/assess/SKILL.md`. The workflow defers to that spec instead of re-arguing the split.

### The native Codex package and compatibility surface

Codex consumes the repository through `.codex-plugin/plugin.json` and the repo-local `.agents/plugins/marketplace.json`. That manifest declares exactly one content key, `"skills": "./skills/"` — no `commands`, no `agents` — so `skills/` was already Codex's only path to the nine workflows before #537, which is the probe that licensed deleting the generator: the consolidation had to run commands → skills, never the reverse. Each workflow skill now carries the contract directly, and its plugin-root preamble resolves shared `skills/`, `agents/`, `templates/`, `hooks/` and `.codex/` assets from an installed plugin layout.

**`scripts/generate_codex_artifacts.py` is deleted** (#537), with its `--check` gate stage and its test module. It held four mirror sets in step; three of them no longer exist — the nine `command-*` skills and nine `commands/*.md` collapsed into nine authored skills, the four `agent-*` skills were a third copy of the role body and went with them, and `AGENTS.md` is authored rather than compiled. One pair survives: `agents/<role>.md`, the definition Claude Code dispatches, and `.codex/agents/<role>.toml`, Codex's native adapter for the same role, which `/harness:hydrate` copies into a consuming repo. Deleting the generator *and* the check for that survivor would have traded a real protection for a line count, so the check survives as `tests/unit/test_codex_agent_adapters.py` — class (e) tree-consistency, both operands read from the index, the role body compared as an opaque string with emptiness refused on **both** sides so two failed extractions cannot compare equal. It earned its place inside one review cycle: a fix that moved configuration references in `agents/*.md` left `.codex/agents/*.toml` behind, and this is what caught it. No local mirror of the native plugin skills is tracked under `.agents/skills/` or `.codex/skills/`.

### Hydration — `/harness:hydrate` (#624)

`skills/init/` is deleted and `skills/hydrate/SKILL.md` replaces it: one invocation, no flag, whether the repo has never been hydrated or was hydrated against an older release. `references/refresh.md`, the refresh fixture corpus under `tests/fixtures/refresh/` and `tests/unit/test_refresh_fixtures_manifest.py` go with it. The change is 193 lines in against 7,986 out, measured at `92dad13` over tree `00b72cb` against `0c88fed`.

**One rule replaces the classification apparatus.** *Absence licenses creation; only positive identification licenses a rewrite; everything else is retained or blocked.* A plugin-owned region is one the workflow can name — the content between exactly one `spine:generated` pair, a `.codex/agents/*.toml` whose first line carries a plugin marker, the region above a `<!-- spine:copy:end -->` line — and replacing one is the generated-guidance exception ADR 0022 point 1 preserves. Nothing else is ever rewritten. **There is no greenfield/brownfield branch:** each artefact decides for itself under that rule, so the two words name only what the report says — *already hydrated* where any positive plugin mark is present, *first hydration* where none is — and a wrong label costs a sentence in a report rather than a byte. A predicate keyed on what a repo *lacks* is the shape this avoids, and the workflow states the one assumption it cannot check, that a consumer's agent instructions live at the repo root in `AGENTS.md`, where its reader can disagree with it.

**Thirteen steps, in order:** read what is there, a positive-identification pass that writes nothing; interview only for what the repo has not already declared; write `harness.yaml` where absent; write or refresh the spine; seed the path-scoped rules and the sub-directory instruction file each one earns; scaffold `specs/`; seed `specs/infrastructure.md`; declare the plugin's provenance beside the enablement in `.claude/settings.json`; hydrate the Codex role adapters, replacing one only where its first line carries either marker spelling; merge the gate-ignore patterns; copy out skill-attached assets; derive `CLAUDE.md`; dispatch `harness-audit` and report.

**The sub-directory instruction file is not a spine and not a copy** (step 5). It is directory-local guidance — what changes when you work *here* — and carries nothing the root spine already says, which is what makes progressive discovery pay. One body, two carriers: `.claude/rules/<name>.md` with `paths:` globs for Claude, and the same body as `<dir>/AGENTS.md` for Codex, which has no path-scoped rules and reads nearest-wins. The shared region is everything from the first `##` heading down and is identical in both; only the preamble differs, because it names a host mechanism. Both are repo-owned once seeded. The set of directories that earn one is the set of rules seeded, usually one and often zero — not a file per package or service, and no nested `CLAUDE.md`. This inherits `init` step 4 unchanged and is not a deviation from the ticket.

**No gate, and nothing under `scripts/`** (step 10, AC-1). ADR 0022 point 1 stopped the plugin writing an executable it owns into a consumer's tree, so `scripts/harness-config.js` and `scripts/package.json` stay in the plugin and are read from there. Where a repo has a gate it is left alone; where it has none the operator is told what the gate must do — the interview's lint, typecheck and test commands in order, non-zero on the first failure — and writes it at whatever path `commands.verify` names. No skeleton, because a gate is the one thing whose bytes the repository has to own, and the run reports that it wrote none. The gate-ignore block is still merged pattern by pattern rather than as a unit, and still writes no `harness:gate-ignore` marker into a consumer's `.gitignore` in either spelling; `tests/unit/test_hydrate_gate_ignores.py` holds `.gitignore`'s block against that block and against an explicit set, so a shared omission cannot make the comparison vacuous. **AC-1 named a RED-then-GREEN run over a greenfield fixture and no such run was performed**, here or in the build session. What stands behind it is the smaller form ADR 0019 admits for prose — direct review of both prohibitions in step 10 and of the closing *What this never does*, against ADR 0022 point 1 — plus the one mechanical operand the step does have, the gate-ignore guard above. Recorded rather than deferred, because the substitution is the matrix working as written and not an omission; what a probe would still buy is the *use* half of law 2's "guidance is verified by using it", and the first hydration of a real consumer is where that arrives.

**`CLAUDE.md` is derived last** (step 12), after every edit to `AGENTS.md`, in four states and no fifth: absent gives `written`, bounded by exactly one `<!-- spine:copy:end -->` line gives `rewritten`, an `@AGENTS.md` pointer gives `rewritten`, and anything else gives `blocked`. Reporting the overwrite is mandatory and names every line in the copy region that `AGENTS.md` does not carry, verbatim, or says in those words that no such line exists. Verified at review over the index rather than through the suite: `CLAUDE.md`'s first 19,370 bytes are `AGENTS.md` byte for byte, with the boundary marker alone on the line immediately after and occurring exactly once.

**No transition logic, and where that is actually held.** No step removes, migrates or classifies a vendored gate asset. A repo whose `scripts/` holds files the workflow did not write gets them left untouched and unclassified; the one-time cutover for a repo carrying assets from before ADR 0022 is #629's, with its own lifetime. The report's four actions are `written`, `rewritten`, `retained` and `blocked`, and `migrated` and `deleted` are absent so a step that wanted either has no word to report it with. That argument holds, but it is the reinforcement rather than the mechanism: what carries the constraint is that step 1's read pass enumerates its subjects and `scripts/` is not among them, so no later step has a classification to act on — backed by the two explicit prohibitions in step 10 and by the closing *What this never does*. Step 9's recognition of the legacy `# Generated by scripts/generate_codex_artifacts.py` adapter marker is not a transition branch: it identifies ownership, removes and migrates nothing, and the workflow states that a future marker change joins that list rather than replacing it.

**One dispatch point remains ahead of what it names.** Step 13 dispatches the `harness-audit` agent, which **#625 built**: `agents/harness-audit.md` and its Codex mirror `.codex/agents/harness-audit.toml` ship at this tree, `agents/` now carrying six roles, with `tests/unit/test_codex_agent_adapters.py` holding the two bodies and descriptions in correspondence. It reads the hydrated repository and the plugin installed beside it — the spine, the derived `CLAUDE.md` copy, the Codex role adapters, `harness.yaml`, the gate declaration, disowned plugin assets, scaffold and plumbing — and reports the drift between them; its tools are `Read, Glob, Grep, Bash`, carrying no `Write`, and it reads what *is*, never what *passed* (ADR 0022 point 3) — no verdict, no gate result, no CI state, no certification. Step 13's fallback for a host that reports no such agent — one printed row, no audit performed in its place — is unchanged and stays live for a repository that has not re-hydrated onto this release. Step 11 copies out skill-attached assets, and **#626's design-system asset is not built either, so only the copy-out hook ships and no asset with it**; the step says this release ships none and moves on. Each destination is named by the producing skill rather than by this workflow, so a skill that gains an asset lands it and its destination together and step 11 needs no edit — which is also what keeps the copy-out inside ADR 0022 point 1, whose permitted pattern is a generator copied out once and owned by the consumer thereafter.

**Nothing here changes how `.claude/rules/design-system.md` or `templates/rules/design-system.md` is seeded.** The rule is still seeded from the template where absent, still repo-owned from that moment, still never overwritten by a later run, and its Codex twin `design/AGENTS.md` is still seeded beside it. What moved is the preamble sentence naming the carrier: `/harness:init` step 4 and `--refresh` became `/harness:hydrate` step 5 and *a later hydration*, in all three files. The shared region — everything from the first `##` heading down — is untouched in every one of them, and was verified byte-identical between `.claude/rules/design-system.md` and `design/AGENTS.md` at review. **#608's text-only carve-out to the *Visual evidence* requirement lands inside that shared region** (`## Visual evidence, when the diff touches a user-facing surface`, line 92 in both the repo rule and the template), so it neither depends on this change nor conflicts with it. #608 landed first, reaching `dev` at `3281242`; the merge into this branch conflicted on one paragraph of this record alone, where both sides had rewritten the path-scoped-rules sentence, and the resolution keeps #608's carve-out with this change's carrier word. Verified at certification: the shared region is byte-identical across all three homes, and this record's *The spine* paragraph carries both sides.

**AC-3, as decided.** The roughly 1,340 lines the ticket put in question are retained on recorded mutation evidence rather than opinion: eleven staged probes, all `KILLED`, run in a throwaway worktree at `85088c8` with the tree oid re-derived and compared to the pristine value after each entry. All five candidate modules read the index through `tests/_gitutil`, which `scripts/mutate.py` cannot reach because it edits working files, so the staged probe is the method this repo already accepts for the class and `test_spine_template_parity.py`'s own docstring records that (#490). Two decisions contradict the ticket's own retirement list, and the evidence carries the contradiction. `test_init_gate_ignores.py` is repointed and renamed to `test_hydrate_gate_ignores.py` rather than deleted: three probes kill it, one on the hardcoded set and two on the cross-file parity in both directions, and the rename moves its second operand's path without emptying its subject — verified at review, `_EXPECTED` and both assertions are unchanged. `test_fixture_git_init_declares_its_branch.py` never had `tests/fixtures/refresh/` as a subject at all: it scans the tracked Python sources under `tests`, and that corpus held **no Python file** — 23 files across `.sh`, `.yaml`, `.md`, `.json`, `.js` and `.gitignore`, counted at `0c88fed` — while the string `refresh` occurs nowhere in the module. It was grouped onto the list by the word *fixture*. `test_refresh_fixtures_manifest.py` is the one retirement, and not on liveness: its subject was `tests/fixtures/refresh/MANIFEST.md`, which this change deletes.

**The version class.** A renamed command exceeds the minor floor, so this cycle owes a major, and it already carries one. `main` stands at `10.0.0`; all five homes in the candidate — both plugin manifests and the `spine:generated` markers in `templates/spine.md`, `AGENTS.md` and the `CLAUDE.md` derived from it — stand at `11.0.0`, raised at #620 and verified equal at review. `plugin-version.js` reports `already-ahead`, and a second raise inside one cycle is what `test_a_second_run_in_one_cycle_is_a_no_op` refuses, so none is owed here. The release therefore reaches a consuming repo as a decision rather than an auto-pull, which is the point of the class: `/harness:init` and its `--refresh` flag are gone, and a repo that has not adopted `11.0.0` keeps invoking a command this plugin no longer ships.

**The sweep, and what it left.** The ticket's amendment required a search of the tree with each hit decided, never a sweep against a list. Live instructions whose carrier changed were rewritten: `README.md`, `MIGRATION.md`, `docs/index.html`, `.claude-plugin/marketplace.json`, `templates/harness.yaml`, `templates/spine.md`, `templates/rules/design-system.md`, `.claude/rules/design-system.md`, `.claude/rules/scripts.md`, `design/AGENTS.md`, `design/01-voice/README.md`, `AGENTS.md` and `CLAUDE.md`, `skills/engineering/SKILL.md`, `skills/build/references/run-state.md`, `skills/review-discipline/references/improvement-ledger.md`, `specs/architecture-principles.md`, `specs/harness-assumptions.md`, `scripts/plugin-version.js`'s cited exemplar, and nine test-module docstrings. ADRs 0017, 0018 and 0021 and the superseded proposals were left as history. `skills/engineering/SKILL.md`'s consumer-migration rule was rewritten rather than deleted or repointed at a transition step: its principle survives, because `harness.yaml`, the spine and the seeded rules are still consumer-owned; the carrier became hydrate's brownfield reconciliation; and the sentence now bounds the population it reaches to the repo-owned set and the generated regions inside it. `skills/architecture/evals/evals.json` eval #3 was filed as **#631** rather than fixed here, correctly — its stale subject is `scripts/gate-marker.js`, orphaned at #621 rather than by this change. Four more hits were rewritten and are named here because the paragraph above omitted them: `.gitignore`'s state-artifacts comment and eval #1's prompt, both repaired at `ae15a03` (*Known limitations* below carries why they were late); `skills/build/evals/triggers.json`, whose fictional-ticket query named the retired flag, re-subjected with `should_trigger` untouched; and `specs/proposals/operation-nuke.md`, which is **accepted** rather than history and cited `skills/init/references/refresh.md` — a path this change deletes, which `tests/unit/test_accepted_proposals_cite_live_paths.py` would have caught at the gate, so the cite now names the reference without spelling a dead path.

### Two-branch topology

This repo runs `dev` (integration) → `main` (release) — ADR 0003 as amended by ADR 0017 D6 and again on 2026-08-19, recorded in `specs/infrastructure.md` → *Branch topology*. `main` carries branch protection requiring a pull request, so no direct ref update advances it; `github-actions[bot]` has no bypass, which is why the promotion cannot push.

`.github/workflows/nightly-promotion.yml` checks out `dev` with full history and no persisted git credential, and runs `scripts/promotion-step.sh`. The script gates the exact candidate, then **opens or reuses a pull request whose head is the `dev` branch itself and merges it through the API**, binding the merge to the gated SHA with a server-side `sha=` head match. Head-is-`dev` is what lets it run unattended: that commit already carries the `lint-and-test` check raised by the ordinary `push: dev` trigger, so the check `main` requires is satisfied with no new run, no approval, and no stored credential — the token is the job-scoped `GITHUB_TOKEN`, forwarded to that one step. The workflow grants `contents: write`, `pull-requests: write` and `checks: read`, pinned as a set equality so a fourth grant fails rather than arriving unobserved.

**The published invariant is tree identity, not fast-forward.** A pull-request merge necessarily puts a commit on `main` that `dev` does not contain, so ancestry can no longer be the rule; what is asserted is that the tree landing on `main` equals the tree the gate certified. Two instruments carry it rather than one predicate: a **pre-condition** that, relative to the merge base, `main` contributes no content — the condition under which the merge is content-trivial — and **post-conditions** on the SHA the merge API returned, that the candidate is contained in it and that its tree equals the candidate's. The post-conditions *detect rather than prevent*: `main` has already moved when they run, and the prevention that survives is the pre-condition plus the head match. The property is self-sustaining — each promotion leaves `tree(main) == tree(candidate)`, so the next night's pre-condition holds with no back-merge, and this repo therefore does not back-merge.

Nothing is forced, repaired, or conflict-resolved. The night stops and reports when the gate is red, when the target branch is absent, when `main` carries content `dev`'s history does not, when `dev` moved past the gated commit, when the required check failed or never completed within the poll deadline, when the one open pull request is a draft or has a different head, when the pull-request number GitHub returned is not numeric, or when the merge's containment or tree identity fails. A refused night leaves its pull request open for the next run to reuse, and a night with nothing to promote exits clean without spending the gate.

`.github/workflows/ci.yml` runs the gate on pushes to `main` and `dev`, and on pull requests based on `dev` only. Pull requests into `main` deliberately raise no run: a pull request opened by a workflow using `GITHUB_TOKEN` produces runs in an approval-required state that nothing unattended can approve, and a second, permanently unapproved run carrying the required check's name on the gated commit is a deadlock this removes rather than reasons about. The cost is stated rather than discovered later — a human pull request into `main` from any branch other than `dev` gets no `lint-and-test` and therefore cannot merge, which is fail-closed and deliberate.

Three-role topologies remain available to repos that deploy to staging — the roles are per-repo configuration in `harness.yaml`'s `branches:` block. Fast-forward-only publishing is `/promote`'s default since #547 moved it there with the rest of the retired `infrastructure` skill; this repo is the recorded exception to it, not a rewrite of it, and `skills/promote/SKILL.md` states the substitute assertion a pull-request-only target gets instead.

### The design system ships as skill assets (#626)

The eight-tier design system was a source-only `design/` tree at the repo root: this
repo had it and a consuming repo, however it set `layers.design_system`, got the rule
and the template and none of the system. It is now `skills/design-system/assets/` —
`00-brand` … `07-flows`, `03-tokens/tokens.json`, and the token builder — and
`/harness:hydrate` step 11 copies it into whatever `paths.design_system` declares.
`design-system` is the first skill in the tree to carry assets that step copies out,
which is why step 11's wording changed with it rather than only the skill's.

**The copy is per file, never per directory, and that is the whole mechanism.** Step 5
runs earlier in the same layer-on run and seeds the Codex twin `AGENTS.md` *into the
design directory*, so a copy gated on the destination **directory** being absent would
find it present in every ordinary run, copy nothing, and report success over a consumer
holding an `AGENTS.md` and no tiers. Asking per file is hydrate's own root rule — absence
licenses creation — rather than an exception to it, and it makes `AGENTS.md` resolve
itself: step 5 writes it first, so the per-file rule finds it present and skips it. A
consumer that already owns a design system keeps every file of it and receives only the
ones it lacks. The first cut of this change gated on the directory and was caught at
review; the per-file rule is stated in both `skills/design-system/SKILL.md` and step 11,
and generalises to any later asset-carrying skill.

**The builder travels with the tiers it resolves.** `scripts/build_design_tokens.py`
became `skills/design-system/assets/build_design_tokens.py`, and its token source became
a sibling lookup (`Path(__file__).parent / "03-tokens" / "tokens.json"`) so one copy
serves a design directory nested three deep under `skills/` here and a repo-root
`design/` in a consumer. Its page default still needs a repo root, and the design
directory's depth is configuration, so `_repo_root()` walks ancestors for the nearest
`harness.yaml` — nearest rather than outermost, because a worktree checked out inside
another checkout must resolve to its own root, which is the live case on every agent
worktree in this repo. That walk is the only new executable logic the relocation
introduced and carries four cases in `tests/unit/test_build_design_tokens.py`: the
nested layout, the repo-root layout, no `harness.yaml` anywhere (the fallback), and a
nearer root beating a farther one. The generated-region marker dropped its `design/`
prefix in step, and `docs/index.html` moved with it.

**It ships as a reference implementation, not a turnkey tool**, and the skill says so
under its own heading: `SEMANTIC_TO_CSS_VAR` maps to *this repo's* `docs/index.html`
variable names and `PAGE_DEFAULT` points at this repo's page. Run unedited against
another repo's page it writes a `:root` region of variable names nothing there consumes,
and the failure is quiet — which is why the warning is prose in the skill rather than a
comment in the file.

**What the surface boundary now says.** `specs/architecture-principles.md` records the
design system as the first unit to cross from source-only into the surface, and
`.claude/rules/scripts.md` restates ADR 0022 point 1 at its actual line: the plugin ships
no executable it owns **and keeps refreshing** inside a consumer's tree. The builder does
land in a consumer, under the other half of that rule — copied out once, only where
absent, the consumer's from that moment, and never rewritten by a later hydration. No ADR
was amended, because the permitted pattern was already point 1's.

**The gate followed the code.** `scripts/verify.sh` typechecks and measures coverage over
`scripts` and `skills/design-system/assets`, and `harness.yaml`'s `commands.typecheck`
names the same two trees — an agent running the declared command must not get a clean
result over a tree the gate would redden. `tests/unit/test_verify_coverage_gate.py` holds
the mypy stage to exactly that set in both directions. `tests/unit/test_seeded_assets_are_tracked.py`
gained a `__pycache__` exclusion: #626 put Python under `skills/` for the first time, and
any session that imports the builder recreates bytecode the sweep would otherwise read as
an untracked shipped file.

**Seeded guidance stopped competing with the assets.** The rule that told a consumer with
no system to stand one up from `templates/design-system.md` by hand now tells it to set
the path and run hydration, with the template re-scoped to the contract that tree
implements rather than the thing that lands at the path. The sentence changed in all
three homes at once — `.claude/rules/design-system.md`, `templates/rules/design-system.md`
and `skills/design-system/assets/AGENTS.md` — whose shared region from the first `##`
heading was verified byte-identical at this review. `templates/design-system.md` was
re-scoped rather than retired: the accepted proposal keeps `templates/` wholesale.

**The landing page moved because a guard forced it.** `tests/unit/test_landing_page_inventory.py`
derives the inventory and the hero counts from the tracked tree, so a seventeenth skill is
a page edit in the same change: one `data-unit` entry, the Craft skills card 7 → 8, and the
hero 16 → 17 skills. The branch's second merge with `dev` conflicted here — this change had
taken skills to 17 while #625 had taken agents to 5 → 6 — and the resolution keeps both,
which the inventory guard then re-derives from the tree. Nothing else of #625's page content
was lost. The page's stale gate-marker prose, noticed while rendering evidence, was filed
onto #630, which already owns that sweep, rather than fixed here or filed as a twin.

### The landing page's prose numerals are gone (#633)

`docs/index.html:7`'s meta description said *sixteen skill packages* against a hero the
inventory guard already held at 17 — #626 moved every tagged count and the prose beside
the meta tag was not one of the guard's operands, so it shipped stale, green. The defect
named at filing was the guard's subject set, not the word: `tests/unit/test_landing_page_inventory.py`
reads three *tagged* shapes only — `data-unit` tags, `<span class="n">N</span>` counts, and
the hero's `<li><b>N</b> kind</li>` items — and a number written into a sentence is in none
of them.

**The operator decided the guard question ahead of the build.** Three options were on the
ticket: leave the six correct prose numerals as future drift, extend the guard to spelled-out
numerals in prose, or remove the numerals so nothing duplicates the guarded number. The
second is a predicate over what a sentence says, which ADR 0017 D5 refuses outright; the
third deletes the operand instead of detecting its drift (P0). The operator took the third
before the build started, recorded in the ticket's second comment and carried into the
change spec's Decision block.

**Seven prose numerals duplicated a guarded count; all seven are gone.** The meta
description, the `og:` and `twitter:` description pairs, the hero thesis, the inventory
lede, the agents-card caption, and the craft-skills-card caption each restated a number the
`data-unit`, `<span class="n">`, or hero reader already derives. Sentence structure and
every other word were left alone — no restyling, no restructuring — and the guard itself
did not grow: `tests/unit/test_landing_page_inventory.py`'s diff is its module docstring
only, corrected to name the three reader shapes above and state plainly that a number in
prose is not among them. No test was added, on the same D5 grounds the Decision took:
law 2 scopes a measuring test to a criterion about code, and both of this ticket's
criteria are about what the page and the docstring say.

**Two numerals were kept because they partition rather than duplicate.** "Three are
operator-triggered only" (of the hero's nine workflows) and "One refuses, three advise"
(of the hero's four hooks) each carry a fact the guarded total does not, so removing either
would delete information instead of a copy. The eight-tier design-system caption at
`docs/index.html:407` was left standing for the same reason from the other direction: its
`8` counts the design system's own tiers, a different subject that happens to share a
numeral with the guarded craft-skill count.

**One residual survives, recorded rather than repaired.** The hero still prints
`<b>9</b> workflows` and `<b>1</b> gate`, and the hero reader's regex alternation is closed
to `(commands|skills|agents|hooks)`, so neither of those two `<li>` items is derived there.
The `9` is not unguarded overall — its card's own `<span class="n">9</span>` is held to a
nine-entry list by the card-count sweep — but the hero's copy of it is not cross-checked
against that card. The `1` is unguarded everywhere: it counts a gate script that has been
one file since ADR 0015, and nothing in this tree derives that fact from the tree. Widening
the hero regex or adding a card for the gate would restructure the hero, which this ticket's
scope excluded; the residual stands until a change that touches the hero's shape for some
other reason picks it up.

### Creating a worktree reclaims closed-ticket ones first (#610)

`skills/worktree-isolation/SKILL.md` → *Creating the worktree* now runs a reclaim
before every branch cut: list `git worktree list`'s entries, match each to a
ticket by the `<repo>-<task-id>` naming convention, and remove the ones whose
ticket is closed — checking first for unsaved or unpushed work, since removal
destroys both, and leaving standing every worktree whose ticket is open or
whose name matches none, since another run may be working in it. This is
part (b) of #610; part (a), the DEFER-resume rule, was already `/build`'s own
*Resuming a held or deferred ticket* bullet, landed at #623 and recorded
above.

**Why an instruction at cut time, and not a sweeper.** ADR 0022 point 1
forecloses a plugin-owned executable persisting in a consumer, and a periodic
sweep needs a scheduler the plugin does not own; the worktree-cut moment is
the one every run already passes through with a fetched remote and the
tracker in hand. The #582 sweep this ticket cites found six of seven
`work-<n>` worktrees on disk belonged to already-closed tickets — the
built-but-never-torn-down case *Cleanup* does not reach, because *Cleanup*
runs only on a task that ships.

**The reclaim stays on the git side, so it does not repeat *Cleanup*'s
refusal.** *Cleanup*, below in the same file, forbids selecting a *resource*
— a container, simulator, volume or service — by a host-wide sweep or
another worktree's name, because nothing records this run as that resource's
owner. The new text removes only the worktree directory and git's own
administrative records, using *Cleanup*'s own commands, and leaves every
resource standing, reported rather than torn down: ownership there rests on
the tracker's own ticket state, not a name guess, so the two rules govern
different objects rather than contradicting each other.

**No test**: prose reviewed and used directly, law 2's subject is code. The
brief behind this ticket's build cited three stale worktrees observed live
on this host; none reproduce here — `git worktree list` carries only the
main checkout, `harness-610`, and one unmatchable agent worktree, all
correctly left standing by a walk of the new instruction against them — so
the change rests on the #582 finding the ticket already records rather than
on a reproduction this session could not repeat.

### What #636 repointed, as built

All three evals in `skills/engineering/evals/evals.json` graded machinery #621 had
already deleted (`hooks/push-target-guard.js`'s marker-gated refusal,
`scripts/gate-marker.js`, `scripts/land.js`) and every prompt pointed at
`/home/user/harness-ref`, absent from this host. Fixed as three `prompt` edits;
`git diff origin/dev...HEAD` touches one file, six lines, and `expectations` is
byte-unchanged in all three (AC-3).

**The fixture decision (AC-2).** `/home/user/harness-ref` is provisioned nowhere
in this tree, in git history, or in the harness that runs these files — it is a
build-container artefact of #548's measurement run, whose workspaces
*Known limitations* above already says do not survive it. Documenting a
provisioning procedure would mean inventing one, refused under P0. The prompts
now name the repository under test instead: eval 2's own sixth expectation —
the answer must actually run a search against the repo and report what it
found — is satisfiable only against a real, populated checkout, and the repo
under test is the one guaranteed present when the suite runs. Left open rather
than argued away: #548's baseline arms already reconstruct skill content out of
this repo's own artefacts, and pointing every prompt at the repo under test
widens that confound for a future no-guidance arm; the narrowed read fence
below reduces it without closing it.

**The three substitutes**, each keeping the shape its `expectations` grade.

| Eval | Was | Now | Verified against the tree |
|---|---|---|---|
| 1 `fail-open-guard-build-plan` | `hooks/push-target-guard.js` refusing a push without a marker | `hooks/test-lock-guard.js` refusing a locked-test edit outside the `fix` lane | `:241` the refusal, `:246` the fix lane's base-tree allowance, both read in full |
| 2 `retired-claim-sweep-before-handoff` | `--legacy-path` on the deleted `scripts/gate-marker.js` | `--repo` on `scripts/plugin-version.js` | Homes at `scripts/plugin-version.js:70,78-79`, `skills/build/SKILL.md:25`, `specs/features/plugin-surface.md:21,1506`, `tests/unit/test_plugin_version_script.py:734` — code, a shipped skill instruction, a spec record and a test, each read |
| 3 `quantitative-criterion-needs-measuring-test` | `scripts/land.js`, deleted at #621 | `scripts/harness-config.js` | 406 lines; scalar, fence and flow-mapping parsing at `:63-302`; the substitute keeps both numbers expectation 4 pins, `300` and `214`, arithmetically honest rather than asserted |

**The read fence is not uniform, by amendment.** Evals 1 and 3 widen the excluded
paths from `skills/`, `agents/` to add `specs/`, where an as-built record or an
accepted proposal restates guidance nearly verbatim; neither eval needs to read
any of it to answer. Eval 2 cannot take the same fence: its expectations require
naming non-obvious homes and require a search actually run and reported, and two
of the four richest `--repo` homes are `skills/build/SKILL.md` and
`specs/features/plugin-surface.md` — fencing off `skills/` and `specs/` there
would put the best answer out of reach. Eval 2's fence is `skills/engineering/`
alone, the skill under test, with the rest of the tree — `specs/` included —
open. The cost stands recorded: eval 2 gives up most of the contamination
protection the wider fence buys, so it is the least trustworthy of the three for
a future no-guidance baseline arm.

**Residue, checked by search.** No reference to `/home/user/harness-ref`,
`scripts/gate-marker.js`, `scripts/land.js`, or `--legacy-path` remains in
`skills/engineering/evals/evals.json`. The other eight `evals.json` files still
name `/home/user/harness-ref`, flagged on this ticket as a widening question and
not adopted: this ticket's scope is the one file its own problem statement names,
`skills/architecture/evals/evals.json` is #631's sibling repoint, and the
remaining seven stay open, the same absent-fixture defect on a different file
each.

### What #640 completed, as built

Three additions to the reviewer's brief, all guidance-only. `agents/reviewer.md`
→ *Your context is the packet* is now the packet's one definition and names the
ticket's **comment thread** as a required part — the thread is where #610's
strongest design objection and #636's scope amendment both lived, invisible to
a reviewer reading the body alone. `skills/build/SKILL.md` section 3 and
`skills/build/references/codex-review.md` point at that definition instead of
re-enumerating it; the two rival enumerations the grounding found
(`agents/reviewer.md:18-23`, `codex-review.md:8-12`, neither naming the thread)
collapse to one definition plus two pointers, `codex-review.md` keeping only
the two items the base packet lacks — the staged diff's lint output and
`reviewed_tree`.

`agents/reviewer.md` also gains one line pointing a reviewer that must
reconcile a mid-review base movement at `skills/build/references/reconcile.md`
(#631, held by luck before this — the rule was stated nowhere a reviewer's own
definition reached). `agents/reviewer-feature.md` gains no second copy: its
existing "read `agents/reviewer.md` and follow it exactly ... none of it is
restated here" already routes a feature-lane reviewer through the same
pointer, and a second line there would restate an operand AC-2 itself refuses.

`skills/authoring/SKILL.md` → *Acceptance criteria* answers #636's open half:
a filer amending scope in a comment now edits the acceptance criteria too,
leaving the comment as the rationale, because the criteria are what a reviewer
certifies against and a comment is not.

`agents/reviewer.md` and `.codex/agents/reviewer.toml` moved together,
`tests/unit/test_codex_agent_adapters.py` holding the two bodies equal. No
tests are authored: all three criteria name direct review and no quantity.

### What #641 repointed, as built

Applied #636's landed decision — the prompt names the repository under test,
not a fixture checkout — to the remaining eight suites in one pass:
`architecture`, `assess`, `authoring`, `drain`, `review-discipline`, `tracker`,
`work-discovery`, `worktree-isolation`. That eval-suite scope is 42 changed
lines across the eight files (21 `prompt` insertions, 21 deletions), and
`expectations` is byte-unchanged in all eight — confirmed by diffing every
changed line and finding each one a `"prompt":` line, none other.
`git diff origin/dev...HEAD` over the whole branch touches 13 files, 52
changed lines: the eight above plus the five version homes
(`.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, `AGENTS.md`,
`CLAUDE.md`, `templates/spine.md`) carrying `/build` step 1's 11.1.0 →
11.2.0 raise, in scope by the version-class rule rather than by this
ticket's own problem statement.

**AC-1.** The ticket's derivation, re-run over the reviewed tree:

```
architecture 0 3        assess 0 2         authoring 0 3
drain 0 1                engineering 0 3    review-discipline 0 3
tracker 0 3              work-discovery 0 3 worktree-isolation 0 3
```

Zero for all nine suites, `engineering` included (#636's earlier repoint,
untouched by this diff).

**AC-2, the convention.** #636's landed wording replaces the path with `this
repository`, drops `real repo;`, and carries the read fence through
unmodified. Nineteen of the twenty-one prompts are a straight noun
substitution — for example `architecture` 1: `"Design question on
/home/user/harness-ref (real repo; do not read anything under skills/ or
agents/ there)."` becomes `"Design question on this repository (do not read
anything under skills/ or agents/ there)."` Two needed the surrounding clause
rebuilt rather than the noun swapped in place, because "the repo is this
repository" is not a sentence: `review-discipline` 1 (`"Review this change for
me. The repo is /home/user/harness-ref (real repo; …)"` becomes `"Review this
change for me in this repository (…)"`) and `tracker` 1 (`"Working against the
repo at /home/user/harness-ref (real repo; …)"` becomes `"Working in this
repository (…)"`). Both keep the same substance — path gone, `real repo;`
gone, fence intact — so the convention is one shape across all 21, matching
`skills/engineering/evals/evals.json`'s three.

**The read fence, not homogenized, by design.** These eight suites fence
`skills/ or agents/`; `engineering` 1 and 3 additionally fence `specs/`, a
widening #636 made on its own reasoning and this ticket does not extend.
`worktree-isolation` 2 and 3 carry no read fence at all — true before this
diff and true after it; the diff touched only the path clause in those two
prompts, leaving the absent fence as it found it. Both observations predate
this ticket and neither is a defect this diff introduced.

**No guard added.** `evals.json` is `skill-creator`'s own format, run by its
model-orchestrated sub-agent loop rather than any script; `scripts/verify.sh`
gains nothing here, per the ledger's option A.

## Data model

**No persistent state beyond the tree itself, since #621.** The gate marker under `<git-common-dir>/harness/gate/` and the `refs/harness/*` namespace #539 added — gate records, claims and the green pointer — are both deleted, and nothing writes either. The one file that survives is `.harness/run.json`, which is gitignored, records where a run is rather than what is true of the tree, and is read by exactly one hook. This was never a run ledger (ADR 0015) and it is less of one now.

## Interface surface

- `bash scripts/verify.sh` — the canonical gate, run directly since #621; exit 0 green, 97 reserved for an unrunnable toolchain, tool exit codes otherwise. It writes no evidence. Production callers: `.github/workflows/ci.yml`, `scripts/promotion-step.sh`, every completion claim.
- `node scripts/plugin-version.js [--repo <dir>] [--remote <name>]` (#589) — the plugin's one version, raised once per release cycle by `/build` step 1. One JSON object on stdout carrying `bumped` and a machine `case`: `raised`, `already-ahead`, `no-plugin-manifest` and `no-release-branch` at exit 0, and `stale-base`, `release-ahead`, `release-unresolvable`, `release-manifest-unreadable`, `unreadable-version`, `homes-disagree` and `home-unwritable` at exit 2; 3 when git, the fetch or the configuration reader could not run, and 64 for usage. The exit vocabulary is the retired marker helper's, kept because it was already the repo's convention and #621 did not invent a second one. It writes every version home in its `CANDIDATES` list by substring and nothing else, and never commits, pushes, or runs the gate. Versions outside `X.Y.Z` with no leading zeros refuse rather than sort, because ordering a prerelease needs a SemVer precedence nobody specified. The fetch has no fallback to a local `refs/heads/<release>`: the operand has to be what a consumer can pull, so a plugin source with no reachable remote cannot run `/build` step 1. Runs from the plugin root and is **not** materialized into a consumer repo.
- `scripts/mutate.py check|run` — mutation instrument; usage in `CONTRIBUTING.md`.
- `scripts/promotion-step.sh` — the nightly's whole logic: the gate, the content-divergence pre-condition, pull-request open-or-reuse, the required-check poll, the API merge bound to the gated SHA, and the two post-conditions. Four inputs, all asserted before any work and none of them echoed: `GITHUB_WORKSPACE`, `RUNNER_TEMP`, `GITHUB_REPOSITORY`, `GH_TOKEN`. Called by `nightly-promotion.yml`; **executed**, not read, by `tests/unit/test_promotion_step_script.py` against a stubbed `git` and `gh` that record every invocation to one shared file, so ordering is assertable.
- `bash scripts/setup-cloud-env.sh` — the cloud provisioner, idempotent and safe to re-run; the spine's `commands:` block names it as `bootstrap:`. Callers: `scripts/session-start-bootstrap.sh`, the SessionStart hook this repo's own `.claude/settings.json` registers, and an operator provisioning by hand. Nothing in the gate or under `.github/workflows/` calls it.
- The plugin surface itself (skills / agents / hooks) — consumed natively by Claude Code via `.claude-plugin/` and by Codex via `.codex-plugin/`, the repo marketplace, and `skills/`, which both hosts read. `AGENTS.md` is authored, not generated, and is the always-loaded spine for both; `.codex/agents/*.toml` remain repo-owned hydration outputs supplying Codex's named-agent role adapters. No `.agents/skills/` or `.codex/skills/` local skill mirror is generated or tracked.

## Known limitations

- **~~The Stop hook's ownership filter needs both sides to declare a ticket (#587).~~** Closed by deletion at #621: the hook is gone, so neither the filter nor its false negative exists. Kept as a line because the reasoning — that a marker written over another run's bytes is indistinguishable from one that worktree earned — is part of why ADR 0022 point 3 refuses a verdict read at all. The original entry read: A session whose own worktree carries no `.harness/run.json` — an orchestrator at the repo root, which is #439's motivating shape and stays enrolled deliberately — admits every derived candidate, and the block still names a directory and still prescribes running the gate there. The filter's own failure direction is the false negative: a session that authored ungated work in a worktree whose run file names a different ticket is not nudged about it, and where no live session owns that worktree nothing else nudges either. A protected-branch landing is unaffected — `push-target-guard.js` refuses on the pushed tree and knows nothing of tickets — while a task branch was never guarded by either hook. What is lost is a reminder, against a false positive whose remedy was to write a marker over another run's bytes.
- **~~The attached shape of #569's root cause survives.~~** Closed by deletion at #621 with `integrationTip` and the hook that called it. The original entry read: `integrationTip` resolves `refs/heads/<b>` before `refs/remotes/origin/<b>` — #490 AC-3 decided that order deliberately, on the grounds that a stale local ref is the normal state of a working checkout, and pinned it with `test_the_tip_is_resolved_local_ref_first`. So a clean task branch whose commits have already landed on `origin/<b>` is still strictly ahead of the tip the hook resolves, still counts as work to claim, and still blocks a completion claim while its tree carries no fresh marker. #569 narrowed the arm to attached HEADs, which closes the shape all three of its recorded firings sat in and leaves this one open. Accepted rather than filed: the tree does not contradict its own contract — the arm behaves exactly as this section now describes and as #490 decided — and no firing of the attached shape has been observed, so a ticket would name no outcome anyone received (P0). Closing it means reversing a pinned decision, which is a proposal rather than a fix. File it when it is observed.
- **AC-1d cannot refuse anything, and #548 shipped with that visible.** Its second disjunct — *the shortfall is attributed to a measured cause and the skill is carried to the consumer-repo measurement window rather than cut* — names no threshold, no owner and no date, so a building session can always satisfy it; three successive reviews reached that reading independently. The operator ratified the wording after the result it would license was already on the ticket, so it stands for this change. What has no home at all is the teeth: *if the four-week window shows the same four flat against no guidance there, that is the evidence for a cut* lives in a ticket comment, owned by nobody and dated never.
- **The carried measurements have no comparison basis in the tree.** `evals/` ships the prompts, the assertions and the trigger sets. The benchmarks that AC-1b, AC-1c and AC-1d were decided from live only under `/home/user/eval-workspaces/`, `/home/user/eval-baseline/` and `/home/user/eval-meta/` on the build container, and the ticket's tables are their only durable record. The four-week window in calibrate and nano-erp is asked to re-answer AC-1d and AC-4 against numbers it cannot re-derive.
- **The measured rewrite is not quite the shipped rewrite.** The eval arms are byte-identical to `skills/<name>/` at `6e21f1a`, walked file by file at review, and four repair commits landed after them — `fda33e5`, `ddef7ba`, `4fe8933`, `a97873b`. So the text that produced the deltas above differs from what ships in six files, by `git diff --numstat 6e21f1a HEAD`: 14 lines in `review-discipline/SKILL.md`, 6 in `assess/references/process-economy.md`, 4 in `work-discovery/SKILL.md`, and 2 each in `authoring/SKILL.md`, `engineering/SKILL.md` and `engineering/references/specialized-verification.md`. The snapshot arms are byte-identical to `origin/dev`, walked file by file at review. Re-running 72 sub-agent runs for a 14-word trim is the over-processing P2 refuses, so the gap is recorded rather than closed.
- **AC-3's bold-span cap is met at zero margin, under an instrument that undercounts.** The ticket's instrument is a line-based `grep`, which cannot see a bold span wrapping a line. `promote` reads **12** under it — exactly the cap — and 14 under a multiline-aware count; `tracker` reads 11 against 12. The criterion names its own instrument, so both are met, and AC-3 is a proxy the ticket already says is a proxy. The next edit to either file should know that its headroom is a property of the counter rather than of the file.
- **The spine can go stale in a consumer** that never re-runs `/harness:hydrate`; the generated markers and a second hydration are the remedy, and since #624 that is the same invocation as the first with no flag to remember. Spine growth is a first-`/assess` metric.
- **The landing page's inventory, counts, and dual-host positioning are guarded; its remaining prose is not, and since #633 there is nothing left in the prose for that gap to bite.** `tests/unit/test_landing_page_inventory.py` holds `docs/index.html`'s `data-unit` inventories to the tracked tree, compares every inventory count with its list, derives the hero counts from the same tree, and requires the native Claude Code and Codex description in metadata and visible copy. The card-count pairing is positional and `_COUNT_TAG` is unanchored: a new `<span class="n">…</span>` elsewhere could take ownership of later tags, and nothing tests that shape. `build_design_tokens.py --check` holds the page's `:root` block and hex literals to the tokens under `paths.design_system`; other prose and the self-contained rule still rest on review. #633 removed the seven prose numerals that duplicated a guarded one — the meta description among them, which had gone stale at #626 while the hero it echoed had already moved to 17 — rather than widening any of these guards to reach prose, which ADR 0017 D5 refuses. Two hero items still escape every guard: `<b>9</b> workflows` and `<b>1</b> gate` are outside the hero reader's closed `(commands|skills|agents|hooks)` alternation, so neither is cross-checked there; the `9` is at least held at its own card, and the `1` — a gate script one file since ADR 0015 — is held nowhere. Recorded as a residual rather than repaired, because closing it means restructuring the hero, which #633 scoped out.
- **`.claude/rules/scripts.md` carries one bare figure for the token builder's coverage scope**, and it was measured before the review-cycle edits that grew the file: the rule reads *133 statements at 98%* where the gate at this record's tree reports 139 at 98%. The claim the figure stands for — that dropping the builder from the coverage scope rather than following it costs about four points of the total — still holds at 139, and no guard derives the number, which is why it can go stale silently.
- **One lock-file consumer has performed the migration** — nano-erp, 2026-08-18. `MIGRATION.md` carries its edges in *Edges from performed migrations* and still states, in *Honest limits*, what remains untested: later migrations should expect repo-specific edges, and the interview, the `CLAUDE.md` merge and uninstall ordering are instruction rather than tested code.
- **Nothing guards the provenance *instructions*.** `tests/unit/test_marketplace_provenance.py` asserts this repo's own declaration corresponds to its two manifests (class (e)); that `skills/hydrate/SKILL.md` and `MIGRATION.md` still tell a hydration to write one is prose, and ADR 0017 D5 admits no guard over it. The one instance in this tree is the whole mechanical check.
- **The consumer-facing guidance no longer names the helper, and nothing holds it that way.** #621 rewrote `skills/init/SKILL.md`, `skills/init/references/refresh.md`, `CONTRIBUTING.md`, `README.md`, `docs/index.html` and `.claude/rules/scripts.md`, and the two index-reading assertions that were the mechanical half lived in `tests/unit/test_gate_marker_js.py`, which is deleted. What replaces them is narrower and is a different claim: `test_no_shipped_executable_reads_gate_state` sweeps `hooks/` and `scripts/` for the retired spellings, so an **executable** cannot name the marker; guidance and specs are excluded deliberately, because a record may describe the retired mechanism and ADR 0022 itself quotes the sentence it forbids. The guidance half rests on enumeration at build and at review, which is where this review found the surviving homes it repaired.
- **~~The three marker implementations are held equivalent, not independent in origin.~~** Closed by deletion at #621: there is one implementation of nothing. All three copies of the marker algorithm and the contract test that compared them are gone, which is the cleanest possible resolution of an entry that had no other one.
- **`scripts/package.json` is a directory-wide declaration in a repo the harness does not own.** A consuming repo that declares `"type": "module"` at its root and keeps ESM `scripts/*.js` of its own has those files retyped by the manifest hydration places, and they stop parsing at whichever ESM construct they reach first. The failure is loud but lands at that repo's next run, on its file rather than on the harness's. #501 owns the migration; ADR 0018 records the remedy it should take. In this repo `scripts/` now holds five tracked `*.js` — derived at this record's tree by `git ls-files 'scripts/*.js'` — and there is still no root `package.json`; see *The flat-placement premise no longer holds here* below.
- **Flat Node placement is now defended.** The init and refresh procedure refuses the flat placement when `scripts/` has another immediate JavaScript sibling or a non-CommonJS local manifest, retaining every gate asset and reporting the blocking path for an operator decision. The instruction-only migration neither isolates the helper automatically nor executes a consumer migration; its first downstream adoption performs attended end-to-end QA. In this repo `scripts/` now holds five tracked `*.js` — derived at this record's tree by `git ls-files 'scripts/*.js'` — and there is still no root `package.json`; see *The flat-placement premise no longer holds here* below.
- **#510 supersedes the earlier JavaScript-only predicate.** `scripts/package.json` can affect every immediate module-bearing `scripts/` source: `*.js`, `*.mjs`, `*.cjs`, `*.ts`, `*.mts`, and `*.cts`. Hydration permits the flat managed assets only when the recognised helper is the sole such source and the local manifest is absent or CommonJS; every other source or incompatible manifest retains every asset and is reported by path. In this repo `scripts/` now holds five tracked `*.js` — derived at this record's tree by `git ls-files 'scripts/*.js'` — and there is still no root `package.json`; see *The flat-placement premise no longer holds here* below.
- **~~The flat-placement premise no longer holds here.~~** Moot since #621: nothing is materialized into a consumer at all, so there is no placement to be safe or unsafe. The three bullets above are kept because they record why the plugin stopped doing it — a directory-wide `scripts/package.json` in a repo the harness does not own, and a safety test whose premise its own repo had already broken at #537. `skills/init` no longer wrote a gate asset and `refresh.md` no longer classified one; #624 deleted both files, so the fenced steps 3 and 4 that were the residue are gone rather than pending.
- **`.claude/settings.json`'s own `hooks` block is unheld against the files it names.** `hooks/hooks.json` gained its guard at #489, but the installed settings wire the same four hooks a second time by relative path (`node .claude/hooks/<name>.js`, reaching them through the tracked `.claude/hooks` symlink), and only that block's correspondence with `settings/harness.json` is measured — a renamed hook file would leave the second wiring dangling with nothing red. The same block's `SessionStart` entry names `scripts/session-start-bootstrap.sh`, a path `settings/harness.json` does not declare at all, so the subtree rule admits it and nothing measures it either; neither bootstrap script is executed by a test.
- **No guard enforces the assessment retention convention.** Deriving a report filename from an `assessments/LOG.md` line means parsing that line's prose into a path, which ADR 0017 D5 class (e) excludes — it admits a *cited* path and the file it names, not a constructed one. The retired `test_assessments_retention.py` went in the v5 cull on that ground and was not revived; the state is checked by a reviewer against `git ls-files`.
- **~~Two sweep hits at #624 were left undecided.~~** Closed inside the ticket. At `92dad13` the sweep had missed `.gitignore:37`, a comment naming `/harness:init` as the hydrator that never delivered the loose `.harness/` line, and had left `skills/architecture/evals/evals.json` eval #1 posing its hypothetical about "the init workflow" writing `scripts/verify.sh` while the session record claimed the rename. Both were repaired at `ae15a03` and verified at certification: the comment names `/harness:hydrate`, and the eval's prompt names the hydration workflow with exactly one of its seven expectations touched, the name inside it and nothing graded. Neither ever broke anything a consumer receives — a comment and a hypothetical prompt — so the entry is kept for the lesson that a recorded sweep and the tree can disagree, and that the disagreement is found by reading the tree.
- **The eval that grades the absence-predicate lesson now has its answer key in the tree.** `skills/hydrate/SKILL.md`'s *There is no greenfield/brownfield branch* paragraph states, in the workflow's own words, the failure `skills/architecture/evals/evals.json` eval #1 exists to see whether a model can find: a repo missing something because its own policy forbids it satisfies an absence test trivially and then gets written the file it rejects. The eval's prompt already forbids reading `skills/` in the repo under question, which is what keeps it honest, but that is a prompt instruction rather than enforcement, and skill evals are outside the gate. Recorded rather than acted on: the remedy is the eval's, not this workflow's.
- **Whether `main`'s protection actually *requires* the `lint-and-test` check is off-tree, and no green suite here implies it.** The promotion's safety argument has two halves. The first is in this tree and is tested: the script refuses to merge unless it observes that check completed-successful on the gated commit, and the check's name is derived from the names `ci.yml` will actually publish — each job's `name:` where it declares one, its key otherwise — rather than restated, so a rename on either side fails. The derivation is a hand-rolled read of the `jobs:` mapping rather than a YAML parse, and its bound is stated rather than assumed: it reads a `name:` whose value is on the `name:` line, and **refuses** every other spelling instead of falling back to the key, which is the silent mis-derivation a second review measured live. It is exercised on synthetic workflows whose answers differ from this repo's, because `ci.yml` declares no job-level `name:` and could not exercise the shadowing branch at all. The second half is the *server* refusing a merge that lacks the check — GitHub branch-protection configuration that nothing in this repo can read, and that an operator can change at any time with no signal here. Read on 2026-08-19 it was in force (`lint-and-test`, `strict: false`, zero required approvals, `enforce_admins: false`). The related blind spot #491 closed, and the narrower one it leaves: the script's three `--jq` expressions used to be exercised by nothing, because the `gh` stub emitted post-`jq` text at every call site — so the check-run poll's slice, the pull-request list's projection and the merge's `.sha` could each be changed with the whole suite staying green, and `.[-1:][]` → `last` did exactly that while turning a named arm into dead code. The stub now holds **raw JSON** and runs each call's own program over it through a real engine, so the expressions decide: the empty check-run set reaches its named *no run yet* arm rather than reporting a `null null` state GitHub never returned, the listing's projection is what the draft and moved-head refusals name, and `--jq .sha` is what the promotion reports. **What is still not measured is `gh`'s own engine.** `gh --jq` is evaluated by an engine embedded in `gh`; these tests evaluate the same programs under the `jq` binary they resolve, and a divergence between the two is live and unclaimed either way.
- **The promotion path is now observed, and it turns on a repository setting nothing in this tree can read.** Three promotions have completed: `20c84ac → 33199bc` (the `workflow_dispatch` bootstrap, 2026-08-19), then `b5262f9 → 5f13481` and `b2fc045 → 3ddec02` on the schedule (2026-08-20 and 2026-08-21); three later nights had nothing to promote and exited clean without spending the gate. Tree identity held on all three merges, and the pre-condition held on the second promotion — whose merge base *was* the first promotion's candidate — which is the self-sustaining content-triviality this record previously carried as reasoning rather than observation. What the design did not anticipate is that **the job-scoped token cannot open a pull request unless the repository permits it**: the first bootstrap dispatch failed at `gh pr create` with *GitHub Actions is not permitted to create or approve pull requests (createPullRequest)*, and a second dispatch of the identical commit (`20c84ac`) succeeded 74 minutes later. The repository's Actions permissions report `can_approve_pull_request_reviews: true` today; that this field is the one governing that refusal is the reading taken here, not a correspondence this repo has measured. Either way the dependency is off-tree and revocable at any time with no signal in this tree, exactly like `main`'s protection above — and it fails loud, red at pull-request creation and before any merge.
- **Whether a merge performed by the Actions token triggers the Pages `pages-build-deployment` build is unverified.** `specs/infrastructure.md` promises `docs/index.html` publishes when `dev` reaches `main`; if that build does not fire, the page stops updating until one is requested explicitly. Nothing else about the promotion depends on the answer.
- **The cloud bootstrap's trigger is an undocumented host interface.** `scripts/session-start-bootstrap.sh` provisions only when `CLAUDE_CODE_REMOTE` is exactly `true`. The wrapper's header records the check behind that choice, made on 2026-08-19: the variable was absent from Claude Code's hooks and environment-variable reference, and absent from this repo's own environment in a session described as remote. It is used anyway, on the operator's explicit call, in preference to inferring *remote* some other way, and the cost is written down rather than discovered later — a host that never sets it leaves the hook inert everywhere, local and remote alike, with no signal that provisioning did not happen. Nothing in this tree can observe the host's side, so the variable's real behaviour is unclaimed in either direction; running `bash scripts/setup-cloud-env.sh` by hand is the fallback.
- **The process-economy reference asserts facts about this tree that nothing measures.** Its baseline section quotes the 37-vs-35 glob difference, names the two files that differ and the suite's four shared helpers, quotes ADR 0017's and this record's assurance figures, and names three vacuity shapes `skills/review-discipline/references/craft.md` has no entry for. Every one was re-derived against the tree at review and none of them is held by a test: a file added under `tests/`, or an entry added to `craft.md`, makes the prose false with the gate green. All three blocking review findings on this change were in exactly that class. The remedy is to delete the claims or guard them, and ADR 0017 D5 admits no guard over prose meaning, so the state is a reviewer's read — the same standing this record's own figures have.
- **Three sweep shapes are named outside the craft file by design.** Terminal-state-only loop tests, dead exemptions, and change detectors appear in `skills/assess/references/process-economy.md`'s ground-1 list and have no `craft.md` entry; several other shapes there map only loosely to differently-scoped entries. Admission to `craft.md` is an operator call at the drain and is never self-filed, so the two lists disagree until one happens, and the reference says so rather than papering over it.
- **The process filing split is restated in every one of these homes** — `skills/assess/references/process-economy.md` → *Filing*, `skills/assess/SKILL.md` in three places (the scope table, the report-contract bullet, and step 2), `templates/assessment.md` twice, `skills/assess/references/finding-bar.md`, and `specs/architecture-principles.md`. The reference itself names "a rule stated in three places" as a theatre candidate, so the change ships an instance of the class its own lens exists to flag. Nothing in the tree is false, so it is routed to the improvement ledger as an improvement rather than filed; #547 moved two of the seven homes without reducing their number, and the next edit to that rule still has seven places to keep in step.
- **No test holds the assessment guidance recorded above.** The scope wiring, report shapes, retention field, and scope-admission rule are prose in the plugin surface. The native packaging added in this range has separate manifest, generated-artifact, installed-layout, hook-contract, and landing-page guards; none of those measures the assessment prose. That is D5 working as written, not an oversight.
- **The test lock sees three tools, not every write.** `hooks/test-lock-guard.js` matches `Write`, `Edit` and Codex's `apply_patch`; a test rewritten through `Bash` — `sed -i`, a heredoc, `git checkout -- tests/` — is not seen, and the lock is released by one edit to a gitignored file. Both are deliberate (the alternative is parsing arbitrary shell, and a refusal with no escape wedges a session), and both mean the hook raises the cost of the cheapest cheat rather than closing it. The backstops are the reviewer's explicit item per test-file diff and the declared gate; whatever a repository runs server-side is its own (ADR 0022 point 2).
- **The test lock's Codex half is unprobed.** `.codex/config.toml` registers no hooks at all, so on Codex none of the four guards runs from this repo's configuration. Its `apply_patch` handling and `turn_id` pass-through match `push-target-guard.js`'s shipped shape, and `tests/unit/test_test_lock_hook.py` exercises both over synthetic Codex payloads; what is recorded nowhere in this tree is whether Codex honours `permissionDecision: "deny"`. Stated as a limitation rather than measured.
- **Nothing states when the lock is released, and one stage plausibly needs it to be.** `tests_locked` is set `true` in the write that enters `implement`, and the only documented way back is a test that turns out wrong returning the run to `stage: "tests"`. Reconciliation happens later in the same run, so a merge conflict *inside* a test file is resolved under an armed lock: the hook refuses the `Edit`, and the escape its message names mislabels where the run actually is. No shipped guidance covers the case. T3 (#539) built the reconcile-and-land loop this would land in and did **not** resolve it, and neither #621 nor #622 did: the instruction to resolve a conflicted merge by hand moved from `skills/build/references/re-bind.md` into `skills/build/SKILL.md`'s ship step and `references/reconcile.md`, which is still precisely an edit to a test file under a lock nothing releases. Neither the run file's stage vocabulary nor `hooks/test-lock-guard.js` changed at either ticket, so the case is still reachable by the shipped landing procedure and still unowned.
- **The build workflow's length is a read, not a guard.** #538's criterion set a 70-line bound on `skills/build/SKILL.md`, which measured 68 at #547's tree; the measurement is `wc -l` and direct review, and no test asserts it — law 2's subject is code, and P2 refuses a guard over prose, so a wording or length predicate over a skill file would be the thing the spine was amended to stop (#511, #520). What *is* mechanical is the structural half: `tests/unit/test_build_lifecycle_order.py` reads the `harness:build-lifecycle` block out of the index, so a rewrite that drops it goes red. `tests/unit/test_teardown_guidance.py` once held this skill's delegation to `worktree-isolation`'s cleanup contract the same way; #615 retired it, mutation-confirmed vacuous — a fully reversed cleanup obligation kept all seven pinned tokens and both tests still passed — so that delegation now rests on review alone, the same standing the bound itself has: a reviewer's read at a named tree.
- **Workflow invocation control is asserted from a host reference, not measured here.** Three of the nine workflow skills carry `disable-model-invocation: true` — `capture`, `hydrate`, `propose` — and `build`, `review`, `routine`, `drain`, `assess` and `promote` deliberately do not, because each answers to a caller that is not a human at a prompt: `/routine` drives `/build`, `/build` drives the review stage, `routine` itself is fired by an unattended scheduled run, `/assess` drives `/drain` for the improvement ledger, and a work-pull run falls back to `/assess code`. The probe behind that split read the host's own frontmatter and skills references; nothing in this tree executes a host dispatch, so what the flag does at runtime is the host's contract, recorded here rather than tested. #537's criterion said "six"; the shipped set was seven, because `routine` had been swept into the operator-only bucket by category rather than by intent. #564 (2026-09-06) is the first correction: a scheduled run was observed refused on `Skill(routine)`, silently shipping nothing, and removing the flag returned the count to six. #565 is the second: `digest` and `assess` carried the identical contradiction — a scheduled run refused on `Skill(digest)`, and `lab-book-work-pull`'s `/assess code` fallback refused the same way — and removing both flags returned the count to four. `tests/unit/test_workflow_skill_invocability.py` now holds the composed set (`routine`, `build`, `review`, `drain`, `assess`, `promote`) against the flag, with the remaining three as its control, both read from the index. #623 is the third correction and the one with no observed refusal behind it: splitting the lifecycle at PASS gave `/promote` the landing half, so an unattended `/routine` tick could no longer finish without firing it, and the flag was removed before the outage rather than after. #627 is a rename inside that set rather than a correction at all: `drain` took `digest`'s place with its own caller — `/assess` step 5 — recorded in the module's header, and no observed refusal drove it. The flag never enforced operator presence for `digest`'s drain half either; the rule in the skill's body does, and the rename left that rule where it was.
- **The improvement ledger and the tracker behaviours leave almost no footprint in this tree.** D7's sweep, holds and board writes are tracker-side; what is in the tree is `skills/tracker/` and the two transport references beneath it, and the ledger's own contents live on one standing issue found by its `improvement-ledger` label.
- **Three exercises #547's criteria name cannot run from this environment, and each has a named owner rather than a fix.** The agent proxy in front of this container refuses every GraphQL query before GitHub sees it, and Projects v2 is GraphQL-only, so the board's Todo placement and Priority writes in `skills/tracker/references/github.md` ship carried; no Linear transport or workspace is reachable, so `references/linear.md` ships carried too; and `/assess` step 5 forbids an unattended run from draining, so the drain's three-outcome marking is reviewed by reading. `specs/harness-assumptions.md` → *Carried, with an owner* names who produces each piece of evidence and when. The recipes moved into `tracker` verbatim from the two provider skills, where they were exercised, which is why a re-exercise buys less here than the criterion assumed.
- **`create`'s postcondition now reads back the board Status as well as the issue label, and honestly reports what it cannot read (#607).** The bullet above names the recipe's own board-write limitation; #607 is the fix to the read-back that sat beside it unapplied. Filed from a 2026-09-08 ledger drain against ticket #594, spawned complete and never reaching the board, then confirmed at scale in the 2026-09-09 amendment: nine tickets (#620–#628) filed that day carried no board Status, and #607's own board move failed the identical way while this ticket was itself being built — recorded on the issue with the identifier, the URL and the unavailable operation, `item-edit` (Status), rather than claimed. `skills/tracker/references/github.md`'s `create` step 4 now runs `gh project item-list` beside the existing `gh issue view --json labels` and states two branches. Where the read succeeds, the ticket is reported placed only once the Status it returns agrees with the option step 3 set; a mismatch is left unresolved rather than read as a failure diagnosis, because `item-list`'s `status` field is separately recorded unreliable under `transition` in the same file. Where `gh project item-list` fails — the GraphQL-refused host *What is reachable when GraphQL is refused* above already documents — step 4 says which case it is in and the run reports the filing incomplete: identifier, URL, the board operation that could not run, under the rule the file already carried at line 49 for every `gh project` call. No change to `skills/tracker/SKILL.md`: its `create` contract already named explicit placement among the five things a filing owes, and its general postcondition rule already required reporting anything unverifiable as an incomplete filing — the recipe was the one place not yet applying either. The change carries no test: law 2's subject is code, and ADR 0017 D5 refuses a guard over what this prose means. The evidence is the gate plus this ticket's own build session, which exercised the refused-transport branch live — the probe pair at *Two failures that look the same from the call site* above, transport case two, this ticket's own board Status left unset rather than claimed — and could not exercise the working-transport branch from this host, the same limitation the bullet above already names for this file's board writes generally.
- **`linear.md`'s `create` recipe now reads the created issue's state back alongside its labels, closing the twin of #607's defect in the GitHub reference (#632).** The recipe's postcondition previously re-read only the labels; placement is a second write, the `issueUpdate` at *Move an issue's status*, and a silent failure there reported a created-but-unplaced ticket as filed while a Todo-scoped queue read never saw it. The read-back now queries `state { id name type }` beside `labels { nodes { id name } }`, and the filing is complete only when the labels carry exactly one `assurance:<level>` and the returned `state.id` equals the id the placement `issueUpdate` set — compared by id rather than name, because the state was resolved by `type` and a workspace may rename its columns. Where the read cannot run, the run reports the filing incomplete: identifier, URL, and the operation that could not run. #607 needed two branches because GitHub's issue and its board are separate transports, reachable independently; here both writes and the read-back share Linear's one GraphQL endpoint, so a transport that answers answers for both halves and one branch covers it. The ticket's own premise that `issueCreate` "takes ... no `stateId`" holds only of the recipe's example input, not demonstrably of `IssueCreateInput` generally, which this environment cannot reach to confirm; the shipped text says what the recipe passes rather than what the API accepts. Not executed against Linear: `harness.yaml` declares `tracker: github`, and `specs/harness-assumptions.md` → *Carried, with an owner* already records every recipe in this file as carried to the first consumer update with a reachable workspace. The evidence is a read-through against the recipe's own text and parity with the `github.md` twin; the change carries no test, since law 2's subject is code and ADR 0017 D5 refuses a guard over what this prose means.
- **`linear.md`'s state-type table listed four types and called them exhaustive, while *Placement on create* two sections earlier already told a run to resolve a fifth (#637).** The table under *Resolving states by type* introduced itself as "every Linear workspace has the same four state types" and listed `unstarted`, `started`, `completed`, `canceled`; *Placement on create* names `backlog` for a Backlog placement, which the table had no row for. The contradiction is provable from the file alone — one section instructs resolving a type the other calls nonexistent — and that internal mismatch is the whole evidential basis: Linear's actual `WorkflowState.type` enum was not checked against a live workspace, since none is reachable from this environment, the same carry `specs/harness-assumptions.md` → *Carried, with an owner* already records for this file (line 96, not `plugin-surface.md` as the filing ticket first cited — corrected at build rather than propagated). The lead-in now scopes the table to "the types the recipes in this file resolve" instead of claiming completeness, a `backlog` row was added ahead of `unstarted` to match the workflow order the rest of the table runs in, and the read-out sentence immediately after the `workflowStates` query gained the matching clause, since it restates the table's mapping and carried the same gap one paragraph later. `triage`, which the enum also carries beyond these five, is left out: no recipe in this file resolves a triage queue, and a row for it would be an unverified claim about Linear's API sitting in a table this change exists to make trustworthy. The change carries no test: law 2's subject is code, and ADR 0017 D5 refuses a guard over what this prose means; the evidence is a read-through of the recipe end to end along the path a run actually follows.
- **~~A `<<` shift inside a multi-line `$(( ... ))` still refuses.~~** Moot since #621 deleted the lexer: nothing parses a Bash command for a push any more, so no shell construct is refused by shape.
- **~~One arm of the heredoc harvest has no test that can fail for it.~~** Moot since #621 deleted `harvestSubstitutions` with the lexer. It is kept as the clearest recorded instance of a guard arm with no failing evidence: `harvestSubstitutions` recognised `$(...)` and backticks; only the first was measured. Deleting the backtick arm leaves the whole suite green while `cat <<EOF` / `` `git push --force ...` `` / `EOF`, which bash runs, turns from deny to allow. Measured at review: the mutation survived `scripts/mutate.py` against the four push-guard suites, and running both hook copies against that command confirmed the mutation was live rather than a no-op. The behaviour in this tree is correct; the missing piece is the evidence that keeps it correct, and it is carried in the improvement ledger rather than filed.
- **~~`sh <<EOF ... EOF` no longer reaches `push-target-guard.js`.~~** Moot since #621: both the lexer and the refusal it fed are deleted, `test_push_target_guard_composition.py` went with them, and #562 is closed by deletion rather than by a fix. The original entry read: It reached that guard only because the body leaked back into the command stream as commands. `git-push-guard.js` still denies every such form through `isBareShellFedExternally`, which reads the redirect operator off the command line rather than the body, and both hooks run on the same `Bash` event, so the composite verdict is unchanged; a 44-shape differential re-run at review found no shape where neither guard denies. The gap is #562 — `push-target-guard.js` never calls `isBareShellFedExternally` at all, so a bare shell fed a pipe, a here-string or a process substitution passes it. Reclassified, not fixed: the composed control has no hole, because `git-push-guard.js`'s unconditional refusal (above) already covers this class on the same `Bash` call, so a copy of the check in `pushesIn` could never fire (P2) and none was added; the dependency is pinned instead, by a comment in `pushesIn` and `tests/unit/test_push_target_guard_composition.py`, which goes red if that sibling refusal is ever narrowed or unregistered. `assurance:simple`, unassigned.
- **A cycle whose changes all ship through the fix lane raises nothing (#589).** `/build` step 1 is the only caller of `scripts/plugin-version.js`, and a fix-lane change carries no ticket and runs no command — "fix X" is the whole invocation. So a release cycle containing only fix-lane work reaches the release branch at the released version, and a consumer running `claude plugins update harness` is told it is current over bytes that changed; that failure is not hypothetical, it happened on 2026-09-05 (`a609d5b`). Recorded rather than closed, because the alternative homes all break the tree binding: a hook edits content after the gate, and a landing-time edit voids the tree the verdict binds to. One ticket built in the cycle is enough to move it, and `/routine` drives `/build`, so unattended work is covered.
- **Nothing detects a version that failed to move, and that is now a decision (#588, #589).** The surviving guards measure agreement, not movement: `tests/unit/test_spine_template_parity.py` and `tests/unit/test_native_codex_plugin.py` fail on a partial write and are silent on a raise that never happened. A gate stage asserting the integration version exceeds the release's would be #588's deleted 713-line guard again, reading the two operands the writer already read, and it would refuse correct work at the start of every cycle instead of doing the job. The control is the writer's own refusal at step 1.
- **The version comparison's patch position is unreachable in this tree and unmeasured (#589).** `compare` in `scripts/plugin-version.js` walks all three components, and no fixture in `tests/unit/test_plugin_version_script.py` differs in the third: mutating the loop bound from `i < 3` to `i < 2` leaves all 23 tests green, measured at review by a restored staged probe that re-derived tree `97d0ddeb`. Under that mutant a patch-only difference reads as equal and raises instead of reporting `already-ahead`. Nothing in the mechanism can produce such a state — `raised` always zeroes the patch and a review-time major raise writes `X.0.0` — so the slot is reachable only from a hand-written patch version. #590 resolved the open half of that sentence without changing the entry: it retired the grammar's `patch` **level** and left the version's third **component** untouched, so `compare` still walks all three, `raised` still zeroes the third, and the position is still reachable and still unmeasured.
- **The parity check does not ship, and after #594 nothing waits on whether it should (#558, #594).** `tests/unit/test_spine_template_parity.py` lives in this repo's suite, and the plugin seeds no equivalent: no hook compares the two files, no gate stage does, and `hydrate` writes none into the consumer. What changed is the cost of drift, not the shipping. A consumer that edits one file and not the other now carries a stale copy until its next hydration, which re-derives from the boundary marker however far the copy region has drifted and names the lines it overwrites; before #594 that consumer reached `blocked` and stayed there until a human re-derived the file by hand, which the spine's own contract made the ordinary case. Two bounds on that. A repo that never refreshes never heals — *The spine can go stale in a consumer* above is the entry that records it, and "one release cycle" is the wrong unit, because the healing is a plugin-update ritual and not a wall-clock interval. And a copy written before the marker existed still blocks once on drift; the re-derivation writes the marker into every copy whose prefix still holds, so an undrifted consumer migrates in silence on its next run and a drifted one migrates on the hand re-derivation its blocked row prescribes, after which the state cannot recur for that file. Whether the check should also ship remains with the operator, raised at #558's first review cycle; #594 removed the urgency, not the question.
- **One seam in the written derivation admits two readings, and the prose settles it only by inference (#594).** *The write* defines the boundary as three fixed bytes — a newline, the marker, a newline — and the next sentence inserts a single newline after it where the deltas do not already begin with one. Two fresh contexts executing that prose at this review each stopped at the same place and each asked, unprompted, whether the boundary's own trailing newline composes with that insertion, and whether "everything above the boundary marker's line" includes the boundary's leading newline. Both resolved it correctly — one from the idempotency claim in the same paragraph — and both flagged it rather than guessing. The cost of the other reading is bounded and not destructive: one blank line at the join, or an overwrite report that says a byte-perfect copy "had only fallen behind". Recorded rather than reworded, because the readings converge after one run and the repo's posture accepts an imprecise message over a review cycle spent on one.
- **One cross-reference inside the #590 amendment points the wrong way, and it is recorded rather than reworded (#590).** The provenance sentence reads "patch entered at the restatement above"; the other three directional references in the same note, and both in the notes above it, are relative to the reader's position, and read that way it points at the 2026-08-18 supersession note, which merely inherited the level. The `Patch` bullet entered at `d334232` (2026-06-13), in the restatement that sits *below* the sentence. The reading that makes it true is "above the decision just named", which the sentence supports but the section's own usage does not. The cost is bounded and not destructive — a reader who follows it lands on a note that says the same thing about patch, two months later — and the claim it serves (D3 named two levels) is independently correct, so nothing downstream of it moves. Left as the builder wrote it because repairing the candidate would cost a third review cycle on one preposition, which the repo's posture refuses (P0), on the precedent the entry above sets.

## Decisions

### Decision: Re-bind PASS only across clean, disjoint post-verdict drift

*Retired 2026-09-09 by [ADR 0022](../decisions/0022-plugin-only-shape.md), built as #621: ADR 0020 below is itself superseded and there is no machine half to the binding at all. Kept as history.* *Decided 2026-08-31. **Superseded 2026-09-05 by [ADR 0020](../decisions/0020-authored-tree-binding.md)**, built as #539: the disjoint-path precondition is gone, the proof moved from observing the merge to recomputing it with `git merge-tree --write-tree`, and a conflicted merge now ships under a scoped re-gate instead of returning to the reviewed path. What survives is the shape of the licence — git alone must have produced the bytes — and the two-attempt reconciliation bound. Kept here as the decision this repo actually made and then replaced.*

**Context.** A push can lose a race after PASS has bound a reviewed tree. Repeating the reviewer round trip adds no judgment when the new base changed only disjoint paths, but the prior gate evidence cannot certify the merged tree.

**Decision.** `/build` may inherit PASS only after a unique-base, disjoint-path check and a clean Git-authored merge with the expected parents and no resolution or edit. It then runs the complete configured gate, binds fresh marker evidence to the exact merged tree, reports the incoming range and tree identities, and retains the normal pre-push tree-equality check. Shared paths or conflicts retain delta review and a new final verdict. The shortcut saves the reviewer round trip, never the complete gate.

**Alternatives.** Always repeating delta review was rejected for clean, disjoint drift because it adds no new judgment. A selective or shortened gate was rejected because it weakens exact-tree certification. Conflict resolution, prose parsing, and inferred semantic overlap were rejected because they exceed the mechanical licence.

**Consequences.** The shortcut stays inside the existing two-attempt reconciliation bound. Any ambiguity, authored byte, failed or wrong-tree evidence, or equality mismatch returns the run to the ordinary reviewed path.

### Decision: Ship a second copy of the spine, against the ecosystem's one-source consensus

*Decided 2026-09-06 (#558). Amended 2026-09-07 by #594: the refusal of a marker under* Alternatives *is narrowed, not reversed — see* Decision: Mark where the copy ends, keep the prefix as the contract *below. The prefix relation remains the contract and the only thing asserted.*

**Context.** `research/01-instruction-files.md` records the ecosystem consensus — one source of truth in `AGENTS.md`, `CLAUDE.md` a thin `@AGENTS.md` bridge, "never maintain two copies of the same content" — and P2 refuses a second copy by name. #537 had reduced this repo's `CLAUDE.md` to that bridge. The operator judged the trade wrong: a guaranteed load of the contract every session runs on was exchanged for an instruction to resolve an import the repo does not control. The corpus file is not edited, which the ticket puts out of scope; its line is a finding about what others do, and this block is where the departure from it is answered.

**Decision.** `CLAUDE.md` carries `AGENTS.md` byte for byte as its prefix, then the host deltas. The reason the consensus holds is that a copy drifts, and the answer here is a mechanism rather than discipline: the prefix relation is asserted over both files read from the git index on every gate run, which is P1's lowest rung that can hold it. The rung reaches this repo alone, and the *Known limitations* entry above says so rather than letting the guidance imply otherwise.

**Alternatives.** A `spine:mirror` marker pair and a deltas-first ordering were considered at capture and refused: a marker is a second contract to keep true where a positional boundary needs none. Keeping the pointer was rejected by the operator on the measurement recorded above. Deriving the copy at hydration with no comparison at all was rejected as the drift the consensus warns about, with nothing standing against it.

**Consequences.** Every hydrated repo carries the spine twice, its own repo-owned tail included. A version bump moves five files rather than four, and `scripts/plugin-version.js` carries the fifth. `--refresh` is the only re-derivation, and it blocks rather than guessing wherever the boundary between the copy and the deltas is unfindable. The derivation refuses to copy a spine that still carries a fenced configuration block, because `scripts/harness-config.js` reads `CLAUDE.md` as a configuration source. This change alters what `--refresh` does to a repo-owned file without asking and adds outcomes that block a plan, so the release carrying it is a major rather than the minor floor: a consuming repo takes it as a decision rather than an auto-pull.

### Decision: Mark where the copy ends, keep the prefix as the contract

*Decided 2026-09-07 (#594).*

**Context.** The decision above refused a marker on the grounds that a positional boundary needs none. That holds while the copy is correct and fails the moment it is not: the prefix locates the boundary only by comparing the two files, so the first edit to either destroys the only thing that could delimit the deltas, `--refresh` reaches `blocked`, and it stays there until a human re-derives the file by hand. The spine tells every consumer to restate its stage line and its repo principles under *This repo*, so editing `AGENTS.md` without re-deriving is what the contract asks for, not an edge case. Measured at #558 by probe, and the question reached this repo as the wrong one: #558's first review cycle asked whether the parity check should ship downstream, and a boundary that survives drift removes what the downstream detector was for (P1 — an upstream ambiguity is not answered by a downstream detector).

**Decision.** `CLAUDE.md` carries `<!-- spine:copy:end -->` alone on a line at the end of the copied region. `--refresh` locates the deltas by that marker where a file carries exactly one, and by the prefix relation where it carries none, re-deriving in both cases, and names every line it overwrites above the boundary. The marker is additive and one-sided: it sits at `len(AGENTS.md)`, inside the remainder the guard already treats as opaque, so `tests/unit/test_spine_template_parity.py` asserts exactly what it asserted before and a marker never excuses a divergent copy.

**Alternatives.** A `begin`/`end` pair was refused: a begin marker would sit above the copied bytes and break the prefix relation outright, to locate a position already known by construction. Replacing the prefix comparison with a marker-delimited one was refused for the reason #558 gave — it makes a declaration, rather than the bytes, the thing asserted — and a sample in the parity module pins the difference by accepting a file the marker would reject. Counting a bounded file's markers against `A_old`'s own count was refused because it is arithmetic over drifted bytes, which is the fragility being removed. Leaving the blocked state in place was refused on the measurement above.

**Consequences.** Where a marker is present it is trusted, so a re-derivation can overwrite bytes a consumer authored inside the copy region. That is bounded by the report, which lists every line that leaves, and by the refresh committing nothing, so `git diff` holds the rest. A file carrying two anchored markers is not bounded and blocks, which means a spine that discusses this marker on its own line costs its repo the recovery — this repo's own copy is held to exactly one occurrence by a sweep in the parity module, and `templates/spine.md` names `CLAUDE.md` nowhere, so no consumer can be handed a counterfeit through the generated block. A copy written before the marker existed blocks once on drift and never again. The change moves a whole class of file from `blocked` to `rewritten`, which is a changed refusal reason and therefore major under the compatibility grammar; it lands in the same unpromoted cycle as the decision above, which is already major, so the cycle's one raise carries both and no consumer sees a second decision.

- [ADR 0017 — v5: the guidance ships as a plugin](../decisions/0017-harness-v5-plugin-shaped-guidance.md) — the shape of everything above, including the guard admission rule.
- [ADR 0003 — promotion lifecycle](../decisions/0003-promotion-lifecycle.md), as amended 2026-08-17 — topology is per-repo configuration; this repo's is `dev → main`.
- [ADR 0020 — the verdict binds to the authored tree](../decisions/0020-authored-tree-binding.md) — the second acceptance path, its five conditions, and its accepted risks.
- [ADR 0015 — v4: thin verification layer](../decisions/0015-harness-v4-thin-verification-layer.md) — why there is no runtime.
- One licence — everything is MIT: Decision block in [`specs/architecture-principles.md`](../architecture-principles.md).

**Deliberately absent** — a runtime (ADR 0015), a registry / per-file versions / an installer (`BOOTSTRAP.md`) / `/update-guidance` (ADR 0017 D1), a `CONTEXT.md` of this repo's own (D2; the name survives only as the last fallback source the shared reader consults for an unmigrated consumer), a `commands/` directory and the Codex generator that mirrored it (#537), and the `staging` role in this repo (D6). #547 added five: the `systematic-debugging`, `infrastructure`, `design-system` and `ux-design` skills, and `specs/retired/` with the 33 settled proposals. The retired `BOOTSTRAP.md` was a consumer installer, a different subject from this repo's own cloud session bootstrap.

### Decision: Translate the runner-flag comparison by polarity, and retire the fixed substitution

*Retired 2026-09-09 by ADR 0022, built as #621: `HARNESS_GATE_MARKER_RUNNER` no longer exists, so there is no comparison to translate and `refresh.md`'s sweep for it is fenced. Kept as history — the polarity reasoning is the general lesson.* *Decided at the design stage of #592, 2026-09-08.*

**Context.** `--refresh` carried one substitution: where the public `exec` line was guarded by a test that `HARNESS_GATE_MARKER_RUNNER` is **not** `1`, replace that test with `[ -z "${HARNESS_GATE_MARKER_RUNNER:-}" ]`. Because the replacement text was fixed, it was correct only for the inequality, so the rule carved the equality out — "the inverted spelling, where the equality test guards the *internal stages*" — as an unrecognised shape to retain and report. Both consuming repos then failed the rule, each for a different reason, and one of those failures was the silent shape recorded under *The enforcement loop* above.

**Decision.** Translate by the comparison's own polarity and never by the branch it guards: an equality against `1` becomes `[ -n "${HARNESS_GATE_MARKER_RUNNER:-}" ]`, an inequality becomes `[ -z … ]`. Both then say what the contract says — *a runner is running* — whichever way the surrounding construct is written, so the construct never needs reading and can never be inverted. Sweep every tracked file for the comparison in any spelling, and rewrite in `scripts/verify.sh` alone.

**What it retires** (P2 — an addition names what it retires). Two things, both deleted rather than kept beside it: the fixed `-z` substitution, and the "unrecognised inverted shape" carve-out, which existed only because a fixed substitution could not survive that spelling. One rule replaces two plus an exemption, and it handles both consumers' actual failures where the pair handled neither.

**Consequences.** The rewrite is no longer conditioned on the site being paired with the public `exec` line, so `--refresh` writes in a consumer's gate at sites it previously left alone. That is the point — the silent internal-guard shape is only reachable that way — and it is bounded by the plan-then-report contract: every site is reported as `rewritten` with both spellings before the operator commits anything. Three shapes stay unrewritable by construction and are reported instead, because no translation of the comparison exists for them.

### Decision: Resolve the Linear team at runtime, and retire `repo.linear` from the recipe

*Decided by the operator 2026-09-08, superseding the same day's earlier `tracker_address.team` shape before any edit was made.*

**Context.** `skills/tracker/references/linear.md` read the team key from `repo.linear`. Measured across the two consuming repos, that was already broken in both directions: one declared a workspace *hostname* there, which is not a team key, and the other did not declare the key at all. A queue read by the recipe therefore returned empty on both, which only an unattended discovery run would ever have noticed. The first remedy taken — read `tracker_address.team`, "the key both consumers already declare" — was falsified at grounding: one consumer declares no `tracker_address` block, and the key was on this record's own unread list.

**Decision.** Read no configuration field for the team. The API token is workspace-scoped, so nothing needs to say which workspace this is; query `teams { nodes { id key name } }` and use the single node. Every other identifier in that recipe — state, label, project — was already resolved at runtime, so team lookup was the one deviation and the one defect. More than one node is genuinely ambiguous: report and hold, with `tracker_address.team` as the override for that case alone, the same shape the recipe already uses for a custom or renamed workflow state.

**`repo.linear`'s retirement, and why it is recorded here.** #561's declared retired-key list is maintained by one trigger: *any shipped decision that retires a key*. This is that trigger, and #592 is the shipped decision it names, so `repo.linear` joins `loop.engine_timeout_seconds`, `loop.review_model` and `loop.unconditional_review_cycles` in the list `--refresh` reports. Nothing is deleted from a consumer: a repo keeping `repo.linear` as a documentary pointer to its workspace URL is unaffected and simply carries an ordinary unread key. This was the one item folded into #592 whose original form — report *every* unread key, classified retired or repo-owned — would have rebuilt the derivation #561 spent three review cycles refusing, and it was cut back to the one declared line at the design stage.

**Alternatives.** Reading `tracker_address.team` with a `repo.linear` fallback was rejected as two sources for one value. Reading a `tools.linear_team_id` UUID as a second accepted spelling was rejected for the same reason. Asking one consumer to add a key was rejected by the operator, who had ruled out consumer edits for this item.

### Decision: The design rule and its Codex twin join the created-where-absent set

*Decided by the operator 2026-09-08, narrowed from the audit's original form.*

**Context.** The design rule was init-only: a repo declaring `layers.design_system: true` and hydrated before the rule existed received it never, and one consumer was measured in exactly that state — the layer on, no `.claude/rules/design-system.md`, no `design/AGENTS.md`. The audit also asked `--refresh` to report a *diverged* twin, on a premise a 2026-09-07 grounding falsified: the other consumer's two files differ deliberately. The operator's own re-grounding overturned that finding — #547 redefined `design/AGENTS.md` as the byte-identical Codex twin below the first `##`, so the difference is staleness against the current template rather than a correct arrangement, and byte-equality of the shared region is a mechanical check rather than a judgment.

**Decision.** Seeding joins the **written only where absent** set, never the regenerated one: where both files are absent, write both from the template; where one exists, write the missing one from the **present** one, so a twin is never born diverged from a sibling the repo has since edited; where both exist, write nothing and report a shared-region divergence as `blocked` with the offset of the first difference. `paths.design_system` fills the first `paths:` glob; the second, `<ui-source-glob>/**`, is carried through as the placeholder it is and reported by name, because this plan runs no interview and a guessed glob loads the rule where it does not belong or nowhere at all.

**Consequences.** This is the second reach into a repo-owned region after the configuration move, and it is narrower than that one: it creates a file that is absent and never touches one that exists, so no repo-owned bytes are at risk. The `blocked` row is new behaviour for a repo whose twin has drifted — a refresh that used to complete now waits on an operator answer — which is a cost paid to make a stale twin visible at all.

### Decision: Rewrite a positively-identified managed helper in place, wherever the consumer keeps it

*Retired 2026-09-09 by ADR 0022 point 1, built as #621: the plugin owns no executable inside a consumer, so there is no managed helper to locate or rewrite. Kept as history.* *Decided at the design stage of #592, 2026-09-08. Reviewed and affirmed at the certifying review, with the cost below named rather than narrowed.*

**Context.** One consumer vendors the managed trio under `scripts/gate/`, not flat under `scripts/`, and pins the three files by SHA-256 in a test of its own. `--refresh` managed only the flat paths, so that repo ran 7.0.0 helpers under an 8.0.0 plugin — the runner still exporting the retired literal `1`, the reader lacking the queue defaults — and nothing in the plan could see it. The obvious fix, parsing the helper's path out of `commands.verify`, cannot work there at all: that repo declares `npm run verify`, two hops from the invocation.

**Decision.** Locate the pair by **positive content identification** — each file's own opening bytes identify it as the plugin's — and rewrite a differing one in place at wherever the sweep found it, after reporting any tracked file that pins its current hash and never editing that file. A retired banner spelling joins the identification list rather than replacing the current one, because a rule keyed only on the current spelling stops firing for every repo materialised under the old one.

**Why a Decision and not an ADR.** `refresh.md`'s invariant paragraph says *nothing derives a destination from what a consumer's file says*, and that clause is **not** breached: a location found by reading the plugin's own bytes is not a location a consumer's shim, manifest or configuration claimed, and the step says so where it makes the identification. What the change does strain is the neighbouring clause in the same paragraph, *every path written is a fixed literal relative to the workspace root*, which no longer holds, and the enumeration of gate paths above it, which still lists only the flat ones. Measured at the certifying review by a fresh context executing the whole document against the relocated-pair case: it wrote the located pair without hesitation and never read the invariant as a bar, so the imprecision is inert in execution. Recorded rather than reworded, on this repo's stated acceptance of an imprecise message over a review cycle spent on one.

**The cost, named.** The precondition genuinely widened. On the flat path `--refresh` materializes the current helper only over one **byte-identical to a released Harness helper** — a test that leaves a locally modified helper alone as consumer-owned. On the located path it rewrites on **any** byte difference, so a consumer that has patched a vendored helper while leaving its banner intact loses that patch. Three things bound it. The write is working-tree only and reported as `rewritten` before the operator commits, so it is one `git checkout` from undone. No such patch exists in the fleet today: measured at this review against the plugin caches under `~/.claude/plugins/cache/harness/harness/`, the relocated pair hashes byte-identical to the released 7.0.0 helpers and the flat consumer's `gate-marker.js` to the released 8.0.0 one, so both vendor released bytes exactly and neither carries a local edit. And the pinned-hash sweep means a repo asserting its helper's bytes is told what changed rather than discovering it at its next gate. The narrower rule was available and not taken — requiring byte-identity to *some* released helper on the located path, as the flat path already does. The same measurement shows it would have admitted the one real case this ticket exists for, so the widening bought nothing that was needed; this entry is what it was traded for, and narrowing it later costs one clause.

**One case the rule states in only one direction.** A manifest beside the located pair declaring `"type": "commonjs"` is reported compatible and current. The rule does not say what to do with an incompatible one, where the flat path's safety test would have refused — a gap left standing because the flat test is skipped once the pair is located, and because the one measured relocated manifest declares CommonJS.

### Decision: The Codex adapters are plugin-owned per file, identified by their marker

*Decided at the design stage of #601, 2026-09-08. Recorded at the certifying review.*

**Context.** `refresh.md` placed "the Codex-adapter set" in the **Regenerated** — plugin-owned — set, while `SKILL.md`'s step 8 called the same files "repo-owned host adapters". Under the second reading `refresh.md`'s claim that the configuration move is *the plan's one reach into a repo-owned region* is false, because every refresh also rewrites marked adapters. Both sentences were load-bearing, so one had to change, and an executor meeting the two had no way to choose.

**Decision.** A file in `.codex/agents/` whose first line carries one of the plugin's markers is plugin-owned content vendored into the repo, and `--refresh` rewrites it to the plugin's current bytes. Any other file there is the consumer's and is retained. The directory is repo-owned; ownership of each file is decided by positive identification, never by location. `SKILL.md`'s "repo-owned host adapters" is the sentence that changed.

**Alternative rejected.** *Repo-owned once hydrated, like `.claude/rules/`* — `--refresh` would create an absent adapter and never rewrite one. The adapter body mirrors `agents/<role>.md`, which changes every release, so every hydrated repo's Codex dispatch would freeze at hydration-time content with no signal that it had, and `tests/unit/test_codex_agent_adapters.py` holds the two copies of each role's body in a correspondence no repo-owned file can be held to across a plugin update.

**Consequences.** `refresh.md`'s "one reach into a repo-owned region" becomes true as written and needed no edit. The cost is that a consumer who edits a marked adapter loses those edits at the next refresh, reported but not preserved; the escape hatch is to delete the plugin's marker line, which converts the file into a collision the plan retains, and the shipped text says so in the same sentence rather than leaving it folklore.

### Decision: The gate-ignore markers are never written into a consumer's `.gitignore`

*Decided at the design stage of #601, 2026-09-08. Recorded at the certifying review.*

**Context.** `SKILL.md` presents the four gate-ignore patterns inside `<!-- harness:gate-ignore:begin -->` / `:end` and instructed a run to wrap the lines it appends in that block's begin/end comments. `#` is `.gitignore`'s comment character, so those two lines written literally are patterns rather than comments, and this repo's own `.gitignore` shows the intended form was `#`-translated instead — a third live reading. Meanwhile the merge rule already decided membership by each pattern's own presence, never the block's presence as a unit, so idempotence rested on the per-pattern test and on no marker.

**Decision.** A run appends the absent patterns and nothing else, and never writes a `harness:gate-ignore` marker into `.gitignore` in either spelling. The begin/end comments delimit the block inside `SKILL.md` — which is what *machine-identifiable* names, and what `tests/unit/test_init_gate_ignores.py` reads — and are a source-document delimiter rather than an artefact.

**Alternatives rejected.** *Write them, `#`-translated* — no reader consumes a marker in a consumer's `.gitignore`; a wrapped subset invites exactly the block-as-a-unit membership test the merge rule exists to refuse, since a partial run wraps two of the four patterns while the others stand elsewhere; and it needs a second rule nothing else needs, for where a later run's new pattern goes. Bytes with no reader, whose meaning decays at the next run, are inventory (P2). *Write them as the HTML spelling stands* — two junk ignore patterns in every hydrated repo, permanently.

**Consequences.** `.gitignore` takes one of three rows — `absent | written`, `present, gaining <n> patterns | rewritten`, `present, every pattern already ignored | retained` — and no marker state. The per-pattern test is now the only thing that has to be true for idempotence, which it already was. `tests/unit/test_init_gate_ignores.py` and this repo's own already-marked `.gitignore` block are untouched: the decision governs what a run writes into a consumer, not what either file contains, and the guard's two enumerations still have to match.

### Decision: The plan is a report, and no run waits for a turn

*Decided at the design stage of #601, 2026-09-08. Recorded at the certifying review.*

**Context.** Step 1 stopped "until they have said which block is the configuration", the closing paragraph offered to write the provenance key, and every `blocked` row waits on an operator — but nothing said whether a caller with no operator turn presents the plan, waits for an answer, or writes on silence. The `CLAUDE.md` derivation's *Expand without asking* was the one place the reasoning had already been done.

**Decision.** Reporting the plan is the run's last act. Nothing in a run waits for a turn and no caller is asked a question: a question the plan cannot answer is a `blocked` row carrying what is needed, an offer is a `retained` row carrying the exact bytes and the acceptance that would trigger the write, and silence is a decline rather than a consent, costing nothing because the next run offers again. What licenses acting without asking is positive identification — the bytes at risk are the plugin's by declaration or content, and the target shape is settled; repo-authored bytes at risk, or two plausible readings, license an offer or a block instead. That discriminator is what six of #601's seven cases fall out of, rather than each being legislated separately.

**Alternatives rejected.** *Write the provenance key unasked, generalising the pointer expansion* — `.claude/settings.json` carries the host's enablement and permissions, and a repo that deliberately removed the marketplace key would have it re-added on every refresh with no way to win. First-time setup writes it because hydration is the operator's own act; a refresh is not, and the asymmetry is deliberate. *Have a non-interactive caller wait, or refuse to start* — it converts a complete report into no report, the outcome an operator can act on least.

**Consequences.** Every state a run can reach ends in a row an operator reads later, so a scheduled or headless invocation is as useful as an attended one, minus the acceptances. Step 1's "stop before any write, not before the rest of the plan" became an instance of the general rule rather than a local carve-out, and the `blocked` action's definition moved from "before the plan is complete", which read as though the run halts, to "before this path changes".

## Cross-references

- `specs/harness-assumptions.md` — one row per hook, script, skill and agent: what it assumes the model cannot do, and the test that would retire it. Read at every model or host release.
- `specs/infrastructure.md` — the operational record this feature's topology section summarises.
- The `guidance-system` record — the registry-era predecessor, retired 2026-08-18 and removed from the tree with `specs/retired/` at #547. In git history.
