---
name: review-discipline
description: Use when reviewing any artifact — code, a spec, or a design — for spec compliance then quality, or doing a self-check before handoff. Two stages (does it meet the requirements, then is it well-built), a severity bar, and the four-part finding format. Load before approving or handing off work.
---
<!-- guidance:review-discipline@0.11.0 -->
# Code Review

How to review any artifact (code, spec, design, copy) for spec compliance and quality. Used by the **reviewer** for formal pre-merge review, the **developer** for self-check before handoff, and anyone doing an ad-hoc quality pass.

The standards the reviewer applies are not separate from the ones the builder built to: structure, scope, and verification come from `code-quality`; design values come from `engineering-principles`. This file is the *method* and the *bar*, in one place, so the two sides cannot drift.

## Two stages, in order

Stage 1 must pass before Stage 2 begins. Quality is irrelevant if the artifact does not do what was asked.

### Stage 1 — Spec compliance

One question: **does the output meet the requirements?**

1. **Read the requirements first**, before the artifact: the change spec — its acceptance criteria *and* its design.
2. **Check each requirement.** For every criterion, mark met / partial / missing.
3. **Check the design was specified and followed.** For non-trivial work the change spec should state its design (data model / interface / scenarios), not just acceptance criteria (`spec-authoring`). If the design was specified, confirm the code matches it; if a non-trivial change shipped with no design at all, that is a Stage 1 gap — the contract was invented mid-build. (Trivial changes are exempt.)
4. **Check scope.** Was anything added that was not asked for? Was anything in-scope skipped? (Per `code-quality` Part A.)
5. **Check intent.** Does it meet the spirit, not just the letter? A technically-compliant solution that misses the point fails.
6. **For code: verify TDD.** Every acceptance criterion has a test. Tests were written to fail first (the diff and history should show it). Tests are meaningful, not trivially true.
7. **Check the criteria are current, and any renegotiation is on the ticket.** Review against the acceptance criteria *as they stand on the ticket now* — not a remembered earlier version. A builder who found a criterion wrong mid-build must have renegotiated it *on the tracker issue* (comment with the evidence, amend the criterion there — `spec-authoring`), and you flag that amendment in the review report. A criterion renegotiated only in a commit body or PR description — never amended on the ticket — is a Stage 1 **FAIL** even when the engineering call is right: the canonical record is the ticket, so a Done ticket whose current criteria the diff did not meet is a false record, regardless of how sound the reasoning buried in the commit was. (A raw file-size criterion is itself a Stage 1 gap — `spec-authoring` forbids it; the structural outcome is what the spec should state.)

**If Stage 1 fails, stop.** Report what is missing. Issue a FAIL. Do not review quality.

### Stage 2 — Quality

Only after Stage 1 passes.

**For code:**
- **Correctness** — logic errors, edge cases, off-by-one, null handling, error messages.
- **Diff-shape checks** — when the change adds a type predicate; deletes or ports a public surface; repeats a helper; introduces placeholder, synchronization, fetch/refetch, watchlist, or CONTEXT/as-built-record changes, load [`skills/review-discipline/references/diff-shape-checks.md`](references/diff-shape-checks.md) and apply only the matching checks.
- **Over-engineering** — complexity the change *adds* that a simpler form replaces. Tag each finding with the cut it names, and in the finding name *what replaces it* so the fix is concrete, not a vibe:
  - `stdlib:` hand-rolled what the standard library already ships — name the function that replaces it.
  - `native:` a dependency, or a block of code, doing what the language or platform already does — name the built-in feature.
  - `yagni:` an abstraction with one implementation, a config nobody sets, a layer with one caller — inline it until a second caller exists.
  - `shrink:` the same logic in fewer lines — show the shorter form.
  - `delete:` dead code, a speculative feature, or unused flexibility — replaced by nothing.

  This lens is **complexity only** — correctness, security, and performance stay in their own lenses above; do not relabel a real bug as over-engineering. The single minimum smoke test, or an `assert`-based self-check, is **never** flagged as bloat: the smallest thing that proves the change works is not over-engineering. As with Structure, pre-existing complexity in files this change does not touch is not a finding.

