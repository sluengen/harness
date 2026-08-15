# ADR 0015 — Harness v4: the runtime is retired; the harness becomes a thin verification layer

- **Status:** Accepted
- **Date:** 2026-08-15
- **Supersedes (in mechanism):** [ADR 0012](0012-persistent-runtime-host.md), [ADR 0013](0013-codex-engines-in-container.md) — their analyses stand as history; the subsystems they govern are retired.

## Context

The harness was built on a 2024 assumption: models need to be *driven* — an external orchestrator sequencing them through `start → review → close`, a Docker container isolating them, a ledger auditing every verb. Current frontier models falsified that assumption. They hold the whole lifecycle in context, drive sub-agents themselves, and get output faster without the machinery. The operator has stopped using the harness app; every tick since #217 has run agent-led `/build`.

The backlog measured this. On 2026-08-15 the repo had **61 open issues**. Categorised, they were: container/Codex-engine/runtime-host (15), test-and-guard debt on harness code (16), assurance-certification machinery (6), deployment/wrapper/doctor/CLI (6), spec/changelog ceremony (5), verb-loop/ledger/routine maintenance (4), promotion machinery (3), steward guidance-coherence machinery (3), the repo's own site (2), and **exactly one** user-facing capability request (#362, visual evidence for review). Not one ticket recorded the machinery catching a defect the agent-led flow would have missed. The backlog was the machinery maintaining itself, and each review of a machinery ticket filed further machinery tickets — the queue grew by construction.

What is *not* obsolete is the discipline the machinery happened to enforce. The ledger records four consecutive ticks where the reviewer's independently built mutation table caught survivors the builder's table missed; the vacuity catalogue (wiring-field survivors, prose-guard polarity, fail-open blacklists) names failure modes frontier models still exhibit. That discipline is the durable value.

## Decision

**The harness stops being a runtime and becomes a thin layer of things a model cannot fake: deterministic gates, enforcement hooks, and a small skill set carrying the review discipline. The model drives; the harness checks.**

### Retired

- The Docker container, the runtime host, and the Codex-in-container review engine.
- The harness CLI: the audited verb loop, the ledger, `serve`, `doctor`, the `~/bin/harness` wrapper, and the deployment machinery around them.
- The assurance-certification machinery (the `assurance:trivial` deterministic certifier and its policy surfaces).
- The promotion-chain machinery and the scheduled unattended-loop configurations (`/harness routine *`).
- The steward's guidance-coherence apparatus and the commit-derived changelog assembler.
- The spec-lifecycle ceremony beyond what a change actually needs.

### Kept and sharpened

- **Deterministic gates.** `scripts/verify.sh` and `scripts/mutate.py` — exit codes and mutation survivors are the artifacts a model cannot self-deceive about.
- **Enforcement moves to hooks.** Claude Code hooks replace the verb loop: a Stop hook that blocks a "done" claim unless the gate ran green this session; a PreToolUse hook guarding pushes to the default branch. Hooks fire mechanically; the audit trail is gate output plus git history, not a ledger.
- **A slim skill set.** Build (test-first, scope, the vacuity catalogue), review (fresh-context adversarial reviewer building its **own** mutation table), debug, ship — plus the backend-neutral `tracker` protocol, which earns its keep because consuming repos genuinely differ (Linear vs GitHub).
- **A versioned craft file.** The cross-session lesson ledger moves into the repo so it travels with the tool.

### Filing policy — the queue must shrink under review

- **Severity floor.** Critical and High block. Medium and Low get fixed in the same branch when small, or recorded in the review notes and dropped. **A Low is never filed as a ticket.** A Medium is filed only when it is genuinely separate work — different system, needs a design decision — and the reviewer states why it cannot be fixed in-branch.
- **Recursion cap.** A follow-up ticket filed from a review carries the `review-finding` label — that label marks generation one, and generation one is the last. **A review of a `review-finding` ticket files nothing below High.** One generation of follow-up, never a lineage.

### Hold labels — consolidated

`decision` merges into `input`. Two hold labels remain: **`input`** — the operator must supply something the run cannot (an answer, a judgment call, a credential, a fact); **`operator`** — the operator must be present at the keyboard (setup, hands-on, a visual check). Assignment to a human remains the load-bearing hold signal. Existing `decision` labels in consuming repos migrate on their next guidance update.

### Standing prompts become pointer commands

The unattended build-cycle prompt and the morning digest were running as large pasted prompts. Each becomes a small versioned command — `/routine` (discover the next ticket, build it, ship to the integration branch, hold on a red gate or conflict) and `/digest` (read-only morning report: holds needing input, overnight outcomes, work parked for a verdict, operator errands). `/routine` is deliberately **not** a mode of `/build`: `/build` builds one named ticket; `/routine` owns discovery, the standing branch authorisation, and the hold-don't-force rule.

### Delivery

The existing installer/`/update-guidance` mechanism is retained for now — it is proven cross-repo and works for Codex consumers. Packaging as a Claude Code plugin is the intended future shape once the v4 surface has settled; nothing in this ADR blocks or depends on it.

## Consequences

- **All 61 open issues close citing this ADR.** #362 alone is re-filed in the new shape (visual evidence as a capability of the review skill, carrying #361's measured narrowing: viewport-height slices per width, a documented max capture height). The four held `decision` tickets (#351, #364, #411, #416) become moot — each awaited a judgment about a subsystem this ADR retires.
- Lesson-bearing closures (#432 plan-mode-is-not-a-sandbox, #421 negation polarity, #420 fail-open blacklists, and the wider vacuity catalogue) are preserved in the craft file, not as tickets.
- The teardown itself is tracked as new, bounded work; success criterion for v4: a new repo adopts it in minutes, and the harness itself does not need a ticket for a month.
