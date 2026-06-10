<!-- guidance:build@1.2.0 -->
# /build — superseded in this repo

This repo's canonical end-to-end build process is **`/harness run <TICKET>`** — the agent-orchestrated verb loop (`start → implement → review → (fix → review)* → close`) documented in [`commands/harness.md`](harness.md). All git and tracker mutations route through the three harness verbs, so the run ledger stays the whole audit trail.

When a task does **not** fit that shape, use the agent-led backup flow: **`/start` → `/review` → `/ship`**.

The standalone `/build` worktree-and-review loop is **superseded here** — its process is replaced by `/harness run`. Do not use it in this repo.
