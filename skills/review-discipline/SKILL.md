---
name: review-discipline
description: Use when reviewing any artifact — code, a spec, or a design — for spec compliance then quality, or doing a self-check before handoff. Two stages (does it meet the requirements, then is it well-built), a severity bar, and the four-part finding format. Load before approving or handing off work.
---
<!-- guidance:review-discipline@0.6.2 -->
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
7. **Check the criteria are current, and any renegotiation is on the ticket.** Review against the acceptance criteria *as they stand on the ticket now* — not a remembered earlier version. A builder who found a criterion wrong mid-build must have renegotiated it *on the Linear issue* (comment with the evidence, amend the criterion there — `spec-authoring`), and you flag that amendment in the review report. A criterion renegotiated only in a commit body or PR description — never amended on the ticket — is a Stage 1 **FAIL** even when the engineering call is right: the canonical record is the ticket, so a Done ticket whose current criteria the diff did not meet is a false record, regardless of how sound the reasoning buried in the commit was. (A raw file-size criterion is itself a Stage 1 gap — `spec-authoring` forbids it; the structural outcome is what the spec should state.)

**If Stage 1 fails, stop.** Report what is missing. Issue a FAIL. Do not review quality.

### Stage 2 — Quality

Only after Stage 1 passes.

**For code:**
- **Correctness** — logic errors, edge cases, off-by-one, null handling, error messages.
- **Type predicate coverage** — for every user-defined type predicate (`value is T`), enumerate `T`'s required fields and confirm the guard checks each one. A predicate that validates a subset is a false assurance at the boundary it was added to protect — flag it as a defect, not a nit.
- **Security** — input validated at the boundary, no injection-prone string building, no dangerous eval/exec on input, no secrets in code, paths sanitised.
- **Principles** — does the change violate a named `engineering-principles` tenet? Cite the principle, not a preference.
- **Structure** — size, layer boundaries, rule-of-three duplication, composition. Apply the `code-quality` Part B thresholds. Pre-existing violations in untouched files are not findings; only flag if this change makes them worse.
- **Dead surface after a deletion** — when a change retires a subsystem but keeps its module as a re-homed helper, each remaining public function needs a *production* caller, not just a test. Grep each one across the source tree, excluding its own module and tests (`grep -rn <fn> <src>/ | grep -v <its-module>`); one reached only by its own unit test is dead surface masquerading as a helper, its passing test hiding the rot rather than justifying it. Delete it with its tests.
- **Port-time orphan** — when a change *lifts a module from another repo*, confirm production code in **this** repo imports it before the lift lands. Grep the source tree for an importer, excluding the module itself and tests (`grep -rn <module> <src>/ | grep -v <its-own-path>`); a lifted module reached only by its own tests, or by nothing, is dead on arrival — a class no later per-change reviewer will catch, because no future change touches the orphan. Wire it to a production caller in the same change or leave it out.
- **Misplaced pure helper** — in a repo whose CONTEXT designates a home for testable client logic (e.g. a `lib/` directory under a coverage ratchet), a *pure* function — no hooks, no JSX/render — declared inline inside a view or screen file, that a **second** view also needs, belongs in that home before approval, not copied screen-to-screen. The class hides per-change because each ticket touches one screen, so catch it at the moment of reuse: when this change adds or copies an inline pure helper a sibling screen already declares, move it to the designated `lib/` (under its ratchet) as part of this change. Grep the source for a sibling declaration before approving (`grep -rn <fn> <src>/ | grep -v <its-screen>`); the same pure helper declared in two screens is the signal.
- **"Mirrors/duplicates" admission comment** — a pure helper carrying a comment that it *mirrors*, *duplicates*, or must be *kept in sync with* a sibling is an explicit admission of duplication (`code-quality` Part B, "Extract on the third strike"): the author named the original, so the rule-of-three count no longer applies. Report an unextracted helper that carries such a comment as a **Medium** structural finding — the same tier as the same logic in 3+ places — regardless of how small each copy is; the admission is the trigger, not the size. The fix is to extract it to its shared home in this change.
- **Architecture watchlist** — in a repo whose `CONTEXT.md` declares an `architecture_watchlist`, compare the **actual diff** against `architecture_watchlist.files` (`git diff --name-only <integration-branch>...HEAD`, the integration branch from `CONTEXT.md` `branches.integration`; fall back to the working-tree diff when it is unknown — the mechanism is in `architecture` → *Architecture watchlist*). When the diff touches a watchlisted gravity-well file and *adds* inline state, orchestration, branching, or repeated rendering to it, the change must carry a `Watchlist trigger` outcome — a small behavior-preserving seam extraction, or a recorded deferral with a reason. A watchlisted file grown this way with **neither** recorded is a **Medium** structural finding: the gravity well got heavier and nothing was decided. A repo with no `architecture_watchlist` skips this check (it is a no-op).
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
- **Record reality on PASS — the as-built-record gate.** When the diff touches a **user-facing surface** (a screen, route, endpoint, CLI command, or any behaviour the as-built record documents — matched from the changed paths the same way the *Architecture watchlist* reads `git diff --name-only`), the review must either fold the matching **as-built-record** update into this change or record an **explicit deferral naming the reason**. A shipped behaviour change to such a surface with **neither** a record update **nor** a recorded deferral is a **FAIL** — the canonical record silently rots otherwise, a drift no later per-change reviewer catches because no future change re-touches the gap. The as-built record is `specs/features/<feature>.md` where the `feature_specs` layer is on, otherwise the design doc / `SPEC.md`; the same gate applies to it. Recording reality is the reviewer's job, not the builder's, written from what the diff actually does as the last commit before merge. When a surface's as-built record does not exist yet, the first ticket touching that surface creates it; a surface is not permitted to accumulate more than one shipped ticket without one — the record is where a gap between tickets becomes visible, and it cannot do that job retroactively (`spec-driven-development`).
- **Report:** a one-line verdict, Stage 1 result per criterion, Stage 2 findings by severity with the four parts each, the verification output, and a final PASS / FAIL.

## On a FAIL

Return the blocking findings to the builder and re-review. A second consecutive FAIL is a stop: escalate to the user rather than looping further.
