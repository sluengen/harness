---
proposal: node-gate-marker-refresh
status: accepted
date: 2026-08-21
related:
  - specs/decisions/0015-harness-v4-thin-verification-layer.md
  - specs/decisions/0017-harness-v5-plugin-shaped-guidance.md
  - specs/architecture-principles.md
---

# Proposal: Migrate the delivered gate-marker helper to Node

> Make `/harness:init --refresh` update every repo-owned Harness artifact in one pass, including migration from the delivered Python gate-marker helper to a buildless Node helper.

**Accepted 2026-08-21.** Implementation is tracked by [#500](https://github.com/sluengen/harness/issues/500) and [#501](https://github.com/sluengen/harness/issues/501).

## Problem / motivation

Harness's plugin hooks already run with Node. `hooks/hooks.json` starts every hook as `node ${CLAUDE_PLUGIN_ROOT}/hooks/<name>.js`, and `hooks/package.json` makes their CommonJS module type stable inside an ESM consumer repository.

The plugin nevertheless delivered a Python dependency to new repositories. On first setup, `/harness:init` copied the Python helper `gate_marker.py` into the consumer's `scripts/` directory and wired the consumer's verify command to run its `preflight` and `write` subcommands. A repository that had no Python otherwise acquired it solely for Harness's marker helper. **#500 has since landed**, so first-time init now delivers `scripts/gate-marker.js`; what follows describes the state at acceptance, and the refresh half is still open as #501.

`/harness:init --refresh` does not repair this. It replaces the generated spine block, merges the gate-ignore block, and adds a missing preflight, but it neither replaces the copied Python helper nor rewrites its verify invocations. A plugin update therefore has two incompatible outcomes: the plugin's hooks are current, while a consumer's repo-owned marker implementation remains on its original language and version.

The refresh command already owns changes to repo-owned Harness material. The marker helper and its two verify invocations belong in that same refresh set. Treating them as separate manual work makes upgrades incomplete by default.

## Options

**Option A — Keep delivering `gate_marker.py`.** Keep first-time init and refresh as they are. Consumers without Python install it for this helper, and existing copied helpers remain outside the update path. This preserves the current source file but leaves the delivery gap open.

**Option B — Deliver a Node helper only for new repositories.** Change first-time init to copy `gate-marker.js` but leave `--refresh` unchanged. New consumers avoid Python, but existing consumers keep an obsolete managed artifact. Two installation generations need separate guidance and tests.

**Option C — Deliver a buildless Node helper and migrate it through `--refresh`.** Package a canonical `gate-marker.js` template, make first-time init materialize it, and make refresh migrate the known Python helper and verify invocations in the same working-tree operation. Preserve a custom helper or custom invocation rather than guessing. This makes one Node runtime serve both installed hooks and the delivered helper, and gives existing consumers a safe upgrade path.

## Recommendation

Adopt Option C.

The plugin ships a canonical `scripts/gate-marker.js` asset, which `/harness:init` copies into a consuming repository's `scripts/gate-marker.js`. It is ordinary CommonJS JavaScript using Node's standard library. Node runs it directly; the consumer never installs TypeScript, an npm package, or a runtime transpiler.

Its command contract replaces the Python helper without changing the marker protocol:

| Command | Required behaviour |
|---|---|
| `node scripts/gate-marker.js preflight` | Refuse a Git-visible nested worktree before any expensive gate stage. |
| `node scripts/gate-marker.js write` | After every gate stage succeeds, write the marker for the current Git tree to the shared Git directory. |
| `node scripts/gate-marker.js tree` | Print the current working tree's tree object ID. |
| `node scripts/gate-marker.js path --tree <oid>` | Print the path where that tree's marker belongs. |

The marker file path, tree computation, freshness environment variable, and payload schema remain compatible with the existing hooks. The payload's writer identifier changes to identify the JavaScript writer. The hooks continue to treat the filename and freshness as the enforcement inputs; the payload remains diagnostics.

`/harness:init --refresh` becomes the one-shot prompt for the whole repo-owned Harness refresh set:

1. Replace only the generated block in `CLAUDE.md` and merge the existing gate-ignore block in `.gitignore`.
2. Materialize the current `scripts/gate-marker.js` from the plugin template.
3. Update Harness-managed verify wiring to run `node scripts/gate-marker.js preflight` before the first expensive stage and `node scripts/gate-marker.js write` as the final success-path command.
4. Remove the legacy Python helper `gate_marker.py` from the consumer's `scripts/` directory only when it is the recognized Harness-managed helper and no remaining tracked invocation references it. (The path is in the *consumer's* frame: this repo deleted its own copy in #500.)
5. Report each changed, retained, and skipped artifact. The command remains working-tree only: it creates no ticket, commit, or push.

The migration is deterministic for managed files. A custom marker helper, a modified managed helper, or a verify command whose invocation cannot be identified is not overwritten. Refresh writes the new JavaScript helper, leaves the custom path intact, and reports the precise file and invocation that need an operator decision. It must never silently leave a verify command pointing at a deleted Python file.

Plugin-provided commands, skills, agents, and hooks update when the plugin updates. `--refresh` applies the corresponding repo-owned changes in the same invocation: the spine, ignore block, marker helper, and verify wiring. It does not attempt to copy plugin prose into consumer-owned files or change the consumer's lint, typecheck, or test commands.

Harness dogfoods the same helper. Its own `scripts/verify.sh` changes to invoke `node scripts/gate-marker.js`; the Python writer is removed after the mutation instrument and tests no longer import it. Python remains the source repository's test and tooling language. This proposal moves the helper Harness delivers, rather than requiring a repository-wide language rewrite.

## Decisions — resolved

| Decision | Resolution | Recorded in |
|---|---|---|
| Runtime for the delivered marker helper | Node, through a buildless CommonJS script. | #500 records the decision in `specs/decisions/` and `specs/architecture-principles.md`. |
| Legacy helper eligible for automatic replacement | Only a recognized, unmodified Harness-managed Python helper. | #501 specifies the recognition rules and fixture tests. |
| Modified helper or unrecognized verify invocation | Preserve it and report the exact operator decision required. | #501 implements and tests this response. |

## Breakdown

1. **[#500](https://github.com/sluengen/harness/issues/500) — Ship the Node writer and prove the contract** — **Landed 2026-08-25 as `cc78cd4`**, with the runtime decision recorded in `specs/decisions/0018-gate-marker-convention-is-node.md`. Write failing contract tests first. Add the canonical `scripts/gate-marker.js` asset and migrate Harness's own gate to it. Execute the writer and both hook readers over clean and dirty linked-worktree fixtures; assert equal marker paths, tree IDs, freshness parsing, nested-worktree preflight, and successful marker discovery. Remove the Python writer only after its users are migrated.
2. **[#501](https://github.com/sluengen/harness/issues/501) — Deliver and migrate the helper through init and refresh** — Update first-time init to copy `scripts/gate-marker.js`, then extend `--refresh` to recognize the known Python helper, materialize the JavaScript replacement, rewrite only recognized Harness-managed verify invocations, and remove the legacy file only after the rewrite is complete. Fixture tests cover fresh installs, an unmodified legacy install, an already-migrated install, a modified helper, and a custom verify command. Reconcile the command, README, architecture record, and generated Codex surface in the same ticket.

## Risks / unknowns

- **Node is unavailable in a consumer environment.** The plugin's hooks already require it, so the migration does not add a new runtime dependency. `/harness:init` must report that precondition before writing a verify command that uses Node.
- **A custom gate is damaged by automatic text rewriting.** Refresh recognizes only managed invocations and preserves every other gate command. Fixture tests must prove both sides: a known legacy command migrates, and an unrecognized command is reported without modification.
- **The new writer drifts from the hooks.** The contract tests execute all three implementations against the same repositories. A payload comparison alone is insufficient because the enforcement readers rely on the path, tree, and freshness rules.
- **Partial updates leave stale guidance.** The delivery items land as one coherent feature: a plugin release that supplies the Node helper also teaches first-time init and refresh to install it, then updates every consumer-facing description of that operation.

---

**Lifecycle.** Accepted 2026-08-21; [#500](https://github.com/sluengen/harness/issues/500) landed 2026-08-25, [#501](https://github.com/sluengen/harness/issues/501) is open. The proposal becomes **shipped** when both have landed, or **superseded** if plugin packaging changes before implementation.
