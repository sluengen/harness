# Migrating a consumer repo from the lock-file install to the plugin

For a repository that installed the guidance the pre-v5 way — copied
`commands/` / `skills/` / `agents/` / `hooks/` trees, a `.guidance-lock.yaml`
pinning their versions, a `CONTEXT.md`, and `/update-guidance` to pull updates.
That whole channel is retired (ADR 0017): the guidance now ships as a Claude
Code plugin with one version, and the repo owns only a handful of hydrated
files. Migration is per-repo, at your own pace — nothing breaks on the day the
source repo moves.

## The steps

1. **Install the plugin** (this repo is also its marketplace):

   ```
   /plugin marketplace add sluengen/harness
   /plugin install harness@harness
   ```

2. **Hydrate:** run `/harness:init` in the repo. It interviews for the repo's
   values (tracker, commands, branch roles, layers) — taking answers from the
   repo itself where it can, including your existing `CONTEXT.md` — and writes
   the repo-owned files: the spine (`CLAUDE.md`), the specs scaffold, the
   infrastructure record, and a `scripts/verify.sh` skeleton only if the repo
   has no gate yet. **An existing `CLAUDE.md` is merged, not overwritten**: the
   generated block is inserted above your content, which becomes the repo-owned
   section. Hydration is working-tree only — you review and commit the result.

3. **Declare where the plugin comes from.** Installing it wrote the
   enablement into whichever settings scope you chose — the repo's own
   `.claude/settings.json` at project scope. The marketplace that
   `harness@harness` resolves through is registered per machine either way, so a
   colleague's fresh clone gets no commands and no enforcement hooks and is told
   nothing.
   `/harness:init` writes the declaration for you — check it landed, and add it
   by hand in a repo hydrated before that step existed:

   ```json
   "extraKnownMarketplaces": {
     "harness": { "source": { "source": "github", "repo": "sluengen/harness" } }
   }
   ```

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

5. **`CONTEXT.md` keeps working until you retire it.** The enforcement hooks
   read the spine's (`CLAUDE.md`) `branches:` block first and fall back to
   `CONTEXT.md` for a repo hydrated before the spine absorbed it — so branch
   protection does not lapse mid-migration. Once `/harness:init` has written a
   spine whose `branches:` block is right, `CONTEXT.md` is unread; fold
   anything repo-specific you still want into the spine's repo section and
   delete it.

6. **After future plugin updates:** `/harness:init --refresh` regenerates the
   spine's generated block between its markers and touches nothing else. There
   is no `/update-guidance` any more; the plugin manager owns updates.

## Version pinning

Per-file `guidance:` pins are gone. The plugin has one version; a repo that
needs to diverge from a skill forks that skill locally (a repo-local skill
shadows nothing — it is simply also present) rather than pinning a file.

## Edges from performed migrations

Learned from the first real consumer migration (nano-erp, 2026-08-18):

- **The lock list is not the complete inventory of the old install.** Generated
  droppings sit beside it unlisted — `.codex/` (compiled output of the old
  skills) being the observed case. Delete generated artifacts of the old
  install too: their inputs are leaving, so they can never regenerate, and a
  stale copy reads as live guidance to the tool that consumes it.
- **Delete before you hydrate.** The old `CLAUDE.md` is a *mirror copy* of the
  retired process doc, and `/harness:init`'s merge rule would faithfully
  preserve it as "repo-owned" content. Deleting the lock-listed mirrors first
  gives `init` a clean slate. This ordering is safe because `CONTEXT.md` is not
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

## Honest limits — what is untested

- The path above has now run once end-to-end (nano-erp). The second and later
  migrations should still expect repo-specific edges; report them as issues.
- The `CONTEXT.md` fallback in the hooks is covered by tests
  (`tests/unit/test_context_branch_parsing_contract.py`); the *interview*
  reading an existing `CONTEXT.md` for its answers is prose instruction to the
  agent, not tested code.
- The `CLAUDE.md` merge in `/harness:init` preserves existing content by
  instruction; review the diff before committing, as with anything `init`
  writes.
- Uninstall ordering is untested: the claim that stale copied trees are inert
  beside the plugin holds for skills/commands/agents (the plugin's are
  namespaced), but a repo whose `.claude/settings.json` still wires the old
  copied hooks will run *those* copies until that wiring is removed — check
  your settings file for hook paths pointing into the repo's own `hooks/`.
