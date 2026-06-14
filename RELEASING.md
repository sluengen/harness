# Release Checklist

Follow this checklist before tagging any release. All items must be ticked before pushing a version tag.

## Pre-release

- [ ] All work for the release is merged to `main`
- [ ] `CHANGELOG` section in `README.md` is written and accurate
- [ ] Version roadmap tables in `README.md` and `CLAUDE.md` reflect what shipped vs what's next

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
- [ ] Consuming repos updated to the new tag — see `BOOTSTRAP.md §Updating` for the per-install-method steps (git checkout + Docker rebuild, or pip upgrade)
- [ ] Linear milestone closed or next milestone opened

### First GHCR publish only (one-time, manual)

The image package does not exist until the first tagged release pushes it. After that first publish, a human must do these once (deferred from CAL-623 — they need a live package / the GitHub UI and cannot be scripted in CI):

- [ ] In the package settings, enable **"Inherit access from repository"** so `sluengen/harness` collaborators get matching pull access (keep the package **private**).
- [ ] Verify access: a collaborator `docker login ghcr.io` + `docker pull ghcr.io/sluengen/harness:<version>` succeeds; an anonymous pull is denied.
- [ ] Flip the `~/bin/harness` wrapper default `HARNESS_IMAGE` to `ghcr.io/sluengen/harness:<version>` and update `BOOTSTRAP.md` — only once a pullable image exists, so existing local users aren't broken.
