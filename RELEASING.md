# Release Checklist

Follow this checklist before tagging any release. All items must be ticked before pushing a version tag.

## Release notes + `dev → main` PR

Cutting a release starts by summarising what shipped since the last one and opening the promotion PR. (This folds the retired `agents/tasks/release.md` agent task — the deterministic `release.yaml` workflow it replaced was removed in CAL-574, and a "task file" is not a durable artifact; see `specs/architecture-principles.md`, "A task is command + role + skill + template".)

1. **Gather the completed tickets.** Query Linear for issues completed in the release window (default: since the last release) via the `linear` skill (`skills/linear/SKILL.md`) — it owns the GraphQL; `LINEAR_API_KEY` comes from the repo `.env`, never hard-coded. Derive each ticket's kind from its labels (`bug` / `feature` / `improvement` / `chore`).
2. **Write the release notes.** Group the tickets by kind under **Features**, **Bug fixes**, and **Improvements**; write concise, human-readable notes. The same content seeds the `README.md` CHANGELOG section (below) and the GitHub Release body.
3. **Rotate `CHANGELOG.md`.** The root changelog keeps only the current `[Unreleased]` window; the release moves its shipped entries into the per-year archive so the root stays bounded (CAL-1011). Move every entry under `## [Unreleased]` in `CHANGELOG.md` to the top of `CHANGELOG-archive/<year>.md` (newest first, under that file's `## Released` heading — create the file with an archive header if the year has none yet), then leave `## [Unreleased]` empty for the next cycle. The archive is historical record; the freshness hook still points authors at the root `CHANGELOG.md` for new entries, and `tests/unit/test_changelog_rotation.py` enforces the root's byte/line ceiling. Include this rotation in the promotion PR below.
4. **Open the promotion PR** from `dev` to `main`:

   ```bash
   gh pr create --base main --head dev \
     --title "Release — $(date +%Y-%m-%d)" \
     --body-file <release-notes.md>
   ```

   The `dev → main` promotion *is* the release (`specs/architecture-principles.md`, D7). Merge it before working the checklist below.

## Pre-release

- [ ] All work for the release is merged to `main`
- [ ] `CHANGELOG` section in `README.md` is written and accurate — the newest era covers what shipped in this window (era granularity; the per-ticket record is `CHANGELOG-archive/<year>.md`)

## Verification gate

Run `scripts/verify.sh` and confirm every check passes:

```bash
bash scripts/verify.sh
```

The script runs, in order: ruff → mypy → pytest (with `--durations=20`) → CLI smoke (`harness version` and `harness --help`).

- [ ] `ruff check .` — zero errors
- [ ] `mypy harness` — zero errors
- [ ] `pytest` — all tests pass, no unexpected skips
- [ ] CLI smoke — `harness version` prints a version string and `harness --help` exits cleanly

## Tagging

```bash
git tag -s v<X.Y.Z> -m "v<X.Y.Z>"
git push origin v<X.Y.Z>
```

- [ ] Tag is signed (`-s`) or annotated (`-a`)
- [ ] Tag message matches the version number
- [ ] Tag is pushed to `origin`

Pushing a `v*` tag triggers `.github/workflows/release.yml`, which builds `docker/Dockerfile` and publishes `ghcr.io/sluengen/harness:<version>` (built-in `GITHUB_TOKEN`, `packages: write`). The workflow is inert until the tag is pushed.

## Post-release

- [ ] GitHub Release created from the tag with the changelog section pasted in
- [ ] Consuming repos updated to the new tag — see `ONBOARDING.md §Updating` for the per-install-method steps (git checkout + Docker rebuild, or pip upgrade)
- [ ] Linear milestone closed or next milestone opened

### First GHCR publish only (one-time, manual)

The image package does not exist until the first tagged release pushes it. After that first publish, a human must do these once (deferred from CAL-623 — they need a live package / the GitHub UI and cannot be scripted in CI):

- [ ] In the package settings, enable **"Inherit access from repository"** so `sluengen/harness` collaborators get matching pull access (keep the package **private**).
- [ ] Verify access: a collaborator `docker login ghcr.io` + `docker pull ghcr.io/sluengen/harness:<version>` succeeds; an anonymous pull is denied.
- [ ] Flip the `~/bin/harness` wrapper default `HARNESS_IMAGE` to `ghcr.io/sluengen/harness:<version>` and update `ONBOARDING.md` — only once a pullable image exists, so existing local users aren't broken.
