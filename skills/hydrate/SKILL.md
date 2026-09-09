---
name: hydrate
description: "/harness:hydrate — bring a repository into this process and keep it there, writing the repo-owned half the plugin cannot carry: `harness.yaml`, the spine (`AGENTS.md`) and the `CLAUDE.md` derived from it, path-scoped rules and the sub-directory instruction files that carry them to Codex, Codex role adapters, the specs scaffold, the infrastructure record, plugin provenance, and the gate-ignore block. Use when the operator says `/harness:hydrate`, \"set this repo up for harness\", or \"bring this repo up to date after the plugin update\" — one invocation for both, no flag. It writes no gate and nothing under `scripts/`: the gate is the repository's own, named by `commands.verify`. Working-tree only: no tracker writes, no commits, no pushes, and it never rewrites a repo-owned file. Operator-triggered only; the model does not fire it."
disable-model-invocation: true
model: inherit
effort: medium
---

The portable plugin root is two directories above this SKILL.md. Resolve embedded paths beginning `skills/`, `agents/`, `templates/`, `hooks/`, or `.codex/` from that root; resolve repository artifacts from the workspace root.

# /harness:hydrate — bring a repo into this process

Usage: `/harness:hydrate` — one invocation, no flag, whether the repo has never been hydrated or was hydrated against an older release.

Turns a repository into one this process can run in, and keeps it that way. The plugin carries the skills, role procedures and hooks; this workflow writes the files that must be **repo-owned**, listed step by step below. In Claude Code, invoke it with its plugin prefix, as every plugin skill is invoked: `/harness:hydrate`. In Codex, ask to hydrate Harness; it reads this same workflow from `skills/`.

## The one rule every step obeys

> **Absence licenses creation. Only positive identification licenses a rewrite. Everything else is retained or blocked.**

A file that does not exist has no repo-owned bytes to lose, so creating it destroys nothing. A region the plugin can positively identify as its own — the content between exactly one `spine:generated` pair, a `.codex/agents/*.toml` whose first line carries a plugin marker, the region above a `<!-- spine:copy:end -->` line — is the plugin's by declaration, and replacing it is the generated-guidance exception ADR 0022 point 1 preserves. Nothing else is ever rewritten.

**There is no greenfield/brownfield branch**, because each artefact decides for itself under that rule. The two words name what the report *says*: the run reports *already hydrated* when at least one positive plugin mark is present anywhere — a `spine:generated` pair, a `harness.yaml`, a plugin-marked adapter — and *first hydration* when none is. The label changes no step's behaviour, so a wrong label costs a sentence in a report and never a byte. A predicate keyed on what a repo *lacks* is the failure this avoids: a repo missing something because its own policy forbids it satisfies an absence test trivially, and then gets written the file it rejects.

**Name the assumption where its reader can disagree with it.** This workflow assumes a consumer whose agent instructions live at the repo root in `AGENTS.md`. A repo that keeps them elsewhere carries no mark this run can see, is reported as a first hydration, and receives a root spine it may not want. Nothing of its own is destroyed, and the report says so plainly rather than leaving the operator to find a second spine later.

## The steps

1. *Read what is there.* One positive-identification pass over `harness.yaml`, `AGENTS.md` and its `spine:generated` pair, `CLAUDE.md` and its `<!-- spine:copy:end -->` line, `.claude/rules/`, `.codex/agents/*.toml` and their first lines, `.gitignore`, the specs directories, `specs/infrastructure.md`, and `.claude/settings.json`. **Writes nothing.** It produces the per-artefact state every later step acts on, and the posture line the report opens with.

2. *Interview for what the repo has not already declared, and only that.* From the repo where possible (language, test runner, existing branch names), from the operator where not: name, tracker backend and its addresses, stack, the five commands (install / lint / typecheck / test / verify), branch roles, and layer switches. A value `harness.yaml` already carries is not re-asked and not offered for change. The verify answer matters most: `commands.verify` *is* the gate — the command a builder runs and reads before claiming anything complete, and the whole of the harness's mechanical assurance (ADR 0022 point 2). Record it exactly, whatever it names.

