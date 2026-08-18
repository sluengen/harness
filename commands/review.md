# /review — review the current branch

Usage: `/review` (reviews the active branch's diff against its change spec)

Runs the final gate before merge. Implements `review-discipline` via the `reviewer` agent.

## Steps

### 1. Set context
Identify the branch, its ticket, the change spec, and the canonical spec(s) in `specs/features/` the change touches.

### 2. Move the ticket to In Review
Reflect the handoff on the board.

### 3. Run the reviewer
Dispatch the `reviewer` agent in a fresh context. Supply the ticket, change spec, design artifact for `complex` work, diff, verification output, and — for a user-facing change — the visual evidence: the capture directory `.evidence/<TICKET-ID>/` and its `manifest.md` (`commands/build.md` → *Visual evidence for a user-facing change* owns what lands there); do not supply the implementer's conversation. It performs the two-stage review, runs the verification gate independently (it does not trust the build's claim), and returns a verdict with findings. `trivial` work instead requires its conservative deterministic certification; an ineligible diff upgrades to `simple` rather than bypassing review.

### 4. Act on the verdict
The three verdicts are `review-discipline`'s *The verdict vocabulary* — PASS, FAIL, DEFER — and this step handles all three.

- **PASS:** the reviewer has already recorded what shipped to the **as-built record** (`specs/features/<feature>.md`, or the design doc / `SPEC.md` where `feature_specs` is off) — committed *into* the candidate before the certifying gate ran, per `review-discipline`'s *final-evidence ordering* rule, so the verdict covers it and the branch is not touched again. The report names the `reviewed_tree` that verdict binds to, which is the identity `/ship` re-checks. When the diff touches a user-facing surface this is **gated**, not optional — a behaviour change that lands with neither a record update nor a recorded **deferral** (naming the reason) is a FAIL, not a PASS (`review-discipline`, the as-built-record gate). When the surface has no as-built record yet, this ticket creates it — a surface may not accumulate a second shipped ticket without one. The change is then ready for `/ship`.
- **FAIL:** return the blocking findings to the developer to fix, then re-run `/review`. How many times you may do that — and what happens to the ticket when the budget is spent — is `review-discipline`'s *On a FAIL* section, which owns the stop rule for every entry point. Follow it there rather than counting from a number restated here.
- **DEFER:** the tree carries nothing blocking, but the ticket cannot ship as scoped without the operator's call. Hold it through the `tracker` skill — comment the reason, apply the `input` label, assign the operator — and route every out-of-scope finding by the class split `review-discipline` owns (*bugs are filed; improvements are proposed*), which is also where the filing rules for each class live. **Do not merge and do not run `/ship`** — a DEFER binds no tree to an integration. The ticket returns through `/decision`, not through this command.

### 5. Report
Print the verdict, Stage 1 result per acceptance criterion, Stage 2 findings placed in `review-discipline`'s 2×2 with what happened to each, a **Proposals** section carrying every improvement the review proposes rather than files — one line each with its case, or the word `none`, never an omitted section, and each one also appended to the proposals ledger (`review-discipline` → *The proposal channel*) — the verification output, and the reviewer's **visual-evidence line** — consulted, or not consulted with its reason (`review-discipline` → *Reviewer obligations* owns the reasons).

## Note
On PASS this command leaves the branch review-clean and the canonical spec updated, but does not merge. Integration and ticket-closing belong to `/ship` and the repo's branch model (`CONTEXT.md`).
