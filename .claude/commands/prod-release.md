# Production Release

Create a staging → main release PR with version bump and customer-facing release notes.

## Instructions

### Step 1: Pre-flight checks

1. Ensure you're on `staging` and it's up to date: `git checkout staging && git pull`
2. Verify main is up to date: `git fetch origin main`
3. Check there are actual changes to release: `git log --oneline origin/main..staging --no-merges`
   - If no changes, stop: "Nothing to release — staging and main are in sync."
4. Verify CI is green on staging: check the latest commit status
5. Check for any tasks stuck in `in_progress` status in `manifest.yaml` — warn the user if releasing would ship incomplete work

### Step 2: Determine version

<!-- PROJECT: Adapt this step to your project's versioning strategy -->

Read the current version from your primary version source (e.g., `package.json`, `pyproject.toml`, or a `VERSION` file). This is the source of truth.

The version on staging is the version that will go live. If staging and main have the same version, bump staging now before proceeding:

- **Minor bump** (default): `0.1.0` → `0.2.0` — new features or significant changes
- **Patch bump**: `0.1.0` → `0.1.1` — only bug fixes, no new features

Use minor bump unless the user explicitly says "patch" or the changes are purely bug fixes.

### Step 3: Sync version files

Update all version files to match the primary version source. If any versions were bumped in this step, commit:

```
chore: bump version to {version}
```

Push to staging before creating the PR.

### Step 4: Generate release notes

Scan commits between main and staging:

```bash
git log --oneline origin/main..staging --no-merges
```

**Filter out noise.** Ignore:
- `manifest:` commits (pipeline bookkeeping)
- `review(` commits (internal review reports)
- `docs:` commits that are specs/designs (internal)
- Merge commits

**Group the remaining commits into categories:**

1. **New** — `feat(` commits → customer-facing features
2. **Improved** — `fix(` and `refactor(` commits → improvements and bug fixes
3. **Under the hood** — `chore(`, `test(` commits → brief one-liner, not itemized

For each feature/fix, write a **customer-facing summary** — what the user gets, not what the code does:
- Bad: "Added useRatioLock hook with bi-directional picker coupling"
- Good: "Lock your brew ratio — tap the ratio display, set your target, and dose/water stay coupled as you adjust"

**Release notes format:**

```markdown
## {Project} v{version}

{One sentence hook — the headline change in this release.}

### New

- {Feature description — benefit-led, plain language}

### Improved

- {Fix/improvement description}

### Under the hood

{One sentence summary of internal improvements, e.g. "Code cleanup, test coverage improvements, and CI automation."}
```

Omit empty sections. If everything is "under the hood", say so — don't force features that aren't there.

### Step 5: Create the release PR

```bash
gh pr create --base main --head staging --title "Release v{version}" --body "$(cat <<'EOF'
{release notes from Step 4}

---

## Pre-merge checklist

- [ ] Release notes reviewed
- [ ] Version number correct (v{version})
- [ ] CI green on staging
- [ ] No incomplete tasks shipping

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

### Step 6: Bump staging to next version

After the PR is created, immediately bump staging to the next minor version for the next development cycle:

```
{version} → {next_minor}
```

For example: if releasing `0.2.0`, bump staging to `0.3.0`.

Update all version files and commit:

```
chore: bump version to {next_minor} for next release cycle
```

Push to staging. This means staging is always one version ahead of main (production).

### Step 7: Save release notes

Write the release notes (from Step 4) to `releases/v{version}.md` so they accumulate and can be reused for changelogs, marketing updates, or in-app "what's new" prompts.

Commit: `docs: release notes for v{version}`

### Step 8: Report

```
## Release v{version}

PR: {PR URL}
Releasing: {count} changes ({features} features, {fixes} fixes)
Next dev version: v{next_minor}

Approve and merge the PR when ready — that's all you need to do.
```

## Version strategy

- One file is the version source of truth (define in project CLAUDE.md)
- All other version files mirror it
- Staging is always the "next" version (one minor ahead of main)
- Main is always the "live" version
- No pre-release suffixes — just clean semver
