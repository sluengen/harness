---
proposal: ground-specs-and-context-rollover
status: shipped          # draft | under-decision | accepted | shipped | rejected | split
date: 2026-06-30
related: [harden-loop-layer, spec-driven-development, spec-authoring, four-loops, CAL-922, CAL-923]
---

# Proposal: Ground every change spec in current reality; graceful context rollover

> An assessment of DoorDash's *long-running agents* write-up found it overwhelmingly confirmatory — it independently converged on the harness's architecture (deterministic verbs over single-purpose sessions; fresh-context reviewer; worktrees; progress-file memory; crash recovery) and retired the same AI-manages-AI anti-pattern we did. Two patterns in it are genuinely additive. **WS-A (primary):** an explicit **grounding** step before the change spec is written, so specs are built on *current* system reality rather than stale recalled facts. **WS-B (also adopted, built in parallel):** a proactive **context rollover** — a build that nears its context limit hands off to a fresh session that continues the same ticket, rather than only recovering after a crash.

## Problem / motivation

**WS-A — specs are authored from memory, not from the system as it is now.** The flow in `spec-driven-development` goes straight from "open the Linear issue" (step 1) to "write the change spec" (step 2): there is no step that grounds the spec in the current codebase. `spec-authoring` rightly insists on **design** and on holding "no unresolved decision presented as settled" — but nothing requires the author to *verify* that the facts the spec rests on are still true. The memory subsystem already carries the right instinct — *"recalled memories reflect what was true when written; if one names a file, function, or flag, verify it still exists before recommending it"* — but that rule lives in the memory layer, not the build flow, so it never fires at the moment a spec is being written.

The observed failure (Scott, 2026-06-30): **reactive agents assert stale facts pulled from memory or system-reminders** — facts they would catch as wrong simply by looking at the current code — and write them into change specs. The spec reads plausible, the build starts, and then reality bites mid-build: the named file moved, the flag was renamed, the decision was already superseded. The ticket reverts to blocked, a loop iteration is wasted, and the decision that should have been caught at creation time is now being made "fastest and worst" mid-build (exactly what `spec-authoring` warns design exists to prevent). A grounding step turns those late, expensive discoveries into early, cheap ones — tighter specs, decisions surfaced at creation time, fewer blocked reverts.

There is a ready structural precedent: the **Watchlist trigger** is already a conditional, pre-spec, *code-inspecting* check whose result is recorded in the change spec. Grounding is the same shape, generalized.

**WS-B — a long build has no graceful exit from a full context window.** Today a build that approaches the context limit has only two paths: manual `harness checkpoint` + `harness start --resume`, or — if the session actually dies — the death-keyed stale-run reclamation. There is no *proactive, graceful* handoff: an agent that senses it is running out of room cannot cleanly checkpoint and spawn a fresh session that continues the **same** ticket mid-task. DoorDash does exactly this (emit `AGENT_LOOP_STATUS: RETRY`; a fresh session inherits the progress file and resumes). We hold every building block — `checkpoint`, `start --resume`, the `reclaim_marker` writer/reader contract — but not the proactive trigger or the within-ticket continuation. This is low-urgency under our small-ticket discipline; it matters when one build legitimately spans multiple context windows.

## Options

**WS-A — where does grounding live?**
- **A1 — A grounding step in the flow + a recorded `Grounding` section in the change spec.** Add a grounding step to `spec-driven-development` (before the change spec is written); put the craft in `spec-authoring` (investigate current reality; verify every fact the spec will rest on that names a file / function / flag / version / decision against the actual code; record what was found and surface any decision now); add a conditional **`Grounding`** section to `templates/change.md`, mirroring the Watchlist-trigger pattern. · *Trade-offs:* small; reuses an existing structural precedent; operationalizes the memory verify-before-assert rule at the exact moment it bites; the recorded artifact makes grounding auditable and pulls decisions forward. Costs a little up-front per ticket — kept proportionate by the template's "scaled to size" rule (a one-line fix gets a one-line grounding).
- **A2 — A separate research artifact/phase (DoorDash-style isolated research doc).** · *Trade-offs:* closest to the source; strongest isolation of research from planning. But a new artifact type is heavier than the harness's lean record set (proposal / change / feature); the change spec already *is* the plan artifact. Over-built for our scale.
- **A3 — Guidance-only nudge.** Strengthen "read the as-built record" prose without a recorded section or guard. · *Trade-offs:* cheapest, but no artifact and no enforcement — which is precisely why today's weak guidance gets skipped. Does not change behaviour.

**WS-B — how to roll over a full context window?**
- **B1 — A handoff protocol composing the existing verbs.** When a build nears its context budget, it checkpoints WIP and writes a progress/handoff marker (reuse / extend `reclaim_marker`); a fresh session resumes the **same** ticket from it via `start --resume`. Mostly a documented trigger + convention; no new machinery. · *Trade-offs:* reuses `checkpoint`/`resume`; cleanly distinguishes a *proactive* handoff (alive, near-limit) from *death-keyed* reclamation. Lower urgency.
- **B2 — A new sentinel/verb baked into the loop** (an `AGENT_LOOP_STATUS`-style emit). · *Trade-offs:* more automatic, but new machinery for a need that is presently rare. Premature.

## Recommendation

