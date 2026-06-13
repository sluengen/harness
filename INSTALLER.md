<!-- guidance:bootstrap@0.4.2 -->
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
> **1. Locate the source, pick a profile, pick a visibility mode.**
> Find the guidance source (path given to you, or clone `<source repo>` to a temp dir) and read its `registry.yaml`. Then decide:
> - **Profile:** read the registry's `profiles:` block and pick the one whose `description` matches this repo. Only the profiles that block defines are installable — do not assume a profile that is not listed there (the source publishes a profile only once every file it needs is present).
> - **Visibility mode:** `committed` (all guidance in git; enables cloud execution; default for private repos) or `local` (only `CONTEXT.md` in git; internals bootstrapped locally; default for public repos). Determine the repo's visibility with `gh repo view --json visibility` if available, else ask; default the mode from it.
> Confirm both with me if either is ambiguous.
>
> **2. Check for collisions, then copy the profile's files in.**
> First, **never overwrite a pre-existing non-guidance file.** For every target path, if a file already exists there and does **not** carry a `guidance:` header (it is the repo's own, not a prior install), stop and resolve it — do not clobber it. **Exception — registry-managed JSON settings** (`settings/*.json`) carry no header by design (the registry version is authoritative), so header-presence can't distinguish a prior install from a repo-owned file. Use the **lock**: if `.guidance-lock.yaml` records this path, it is a prior install you may update; if no lock records it, treat an existing file as a potential repo-owned collision and stop to resolve it — never overwrite an unmarked settings file on a first install (registry membership alone does not prove the file came from us). The common case for the no-clobber rule is commands: the universal guidance commands own the bare names (`/start`, `/review`, `/ship`, `/propose`, `/assess`, `/update-guidance`), so a repo's own command at one of those paths (e.g. a harness repo whose `commands/start.md` launches the harness) must be **namespaced under a repo prefix first** (e.g. `/harness …` — see `process/harness.md`) before the guidance installs its version. The same no-clobber rule applies to any path.
> Then, for every entry in `registry.yaml` whose `profiles` includes the chosen profile, copy the file to the same path, **preserving its `guidance:` header verbatim**. This covers `skills/`, `agents/`, `commands/`, `templates/`, and the profile's process doc. (Re-running over a prior install is fine — those files carry the header and are yours to update.)
>
> **Flag legacy-process artifacts.** A repo set up under an older process may carry artifacts the new model has retired:
> - A **`manifest.yaml`** (the new model uses Linear; there is no manifest — see `linear-sync`).
> - Old per-task **`changes/` folders, including nested ones** (e.g. `harness/changes/`) — search the tree, not just the root. But a `changes/` folder may be *functional* (test fixtures, runtime output, referenced by code) rather than legacy — check for references before flagging, and present it for the user to classify; never assume it is cruft.
> - **Superseded skill/agent files** the guidance has since merged or renamed: a repo's own `scope-discipline`, `verification-before-completion`, or `code-structure` are now folded into `code-quality`; an old `spec.md` template is now `feature.md`. These sit alongside the new files as redundant cruft — **but check references first** (the repo's own agents/docs may still point at the old names; update those to the merged file, or leave the old file, rather than break them).
>
> Detect these and surface them: recommend migrating any open items (to Linear, or the repo's idea inbox), then removing the artifact. **Do not delete automatically** — they may hold un-migrated history; remove only with my confirmation. Note any you found in the step 7 report.
>
> **3. Create the entry files.**
> - **Preserve before you overwrite.** If `AGENTS.md` / `CLAUDE.md` / `GEMINI.md` already exist with repo-specific content (a prior setup, or a file carrying no `guidance:` header), read them **now** and migrate any repo-specific knowledge they hold (gotchas, the verify gate, conventions, architecture notes) into `CONTEXT.md` (step 4) before the copies below clobber them. Do not lose it.
> - Copy the profile's process doc (e.g. the profile's `process/<profile>.md`) to `AGENTS.md` at the repo root.
> - Write `CLAUDE.md` and `GEMINI.md` as **byte-identical copies of `AGENTS.md`** (the same process-doc content and `guidance:` header) — not shims. Each tool auto-loads a different name (Claude → `CLAUDE.md`, Gemini → `GEMINI.md`, Codex → `AGENTS.md`), and a goal-directed agent reads the file it is handed rather than following a pointer to a second one — so the full process lives in all three. The process doc already says to read `CONTEXT.md` first, so the shim's pointer is preserved. This also matters for the pipeline harness, which injects `CLAUDE.md` verbatim: a shim would hand it nothing. `/update-guidance` re-derives all three from the process doc.
> - Create `.claude/` with symlinks `agents -> ../agents`, `skills -> ../skills`, `commands -> ../commands`, `hooks -> ../hooks`, and **derive** `.claude/settings.json` from the profile's `settings/<profile>.json` (which step 2 already copied in, since it is a registry file). `.claude/settings.json` is a derived copy — like `AGENTS.md` is derived from the process doc — so `/update-guidance` regenerates it when the source settings change. The settings file wires the hooks; they are Claude Code only (Codex and Gemini read the same plain files but do not run hooks).
>
> **4. Scaffold `CONTEXT.md`.**
> **Only if `CONTEXT.md` does not already exist**, copy `templates/CONTEXT.template.md` to `CONTEXT.md`. On a re-bootstrap (e.g. restoring a `local`-mode install on a fresh clone) the populated `CONTEXT.md` is already committed — **keep it**, fill only still-empty `{placeholder}` fields, and never overwrite it with the blank template (it holds repo-specific branch, tracker, env, and operational detail that may not be re-inferable). Then fill it by inspecting the repo:
> - Read `package.json` / `pyproject.toml` / lockfiles for stack and commands.
> - Read `README.md` and the top-level tree for architecture and paths.
> - Read `git remote` and any existing tracker config.
> - **Verification gate + conventions:** if the repo has a *canonical combined gate* (e.g. `scripts/verify.sh` bundling lint + type + test + smoke), capture it in `commands.verify` — do not lose it by only recording the decomposed lint/test commands. Capture any commit-format convention (e.g. `type(scope): description`) in `conventions.commit_format`.
> - **Prior-setup entry files:** fold the repo-specific knowledge you preserved in step 3 (before overwriting `AGENTS.md` / `CLAUDE.md` / `GEMINI.md`) into the relevant `CONTEXT.md` fields here.
> - **Env file + Linear token:** look for `.env`, `.env.local`, `.env.*`. Grep them for `LINEAR_API_KEY` — match the *variable name*, never echo the value. Record the file in `env.file` and the variable in `env.linear_token`. If the token sits in a different file than the tooling will source, note it and offer to consolidate **with my confirmation** — never move a secret silently. If the repo is on Linear (`linear: true`) but no token is found, flag it for me to add; do not invent one.
> Fill what you can confidently infer. For everything you cannot — the tracker invocation and IDs, the branch model, the layer flags, repo-specific principles, gotchas — **ask me, one focused batch of questions.** Do not invent facts. Set the `profile:` and `visibility:` fields to match the choices from step 1.
>
> **5. Write `.guidance-lock.yaml`** at the repo root recording, for every file installed: its path, version (from `registry.yaml`), and a short content hash. Record the chosen profile and the source ref. Schema:
>
> ```yaml
> # guidance lock — written by the installer, updated by /update-guidance
> profile: harness
> source: { name: harness, ref: <git sha or "local"> }
> files:
>   skills/code-quality.md: { version: 0.4.0, hash: <sha256-first12> }
>   # ... one line per installed file (paths are the installed/flat shape)
> ```
>
> **6. Reconcile `.gitignore` for the visibility mode.** Never ignore `CONTEXT.md` in either mode. Do not remove unrelated ignores.
> - **committed mode:** the installed files must be committed. Check `.gitignore` for rules excluding any installed path (`.claude/`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `hooks/`, `skills/`, `agents/`, `commands/`, `templates/`, `process/`, `.guidance-lock.yaml`). A repo set up under an older model may ignore `.claude/`, `CLAUDE.md`, or `hooks/` as ephemeral — narrow each such rule so only `.claude/settings.local.json` stays ignored.
> - **local mode:** only `CONTEXT.md` is committed. Add root-anchored ignores for the internals you installed: `/.claude/`, `/.codex/`, `/.gemini/`, `/CLAUDE.md`, `/AGENTS.md`, `/GEMINI.md`, `/skills/`, `/agents/`, `/commands/`, `/hooks/`, `/templates/`, `/process/`, `/settings/`, `/.guidance-lock.yaml`. Only ignore paths you actually installed (do not mask a directory the repo already owns). Confirm `CONTEXT.md` stays tracked.
> - **both modes (secret safety):** confirm the env file (`CONTEXT.md` → `env.file`) and any other secret-bearing file are gitignored. Never let a file holding a token become committable. If the env file is not yet ignored, add it.
> - **per-tool config dirs (`.codex/`, `.gemini/`):** other agent tools generate their own config from the installed files (e.g. Codex writes `.codex/agents/*.toml`). Treat them like `.claude/` — **committed in committed mode** (most of it is portable agent config), **ignored in local mode** (listed above). Narrowly ignore only a genuinely per-machine file if a tool emits one with absolute paths (e.g. an absolute-path hooks config), the way `.claude/settings.local.json` is ignored — not the whole directory.
>
> **7. Verify.**
> - Every file in the lock exists and still carries its `guidance:` header — **except** registry-managed JSON settings (`settings/*.json`), which carry no header; verify their recorded version against `registry.yaml` instead.
> - `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` are byte-identical (one derived process artifact under three names).
> - `.claude/agents`, `.claude/skills`, `.claude/commands`, `.claude/hooks` resolve.
> - `CONTEXT.md` has no remaining `{placeholder}` tokens and is **not** git-ignored (always committed).
> - **committed mode:** `git check-ignore` confirms no installed guidance path is excluded. **local mode:** `git status` shows only `CONTEXT.md` (and the `.gitignore` change) as guidance-related tracked changes; the internals are ignored but still present on disk.
> Report the visibility mode, what was installed (counts per directory), what you inferred for `CONTEXT.md`, any `.gitignore` rules you reconciled, and what you need me to confirm.

## After bootstrap

- **committed mode:** commit the installed files and `.guidance-lock.yaml`; they travel to any clone or cloud runner.
- **local mode:** commit `CONTEXT.md` and the `.gitignore` change only; the internals stay local. A fresh clone re-runs this bootstrap to restore them. The lock is local too, so `/update-guidance` needs the guidance present — re-bootstrap first on a clean clone.
- `CONTEXT.md` is yours to maintain — `/update-guidance` never overwrites it.
- To pull upstream guidance changes later, run `/update-guidance`: it diffs `.guidance-lock.yaml` against the source `registry.yaml`, auto-pulls files you have not locally edited (hash matches), and surfaces a diff for any you have.
