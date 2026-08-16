<!-- guidance:template-proposal@0.1.3 -->
---
proposal: assurance-led-lifecycle
status: shipped
date: 2026-08-05
related: [design-verb, verb-model, run-ledger, 0007-design-verb, issue-332]
---

# Proposal: Assurance-led lifecycle stages

***Shipped.** Assurance is a level carried on the ticket as an `assurance:<level>` label — exactly one, confirmed by re-reading the issue (`skills/tracker/SKILL.md`) — and consumed by `commands/build.md`, which runs the stages that level earns and defaults to `simple` when the value is missing, conflicting or unrecognised.*

> Replace the unconditional design attempt with an issue-carried assurance policy that spends design and review effort only where the change warrants it.

## Problem / motivation

Every harness run currently invokes the design engine, and `review` accepts a failed design attempt as satisfying the design gate. The stage therefore proves invocation rather than a usable outcome. Small changes pay for an Opus call they do not need, while complex changes can proceed after the design stage produced nothing.

Issue #332 settled the intended lifecycle policy but combined the policy core, a new close-gate certification path, diff classification, every filing surface, dependent-ticket rewrites, and later measurement in one assessment ticket. An unattended build cannot choose those contracts safely or know when the programme is complete.

## Options

**Option A — Keep unconditional design.** Every run retains the same shape and a failed attempt continues to satisfy review. This avoids migration work but preserves the cost and the weak gate that prompted the assessment.

**Option B — Assurance controls required stages.** Each issue carries `assurance:trivial`, `assurance:simple`, or `assurance:complex`. The run snapshots that intent, one policy decides its required stages, and the actual diff may only upgrade it. This adds a small policy model and one deterministic certification path, then removes unnecessary engine calls.

**Option C — Let the orchestrator skip stages by judgment.** The session decides at run time without a durable issue signal. This is cheap to implement but cannot be audited or applied consistently across the harness and agent-led flows.

## Recommendation

Adopt Option B in four ordered increments. It makes the issue the durable intent, the run the stable execution snapshot, and the ledger the evidence for what certified the exact tree. Missing, malformed, or unsupported assurance fails safely to `simple`.

The trivial path uses an allowlist, not a denylist. A deterministic classifier cannot prove the absence of semantic risk from an unfamiliar path, so every unknown path upgrades the run to `simple`. Diff eligibility and SHA-bound certification ship together; neither is useful or safe alone.

Certification is its own ledger assertion rather than a synthetic LLM review pass. The shared close-gate predicate accepts either a gate-evidenced review pass or a gate-evidenced trivial certification bound to HEAD. This preserves the meaning of `review` and keeps both close and reclaim on one answer.

These choices follow `engineering-principles`: one policy home, explicit boundaries, safe defaults, independently reversible increments, and no general workflow engine.

## Open decisions

All decisions were resolved by the operator on 2026-08-04 and the decomposition was accepted on 2026-08-05.

| Decision | Resolution | Recorded in |
|---|---|---|
| Assurance levels | `trivial` skips design and LLM review; `simple` requires review; `complex` requires a usable design and review | this proposal; ADR 0007 amendment when the policy ships |
| Safe default | Missing, conflicting, unknown, or temporarily unsupported assurance becomes `simple`, never `trivial` | policy-core change spec |
| Runtime stability | `start` snapshots assurance for the run; later stages consume that snapshot rather than re-reading mutable labels | policy-core change spec; run-ledger feature spec on delivery |
| Upgrade direction | A run may upgrade assurance and persist the upgrade; it may never downgrade | certification change spec |
| Trivial safety | An explicit path allowlist is required; unknown and restricted surfaces upgrade to `simple` | certification change spec |
| Certification evidence | A distinct deterministic certification record is bound to the verified SHA; it is not represented as an LLM review pass | certification change spec; run-ledger feature spec on delivery |
| Engine choice | Claude versus Codex and model aliases remain orthogonal to assurance | ADR 0005 retirement; existing engine-selection proposal |

## Breakdown

The native issue dependency chain is the execution order. Only the first incomplete item is unblocked.

1. **Assurance policy and conditional stages.** Add the vocabulary and run snapshot, make design conditional, require a successful design for complex work, and allow simple review without a design. Until item 2 lands, `trivial` upgrades to `simple`.
2. **Deterministic trivial certification.** Add the conservative diff classifier, upgrade persistence, SHA-bound certification evidence, and the shared close-gate path as one vertical slice.
3. **Assurance-aware filing.** Provision the labels and make every issue-creation surface assign exactly one assurance through the tracker-neutral policy.
4. **Agent-led `/build` alignment.** Re-scope existing issue #288 so the agent-led flow applies the same assurance semantics without pretending it has the harness ledger.

### Spawned issues

| Item | Issue | Blocked by |
|---|---|---|
| 1 — policy and conditional stages | [#352](https://github.com/sluengen/harness/issues/352) | — |
| 2 — trivial certification | [#353](https://github.com/sluengen/harness/issues/353) | #352 |
| 3 — filing integration | [#354](https://github.com/sluengen/harness/issues/354) | #353 |
| 4 — `/build` alignment | [#288](https://github.com/sluengen/harness/issues/288) | #354 |

The design-engine diversity work in #318/#319 remains useful after this programme, but it is not required to deliver assurance. Those tickets move to Backlog and keep their own prerequisite chain. The review-timeout defect is already #347 and remains separate.

## Risks / unknowns

- **The safe trivial set may be small.** That is preferable to a classifier that silently exempts production or public-contract changes. Thirty-day measurement starts only after filing integration ships; the follow-up is created then so its window has a real start date.
- **Existing and in-flight runs predate assurance.** Migration and readers must interpret them as `simple`; no historical ledger rewrite is required.
- **An upgrade spans tracker and ledger state.** External tracker writes are not transactional. Record the run upgrade first, report tracker-sync failure explicitly, and keep the stricter run state authoritative for safety.
- **The gate surface grows.** Item 2 touches the shared certification predicate and `close.py`, so its change spec carries a watchlist trigger and tests both positive evidence types plus stale/missing evidence.
- **Old tickets still describe unconditional design.** #288, #318, and #319 must not run against their current wording. Native dependencies and Backlog placement keep them out of the automatic queue until their specs match the delivered policy.

---

**Lifecycle.** Accepted 2026-08-05. The proposal is complete when its ordered change specs exist; delivered behaviour is recorded by each reviewer in the feature specs and ADR 0007.
