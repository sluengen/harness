---
proposal: design-verb
status: superseded         # draft | under-decision | accepted | shipped | rejected | split
date: 2026-07-25
related:
  - specs/decisions/0005-per-ticket-model-tiering.md
  - specs/features/verb-model.md
  - specs/features/cli-surface.md
---

# Proposal: A `design` verb — a deterministic Opus seam before the build

***Superseded 2026-08-15** by [ADR 0015](../decisions/0015-harness-v4-thin-verification-layer.md) — the verb lifecycle this adds a fourth verb to was retired, taking ADR 0007 and the `design` stage with it; the agent-led `/build` carries design in the change spec instead. Kept for the audit; nothing below describes current behaviour.*

> Add a fourth verb to the run lifecycle — `start → design → implement → review → close` — that runs a top-tier engine to produce the change spec's technical design before the (typically Sonnet) session builds, giving the build dimension the deterministic model seam ADR 0005 said it lacked.

## Problem / motivation

ADR 0005 established two per-ticket model tiers, and admitted an asymmetry: `review:<tier>` is a **control signal** — the verb constructs a `claude -p` subprocess and passes `--model` — but `build:<tier>` is a **recorded judgement only**, because the orchestrating session *is* the builder and there is no verb-owned seam to swap its model per ticket. The ADR's own consequence note says the wiring "would need its own deterministic seam (e.g. a dispatch step) to become controllable."

Meanwhile the hardest part of a hard ticket is not typing the code — it is the technical design: architecture, data model, interface contracts, security posture, failure modes, performance, how it scales. `spec-authoring` states the cost plainly: *"a spec with criteria but no design pushes the hard decisions onto the implementer mid-build, where they are made fastest and worst."* Today that is exactly where those decisions land on automated ticks: a Sonnet session, mid-build, inline.

The queue's tickets split into two populations:

- **Operator-authored work** gets Fable/Opus thinking at proposal time — the `/propose` flow that produced this document. Its change specs arrive with real Design sections.
- **Unattended-filed work** — `/assess` findings, `/harness ingest`, `/bug` / `/tweak` adjustments — arrives with a problem statement and acceptance criteria but a thin or absent Design section. The Sonnet tick session both designs and builds it.

If nothing is done: `build:opus` stays decorative; hard tickets either burn `(fix → review)*` cycles doing design-by-rejection (bounded at 6 cycles, so the expensive path is also the one that hits the breaker) or get deferred to the operator, which defeats the unattended loop.

## Options

**Option A — Discretionary sub-agent, no new verb.** Instruct the orchestrating session (in `commands/harness.md`) to spawn an Opus sub-agent for design when it sees `build:opus`. · Cheapest to ship — a guidance edit, zero code. · But this is precisely the path ADR 0005 rejected as uncontrollable: "a session spawning a subagent is discretionary, not a verb-owned seam." No ledger event, no artifact contract, no way to interrogate later whether the escalation happened. Compliance decays exactly on the runs that need it most (long, hard ones).

**Option B — A `design` verb (accepted).** A fourth verb, run-bound like `review`: after `start`, `harness design --run-id <id>` runs a **read-only top-tier engine subprocess** against the worktree and the ticket, and emits the change spec's Design section — posted to the ticket, returned in bounded JSON, recorded as a ledger event. The session then implements against a completed design. · Deterministic, audited, model-controllable — the same properties `review` already has, applied upstream. · Cost: a new verb (CLI surface, ledger event type, engine protocol reuse), and one Opus engine call per run. (As drafted this was label-gated opt-in; D1 resolved it to an unconditional stage of every run — see Open decisions.)

**Option C — Design at filing time, no new verb.** Enrich the front doors (`/harness ingest`, `/assess`, `/bug`/`/tweak`) to write full Design sections when filing. · No run-time machinery. · But the filer often is the Sonnet unattended loop itself (an `/assess` tick filing findings), so the tier problem just moves; the filer has no worktree at a defined base SHA, so the design grounds against whatever the repo looked like at filing and goes stale in the queue; and for operator front doors it burns operator time on what should be automated.

