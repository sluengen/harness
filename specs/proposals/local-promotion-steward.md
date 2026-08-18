---
proposal: local-promotion-steward
status: superseded         # draft | under-decision | accepted | shipped | rejected | split
date: 2026-07-16
related: [harness-as-tool, harden-loop-layer, run-ledger, verb-model, cli-surface, specs/decisions/0001-cloud-runnable-harness-loop.md]
---

# Proposal: Local promotion steward

***Superseded 2026-08-15** by [ADR 0015](../decisions/0015-harness-v4-thin-verification-layer.md) — the `harness promote` verbs, the promotion ledger rows and the escalation events this proposes went with the runtime. **Read this as a dead mechanism, not a dead goal:** the outcome arrived by other means and is live — `scripts/promotion-step.sh` carries the deterministic step, the `/promote` command drives `dev` → `staging` → `main` with plain git, and ADR 0003's branch topology and its nightly automation are untouched. Kept for the audit; nothing below describes the machinery in use.*

> Add a first-class promotion lifecycle to the harness so any orchestrator can cheaply move completed work from `dev` to `staging` to `main` while the harness owns git, ledger, gate, PR, and escalation state.

## Problem / motivation

The harness shortens individual build runs, but release movement is still too manual or too expensive. A routine human or Claude/Codex session has to collect completed work, understand what changed, merge from the integration branch toward release, resolve obvious conflicts, run the gate, write a PR summary, and keep related repos aligned through guidance updates. That is important work, but much of it is repetitive release mechanics rather than high-judgment implementation.

Using the Claude app or Codex for every nightly promotion wastes premium model tokens on work that should mostly be deterministic: fetch, compare branches, create a worktree, attempt a merge, run `scripts/verify.sh`, push a PR branch, and file a ticket when the machine cannot proceed. The repo already chose an always-on local loop as the default substrate for autonomous harness work (ADR 0001), and the accepted `harness-as-tool` design already says an external actor occupies the trigger/orchestrator slot while the harness remains the audited tool. Promotion should follow the same boundary instead of creating a parallel release bot.

The desired outcome is not a clever local agent that owns releases. It is a boring, auditable harness lifecycle that removes cheap toil, can be driven by Hermes/OpenClaw/Claude/Codex/a human, and escalates whenever a real decision is needed.

## Options

**Option A — Keep promotions human / Claude-driven.** A human or premium model session periodically merges `dev` to `main` (or `dev` to `staging`), writes the PR, resolves conflicts, and updates guidance across repos. Trade-offs: highest judgment and flexibility; no new harness surface. But it keeps spending expensive interactive attention and premium tokens on predictable mechanics, and the process can drift per repo.

**Option B — The outer agent owns the full promotion loop.** Hermes, OpenClaw, Claude, Codex, or a human directly performs git operations, resolves conflicts, runs tests, pushes branches, opens PRs, and files tickets. Trade-offs: fastest to prototype and maximally flexible. But it violates the harness boundary: the audit trail is outside the ledger, git/PR state can be mutated out of band, and the same routing problem `harness-as-tool` solved for build runs reappears for releases.

**Option C — Harness owns promotion verbs; any orchestrator repairs within policy. (Recommended.)** An external orchestrator calls a harness promotion surface. The harness creates a promotion ledger row, worktree, promotion branch, merge attempt, gate run, PR metadata, and escalation events. The orchestrator reads structured JSON, optionally uses a model for PR summaries and bounded repairs when the harness policy permits, then calls back into the harness to continue. Trade-offs: more harness work than Option B, and promotion needs a first-class ledger model. In exchange, state transitions stay auditable, release safety is enforceable, and the outer actor remains the trigger/orchestrator rather than a second source of truth.

**Option D — Add only a deterministic `harness promote` command with no agent repair loop.** A scheduled shell task runs one command that either opens a PR or files an escalation ticket. Trade-offs: simplest and safest. But it leaves easy conflicts and trivial gate failures for a premium-model/human follow-up, so it captures less of the token-saving opportunity.

## Recommendation

Adopt **Option C**: build promotion as a new audited harness lifecycle. Hermes is the likely cheap local driver, but the harness design must be agent-agnostic: the same surface should work for Hermes, OpenClaw, Claude, Codex, or a human.

The shape mirrors the existing verb model:

```text
orchestrator
  -> harness promote start --repo <repo> --from dev --to staging
      -> promotion ledger row, worktree, branch, merge attempt, policy result
  -> orchestrator may repair only when policy says "agent_may_fix"
      -> edit bounded conflicts or small gate failures
      -> harness promote continue --promotion-id <id>
  -> harness promote pr / escalate
      -> gate evidence, PR creation, or Linear ticket
```

For branch topology, use **`dev -> staging -> main`** universally:

