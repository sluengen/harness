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

3. **Delete the old install, at your pace.** The copied guidance trees
   (`commands/`, `skills/`, `agents/`, `hooks/`, `templates/`, `process/`,
   `settings/` — whatever subset `.guidance-lock.yaml` lists as installed) and
   the lock file itself are dead weight once the plugin serves the same
   surface. They do not conflict with the plugin — they are just copies that
   will never update again — so this step can trail the others by weeks.
   Delete `.guidance-lock.yaml` last if you want the record of what was
   installed while you sweep.

4. **`CONTEXT.md` keeps working until you retire it.** The enforcement hooks
   read the spine's (`CLAUDE.md`) `branches:` block first and fall back to
   `CONTEXT.md` for a repo hydrated before the spine absorbed it — so branch
   protection does not lapse mid-migration. Once `/harness:init` has written a
   spine whose `branches:` block is right, `CONTEXT.md` is unread; fold
   anything repo-specific you still want into the spine's repo section and
   delete it.

5. **After future plugin updates:** `/harness:init --refresh` regenerates the
   spine's generated block between its markers and touches nothing else. There
   is no `/update-guidance` any more; the plugin manager owns updates.

## Version pinning

Per-file `guidance:` pins are gone. The plugin has one version; a repo that
needs to diverge from a skill forks that skill locally (a repo-local skill
shadows nothing — it is simply also present) rather than pinning a file.

## Honest limits — what is untested

This path is written from the mechanisms, not from a performed migration:

- **No real consumer repo has run this migration yet.** The source repo
  dogfoods the plugin surface, but it was never a lock-file consumer of
  itself. Expect edges, and report them as issues.
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