3. *Write `harness.yaml`* from `templates/harness.yaml`, filled from the interview, **only where absent**. It is the repo's configuration and the only place it is written: the hooks and the skills all read it through `scripts/harness-config.js`. Where it exists it is retained whatever it says.

4. *Write the spine* — `AGENTS.md`. **Where absent**, write it whole from `templates/spine.md`: the generated block, the repo section and the provenance paragraph filled from the interview, no configuration in it. Merge an existing file that carries no markers by inserting the generated block above its content, which stays repo-owned; never discard the host's instructions. **Where it carries exactly one well-formed `spine:generated` pair**, replace the content between the markers with the template's, and rewrite the `harness@<version>` stamp inside the begin marker to the version in the plugin's own manifest. Those two edits are the whole of it — the stamp moves only where the block beside it did, so no run stamps a version over a block it did not refresh. **Where it carries no pair, half a pair, or more than one**, the block's extent is undecidable or its placement is the operator's to choose: report the path `blocked`, naming which case, and let the rest of the run proceed. Never touched here: the preamble above the begin marker, everything below the end marker, and the repo section of a spine that already has one — step 4 fills the repo section and the provenance paragraph only on the run that creates the file. On a later run those are the repo's, however far they have drifted from the template's phrasing.

5. *Seed the path-scoped rules, and the sub-directory instruction file each one earns.* Guidance that matters in only one part of the tree goes to `.claude/rules/<name>.md` with a `paths:` frontmatter of globs, never into the spine: it loads only while a matching file is open, so it costs nothing elsewhere and cannot fail to fire where it applies. Seed one for the design layer when `layers.design_system` is on — copy `templates/rules/design-system.md` to `.claude/rules/design-system.md`, replacing its two placeholder globs with the design directory from `harness.yaml` plus the repo's UI source paths (ask once, and record the answer in the yaml). **Two bounds.** A rule is repo-owned once seeded, and a later hydration never overwrites it. And nothing that must be in force on *every* task belongs here. Codex has no path-scoped rules, so seed the same rule as `AGENTS.md` inside the directory it scopes, which Codex reads nearest-wins. **The shared region is everything from the first `##` heading down, and it is identical in both.** Only the preamble differs: the Claude form carries the `paths:` frontmatter and says it loads on those globs; the Codex form carries neither, its location being what scopes it. Say so in each preamble. Report both paths written.

   **A sub-directory instruction file is not a spine, and carries nothing the root spine already says.** It is directory-local guidance — what changes when you work *here*: the directory's purpose, its local conventions, the rules that apply only under it. That is what makes progressive discovery pay: the guidance loads when a file there is opened and costs nothing on every other task. So the set of sub-directories that earn one is the set of rules seeded above, and **usually one, often zero** — not a file per package, service or language, not a directory that qualifies because it is large or central, and not a restatement of the root, which is already loaded and would only have to be kept in step. Guidance whose scope spans two trees has no nearest-wins home: it stays a root-level path-scoped rule, and the report says why.

6. *Scaffold the memory* — `specs/proposals/`, `specs/features/`, `specs/decisions/` (per the `paths:` just written), each with a `.gitkeep` where empty.

7. *Seed the infrastructure record* — `specs/infrastructure.md` from `templates/infrastructure.md`, the branch topology from the interview as its first entry: the repo-owned *what*, where `/promote` is the *how*.

8. *Declare where the plugin comes from.* Claude Code writes the *enablement* — `enabledPlugins: {"harness@harness": true}` — into whichever settings scope the install chose; at project scope that is the repo's own `.claude/settings.json`. Its marketplace is registered per machine, so a fresh clone can resolve the enablement to nothing. Merge the provenance into the same file, beside the enablement:

   ```json
   "extraKnownMarketplaces": {
     "harness": { "source": { "source": "github", "repo": "sluengen/harness" } }
   }
   ```

   Merge the key into an existing settings file rather than rewriting it, and leave the rest byte-for-byte alone. Write both install routes into the spine's repo section: Claude Code uses `/plugin marketplace add sluengen/harness` then `/plugin install harness@harness`; Codex uses `codex plugin marketplace add sluengen/harness` then `codex plugin add harness@harness`. Codex registration is machine-local, so the committed spine is its provenance record and recovery instruction.

