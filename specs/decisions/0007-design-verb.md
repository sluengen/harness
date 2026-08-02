# ADR 0007 — A `design` verb: an unconditional, verb-owned design stage before the build

- **Status:** Accepted
- **Date:** 2026-07-25
- **Source:** `specs/proposals/design-verb.md`

## Context

ADR 0005 left an admitted asymmetry: `review:<tier>` is a control signal (the
verb constructs the engine subprocess and passes `--model`), but `build:<tier>`
is a recorded judgement only, because the orchestrating session *is* the
builder and no verb-owned seam exists to swap its model per ticket. Its
consequences section anticipated that wiring the build dimension "would need
its own deterministic seam (e.g. a dispatch step)".

Separately, the hardest part of a hard ticket is the technical design —
architecture, data model, contracts, security, failure modes, performance —
and `spec-authoring` names the cost of skipping it: a spec with criteria but
no design pushes those decisions onto the implementer mid-build, where they
are made fastest and worst. On automated ticks that implementer is a Sonnet
session designing inline, in a context already loaded with orchestration
state. Unattended-filed tickets (`/assess` findings, `/harness ingest`,
`/bug`/`/tweak` adjustments) arrive with acceptance criteria but thin Design
sections; the expensive failure path is design-by-rejection — the
`(fix → review)*` loop converging toward the 6-cycle breaker.

## Decision

A fourth verb in the run lifecycle: **`start → design → implement → review →
(fix → review)* → close`**. `harness design --run-id <id>` runs a read-only
engine subprocess (the `review` engine pattern: `claude -p`, `SUBMIT:`
contract, `engine_timeout_seconds` ceiling, Claude-only in-container per ADR
0002) against the run's worktree and ticket, and produces the change spec's
technical design.

> **Amended 2026-08-02 (#294) — the engine protocol, not the policy.** Two
> clauses of that first sentence no longer hold. The engine's output channel is
> a **file**, not the `SUBMIT:` contract: inheriting `review`'s wire format cost
> `design` 12.5% of its attempts against `review`'s 0.24%, because the same
> format was carrying a 14–17 KB document instead of a fixed 100-character
> verdict. And it is no longer **read-only** — it holds write capability for
> that one file and nothing else, which is a narrower and rule-enforced control
> where plan mode was a broad cooperative one. Everything this ADR actually
> decides — unconditional, Opus, the artifact is the change spec's Design
> section, `review` enforces it, failure degrades and records — is untouched;
> `specs/features/verb-model.md` carries the as-built protocol.

Four resolved dimensions:

- **Unconditional, not label-gated.** The design stage runs for **every**
  ticket, regardless of judged difficulty. The rationale is context
  segmentation as much as tier: the design happens in a fresh, dedicated
  engine context, uncontaminated by the build session's orchestration state.
  The engine model is **Opus for all runs initially**; a lower tier (e.g. a
  `design:<tier>` label defaulting to `opus`, on the dimension-generic
  `resolve_model_tier` seam, `harness/cli/review_protocol.py:179`) is an
  anticipated refinement, deliberately not built now. `build:<tier>` /
  `review:<tier>` semantics from ADR 0005 are untouched.
- **The artifact is the change spec's Design section, not a new artifact
  class.** The verb posts the design to the ticket as a marked comment (the
  reclaim/handoff marker pattern) and returns it in bounded `DesignOutput`
  JSON; the ledger `design` event binds the design's hash and the base SHA it
  grounded against. It lives and dies with the change spec — the permanent
  record remains the feature spec the reviewer writes on PASS. No
  `specs/designs/` folder.
- **`review` enforces it.** A run with no recorded design attempt is refused
  with `reason=no_design`, mirroring `no_gate_evidence`: silence is not a
  pass. When a design exists, `review` passes it to the review engine as
  context, so the fix loop converges on conformance to the design rather than
  re-deriving intent each cycle.
- **Failure degrades and records.** A design-engine failure (timeout, infra
  error) is recorded as the design event and the build proceeds without a
  design; enforcement checks that a design was *attempted and recorded*, not
  that it succeeded. An infra flake never wedges the unattended queue, and
  the ledger stays honest about what happened.

## Alternatives rejected

- **Discretionary sub-agent (guidance-only).** Instruct the session to spawn
  an Opus sub-agent for design. Rejected as the path ADR 0005 already ruled
  uncontrollable: no ledger event, no artifact contract, and compliance
  decays on exactly the long unattended runs that need it.
- **Design at filing time.** Enrich the front doors to write full Design
  sections when filing. Rejected: the filer is often the Sonnet unattended
  loop itself, has no worktree at a defined base SHA, and a filing-time
  design goes stale in the queue.
- **A "Design" board stage.** Tickets flow Todo → Design → Todo. Rejected as
  a parallel lifecycle on the board duplicating the run ledger, with a
  stalled-stage failure mode and no owner.
- **Label-gated opt-in** (the proposal's original draft). Rejected by the
  operator at decision time: the context-segmentation benefit applies to
  routine work too, and a tier label remains available later if per-run Opus
  spend on trivial tickets proves too high.

## Consequences

- Every run pays one Opus engine call at design time; the counterfactual —
  design-by-rejection burning review cycles — is the expensive path this
  removes on hard tickets, and trivial tickets buy context segmentation.
- `review` gains a refusal reason (`no_design`); enforcement must ship
  **after** the verb exists, or in-flight runs are refused with no verb to
  satisfy — the proposal's breakdown is sequential for this reason.
- The build dimension gets its deterministic seam: top-tier thinking happens
  in a verb-owned subprocess, and the Sonnet session executes against its
  output. `build:<tier>` stays a pure judged-difficulty record.
- The mechanics land through the proposal's breakdown tickets; this ADR is
  the policy record.
