<!-- guidance:bootstrap@0.5.6 -->
# Bootstrap the guidance into a repo

> Paste this into an agent running **inside the target repo**, with the guidance source available (cloned locally or reachable). It installs a versioned copy of the guidance and scaffolds the repo's `CONTEXT.md`.

The model is **copy-in, version-stamped**: files are physically copied into the repo (not symlinked to an external clone) so every tool — Claude, Codex, Gemini — reads plain files, and the repo can diverge locally. Each file carries a `guidance:<id>@<version>` header; a `.guidance-lock.yaml` records what was installed so `/update-guidance` can pull changes later.

Installs come in two **visibility modes**, controlling what is committed to git:

- **`committed`** — all guidance files are committed. A clone or a cloud/CI runner has everything, so remote execution works. Default for **private** repos.
- **`local`** — only `CONTEXT.md` is committed; the internals are gitignored, present locally, and restored by re-running this bootstrap on a fresh clone. Keeps the methodology private and the repo clean. Default for **public** repos.

`CONTEXT.md` is always committed in both modes — it is agent-facing repo documentation, not methodology.

## Prompt

> You are installing the shared agent guidance into this repo.
>
> **1. Locate the source (GitHub `main`), note the single surface, pick a visibility mode.**
> The guidance source is the harness **GitHub** repo. Clone it at the released branch — `git clone --branch main --depth 1 https://github.com/sluengen/harness.git` to a temp dir (`registry.yaml` records the canonical cloneable `source.repo` and `source.branch`) — and read its `registry.yaml`. External repos install from `main`; the harness itself authors and dogfoods the surface on `dev`, so a non-harness repo pulls `main`, never in-flight `dev`. (A local path may be given instead when iterating on the source.) Then:
> - **Surface:** there is **one surface** — a single profile under `profiles:` (the `standard`/`harness` split is retired). Install that one surface; do not look for a repo-type profile to choose between. Repo-type variation — feature specs, design system — is set **after** install via this repo's `CONTEXT.md` `layers:` block (step 4), not by selecting a profile.
> - **Visibility mode:** `committed` (all guidance in git; enables cloud execution; default for private repos) or `local` (only `CONTEXT.md` in git; internals bootstrapped locally; default for public repos). Determine the repo's visibility with `gh repo view --json visibility` if available, else ask; default the mode from it.
> Confirm the visibility mode with me if it is ambiguous.
>
> **2. Check for collisions, then copy the profile's files in.**
> First, **never overwrite a pre-existing non-guidance file.** For every target path, if a file already exists there and does **not** carry a `guidance:` header (it is the repo's own, not a prior install), stop and resolve it — do not clobber it. **Exception — the registry-managed JSON files** (`settings/*.json` and `hooks/package.json`) carry no header by design (the registry version is authoritative), so header-presence can't distinguish a prior install from a repo-owned file. Use the **lock**: if `.guidance-lock.yaml` records this path, it is a prior install you may update; if no lock records it, treat an existing file as a potential repo-owned collision and stop to resolve it — never overwrite an unmarked settings file on a first install (registry membership alone does not prove the file came from us). The common case for the no-clobber rule is commands: the universal guidance commands own the bare names (`/start`, `/review`, `/ship`, `/propose`, `/assess`, `/update-guidance`), so a repo's own command at one of those paths — a `commands/start.md` that means *launch this repo's pipeline* rather than *begin the agent-led process* — must be **namespaced under a repo prefix first** (e.g. `/<repo> …` — see `process/harness.md`) before the guidance installs its version. The same no-clobber rule applies to any path.
> Then, for every entry in `registry.yaml` whose `profiles` includes the single profile (the one surface), copy the file to the same path, **preserving its `guidance:` header verbatim**. This covers `skills/`, `agents/`, `commands/`, `templates/`, and the process doc. (Re-running over a prior install is fine — those files carry the header and are yours to update.)
>
> **Also copy `GUIDANCE-MIT.md` to the target repo root.** The guidance you just copied in is **MIT**-licensed, carved out of the harness's AGPL-3.0 engine precisely so it can live in your repo — including a proprietary one — without encumbering it. That carve-out is worth nothing if it is invisible: without this file the repo holds unmarked prose copied out of an AGPL-licensed source, and a compliance scanner has every reason to assume the worst. It is a licence, not guidance, so it carries no `guidance:` header and no version, and it is **not** a `registry.yaml` entry — record it in `.guidance-lock.yaml` like any installed path, and apply the same lock-based no-clobber rule the registry-managed JSON settings use. **Commit it in both visibility modes**, including `local` — a licence that is gitignored does not tell anyone anything.
>
> **Flag legacy-process artifacts.** A repo set up under an older process may carry artifacts the new model has retired:
> - A **`manifest.yaml`** (the new model uses Linear; there is no manifest — see `linear`).
> - Old per-task **`changes/` folders, including nested ones** (e.g. `harness/changes/`) — search the tree, not just the root. But a `changes/` folder may be *functional* (test fixtures, runtime output, referenced by code) rather than legacy — check for references before flagging, and present it for the user to classify; never assume it is cruft.
> - **Superseded skill/agent files** the guidance has since merged or renamed: a repo's own `scope-discipline`, `verification-before-completion`, or `code-structure` are now folded into `code-quality`; an old `spec.md` template is now `feature.md`. **The merge into the harness folded more** (a pre-merge install carries all of these): `linear-sync` → `linear`; the `code-steward` and `harness-steward` agents → one `steward`; the `code-review` skill is gone (its concept is now `review-discipline` + the `/code-review` command); `process/standard.md` → `process/harness.md` and `settings/standard.json` → `settings/harness.json`; and the **flat `skills/*.md` layout moved to `skills/<id>/SKILL.md`**, so *every* old flat skill file is superseded. The old lock's `name`/`ref` source line becomes a `{ repo, branch, ref }` remote. These sit alongside the new files as redundant cruft — **but check references first** (the repo's own agents/docs may still point at the old names; update those to the merged file, or leave the old file, rather than break them).
>
> Detect these and surface them: recommend migrating any open items (to Linear, or the repo's idea inbox), then removing the artifact. **Do not delete automatically** — they may hold un-migrated history; remove only with my confirmation. Two kinds get different handling: a prior install's **own** renamed or folded files (they carry a `guidance:` header, or the prior `.guidance-lock.yaml` records them) are superseded cleanup — the re-bootstrap is replacing them, so **confirm that removal once, in bulk** rather than file-by-file; files the **repo itself owns** (no `guidance:` header, not in the prior lock) get the per-file confirmation, since those may be the repo's own work. Note any you found in the step 7 report.
>
> **A re-bootstrap is how you supersede pre-merge guidance.** Concretely, superseding pre-merge guidance — an older install (from before the guidance repo merged into the harness) whose skills that merge renamed or folded (`scope-discipline` / `verification-before-completion` / `code-structure` → `code-quality`) and whose old `spec.md` template became `feature.md` — is done by **re-running this installer (a re-bootstrap)**, *not* by `/update-guidance`. The fold knowledge (which old file folds into which new one) lives only here, in the legacy-artifact handling above; `/update-guidance` would see a renamed skill as a generic "removed" file and its replacement as "added", losing the fold relationship and any local edits. `/update-guidance` is for a repo **already on a harness lock** (see [`commands/update-guidance.md`](commands/update-guidance.md)); a repo still carrying pre-merge guidance is not yet in that state.
>
> **3. Create the entry files.**
> - **Preserve before you overwrite.** If `AGENTS.md` / `CLAUDE.md` / `GEMINI.md` already exist with repo-specific content (a prior setup, or a file carrying no `guidance:` header), read them **now** and migrate any repo-specific knowledge they hold (gotchas, the verify gate, conventions, architecture notes) into `CONTEXT.md` (step 4) before the copies below clobber them. Do not lose it.
> - Copy the profile's process doc (e.g. the profile's `process/<profile>.md`) to `AGENTS.md` at the repo root.
> - Write `CLAUDE.md` and `GEMINI.md` as **byte-identical copies of `AGENTS.md`** (the same process-doc content and `guidance:` header) — not shims. Each tool auto-loads a different name (Claude → `CLAUDE.md`, Gemini → `GEMINI.md`, Codex → `AGENTS.md`), and a goal-directed agent reads the file it is handed rather than following a pointer to a second one — so the full process lives in all three. The process doc already says to read `CONTEXT.md` first, so the shim's pointer is preserved. It also matters to any tool that injects one of these files verbatim into a session: a shim would hand it nothing. `/update-guidance` re-derives all three from the process doc.
> - Create `.claude/` with symlinks `agents -> ../agents`, `skills -> ../skills`, `commands -> ../commands`, `hooks -> ../hooks`, and **derive** `.claude/settings.json` from the profile's `settings/<profile>.json` (which step 2 already copied in, since it is a registry file). `.claude/settings.json` is a derived copy — like `AGENTS.md` is derived from the process doc — so `/update-guidance` regenerates it when the source settings change. The settings file wires the hooks; they are Claude Code only (Codex and Gemini read the same plain files but do not run hooks).
> - Create Codex-native derived artifacts. Run `templates/generate_codex_artifacts.py` to generate `.codex/agents/*.toml` from `agents/*.md`, preserving each agent's role, description, and instruction body while translating host-specific tool names to Codex's available agent role format. The same generator creates a Codex skills directory: `.codex/skills/<id> -> ../../skills/<id>` exposes each canonical repo skill, and `.codex/skills/command-<id>/SKILL.md` is a thin generated adapter for each `commands/*.md` file. Codex does not discover repo-local slash commands, so commands are surfaced to Codex as skills while Claude still sees the same canonical markdown through `.claude/commands`. These are derived artifacts: `agents/*.md`, `skills/<id>/SKILL.md`, and `commands/*.md` remain the source of truth.
> - **On Windows without Developer Mode, substitute junctions for those symlinks.** Git forces `core.symlinks=false` there and materializes each committed `.claude/*` symlink as a **plain text file holding its target path**, so nothing under `.claude/` resolves and every skill and slash command disappears — with nothing logged, which makes it indistinguishable from a repo that never installed the guidance. Per clone, for each of the four links:
>
>   ```
>   del .claude\agents .claude\commands .claude\hooks .claude\skills
>
>   cmd /c mklink /J .claude\agents   ..\agents     # directory junctions — need no elevation
>   cmd /c mklink /J .claude\commands ..\commands
>   cmd /c mklink /J .claude\hooks    ..\hooks
>   cmd /c mklink /J .claude\skills   ..\skills
>
>   git update-index --skip-worktree .claude/agents .claude/commands .claude/hooks .claude/skills
>   ```
>
>   and add the trailing-slash ignore rules `.claude/agents/`, `.claude/commands/`, `.claude/hooks/`, `.claude/skills/` (step 6). **Both halves are load-bearing, and the reason is the same mechanism:** git *descends into* a junction where it would not follow a symlink. So without the ignore rules a later `git add .` stages a second copy of the whole bundle under `.claude/` and replaces the symlinks Linux and CI depend on; the trailing slash matches only the directory form, suppressing the junction's contents while leaving the tracked symlink blob at that same path alone. `--skip-worktree` closes the other half: without it the junction reads as a *modification* of the symlink entry, and the first careless `git commit -a` converts the repo. This is a per-clone workaround — the installer still records symlinks, and the committed tree stays correct for every other platform.
>
> **4. Scaffold `CONTEXT.md`.**
> **Only if `CONTEXT.md` does not already exist**, copy `templates/CONTEXT.template.md` to `CONTEXT.md`. On a re-bootstrap (e.g. restoring a `local`-mode install on a fresh clone) the populated `CONTEXT.md` is already committed — **keep it**, fill only still-empty `{placeholder}` fields, and never overwrite it with the blank template (it holds repo-specific branch, tracker, env, and operational detail that may not be re-inferable). Then fill it by inspecting the repo:
> - Read `package.json` / `pyproject.toml` / lockfiles for stack and commands.
> - Read `README.md` and the top-level tree for architecture and paths.
> - Read `git remote` and any existing tracker config.
> - **Verification gate + conventions:** if the repo has a *canonical combined gate* (e.g. `scripts/verify.sh` bundling lint + type + test + smoke), capture it in `commands.verify` — do not lose it by only recording the decomposed lint/test commands. Capture any commit-format convention (e.g. `type(scope): description`) in `conventions.commit_format`.
> - **Prior-setup entry files:** fold the repo-specific knowledge you preserved in step 3 (before overwriting `AGENTS.md` / `CLAUDE.md` / `GEMINI.md`) into the relevant `CONTEXT.md` fields here.
> - **Env file + tracker token:** look for `.env`, `.env.local`, `.env.*`. Grep them for the tracker's credential — match the *variable name*, never echo the value. Record the file in `env.file` and the variable under env: for a `tracker: linear` repo that is `LINEAR_API_KEY` → `env.linear_token`; for a `tracker: github` repo it is `GITHUB_TOKEN` (`repo` + `project` scopes) → `env.github_token`. If the token sits in a different file than the tooling will source, note it and offer to consolidate **with my confirmation** — never move a secret silently. If the repo is on a tracker but no token is found, flag it for me to add; do not invent one.
> - **GitHub tracker config:** if the repo tracks work on **GitHub** (Issues + a Projects v2 board) rather than Linear, set `tracker: github`, `repo.linear: none`, and fill the `github:` block — ask me for the **issues repo** (`owner/name`), the **Projects v2 board** (`owner/number`), and, if the board's status field is renamed from the built-in "Status", the `status_field`. Do not invent these IDs.
> Fill what you can confidently infer. For everything you cannot — the tracker invocation and IDs, the branch model, the layer flags, repo-specific principles, gotchas — **ask me, one focused batch of questions.** Do not invent facts. Set the `profile:` and `visibility:` fields to match the choices from step 1.
>
> **5. Write `.guidance-lock.yaml`** at the repo root recording, for every file installed: its path, version (from `registry.yaml`), and a short content hash. Record the chosen profile and the source **you actually installed from** — so `/update-guidance` re-fetches that same source, not a different one. For the standard GitHub install, that is the registry's `repo` + `branch` plus the `ref` SHA you cloned. For the local-checkout path, record the **local checkout** instead (`repo:` its path, `branch:` its branch, `ref: local`) — do *not* write the GitHub `main` remote, or the next update silently switches the consumer to `main`, which may differ from the locally tested guidance. Schema:
>
> ```yaml
> # guidance lock — written by the installer, updated by /update-guidance
> profile: harness
> # GitHub install (the default): the cloneable remote + released branch + cloned SHA.
> source: { repo: https://github.com/sluengen/harness.git, branch: main, ref: <git sha> }
> # Local-checkout install instead: record the checkout you installed from.
> #   source: { repo: /abs/path/to/harness, branch: <its-branch>, ref: local }
> files:
>   skills/code-quality/SKILL.md: { version: 0.4.0, hash: <sha256-first12> }
>   # ... one line per installed file (skills are the Agent Skills shape skills/<id>/SKILL.md)
> ```
>
> **6. Reconcile `.gitignore` for the visibility mode.** Never ignore `CONTEXT.md` in either mode. Do not remove unrelated ignores.
> - **committed mode:** the installed files must be committed. Check `.gitignore` for rules excluding any installed path (`.claude/`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `hooks/`, `skills/`, `agents/`, `commands/`, `templates/`, `process/`, `.guidance-lock.yaml`). A repo set up under an older model may ignore `.claude/`, `CLAUDE.md`, or `hooks/` as ephemeral — narrow each such rule so only `.claude/settings.local.json` stays ignored.
> - **local mode:** only `CONTEXT.md` is committed. Add root-anchored ignores for the internals you installed: `/.claude/`, `/.codex/`, `/.gemini/`, `/CLAUDE.md`, `/AGENTS.md`, `/GEMINI.md`, `/skills/`, `/agents/`, `/commands/`, `/hooks/`, `/templates/`, `/process/`, `/settings/`, `/.guidance-lock.yaml`. Only ignore paths you actually installed (do not mask a directory the repo already owns). Confirm `CONTEXT.md` stays tracked.
> - **both modes (Windows junctions):** where step 3's junction workaround is in force, its four trailing-slash rules (`.claude/agents/`, `.claude/commands/`, `.claude/hooks/`, `.claude/skills/`) belong here too. They are **not** a committed-mode violation to narrow away: each matches only the *directory* a junction presents, never the tracked symlink blob at the same path, so no installed guidance path is actually excluded.
> - **both modes (secret safety):** confirm the env file (`CONTEXT.md` → `env.file`) and any other secret-bearing file are gitignored. Never let a file holding a token become committable. If the env file is not yet ignored, add it.
> - **per-tool config dirs (`.codex/`, `.gemini/`):** other agent tools generate their own config from the installed files (e.g. Codex writes `.codex/agents/*.toml`). Treat them like `.claude/` — **committed in committed mode** (most of it is portable agent config), **ignored in local mode** (listed above). Narrowly ignore only a genuinely per-machine file if a tool emits one with absolute paths (e.g. an absolute-path hooks config), the way `.claude/settings.local.json` is ignored — not the whole directory.
>
> **7. Verify.**
> - Every file in the lock exists and still carries its `guidance:` header — **except** the registry-managed JSON files (`settings/*.json` and `hooks/package.json`), which carry no header; verify their recorded version against `registry.yaml` instead.
> - `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` are byte-identical (one derived process artifact under three names).
> - `.claude/agents`, `.claude/skills`, `.claude/commands`, `.claude/hooks` resolve. On a Windows clone using step 3's junctions, `dir .claude` shows `<JUNCTION>` for each and `git status` reports those four paths **unmodified** — a deletion or modification there means `--skip-worktree` did not take.
> - `templates/generate_codex_artifacts.py --check` passes. `.codex/agents/*.toml` exists for each generated Codex role and references the current `skills/<id>/SKILL.md` paths, not retired flat skill files; `.codex/skills/<id>` resolves to each repo skill; and `.codex/skills/command-<id>/SKILL.md` exists for each `commands/*.md` file.
> - `CONTEXT.md` has no remaining `{placeholder}` tokens and is **not** git-ignored (always committed).
> - **committed mode:** `git check-ignore` confirms no installed guidance path is excluded. **local mode:** `git status` shows only `CONTEXT.md` (and the `.gitignore` change) as guidance-related tracked changes; the internals are ignored but still present on disk.
> Report the visibility mode, what was installed (counts per directory), what you inferred for `CONTEXT.md`, any `.gitignore` rules you reconciled, and what you need me to confirm.

## After bootstrap

- **committed mode:** commit the installed files and `.guidance-lock.yaml`; they travel to any clone or cloud runner.
- **local mode:** commit `CONTEXT.md` and the `.gitignore` change only; the internals stay local. A fresh clone re-runs this bootstrap to restore them. The lock is local too, so `/update-guidance` needs the guidance present — re-bootstrap first on a clean clone.
- `CONTEXT.md` is yours to maintain — `/update-guidance` never overwrites it.
- To pull upstream guidance changes later, run `/update-guidance`: it diffs `.guidance-lock.yaml` against the source `registry.yaml`, auto-pulls files you have not locally edited (hash matches), and surfaces a diff for any you have.
