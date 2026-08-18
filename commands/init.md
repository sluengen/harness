# /harness:init — hydrate a repo

Usage: `/harness:init` (first-time setup) · `/harness:init --refresh` (after a plugin update)

Turns a repository into one this process can run in. The plugin carries the skills, commands, agents, and hooks; this command writes the handful of files that must be **repo-owned**: the spine, the specs scaffold, the infrastructure record, and the gate's ignore rule. Always invoked with its plugin prefix — bare `/init` is the host's own command.

## First-time setup

1. **Interview for the repo values.** From the repo itself where possible (language, test runner, existing branch names), from the operator where not: name, tracker backend and its addresses, stack, the five commands (install / lint / typecheck / test / verify), branch roles, and layer switches. The verify command is the one that matters most — it is the single command that decides green, and the hooks enforce against its marker.
2. **Write the spine** — `CLAUDE.md` from `templates/spine.md`: the generated block verbatim, the repo section filled from the interview. If a `CLAUDE.md` already exists, merge: the generated block is inserted above the existing content, which becomes the repo-owned section — nothing the repo already wrote is discarded.
3. **Scaffold the memory** — `specs/proposals/`, `specs/features/`, `specs/decisions/` (per the `paths:` just written), each with a `.gitkeep` where empty.
4. **Seed the infrastructure record** — `specs/infrastructure.md` from `templates/infrastructure.md`, with the branch topology from the interview as its first entry (`infrastructure` skill: this is the repo-owned *what*; the skill is the *how*).
5. **Gate plumbing** — append `.evidence/` to `.gitignore` if absent; if the repo has no verify command yet, write a minimal `scripts/verify.sh` skeleton that runs the interview's lint/typecheck/test commands in order and calls `gate_marker.py write` on green, and copy `scripts/gate_marker.py` from the plugin's templates. A repo with its own gate keeps it — the only requirement is that green ends with a marker write.
6. **Report** what was written, what was skipped because it existed, and the one next step: file or pick a ticket and `/build` it.

Hooks need no per-repo wiring — the plugin's `hooks/hooks.json` registers them at install. The spine's `branches:` block is what the push and stop guards read; that is why step 1's answers land there.

## `--refresh` — after a plugin update

Replace the content between `<!-- spine:generated:begin … -->` and `<!-- spine:generated:end -->` in `CLAUDE.md` with the current template's generated block, touching nothing outside the markers. Report the version stamped in the new marker. If the markers are missing (a hand-edited spine), do not guess: show the current generated block and ask the operator where it should go.

## What this never does

No tracker writes, no commits, no pushes — hydration is working-tree only, and the operator reviews and commits the result. It never overwrites a repo-owned section, never edits between another plugin's markers, and never touches an existing gate beyond reporting that it kept it.
