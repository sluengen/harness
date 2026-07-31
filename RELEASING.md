# Release Checklist

Follow this checklist before tagging any release. All items must be ticked before pushing a version tag.

## Release notes + the `staging → main` promotion

Cutting a release starts by summarising what shipped since the last one and driving the promotion through to `main`. (This folds the retired `agents/tasks/release.md` agent task — the deterministic `release.yaml` workflow it replaced was removed in CAL-574, and a "task file" is not a durable artifact; see `specs/architecture-principles.md`, "A task is command + role + skill + template".)

1. **Gather the completed issues.** List issues closed in the release window (default: since the last release) on the GitHub tracker — `gh issue list --repo sluengen/harness --state closed --search "closed:>=<last-release-date>"`, or browse the "Harness" board (`CONTEXT.md` `github.project`). Derive each issue's kind from its labels (`bug` / `feature` / `improvement` / `chore`).
2. **Write the release notes.** Group the issues by kind under **Features**, **Bug fixes**, and **Improvements**; write concise, human-readable notes. The same content seeds the `README.md` CHANGELOG section (below) and the GitHub Release body.
3. **Fold the fragments, then rotate `CHANGELOG.md`.** Since #267 the unreleased window is `changelog.d/`, not the root file. Fold first, rotate second:

   ```bash
   uv run --extra dev python scripts/changelog_fragments.py fold --version <X.Y.Z> --date <YYYY-MM-DD>
   ```

   That assembles every fragment into one `## [<version>] — <date>` section (grouped by category, newest ticket first, bodies verbatim), inserts it into `CHANGELOG.md`, and deletes the consumed fragments — including any `### None` exemptions, which are consumed but never emitted. Then move that section, plus anything still under `## [Unreleased]` from before #267, to the top of `CHANGELOG-archive/<year>.md` (newest first, under that file's `## Released` heading — create the file with an archive header if the year has none yet), leaving `## [Unreleased]` empty for the next cycle. The archive is historical record.

   **Re-baseline the ratchet in the same commit.** `tests/unit/test_changelog_rotation.py`'s `_ROOT_BYTE_BOUND` / `_ROOT_LINE_BOUND` are a may-not-grow ratchet, not a headroom budget, so the fold is the one step allowed to move them: run `wc -lc CHANGELOG.md` after rotating and set them to that measurement plus the same small allowance. This is a deliberate re-taking, like `_RELEASED_SENTINELS`. Include the rotation in the promotion below.
4. **Drive the promotion to `main`** via `/promote staging to main` (or `harness promote start/continue/pr --from staging --to main` directly) — the audited promotion lifecycle (ADR 0003), which gates the merge and opens the release PR rather than a hand-rolled `gh pr create`.

   The `staging → main` promotion *is* the release (`specs/architecture-principles.md`, D7; ADR 0003 amendment, #189/#190). Merge the opened PR before working the checklist below.

## Changelog fragments

A change records its changelog entry as its **own file**, `changelog.d/<ticket>.md`, and never by editing `CHANGELOG.md`. Two concurrent runs then write two different files and cannot conflict — before #267 every ticket appended to the same `## [Unreleased]` insertion point, which conflicted by construction on a file whose correct merge semantics are "keep both lines", and cost run `01KYR7T7B5E3QDC3WP7ZGYHTGV` two full rebase → gate → re-review → close rounds before going on to refuse a close on two further ticks.

1. **Write the fragment.** One file per change, named for its ticket — a GitHub issue number (`changelog.d/270.md`), or a legacy pre-cutover key (`changelog.d/CAL-1204.md`), which the format still accepts so historical ids stay writable. The filename is the primary key, so a resumed run overwrites rather than duplicating. The content is the entry exactly as it renders in `CHANGELOG.md` today, so nothing is reformatted at fold time:

   ```markdown
   ### Added — `harness stats`, the aggregate ledger reader (#265)
   - Breakdown item 5 of `verb-telemetry` (ADR 0009), and the last …
   ```

   The category is one of `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`. The ticket id in the heading must match the filename — a disagreement is a copy-pasted fragment, and `check` fails it. A body is required, and it may not contain an `## ` line: the fold owns H2, and an injected one would silently split the released section.

2. **When a change genuinely warrants no entry, say so in the same place.** Write `### None — <why no entry is warranted> (#<ticket>)`. The exemption is a file in the diff rather than a flag or a commit trailer, so the reviewer sees the claim and can disagree with it. The fold consumes it and emits nothing.

3. **The gate checks both shape and presence.** `scripts/verify.sh` runs `scripts/changelog_fragments.py check` (every fragment parses — structural, and meaningful wherever it runs) and `require` (this change carries a fragment or an exemption — a merge-base diff against `origin/<integration>`). `require` **abstains with a printed reason** rather than guessing where the base cannot resolve: a shallow `actions/checkout` fetch, a detached `promote` worktree, or HEAD being the integration branch itself.

4. **The ratchet is the half that holds everywhere.** Because `CHANGELOG.md` no longer accumulates, `tests/unit/test_changelog_rotation.py` enforces its size as **may-not-grow** rather than as headroom:

   | Bound | Value | Enforced by |
   |---|---|---|
   | Byte ratchet | 46,500 bytes | `test_root_changelog_is_byte_bounded` |
   | Line ratchet | 160 lines | `test_root_changelog_is_line_bounded` |

   An append to `[Unreleased]` trips these wherever the suite runs, including the environments where `require` abstains. That is why there are two guards rather than one: `require` is the direct check but is base-dependent, and the ratchet is base-independent but indirect. Neither subsumes the other.

   Measure with `wc -c CHANGELOG.md` and `wc -l CHANGELOG.md` if you need to see where the file sits. Only the release fold may move these constants, and it does so deliberately — see "Release notes + the `staging → main` promotion", step 3.

5. **The fold happens at release, not between releases.** There is no between-release fold any more, and nothing to fold: the root file does not grow. The pending window is `changelog.d/` itself, bounded by `test_unreleased_fragments_are_bounded` (too many fragments means a release is overdue) and `test_each_fragment_is_byte_bounded`.

**The per-entry budget.** The old fold ran on nine consecutive ticks without ever buying durable headroom, because entry *length* was the cause and the fold only ever treated the symptom: entries ran 2,000–3,000 bytes each against a window median nearer 600. A fragment should target **1,000 bytes and three lines**, and `test_each_fragment_is_byte_bounded` now enforces an outer limit rather than merely asking. Reasoning longer than that belongs in the change spec, the commit body, or the review record — where it already lives in full, and where nobody pays a context tax to skip it.

Prior art for the mechanism this replaced, kept because the reasoning still explains the bounds: `208118e` (CAL-1182) — the first-pass byte fold, condensing entry bodies. `c907faf` (2026-07-26) — the second-pass line collapse, after a byte fold took the file 47,674 → 42,825 bytes and two new entries then tripped the line ceiling at 251 against 250 with bytes still comfortable. Both passes are retired; #267 removed the accumulation that made them necessary.

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
