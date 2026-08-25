# /harness:init — hydrate a repo

Usage: `/harness:init` (first-time setup) · `/harness:init --refresh` (after a plugin update)

Turns a repository into one this process can run in. The plugin carries the skills, commands, agents, and hooks; this command writes the handful of files that must be **repo-owned**: the spine, the specs scaffold, the infrastructure record, and the gate's ignore rule. Always invoked with its plugin prefix — bare `/init` is the host's own command.

## First-time setup

1. **Interview for the repo values.** From the repo itself where possible (language, test runner, existing branch names), from the operator where not: name, tracker backend and its addresses, stack, the five commands (install / lint / typecheck / test / verify), branch roles, and layer switches. The verify command is the one that matters most — it is the single command that decides green, and the hooks enforce against its marker.
2. **Write the spine** — `CLAUDE.md` from `templates/spine.md`: the generated block verbatim, the repo section filled from the interview. If a `CLAUDE.md` already exists, merge: the generated block is inserted above the existing content, which becomes the repo-owned section — nothing the repo already wrote is discarded.
3. **Scaffold the memory** — `specs/proposals/`, `specs/features/`, `specs/decisions/` (per the `paths:` just written), each with a `.gitkeep` where empty.
4. **Seed the infrastructure record** — `specs/infrastructure.md` from `templates/infrastructure.md`, with the branch topology from the interview as its first entry (`infrastructure` skill: this is the repo-owned *what*; the skill is the *how*).
5. **Declare where the plugin comes from.** Installing the plugin writes the *enablement* — `enabledPlugins: {"harness@harness": true}` — into whichever settings scope the install chose; at project scope that is the repo's own `.claude/settings.json`, the file shared with the team. The marketplace that name resolves through is registered per machine either way, so a fresh clone resolves the enablement to nothing: no commands, no skills, and no enforcement hooks, with no error naming what is missing. Merge the provenance into the same file, next to the enablement:

   ```json
   "extraKnownMarketplaces": {
     "harness": { "source": { "source": "github", "repo": "sluengen/harness" } }
   }
   ```

   Merge the key into an existing settings file rather than rewriting it, and leave the rest of the file byte-for-byte alone. Write the same fact in prose into the spine's repo section — the marketplace and the two install commands, `/plugin marketplace add sluengen/harness` then `/plugin install harness@harness` — so a host too old to read the key still tells a reader what to run.

6. **Gate plumbing** — merge every pattern in this machine-identifiable block into `.gitignore`, appending only those absent so the operation is idempotent:

   <!-- harness:gate-ignore:begin -->
   ```gitignore
   .evidence/
   .worktrees/
   .claude/worktrees/
   ```
   <!-- harness:gate-ignore:end -->

   If the repo has no verify command yet, write a minimal `scripts/verify.sh` skeleton that runs the interview's lint/typecheck/test commands in order, runs `node scripts/gate-marker.js preflight` before those commands, and calls `node scripts/gate-marker.js write` on green. Copy the plugin's `scripts/gate-marker.js` **and `scripts/package.json`** beside it — the manifest pins the helper to CommonJS, and without it a repo whose root declares `"type": "module"` cannot run its own gate. A repo with its own gate keeps its commands, but add the preflight before its expensive stages and preserve the marker write at the end.
7. **Report** what was written, what was skipped because it existed, and the one next step: file or pick a ticket and `/build` it.

Hooks need no per-repo wiring — the plugin's `hooks/hooks.json` registers them at install. The spine's `branches:` block is what the push and stop guards read; that is why step 1's answers land there.

## `--refresh` — after a plugin update

Replace the content between `<!-- spine:generated:begin … -->` and `<!-- spine:generated:end -->` in `CLAUDE.md` with the current template's generated block, touching nothing outside the markers. Report the version stamped in the new marker. Merge the gate-ignore block from step 6 into `.gitignore` and add the gate preflight when the repo's verify command lacks it. The provenance declaration survives untouched — it lives in `.claude/settings.json`, which `--refresh` never writes; where it is *absent*, because the repo was hydrated before step 5 existed, report that and offer to write it. If the markers are missing (a hand-edited spine), do not guess: show the current generated block and ask the operator where it should go.

## What this never does

No tracker writes, no commits, no pushes — hydration is working-tree only, and the operator reviews and commits the result. It never overwrites a repo-owned section, never edits between another plugin's markers, and never touches an existing gate beyond reporting that it kept it.
