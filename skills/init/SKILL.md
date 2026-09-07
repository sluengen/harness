---
name: init
description: "/harness:init — hydrate a repository so this process can run in it, writing the repo-owned half the plugin cannot carry: `harness.yaml`, the spine (`AGENTS.md`) and its `CLAUDE.md` pointer, path-scoped rules, Codex role adapters, the specs scaffold, the infrastructure record, plugin provenance, and the gate wiring with its ignore block. Use when the operator says `/harness:init`, \"set this repo up for harness\", or — after a plugin update — `/harness:init --refresh` to re-generate what the plugin owns. Working-tree only: no tracker writes, no commits, no pushes, and it never overwrites a repo-owned file or an existing gate. Operator-triggered only; the model does not fire it."
disable-model-invocation: true
model: inherit
effort: medium
---

The portable plugin root is two directories above this SKILL.md. Resolve embedded paths beginning `skills/`, `agents/`, `templates/`, `hooks/`, or `.codex/` from that root; resolve repository artifacts from the workspace root.

# /harness:init — hydrate a repo

Usage: `/harness:init` (first-time setup) · `/harness:init --refresh` (after a plugin update)

Turns a repository into one this process can run in. The plugin carries the skills, role procedures and hooks; this workflow writes the files that must be **repo-owned**, listed step by step below. In Claude Code, always invoke it with its plugin prefix, because bare `/init` is the host's own command. In Codex, ask to initialize Harness; it reads this same workflow from `skills/`.

## First-time setup

1. *Interview for the repo values.* From the repo where possible (language, test runner, existing branch names), from the operator where not: name, tracker backend and its addresses, stack, the five commands (install / lint / typecheck / test / verify), branch roles, and layer switches. The verify answer matters most: `node scripts/gate-marker.js run` resolves what it launches out of `harness.yaml`'s `commands.verify`, so that answer *is* the gate. Record it exactly, whatever it names.
2. *Write `harness.yaml`* from `templates/harness.yaml`, filled from the interview. It is the repo's configuration and the only place it is written: the hooks, the marker helper and the skills all read it through `scripts/harness-config.js`.
3. *Write the spine* — `AGENTS.md` from `templates/spine.md`: the generated block, the repo section filled from the interview, no configuration in it. Merge an existing file by inserting the generated block above its content, which stays repo-owned; never discard the host's instructions. Then write `CLAUDE.md` as `@AGENTS.md` plus any Claude-specific deltas — a pointer of a few lines, not a second copy, so the hosts cannot drift apart.
4. *Seed the path-scoped rules.* Guidance that matters in only one part of the tree goes to `.claude/rules/<name>.md` with a `paths:` frontmatter of globs, never into the spine: it loads only while a matching file is open, so it costs nothing elsewhere and cannot fail to fire where it applies. Seed one for the design layer when `layers.design_system` is on — copy `templates/rules/design-system.md` to `.claude/rules/design-system.md`, replacing its two placeholder globs with the design directory from `harness.yaml` plus the repo's UI source paths (ask once, and record the answer in the yaml). **Two bounds.** A rule is repo-owned once seeded: `--refresh` never overwrites it. And nothing that must be in force on *every* task belongs here. Codex has no path-scoped rules, so seed the same rule as `AGENTS.md` inside the design directory, which Codex reads nearest-wins. **The shared region is everything from the first `##` heading down, and it is identical in both.** Only the preamble differs: the Claude form carries the `paths:` frontmatter and says it loads on those globs; the Codex form carries neither, its location being what scopes it. Say so in each preamble. Report both paths written.
5. *Scaffold the memory* — `specs/proposals/`, `specs/features/`, `specs/decisions/` (per the `paths:` just written), each with a `.gitkeep` where empty.
6. *Seed the infrastructure record* — `specs/infrastructure.md` from `templates/infrastructure.md`, the branch topology from the interview as its first entry: the repo-owned *what*, where `/promote` is the *how*.
7. *Declare where the plugin comes from.* Claude Code writes the *enablement* — `enabledPlugins: {"harness@harness": true}` — into whichever settings scope the install chose; at project scope that is the repo's own `.claude/settings.json`. Its marketplace is registered per machine, so a fresh clone can resolve the enablement to nothing. Merge the provenance into the same file, beside the enablement:

   ```json
   "extraKnownMarketplaces": {
     "harness": { "source": { "source": "github", "repo": "sluengen/harness" } }
   }
   ```

   Merge the key into an existing settings file rather than rewriting it, and leave the rest byte-for-byte alone. Write both install routes into the spine's repo section: Claude Code uses `/plugin marketplace add sluengen/harness` then `/plugin install harness@harness`; Codex uses `codex plugin marketplace add sluengen/harness` then `codex plugin add harness@harness`. Codex registration is machine-local, so the committed spine is its provenance record and recovery instruction.

