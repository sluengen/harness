<!-- guidance:review@0.1.5 -->
# /review — review the current branch

Usage: `/review` (reviews the active branch's diff against its change spec)

Runs the final gate before merge. Implements `review-discipline` via the `reviewer` agent.

## Steps

### 1. Set context
Identify the branch, its ticket, the change spec, and the canonical spec(s) in `specs/features/` the change touches.

### 2. Move the ticket to In Review
Reflect the handoff on the board.

### 3. Run the reviewer
Dispatch the `reviewer` agent. It performs the two-stage review, runs the verification gate independently (it does not trust the build's claim), and returns a verdict with findings.

### 4. Act on the verdict
- **PASS:** the reviewer records what shipped to the **as-built record** (`specs/features/<feature>.md`, or the design doc / `SPEC.md` where `feature_specs` is off) as the last commit on the branch. When the diff touches a user-facing surface this is **gated**, not optional — a behaviour change that lands with neither a record update nor a recorded **deferral** (naming the reason) is a FAIL, not a PASS (`review-discipline`, the as-built-record gate). When the surface has no as-built record yet, this ticket creates it — a surface may not accumulate a second shipped ticket without one. The change is then ready for `/ship`.
- **FAIL:** return the blocking findings to the developer to fix, then re-run `/review`. How many times you may do that — and what happens to the ticket when the budget is spent — is `review-discipline`'s *On a FAIL* section, which owns the stop rule for every entry point. Follow it there rather than counting from a number restated here.

### 5. Report
Print the verdict, Stage 1 result per acceptance criterion, Stage 2 findings by severity, and the verification output.

## Note
On PASS this command leaves the branch review-clean and the canonical spec updated, but does not merge. Integration and ticket-closing belong to `/ship` and the repo's branch model (`CONTEXT.md`).
