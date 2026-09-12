# Migrating a consumer repo from the lock-file install to the plugin

For a repository that installed the guidance the pre-v5 way — copied
`commands/` / `skills/` / `agents/` / `hooks/` trees, a `.guidance-lock.yaml`
pinning their versions, a `CONTEXT.md`, and `/update-guidance` to pull updates.
That whole channel is retired (ADR 0017): the guidance now ships as native
Claude Code and Codex plugins with one version, and the repo owns only hydrated
files. Migration is per-repo, at your own pace — nothing breaks on the day the
source repo moves.

## The steps

1. **Install the plugin** (this repo is also its marketplace):

   ```
   /plugin marketplace add sluengen/harness
   /plugin install harness@harness
   ```

   Codex installs the same release:

   ```bash
   codex plugin marketplace add sluengen/harness
   codex plugin add harness@harness
   ```

2. **Hydrate:** run `/harness:hydrate` in Claude Code or ask Codex to hydrate
   Harness. It interviews for the repo's
   values (tracker, commands, branch roles, layers) — taking answers from the
   repo itself where it can, including your existing `CONTEXT.md` — and writes
   the repo-owned files: `harness.yaml`, the spine (`AGENTS.md`) and its
   `CLAUDE.md` derived from it, the path-scoped rules under `.claude/rules/`, Codex role
   adapters under `.codex/agents/`, the specs scaffold, the infrastructure
   record, and a `scripts/verify.sh` skeleton only if the repo has no gate yet.
   Existing host files are merged, not overwritten: the generated block is
   inserted above their content, which remains repo-owned. Hydration is
   working-tree only — you review and commit the result.

3. **Declare where the plugin comes from.** Installing it wrote the
   enablement into whichever settings scope you chose — the repo's own
   `.claude/settings.json` at project scope. The marketplace that
   `harness@harness` resolves through is registered per machine either way, so a
   colleague's fresh clone gets no commands and no enforcement hooks and is told
   nothing.
   `/harness:hydrate` writes the declaration for you — check it landed, and add it
   by hand in a repo hydrated before that step existed:

   ```json
   "extraKnownMarketplaces": {
     "harness": {
       "source": { "source": "github", "repo": "sluengen/harness" },
       "autoUpdate": true
     }
   }
   ```

   An entry already there without `autoUpdate` gains the flag the same way. A
   third-party marketplace defaults to `autoUpdate: false`, so a host that
   installed once stays on that version until somebody updates it by hand. With
   the flag, Claude Code refreshes the marketplace and updates its installed
   plugins in the background after startup, so a published `version` is what
   moves every host that has the plugin. It cannot install for a host that has
   none: `enabledPlugins` enables but never installs, and each contributor still
   runs the install command Claude Code prints.

   Commit it with the rest of the hydration. The spine's repo section carries the
   same fact in prose, for a host too old to read the key.

4. **Delete the old install, at your pace.** The copied guidance trees
   (`commands/`, `skills/`, `agents/`, `hooks/`, `templates/`, `process/`,
   `settings/` — whatever subset `.guidance-lock.yaml` lists as installed) and
   the lock file itself are dead weight once the plugin serves the same
   surface. They do not conflict with the plugin — they are just copies that
   will never update again — so this step can trail the others by weeks.
   Delete `.guidance-lock.yaml` last if you want the record of what was
   installed while you sweep.

5. **`CONTEXT.md` keeps working until you retire it.** One reader,
   `scripts/harness-config.js`, resolves the `branches:` block from the first
   source that declares it: `harness.yaml`, then `AGENTS.md`, `CLAUDE.md`, and
   legacy `CONTEXT.md` — so branch protection does not lapse mid-migration, and a
   repo that never migrates keeps working unchanged. Once `/harness:hydrate` has written a
   spine whose `branches:` block is right, `CONTEXT.md` is unread; fold
   anything repo-specific you still want into the spine's repo section and
   delete it.

