# ADR 0003 — Promotion is an audited harness lifecycle over a universal `dev → staging → main` topology

- **Status:** Accepted
- **Date:** 2026-07-16
- **Source:** proposal `specs/proposals/local-promotion-steward.md` (Option C); CAL-1112.

This records the promotion **design** before any `harness promote` mechanics exist. The CLI surface (CAL-1113), the ledger and JSON contracts (CAL-1114), the worktree/merge mechanics (CAL-1115), the gate evidence (CAL-1116), PR creation (CAL-1117), and escalation (CAL-1118) are implemented against this record — not decided in it. No CLI, no local-inference adapter, and no PR mechanics land with this ADR.

## Context

The harness shortens individual build runs, but moving completed work toward release is still manual or expensive: collect what changed, merge from the integration branch toward release, resolve the obvious conflicts, run the gate, write a PR summary, escalate the rest. Most of that is repetitive release mechanics — deterministic work that should not spend a premium interactive session per nightly promotion.

The repo already chose an always-on local loop as the default substrate for autonomous harness work ([ADR 0001](0001-cloud-runnable-harness-loop.md)), and the accepted `harness-as-tool` design already puts an external actor in the trigger/orchestrator slot while the harness remains the audited tool. Promotion must follow the same boundary rather than grow a parallel release bot with its own out-of-band git and PR state. What forces this record now: the P2 promotion implementation chain (CAL-1113–1118) cannot start without a durable branch policy and lifecycle to build against, and the branch topology in particular is a repo-wide policy change (`staging` becomes first-class) that the code and docs must agree on.

## Decision

**Promotion is a first-class, audited harness lifecycle** — the same shape as the build verbs (`start` → `review` → `close`), applied to release movement. An external orchestrator triggers it and may repair within a narrow policy; the harness owns every state transition and records it in a promotion ledger.

### Branch topology — universal `dev → staging → main`, `staging` first-class

- **`dev`** is moving integration: feature branches base from it and `close` merges them back into it.
- **`staging`** is the nightly **stabilized release candidate** — the new first-class branch this ADR adds. Promotion merges `dev` into a promotion candidate branched from `staging`, runs the gate on that candidate, and — only if it is green — advances `staging` to it. The merge happens on the candidate, never on `staging` itself: nothing lands on a target branch until the gate has passed on exactly what would land.
- **`main`** is intentional release: promotion opens a PR `staging → main`.

There is **no interim `dev → main` compatibility path**. The three-tier model is common, understandable, and safer for autonomous promotion. This is recorded as policy in `CONTEXT.md` (`branches:`); the branch-model *code* (`harness/cli/start.py`, `harness/cli/worktrees.py`) still hardcodes `dev`/`main`/`master` today — reading the model from `CONTEXT.md` is separate work (CAL-1106), so this ADR changes policy and docs only, with no runtime behaviour change.

### Lifecycle states

A promotion row moves through:

- **`opened`** — the promotion row, worktree, and promotion branch exist; the merge has been attempted.
- **`pr_ready`** — the merge was clean and the gate is green; the promotion may publish (land the staging hop, or open the release PR).
- **`agent_may_fix`** — a small, in-policy conflict or gate failure the orchestrator may repair once (see repair authority).
- **`needs_ticket`** — the block is real but out of local repair authority; it must become a human-owned Linear ticket.
- **`blocked`** — the promotion cannot proceed on infrastructure grounds (missing credentials, remote permission, unclean base) rather than on a code decision.
- **`promoted`** — terminal success on the **staging hop**: the target branch was advanced to the gated SHA. Nothing further is pending (amended 2026-07-17, below).
- **`pr_opened`** — terminal success on the **release hop**: the promotion branch is pushed and the PR is created.
- **`escalated`** — terminal non-success: a Linear ticket carries the evidence.
- **`cancelled`/`abandoned`** — the promotion was withdrawn or superseded; recorded, never deleted.

`pr_ready`, `agent_may_fix`, `needs_ticket`, and `blocked` are the **policy classifications** the harness returns from a merge+gate attempt; `promoted`, `pr_opened`, and `escalated` are the terminal paths. The two successes are distinct because the hops finish differently: `promoted` is *done*, while `pr_opened` still waits on a human. A promotion that opened no PR must not record `pr_opened` — the ledger is the audit trail, and it does not round off.

### Repair authority — one bounded attempt

The orchestrator may repair only small, low-semantic problems, and only **once** before the promotion must escalate:

- **Allowed:** docs / changelog / generated-summary / spec-prose conflicts; small source conflicts under a configured file/line threshold; obvious formatting or import-order gate failures.
- **Escalate instead of repair:** schema migrations; auth / payment / security / release / deployment scripts; package-lock conflicts unless a repo opts in; conflicts over the file threshold; a second gate failure after one bounded fix; missing credentials or remote-permission failures; ambiguous branch topology or an unclean base.