**For specs and designs:**
- **Completeness** — no TBDs, no unresolved questions.
- **Testability** — every criterion is verifiable by a test, not subjective ("feels fast").
- **Clarity** — an implementer could build it without asking. (And it reads cleanly: `writing-quality`.)
- **Consistency** — no contradiction with existing specs or recorded decisions.

**For frontend code, additionally:** design-system adoption and accessibility (`design-system`), and that the surface handles all its states — empty, loading, error, and edge cases (0 / 1 / many / missing), not just the happy path (`ux-design`).

## Severity

| Severity | Definition | Action |
|---|---|---|
| **Critical** | Security hole, data loss, crash, spec violation | Blocks approval |
| **High** | Logic bug, missing validation, missing test for a criterion | Blocks approval |
| **Medium** | Minor inefficiency, incomplete error handling, structural drift | Fix now if small (1–5 lines); carry-forward only if out of scope |
| **Low** | Suggestion, minor improvement | Fix now if trivial; otherwise record in the review notes and drop — **never filed as a ticket** |

Critical and High block. Medium and Low do not, **but fix them in the same pass when the fix is small** — the builder already has the context, so deferring a two-line fix wastes more effort than doing it.

### Fix now vs carry-forward

**Fix now:** any mechanical, localised fix on code the task already touched (stale comment, missing validation, wrong helper, a duplicated block). If you can state the fix in one sentence, fix it now.

**Carry-forward (rare):** genuinely separate work — touches systems the task did not, needs a design decision, or is a broad pre-existing pattern. Before filing, apply the `tracker` skill's *Bundle before you file* check: an open unstarted ticket on the same surface gets this finding appended to it rather than a twin filed beside it. Only when nothing bundles does it become its own ticket — and state in the finding why it cannot be fixed in-branch.

Two bounds on filing (ADR 0015), because a queue that grows under review is a failed review process:

- **The severity floor.** Only Critical, High, and a Medium meeting the carry-forward bar may be filed. A Low is never filed — fix it or record it in the review notes and drop it.
- **The recursion cap.** A ticket filed from a review carries the `review-finding` label; that label marks generation one, and generation one is the last. When the ticket **under review** carries `review-finding`, this review files nothing below High — every other finding is fixed in-branch or recorded and dropped. One generation of follow-up, never a lineage.

## Every finding has four parts

1. **What** — the specific issue.
2. **Where** — file:line (code) or section (docs).
3. **Why** — the requirement, principle, or rule it violates.
4. **How** — a concrete suggested fix.

"Could be improved" or "doesn't feel right" is not a finding. Be specific or say nothing.

## Reviewer obligations

