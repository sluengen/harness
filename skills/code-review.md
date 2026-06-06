<!-- guidance:code-review@0.1.1 -->
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

**If Stage 1 fails, stop.** Report what is missing. Issue a FAIL. Do not review quality.

### Stage 2 — Quality

Only after Stage 1 passes.

**For code:**
- **Correctness** — logic errors, edge cases, off-by-one, null handling, error messages.
- **Security** — input validated at the boundary, no injection-prone string building, no dangerous eval/exec on input, no secrets in code, paths sanitised.
- **Principles** — does the change violate a named `engineering-principles` tenet? Cite the principle, not a preference.
- **Structure** — size, layer boundaries, rule-of-three duplication, composition. Apply the `code-quality` Part B thresholds. Pre-existing violations in untouched files are not findings; only flag if this change makes them worse.

**For specs and designs:**
- **Completeness** — no TBDs, no unresolved questions.
- **Testability** — every criterion is verifiable by a test, not subjective ("feels fast").
- **Clarity** — an implementer could build it without asking. (And it reads cleanly: `writing-quality`.)
- **Consistency** — no contradiction with existing specs or ADRs.

**For frontend code, additionally:** design-system adoption and accessibility (see the `design-system` skill where the profile includes it).

## Severity

| Severity | Definition | Action |
|---|---|---|
| **Critical** | Security hole, data loss, crash, spec violation | Blocks approval |
| **High** | Logic bug, missing validation, missing test for a criterion | Blocks approval |
| **Medium** | Minor inefficiency, incomplete error handling, structural drift | Fix now if small (1–5 lines); carry-forward only if out of scope |
| **Low** | Suggestion, minor improvement | Fix now if trivial; otherwise note and move on |

Critical and High block. Medium and Low do not, **but fix them in the same pass when the fix is small** — the builder already has the context, so deferring a two-line fix wastes more effort than doing it.

### Fix now vs carry-forward

**Fix now:** any mechanical, localised fix on code the task already touched (stale comment, missing validation, wrong helper, a duplicated block). If you can state the fix in one sentence, fix it now.

**Carry-forward (rare):** genuinely separate work — touches systems the task did not, needs a design decision, or is a broad pre-existing pattern. File it as its own ticket.

## Every finding has four parts

1. **What** — the specific issue.
2. **Where** — file:line (code) or section (docs).
3. **Why** — the requirement, principle, or rule it violates.
4. **How** — a concrete suggested fix.

"Could be improved" or "doesn't feel right" is not a finding. Be specific or say nothing.

## Reviewer obligations

- **Run the verification yourself.** Do not trust the builder's claim that tests pass. Fresh run, read the output (`code-quality` Part C).
- **Record reality on PASS.** Update `specs/features/<feature>.md` from what the diff actually does, as the last commit before merge (`spec-driven-development`). This is the reviewer's job, not the builder's.
- **Report:** a one-line verdict, Stage 1 result per criterion, Stage 2 findings by severity with the four parts each, the verification output, and a final PASS / FAIL.

## On a FAIL

Return the blocking findings to the builder and re-review. A second consecutive FAIL is a stop: escalate to the user rather than looping further.