8. *Hydrate Codex role adapters* — copy the plugin's `.codex/agents/*.toml` into the repo's `.codex/agents/`. They are repo-owned host adapters for named-agent workflows, each mirroring the role in `agents/<name>.md`. Replace one only when its first line marks it as the plugin's own — either `# Codex's native adapter for the role in` (written now) or the legacy `# Generated by scripts/generate_codex_artifacts.py` (carried by a repo hydrated before that generator was retired, and still to be migrated). Anything else is a consumer's file: report the collision and leave it untouched. Both markers, never one: a rule keyed only on the current spelling silently stops firing for every repo hydrated under the old one, so when the marker changes again the previous spelling joins this list rather than replacing it.
9. *Gate plumbing* — merge every pattern in this machine-identifiable block into `.gitignore`, appending only those absent so the operation is idempotent:

   <!-- harness:gate-ignore:begin -->
   ```gitignore
   .evidence/
   .worktrees/
   .claude/worktrees/
   .harness/
   ```
   <!-- harness:gate-ignore:end -->

   Make a **plan before any write**. Gate assets are managed only at `scripts/gate-marker.js`, `scripts/harness-config.js`, `scripts/package.json`, and a newly created `scripts/verify.sh`; do not place them elsewhere. The first two are a **pair** — the marker helper resolves the declared gate command through the reader beside it — so copy both or neither.

   *The safety test* (shared with `--refresh`): flat placement is safe only when every immediate module-bearing source (`*.js`, `*.mjs`, `*.cjs`, `*.ts`, `*.mts`, `*.cts`) is the recognised managed helper and `scripts/package.json` is absent or declares CommonJS. The absence of `*.js` does not establish consent.

   *The asset rules* (likewise shared): copy each helper only when it is absent; retain and report an existing non-Harness helper as consumer-owned, and retaining either retains both. Write the plugin's `scripts/package.json` only when that file is absent, otherwise retain the compatible manifest. Any other module source or incompatible manifest retains every gate asset and reports each blocking path for an operator decision.

   In the safe case, write the `scripts/verify.sh` skeleton **only when step 1's verify answer names it** — the runner launches whatever `commands.verify` declares, so a skeleton the spine does not name is a file nothing executes. Its public path is `exec node scripts/gate-marker.js run`, taken when `HARNESS_GATE_MARKER_RUNNER` is **empty**; its internal path — that variable set to anything — runs `node scripts/gate-marker.js preflight`, then the interview's lint/typecheck/test commands in order. Test the variable for emptiness and never against a value: the runner sets it to the identity of the repository it is gating (#559, ADR 0018), a shape private to the runner that has already changed once, and a skeleton comparing against a literal breaks the next time it does. Where the answer names anything else, write no skeleton: report that none was written, and tell the operator the nested-worktree preflight belongs at the head of *that* command. The runner emits evidence only after the command it resolved exits successfully; never add a direct marker-write command. A repo with its own gate keeps its commands until `--refresh` classifies its wiring as managed.
10. *Report* what was written, what was skipped because it existed, and the one next step: file or pick a ticket and `/build` it.

Hooks need no per-repo wiring — `hooks/hooks.json` registers them at install. The push and stop guards read `harness.yaml`'s `branches:` block through `scripts/harness-config.js`; that is why step 1's answers land there and not in the spine.

## `--refresh` — after a plugin update

`/harness:init --refresh` re-seeds an already-hydrated repo after the plugin
changes: it refreshes what the plugin owns, leaves what the repo owns, and
reports every file it retained and why. Load
[`references/refresh.md`](references/refresh.md) when running it — the
classification of each managed asset, the retained-versus-rewritten rule, and
the migration paths are there, and none of it applies to a first-time run.

## What this never does

No tracker writes, no commits, no pushes — hydration is working-tree only, and the operator reviews and commits the result. It never overwrites a repo-owned section, never edits between another plugin's markers, and never touches an existing gate beyond reporting that it kept it.