- `dev` is moving integration and may contain fresh or WIP-adjacent work.
- `staging` is the nightly stabilized candidate branch.
- `main` is intentional release.

There is no interim `dev -> main` compatibility path in this proposal. The three-tier model is common, understandable, and safer for autonomous promotion. Accepting the proposal means updating repo branch policy so `staging` becomes first-class.

The local inference layer is explicitly **not** harness design. A local model may power Hermes or another outer agent, but the harness surface does not depend on Ollama, MLX, MLC, BaseRT, llama.cpp, or an OpenAI-compatible endpoint. The harness returns deterministic facts, policy classifications, bounded evidence, and lifecycle state. The outer actor decides how to use any model. If the existing `review` verb later wants a local OpenAI-compatible engine, that is a separate review-engine proposal, not part of promotion.

### Promotion authority model

The harness, not Hermes, owns:

- promotion row creation and lifecycle state
- source / target / promotion branch naming
- worktree creation and cleanup
- merge attempt and abort handling
- gate invocation and evidence capture
- PR branch push and PR creation
- Linear escalation ticket creation
- policy classification: `clean`, `agent_may_fix`, `needs_ticket`, `blocked`

The outer orchestrator owns:

- cron / schedule
- repo selection
- optional model invocation
- PR prose draft when requested by harness, or human-authored prose
- bounded edits when the policy permits them
- calling `promote continue` after an edit
- notifying the human when harness escalates

The orchestrator must not directly push release branches, open/close PRs outside the harness promotion command, mutate Linear promotion state, or mark a promotion done. Those are promotion lifecycle state transitions and belong in the harness ledger.

### Bounded repair policy

The promotion loop should explicitly permit only small, low-semantic repairs:

- docs, changelog, generated summary, or spec prose conflicts
- small source conflicts under a configured file/line threshold
- obvious formatting or import-order failures
- small lockfile-free dependency metadata conflicts only when the gate proves the result

It should escalate instead of repair when it sees:

- schema migrations
- auth, payment, security, release, or deployment scripts
- package lock conflicts unless a repo explicitly opts in
- conflicts across more than the configured file threshold
- repeated gate failure after one bounded fix attempt
- missing credentials or remote permission failures
- ambiguous branch topology or unclean base state

Escalation means filing or updating a Linear ticket with the promotion id, source/target branches, conflict files, gate output summary, and the branch/worktree to inspect.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| **D1 — Branch topology.** | **Resolved:** `dev -> staging -> main` is universal and first-class; no `dev -> main` interim compatibility path. | `CONTEXT.md`, branch model docs, promotion feature spec |
| **D2 — Promotion surface MVP.** | **Resolved:** use a `harness promote` subcommand group with the smallest lifecycle surface that maps to real pause points: `start`, `continue`, `status`, `pr`, and `escalate`. Do not add a separate `verify` command in v1 unless implementation evidence shows `start`/`continue` cannot cleanly own gate execution. | `cli-surface` and promotion feature spec |
| **D3 — Inference adapter.** | **Resolved:** out of scope for harness promotion. The model powers the outer agent, not the harness; any local review-engine adapter is a separate proposal. | outer-agent runbook / future review-engine proposal if needed |
| **D4 — Auto-repair authority.** | **Resolved for v1:** one bounded repair attempt; docs/spec/changelog, formatting/imports, and small source conflicts only; no lockfiles, migrations, auth/security/payment/release scripts, or second gate failure. | promotion policy config and tests |
| **D5 — PR creation authority.** | **Resolved:** harness pushes the promotion branch and creates the PR; model/agent may only draft content from deterministic facts. | promotion feature spec |
| **D6 — Cross-repo guidance update.** | **Resolved:** separate scheduled jobs per repo, sequenced by the scheduler/orchestrator rather than one complex fleet-wide harness operation. | guidance/update runbook or separate proposal |

### Resolved 2026-07-16 — D2 MVP surface

The promotion surface should follow the current harness pattern: add verbs only where the orchestrator needs a stable pause/resume boundary, not for every internal step. The build lifecycle needed `start`, `review`, `close`, plus later `checkpoint` because implementation and review are long, context-bearing phases. Promotion is narrower: merge classification and gate execution are deterministic harness work; the outer actor only needs a chance to repair after the harness returns a policy state.

MVP command set:

```bash
harness promote start --repo . --from dev --to staging
harness promote continue --promotion-id <id> --repo .
harness promote status --promotion-id <id> --json
harness promote pr --promotion-id <id>
harness promote escalate --promotion-id <id>
```

