---
name: review
description: "/review — review the current branch. Use when the operator invokes `/review` or asks to run that workflow. Invoked by the operator, and reachable by the model: `/routine` drives `/build`, and `/build` drives the review stage, so `disable-model-invocation` is deliberately not set here — it would break that composition (#537 AC-7)."
model: inherit
effort: high
---

The portable plugin root is two directories above this SKILL.md. Resolve embedded paths beginning `skills/`, `agents/`, `templates/`, `hooks/`, or `.codex/` from that root; resolve repository artifacts from the workspace root.

# /review — review the current branch

Usage: `/review` (reviews the active branch's diff against its change spec)

Runs the final gate before merge. Implements `review-discipline` via the `reviewer` agent.

## Steps

### 1. Set context
Identify the branch, its ticket, the change spec, and the canonical spec(s) in `specs/features/` the change touches.

### 2. Move the ticket to In Review
Reflect the handoff on the board.

### 3. Run the reviewer
Dispatch the lane's reviewer agent in a fresh context — `reviewer` in the change lane, `reviewer-feature` in the feature lane, which differ only in the model and effort their frontmatter sets. Supply the ticket, change spec, design artifact for `complex` work, diff, verification output, and — for a user-facing change — the visual evidence: the capture directory `.evidence/<TICKET-ID>/` and its `manifest.md` (the repo's `.claude/rules/design-system.md` owns what lands there); do not supply the implementer's conversation. It performs the two-stage review, runs the verification gate independently (it does not trust the build's claim), and returns a verdict with findings. The **fix** lane has no reviewer at all — the gate and the push guard are its whole assurance (the spine's lane contract); a diff that outgrows the lane is upgraded rather than shipped under it.

### 4. Act on the verdict
The three verdicts are `review-discipline`'s *The verdict vocabulary* — PASS, FAIL, DEFER — and this step handles all three.

- **PASS:** the reviewer has already recorded what shipped to the **as-built record** (`specs/features/<feature>.md`, or the design doc / `SPEC.md` where `feature_specs` is off) — committed *into* the candidate before the certifying gate ran, per `review-discipline`'s *final-evidence ordering* rule, so the verdict covers it and the branch is not touched again. The report names the `reviewed_tree` that verdict binds to, which is the identity `/build`'s ship step re-checks. When the diff changes a documented behaviour — in any lane — this is **gated**, not optional: landing with neither a record update nor a recorded **deferral** (naming the reason) is a FAIL, not a PASS (`review-discipline`, the as-built-record gate). When the surface has no as-built record yet, this ticket creates it — a surface may not accumulate a second shipped ticket without one. The change is then ready for `/build`'s ship step.
- **FAIL:** return the blocking findings to the developer to fix, then re-run `/review`. How many times you may do that — and what happens to the ticket when the budget is spent — is `review-discipline`'s *On a FAIL* section, which owns the stop rule for every entry point. Follow it there rather than counting from a number restated here.
- **DEFER:** the tree carries nothing blocking, but the ticket cannot ship as scoped without the operator's call. Hold it through the provider skill — comment the reason, apply the `input` label, assign the operator — and route every out-of-scope finding by the class split `review-discipline` owns (*bugs are filed; improvements are proposed*), which is also where the filing rules for each class live. **Do not merge** — a DEFER binds no tree to an integration. The ticket returns through `/digest --drain`, not through this command.

### 5. Report
Print the verdict, Stage 1 result per acceptance criterion, Stage 2 findings placed in `review-discipline`'s 2×2 with what happened to each, a **Proposals** section carrying every improvement the review proposes rather than files — one line each with its case, or the word `none`, never an omitted section, and each one also appended to the proposals ledger (`review-discipline` → *The proposal channel*) — the verification output, and the reviewer's **visual-evidence line** — consulted, or not consulted with its reason (`review-discipline` → *Reviewer obligations* owns the reasons).

## Note
On PASS this command leaves the branch review-clean and the canonical spec updated, but does not merge. Integration and ticket-closing belong to `/build`'s ship step and the repo's branch model (`harness.yaml` → `branches:`).