After a bounded edit the orchestrator calls `continue`, which re-runs classification and the gate and increments the attempt count. A promotion **cannot become `pr_ready` without fresh gate evidence** — the same evidence discipline the `review`/`close` gate already enforces (`code-quality`).

### PR authority — the harness creates the release PR; it never auto-merges

> **Amended 2026-07-17 (CAL-1158).** As first accepted, this section applied one rule to both hops: "Direct target-branch pushes and auto-merge are out of scope for v1." That over-applied a **release-hop** rule — its own stated rationale reached only as far as "merging the *release* PR stays a deliberate human/CI act" — and it foreclosed the nightly `dev → staging` automation this ADR exists to enable: a cron would gate the candidate, open a PR into staging, and stop, waiting for a human to merge a PR with no reviewer and no question to answer. The rule is now **scoped to the release hop**. The paragraph below is the amended decision.

**Staging is derived; main is decided.** That distinction sets where the authority sits:

- **The staging hop (`dev → staging`) direct-pushes on a green gate.** Nothing is judged there — the gate *is* the decision — so the harness advances `staging` to the gated SHA and opens no PR, and the promotion terminates at `promoted`. The push is bounded three ways: it happens **only** on a green gate (a red gate cannot reach `pr_ready`, so it cannot publish); it moves **exactly one ref**, via an explicit refspec naming the gated SHA; and the eligible target is a **structural allowlist of `staging` alone**, so the code cannot direct-push a release branch however it is called.
- **The release hop (`staging → main`) is PR-only, and never auto-merges.** The harness pushes **only the promotion branch** and creates the PR; a model or agent may draft the PR prose from deterministic facts (commit range, Linear IDs, changed specs, gate evidence), but the source facts are the harness's. Merging it stays a deliberate human/CI act — `main` is the single human decision point in the topology, and **auto-merge remains out of scope**.

Rejected: **PR + auto-merge on the staging hop.** It would need `gh pr merge` un-denied, repo auto-merge enabled, and auto-merge permitted through staging's protection — more moving parts, more standing authority, to produce a PR nobody reads.

The orchestrator's own limits are unchanged: it must not push target branches, open or close PRs outside the promotion command, mutate Linear promotion state, or mark a promotion done; those are lifecycle transitions and belong in the harness ledger. The staging push is the **harness's** authority, exercised inside the audited lifecycle — it is not a licence for the outer agent to touch a target branch.

### Escalation

When a block exceeds local repair authority, the harness files or updates a Linear ticket with the promotion id, source/target branches, conflict files, a bounded gate-output summary, and the branch/worktree to inspect — then marks the promotion `escalated`. Escalation is a first-class terminal path, not an error.

### The harness is agent-agnostic

The promotion surface is **agent-agnostic**: the harness returns deterministic facts, policy classifications, bounded evidence, and lifecycle state, and any outer orchestrator drives it — **Hermes**, **OpenClaw**, **Claude**, **Codex**, or a **human**. The harness surface does not depend on a local inference runtime (Ollama, MLX, MLC, llama.cpp, or an OpenAI-compatible endpoint); a model powers the outer agent, not the harness. Runtime choice is kept out of harness semantics so the same surface serves every orchestrator.

## Alternatives

- *Keep promotions human / Claude-driven* (proposal Option A) — a human or premium session merges, writes the PR, and resolves conflicts each time. Highest judgment, no new surface; but it keeps spending expensive attention on predictable mechanics and drifts per repo.
- *The outer agent owns the full promotion loop* (Option B) — the orchestrator directly runs git, tests, PRs, and tickets. Fastest to prototype; but it violates the harness boundary — the audit trail leaves the ledger and git/PR state is mutable out of band, reintroducing the routing problem `harness-as-tool` already solved for build runs.
- *Deterministic `harness promote` with no repair loop* (Option D) — one command either opens a PR or files a ticket. Simplest and safest; but it hands every easy conflict and trivial gate failure to a premium/human follow-up, capturing less of the toil savings.

Option C wins: promotion becomes an audited lifecycle the harness owns, with a narrow, escalation-first repair policy any orchestrator can drive.

## Consequences

- **Enables** the P2 implementation chain (CAL-1113–1118) to build against a fixed policy: the CLI surface, the ledger contract, merge mechanics, gate evidence, PR creation, and escalation each have a decided target.
- **Requires** `staging` as an operational branch — added to `CONTEXT.md` now, and honoured by the branch-model code once CAL-1106 reads the model from `CONTEXT.md`. Until then the release path in code is unchanged.
- **Constrains** the outer orchestrator to a narrow, escalation-first repair authority — a deliberate limit that keeps release safety enforceable and the ledger the single source of promotion truth.
- **Forecloses** an interim `dev → main` promotion path: the topology is three-tier from the start, so no compatibility shim is built and later removed.
- **Distinct from the build-run `close` gate:** `close` gates a ticket's integration into `dev`; promotion gates branch movement toward release. The two lifecycles must not be conflated — one must not weaken the other.
