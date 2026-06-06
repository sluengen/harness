<!-- guidance:update-guidance@0.1.1 -->
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

**Re-derive the derived artifacts.** `AGENTS.md` is derived from the profile's process doc and `.claude/settings.json` from `settings/<profile>.json`. When either source pulled an update, regenerate its derived copy — but if the repo merged local content into `.claude/settings.json` (e.g. extra permissions), surface the settings change for a manual re-merge rather than clobbering it.

### 4. Rewrite the lock
Update `.guidance-lock.yaml` with the new versions and hashes for everything pulled. Leave LOCAL/CONFLICT entries as they are until resolved.

### 5. Report
Print the counts: pulled, left local, conflicts awaiting decision, already current. Name each non-current file so the user knows what changed.

## Note
If you find a bug in an installed guidance file, do not just patch it locally (that creates a LOCAL divergence forever). Fix it in the source, bump its version there, then `/update-guidance` here — so every repo benefits.
