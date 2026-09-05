# ADR 0007 — A `design` verb: an unconditional, verb-owned design stage before the build

- **Status:** Accepted
- **Date:** 2026-07-25
- **Source:** the `design-verb` proposal (settled; removed from the tree by #547, kept in git history)

## Context

ADR 0005 left an admitted asymmetry: `review:<tier>` was a control signal (the
verb constructs the engine subprocess and passes `--model`), while `build:<tier>`
was a recorded judgement only, because the orchestrating session *is* the
builder and no verb-owned seam exists to swap its model per ticket. (Both labels
were retired by #321; the asymmetry is what motivated this ADR, not a live
mechanism.) Its
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

> **Amended 2026-08-07 (#352) — the policy, not the protocol.** Two of the four
> dimensions below no longer hold as written. The stage is **no longer
> unconditional**: an issue carries its intent as an `assurance:<level>` label,
> `start` snapshots the resolved level on the run, and only `complex` requires a
> design. And a *failed* attempt **no longer satisfies `review`** on such a run —
> it is refused with `design_not_usable`. What is unchanged is why the stage
> exists (context segmentation, Opus, the artifact is the change spec's Design
> section) and that `review` is where it is enforced. The reasoning is in
> the `assurance-led-lifecycle` proposal (settled; removed from the tree by #547, kept in git history); the as-built policy is in
> `specs/features/verb-model.md`, and the vocabulary lives in one module,
> `harness/assurance.py`.
>
> Two guard rails came with it. Everything unresolved fails safe to `simple`,
> the level that still requires a review — a label is third-party input, so the
> most a hostile or mistaken one can buy is skipping the *design* stage, never
> the review, the verify-gate evidence check, or `close`'s SHA-bound gate. And
> `trivial` — the level that *would* skip review — is recognized but rewritten
> to `simple` at the boundary, because the deterministic certification that
> makes skipping a review safe is a later increment and is not built. The
> trivial fast path has **not** shipped.

> **Amended 2026-08-15 (#353) — the trivial fast path has shipped, and the
> security bound moved with it.** The two sentences above about `trivial` are
> superseded: `resolve_assurance` now returns `trivial` as stated, and
> `harness certify` is the deterministic certification the previous amendment
> named as missing. A `trivial` run takes no design and **no LLM review**; its
> evidence is a `certify` event bound to HEAD, which `close` accepts as the
> second kind of gate evidence alongside a gate-evidenced `review` pass.
>
> So the bound is no longer *"the worst a label can buy is `complex` → `simple`,
> i.e. skipping the design stage"*. The worst a hostile or mistaken
> `assurance:trivial` label can now buy is **skipping the LLM review** — and only
> when four independent conditions all hold, none of them under the label
> writer's control: the repo's own `CONTEXT.md` declares a valid
> `assurance.trivial_paths` allowlist (absent, empty, or holding one malformed
> pattern, `start` opens the run at `simple` with `fast_path_unavailable`); the
> repo configures a `verify:` command **and** the orchestrator reports it green
> at this HEAD (an unconfigured gate is an ineligibility reason, not a pass —
> the one place `certify` is stricter than `has_gate_evidence`); the worktree is
> clean; and **every** path in `base_sha...HEAD` matches the allowlist *and*
> survives the restricted-surface veto held in code
> (`harness/trivial_diff.py`), which no repo configuration can widen. What a
> label still cannot buy: the verify-gate evidence check, `close`'s SHA-bound
> gate, a `review` event (none is ever synthesized), or eligibility for any
> source, security, persistence, configuration, command/guidance, feature-spec,
> decision, or other public-contract path. An ineligible diff upgrades the run
> and its issue to `simple` and takes an ordinary review; every unresolved
> condition — no allowlist, no boundary, an unreadable diff, an empty diff —
> fails in that same direction, so a bug in the classifier costs a fast path and
> never a gate.

> **Amended 2026-08-08 — the design engine is selectable natively.** A required
> design may run through `claude` (the default, with the configured Opus model)
> or `codex`. Codex runs read-only and returns only the design Markdown as its
> final response; the CLI writes that response to a verb-owned temporary file
> through `--output-last-message`. The ledger records `channel=last_message`
> and no model when Codex uses its own configured default. Claude retains the
> scoped writable-file channel and marked stdout fallback unchanged. This
> native engine union supports strict Codex-only operation without claiming the
> Docker sandbox work in ADR 0013 has shipped.

- **Unconditional, not label-gated.** *(Superseded by the #352 amendment above:
  conditional on issue-carried assurance.)* The design stage runs for **every**
  ticket, regardless of judged difficulty. The rationale is context
  segmentation as much as tier: the design happens in a fresh, dedicated
  engine context, uncontaminated by the build session's orchestration state.
  The engine model is **Opus for all runs initially**; a lower tier was an
  anticipated refinement, deliberately not built. That refinement was described
  as a `design:<tier>` label hanging off the dimension-generic resolver in
  `harness/cli/review_protocol.py`; #321 deleted that resolver along with ADR
  0005's own labels, so the seam it would have hung off no longer exists. A
  configurable design model would now follow `review`'s shape — one value in
  `CONTEXT.md`'s `loop:` block — and is still not built.
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
- **Failure degrades and records.** *(Narrowed by the #352 amendment above: it
  holds where the run's assurance does not require a design; a `complex` run is
  refused `design_not_usable`.)* A design-engine failure (timeout, infra
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

- Every run pays one Opus engine call at design time — until #352, which is the
  cost that motivated making the stage conditional. The counterfactual —
  design-by-rejection burning review cycles — is the expensive path this
  removes on hard tickets, and trivial tickets buy context segmentation.
- `review` gains a refusal reason (`no_design`); enforcement must ship
  **after** the verb exists, or in-flight runs are refused with no verb to
  satisfy — the proposal's breakdown is sequential for this reason.
- The build dimension gets its deterministic seam: top-tier thinking happens
  in a verb-owned subprocess, and the Sonnet session executes against its
  output. `build:<tier>` stayed a pure judged-difficulty record until #321 removed it.
- The mechanics land through the proposal's breakdown tickets; this ADR is
  the policy record.