6. **After future plugin updates:** run `/harness:hydrate` again, or ask Codex to
   hydrate — one invocation, no flag. It re-derives the spine's marked block, the
   `CLAUDE.md` copy and the plugin-marked Codex role adapters, and where a repo still
   carries its configuration in the spine's prose it interviews for the values and
   writes `harness.yaml`, leaving the stale fence for you to delete. There
   is no `/update-guidance` any more; the plugin manager owns updates.

## Version pinning

Per-file `guidance:` pins are gone. The plugin has one version; a repo that
needs to diverge from a skill forks that skill locally (a repo-local skill
shadows nothing — it is simply also present) rather than pinning a file.

## What a per-release section names

A section documenting one release names both halves: what the release takes out
of a consumer's tree, and what it puts in. Most of a release is guidance, which
lives in the plugin and never enters a consumer's tree, so the second half is the
one that gets left out. One set does enter it: `/harness:hydrate` rewrites the
plugin's Codex role adapters (`.codex/agents/*.toml`) on every run, so a release
that gains a role lands a new file in every consumer that hydrates, and a repo
pinning that set meets the addition as a red gate instead of as a line here.
That is what v11 did to `calibrate` (sluengen/harness#644).

Additions therefore get a row in the release's per-artefact table: the path, what
puts it there, and what a consumer who pins the set has to do. A release that
adds nothing says so.

## Retiring the vendored gate assets (2026-09-09, plugin v11)

**Delete this section once `calibrate` and `nano-erp` have both adopted.** It
describes a one-off transition between two plugin versions, not a standing
procedure; left standing after its subject is gone it becomes a note that
instructs a repo to remove files it never had.

ADR 0022 point 1 stops the plugin writing executables into a consumer:
`gate-marker.js`, `harness-config.js`, `scripts/package.json` and the
`verify.sh` skeleton. The rule is **ownership, not execution** — `verify.sh` is
disowned rather than removed, and remains the gate you run at landing.

**This retirement breaks nothing, and none of it is urgent.** A repo that does
nothing keeps a working gate: `verify.sh`'s public branch execs the local
`gate-marker.js`, which resolves `commands.verify`, spawns the internal branch
and runs the stages, writing a marker no surviving hook reads. The cost is a
redundant hop and some dead files, not a red gate. Simplify on your own
schedule.

**The release as a whole is not silent on your gate.** v11 also adds a file to
your tree, and a repo that pins its Codex adapter set goes red on it at the
first hydration. It is the last row of the table below.

The transition itself is the consumer's to perform. Paste the prompt below into
a session in the repo being adapted.

`````markdown
The harness plugin no longer writes or refreshes the gate helpers in this
repository (ADR 0022 point 1). Adapt this repo to own its gate outright.

Nothing here is urgent: the vendored chain still works, so stopping halfway
costs a redundant hop rather than a red gate. The one state to avoid is a
`verify.sh` that calls a file which has been deleted.

### 1. Find what is actually here, before changing anything

Placements differ between repos, and this one may have moved since this
prompt was written. Do not assume a path.

```bash
grep -rn "gate-marker\|harness-config\|HARNESS_GATE_MARKER_RUNNER" \
  --exclude-dir=.git --exclude-dir=node_modules .
```

Read every hit. Two things this turns up that a quick reading misses:

- **The helpers sit flat under `scripts/` in some repos and under a prefix
  such as `scripts/gate/` in others.** Take the paths from the grep.
- **There is usually more than one caller.** As well as the branch in
  `verify.sh` that execs `gate-marker.js run`, repos have carried a second
  `gate-marker.js preflight` call — either further down `verify.sh` on its
  internal branch, or as an npm script in `package.json` (`"gate:preflight"`)
  wired into the stage list. A changed-path classifier or file-type map may
  name the helpers as well, and the repo's own tests may pin them. Every one
  of those is a caller, and every one must go before the helper does.

### 2. What happens to each artefact

The verbs differ, and the last row arrives rather than leaves. Getting a
removal's verb wrong is what breaks a gate during this transition; the
arrival is what breaks one after it.

| Artefact | What happens | Why |
|---|---|---|
| `verify.sh` | **Stays. It is yours now.** Collapse the two branches into one: delete the public branch and the `HARNESS_GATE_MARKER_RUNNER` test, and run the stages directly. | It is still the gate you run at landing. It was never the marker's; it was only wired through it. |
| `gate-marker.js` | **Delete**, once nothing calls it. | Nothing reads its output. The hooks that did are gone. |
| `harness-config.js` | **Delete**, once nothing calls it. | Its only caller here was `gate-marker.js`. The plugin's own hooks resolve their copy from the plugin root, never from this repo, so deleting yours cannot affect them. Confirm with the grep first: you may have wired your own callers. |
| `package.json` beside the helpers | **Judge it.** Delete it if it exists only to pin `"type": "commonjs"` for the vendored pair — its own `"//"` comment usually says so. Keep it if it is the repo's own. | Some repos have one of each: a project `package.json` at the root, and a module-type pin next to the helper. The purpose decides, not the path. |
| `.git/harness/gate/` | **Remove at leisure.** Already gitignored. | Dead evidence files. |
| `.codex/agents/harness-audit.toml` | **New in v11. Expect it; do not delete it.** The next `/harness:hydrate` copies it in with the rest of the adapter set. If anything here pins that set — a test asserting the adapter roster, a lock list, a checked-in inventory — add this file to it before you gate. | v11 added a sixth role adapter. Hydration rewrites plugin-owned adapters on every run, so the set grows whenever the plugin gains a role. `calibrate` asserts set equality over that directory and went red on this file. |

### 3. The order, which is the part that can break a gate

**Edit first, gate, then delete.** A repo that deletes `gate-marker.js` while
something still calls it has a broken gate, and that is the one way this
transition breaks anything.

1. Rewrite `verify.sh` so it runs its stages directly, and remove every other
   caller the grep found — the trailing `preflight` block, the npm script, the
   classifier arm.
2. **Run the gate and read it.** Use whatever this repo declares at
   `commands.verify` in `harness.yaml`, which may not be `verify.sh` directly.
   Capture the exit code; never pipe it, because a pipe reports the exit status
   of the last command in the pipeline and will mask a red gate:

   ```bash
   <commands.verify> > /tmp/gate.log 2>&1; echo "EXIT=$?"
   ```

   Green means nothing calls the helpers any more.
3. Delete the helpers, and the module-type pin if step 2 judged it deletable.
   Re-run the grep to confirm no reference survives.
4. **Gate again** and read it. This is the run that licenses the change.

If the repo has tests pinning the vendored chain, they go red at step 3 and
are deleted with their subject in the same change, not before it.
`````

This repository ships the prompt and nothing else. It does not enter a
consumer, run the adaptation, or change any consumer's CI, branch protection
or billing.

## Edges from performed migrations

### From the first migration (nano-erp, 2026-08-18)

- **The lock list is not the complete inventory of the old install.** Generated
  droppings sit beside it unlisted — `.codex/` (compiled output of the old
  skills) being the observed case. Delete generated artifacts of the old
  install too: their inputs are leaving, so they can never regenerate, and a
  stale copy reads as live guidance to the tool that consumes it.
- **Delete before you hydrate.** The old `CLAUDE.md` is a *mirror copy* of the
  retired process doc, and `/harness:hydrate`'s merge rule would faithfully
  preserve it as "repo-owned" content. Deleting the lock-listed mirrors first
  gives `hydrate` a clean slate. This ordering is safe because `CONTEXT.md` is not
  lock-listed — it survives to seed the interview.
- **Check `.gitignore` for `.claude/hooks`.** An ignore rule carried for the
  old symlinked install will silently hide any real hook file the migration
  relocates there.
- **Diff your local hook fixes before deleting them.** A consumer that had
  patched its own copy loses the patch by migrating. The one gap this migration
  surfaced — the gate-evidence guard resolving the integration branch as a local
  ref only, so it was silently inert in single-branch/cloud clones — shipped as
  sluengen/harness#483 and is fixed in the plugin. Anything else your copy
  carries is not: diff it against the plugin's hooks before deleting, and
  upstream what the plugin lacks.
- **Tests that executed the old copied hooks** need re-pointing at the plugin
  cache (resolve via the plugin root, skip where absent) — and that skip costs
  CI coverage on runners without the plugin installed. Install the plugin on
  the runner to restore it.
- **Two old hooks have no plugin replacement** — `context-monitor.js` and
  `guidance-freshness.js` were retired, not moved. Their capabilities are
  deliberately gone; nothing to re-wire.
- **Snapshot directories are exempt from the reference sweep.** A vendored
  or verbatim-snapshot tree (another repo's docs, a frozen export) keeps its
  stale references; rewriting a snapshot corrupts it.
- **`paths.decisions` may point at a file.** A repo that records decisions in
  one document (e.g. its architecture-principles spec) points the path there
  rather than scaffolding an empty competing directory.

### From the second migration (calibrate, 2026-08-19)

- **A lock-listed tree can contain repo-owned files.** Before deleting a tree
  the lock names, diff its contents against the lock's file list — anything
  present that the lock does not list is the repo's own (custom commands, a
  session hook) and moves to a real location first. Re-verify any relocated
  hook's relative-path arithmetic and file-existence assumptions: a script
  written for a symlinked location breaks quietly when it becomes a real file
  two levels deep.
- **Sweep retired *names*, not just retired paths.** Three residue classes
  survive a path-based grep: free prose inside `.claude/settings.json`
  (permission/autoMode rationale citing a retired command), citations of
  retired *skill names* (`code-quality`, `test-driven-development`, … —
  derive the sweep list from the old lock's `skills/` entries minus the
  plugin's current roster), and a pathlib-style join
  (`ROOT / "commands" / "x.md"`) that contains no literal slash-path —
  search the moved *filenames* too.
- **Frozen decision records need a third category.** Banner-or-frozen is not
  enough: a bare "See CONTEXT.md" navigational pointer inside an otherwise
  historical ADR reads as live routing. Re-aim bare pointers even in frozen
  records, or banner the record.
- **Make the reconcile commit auditable.** When its message claims a class was
  fully re-aimed, put the grep command and residual count in the body — the
  second migration's one overclaim would have been self-catching.
- **End with an explicit CI decision.** Plugin-resolving tests skip on a
  runner without the plugin; that is by design, but the migration ends with a
  recorded choice — install the plugin on the runner, set the plugin-root
  override, or accept and ticket the coverage gap — not just a known-limits
  paragraph.
- **An existing record under another name beats a fresh seed.** A repo whose
  infrastructure reality already lives in a feature spec points at it rather
  than seeding a second file — same judgment as `paths.decisions`-as-file.
- **Capture the gate's exit code directly.** `verify.sh | tail` reports
  *tail's* status and masked a red, marker-less gate on the second migration.
  The idiom is `verify.sh > /tmp/gate.log 2>&1; echo EXIT=$?` then read the
  log — never a pipe. And gate the final run on a quiet machine: a contended
  run stacked a load-induced subprocess timeout on top of a genuine defect,
  and separating them cost five full gate runs.
- **The guards' fallback can mask an unreadable spine** in repos with
  conventional branch names, and the branches parser cannot read YAML flow
  mappings — upstream sluengen/harness#487; until it ships, write the
  `branches:` block in plain block form and consider an executing test that
  the guards read *this* repo's declaration (calibrate has the reference
  implementation, mutation-proven).

## Honest limits — what is untested

- The path above has run twice end-to-end (nano-erp, calibrate), each run
  audited independently. Later migrations should still expect repo-specific
  edges; report them as issues.
- The `CONTEXT.md` fallback in the hooks is covered by tests
  (`tests/unit/test_context_branch_parsing_contract.py`); the *interview*
  reading an existing `CONTEXT.md` for its answers is prose instruction to the
  agent, not tested code.
- The `CLAUDE.md` merge in `/harness:hydrate` preserves existing content by
  instruction; review the diff before committing, as with anything `hydrate`
  writes.
- Uninstall ordering is untested: the claim that stale copied trees are inert
  beside the plugin holds for skills/commands/agents (the plugin's are
  namespaced), but a repo whose `.claude/settings.json` still wires the old
  copied hooks will run *those* copies until that wiring is removed — check
  your settings file for hook paths pointing into the repo's own `hooks/`.
