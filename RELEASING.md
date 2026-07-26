# Release Checklist

Follow this checklist before tagging any release. All items must be ticked before pushing a version tag.

## Release notes + the `staging → main` promotion

Cutting a release starts by summarising what shipped since the last one and driving the promotion through to `main`. (This folds the retired `agents/tasks/release.md` agent task — the deterministic `release.yaml` workflow it replaced was removed in CAL-574, and a "task file" is not a durable artifact; see `specs/architecture-principles.md`, "A task is command + role + skill + template".)

1. **Gather the completed issues.** List issues closed in the release window (default: since the last release) on the GitHub tracker — `gh issue list --repo sluengen/harness --state closed --search "closed:>=<last-release-date>"`, or browse the "Harness" board (`CONTEXT.md` `github.project`). Derive each issue's kind from its labels (`bug` / `feature` / `improvement` / `chore`).
2. **Write the release notes.** Group the issues by kind under **Features**, **Bug fixes**, and **Improvements**; write concise, human-readable notes. The same content seeds the `README.md` CHANGELOG section (below) and the GitHub Release body.
3. **Rotate `CHANGELOG.md`.** The root changelog keeps only the current `[Unreleased]` window; the release moves its shipped entries into the per-year archive so the root stays bounded (CAL-1011). Move every entry under `## [Unreleased]` in `CHANGELOG.md` to the top of `CHANGELOG-archive/<year>.md` (newest first, under that file's `## Released` heading — create the file with an archive header if the year has none yet), then leave `## [Unreleased]` empty for the next cycle. The archive is historical record; the freshness hook still points authors at the root `CHANGELOG.md` for new entries, and `tests/unit/test_changelog_rotation.py` enforces the root's byte/line ceiling. Include this rotation in the promotion below.
4. **Drive the promotion to `main`** via `/promote staging to main` (or `harness promote start/continue/pr --from staging --to main` directly) — the audited promotion lifecycle (ADR 0003), which gates the merge and opens the release PR rather than a hand-rolled `gh pr create`.

   The `staging → main` promotion *is* the release (`specs/architecture-principles.md`, D7; ADR 0003 amendment, #189/#190). Merge the opened PR before working the checklist below.

## Between-release CHANGELOG fold

`CHANGELOG.md` accumulates every `[Unreleased]` entry continuously on `dev`; only step 3 above, at a `staging → main` release, ever rotates it. Between releases nothing shrinks the file, so a busy stretch of Build ticks runs it up against the ceilings `tests/unit/test_changelog_rotation.py` enforces. There are **two**, and they move independently:

| Bound | Value | Enforced by |
|---|---|---|
| Hard byte gate | 60,000 bytes | `test_root_changelog_is_byte_bounded` |
| Line ceiling | 250 lines | `test_root_changelog_is_line_bounded` |
| Soft byte warning (80% of the hard gate) | 48,000 bytes | `test_root_changelog_soft_warning_threshold` |

The soft warning is meant to fire first — CAL-1182 hit 9 bytes of headroom against the hard gate, and regrew to a second near-miss within four days (#195). But a fold that clears bytes may buy nothing at all against lines, so the pass you run depends on the reading, not on which test happened to trip.

1. **Measure before you fold.**

   ```bash
   wc -c CHANGELOG.md   # against the 48,000-byte soft warning and the 60,000-byte hard gate
   wc -l CHANGELOG.md   # against the 250-line ceiling
   ```

   Take both readings every time, and take them again after folding, before you run the gate. (`wc -l` counts newlines and matches the line test's `splitlines()` on this newline-terminated file, so the two numbers agree.) Whichever reading is at or near its bound decides the pass — often only one of them is.

2. **First pass — condense bodies. This relieves bytes only.** Keep the newest handful of entries at full detail and fold every older, multi-bullet entry down to its heading plus one summary bullet that preserves the entry's type, ticket id, and key mechanism. Full detail stays recoverable from git history; only the file is lossy, not the record.

   Note what this pass does *not* buy. A condensed entry is still a heading, a bullet, and a blank line — three lines, exactly what it occupied before — so however much prose you cut, the line count does not move. Run this pass when the byte reading is the one near its bound.

   **Condense, don't rotate.** Nothing in `[Unreleased]` has shipped to `main` yet, so none of it can move to `CHANGELOG-archive/<year>.md` — that archive holds released history only (step 3 above, not this step's job). Rotation clears neither ceiling between releases.

3. **Second pass — collapse heading and summary onto one line. This is the only fold that relieves lines.** Run it when the line reading is at or near 250. Move the oldest entries under a single `### Earlier still — one line each` heading, introduced by a blockquote recording that these are folded a second time and that full detail is in git history, then write one line per entry in the form `- **<original heading>** — <summary>`. That saves roughly two lines per entry, and further bytes on top. If the collapse heading already exists, append to it — there is one such block, never a second.

4. **Land it as a standalone commit on `dev`**, not tied to a release — most often an unattended Build tick's own fix-up before the next ticket's entry would otherwise breach a ceiling.

**The per-entry budget.** The fold is a symptom; entry *length* is the cause. It has run on nine consecutive ticks without ever buying durable headroom because the newest entries run 2,000–3,000 bytes each against a window median nearer 600, so a four-entry fold is consumed by the next two tickets. A full-detail `[Unreleased]` entry should target **1,000 bytes and three lines**. Reasoning longer than that belongs in the change spec, the commit body, or the review record — where it already lives in full, and where nobody pays a context tax to skip it.

Prior art, one commit per pass: `208118e` (CAL-1182) — the ad hoc first-pass byte fold this procedure gives a durable, repeatable home. `c907faf` (2026-07-26) — the second-pass line collapse: the byte fold earlier that day took the file 47,674 → 42,825 bytes, two new entries then tripped `test_root_changelog_is_line_bounded` at 251 lines against 250 with bytes still comfortable, and the collapse took it 251 → 174.

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
- [ ] The GitHub Projects "Harness" board (`sluengen/2`) shows no open items left in this release's window

### First GHCR publish only (one-time, manual)

The image package does not exist until the first tagged release pushes it. After that first publish, a human must do these once (deferred from CAL-623 — they need a live package / the GitHub UI and cannot be scripted in CI):

- [ ] In the package settings, enable **"Inherit access from repository"** so `sluengen/harness` collaborators get matching pull access (keep the package **private**).
- [ ] Verify access: a collaborator `docker login ghcr.io` + `docker pull ghcr.io/sluengen/harness:<version>` succeeds; an anonymous pull is denied.
- [ ] Flip the `~/bin/harness` wrapper default `HARNESS_IMAGE` to `ghcr.io/sluengen/harness:<version>` and update `ONBOARDING.md` — only once a pullable image exists, so existing local users aren't broken.