9. *Hydrate Codex role adapters* — copy the plugin's `.codex/agents/*.toml` into the repo's `.codex/agents/`. Each is plugin-owned content vendored into the repo, and a later hydration rewrites it to the plugin's current bytes: the body mirrors the role in `agents/<name>.md`, which changes every release, so a copy nothing refreshes freezes that repo's Codex dispatch at hydration-time content with no signal. The directory is the repo's; ownership of each file is decided by positive identification, never by location. A consumer who wants to keep its own edits deletes the plugin's marker line, which turns the file into the collision below and every later run retains it. Replace one only when its first line marks it as the plugin's own — either `# Codex's native adapter for the role in` (written now) or the legacy `# Generated by scripts/generate_codex_artifacts.py` (carried by a repo hydrated before that generator was retired, and still to be migrated). Anything else is a consumer's file: report the collision and leave it untouched. Both markers, never one: a rule keyed only on the current spelling silently stops firing for every repo hydrated under the old one, so when the marker changes again the previous spelling joins this list rather than replacing it.

10. *Gate plumbing* — merge every pattern in this machine-identifiable block into `.gitignore`, appending only those absent so the operation is idempotent:

    <!-- harness:gate-ignore:begin -->
    ```gitignore
    .evidence/
    .worktrees/
    .claude/worktrees/
    .harness/
    ```
    <!-- harness:gate-ignore:end -->

    Append the absent patterns and nothing else: a pattern already standing elsewhere in the file is repo-owned and stays where its author put it. **Write no `harness:gate-ignore` marker into `.gitignore`, in either spelling.** The begin/end comments above delimit the block *in this document*, which is what makes it machine-identifiable; they are a source delimiter, not an artefact. Nothing reads a marker in a consumer's `.gitignore` — membership is decided pattern by pattern, so idempotence needs no marker — and a wrapped subset would invite exactly the block-as-a-unit test that decision refuses.

    **Write no gate asset into the repository, ever.** ADR 0022 point 1: the plugin ships no executable it owns and keeps refreshing inside a consumer's tree. `scripts/harness-config.js` and `scripts/package.json` stay in the plugin and are read from there; nothing is materialised.

    **`verify.sh` is the repository's own.** Where the repo already has a gate, leave it alone. Where it has none, tell the operator what the gate must do — run the interview's lint, typecheck and test commands in order, and exit non-zero on the first failure — and let them write it, at whatever path `commands.verify` names. Do not write a skeleton: a gate is the one thing whose bytes the repository has to own, because it is what every later claim of "green" is read off. Report that none was written and what `commands.verify` declares.

