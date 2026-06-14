<!-- guidance:update-guidance@0.5.0 -->
# /update-guidance — pull guidance changes

Usage: `/update-guidance` (run inside a repo that was bootstrapped)

Compares the installed guidance against the source and pulls what changed, without clobbering anything you edited locally. This is the other half of `BOOTSTRAP.md`: the version stamps exist so this command can tell exactly what moved.

## Steps

### 1. Locate the source and fetch it
Read this repo's `.guidance-lock.yaml` → `source`. It records where this repo was installed from, in one of two forms:

- **GitHub remote** — `repo` is a cloneable git URL (`https://github.com/sluengen/harness.git`) and `branch` is the released ref external repos track (`main`). Clone it — `git clone --branch <branch> <repo>` into a temp dir (or `git fetch` an existing cache) — and read the fetched tree's `registry.yaml`. Clone with **history, not `--depth 1`**: a CONFLICT's 3-way base is the source content at the conflicted file's *locked version* (step 2), which lives in the source's git history. The harness authors and dogfoods the surface on `dev`, so external repos pull `main`, never in-flight `dev`.
- **Local checkout** — `repo` is a filesystem path and `ref` is `local` (the install iterated against a local harness checkout). Use that path directly; do **not** clone a remote, and do not silently switch the source to GitHub `main` (it may differ from the locally tested guidance). First confirm the checkout is still on the locked `branch` — its working tree may have moved since install — and if it has, read the locked branch through a temporary `git worktree` rather than its current tree. If a local checkout's history does not reach a conflicted file's locked version, that CONFLICT falls back to a manual 2-way diff (on-disk vs. new source).

**Migrate a legacy lock.** A pre-0.5 lock carries `source: { name, ref }` with no `repo`/`branch` (and `ref` may even be a retired-`agents`-repo SHA). All that is missing is *where the remote is*, so the migration is **non-destructive and metadata-only**: rewrite just the lock's `source:` block in place to `source: { repo: https://github.com/sluengen/harness.git, branch: main, ref: <unset> }` — this touches **no installed file**, so every LOCAL edit is preserved — then run `/update-guidance`, which classifies normally. The 3-way base is per-file (the locked version), **not** the old `ref`, so the unreachable agents-repo SHA is never fetched; the first clean pull sets a real `ref`. There is one bootstrap wrinkle: a consumer still on a pre-0.5 `/update-guidance` has no GitHub remote and cannot self-fetch *this* newer command (chicken-and-egg) — so install just the GitHub-aware `commands/update-guidance.md` once by hand (copy that single file from the source). Do **not** copy `registry.yaml` into the consumer root: its presence flips `guidance-freshness.js` into SOURCE mode and bypasses the consumer lock checks — the migrated command fetches the registry from the remote itself. (Re-running [`INSTALLER.md`](../INSTALLER.md) also works but **overwrites locally-edited installed guidance** — step 2 copies over any header-carrying file — so commit or stash those edits first and reconcile them afterward via the CONFLICT flow, or just prefer the metadata-only lock edit above.) In practice the only pre-0.5 install is the harness itself — now the source, with no consumer lock — so this path is currently unexercised.

### 2. Classify every installed file
For each file in the lock, compute its current on-disk hash and compare three things — the lock version, the source version, and whether the on-disk hash still matches the lock hash:

| State | Condition | Action |
|---|---|---|
| **current** | source version == lock version, hash matches | nothing |
| **PULL** | source version > lock version, hash matches lock | copy the new version in, update the lock |
| **LOCAL** | versions equal, hash differs from lock | the repo edited it — leave it; suggest pushing the change upstream |
| **CONFLICT** | source version > lock version AND hash differs | show a 3-way diff (base = source at the file's *locked* version); let the user choose |

Also report **new** files the source added to this profile (offer to install) and **removed** files (offer to delete).

### 3. Apply
Pull the clean PULLs automatically. For CONFLICTs, present the diff and ask. Never overwrite a LOCAL or CONFLICT file without confirmation. Never touch `CONTEXT.md` — it is repo-owned and not tracked as a distributable.

**Re-derive the derived artifacts — mandatory, not optional.** `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` are three byte-identical copies of the profile's process doc, and `.claude/settings.json` derives from `settings/<profile>.json`. They are **not** registry or lock entries — and that does **not** put them out of scope. Derived artifacts are *regenerated*, not tracked: whenever the process doc pulled an update, rewrite **all three** entry files from it. `CLAUDE.md` and `GEMINI.md` are no longer redirect shims — treating either as "just a pointer to `AGENTS.md`, so it's already fine" is the pre-triplication model and is wrong; a repo bootstrapped before triplication still has shims there, and this pass must replace them with the full content (the harness injects `CLAUDE.md` verbatim, so a stale one ships old guidance). For `.claude/settings.json`, regenerate it when the settings source updated — but if the repo merged local content into it (e.g. extra permissions), surface the change for a manual re-merge rather than clobbering it.

### 4. Rewrite the lock
Update `.guidance-lock.yaml` with the new versions and hashes for everything pulled, and write the full `source: { repo, branch, ref }` — carrying the `repo`/`branch` you used (including values filled by a step-1 legacy migration). Each file's lock entry is **self-contained**: its recorded version *is* its 3-way base for the next run (the source content at that version), so a partial pull — advancing some files while others stay LOCAL/CONFLICT — corrupts no base. `source.ref` is only an informational marker of the last fully-clean source tip: advance it to the fetched SHA when every file resolved cleanly, and leave it untouched while any CONFLICT/LOCAL remains. Leave LOCAL/CONFLICT entries as they are until resolved.

### 5. Verify
**Verify the derived artifacts first:** `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` must be byte-identical to each other (`diff` them). If any differs, the step-3 re-derivation was skipped — regenerate it now; do not proceed with the three out of sync.

### 6. Commit, integrate, and report
A guidance pull is maintenance, not feature work: it carries no ticket, spec, or review gate, so it lands without ceremony — don't make the user ask for the commit. Commit the pulled files, the re-derived artifacts, and the rewritten lock, then integrate per the repo's branch model (`CONTEXT.md` `branches`) exactly as `/ship` does — fast-forward or merge to the integration branch and push if the model pushes. Never force-push; never push to a protected branch unless `CONTEXT.md` says that is the path.

Commit only what resolved cleanly. Leave any unresolved CONFLICT/LOCAL files out of the commit and name them for the user to handle — do not block the clean pulls on them. If nothing was pulled (everything already current), there is nothing to commit: say so and stop.

Then print the counts: pulled, left local, conflicts awaiting decision, already current. Name each non-current file, confirm the three entry files match, and report the integration target and merge/push result.

## Note
If you find a bug in an installed guidance file, do not just patch it locally (that creates a LOCAL divergence forever). Fix it in the source, bump its version there, then `/update-guidance` here — so every repo benefits.
