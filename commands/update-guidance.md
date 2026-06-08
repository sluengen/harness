<!-- guidance:update-guidance@0.3.0 -->
# /update-guidance — pull guidance changes

Usage: `/update-guidance` (run inside a repo that was bootstrapped)

Compares the installed guidance against the source and pulls what changed, without clobbering anything you edited locally. This is the other half of `BOOTSTRAP.md`: the version stamps exist so this command can tell exactly what moved.

## Steps

### 1. Locate source and lock
Find the guidance source (the path/remote in `.guidance-lock.yaml` → `source`). Read its `registry.yaml` and this repo's `.guidance-lock.yaml`.

### 2. Classify every installed file
For each file in the lock, compute its current on-disk hash and compare three things — the lock version, the source version, and whether the on-disk hash still matches the lock hash:

| State | Condition | Action |
|---|---|---|
| **current** | source version == lock version, hash matches | nothing |
| **PULL** | source version > lock version, hash matches lock | copy the new version in, update the lock |
| **LOCAL** | versions equal, hash differs from lock | the repo edited it — leave it; suggest pushing the change upstream |
| **CONFLICT** | source version > lock version AND hash differs | show a 3-way diff; let the user choose |

Also report **new** files the source added to this profile (offer to install) and **removed** files (offer to delete).

### 3. Apply
Pull the clean PULLs automatically. For CONFLICTs, present the diff and ask. Never overwrite a LOCAL or CONFLICT file without confirmation. Never touch `CONTEXT.md` — it is repo-owned and not tracked as a distributable.

**Re-derive the derived artifacts — mandatory, not optional.** `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` are three byte-identical copies of the profile's process doc, and `.claude/settings.json` derives from `settings/<profile>.json`. They are **not** registry or lock entries — and that does **not** put them out of scope. Derived artifacts are *regenerated*, not tracked: whenever the process doc pulled an update, rewrite **all three** entry files from it. `CLAUDE.md` and `GEMINI.md` are no longer redirect shims — treating either as "just a pointer to `AGENTS.md`, so it's already fine" is the pre-triplication model and is wrong; a repo bootstrapped before triplication still has shims there, and this pass must replace them with the full content (the harness injects `CLAUDE.md` verbatim, so a stale one ships old guidance). For `.claude/settings.json`, regenerate it when the settings source updated — but if the repo merged local content into it (e.g. extra permissions), surface the change for a manual re-merge rather than clobbering it.

### 4. Rewrite the lock
Update `.guidance-lock.yaml` with the new versions and hashes for everything pulled. Leave LOCAL/CONFLICT entries as they are until resolved.

### 5. Verify and report
**Verify the derived artifacts first:** `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` must be byte-identical to each other (`diff` them). If any differs, the step-3 re-derivation was skipped — regenerate it now; do not report done with the three out of sync. Then print the counts: pulled, left local, conflicts awaiting decision, already current. Name each non-current file so the user knows what changed, and confirm the three entry files match.

## Note
If you find a bug in an installed guidance file, do not just patch it locally (that creates a LOCAL divergence forever). Fix it in the source, bump its version there, then `/update-guidance` here — so every repo benefits.
