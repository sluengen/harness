<!-- guidance:build-codex@1.2.0 -->
# /build-codex — superseded in this repo

This repo's canonical end-to-end build process is **`/harness run <TICKET>`** — the agent-orchestrated verb loop (`start → implement → review → (fix → review)* → close`) documented in [`commands/harness.md`](harness.md). The `harness review` verb already runs the Codex review against the worktree HEAD, so the separate `/build-codex` loop is redundant here. All git and tracker mutations route through the three harness verbs, keeping the run ledger as the whole audit trail.

When a task does **not** fit that shape, use the agent-led backup flow: **`/start` → `/review` → `/ship`**.

The standalone `/build-codex` worktree-and-review loop is **superseded here** — its process is replaced by `/harness run`. Do not use it in this repo.