- **WS-A → A1 (primary).** It is the smallest change that fixes the observed failure, it reuses the Watchlist-trigger precedent rather than inventing a shape, and it operationalizes a rule the system already believes (verify recalled facts) at the one moment it pays off — spec creation. The recorded `Grounding` section is what converts "I think X" into "X, verified against `path:line` today," and it is where a decision that would otherwise surface mid-build gets caught.
- **WS-B → B1, build now alongside WS-A (decided).** Compose `checkpoint` + `start --resume` + a `reclaim_marker` extension into a proactive handoff; do not build the sentinel machinery (B2) up front. Independent of WS-A — no blocking relation; the two ship in parallel.

Both trace to `engineering-principles`: smallest change that fixes the real failure (A1, B1), no premature abstraction (skip A2/B2), reuse existing seams (Watchlist precedent; checkpoint/resume/reclaim_marker).

### Resolved 2026-06-30 — all three closed, no open decisions remain

- **D1 → recorded section + guard.** A conditional `Grounding` section in the change spec plus a guard test that the skills/template carry the rule — not guidance-only prose, which is the status quo that already gets skipped.
- **D2 → concrete named facts only.** The verify rule is scoped to facts that name a **file / function / flag / version / decision** — the checkable, staleness-prone ones — keeping grounding proportionate rather than turning every spec into a research essay.
- **D3 → build WS-B now, alongside WS-A.** Not deferred. The two are independent (grounding guidance vs context-rollover protocol); they ship in parallel with no blocking relation.

### WS-A delivery revised 2026-06-30 — research subagent (primary), inline fallback

The accepted WS-A recommendation was **A1** (inline self-grounding by the executor). On further design discussion the *delivery mechanism* was re-scoped toward **A2**: the agent-led `/start` flow dispatches a read-only **`researcher` agent** that investigates current reality in its own context and returns a distilled **grounding brief** to the executing agent alongside the change spec. Rationale — the *double whammy*: the executor's context is saved (only the brief enters its window, not the raw investigation) and a dedicated read-only pass grounds deeper, free of build-narrative momentum (DoorDash's isolated research phase; the same pattern as the Explore subagent). Inline self-grounding (the original A1 rule) is **retained as the fallback** where no sub-agent host is available, so grounding always happens.

The grounding **contract is unchanged** (D1/D2 still hold): verify facts naming a file / function / flag / version / decision against current code, recorded artifact + guard — the brief *is* the recorded Grounding artifact. The deterministic `start` CLI verb is **not** modified (it stays deterministic); dispatch lives in the agent-led flow. An extra agent per ticket interacts with the spend breakers (`harden-loop-layer` WS1) — it is a context-quality trade, not a token saving. Tracked in the WS-A change spec.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| **D1 — WS-A artifact & enforcement.** A recorded `Grounding` section in the change spec + a guard test that the skills/template carry the rule (A1), or guidance-only prose (A3)? *Rec: recorded section + guard — an unenforced nudge is the status quo that already gets skipped.* | user | spec-authoring / template-change / a guard test |
| **D2 — WS-A scope of the verify rule.** Verify *every* fact the spec rests on, or only facts that name a **file / function / flag / version / decision** (the concrete, checkable, staleness-prone ones)? *Rec: the latter — that is where staleness actually bites, and it keeps grounding proportionate rather than turning every spec into a research essay.* | user | spec-authoring |
| **D3 — WS-B timing.** Build the rollover protocol now, or capture it and sequence it after WS-A? *Resolved: **build now**, alongside WS-A — independent, ships in parallel.* | user ✓ | this proposal / a change spec |

## Breakdown

The change specs this proposal would spawn once accepted:

1. **WS-A — Grounding step + change-spec `Grounding` section + verify-recalled-facts rule.** Add the grounding step to `spec-driven-development`; add the craft (investigate current reality; verify file/function/flag/version/decision facts against current code; record findings and surface decisions) to `spec-authoring`; add a conditional `Grounding` section to `templates/change.md` (mirroring Watchlist trigger, scaled to size); version-stamp all three + registry; add a guard test that the rule and section are present. *Primary.*
2. **WS-B — Graceful context-rollover handoff.** Compose `harness checkpoint` + `harness start --resume` + a `reclaim_marker` extension into a proactive, within-ticket handoff distinct from death-keyed reclamation: a documented trigger (near context budget → checkpoint + write progress marker) and a resume path that continues the same ticket. *Build now, in parallel with WS-A (independent — no blocking relation).*

## Risks / unknowns

- **Grounding can add ceremony to small work.** Mitigation: it inherits the template's "scaled to size" rule — a one-line fix gets a one-line grounding ("verified `foo.py:rename_flag` still exists"), not a research essay. The proportionality must be stated explicitly or it will be over-applied.
- **Grounding can decay into box-ticking** ("verified: yes"). Mitigation: the recorded artifact must state *what current reality is* / *what was checked* (a `path:line`, a current version), not merely assert the step was done. The guard test can only check the rule's *presence*, not that grounding was genuinely performed — be honest about that limit (it is a discipline aid, not a proof).
- **WS-B can be confused with reclamation.** The proactive handoff (alive, near-limit, same ticket) must be clearly distinguished from death-keyed reclaim (dead run, revert to Todo) so the two protocols do not collide on the `reclaim_marker` contract.

---

**Lifecycle.** Ends in one explicit state: **accepted** (spawn the breakdown as Linear issues; record decisions in the specs they govern), **rejected** (kept as the record of why), or **split**. Lives in `specs/proposals/`.

## Out of scope

- **Changing the memory subsystem itself** (auto-pruning or auto-verifying stale memories at recall time). WS-A grounds the *spec* against current code at creation time; keeping the memory store itself fresh is a separate concern worth its own proposal.
