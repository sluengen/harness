# The improvement ledger

An improvement is proposed, never filed (`review-discipline` → *bugs are filed; improvements are proposed*). The **improvement ledger** is where a proposal lands so it outlives the report that raised it: one standing issue per repo, holding every entry as a comment. `tracker` → *`ledger`* owns how it is found, opened and migrated from the pre-#547 `proposals-ledger` label; this file owns what goes in it and which ledger receives it.

**Entries accumulate as memory, not as promises.** Nothing in the ledger expires, nothing auto-drops, and no entry is owed a build; an entry is what the loop noticed, kept where the operator can find it. `/digest` reads it and surfaces what is new; `/assess` drains it, which is the only thing that clears an entry, and the drain marks every entry **done**, **folded** into a ticket, or **dropped** — dropped in writing, with its reason.

**An entry carries three things.** The one-line **case**; a **provenance** link to the ticket or session that raised it; and the **suggested home** — the file or surface a fix would land in.

## Which ledger — the repo's own, or the guidance source's

Two ledgers, and the entry's subject decides which one receives it. Get this wrong in the harmless direction and an improvement to the shared guidance dies in a repo that cannot act on it.

- **An improvement to this repo** — its code, its specs, its own configuration — goes to **this repo's** ledger.
- **An improvement to the guidance itself** — a skill that misdirects, a broken cross-reference, a workflow that does not behave as documented, real friction met while following it — goes to the **guidance source's** ledger. "Fix it at the source" is not actionable from a consuming repo, which has no push access; the ledger there is the channel, and without it the observation dies at the end of the session.

**Resolve the source repo; never write it down.** This guidance installs into every repo that adopts it, and a fork's feedback must reach *its* source rather than ours. The address is already declared where the plugin was installed from — read it, in this order, and take the first that resolves:

1. `.claude/settings.json` → `extraKnownMarketplaces.<name>.source` for the marketplace this plugin came from (`/harness:init` writes it, next to the enablement).
2. `.agents/plugins/marketplace.json` → the matching plugin's `source`, which is Codex's equivalent record.
3. The plugin root's own `.claude-plugin/plugin.json` `repository`, which is only present when you are working *in* the source repo.

A `source` of `{"source": "github", "repo": "<owner>/<name>"}` is the address; a `local` source means you are in the source repo, so rule 1 below applies. **If none of the three resolves, do not guess an owner** — say so and surface the entry to the operator; a hardcoded `sluengen/harness` in shipped guidance is the defect this rule exists to prevent, and it silently redirects every fork's feedback to us.

Two consequences worth stating:

1. **In the source repo, an entry about the guidance is just a local entry** — the resolved source is this repo. Fixing it at source is the resolution, not a substitute for recording it.
2. **Keep the entry about the guidance, not about the consumer's code.** The ledger you are writing to belongs to somebody else's repo, and it may be public. Name the skill, the workflow, and what it said; do not paste proprietary context to illustrate it. The same rule as never echoing a credential.