- **`start`** opens the promotion row, creates the worktree/branch, attempts the merge, runs the gate when the merge is clean, and returns a structured state: `pr_ready`, `agent_may_fix`, `needs_ticket`, or `blocked`.
- **`continue`** is the only repair/resume entrypoint. After the orchestrator makes a bounded edit, it re-runs classification and the gate, records the attempt count, and returns the next structured state.
- **`status`** is read-only inspection for humans and agents.
- **`pr`** is the success terminal path: it pushes the promotion branch, creates the PR, records the PR URL, and marks the promotion `pr_opened`.
- **`escalate`** is the non-success terminal path: it files or updates the Linear ticket with promotion evidence and marks the promotion `escalated`.

No separate `verify` command in v1. Gate execution is part of `start` and `continue` because the gate is not a human/agent decision boundary; it is deterministic evidence the harness needs before `pr`. If a later implementation discovers a real reuse case, `verify` can be added as an interface change with tests and docs.

## Breakdown

1. **Promotion design record and branch policy.** Record the universal `dev -> staging -> main` branch topology, lifecycle states, repair policy, and escalation rules. Update `CONTEXT.md` so `staging` is first-class.
2. **Promotion MVP surface.** Add the `harness promote` subcommand group with `start`, `continue`, `status`, `pr`, and `escalate`. Keep gate execution inside `start`/`continue`; do not add a separate `verify` command in v1.
3. **Promotion ledger and CLI contract.** Add a promotion lifecycle model to the ledger or a sibling table, plus a locked CLI JSON contract for the v1 subcommands. The contract must expose structured states for clean merge, conflict, gate failure, PR-ready, escalated, and complete.
4. **Promotion worktree and merge mechanics.** Implement deterministic fetch, worktree creation, source/target validation, promotion branch naming, merge attempt, merge abort, cleanup, and resume by promotion id. Test conflict and non-conflict paths first.
5. **Gate and evidence capture.** Run the repo's configured verify command, capture bounded output, classify failures, and make every measurable threshold a measuring test. A promotion cannot become PR-ready without fresh gate evidence.
6. **PR summary and PR creation.** Generate a structured change summary from commit range, Linear IDs, changed specs, and gate evidence. Let an outer agent/model draft prose if available, but keep the source facts deterministic. Push the promotion branch and create the PR through the harness.
7. **Escalation ticket path.** File or update a Linear ticket when conflicts, gate failures, size limits, credentials, or policy blockers exceed local repair authority. Include promotion id, branch names, conflict files, gate summary, and next human action.
8. **Outer-agent routine guidance.** Document how Hermes or any other agent/human should drive the promotion lifecycle on a schedule: select repo, call the harness promotion surface, optionally repair within policy, and stop on harness escalation.
9. **Guidance update scheduling.** Document separate per-repo update-guidance cron jobs that fire in sequence. Each job should use that repo's own promotion path and escalate independently.

## Risks / unknowns

- **Local model quality is variable.** A 7B-14B local model is appropriate for summaries and bounded repairs, not unbounded release judgment. The policy must keep authority narrow and force escalation on semantic conflicts.
- **Agent/runtime choice may drift quickly.** Hermes, OpenClaw, Claude, Codex, and humans should all be able to use the same harness surface. Keep runtime details out of harness semantics.
- **Promotion can become a second close gate if not designed carefully.** Build-run `close` gates ticket integration into `dev`; promotion gates branch movement toward release. The specs must distinguish those lifecycles so one does not weaken the other.
- **Staging adds operational clarity but branch overhead.** A new staging branch reduces release risk for autonomous promotion, but it also adds branch management, CI, and repo convention work.
- **PR summaries can hallucinate if model-led.** The local model should draft prose from deterministic facts, not invent content from raw diff context alone. Commit list, Linear IDs, spec changes, and gate evidence are the source of truth.
- **Cross-repo guidance updates can create cascade failures.** Separate per-repo cron jobs reduce one-shot orchestration complexity, but sequencing and failure policy still need a runbook: one repo failure should file a ticket and continue/stop according to policy, not wedge the whole chain silently.
- **Credential and permission failures are likely early.** Local cron, git push auth, GitHub PR creation, Linear tickets, and local model serving each have separate credentials. V1 should make missing auth a structured `blocked` result, not a generic failure.

---

**Lifecycle.** Accepted 2026-07-16. D1-D6 resolved: `dev -> staging -> main` is universal; the promotion MVP surface is `start`, `continue`, `status`, `pr`, `escalate`; local inference is out of scope for harness promotion; repair is one bounded attempt; harness creates PRs by pushing only promotion branches; guidance updates are separate sequenced per-repo jobs.

Spawned implementation issues:

- 1 → CAL-1112
- 2 → CAL-1113
- 3 → CAL-1114
- 4 → CAL-1115
- 5 → CAL-1116
- 6 → CAL-1117
- 7 → CAL-1118
- 8 → CAL-1119
- 9 → CAL-1120