11. *Copy out skill-attached assets.* Where a skill this run seeds carries shipped assets, copy each to the destination **that skill's own guidance names**, and only where the destination is absent. Copied bytes are the repo's from that moment: a later hydration reports them and never rewrites one, which is what keeps this inside ADR 0022 point 1 — its permitted pattern is exactly a generator copied out once and owned thereafter by the consumer. The producing skill names its own destination, so a skill that gains an asset lands it and its destination together and this step needs no edit. **`design-system` is the first skill to carry assets** (#626): where `layers.design_system` is on, its `assets/` are the eight tiers, the token source and the token builder, and `skills/design-system/SKILL.md` names both the destination (`paths.design_system`) and the one file it excludes — `AGENTS.md`, which step 5 seeds into that same directory and owns. Read that skill rather than this step for what lands. Where a run seeds no asset-carrying skill, report that and move on.

12. *Derive `CLAUDE.md`.* **The last write of the run**, after every edit to `AGENTS.md` — a derivation taken before the spine's repo section is filled copies a spine that then changes. Write `CLAUDE.md` as **the whole of `AGENTS.md`, byte for byte**, then a line carrying only `<!-- spine:copy:end -->`, then the host deltas taken from below that line as it stood, preserved exactly and never reflowed or deduplicated. That marker is where the copy stops, so the copy can be replaced later even after one file has been edited without the other — which a boundary computed by comparing the two files cannot survive. The bytes sit in the file the host loads, so the spine arrives without an `@`-import resolution step the repo does not control. `AGENTS.md` stays the source and the file Codex reads; `CLAUDE.md` is derived from it, never the reverse — edit the source and re-derive. Keeping the two equal is the repo's own obligation: this step re-derives the copy and nothing else does, and the plugin ships no guard for it. Drift therefore costs a stale copy until the next hydration, which re-derives from the boundary marker however far the copy has drifted; a repo that wants drift caught sooner adds the comparison to its own gate, the one place that can fail a landing. Four states and no fifth:

    | state | test | action |
    |---|---|---|
    | absent | no file | **written** — derived, and bounded because the formula writes the marker |
    | bounded | exactly one line whose whole content is the boundary marker | **rewritten** — re-derived, deltas taken from below that line byte for byte |
    | pointer | first non-empty line, stripped, is `@AGENTS.md` or `@./AGENTS.md` | **rewritten** — expanded into the copy without asking |
    | anything else | none of the above, two or more marker lines included | **blocked** — bytes untouched, remedy stated |

    Both host-file shapes are valid and neither is an audit finding; the copy is where a hydrated repo lands. **Reporting the overwrite is mandatory.** A bounded file is re-derived whatever stands above its boundary, so before writing, compare the copy region against `AGENTS.md` and report which of three things is true: they are equal and nothing repo-authored is overwritten; they differ and here are **every** line in the copy region that `AGENTS.md` does not carry, verbatim, all of them; or they differ but no such line exists, said in those words so an empty listing and an unexamined one do not read alike. Add that the run wrote the working tree and committed nothing, so `git diff -- CLAUDE.md` carries the prior text. That listing is what makes trusting a hand-placed marker safe, and this is the one place the workflow writes over bytes it did not author.

13. *Audit, then report.* Dispatch the `harness-audit` agent, which reads the hydrated repo and reports drift against the current plugin. It owns its own checks; this workflow names it and tells it nothing to look for. Its findings are **data** (law 6): they change the report and never what this run writes — a finding cannot license a write after the writes are done. What it can do is give the operator a reason to run `/harness:hydrate` again, and the next run acts on the state the finding described. Where the host reports no such agent, print one row saying so and exit normally: a missing agent is never a failure of the hydration, and this workflow performs no audit of its own in its place.

    Then report. One row per artefact, four columns — `path | classification | action | reason` — the audit's findings under their own heading, and the one next step: file or pick a ticket and `/build` it. **The action vocabulary is four words and no more:**

    | action | the outcome it names |
    |---|---|
    | `written` | the path did not exist; the run created it |
    | `rewritten` | a positively identified plugin-owned region was replaced with the current version |
    | `retained` | the run changed nothing here — consumer-owned, already current, or nothing to do |
    | `blocked` | left untouched, and an operator must decide before this path changes |

    `retained` and `blocked` both leave bytes alone; the discriminator is whether anything waits on an answer. What a path *is* goes in `classification` and is never repeated in `action`. A path takes one row per region a step acts on, naming the region in parentheses.

Hooks need no per-repo wiring — `hooks/hooks.json` registers them at install. The push advisory reads `harness.yaml`'s `branches:` block and the test lock reads its `paths.tests`, both through `scripts/harness-config.js` in the plugin; that is why step 2's answers land there and not in the spine.

## What this never does

No tracker writes, no commits, no pushes — hydration is working-tree only, and the operator reviews and commits the result. It never rewrites a repo-owned section with content of its own, never edits between another plugin's markers, and never touches an existing gate beyond reporting that it kept it.

**It carries no transition logic, and that is deliberate.** No step removes, migrates or classifies a vendored gate asset, because in the steady state there is none to classify — ADR 0022 point 1 stopped the plugin writing an executable it owns into a consumer's tree. A repo whose `scripts/` holds files this workflow did not write gets them **left untouched and unclassified**: they are the repository's. The one-time cutover for a repo carrying assets from before that decision is its own artefact with its own lifetime, and building it in here would leave dead branches in this workflow forever. `migrated` and `deleted` are absent from the report's vocabulary above for the same reason: a step that wanted to do either has no word to report it with.