**Option D — A "Design" queue stage on the board.** Tickets flow Todo → Design → Todo, with a separate design pass working the Design column. · Makes design visible as board state. · Heaviest option: a board schema change (and #172 showed non-default board fields/views are where information goes to be invisible), a second unattended loop to own the stage, and a stalled-stage failure mode with no owner. The run already has a lifecycle with a ledger; adding a parallel lifecycle on the board duplicates it.

## Recommendation

**Option B.** It is the shape this system already trusts: `review` proved the pattern — a deterministic, verb-owned, read-only engine subprocess whose model is a per-ticket label, whose output is a bounded contract, and whose occurrence is a ledger fact. The design verb applies the identical pattern to the moment `spec-authoring` says matters most. `engineering-principles` alignment: it is the smallest change that makes the build tier *controllable* rather than aspirational, it reuses the existing engine protocol layer rather than inventing one, and it keeps judgement (what the design says) separate from enforcement (that a design happened, recorded in the ledger).

### Mechanics sketch

- **Placement:** `start → design → implement → review → (fix → review)* → close`. The verb is run-bound (`harness design --run-id <id>`), running **after `start`** so the engine designs against the real worktree at the run's base SHA — grounded in the code as it is, not as the ticket remembers it.
- **Trigger:** unconditional — the design step is part of every run, not an opt-in for hard tickets (D1, resolved). The value is not only tier escalation but **context segmentation**: the design happens in a fresh, dedicated engine context, uncontaminated by (and not contaminating) the build session's context, regardless of difficulty. The engine model is **Opus for every run initially**; a lower tier (e.g. a `design:<tier>` label with default `opus`) is an anticipated future refinement, not built now — the dimension-generic `resolve_model_tier` (`harness/cli/review_protocol.py:179`) makes that a small change when wanted.
- **Engine:** the same protocol family as `review` — a read-only `claude -p` subprocess constructed by the verb, `SUBMIT:` contract, `engine_timeout_seconds` ceiling, Claude-only in-container (ADR 0002 posture carries over; no codex variant — this is not a cross-model second opinion, it is a tier escalation). The prompt embodies `agents/architect.md` and the `architecture` skill: data model, interface/contract, behaviour in scenarios, security section, test strategy — a design the builder can implement test-first without guessing.
- **The artifact is not a new artifact class.** The design doc **is the change spec's Design section** — the tier `spec-authoring` already defines, delivered late instead of never. The verb posts it to the ticket as a marked comment (the reclaim/handoff marker pattern) and returns it in the bounded `DesignOutput` JSON; the ledger `design` event binds the design's hash and the base SHA it grounded against. It lives and dies with the change spec: the permanent record remains the feature spec the reviewer writes on PASS. No `specs/designs/` folder — a committed design-doc corpus would compete with "decisions live in the spec they govern," duplicate the feature spec, and rot.
- **Review linkage:** when a design event exists, `review` passes the design to the review engine as context, so the `(fix → review)*` loop converges on *conformance to the design* rather than re-deriving intent each cycle.
- **Decision record:** accepted, this is ADR 0007 — it extends ADR 0005 by adding the dispatch seam its consequences section anticipated.

## Open decisions

All four resolved by the operator, 2026-07-25:

| Decision | Resolution | Recorded in |
|---|---|---|
| D1 — Trigger: label-gated opt-in, or an unconditional stage of every run? | **Unconditional.** The design step runs for every ticket regardless of judged difficulty — the win is context segmentation as much as tier. Model is **Opus for all runs initially**; a lower tier is a future refinement (no `design:<tier>` label built now). Neither `build:<tier>` nor a new label family gates the verb; ADR 0005's build-label semantics are untouched. | ADR 0007 |
| D2 — Artifact home: ticket comment, committed `specs/designs/` file, or worktree-only file | **Ticket comment** — the change spec's Design section, posted as a marked comment; no committed artifact class. | ADR 0007 + `spec-authoring` |
| D3 — Enforcement: advisory, or `review` refuses an undesigned run | **`review` refuses** a run with no recorded design attempt (`reason=no_design`, mirroring `no_gate_evidence`: silence is not a pass). Applies to every run, per D1. | verb-model feature spec |
| D4 — Failure posture: a failed design engine blocks the run, or degrades | **Degrade and record.** The failure is recorded as the design event; the build proceeds without a design. D3's enforcement checks "a design was *attempted and recorded*", not "succeeded" — an infra flake never wedges the unattended queue. | verb-model feature spec |

## Breakdown

1. **Design engine protocol** — the prompt builder (architect framing: data model / contract / scenarios / security / test strategy), the `SUBMIT:` design contract and parser, and the model default (Opus, hard-coded initially; the dimension-generic `resolve_model_tier` is the anticipated seam for a future tier label but is not wired here). Pure protocol layer beside `review_protocol.py`; no verb yet.
2. **The `harness design` verb** — run-bound CLI command: resolves the run, invokes the engine with the timeout ceiling, posts the marked ticket comment, appends the ledger `design` event (design hash + grounded base SHA + engine + model), emits bounded `DesignOutput` JSON. Failure posture per D4 (degrade and record).
3. **Review linkage + enforcement** — `review` loads the run's design event, passes the design as engine context, and refuses any run with no recorded design attempt (`reason=no_design`, per D3).
4. **Loop + guidance integration** — `commands/harness.md` gains the design step in `/harness run`; `spec-authoring`'s model-tiering paragraph notes the design stage; ADR 0007 cross-references land; CONTEXT/feature-spec updates land through the normal reviewer path.

Each ships on its own: 1 is inert protocol, 2 makes the verb usable manually, 3 wires the gate, 4 makes the loop drive it.

## Risks / unknowns

- **A bad design misleads worse than no design.** Garbage in, confidently built out. Mitigated by the review linkage: the review engine sees the ticket *and* the design, so a design that contradicts the spec produces a fail, not a silently wrong merge. The residual risk — spec and design both plausible and both wrong — exists today without the verb.
- **Contract shape needs iteration.** Too rigid a `SUBMIT:` schema yields boilerplate sections; too loose yields essays. Start with the section list `agents/architect.md` already mandates and tune from real runs.
- **Opus spend is now on every run, not just hard ones** — one engine call per ticket, capped by `engine_timeout_seconds`. D1 accepts this deliberately: the context-segmentation benefit applies to routine work too, and the counterfactual cost (design-by-rejection burning review cycles toward the 6-cycle breaker) is the expensive path. If per-run spend proves too high on trivial tickets, the recorded relief valve is a `design:<tier>` label defaulting to `opus` — a small change on the `resolve_model_tier` seam.
- **Staleness within a run is a non-issue** (the per-run wall-clock budget bounds it — `loop.wall_clock_budget_minutes`, 110 min since #260), but a *reclaimed* run resumed from a WIP branch inherits a design grounded at the original base SHA — acceptable, same as it inherits the WIP itself; the design event's recorded SHA makes the gap auditable.
- **Migration ordering matters**: enforcement (breakdown 3) must ship after the verb (breakdown 2), or every in-flight run hits `no_design` with no verb to satisfy it. The breakdown is sequential for exactly this reason.