- **Run the verification yourself.** Do not trust the builder's claim that tests pass. Fresh run, read the output (`code-quality` Part C).
- **Record reality on PASS — the as-built-record gate.** When the diff touches a **user-facing surface** (a screen, route, endpoint, CLI command, or any behaviour the as-built record documents — matched from the changed paths the same way the *Architecture watchlist* reads `git diff --name-only`), the review must either fold the matching **as-built-record** update into this change or record an **explicit deferral naming the reason**. A shipped behaviour change to such a surface with **neither** a record update **nor** a recorded deferral is a **FAIL** — the canonical record silently rots otherwise, a drift no later per-change reviewer catches because no future change re-touches the gap. The as-built record is `specs/features/<feature>.md` where the `feature_specs` layer is on, otherwise the design doc / `SPEC.md`; the same gate applies to it. Recording reality is the reviewer's job, not the builder's, written from what the diff actually does. When a surface's as-built record does not exist yet, the first ticket touching that surface creates it; a surface is not permitted to accumulate more than one shipped ticket without one — the record is where a gap between tickets becomes visible, and it cannot do that job retroactively (`spec-driven-development`).
- **Close the candidate before you certify it — the final-evidence ordering rule.** The tree you verify and the tree your verdict covers are the tree that merges. So the as-built-record update goes **into the candidate first**: draft it from the diff, commit it onto the branch, and only then run the verify gate and decide. Nothing lands after that — a later commit, documentation included, is uncertified tree content and voids the pass. Order it the other way and the record edit is never gate-checked, which matters because a record is delivered tree content that a link, generated-doc, or drift guard can reject; on the harness path it is refused outright, since `harness close` binds the pass to a SHA and a post-verdict commit is exactly what `stale_review` rejects. Two consequences worth stating: on a **FAIL** there is nothing settled to record, so no record work is done — it is drafted fresh from the *next* diff; and when the certifying gate goes red **because of your own record edit**, you wrote it, so you fix it and re-run (bounded — two attempts, then FAIL carrying the gate output), never the implementation, which would make you the builder. A **deferral** is ordering-neutral: it lands in the report and the ticket, not the tree. Report the SHA the verdict bound to, so the flow that ships can check that HEAD is still it.
- **Report:** a one-line verdict, Stage 1 result per criterion, Stage 2 findings by severity with the four parts each, the verification output, the `reviewed_sha` the verdict binds to, and a final PASS / FAIL.

## On a FAIL — the review→fix stop rule

Return the blocking findings to the builder and re-review. How many times that may happen is **one policy, owned here**. Every other agent and command points at this section rather than restating it; the numbers it names live in `CONTEXT.md` → `loop:` so a repo tunes its own budget without forking the rule.

A run may spend `loop.max_review_cycles` review→fix cycles in total. Three windows:

- **The unconditional window** — the first `loop.unconditional_review_cycles`. A FAIL here is normal iteration: fix the root cause and re-review, no justification owed. Most work that converges converges inside it.
- **The judged window** — every cycle after that, up to the budget. Before spending one, make a convergence judgment and **write it down**: name which findings are new and which are carried over, and continue only when the findings are peeling back layers and the work is materially approaching PASS. Stop early when the pattern says the problem is the design, the requirements, or the implementation approach rather than the remaining defects — more cycles do not fix any of those. The judgment is recorded so it stays honest rather than optimistic; an unwritten one is reliably a rationalisation for another cycle.
- **Exhausted** — the budget is spent and the last cycle did not PASS. **Stop regardless of how converging it looked.** A run that still reads as converging on its last allowed cycle is exactly the case the budget exists to bound: the read has been wrong every cycle so far.

**An exhausted ticket goes on operator hold — it does not go back to the queue.** Preserve the work (push the branch), then put the ticket in a state the unattended loop will not pick up: apply the operator-hold label **and assign the ticket to the operator**. Assignment is the load-bearing half — `work-discovery` skips an assigned ticket, so this is what stops the next tick re-picking the work and starting a fresh budget on it. A human decides what happens next: re-scope it, split it, or authorise a continuation. Nothing automated may clear the hold or reset the budget, because "start again with five more cycles" is the one outcome that turns a bounded loop back into an unbounded one.

Where the harness app is available, that is `harness checkpoint` followed by `harness defer <TICKET> --needs operator` — the verb posts the comment, applies the label, assigns the operator, and records the hold in the ledger. Elsewhere, reach the same end state through the repo's tracker. Either way the reason posted with it is written by you, from the cycle count and the branch — not a paste of the review engine's own prose, which is derived from an untrusted diff.

The harness enforces the budget deterministically at the `review` boundary, so an orchestrator that ignores the rule is refused rather than merely wrong (`commands/harness.md` has the verb-level mechanics: the exit code, the `reason` tag, and the two advisory fields that let a run stop *before* the refusal). The refusal is the backstop; this section is the policy.
